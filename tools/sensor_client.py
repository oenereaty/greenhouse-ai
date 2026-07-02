"""Greenhouse sensor client — real API or time-based simulation fallback."""
import math
import os
import random
import requests
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")


def fetch_from_api(url: str, timeout: int = 5) -> dict:
    """
    Fetch sensor readings from a real IoT API.
    Expected JSON response keys (flexible): temp/temperature, rh/humidity,
    co2/co2_ppm, vent/ventilation/vent_pct.
    """
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    raw = resp.json()

    def _get(*keys, default=0.0):
        for k in keys:
            if k in raw:
                try:
                    return float(raw[k])
                except (TypeError, ValueError):
                    pass
        return default

    return {
        "temp":  _get("temp", "temperature", "air_temp", "ta"),
        "rh":    _get("rh", "humidity", "relative_humidity", "hm"),
        "co2":   _get("co2", "co2_ppm", "co2_concentration"),
        "solar": _get("solar", "solar_radiation", "irradiance", "rad", "sr"),
        "timestamp": raw.get("timestamp", datetime.now().isoformat(timespec="seconds")),
        "source": "api",
        "api_url": url,
    }


def generate_mock(seed_offset: float = 0.0) -> dict:
    """
    Generate realistic simulated sensor readings.
    - Temperature: 22~35℃ daily sine curve (peak 14:00)
    - Humidity: inversely correlated with temperature
    - CO2: drops during active photosynthesis (08~17시)
    - Solar: sine curve during daylight (06~18시), peak ~900 W/m²
    """
    now = datetime.now()
    hour = now.hour + now.minute / 60 + seed_offset

    # Temperature: sine curve
    base_temp = 28 + 7 * math.sin((hour - 8) * math.pi / 12)
    temp = round(max(18.0, min(38.0, base_temp + random.uniform(-0.8, 0.8))), 1)

    # Humidity: drops as temp rises
    rh_base = 80 - (temp - 20) * 1.5
    rh = int(max(40, min(90, rh_base + random.uniform(-3, 3))))

    # CO2: consumed by photosynthesis 08~17시, restored at night
    if 8 <= hour <= 17:
        co2_base = 800 - (hour - 8) * 35
    else:
        co2_base = 400 + (hour - 17) * 20 if hour > 17 else 400
    co2 = int(max(300, min(1500, co2_base + random.uniform(-25, 25))))

    # Solar radiation: sine curve 06~18시, peak ~900 W/m²
    if 6 <= hour <= 18:
        solar = round(max(0, 900 * math.sin((hour - 6) * math.pi / 12) + random.uniform(-30, 30)), 1)
    else:
        solar = 0.0

    return {
        "temp": temp,
        "rh": rh,
        "co2": co2,
        "solar": solar,
        "timestamp": now.isoformat(timespec="seconds"),
        "source": "simulation",
        "api_url": None,
    }


def fetch_sensors(url: str = "") -> dict:
    """
    Main entry point. Tries real API if URL given, falls back to simulation.
    URL priority: argument > .env(SENSOR_API_URL) > simulation
    """
    target_url = url or os.getenv("SENSOR_API_URL", "")

    if target_url:
        try:
            data = fetch_from_api(target_url)
            return data
        except Exception as e:
            fallback = generate_mock()
            fallback["api_error"] = str(e)
            fallback["source"] = "simulation(api_fallback)"
            return fallback

    return generate_mock()


if __name__ == "__main__":
    print("=== 센서 시뮬레이션 테스트 ===")
    for _ in range(5):
        d = generate_mock()
        print(f"  {d['timestamp']}  온도={d['temp']}℃  습도={d['rh']}%  CO2={d['co2']}ppm  일사={d['solar']}W/m²")
