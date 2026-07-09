"""온실 제어 탭 — 진단/조치 제안(job), 자동진단 설정, 이메일 경보, 제어 로그."""
import io

import openpyxl
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from backend import jobs, scheduler
from backend.cache import cached
from backend.config import get_settings
from tools import control_log
from tools.env_calc import calc_vpd
from tools.kma_client import fetch_aws, to_outdoor_context
from tools.notifier import cooldown_remaining_min, is_in_cooldown, send_alert_email
from tools.sensor_client import fetch_sensors

router = APIRouter(prefix="/api/control", tags=["control"])


def _current_outdoor() -> dict | None:
    raw = cached("weather_aws_raw", ttl_seconds=600, fn=lambda: _safe(fetch_aws))
    return to_outdoor_context(raw) if raw else None


def _safe(fn):
    try:
        return fn()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 진단 / 조치 제안 (job)
# ---------------------------------------------------------------------------

def _run_diagnosis() -> dict:
    from rag.pipeline import build_vectorstore, diagnose

    settings = get_settings()
    sensor = fetch_sensors()
    outdoor = _current_outdoor()
    col = build_vectorstore()
    return diagnose(
        temp=float(sensor["temp"]), rh=float(sensor["rh"]),
        co2=float(sensor["co2"]), solar=float(sensor.get("solar", 0)),
        col=col, model=settings.ollama_model, outdoor=outdoor,
    )


def _growth_context() -> str:
    """구역별 화방높이 균형 판정 + 초장·줄기두께 전 주 대비 추세를 한 줄 요약.

    generate_advice()의 LLM 프롬프트에 실측 생육 신호를 실어 보내기 위함
    (착과 여부만 보던 이전 온실제어 조치추천은 생육 데이터를 전혀 참조하지
    않았음 — 이 함수가 그 연결점).
    """
    from tools.growth_data import assess_growth

    rows = assess_growth("전체")
    parts = []
    for r in rows:
        bits = []
        status = r.get("truss_status")
        if status:
            bits.append(f"화방높이 {status}")
        height_trend = r.get("crop_height_cm_trend")
        if height_trend is not None:
            bits.append(f"초장 {height_trend:+.1f}cm/주")
        stem_trend = r.get("stem_diameter_mm_trend")
        if stem_trend is not None:
            bits.append(f"줄기두께 {stem_trend:+.1f}mm/주")
        if bits:
            parts.append(f"{r.get('zone')}구역 " + ", ".join(bits))
    return " / ".join(parts)


def _run_advice() -> dict:
    from rag.pipeline import build_vectorstore, search
    from tools.advisor import generate_advice

    settings = get_settings()
    sensor = fetch_sensors()
    outdoor = _current_outdoor()
    temp, rh = float(sensor["temp"]), float(sensor["rh"])
    vpd = calc_vpd(temp, rh)
    col = build_vectorstore()
    docs = search(col, f"온도{temp}℃ VPD{vpd}kPa CO2{int(float(sensor['co2']))}ppm", n_results=3)
    rag_ctx = "\n\n".join(f"[{d['meta'].get('source_file')}] {d['text'][:300]}" for d in docs)
    growth_ctx = _growth_context()
    return generate_advice(
        sensor=sensor, outdoor=outdoor, rag_context=rag_ctx,
        model=settings.ollama_model, growth_context=growth_ctx,
    )


def _run_diagnosis_with_advice() -> dict:
    diagnosis = _run_diagnosis()
    advice = _run_advice()
    return {"diagnosis": diagnosis, "advice": advice}


@router.get("/diagnosis/history")
def diagnosis_history(n: int = 10) -> list[dict]:
    from rag.pipeline import load_decisions
    return load_decisions()[-n:][::-1]


@router.post("/diagnosis")
def submit_diagnosis() -> dict:
    return {"job_id": jobs.create_job(_run_diagnosis)}


@router.post("/advice")
def submit_advice() -> dict:
    return {"job_id": jobs.create_job(_run_advice)}


@router.post("/diagnosis-with-advice")
def submit_diagnosis_with_advice() -> dict:
    return {"job_id": jobs.create_job(_run_diagnosis_with_advice)}


class AdviceResponseIn(BaseModel):
    advice: dict
    response: str  # "y" | "n" | 자유 텍스트


@router.post("/advice/response")
def advice_response(body: AdviceResponseIn) -> dict:
    from tools.advisor import save_response
    from rag.pipeline import update_latest_decision_action

    entry = save_response(body.advice, body.response)
    decision = update_latest_decision_action(body.response, body.advice)
    return {"advice_log": entry, "decision": decision}


@router.get("/advice/log")
def advice_log(n: int = 20) -> list[dict]:
    from tools.advisor import load_log
    return load_log(n)


# ---------------------------------------------------------------------------
# 자동 진단 스케줄
# ---------------------------------------------------------------------------

class AutoDiagnosisSettingsIn(BaseModel):
    enabled: bool
    interval_minutes: int


@router.get("/auto-diagnosis/settings")
def get_auto_settings() -> dict:
    return scheduler.load_settings()


@router.put("/auto-diagnosis/settings")
def put_auto_settings(body: AutoDiagnosisSettingsIn) -> dict:
    if body.interval_minutes not in {30, 60, 90}:
        body.interval_minutes = 30
    return scheduler.save_settings(body.enabled, body.interval_minutes)


@router.get("/auto-diagnosis/status")
def auto_status() -> dict:
    return scheduler.get_status()


# ---------------------------------------------------------------------------
# 이메일 경보
# ---------------------------------------------------------------------------

@router.get("/email-alert/status")
def email_status() -> dict:
    return {"in_cooldown": is_in_cooldown(), "cooldown_remaining_min": cooldown_remaining_min()}


@router.post("/email-alert/test")
def email_test() -> dict:
    sensor = fetch_sensors()
    try:
        send_alert_email(
            ["테스트 경보"], sensor,
            situation="이메일 연동 테스트",
            recommendation="이 메시지가 수신되면 설정 완료입니다.",
        )
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return {"sent": True}


# ---------------------------------------------------------------------------
# 센서 제어 로그
# ---------------------------------------------------------------------------

class ControlLogIn(BaseModel):
    target: str
    action: str
    setval: str = ""
    zone: str = "전체"
    reason: str = ""
    result: str = ""


@router.get("/log")
def get_control_log() -> list[dict]:
    return control_log.load_all()


@router.post("/log")
def post_control_log(body: ControlLogIn) -> dict:
    sensor = fetch_sensors()
    temp, rh = float(sensor["temp"]), float(sensor["rh"])
    vpd = calc_vpd(temp, rh)
    snapshot = f"온도 {temp}℃ / 습도 {rh}% / VPD {vpd}kPa"
    return control_log.add_entry(
        body.target, body.action, body.setval, body.zone, body.reason, body.result, snapshot,
    )


@router.get("/log/export")
def export_control_log() -> StreamingResponse:
    rows = control_log.load_all()
    wb = openpyxl.Workbook()
    ws = wb.active
    if rows:
        ws.append(list(rows[0].keys()))
        for r in rows:
            ws.append(list(r.values()))
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=control_log.xlsx"},
    )
