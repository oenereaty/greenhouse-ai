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
COUNTRY_CODES = {
    "서울가락": "1101",
    "부산":     "2100",
    "대구":     "2200",
    "광주":     "2300",
    "인천":     "2401",
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
