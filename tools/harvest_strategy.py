"""Market-linked harvest timing strategy.

This module connects growth records, current greenhouse climate, and recent
auction prices into one practical recommendation. It is intentionally rule-first:
the first version should be explainable before any LLM wording is added.
"""
from __future__ import annotations

from datetime import date, timedelta
from statistics import mean


def _num(value, default: float | None = None) -> float | None:
    try:
        if value in ("", None):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _price_signal(series: list[dict], horizon_days: int) -> dict:
    rows = [r for r in series if _num(r.get("price")) is not None]
    if len(rows) < 3:
        return {
            "direction": "unknown",
            "change_pct": None,
            "current_price": None,
            "projected_price": None,
            "reason": "가격 시계열이 부족해 2주 방향성을 계산하지 못했습니다.",
        }

    recent = rows[-14:] if len(rows) >= 14 else rows
    first = _num(recent[0].get("price"), 0) or 0
    last = _num(recent[-1].get("price"), 0) or 0
    daily_slope = (last - first) / max(len(recent) - 1, 1)
    projected = max(0, last + daily_slope * horizon_days)
    change_pct = ((projected - last) / last * 100) if last else 0

    if change_pct >= 8:
        direction = "up"
        reason = f"최근 가격 기울기를 {horizon_days}일 연장하면 약 {change_pct:+.1f}% 상승 구간입니다."
    elif change_pct <= -8:
        direction = "down"
        reason = f"최근 가격 기울기를 {horizon_days}일 연장하면 약 {change_pct:+.1f}% 하락 구간입니다."
    else:
        direction = "flat"
        reason = f"최근 가격 기울기 기준 {horizon_days}일 변화가 약 {change_pct:+.1f}%로 크지 않습니다."

    return {
        "direction": direction,
        "change_pct": round(change_pct, 1),
        "current_price": int(last),
        "projected_price": int(projected),
        "recent_avg": int(mean(_num(r.get("price"), 0) or 0 for r in recent)),
        "reason": reason,
    }


def _growth_summary(assess_rows: list[dict]) -> dict:
    """구역별 생식/영양생장 균형 판정 결과(growth_data.assess_growth 출력)를 요약.

    착과수는 육안 계수 오차가 크고 표본 편차가 심해(개체마다 편차 큼) 신뢰도가
    낮다. 대신 화방높이(생장점–개화화방 거리, 균형 판정 표준 측정치), 줄기두께·
    초장의 전 주 대비 추세를 메인 지표로 쓴다 — 셋 다 growth_data.assess_growth()가
    이미 계산해두는 값이라 여기서 다시 만들지 않고 그대로 집계만 한다.
    """
    if not assess_rows:
        return {
            "zones": 0,
            "avg_height_trend_cm": None,
            "avg_stem_trend_mm": None,
            "truss_balance": {"영양생장쪽": 0, "생식생장쪽": 0, "균형": 0},
            "readiness": "unknown",
            "reason": "최근 생육 기록이 없어 생육 기반 출하 판단을 할 수 없습니다.",
        }

    height_trends = [_num(r.get("crop_height_cm_trend")) for r in assess_rows]
    height_trends = [v for v in height_trends if v is not None]
    stem_trends = [_num(r.get("stem_diameter_mm_trend")) for r in assess_rows]
    stem_trends = [v for v in stem_trends if v is not None]

    statuses = [r.get("truss_status") for r in assess_rows if r.get("truss_status")]
    veg_heavy = statuses.count("영양생장 쪽으로 추정")
    rep_heavy = statuses.count("생식생장 쪽으로 추정")
    balanced = statuses.count("균형 추정")

    avg_height_trend = mean(height_trends) if height_trends else None
    avg_stem_trend = mean(stem_trends) if stem_trends else None

    total = len(statuses)
    if not statuses:
        readiness = "unknown"
        reason = "화방높이 기록이 없어 생식/영양생장 균형을 판정할 수 없습니다."
    elif veg_heavy > max(rep_heavy, balanced):
        readiness = "vegetative_heavy"
        reason = f"화방높이 기준 영양생장 우세 구역이 {veg_heavy}/{total}곳으로 가장 많습니다 — 착과·비대보다 생식생장 유도가 우선입니다."
    elif rep_heavy > max(veg_heavy, balanced):
        readiness = "reproductive_heavy"
        reason = f"화방높이 기준 생식생장 우세 구역이 {rep_heavy}/{total}곳으로 가장 많습니다 — 과실 비대에 자원이 집중되는 시기로 출하 타이밍 조절 여지가 있습니다."
    else:
        readiness = "balanced"
        reason = "화방높이 기준 생식/영양생장이 균형 상태로 추정됩니다."

    return {
        "zones": len(assess_rows),
        "avg_height_trend_cm": round(avg_height_trend, 1) if avg_height_trend is not None else None,
        "avg_stem_trend_mm": round(avg_stem_trend, 1) if avg_stem_trend is not None else None,
        "truss_balance": {"영양생장쪽": veg_heavy, "생식생장쪽": rep_heavy, "균형": balanced},
        "readiness": readiness,
        "reason": reason,
    }


