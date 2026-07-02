"""실제 온실 센서가 없을 때 사용하는 시뮬레이터 (여름 온실 패턴 기반)"""
import random
from datetime import datetime


def get_greenhouse_data() -> dict:
    """현재 시각 기반 온실 내부 환경 시뮬레이션"""
    hour = datetime.now().hour
    is_daytime = 9 <= hour <= 17

    temp = round(
        (34 if is_daytime else 26)
        + random.gauss(0, 1.5),
        1,
    )
    humidity = round(
        (60 if is_daytime else 80)
        + random.gauss(0, 5),
        1,
    )
    co2 = round(400 + (200 if not is_daytime else 0) + random.gauss(0, 30))

    return {
        "temperature": max(15.0, min(50.0, temp)),
        "humidity": max(30.0, min(100.0, humidity)),
        "co2_ppm": max(300, co2),
        "timestamp": datetime.now().isoformat(),
        "source": "simulator",
    }


if __name__ == "__main__":
    data = get_greenhouse_data()
    print(data)
