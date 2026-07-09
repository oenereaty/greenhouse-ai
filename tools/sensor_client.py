"""Greenhouse sensor client — real 5-minute-interval greenhouse log (2026-01-01 ~ 오늘).

file/온실_센서데이터_통합.csv(scripts/import_sensor_data.py로 생성)를 사용한다.
데이터가 존재하는 최신 시각까지는 "지금" 시각에 맞춰 실측값을 그대로 반환하고,
데이터 갱신이 아직 안 된 최근 구간(리포트 내보내기 지연)은 마지막 실측 행으로
고정(freeze)해 보여준다.
"""
import csv
import math
import random
from datetime import datetime, timedelta
from pathlib import Path

_CSV_PATH = Path(__file__).parent.parent / "file" / "온실_센서데이터_통합.csv"

# timestamp(5분 단위, "YYYY-MM-DD HH:MM:SS") → row dict; 최초 사용 시 1회 로드
_ROWS: dict[str, dict] | None = None
_SORTED_KEYS: list[str] = []


def _round_down_5min(dt: datetime) -> datetime:
    return dt.replace(minute=(dt.minute // 5) * 5, second=0, microsecond=0)


def _demo_now() -> datetime:
    """실측 CSV가 최신까지 갱신되지 않아(마지막 실측 2026-07-06) 발표 시점에 맞는
    시연용 '오늘'을 2026-07-01로 고정한다. 시:분은 실제 현재 시각을 그대로 써서
    발표 진행 중에도 자연스럽게 값이 바뀐다. 가격/기상처럼 실제 외부 API를
    조회하는 곳은 이 함수를 쓰지 않고 실제 오늘 날짜를 그대로 사용해야 한다
    (그렇지 않으면 aT/KMA가 존재하지 않는 날짜를 조회해 빈 응답만 온다)."""
    now = datetime.now()
    return now.replace(year=2026, month=7, day=1)


def _load_rows() -> tuple[dict[str, dict], list[str]]:
    rows: dict[str, dict] = {}
    try:
        with _CSV_PATH.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                rows[row["timestamp"]] = row
    except Exception:
        return {}, []
    keys = sorted(rows.keys())
    return rows, keys


def _get_rows() -> tuple[dict[str, dict], list[str]]:
    global _ROWS, _SORTED_KEYS
    if _ROWS is None:
        _ROWS, _SORTED_KEYS = _load_rows()
    return _ROWS, _SORTED_KEYS


def _lookup(now: datetime) -> tuple[dict | None, bool]:
    """now 시각(5분 반올림)에 해당하는 실측 행을 반환.

    데이터 끝을 넘어선 시각이면 (마지막 행, True) 반환 — 최신값 고정(freeze) 표시용.
    """
    rows, keys = _get_rows()
    if not keys:
        return None, False

    key = _round_down_5min(now).strftime("%Y-%m-%d %H:%M:%S")
    if key in rows:
        return rows[key], False
    if key > keys[-1]:
        return rows[keys[-1]], True
    return None, False


def _cum_solar_real(hourly_unused=None, now: datetime | None = None) -> float:
    """호환용 — 실제로는 fetch_from_csv 내부에서 CSV의 solar_cum 컬럼을 직접 사용."""
    return 0.0


def get_recent_series(hours: int = 24) -> list[dict]:
    """데이터가 존재하는 최신 시각 기준, 최근 N시간의 실측 시계열을 반환.

    각 항목: timestamp, temp, rh, co2, solar (5분 간격).
    """
    rows, keys = _get_rows()
    if not keys:
        return []
    end = min(_round_down_5min(_demo_now()), datetime.strptime(keys[-1], "%Y-%m-%d %H:%M:%S"))
    end_key = end.strftime("%Y-%m-%d %H:%M:%S")
    start_key = (end - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    result = []
    for k in keys:
        if k < start_key or k > end_key:
            continue
        row = rows[k]
        result.append({
            "timestamp": k,
            "temp":  round(float(row["indoor_temp"]), 1),
            "rh":    round(float(row["indoor_rh"]), 1),
            "co2":   round(float(row["co2"]), 0),
            "solar": round(float(row["solar"]), 1),
        })
    return result


def get_series_range(start_date: str, end_date: str) -> list[dict]:
    """실제 달력 날짜(YYYY-MM-DD) 범위로 실측 시계열을 반환.

    get_recent_series()는 시연용 "오늘"(_demo_now)에 고정된 최근 N시간만 조회하지만,
    리포트는 영농일지 등 실제 오늘 날짜 기준 데이터와 기간을 맞춰야 하므로 CSV의
    실제 timestamp로 직접 필터링한다. CSV 갱신이 안 된 최근 날짜는 빈 결과로
    남아 있는 그대로 "데이터 없음"이 되도록 두고(freeze 처리하지 않음) 리포트가
    솔직하게 데이터 공백을 보여주게 한다.
    """
    rows, keys = _get_rows()
    if not keys:
        return []
    start_key = f"{start_date} 00:00:00"
    end_key = f"{end_date} 23:59:59"
    result = []
    for k in keys:
        if k < start_key or k > end_key:
            continue
        row = rows[k]
        result.append({
            "timestamp": k,
            "temp":  round(float(row["indoor_temp"]), 1),
            "rh":    round(float(row["indoor_rh"]), 1),
            "co2":   round(float(row["co2"]), 0),
            "solar": round(float(row["solar"]), 1),
        })
    return result


def fetch_from_csv() -> dict:
    """실측 CSV에서 현재(또는 마지막 실측) 시각의 센서값을 반환."""
    now = _demo_now()
    row, is_frozen = _lookup(now)

    if row is None:
        return generate_mock()

    return {
        "temp":          round(float(row["indoor_temp"]), 1),
        "rh":            int(round(float(row["indoor_rh"]))),
        "co2":           int(round(float(row["co2"]))),
        "solar":         round(float(row["solar"]), 1),
        "solar_is_mock": False,
        "cum_solar":     round(float(row["solar_cum"]), 0),
        "outdoor_temp":  round(float(row["outdoor_temp"]), 1),
        "wind_speed":    round(float(row["wind_speed"]), 1),
        "wind_dir":      float(row["wind_dir"]),
        "rain":          row["rain"],
        "timestamp":     now.isoformat(timespec="seconds"),
        "data_timestamp": row["timestamp"],
        "is_frozen":     is_frozen,
        "source":        "csv",
    }


def generate_mock(seed_offset: float = 0.0) -> dict:
    """Fallback: generate realistic simulated sensor readings."""
    now  = datetime.now()
    hour = now.hour + now.minute / 60 + seed_offset

    base_temp = 28 + 7 * math.sin((hour - 8) * math.pi / 12)
    temp = round(max(18.0, min(38.0, base_temp + random.uniform(-0.8, 0.8))), 1)

    rh_base = 80 - (temp - 20) * 1.5
    rh = int(max(40, min(90, rh_base + random.uniform(-3, 3))))

    if 8 <= hour <= 17:
        co2_base = 800 - (hour - 8) * 35
    else:
        co2_base = 400 + (hour - 17) * 20 if hour > 17 else 400
    co2 = int(max(300, min(1500, co2_base + random.uniform(-25, 25))))

    return {
        "temp":          temp,
        "rh":            rh,
        "co2":           co2,
        "solar":         _mock_solar(hour),
        "solar_is_mock": True,
        "cum_solar":     _cum_solar(hour),
        "timestamp":     now.isoformat(timespec="seconds"),
        "source":        "simulation",
    }


def _mock_solar(frac_hour: float) -> float:
    """Sine-curve solar mock (W/m²) for a fractional hour of day."""
    if 6.0 <= frac_hour <= 18.0:
        return round(max(0.0, 900 * math.sin((frac_hour - 6) * math.pi / 12) + random.uniform(-30, 30)), 1)
    return 0.0


def _cum_solar(frac_hour: float, step: float = 0.5) -> float:
    """Cumulative solar energy from 06:00 to frac_hour via trapezoidal rule (Wh/m²)."""
    if frac_hour < 6.0:
        return 0.0
    total = 0.0
    h = 6.0
    end = min(frac_hour, 18.0)
    while h + step <= end:
        s1 = 900 * math.sin((h - 6) * math.pi / 12)
        s2 = 900 * math.sin((h + step - 6) * math.pi / 12)
        total += (s1 + s2) / 2 * step
        h += step
    return round(max(0.0, total), 0)


def fetch_sensors(url: str = "") -> dict:
    """Main entry point. Uses real greenhouse CSV; falls back to simulation."""
    return fetch_from_csv()


if __name__ == "__main__":
    print("=== 실측 센서 데이터 테스트 ===")
    d = fetch_from_csv()
    _tag = "목업" if d.get("solar_is_mock") else "실측"
    _frozen = " (최신값 고정)" if d.get("is_frozen") else ""
    print(f"  요청시각={d['timestamp']}  데이터시각={d.get('data_timestamp', '-')}{_frozen}")
    print(f"  온도={d['temp']}℃  습도={d['rh']}%  CO2={d['co2']}ppm  "
          f"외부일사({_tag})={d['solar']}W/m²  누적일사={d['cum_solar']}Wh/m²")
    if "outdoor_temp" in d:
        print(f"  외부온도={d['outdoor_temp']}℃  풍속={d['wind_speed']}m/s  강우={d.get('rain')}")
