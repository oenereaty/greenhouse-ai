"""기상 데이터 탭 — KMA AWS 실황 + 단기예보 + 환기 힌트 + 새로고침(경보 트리거)."""
from fastapi import APIRouter

from backend.cache import cached, invalidate, set_value
from tools.env_calc import sky_info
from tools.kma_api import get_daily_summary, get_short_forecast
from tools.kma_client import fetch_aws, latlon_to_grid, to_outdoor_context, ventilation_hint, DEFAULT_LAT, DEFAULT_LON
from tools.notifier import is_in_cooldown, send_alert_email
from tools.sensor_client import fetch_sensors

router = APIRouter(prefix="/api/weather", tags=["weather"])


def _grid() -> tuple[int, int]:
    return latlon_to_grid(DEFAULT_LAT, DEFAULT_LON)


@router.get("/aws")
def aws() -> dict:
    return cached("weather_aws_raw", ttl_seconds=600, fn=fetch_aws)


@router.get("/forecast")
def forecast() -> list[dict]:
    nx, ny = _grid()
    rows = cached("weather_forecast", ttl_seconds=3600, fn=lambda: get_short_forecast(nx, ny))
    out = []
    for r in rows:
        sky_disp, light = sky_info(r.get("SKY"), r.get("PTY"), r.get("time"))
        out.append({**r, "sky_disp": sky_disp, "light_estimate": light})
    return out


@router.get("/daily-summary")
def daily_summary(days: int = 3) -> list[dict]:
    nx, ny = _grid()
    return cached(f"weather_daily_summary_{days}", ttl_seconds=3600,
                  fn=lambda: get_daily_summary(nx, ny, days=days))


@router.get("/ventilation-hint")
def ventilation_hint_endpoint() -> dict:
    sensor = fetch_sensors()
    aw = cached("weather_aws_raw", ttl_seconds=600, fn=fetch_aws)
    hint = ventilation_hint(to_outdoor_context(aw), indoor_temp=float(sensor["temp"]))
    return {"hint": hint}


@router.post("/refresh")
def refresh() -> dict:
    """'기상 새로고침' 버튼과 end-to-end 동일 — 강제 재조회 + 특보 감지 + 이메일 경보."""
    invalidate("weather_aws_raw")
    aw = fetch_aws()
    set_value("weather_aws_raw", aw)

    warnings: list[str] = []
    if aw.get("rainfall_60m", 0) >= 10:
        warnings.append(f"강수 특보: 60분 강수량 {aw['rainfall_60m']}mm")
    if aw.get("wind_speed", 0) >= 10:
        warnings.append(f"강풍 특보: 풍속 {aw['wind_speed']}m/s")
    if aw.get("temp", 0) >= 35:
        warnings.append(f"고온 특보: 외기 {aw['temp']}℃")
    if aw.get("temp", 0) <= 0:
        warnings.append(f"저온 특보: 외기 {aw['temp']}℃")

    alert_sent = False
    if warnings and not is_in_cooldown():
        try:
            send_alert_email(
                warnings, fetch_sensors(),
                situation="기상 특보 감지", recommendation="즉각 점검이 필요합니다.",
            )
            alert_sent = True
        except Exception:
            pass  # EMAIL_APP_PASSWORD 미설정 등 — 새로고침 자체는 계속 성공으로 처리

    return {
        "aws": aw,
        "outdoor": to_outdoor_context(aw),
        "warnings": warnings,
        "alert_sent": alert_sent,
    }
