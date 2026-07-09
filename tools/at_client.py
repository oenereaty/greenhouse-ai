"""
at_client.py
공공데이터포털 aT 전국 공영도매시장 실시간 경매정보 API 클라이언트
API ID : 15141808
Base URL: https://apis.data.go.kr/B552845/katRealTime2

키 발급: https://www.data.go.kr/data/15141808/openapi.do → 활용신청(자동승인)
.env에 AT_API_KEY=발급받은키 추가
"""
import os
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path
from statistics import mean

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

BASE_URL = "https://apis.data.go.kr/B552845/katRealTime2/trades2"

# 실제 거래 공판장 필터 — 전국 공영도매시장 중 토마토 경매가 실측되는 16개
# (2026-07 실측 스윕 확인: 각 시장에 완숙토마토 경락 + 출하지(산지) 데이터 존재)
# 시장명 LIKE 필터라 "대전"→대전노은·대전오정, "부산"→부산반여·부산엄궁,
# "광주"→광주각화·광주서부, "인천"→인천남촌·인천삼산처럼 도시별 복수 공판장이 함께 잡힌다.
DEFAULT_MARKET_KW = [
    "가락", "강서", "구리", "수원", "안양", "안산", "인천",
    "대전", "청주", "천안", "전주", "익산",
    "광주", "부산", "대구", "울산",
]
DEFAULT_ITEM_KW   = ["토마토"]

# app.py 호환용 (KAMIS의 GRADE_KINDCODES 대체)
GRADE_KINDCODES = {"상": "상", "중": "중", "하": "하"}


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------

def _get_key() -> str:
    raw = os.getenv("AT_API_KEY", "")
    if not raw:
        raise RuntimeError(
            "AT_API_KEY가 .env에 설정되지 않았습니다.\n"
            "https://www.data.go.kr/data/15141808/openapi.do 에서 활용신청 후 .env에 입력하세요."
        )
    return urllib.parse.unquote(raw)


class _AtRateLimited(Exception):
    """요청 한도 초과/서버 무응답으로 쿨다운 중임을 알리는 신호용 예외.

    RuntimeError를 쓰지 않는 이유: 호출부(_find_recent 등)가 RuntimeError만
    골라서 상위로 재전파(설정 오류를 숨기지 않기 위함)하므로, 여기서 RuntimeError를
    쓰면 UI가 깨진다. 이 예외는 일반 Exception이라 기존 "당일 데이터 없음"과 같은
    방식으로 조용히 삼켜져 화면은 안전하게 빈 값으로 표시된다.
    """


# 429(요청 한도 초과)뿐 아니라 커넥션 타임아웃(게이트웨이가 아예 응답하지 않는
# 경우 — 2026-07 실측: 한도 소진 후 429 대신 ConnectTimeout으로 나타남)도 같은
# 쿨다운으로 취급한다. 한 번이라도 이런 실패가 나면 이 시각까지 실제 네트워크
# 요청 없이 즉시 실패시킨다. 시장 수가 많아진 뒤로는 매 요청을 그대로 흘려보내면
# 한 화면 로딩에 수십 초씩 걸리므로, 쿨다운으로 응답을 즉시 반환해 UI가
# 멈추지 않게 한다.
_RATE_LIMIT_COOLDOWN_SEC = 90
_rate_limited_until = 0.0


def _fetch_page(
    saledate: str,
    page: int,
    market_kw: str = "",
    item_kw: str = "",
    num_rows: int = 100,
) -> dict:
    """단일 페이지 조회. 시장명·품목명을 서버 사이드 LIKE 필터로 전달."""
    global _rate_limited_until
    if time.time() < _rate_limited_until:
        raise _AtRateLimited("AT API 요청 한도 초과/무응답 — 쿨다운 중")

    params: dict = {
        "serviceKey":              _get_key(),
        "pageNo":                  page,
        "numOfRows":               num_rows,
        "returnType":              "json",
        "cond[trd_clcln_ymd::EQ]": saledate,
    }
    if market_kw:
        params["cond[whsl_mrkt_nm::LIKE]"] = market_kw
    if item_kw:
        params["cond[corp_gds_item_nm::LIKE]"] = item_kw

    try:
        resp = requests.get(BASE_URL, params=params, timeout=8)
    except requests.exceptions.RequestException as e:
        _rate_limited_until = time.time() + _RATE_LIMIT_COOLDOWN_SEC
        raise _AtRateLimited(f"AT API 연결 실패: {e}") from e

    if resp.status_code == 429:
        _rate_limited_until = time.time() + _RATE_LIMIT_COOLDOWN_SEC
        raise _AtRateLimited("AT API 요청 한도 초과 (429)")
    if resp.status_code in (401, 403):
        raise RuntimeError(f"AT API 인증 실패 ({resp.status_code}): 키 확인 또는 활성화 대기 필요")
    resp.raise_for_status()
    return resp.json()


