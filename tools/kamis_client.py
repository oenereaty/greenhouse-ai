"""KAMIS 농산물유통정보 가격 API 클라이언트.

토마토 당일/기간 도매가격을 조회합니다.
API 키 발급: https://www.kamis.or.kr → 회원가입 → API 활용신청
"""
import json
import os
import ssl
import warnings
from datetime import date, timedelta
from pathlib import Path
from statistics import mean

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context
from dotenv import load_dotenv

warnings.filterwarnings("ignore", message="Unverified HTTPS request")

load_dotenv(Path(__file__).parent.parent / ".env")

KAMIS_URL = "https://www.kamis.or.kr/service/price/xml.do"


class _LegacySSLAdapter(HTTPAdapter):
    """KAMIS 서버가 SHA1 MAC 암호(ECDHE-RSA-AES256-SHA)를 사용해
    Python 기본 SSL이 거부함 → SECLEVEL=0으로 우회."""
    def init_poolmanager(self, *a, **kw):
        ctx = create_urllib3_context()
        ctx.set_ciphers("DEFAULT@SECLEVEL=0")
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        kw["ssl_context"] = ctx
        super().init_poolmanager(*a, **kw)


def _session() -> requests.Session:
    s = requests.Session()
    s.mount("https://", _LegacySSLAdapter())
    return s

# 토마토 분류 코드
TOMATO_CATEGORY = "200"   # 채소류
TOMATO_ITEM     = "214"   # 토마토
TOMATO_KIND     = "01"    # 상품 (02=중품, 03=하품)

# 상/중/하 kindcode 매핑
GRADE_KINDCODES = {"상": "01", "중": "02", "하": "03"}
GRADE_UNIT = "4kg"   # KAMIS 토마토 기준 단위

# 지역 코드
# 2026-07 실측 확인: KAMIS 도매(02) 토마토 데이터가 실제로 나오는 지역코드는
# 이 5개뿐이다. 2300(인천 표기)은 도매 토마토 데이터가 없고, 2401은 인천이 아니라
# 광주다 — 예전 매핑이 틀려 있었다.
COUNTRY_CODES = {
    "서울가락": "1101",
    "부산":     "2100",
    "대구":     "2200",
    "광주":     "2401",
    "대전":     "2501",
}


def _get_creds() -> tuple[str, str]:
    key = os.getenv("KAMIS_API_KEY", "")
    api_id = os.getenv("KAMIS_API_ID", "")
    if not key or not api_id:
        raise RuntimeError(
            "KAMIS_API_KEY / KAMIS_API_ID가 .env에 설정되지 않았습니다.\n"
            "https://www.kamis.or.kr 에서 API 활용신청 후 .env에 입력하세요."
        )
    return key, api_id


def _period_params(key, api_id, start_day: str, end_day: str,
                   country: str, kind_code: str) -> dict:
    return {
        "action":             "periodProductList",
        "p_cert_key":         key,
        "p_cert_id":          api_id,
        "p_returntype":       "json",
        "p_itemcategorycode": TOMATO_CATEGORY,
        "p_itemcode":         TOMATO_ITEM,
        "p_kindcode":         kind_code,
        "p_startday":         start_day,
        "p_endday":           end_day,
        "p_countrycode":      country,
        "p_convert_kg_yn":    "N",
    }


def fetch_today_price(
    country_code: str | None = None,
    grade: str | None = None,
    kind_code: str = TOMATO_KIND,
) -> dict:
    """오늘(+어제) 토마토 도매가격 조회 — 전일 대비 포함.

    Returns:
        {"date", "item", "market", "grade", "price", "price_str",
         "dod_change", "source"}
    """
    key, api_id = _get_creds()
    country = country_code or os.getenv("KAMIS_COUNTRY_CODE", "1101")
    g = grade or os.getenv("KAMIS_GRADE", "1")
    today = date.today()
    # 이틀치 조회해 전일 대비 계산
    start = (today - timedelta(days=7)).isoformat()
    end = today.isoformat()

    resp = _session().get(
        KAMIS_URL,
        params=_period_params(key, api_id, start, end, country, kind_code),
        timeout=10,
    )
    resp.raise_for_status()
    return _parse_today(resp.text, country, g, today.isoformat())


