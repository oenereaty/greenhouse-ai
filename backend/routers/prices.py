"""가격 정보 탭 — 경매현황(실시간 원장+시세판+시장비교+과거비교) + 시장 동향 브리핑."""
import numpy as np
from fastapi import APIRouter
from pydantic import BaseModel

from backend import jobs
from backend.cache import cached
from tools.at_client import (
    fetch_all_grades, fetch_auction_ledger, fetch_grades_by_markets,
    fetch_price_range, fetch_price_range_by_markets, fetch_today_price,
)
from tools.kamis_client import fetch_shipment_price_history, fetch_shipment_price_history_static
from tools.price_advisor import get_sales_advice

router = APIRouter(prefix="/api/prices", tags=["prices"])


@router.get("/ledger")
def ledger() -> dict:
    from tools.auction_archive import archive_ledger_snapshot

    data = cached("prices_ledger", ttl_seconds=600, fn=fetch_auction_ledger)
    result = dict(data)
    try:
        result["archive"] = archive_ledger_snapshot(data)
    except Exception as exc:
        result["archive"] = {"error": str(exc)}
    return result


@router.get("/grades")
def grades(by_market: bool = False) -> dict | list[dict]:
    if by_market:
        return cached("prices_grades_by_market", ttl_seconds=600, fn=fetch_grades_by_markets)
    return cached("prices_grades", ttl_seconds=600, fn=fetch_all_grades)


@router.get("/today")
def today() -> dict:
    return cached("prices_today", ttl_seconds=600, fn=fetch_today_price)


@router.get("/board")
def board(days: int = 30, grade: str = "중") -> dict:
    series = cached(
        f"prices_board_{days}_{grade}", ttl_seconds=600,
        fn=lambda: fetch_price_range(days=days, grade=grade),
    )
    trend: list[dict] = []
    if len(series) >= 2:
        xs = np.arange(len(series))
        ys = np.array([s["price"] for s in series], dtype=float)
        slope, intercept = np.polyfit(xs, ys, 1)
        trend = [
            {"date": s["date"], "trend": round(float(intercept + slope * i))}
            for i, s in enumerate(series)
        ]
    return {"series": series, "trend": trend}


@router.get("/compare-markets")
def compare_markets(days: int = 14, grade: str = "중") -> list[dict]:
    return cached(
        f"prices_compare_markets_{days}_{grade}", ttl_seconds=600,
        fn=lambda: fetch_price_range_by_markets(days=days, grade=grade),
    )


@router.post("/archive-ledger")
def archive_ledger() -> dict:
    from tools.auction_archive import archive_ledger_snapshot

    data = fetch_auction_ledger()
    return archive_ledger_snapshot(data)


@router.get("/archive-summary")
def get_archive_summary() -> dict:
    from tools.auction_archive import archive_summary

    return archive_summary()


@router.get("/origin-market-cycle")
def get_origin_market_cycle(days: int = 180, min_count: int = 3) -> dict:
    from tools.auction_archive import origin_market_cycle

    days = min(max(days, 30), 1095)
    min_count = min(max(min_count, 1), 30)
    return origin_market_cycle(days=days, min_count=min_count)


@router.get("/monthly-seasonal-cycle")
def get_monthly_seasonal_cycle() -> dict:
    """전주·대전오정·대전노은 실거래 아카이브 기준 월별 계절 사이클(4kg 환산).

    38만여 건 전체 스캔이라 무겁다 — 아카이브가 자주 바뀌지 않으므로 캐시.
    """
    from tools.auction_archive import monthly_seasonal_cycle

    return cached("prices_monthly_seasonal_cycle", ttl_seconds=3600, fn=monthly_seasonal_cycle)


@router.get("/daily-price-history")
def get_daily_price_history(start: str, end: str, min_count: int = 1) -> dict:
    """월별 계절 사이클 차트를 "확대"했을 때 보여줄 일자별 시장별 중앙값(4kg 환산)."""
    from datetime import date as _date

    from tools.auction_archive import daily_price_history

    start_d = _date.fromisoformat(start)
    end_d = _date.fromisoformat(end)
    min_count = min(max(min_count, 1), 30)
    return cached(
        f"prices_daily_{start}_{end}_{min_count}", ttl_seconds=3600,
        fn=lambda: daily_price_history(start_d, end_d, min_count=min_count),
    )


@router.get("/daily-grade-history")
def get_daily_grade_history(start: str, end: str) -> dict:
    """일자별 확대 차트의 등급별(상/중/하 tercile 추정) 보기."""
    from datetime import date as _date

    from tools.auction_archive import daily_grade_history

    start_d = _date.fromisoformat(start)
    end_d = _date.fromisoformat(end)
    return cached(
        f"prices_daily_grade_{start}_{end}", ttl_seconds=3600,
        fn=lambda: daily_grade_history(start_d, end_d),
    )


@router.get("/harvest-strategy")
def harvest_strategy(horizon_days: int = 14, grade: str = "중") -> dict:
    from tools.growth_data import assess_growth
    from tools.harvest_strategy import build_harvest_strategy
    from tools.sensor_client import fetch_from_csv

    horizon_days = min(max(horizon_days, 7), 28)
    price_series = fetch_price_range(days=30, grade=grade)
    latest_growth = assess_growth("전체")
    sensor = fetch_from_csv()
    return build_harvest_strategy(
        latest_growth=latest_growth,
        price_series=price_series,
        sensor=sensor,
        horizon_days=horizon_days,
    )


@router.get("/history-long")
def history_long(live: bool = False) -> list[dict]:
    if live:
        try:
            return fetch_shipment_price_history()
        except Exception:
            return fetch_shipment_price_history_static()
    return fetch_shipment_price_history_static()


class BriefingRequest(BaseModel):
    per_query_count: int = 5


@router.post("/briefing")
def create_briefing(body: BriefingRequest | None = None) -> dict:
    from backend.jobs_impl import run_price_briefing
    per_query_count = body.per_query_count if body else 5
    job_id = jobs.create_job(run_price_briefing, per_query_count)
    return {"job_id": job_id}


@router.post("/sales-advice")
def sales_advice(current_price: int | None = None, month: int | None = None) -> dict:
    return get_sales_advice(current_price, month)
