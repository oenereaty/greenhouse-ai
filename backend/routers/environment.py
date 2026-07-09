"""환경 데이터 탭 — 센서 현재값/이력, 규칙 기반 위험도(환경+병해충 통합)."""
from fastapi import APIRouter

from backend.cache import cached
from tools import env_calc
from tools.ncpms_client import has_key as ncpms_has_key, search_diseases
from tools.pest_forecast import assess_risk, pest_thumb_map
from tools.pesticide_db import DISEASE_MAP
from tools.sensor_client import fetch_sensors, get_recent_series

router = APIRouter(prefix="/api/environment", tags=["environment"])

_SEV = {"ok": 0, "warn": 1, "danger": 2, "safe": 0, "caution": 1, "risk": 2,
        "낮음": 0, "주의": 1, "높음": 2}


def _with_vpd(row: dict) -> dict:
    return {**row, "vpd": env_calc.calc_vpd(float(row["temp"]), float(row["rh"]))}


def _with_humidity_calcs(row: dict) -> dict:
    temp, rh = float(row["temp"]), float(row["rh"])
    return {
        **row,
        "abs_humidity": env_calc.calc_abs_humidity(temp, rh),
        "saturation_ah": env_calc.calc_saturation_ah(temp),
        "moisture_deficit": env_calc.calc_moisture_deficit(temp, rh),
    }


def _cached_outdoor() -> dict | None:
    """외기 데이터 — weather 라우터(GET /api/weather/aws)와 캐시 키("weather_aws_raw")를
    공유해 KMA API를 중복 호출하지 않는다. 원본(raw) 응답을 캐시해두고 이 함수에서만
    env_interpret이 기대하는 outdoor_* 형태로 매핑한다."""
    def _fetch():
        from tools.kma_client import fetch_aws
        try:
            return fetch_aws()
        except Exception:
            return None
    from tools.kma_client import to_outdoor_context
    raw = cached("weather_aws_raw", ttl_seconds=600, fn=_fetch)
    return to_outdoor_context(raw) if raw else None


@router.get("/current")
def current() -> dict:
    sensor = fetch_sensors()
    row = _with_humidity_calcs(_with_vpd(sensor))
    outdoor = _cached_outdoor()
    if outdoor:
        row["outdoor"] = {
            **outdoor,
            "abs_humidity": env_calc.calc_abs_humidity(outdoor["outdoor_temp"], outdoor["outdoor_rh"]),
            "moisture_deficit": env_calc.calc_moisture_deficit(outdoor["outdoor_temp"], outdoor["outdoor_rh"]),
        }
    else:
        row["outdoor"] = None
    return row


@router.get("/history")
def history(hours: int = 24) -> list[dict]:
    rows = get_recent_series(hours=hours)
    return [_with_vpd(r) for r in rows]


@router.get("/risk")
def risk() -> dict:
    sensor = fetch_sensors()
    temp, rh = float(sensor["temp"]), float(sensor["rh"])
    co2, solar = float(sensor["co2"]), float(sensor.get("solar", 0))
    vpd = env_calc.calc_vpd(temp, rh)
    outdoor = _cached_outdoor()

    interps = env_calc.env_interpret(temp, rh, vpd, int(co2), solar, outdoor=outdoor)
    pest_risks = assess_risk(temp, rh)
    pest_hi = [r for r in pest_risks if r["label"] != "낮음"]

    thumbs: dict[str, str] = {}
    if ncpms_has_key():
        try:
            thumbs = pest_thumb_map(search_diseases("토마토", rows=100))
        except Exception:
            thumbs = {}

    cards = [
        {"icon": c["icon"], "title": c["title"], "body": c["body"],
         "severity": _SEV[c["level"]], "drugs": [], "thumb_url": "", "pathogen_type": ""}
        for c in interps
    ] + [
        {"icon": "🦠", "title": r["name"], "body": f'{r["reason"]} · {r["note"]}',
         "severity": _SEV[r["label"]],
         "drugs": DISEASE_MAP.get(r["name"], {}).get("pesticides", [])[:3],
         "thumb_url": thumbs.get(r["name"], ""),
         "pathogen_type": r.get("pathogen_type", "")}
        for r in pest_hi
    ]
    cards.sort(key=lambda c: -c["severity"])
    overall = max((c["severity"] for c in cards), default=0)

    return {
        "overall_severity": overall,  # 0=안전(초록) 1=주의(노랑) 2=위험(빨강)
        "cards": cards,
        "pest_table": pest_risks,
    }
