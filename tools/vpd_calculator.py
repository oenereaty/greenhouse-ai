import math


def calculate_vpd(temp_celsius: float, humidity_percent: float) -> float:
    """온도(°C)와 상대습도(%)로 VPD(kPa) 계산 (Tetens 공식)"""
    svp = 0.6108 * math.exp(17.27 * temp_celsius / (temp_celsius + 237.3))
    avp = svp * (humidity_percent / 100)
    return round(svp - avp, 3)


def interpret_vpd(vpd: float) -> dict:
    """토마토 기준 VPD 범위별 영향"""
    if vpd < 0.4:
        return {"status": "위험", "level": "low", "message": "증산 억제, 잿빛곰팡이 위험 증가"}
    elif vpd < 0.8:
        return {"status": "주의", "level": "low_ok", "message": "낮은 증산, 생육 다소 느림"}
    elif vpd <= 1.2:
        return {"status": "최적", "level": "optimal", "message": "이상적인 VPD 범위 (0.8~1.2 kPa)"}
    elif vpd <= 1.5:
        return {"status": "주의", "level": "high_ok", "message": "증산 증가, 관수 체크 필요"}
    elif vpd <= 2.0:
        return {"status": "위험", "level": "high", "message": "기공 폐쇄 시작, 광합성 감소"}
    else:
        return {"status": "심각", "level": "critical", "message": "심각한 수분 스트레스, 즉각 조치 필요"}


if __name__ == "__main__":
    vpd = calculate_vpd(32.0, 65.0)
    print(f"VPD: {vpd} kPa → {interpret_vpd(vpd)}")
