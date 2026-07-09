"""공유 job 폴링 엔드포인트 + 헬스체크 + 기능 플래그."""
import time
from typing import Any, Literal

import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend import jobs
from backend.config import get_settings

router = APIRouter(tags=["system"])

_START_TIME = time.time()


class JobStatusResponse(BaseModel):
    id: str
    status: Literal["queued", "running", "done", "error"]
    result: Any | None = None
    error: str | None = None
    elapsed_seconds: float | None = None


@router.get("/api/jobs/{job_id}", response_model=JobStatusResponse)
def get_job_status(job_id: str) -> JobStatusResponse:
    record = jobs.get_job(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="job을 찾을 수 없습니다.")
    elapsed = None
    if record.started_at:
        end = record.finished_at or time.time()
        elapsed = round(end - record.started_at, 1)
    return JobStatusResponse(
        id=record.id, status=record.status, result=record.result,
        error=record.error, elapsed_seconds=elapsed,
    )


@router.get("/api/system/health")
def health() -> dict:
    settings = get_settings()
    try:
        resp = requests.get(f"{settings.ollama_host}/api/tags", timeout=3)
        ollama_ok = resp.status_code == 200
    except Exception:
        ollama_ok = False
    return {
        "status": "ok",
        "uptime_seconds": round(time.time() - _START_TIME, 1),
        "ollama_reachable": ollama_ok,
    }


@router.get("/api/system/config")
def config() -> dict:
    """민감하지 않은 기능 플래그만 노출 — 프론트엔드가 키 없는 기능을 우아하게 숨기도록."""
    return get_settings().capability_flags()