def fetch_all_grades(country_code: str | None = None) -> dict:
    """상/중/하 3개 등급 도매가격 + 전월/전년/평년 비교 데이터 일괄 조회.

    Returns:
        {
          "상": {"price", "price_kg", "dod_change", "prev_month", "prev_year", "avg_year"},
          "중": {...},
          "하": {...},
          "date": "YYYY-MM-DD",
          "market": "서울가락",
          "unit": "4kg",
        }
    """
    key, api_id = _get_creds()
    country = country_code or os.getenv("KAMIS_COUNTRY_CODE", "1101")
    today = date.today()
    sess = _session()

    result = {
        "date":   today.isoformat(),
        "market": _MARKET_KOR.get(country, country),
        "unit":   GRADE_UNIT,
    }

    for grade_name, kc in GRADE_KINDCODES.items():
        try:
            # ── 현재 (최근 7일) ──────────────────────────────────────
            cur_rows = _fetch_rows(sess, key, api_id,
                                   (today - timedelta(days=7)).isoformat(),
                                   today.isoformat(), country, kc)
            avg_cur = sorted([r for r in cur_rows if r.get("countyname") == "평균"],
                             key=lambda x: x.get("regday", ""), reverse=True)
            pny_cur = sorted([r for r in cur_rows if r.get("countyname") == "평년"],
                             key=lambda x: x.get("regday", ""), reverse=True)

            price     = _safe_price(avg_cur[0]["price"]) if avg_cur else None
            price_kg  = round(price / 4, 0) if price else None
            prev_p    = _safe_price(avg_cur[1]["price"]) if len(avg_cur) > 1 else None
            dod       = (price - prev_p) if (price and prev_p) else None
            avg_year_p = _safe_price(pny_cur[0]["price"]) if pny_cur else None

            # ── 전월 (지난달 같은 기간) ──────────────────────────────
            m_start = (today.replace(day=1) - timedelta(days=1)).replace(day=max(1, today.day - 6))
            m_end   = today.replace(day=1) - timedelta(days=1)
            pm_rows = _fetch_rows(sess, key, api_id,
                                  m_start.isoformat(), m_end.isoformat(), country, kc)
            avg_pm  = [r for r in pm_rows if r.get("countyname") == "평균"]
            prev_month_p = _safe_price(
                sorted(avg_pm, key=lambda x: x.get("regday", ""), reverse=True)[0]["price"]
            ) if avg_pm else None

            # ── 전년 (1년 전 같은 기간) ──────────────────────────────
            y_end   = today.replace(year=today.year - 1)
            y_start = y_end - timedelta(days=6)
            py_rows = _fetch_rows(sess, key, api_id,
                                  y_start.isoformat(), y_end.isoformat(), country, kc)
            avg_py  = [r for r in py_rows if r.get("countyname") == "평균"]
            prev_year_p = _safe_price(
                sorted(avg_py, key=lambda x: x.get("regday", ""), reverse=True)[0]["price"]
            ) if avg_py else None

            result[grade_name] = {
                "price":       price,
                "price_kg":    int(price_kg) if price_kg else None,
                "price_str":   f"{price:,}" if price else "—",
                "price_kg_str":f"{int(price_kg):,}" if price_kg else "—",
                "dod_change":  dod,
                "prev_month":  prev_month_p,
                "prev_year":   prev_year_p,
                "avg_year":    avg_year_p,
            }
        except Exception as e:
            result[grade_name] = {
                "price": None, "price_kg": None,
                "price_str": "조회실패", "price_kg_str": "—",
                "dod_change": None, "prev_month": None,
                "prev_year": None, "avg_year": None,
                "error": str(e),
            }

    return result


def _fetch_rows(sess, key, api_id, start, end, country, kind_code) -> list[dict]:
    """Helper: fetch and flatten KAMIS rows for a given period."""
    params = _period_params(key, api_id, start, end, country, kind_code)
    resp = sess.get(KAMIS_URL, params=params, timeout=10)
    resp.raise_for_status()
    try:
        data  = json.loads(resp.text)
        items = data.get("data", {}).get("item", [])
        if isinstance(items, dict):
            items = [items]
        return [r for r in (items or []) if isinstance(r, dict)]
    except Exception:
        return []