def _fetch_one_combo(saledate: str, mkt: str, itm: str) -> list[dict]:
    """단일 (시장, 품목) 조합의 전 페이지를 가져옴."""
    first = _fetch_page(saledate, 1, market_kw=mkt, item_kw=itm)
    body  = first.get("response", {}).get("body", {})
    total = int(body.get("totalCount", 0) or 0)
    if total == 0:
        return []
    items = _to_list(body.get("items", {}).get("item"))
    pages = (total + 99) // 100
    for p in range(2, pages + 1):
        more_body = _fetch_page(saledate, p, market_kw=mkt, item_kw=itm).get("response", {}).get("body", {})
        items.extend(_to_list(more_body.get("items", {}).get("item")))
    return items


def _fetch_all_filtered(
    saledate: str,
    market_kws: list[str],
    item_kws: list[str],
) -> list[dict]:
    """시장·품목 조합을 병렬로 요청해 합산.

    item_kw="토마토"는 aT 서버의 LIKE 검색 특성상 "방울토마토"도 함께 매칭되므로,
    완숙토마토 포커스를 위해 gds_mclsf_nm(품목 분류)이 정확히 "토마토"인 행만 남긴다
    (방울토마토·대추방울 등은 제외).
    """
    combos = [(mkt, itm) for mkt in market_kws for itm in item_kws]
    all_items: list[dict] = []
    with ThreadPoolExecutor(max_workers=len(combos)) as ex:
        futures = {ex.submit(_fetch_one_combo, saledate, mkt, itm): (mkt, itm) for mkt, itm in combos}
        for fut in as_completed(futures):
            result = fut.result()  # RuntimeError는 그대로 전파
            all_items.extend(result)
    if any("토마토" in itm and "방울" not in itm for itm in item_kws):
        all_items = [i for i in all_items if i.get("gds_mclsf_nm") == "토마토"]
    return all_items


def _to_list(obj) -> list:
    if obj is None:
        return []
    return [obj] if isinstance(obj, dict) else list(obj)


def _price_per_kg(row: dict) -> float | None:
    """경락가 ÷ 단위수량 = kg당 가격."""
    try:
        prc  = float(str(row.get("scsbd_prc", "0")).replace(",", ""))
        uqty = float(str(row.get("unit_qty",  "0")).replace(",", ""))
        if prc > 0 and uqty > 0:
            return prc / uqty
    except (ValueError, TypeError):
        pass
    return None


