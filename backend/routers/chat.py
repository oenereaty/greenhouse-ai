"""AI 상담 탭 — 이미지 병해진단(job), NCPMS 도감, MCP 기반 자유 채팅(job)."""
import base64

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel

from backend import jobs
from backend.cache import cached
from backend.config import get_settings
from tools.ncpms_client import disease_detail, has_key as ncpms_has_key, search_diseases

router = APIRouter(prefix="/api/chat", tags=["chat"])


# ---------------------------------------------------------------------------
# 이미지 병해진단
# ---------------------------------------------------------------------------

@router.post("/diagnose-image")
async def diagnose_image(file: UploadFile = File(...), question: str = Form("")) -> dict:
    from backend.jobs_impl import run_image_diagnosis

    image_bytes = await file.read()
    image_b64 = base64.b64encode(image_bytes).decode()
    job_id = jobs.create_job(run_image_diagnosis, image_b64, question)
    return {"job_id": job_id}


# ---------------------------------------------------------------------------
# NCPMS 병해충 도감
# ---------------------------------------------------------------------------

@router.get("/ncpms/search")
def ncpms_search(crop: str = "토마토", rows: int = 100, start: int = 1) -> list[dict]:
    if not ncpms_has_key():
        return []
    return cached(f"ncpms_search_{crop}_{rows}_{start}", ttl_seconds=86400,
                  fn=lambda: search_diseases(crop, rows=rows, start=start))


@router.get("/ncpms/{sick_key}")
def ncpms_detail(sick_key: str) -> dict:
    return cached(f"ncpms_detail_{sick_key}", ttl_seconds=86400,
                  fn=lambda: disease_detail(sick_key))


# ---------------------------------------------------------------------------
# 자유 채팅 (MCP 에이전트 tool-calling 루프)
# ---------------------------------------------------------------------------

def _run_chat_message(question: str) -> str:
    from agent.agent import ask as mcp_ask
    from backend.routers.control import _current_outdoor
    from rag.pipeline import build_vectorstore, search
    from tools.sensor_client import fetch_sensors

    settings = get_settings()
    col = build_vectorstore()
    docs = search(col, question, n_results=4)
    rag_ctx = "\n\n".join(f"[{d['meta'].get('source_file')}]\n{d['text'][:400]}" for d in docs)

    from datetime import date as _date

    sd = fetch_sensors()
    outdoor = _current_outdoor()
    env_ctx = (
        f"[오늘 날짜] {_date.today().isoformat()}\n"
        f"[현재 센서값] 온도 {sd.get('temp')}℃ 습도 {sd.get('rh')}% "
        f"CO2 {sd.get('co2')}ppm 일사 {sd.get('solar')}W/m²"
    )
    if outdoor:
        env_ctx += f"\n[외기 조건] {outdoor.get('outdoor_temp', '?')}℃ 풍속 {outdoor.get('wind_speed', '?')}m/s"

    full_ctx = f"{env_ctx}\n\n{rag_ctx}" if rag_ctx else env_ctx
    return mcp_ask(question, rag_context=full_ctx, model=settings.ollama_model)


class ChatMessageIn(BaseModel):
    question: str


@router.post("/message")
def submit_message(body: ChatMessageIn) -> dict:
    return {"job_id": jobs.create_job(_run_chat_message, body.question)}