def fetch_market_avg_for_period(start: date, end: date, grade: str = "중") -> list[dict]:
    """지정 기간(임의의 과거 포함) 동안 5개 주요 도매시장의 평균 경락가 비교.

    실시간 경매 아카이브(auction_archive.py)는 최근 며칠치만 있어 "작년",
    "몇 달 전" 같은 조회에는 못 쓴다 — 이 함수가 그 공백을 KAMIS로 메운다.
    단 KAMIS 도매(02) 토마토 데이터가 실제로 나오는 시장은 5개뿐이다(2026-07
    실측 확인, COUNTRY_CODES 참고) — 익산 등 나머지 시장은 이 함수로 조회 불가.
    """
    key, api_id = _get_creds()
    sess = _session()
    kind_code = GRADE_KINDCODES.get(grade, "02")
    results = []
    for market_name, code in COUNTRY_CODES.items():
        try:
            rows = _fetch_rows(sess, key, api_id, start.isoformat(), end.isoformat(), code, kind_code)
        except Exception:
            continue
        avg_rows = [r for r in rows if r.get("countyname") == "평균"]
        prices = [p for r in avg_rows if (p := _safe_price(r.get("price"))) is not None]
        if prices:
            results.append({"도매시장": market_name, "평균가": int(mean(prices)), "건수": len(prices)})
    results.sort(key=lambda x: x["평균가"], reverse=True)
    return results


def fetch_price_range(
    days: int = 7,
    country_code: str | None = None,
    grade: str | None = None,
    kind_code: str = TOMATO_KIND,
) -> list[dict]:
    """최근 N일 토마토 도매가격 시계열 조회."""
    key, api_id = _get_creds()
    country = country_code or os.getenv("KAMIS_COUNTRY_CODE", "1101")
    g = grade or os.getenv("KAMIS_GRADE", "1")
    end = date.today()
    start = end - timedelta(days=days - 1)

    resp = _session().get(
        KAMIS_URL,
        params=_period_params(key, api_id, start.isoformat(), end.isoformat(),
                              country, kind_code),
        timeout=10,
    )
    resp.raise_for_status()
    return _parse_period_response(resp.text, country, g)


_HISTORY_OFFSETS = [(0.5, "6개월전"), (1, "1년전"), (2, "2년전"),
                    (3, "3년전"), (4, "4년전"), (5, "5년전")]

# ---------------------------------------------------------------------------
# Static 5년 참고 데이터 (KAMIS_API_KEY 미설정 시 폴백)
#
# 서울·부산·대구·광주·대전 5개 도매시장의 월별 평균가(상품, 원/5kg).
# 사용자가 제공한 "토마토_도매_지역별_월별_5년_분석.xlsx"(KAMIS Open-API 수집본)에서
# 추출. 실시간 API가 아니므로 연도×월 평균값만 제공하며, 일 단위 변동은 반영하지 않는다.
# ---------------------------------------------------------------------------
_STATIC_MONTHLY_AVG: dict[int, dict[int, int]] = {
    2021: {1: 17900, 2: 15936, 3: 18615, 4: 17040, 5: 11315, 6: 9793,
           7: 11720, 8: 10963, 9: 13859, 10: 14708, 11: 19074, 12: 17968},
    2022: {1: 21046, 2: 19483, 3: 18409, 4: 14310, 5: 13143, 6: 11613,
           7: 15471, 8: 19302, 9: 23162, 10: 24682, 11: 17112, 12: 12596},
    2023: {1: 13502, 2: 18736, 3: 19133, 4: 17596, 5: 14000, 6: 14025,
           7: 16046, 8: 20434, 9: 31114, 10: 35605, 11: 23344, 12: 22749},
    2024: {1: 25653, 2: 29108, 3: 31610, 4: 27591, 5: 22271, 6: 14182,
           7: 13053, 8: 17482, 9: 27409, 10: 42210, 11: 30820, 12: 25232},
    2025: {1: 19172, 2: 20262, 3: 20886, 4: 19147, 5: 14319, 6: 12581,
           7: 15199, 8: 19587, 9: 24142, 10: 23311, 11: 27610, 12: 19275},
}
_STATIC_YEAR_MIN = min(_STATIC_MONTHLY_AVG)
_STATIC_YEAR_MAX = max(_STATIC_MONTHLY_AVG)


def _static_price_for(target: date) -> tuple[int, int, bool]:
    """target 날짜와 같은 달의 정적 참고가를 반환.

    Returns:
        (price, used_year, was_clamped) — used_year가 target.year와 다르면
        was_clamped=True (수집 범위 밖이라 가장 가까운 연도로 대체했다는 뜻).
    """
    year = min(max(target.year, _STATIC_YEAR_MIN), _STATIC_YEAR_MAX)
    price = _STATIC_MONTHLY_AVG[year][target.month]
    return price, year, year != target.year


