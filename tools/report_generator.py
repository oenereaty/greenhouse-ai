"""주기 리포트 생성 — 환경데이터 통계·시각화 + 영농일지(농작업 기록) + 병해 로그.

기간은 발표용 고정 "오늘"(tools/demo_clock.demo_now) 기준으로 계산한다. 예전엔
실제 달력 날짜(date.today())를 썼는데, 센서·생육·기상·수확D-day를 전부
demo_clock 기준으로 맞춘 뒤로는 리포트만 실제 오늘 기준이면 다른 탭과 기간이
어긋난다(2026-07-10 사용자 확인) — 영농일지도 같은 기준으로 필터링된다.
"""
from datetime import datetime, timedelta
from statistics import mean

from tools import diary_data
from tools.demo_clock import demo_now
from tools.pesticide_db import DISEASE_MAP, PEST_NAMES, SPRAY_ACTIONS
from tools.sensor_client import get_series_range

_DISEASE_TAGS = set(DISEASE_MAP.keys()) | PEST_NAMES | SPRAY_ACTIONS


def _daily_env_stats(series: list[dict]) -> list[dict]:
    by_date: dict[str, list[dict]] = {}
    for row in series:
        d = row["timestamp"][:10]
        by_date.setdefault(d, []).append(row)

    daily = []
    for d in sorted(by_date):
        rows = by_date[d]
        temps = [r["temp"] for r in rows]
        rhs = [r["rh"] for r in rows]
        co2s = [r["co2"] for r in rows]
        solars = [r["solar"] for r in rows]
        daily.append({
            "date": d,
            "avg_temp": round(mean(temps), 1),
            "min_temp": round(min(temps), 1),
            "max_temp": round(max(temps), 1),
            "avg_rh": round(mean(rhs), 1),
            "avg_co2": round(mean(co2s), 0),
            "avg_solar": round(mean(solars), 1),
            "reading_count": len(rows),
        })
    return daily


def _env_summary(daily: list[dict]) -> dict | None:
    if not daily:
        return None
    return {
        "avg_temp": round(mean(d["avg_temp"] for d in daily), 1),
        "max_temp": round(max(d["max_temp"] for d in daily), 1),
        "min_temp": round(min(d["min_temp"] for d in daily), 1),
        "avg_rh": round(mean(d["avg_rh"] for d in daily), 1),
        "avg_co2": round(mean(d["avg_co2"] for d in daily), 0),
        "days_with_data": len(daily),
    }


def _diary_in_range(start: str, end: str) -> list[dict]:
    all_entries = diary_data.load_all()
    out = []
    for d, entries in all_entries.items():
        if not (start <= d <= end):
            continue
        for e in entries:
            out.append({**e, "date": d})
    out.sort(key=lambda e: (e["date"], e.get("time", "")))
    return out


def build_report(days: int = 7) -> dict:
    """지난 `days`일(오늘 포함) 리포트를 생성한다."""
    end_d = demo_now().date()
    start_d = end_d - timedelta(days=days - 1)
    start, end = start_d.isoformat(), end_d.isoformat()

    series = get_series_range(start, end)
    daily_env = _daily_env_stats(series)
    env_summary = _env_summary(daily_env)

    diary_entries = _diary_in_range(start, end)
    disease_log = [
        e for e in diary_entries
        if _DISEASE_TAGS.intersection(e.get("tags", []))
    ]

    coverage_note = None
    if not daily_env:
        coverage_note = "이 기간에는 센서 실측 데이터가 없습니다."
    elif len(daily_env) < days:
        missing = days - len(daily_env)
        coverage_note = f"{days}일 중 {missing}일은 센서 데이터가 아직 없습니다(가장 이른 날짜 쪽 공백)."

    return {
        "period": {"start": start, "end": end, "days": days},
        "generated_at": datetime.now().strftime("%Y-%m-%dT%H%M%S"),
        "env": {
            "daily": daily_env,
            "summary": env_summary,
            "coverage_note": coverage_note,
        },
        "diary": diary_entries,
        "disease_log": disease_log,
    }
