"""토마토 온실 주요 병해 위험도 계산"""


def calculate_botrytis_risk(temp: float, humidity: float, leaf_wetness_hours: float = 0) -> int:
    """잿빛곰팡이(Botrytis cinerea) 위험도 0-100"""
    risk = 0
    if 15 <= temp <= 25:
        risk += 40
    if humidity >= 90:
        risk += 40
    elif humidity >= 80:
        risk += 20
    risk += min(20, int(leaf_wetness_hours * 5))
    return min(100, risk)


def calculate_powdery_mildew_risk(temp: float, humidity: float) -> int:
    """흰가루병(Oidium neolycopersici) 위험도 0-100"""
    risk = 0
    if 20 <= temp <= 25:
        risk += 50
    if 50 <= humidity <= 70:
        risk += 50
    return min(100, risk)


def calculate_late_blight_risk(temp: float, humidity: float) -> int:
    """역병(Phytophthora infestans) 위험도 0-100"""
    risk = 0
    if 15 <= temp <= 25:
        risk += 40
    if humidity >= 85:
        risk += 60
    return min(100, risk)


def get_disease_alerts(temp: float, humidity: float, leaf_wetness_hours: float = 0) -> list[dict]:
    """현재 환경 조건에서 위험 병해 목록 반환"""
    alerts = []

    checks = [
        ("잿빛곰팡이", calculate_botrytis_risk(temp, humidity, leaf_wetness_hours), "환기 강화, 예방 살균제 처리"),
        ("흰가루병", calculate_powdery_mildew_risk(temp, humidity), "황 훈증 또는 트리플록시스트로빈 살포"),
        ("역병", calculate_late_blight_risk(temp, humidity), "배수 확인, 메탈락실 살균제 처리"),
    ]

    for disease, risk, action in checks:
        if risk >= 60:
            alerts.append({
                "disease": disease,
                "risk": risk,
                "severity": "경고" if risk >= 80 else "주의",
                "action": action,
            })

    return sorted(alerts, key=lambda x: x["risk"], reverse=True)


if __name__ == "__main__":
    alerts = get_disease_alerts(temp=22.0, humidity=92.0)
    for a in alerts:
        print(f"[{a['severity']}] {a['disease']} 위험도 {a['risk']} - {a['action']}")