def fetch_shipment_price_history_static(reference_date: date | None = None) -> list[dict]:
    """KAMIS API 없이도 동작하는 6개월전~5년전 출하가격 비교 (2021~2025 월평균 기반).

    fetch_shipment_price_history()와 동일한 출력 형식이며, 각 항목에
    "source": "static" 필드가 추가된다. 수집 범위(2021~2025) 밖의 연도는
    가장 가까운 연도의 같은 달 값으로 대체하고 "approximated": True로 표시한다.
    """
    today = reference_date or date.today()
    prices: dict[float, dict] = {}
    for offset_years, label in _HISTORY_OFFSETS:
        target = today - timedelta(days=round(offset_years * 365))
        price, used_year, clamped = _static_price_for(target)
        prices[offset_years] = {
            "label": label,
            "target_date": target.isoformat(),
            "actual_date": f"{used_year}-{target.month:02d}",
            "price": price,
            "approximated": clamped,
            "source": "static",
        }

    result = []
    for offset_years, label in _HISTORY_OFFSETS:
        entry = dict(prices[offset_years])
        prior = prices.get(offset_years + 1)
        if prior and prior["price"]:
            entry["pct_change"] = round((entry["price"] - prior["price"]) / prior["price"] * 100, 1)
        else:
            entry["pct_change"] = None
        result.append(entry)
    return result


def fetch_shipment_price_history(
    country_code: str | None = None,
    kind_code: str = TOMATO_KIND,
    window_days: int = 3,
) -> list[dict]:
    """오늘 기준 6개월전~5년전 도매가 비교 (농업ON 출하시기 지원 서비스 형식 참고).

    각 시점은 해당 날짜 ±window_days 이내의 가장 가까운 실측값을 사용한다.
    pct_change는 해당 시점보다 1년 더 과거 시점 대비 변화율("전년도 대비")이다.
    6개월전과 5년전은 비교 대상(1년 더 과거)이 없어 pct_change가 없다.
    """
    key, api_id = _get_creds()
    country = country_code or os.getenv("KAMIS_COUNTRY_CODE", "1101")
    sess = _session()
    today = date.today()

    prices: dict[float, dict] = {}
    for offset_years, label in _HISTORY_OFFSETS:
        target = today - timedelta(days=round(offset_years * 365))
        start = target - timedelta(days=window_days)
        end = target + timedelta(days=window_days)
        rows = _fetch_rows(sess, key, api_id, start.isoformat(), end.isoformat(),
                           country, kind_code)
        avg_rows = [r for r in rows if r.get("countyname") == "평균"]

        def _dist(r):
            iso = _regday_to_iso(r.get("yyyy", str(target.year)), r.get("regday", ""))
            try:
                return abs((date.fromisoformat(iso) - target).days)
            except ValueError:
                return 999
        avg_rows.sort(key=_dist)

        # KAMIS 서버가 오래된 기간(대략 1~2년 이상 과거)을 요청하면 날짜 필터를
        # 무시하고 최신 연도 데이터를 그대로 반환하는 경우가 실측 확인됨(예:
        # 5년전 조회에도 작년 데이터가 옴). 반환된 날짜가 실제로 요청 창(±window_days)
        # 안에 있는지 검증해, 아니면 "데이터 없음"으로 처리한다 — 라벨과 실제 연도가
        # 다른 값을 그대로 노출하면 발표 등에서 사실과 다른 수치가 될 수 있다.
        if avg_rows and _dist(avg_rows[0]) <= window_days:
            nearest = avg_rows[0]
            iso = _regday_to_iso(nearest.get("yyyy", str(target.year)), nearest.get("regday", ""))
            prices[offset_years] = {"label": label, "target_date": target.isoformat(),
                                    "actual_date": iso, "price": _safe_price(nearest.get("price")),
                                    "source": "kamis_api"}
        else:
            prices[offset_years] = {"label": label, "target_date": target.isoformat(),
                                    "actual_date": None, "price": None, "source": "kamis_api"}

    result = []
    for offset_years, label in _HISTORY_OFFSETS:
        entry = dict(prices[offset_years])
        prior_offset = offset_years + 1
        prior = prices.get(prior_offset)
        if entry["price"] is not None and prior and prior["price"]:
            entry["pct_change"] = round((entry["price"] - prior["price"]) / prior["price"] * 100, 1)
        else:
            entry["pct_change"] = None
        result.append(entry)
    return result


