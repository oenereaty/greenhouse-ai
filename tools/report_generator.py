"""주기 리포트 생성 — 환경데이터 통계·시각화 + 영농일지(농작업 기록) + 병해 로그.

기간은 실제 달력 날짜(date.today() 기준)로 계산한다. 센서 CSV는 시연용으로
"오늘"을 고정해두지만(tools/sensor_client._demo_now), 영농일지는 실제 오늘
날짜로 기록되므로 두 데이터의 기간이 어긋나지 않도록 실제 날짜를 기준으로
삼는다(정보 간 유기성 유지).
"""
from datetime import date, datetime, timedelta
from statistics import mean

from tools import diary_data
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


# 데모 영상 촬영 주간(사용자 요청, 2026-07-08 주 한정) 임시 조치: CSV 실측이
# 끊긴 최근 며칠(현재 2026-07-06 이후)을 리포트에서 공백으로 보여주는 대신
# 마지막 실측일 값을 이어붙인다. 앱의 실시간 센서 표시가 이미 쓰는 freeze
# 방식(tools/sensor_client.fetch_from_csv의 is_frozen)과 같은 관례를 리포트에도
# 적용한 것뿐, 없는 값을 새로 지어내는 것은 아니다. 이번 주 데모 이후에는
# 제거하고 원래대로(공백을 coverage_note로 정직하게 표시) 되돌릴 것.
def _fill_trailing_gaps(daily: list[dict], start: str, end: str) -> list[dict]:
    by_date = {d["date"]: d for d in daily}
    cur = datetime.strptime(start, "%Y-%m-%d").date()
    end_d = datetime.strptime(end, "%Y-%m-%d").date()
    filled: list[dict] = []
    last_real: dict | None = None
    while cur <= end_d:
        ds = cur.isoformat()
        if ds in by_date:
            last_real = by_date[ds]
            filled.append(last_real)
        elif last_real is not None:
            filled.append({**last_real, "date": ds, "reading_count": 0, "is_carried_forward": True})
        cur += timedelta(days=1)
    return filled


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
    end_d = date.today()
    start_d = end_d - timedelta(days=days - 1)
    start, end = start_d.isoformat(), end_d.isoformat()

    series = get_series_range(start, end)
    daily_env_raw = _daily_env_stats(series)
    daily_env = _fill_trailing_gaps(daily_env_raw, start, end)
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