def _compute_grades(rows: list[dict]) -> dict[str, int | None]:
    """낙찰가 목록을 상/중/하 3등분해 4kg 기준 평균가 반환."""
    prices = sorted(p for r in rows if (p := _price_per_kg(r)) is not None)
    if not prices:
        return {"상": None, "중": None, "하": None}
    n   = len(prices)
    t1  = max(n // 3, 1)
    t2  = max(2 * n // 3, t1)
    bot = prices[:t1]
    mid = prices[t1:t2] if t2 > t1 else prices
    top = prices[t2:]   if n > t2  else prices[-1:]
    return {
        "상": int(mean(top) * 4),
        "중": int(mean(mid) * 4),
        "하": int(mean(bot) * 4),
    }


def _find_recent(
    base: date,
    market_kws: list[str],
    item_kws: list[str],
    max_back: int = 7,
) -> tuple[date | None, list[dict]]:
    """base 날짜부터 max_back일까지 소급해 데이터 있는 최근 날 반환.

    실시간 API는 최근 약 30일만 보관하므로(2026-07 실측 확인), 30일 이전을
    조회하면 max_back일 전부가 항상 빈 응답이다. 시장 수가 늘수록(현재 16개)
    "찾을 때까지 하루씩 순차 재시도"가 그대로 배수로 느려지므로, 날짜들을
    병렬로 동시에 조회하고 그중 가장 최신 날짜를 채택한다.
    """
    days = [base - timedelta(days=offset) for offset in range(max_back)]
    results: dict[date, list[dict]] = {}
    # 하루당 이미 시장 수(현재 16개)만큼 내부 병렬 요청이 나가므로, 날짜 축
    # 동시성은 낮게 잡아 서버에 순간적으로 과도한 동시 요청이 몰리지 않게 한다.
    with ThreadPoolExecutor(max_workers=min(max_back, 4)) as ex:
        futures = {ex.submit(_fetch_all_filtered, d.isoformat(), market_kws, item_kws): d for d in days}
        for fut, d in futures.items():
            try:
                items = fut.result()
            except RuntimeError:
                raise
            except Exception:
                items = []
            if items:
                results[d] = items
    if not results:
        return None, []
    latest = max(results)
    return latest, results[latest]


def _empty_grade() -> dict:
    return {
        "price": None, "price_kg": None,
        "price_str": "—", "price_kg_str": "—",
        "dod_change": None, "prev_month": None,
        "prev_year": None, "avg_year": None,
    }


# 표본 수와 무관하게 항상 적용되는 절대 상한/하한 — 토마토 단량(5~10kg 상자)당
# 경락가가 현실적으로 벗어날 수 없는 범위. IQR은 표본이 4건 미만이면 계산 자체가
# 불가능해 판정을 건너뛰므로(예: 거래가 1~3건뿐인 이른 시간대), 자릿수가 잘못
# 입력된 값(예: 8,000,200원)이 그대로 최고가/평균에 반영되는 것을 막는 최후 방어선이다.
_ABS_MIN_PLAUSIBLE = 100
_ABS_MAX_PLAUSIBLE = 200_000


def _outlier_bounds(values: list[float]) -> tuple[float | None, float | None]:
    """IQR 기준 이상값 경계. 표본이 적으면 절대 상하한만 적용한다."""
    if len(values) < 4:
        return _ABS_MIN_PLAUSIBLE, _ABS_MAX_PLAUSIBLE
    xs = sorted(values)

    def percentile(p: float) -> float:
        pos = (len(xs) - 1) * p
        lo = int(pos)
        hi = min(lo + 1, len(xs) - 1)
        frac = pos - lo
        return xs[lo] * (1 - frac) + xs[hi] * frac

    q1 = percentile(0.25)
    q3 = percentile(0.75)
    iqr = q3 - q1
    if iqr <= 0:
        return _ABS_MIN_PLAUSIBLE, _ABS_MAX_PLAUSIBLE
    # IQR 경계와 절대 상하한 중 더 엄격한(=더 좁은) 쪽을 취한다 — 통계적으로는
    # "정상"이어도 절대 범위를 벗어나면 이상값으로, 반대로 IQR이 더 타이트하면
    # 그 값을 그대로 쓴다.
    low = max(q1 - 1.5 * iqr, _ABS_MIN_PLAUSIBLE)
    high = min(q3 + 1.5 * iqr, _ABS_MAX_PLAUSIBLE)
    return low, high


# ---------------------------------------------------------------------------
# 공개 API (kamis_client.py 드롭인 대체)
# ---------------------------------------------------------------------------

def fetch_all_grades(
    market_keywords: list[str] | None = None,
    item_keywords: list[str] | None = None,
) -> dict:
    """당일 경락가를 상/중/하로 분류해 반환.

    Returns:
        {
          "상": {"price", "price_kg", "price_str", "price_kg_str",
                 "dod_change", "prev_month", "prev_year", "avg_year"},
          "중": {...}, "하": {...},
          "date": "YYYY-MM-DD", "market": str, "unit": "4kg",
        }
    """
    mkt_kw  = market_keywords or DEFAULT_MARKET_KW
    item_kw = item_keywords   or DEFAULT_ITEM_KW
    today   = date.today()

    # 실시간 API는 최근 약 30일만 보관한다(2026-07 실측 확인). 365일 전(prev_year)
    # 조회는 구조적으로 항상 빈 응답이라 매번 요청만 낭비하므로 아예 호출하지 않는다
    # (일일 호출 한도가 유한한 공공 API라 특히 중요). 30일 전(prev_month)은 보관
    # 경계선이라 여러 날짜를 재시도할 가치가 있지만 max_back을 줄여 낭비를 최소화한다.
    with ThreadPoolExecutor(max_workers=3) as ex:
        f_today = ex.submit(_find_recent, today,                    mkt_kw, item_kw)
        f_prev  = ex.submit(_find_recent, today - timedelta(1),     mkt_kw, item_kw)
        f_pm    = ex.submit(_find_recent, today - timedelta(30),    mkt_kw, item_kw, 3)
        actual, rows = f_today.result()
        _, rows_prev = f_prev.result()
        _, rows_pm   = f_pm.result()

    if not actual:
        # 실시간 API가 오늘 데이터를 못 찾았다(일일 호출 한도 초과 포함) — 이미 우리가
        # archive_ledger로 저장해둔 당일 원자료가 있으면 그걸로 대체 계산한다.
        from tools.auction_archive import grade_avg_for_date
        archived = grade_avg_for_date(today)
        if archived:
            result: dict = {"date": today.isoformat(), "market": "아카이브(오늘 저장분)", "unit": "4kg"}
            for gn in ("상", "중", "하"):
                p = archived[gn]
                pk = (p // 4) if p else None
                result[gn] = {
                    "price": p, "price_kg": pk,
                    "price_str": f"{p:,}" if p else "—",
                    "price_kg_str": f"{pk:,}" if pk else "—",
                    "dod_change": None, "prev_month": None, "prev_year": None, "avg_year": None,
                }
            return result
        empty = {gn: _empty_grade() for gn in ("상", "중", "하")}
        return {"date": today.isoformat(), "market": "—", "unit": "4kg", **empty}

    g_today = _compute_grades(rows)
    g_prev  = _compute_grades(rows_prev)
    g_pm    = _compute_grades(rows_pm)

    _mkts    = list(dict.fromkeys(r.get("whsl_mrkt_nm", "") for r in rows if r.get("whsl_mrkt_nm")))
    mkt_name = "·".join(_mkts) if _mkts else "공판장"

    result: dict = {"date": actual.isoformat(), "market": mkt_name, "unit": "4kg"}
    for gn in ("상", "중", "하"):
        p   = g_today[gn]
        pp  = g_prev[gn]
        pk  = (p // 4) if p else None
        result[gn] = {
            "price":        p,
            "price_kg":     pk,
            "price_str":    f"{p:,}"  if p  else "—",
            "price_kg_str": f"{pk:,}" if pk else "—",
            "dod_change":   (p - pp) if (p and pp) else None,
            "prev_month":   g_pm[gn],
            # 실시간 API 보관기간(약 30일) 밖이라 항상 조회 불가 — 요청 낭비를 막기 위해
            # 아예 호출하지 않고 고정 None으로 둔다. 장기 이력 비교는 /prices/history-long 사용.
            "prev_year":    None,
            "avg_year":     None,
        }
    return result


def fetch_grades_by_markets(
    market_keywords: list[str] | None = None,
    item_keywords: list[str] | None = None,
) -> list[dict]:
    """시장별 경락가를 개별 조회해 리스트로 반환.

    Returns:
        [{"market": "익산공판장", "date": ..., "상": {...}, "중": {...}, "하": {...}}, ...]
    """
    mkt_kw  = market_keywords or DEFAULT_MARKET_KW
    item_kw = item_keywords   or DEFAULT_ITEM_KW
    today   = date.today()
    results = []

    with ThreadPoolExecutor(max_workers=len(mkt_kw) * 2) as ex:
        futures = {
            ex.submit(_find_recent, today, [mkt], item_kw): mkt
            for mkt in mkt_kw
        }
        for fut, mkt in futures.items():
            actual, rows = fut.result()
            if not actual or not rows:
                continue
            g = _compute_grades(rows)
            mkts = list(dict.fromkeys(r.get("whsl_mrkt_nm", "") for r in rows if r.get("whsl_mrkt_nm")))
            mkt_name = "·".join(mkts) if mkts else mkt
            entry: dict = {"market": mkt_name, "date": actual.isoformat(), "unit": "4kg"}
            for gn in ("상", "중", "하"):
                p  = g[gn]
                pk = (p // 4) if p else None
                entry[gn] = {
                    "price":        p,
                    "price_kg":     pk,
                    "price_str":    f"{p:,}"  if p  else "—",
                    "price_kg_str": f"{pk:,}" if pk else "—",
                }
            results.append(entry)

    results.sort(key=lambda x: x["market"])
    return results


def fetch_today_price(
    market_keywords: list[str] | None = None,
    item_keywords: list[str] | None = None,
) -> dict:
    """오늘 경락가 (중품 기준) 조회."""
    data = fetch_all_grades(market_keywords, item_keywords)
    mid  = data.get("중", {})
    p    = mid.get("price")
    return {
        "date":       data["date"],
        "item":       (item_keywords or DEFAULT_ITEM_KW)[0],
        "market":     data["market"],
        "grade":      "중",
        "price":      p,
        "price_str":  f"{p:,}원" if p else "데이터 없음",
        "dod_change": mid.get("dod_change"),
        "source":     "aT 공판장 경락가격",
    }


def fetch_price_range(
    days: int = 7,
    grade: str = "중",
    kind_code: str | None = None,
    market_keywords: list[str] | None = None,
    item_keywords: list[str] | None = None,
) -> list[dict]:
    """최근 N일 일별 경락가 시계열."""
    mkt_kw  = market_keywords or DEFAULT_MARKET_KW
    item_kw = item_keywords   or DEFAULT_ITEM_KW
    _grade  = kind_code if kind_code in ("상", "중", "하") else grade

    end   = date.today()
    start = end - timedelta(days=days - 1)
    all_days = [start + timedelta(days=i) for i in range((end - start).days + 1)]

    def _one(d: date) -> dict | None:
        try:
            items = _fetch_all_filtered(d.isoformat(), mkt_kw, item_kw)
        except Exception:
            return None
        if not items:
            return None
        p = _compute_grades(items).get(_grade)
        if not p:
            return None
        return {
            "date":   d.isoformat(),
            "price":  p,
            "market": items[0].get("whsl_mrkt_nm", "공판장"),
            "grade":  _grade,
        }

    result: list[dict] = []
    # 하루당 시장 수(현재 16개)만큼 내부 병렬 요청이 이미 나가므로, 날짜 축
    # 동시성은 낮게 잡아 서버에 순간적으로 과도한 동시 요청이 몰리지 않게 한다.
    with ThreadPoolExecutor(max_workers=min(len(all_days), 4)) as ex:
        futures = [ex.submit(_one, d) for d in all_days]
        for fut in as_completed(futures):
            r = fut.result()
            if r:
                result.append(r)

    result.sort(key=lambda x: x["date"])
    return result


def fetch_price_range_by_markets(
    days: int = 14,
    grade: str = "중",
    kind_code: str | None = None,
    market_keywords: list[str] | None = None,
    item_keywords: list[str] | None = None,
) -> list[dict]:
    """최근 N일, 시장별 일별 경락가 시계열 (시장 간 비교용).

    각 (시장 × 날짜)를 개별 필터로 조회해 시장별 라인을 구성한다.
    fetch_price_range()가 전 시장을 합산하는 것과 달리, 시장별로 분리된다.

    Returns:
        [{"date": "YYYY-MM-DD", "market": 시장명, "price": 4kg가, "grade": 등급}, ...]
    """
    mkt_kw  = market_keywords or DEFAULT_MARKET_KW
    item_kw = item_keywords   or DEFAULT_ITEM_KW
    _grade  = kind_code if kind_code in ("상", "중", "하") else grade

    end    = date.today()
    dates  = [end - timedelta(days=i) for i in range(days)]
    combos = [(mkt, d) for mkt in mkt_kw for d in dates]

    def _one(mkt: str, d: date) -> dict | None:
        try:
            items = _fetch_all_filtered(d.isoformat(), [mkt], item_kw)
        except Exception:
            return None
        if not items:
            return None
        p = _compute_grades(items).get(_grade)
        if not p:
            return None
        name = items[0].get("whsl_mrkt_nm") or mkt
        return {"date": d.isoformat(), "market": name, "price": p, "grade": _grade}

    result: list[dict] = []
    # 시장 수 확대(16개) 이후 combos가 커져(시장×일수) 기존 max_workers=8은
    # 병목이 되므로 상향한다. 각 요청은 단일 (시장,날짜) 조합이라 서버 부담은
    # 동시 접속 수에 비례할 뿐 요청당 무게가 크지 않다.
    with ThreadPoolExecutor(max_workers=min(len(combos), 16)) as ex:
        futures = [ex.submit(_one, mkt, d) for mkt, d in combos]
        for fut in as_completed(futures):
            r = fut.result()
            if r:
                result.append(r)

    result.sort(key=lambda x: (x["market"], x["date"]))
    return result


def fetch_auction_ledger(
    market_keywords: list[str] | None = None,
    item_keywords: list[str] | None = None,
) -> dict:
    """오늘(최근) 실시간 경매 원장 + 최소/평균/최대 통계.

    aT '실시간 경매현황' 표와 동일한 컬럼 구성으로 낱건(경매 1건씩)을 반환.

    Returns:
        {
          "date": "YYYY-MM-DD" | None,
          "rows": [{거래일자, 경락일시, 도매시장, 법인, 매매구분, 부류,
                    품목, 품종, 출하지, 단량, 수량, 단량당 경락가(원), 등급}, ...],
          "stats": {"min", "max", "avg", "count"},   # 단량당 경락가 기준
        }

    등급(특/상/중/하)은 aT 원자료에 공식 등급 코드가 없어 당일 낙찰가를
    4등분(quartile)한 근사값이다.
    """
    mkt_kw  = market_keywords or DEFAULT_MARKET_KW
    item_kw = item_keywords   or DEFAULT_ITEM_KW
    actual, rows = _find_recent(date.today(), mkt_kw, item_kw)

    empty_stats = {"min": None, "max": None, "avg": None, "count": 0}
    if not actual or not rows:
        return {"date": None, "rows": [], "stats": empty_stats}

    def _num(v) -> str:
        try:
            return f"{float(str(v).replace(',', '')):g}"
        except (ValueError, TypeError):
            return str(v or "")

    ledger: list[dict] = []
    prices: list[float] = []
    for r in rows:
        try:
            prc = float(str(r.get("scsbd_prc", "0")).replace(",", ""))
        except (ValueError, TypeError):
            prc = None
        if prc and prc > 0:
            prices.append(prc)

        unit = f'{_num(r.get("unit_qty"))}{r.get("unit_nm", "")} {r.get("pkg_nm", "")}'.strip()
        ledger.append({
            "거래일자":          r.get("trd_clcln_ymd", ""),
            "경락일시":          r.get("scsbd_dt", ""),
            "도매시장":          r.get("whsl_mrkt_nm", ""),
            "법인":             r.get("corp_nm", ""),
            "매매구분":          r.get("trd_se", ""),
            "부류":             r.get("gds_lclsf_nm", ""),
            "품목":             r.get("gds_mclsf_nm") or r.get("corp_gds_item_nm", ""),
            "품종":             r.get("corp_gds_vrty_nm") or r.get("gds_sclsf_nm", ""),
            "출하지":            r.get("plor_nm", ""),
            "단량":             unit,
            "수량":             _num(r.get("qty")),
            "단량당 경락가(원)":  int(prc) if prc else None,
        })

    # 단량당 경락가 내림차순 (aT 기본 정렬과 동일)
    ledger.sort(key=lambda x: (x["단량당 경락가(원)"] or 0), reverse=True)

    # 등급(특/상/중/하) — aT 원자료에 공식 등급 코드가 없어 낙찰가 4등분 근사값으로 표기
    n = len(ledger)
    if n:
        q1, q2, q3 = max(n // 4, 1), max(n // 2, 1), max(3 * n // 4, 1)
        for i, row in enumerate(ledger):
            if i < q1:
                row["등급"] = "특"
            elif i < q2:
                row["등급"] = "상"
            elif i < q3:
                row["등급"] = "중"
            else:
                row["등급"] = "하"

    low, high = _outlier_bounds(prices)
    normal_prices: list[float] = []
    outlier_count = 0
    for row in ledger:
        price = row.get("단량당 경락가(원)")
        is_outlier = (
            price is not None
            and low is not None
            and high is not None
            and (float(price) < low or float(price) > high)
        )
        row["이상값"] = bool(is_outlier)
        if is_outlier:
            outlier_count += 1
        elif price:
            normal_prices.append(float(price))

    group_map: dict[tuple[str, str], list[float]] = {}
    market_map: dict[str, list[float]] = {}
    origin_map: dict[str, list[float]] = {}
    for row in ledger:
        if row.get("이상값"):
            continue
        price = row.get("단량당 경락가(원)")
        if not price:
            continue
        market = row.get("도매시장") or "시장 미상"
        origin = row.get("출하지") or "출하지 미상"
        group_map.setdefault((origin, market), []).append(float(price))
        market_map.setdefault(market, []).append(float(price))
        origin_map.setdefault(origin, []).append(float(price))

    market_avg = {k: mean(v) for k, v in market_map.items() if v}
    origin_avg = {k: mean(v) for k, v in origin_map.items() if v}
    total_avg = mean(normal_prices) if normal_prices else (mean(prices) if prices else None)
    origin_market = []
    for (origin, market), vals in group_map.items():
        if len(vals) < 2:
            continue
        avg_price = mean(vals)
        origin_market.append({
            "출하지": origin,
            "도매시장": market,
            "평균가": int(avg_price),
            "건수": len(vals),
            "시장평균대비": int(avg_price - market_avg.get(market, avg_price)),
            "전체평균대비": int(avg_price - total_avg) if total_avg else None,
            "산지평균대비": int(avg_price - origin_avg.get(origin, avg_price)),
        })
    origin_market.sort(key=lambda x: (x["평균가"], x["건수"]), reverse=True)

    stats = {
        "min":   int(min(normal_prices)) if normal_prices else (int(min(prices)) if prices else None),
        "max":   int(max(normal_prices)) if normal_prices else (int(max(prices)) if prices else None),
        "avg":   int(mean(normal_prices)) if normal_prices else (int(mean(prices)) if prices else None),
        "count": len(ledger),
        "outlier_count": outlier_count,
        "avg_basis_count": len(normal_prices),
    }
    return {
        "date": actual.isoformat(),
        "rows": ledger,
        "stats": stats,
        "origin_market": origin_market[:12],
    }


def dummy_price() -> dict:
    """API 키 미설정 또는 오류 시 반환할 빈 데이터."""
    return {
        "date":       date.today().isoformat(),
        "item":       "토마토",
        "unit":       "4kg",
        "market":     "—",
        "grade":      "중",
        "price":      None,
        "price_str":  "API 키 미설정",
        "dod_change": None,
        "source":     "aT 공판장 (미연결)",
    }


# ---------------------------------------------------------------------------
# 단독 실행 테스트
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    try:
        p = fetch_today_price()
        print(f"[{p['date']}] {p['item']}(중) @ {p['market']}: {p['price_str']}")
        if p["dod_change"] is not None:
            arrow = "▲" if p["dod_change"] > 0 else ("▼" if p["dod_change"] < 0 else "─")
            print(f"  전일 대비: {arrow} {abs(p['dod_change']):,}원")
        kgd = fetch_all_grades()
        for gn in ("상", "중", "하"):
            g = kgd[gn]
            print(f"  {gn}품: {g['price_str']}원/4kg  ({g['price_kg_str']}원/kg)")
    except RuntimeError as e:
        print(f"[AT] {e}")
