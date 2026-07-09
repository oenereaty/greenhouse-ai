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
    """민감하지 않은 기능 플래그 + 발표용 고정 "오늘" 노출.

    "오늘" 날짜는 tools/demo_clock.py가 유일한 출처다 — 프론트가 new Date()로
    따로 계산하면(예: 영농일지 캘린더의 "오늘" 표시) 센서·생육·기상은 5/18인데
    캘린더만 실제 오늘(7월)을 가리키는 불일치가 생긴다(사용자 확인, 2026-07-10).
    """
    from tools.demo_clock import demo_now

    return {**get_settings().capability_flags(), "today": demo_now().date().isoformat()}