# ---------------------------------------------------------------------------
# Response parsers
# ---------------------------------------------------------------------------

_GRADE_KOR = {"1": "상", "2": "중", "3": "하"}
_MARKET_KOR = {v: k for k, v in COUNTRY_CODES.items()}


def _safe_price(val) -> int | None:
    """Convert KAMIS price string to int (removes commas, returns None on error)."""
    try:
        return int(str(val).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _items_from_response(text: str) -> list[dict]:
    """Parse KAMIS periodProductList JSON → list of item dicts."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise ValueError(f"KAMIS 응답 파싱 실패: {text[:200]}")
    error = data.get("data", {}).get("error_code", "")
    if error and error != "000":
        raise ValueError(f"KAMIS API 오류: {error}")
    items = data.get("data", {}).get("item") or []
    if isinstance(items, dict):
        items = [items]
    return items


def _regday_to_iso(yyyy: str, regday: str) -> str:
    """Convert KAMIS 'MM/DD' + yyyy → 'YYYY-MM-DD'."""
    try:
        mm, dd = regday.split("/")
        return f"{yyyy}-{mm.zfill(2)}-{dd.zfill(2)}"
    except Exception:
        return regday


def _parse_today(text: str, country: str, grade: str, today_iso: str) -> dict:
    """Extract the most recent actual price and compute DoD change."""
    items = _items_from_response(text)
    # Keep only 평균 rows (filter out 평년 / normals)
    avg_items = [r for r in items if r.get("countyname") == "평균"]
    if not avg_items:
        return {
            "date": today_iso, "item": "토마토",
            "market": _MARKET_KOR.get(country, country),
            "grade": _GRADE_KOR.get(grade, grade),
            "price": None, "price_str": "데이터 없음",
            "dod_change": None, "source": "KAMIS",
        }

    # Sort by date descending, take two most recent
    def _iso(r): return _regday_to_iso(r.get("yyyy", "2026"), r.get("regday", ""))
    avg_items.sort(key=_iso, reverse=True)
    latest = avg_items[0]
    prev   = avg_items[1] if len(avg_items) > 1 else None

    price  = _safe_price(latest.get("price"))
    prev_p = _safe_price(prev.get("price")) if prev else None
    change = (price - prev_p) if (price is not None and prev_p is not None) else None

    return {
        "date":       _iso(latest),
        "item":       "토마토",
        "market":     _MARKET_KOR.get(country, country),
        "grade":      _GRADE_KOR.get(grade, grade),
        "price":      price,
        "price_str":  f"{price:,}원" if price else "—",
        "dod_change": change,
        "source":     "KAMIS",
    }


def _parse_period_response(text: str, country: str, grade: str) -> list[dict]:
    items = _items_from_response(text)
    avg_items = [r for r in items if r.get("countyname") == "평균"]
    result = []
    for row in avg_items:
        price = _safe_price(row.get("price"))
        iso   = _regday_to_iso(row.get("yyyy", "2026"), row.get("regday", ""))
        result.append({
            "date":   iso,
            "price":  price,
            "market": _MARKET_KOR.get(country, country),
            "grade":  _GRADE_KOR.get(grade, grade),
        })
    return sorted(result, key=lambda x: x["date"])


# ---------------------------------------------------------------------------
# Fallback: dummy data when no API key
# ---------------------------------------------------------------------------

def dummy_price() -> dict:
    """Return a clearly marked placeholder when KAMIS key is not configured."""
    return {
        "date":       date.today().isoformat(),
        "item":       "토마토",
        "unit":       "10kg",
        "market":     "—",
        "grade":      "상",
        "price":      None,
        "price_str":  "API 키 미설정",
        "dod_change": None,
        "source":     "KAMIS (미연결)",
    }


if __name__ == "__main__":
    try:
        p = fetch_today_price()
        print(f"[{p['date']}] 토마토({p['grade']}) @ {p['market']}: {p['price_str']}")
        if p["dod_change"] is not None:
            arrow = "▲" if p["dod_change"] > 0 else ("▼" if p["dod_change"] < 0 else "─")
            print(f"  전일 대비: {arrow} {abs(p['dod_change']):,}원")
    except RuntimeError as e:
        print(f"[KAMIS] {e}")
