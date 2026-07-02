"""Greenhouse sensor simulation (day/night cycle + realistic noise)."""
import math
import random
from datetime import datetime


def generate_sensor_data(hour: int | None = None) -> dict:
    """Return simulated greenhouse sensor readings for the given hour (default: now)."""
    if hour is None:
        hour = datetime.now().hour

    # Temperature: rises from 06:00, peaks at 14:00, falls overnight
    base_temp = 24 + 8 * max(0, math.sin((hour - 6) * math.pi / 12))
    temp = round(base_temp + random.uniform(-1.0, 1.0), 1)

    # Humidity: inversely related to temperature
    base_rh = 80 - 0.8 * (temp - 20)
    rh = round(max(40, min(95, base_rh + random.uniform(-5, 5))), 1)

    # CO2: lower during daytime photosynthesis, higher at night
    base_co2 = 600 if 8 <= hour <= 18 else 900
    co2 = round(base_co2 + random.uniform(-80, 120))

    # Solar radiation: zero at night, bell curve during day
    if 6 <= hour <= 18:
        base_solar = 600 * math.sin((hour - 6) * math.pi / 12)
        solar = round(max(0, base_solar + random.uniform(-30, 30)))
    else:
        solar = 0

    return {
        "temp": temp,
        "rh": rh,
        "co2": co2,
        "solar": solar,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "simulated": True,
    }


def generate_history(hours: int = 24) -> list[dict]:
    """Generate a time-series of simulated sensor data over the past N hours."""
    now = datetime.now()
    records = []
    for i in range(hours, 0, -1):
        h = (now.hour - i) % 24
        row = generate_sensor_data(hour=h)
        row["timestamp"] = f"T-{i}h"
        records.append(row)
    return records