def _climate_summary(sensor: dict) -> dict:
    temp = _num(sensor.get("temp"), 0) or 0
    rh = _num(sensor.get("rh"), 0) or 0
    if temp >= 30 or rh >= 90:
        constraint = "risk"
        reason = "현재 고온 또는 고습 위험이 있어 가격 전략보다 온습도 안정이 우선입니다."
    elif temp >= 27 or rh >= 85:
        constraint = "caution"
        reason = "온습도가 높은 편이라 생육 속도 조절은 환기·차광과 병해 위험을 함께 봐야 합니다."
    else:
        constraint = "ok"
        reason = "현재 온습도는 생육 속도 조절 전략을 검토할 수 있는 범위입니다."
    return {"temp": temp, "rh": rh, "constraint": constraint, "reason": reason}


def build_harvest_strategy(
    latest_growth: list[dict],
    price_series: list[dict],
    sensor: dict,
    horizon_days: int = 14,
) -> dict:
    """latest_growth는 growth_data.assess_growth()의 출력(구역별 화방높이 판정 +
    초장·줄기두께 전 주 대비 추세)을 받는다 — 원시 latest() 행이 아님."""
    price = _price_signal(price_series, horizon_days)
    growth = _growth_summary(latest_growth)
    climate = _climate_summary(sensor)
    target_date = (date.today() + timedelta(days=horizon_days)).isoformat()

    price_available = price["direction"] != "unknown"

    if climate["constraint"] == "risk":
        action = "환경 안정 우선"
        temperature_strategy = "평균온도 조절보다 환기·순환·차광으로 고온·고습을 먼저 낮추세요."
        rationale = climate["reason"]
        if not price_available:
            rationale += " (참고: 가격 데이터가 없어 이번 판단은 생육·온습도 신호만으로 내려졌습니다.)"
    elif not price_available:
        action = "생육·환경 신호만으로 판단"
        temperature_strategy = (
            "가격 데이터가 없어 출하 타이밍 조절은 판단하지 않습니다. "
            f"{growth['reason']} 표준 온습도 관리를 유지하며 가격 데이터가 복구되면 다시 확인하세요."
        )
        rationale = "가격 시계열이 없어(예: 외부 API 일시 장애) 가격 기반 출하 전략은 이번 판단에서 제외됩니다."
    elif price["direction"] == "up" and growth["readiness"] in ("reproductive_heavy", "balanced"):
        action = "출하 지연 검토"
        temperature_strategy = (
            "품질 저하가 없다는 전제에서 야간·평균온도를 무리하게 높이지 말고 약간 낮게 가져가 "
            "성숙 속도를 늦춰 2주 뒤 가격 구간을 노리는 전략을 검토하세요."
        )
        rationale = "가격 상승 신호와 함께 화방높이 기준 과실 비대 쪽으로 자원이 쏠려 있어 출하 타이밍 조절 가치가 있습니다."
    elif price["direction"] == "down" and growth["readiness"] == "reproductive_heavy":
        action = "출하 앞당김 검토"
        temperature_strategy = (
            "품질과 착색이 확보되는 범위에서 생육 지연 요인을 줄이고, 선별 가능한 물량은 빠른 출하를 검토하세요."
        )
        rationale = "2주 뒤 가격 하락 신호가 있고 화방높이 기준 생식생장이 우세해 현재 출하 가능 물량의 기회비용이 커질 수 있습니다."
    elif growth["readiness"] == "vegetative_heavy":
        action = "생식생장 유도 검토"
        temperature_strategy = "출하 타이밍보다 화방높이 균형 회복을 우선하세요. 주야간 온도차(DIF) 확대, 야간온도 소폭 하강으로 생식생장을 유도하는 방향을 검토하세요."
        rationale = growth["reason"]
    else:
        action = "관망"
        temperature_strategy = "가격 변화가 크지 않거나 생육 신호가 뚜렷하지 않으므로 현재 표준 온습도 관리를 유지하세요."
        rationale = price["reason"] if price_available else growth["reason"]

    return {
        "horizon_days": horizon_days,
        "target_date": target_date,
        "action": action,
        "temperature_strategy": temperature_strategy,
        "rationale": rationale,
        "price": price,
        "growth": growth,
        "climate": climate,
        "caveats": [
            "가격 전망은 최근 경락가 기울기를 단순 연장한 보조 지표입니다.",
            "온도를 낮춰 출하를 늦추는 판단은 품질, 착색, 병해 위험, 계약 출하 조건을 함께 확인해야 합니다.",
        ],
    }
