"""자동 진단 백그라운드 스케줄러 — APScheduler AsyncIOScheduler.

Streamlit의 `st.fragment(run_every="5s")` 폴러를 대체한다. 브라우저 탭이 열려있지
않아도 서버가 살아있는 한 계속 동작한다는 점이 기존 방식보다 개선된 부분이다.

설정({enabled, interval_minutes})은 다른 tools/*.json과 같은 관례로
레포 루트의 auto_diagnosis_settings.json에 저장한다.
"""
import json
import time
from pathlib import Path
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from backend import jobs

REPO_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_FILE = REPO_ROOT / "auto_diagnosis_settings.json"
REPORT_SETTINGS_FILE = REPO_ROOT / "auto_report_settings.json"

_DEFAULT_SETTINGS = {"enabled": False, "interval_minutes": 30}
_JOB_ID = "auto_diagnosis_tick"

_DEFAULT_REPORT_SETTINGS = {"enabled": False, "interval_days": 7}
_REPORT_JOB_ID = "auto_report_tick"

scheduler = AsyncIOScheduler()

# 스케줄러 상태(다음/마지막 실행 시각) — 재시작 시 사라져도 무방(다음 tick에 다시 채워짐)
_status: dict[str, Any] = {"last_run_at": None, "next_run_at": None, "last_job_id": None}
_report_status: dict[str, Any] = {"last_run_at": None, "last_report_id": None}


def load_settings() -> dict:
    if not SETTINGS_FILE.exists():
        return dict(_DEFAULT_SETTINGS)
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        return {**_DEFAULT_SETTINGS, **data}
    except Exception:
        return dict(_DEFAULT_SETTINGS)


def save_settings(enabled: bool, interval_minutes: int) -> dict:
    data = {"enabled": enabled, "interval_minutes": interval_minutes}
    SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    _reschedule(data)
    return data


def get_status() -> dict:
    settings = load_settings()
    job = scheduler.get_job(_JOB_ID)
    return {
        "enabled": settings["enabled"],
        "interval_minutes": settings["interval_minutes"],
        "last_run_at": _status["last_run_at"],
        "next_run_at": job.next_run_time.timestamp() if job and job.next_run_time else None,
        "last_job_id": _status["last_job_id"],
    }


def _run_auto_diagnosis_tick() -> None:
    """실제 진단+조언 로직 — 수동 버튼과 동일한 경로를 job 저장소를 통해 실행."""
    from tools.sensor_client import fetch_sensors
    from tools.kma_client import fetch_aws, to_outdoor_context
    from rag.pipeline import build_vectorstore, diagnose
    from backend.config import get_settings

    settings = get_settings()
    sensor = fetch_sensors()
    try:
        outdoor = to_outdoor_context(fetch_aws())
    except Exception:
        outdoor = None

    col = build_vectorstore()
    result = diagnose(
        temp=float(sensor["temp"]), rh=float(sensor["rh"]),
        co2=float(sensor["co2"]), solar=float(sensor.get("solar", 0)),
        col=col, model=settings.ollama_model, outdoor=outdoor,
    )
    return result


def _tick() -> None:
    job_id = jobs.create_job(_run_auto_diagnosis_tick)
    _status["last_run_at"] = time.time()
    _status["last_job_id"] = job_id


def _reschedule(settings: dict) -> None:
    existing = scheduler.get_job(_JOB_ID)
    if existing:
        existing.remove()
    if settings["enabled"]:
        scheduler.add_job(
            _tick,
            trigger=IntervalTrigger(minutes=settings["interval_minutes"]),
            id=_JOB_ID,
            replace_existing=True,
        )


# ---------------------------------------------------------------------------
# 주기 리포트 자동 생성
# ---------------------------------------------------------------------------

def load_report_settings() -> dict:
    if not REPORT_SETTINGS_FILE.exists():
        return dict(_DEFAULT_REPORT_SETTINGS)
    try:
        data = json.loads(REPORT_SETTINGS_FILE.read_text(encoding="utf-8"))
        return {**_DEFAULT_REPORT_SETTINGS, **data}
    except Exception:
        return dict(_DEFAULT_REPORT_SETTINGS)


def save_report_settings(enabled: bool, interval_days: int) -> dict:
    data = {"enabled": enabled, "interval_days": interval_days}
    REPORT_SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    _reschedule_report(data)
    return data


def get_report_status() -> dict:
    settings = load_report_settings()
    job = scheduler.get_job(_REPORT_JOB_ID)
    return {
        "enabled": settings["enabled"],
        "interval_days": settings["interval_days"],
        "last_run_at": _report_status["last_run_at"],
        "next_run_at": job.next_run_time.timestamp() if job and job.next_run_time else None,
        "last_report_id": _report_status["last_report_id"],
    }


def _run_report_tick() -> None:
    from tools import report_generator, report_store

    settings = load_report_settings()
    report = report_generator.build_report(days=settings["interval_days"])
    report_id = report_store.save(report)
    _report_status["last_run_at"] = time.time()
    _report_status["last_report_id"] = report_id


def _reschedule_report(settings: dict) -> None:
    existing = scheduler.get_job(_REPORT_JOB_ID)
    if existing:
        existing.remove()
    if settings["enabled"]:
        scheduler.add_job(
            _run_report_tick,
            trigger=IntervalTrigger(days=settings["interval_days"]),
            id=_REPORT_JOB_ID,
            replace_existing=True,
        )


def start() -> None:
    scheduler.start()
    _reschedule(load_settings())
    _reschedule_report(load_report_settings())


def shutdown() -> None:
    scheduler.shutdown(wait=False)
