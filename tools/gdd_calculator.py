from datetime import date, timedelta
from typing import Optional

TOMATO_BASE_TEMP = 10.0  # °C (토마토 생육 기준온도)
TOMATO_MAX_TEMP = 30.0   # °C (이 이상은 GDD 산정에서 제한)

# 정식 후 누적 GDD 기준 (품종마다 다름 - 중생종 기준)
TOMATO_GROWTH_STAGES = {
    "정식 초기": (0, 100),
    "영양생장": (100, 300),
    "1화방 개화": (300, 450),
    "착과": (450, 700),
    "과실 비대": (700, 1000),
    "수확": (1000, float("inf")),
}

# 착과 실패 위험 온도 임계값
FRUIT_SET_FAILURE = {
    "day_temp_critical": 35.0,   # 낮 기온 초과 시 착과 실패 위험
    "night_temp_critical": 25.0, # 밤 기온 초과 3일 연속 시 착과 실패
}


def calculate_daily_gdd(tmax: float, tmin: float) -> float:
    """일별 GDD 계산 (Baskerville-Emin 간이법)"""
    tmax = min(tmax, TOMATO_MAX_TEMP)
    avg = (tmax + tmin) / 2
    return max(0.0, round(avg - TOMATO_BASE_TEMP, 2))


def get_growth_stage(accumulated_gdd: float) -> str:
    for stage, (start, end) in TOMATO_GROWTH_STAGES.items():
        if start <= accumulated_gdd < end:
            return stage
    return "수확"


def is_fruit_set_at_risk(day_temps: list[float], night_temps: list[float]) -> dict:
    """최근 n일 온도 기록으로 착과 실패 위험 판단"""
    risk = False
    reason = []

    if any(t > FRUIT_SET_FAILURE["day_temp_critical"] for t in day_temps):
        risk = True
        reason.append(f"낮 기온 {FRUIT_SET_FAILURE['day_temp_critical']}°C 초과 (꽃가루 불활성화)")

    # 밤 기온 3일 연속 초과
    consecutive = 0
    for t in night_temps:
        if t > FRUIT_SET_FAILURE["night_temp_critical"]:
            consecutive += 1
            if consecutive >= 3:
                risk = True
                reason.append(f"밤 기온 {FRUIT_SET_FAILURE['night_temp_critical']}°C 초과 3일 연속")
                break
        else:
            consecutive = 0

    return {"at_risk": risk, "reasons": reason}


if __name__ == "__main__":
    gdd = calculate_daily_gdd(34.0, 22.0)
    print(f"오늘 GDD: {gdd}")
    print(f"생육 단계 (누적 500 기준): {get_growth_stage(500)}")

    result = is_fruit_set_at_risk([36, 33, 34], [26, 27, 25])
    print(f"착과 위험: {result}")
