"""공유 job 저장소 — 모든 느린 LLM 호출(90~600초+)이 공통으로 쓰는 submit-and-poll 패턴.

POST 핸들러는 create_job()으로 job_id를 즉시 반환(202)하고, 실제 작업은
asyncio.to_thread로 백그라운드에서 실행한다(동기 requests 기반 Ollama 호출이
이벤트 루프를 막지 않도록). 프론트엔드는 GET /api/jobs/{job_id} 하나만 폴링하면 된다.

단일 사용자 로컬 앱이므로 인메모리 dict로 충분 — 재시작 시 진행 중이던 job은
사라지지만(진단/조언 등은 완료 시 이미 JSON 파일에 저장되므로 데이터 손실은 없음),
이는 규모에 맞는 의도적으로 단순한 선택이다.
"""
import asyncio
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

import anyio

JobStatus = Literal["queued", "running", "done", "error"]


class JobQueueFullError(RuntimeError):
    """동시 실행 job 한도를 초과했을 때만 발생 — main.py에서 429로 변환한다."""

# FastAPI의 동기(def) 라우트 핸들러는 워커 스레드에서 실행되어 asyncio.create_task()를
# 바로 쓸 수 없다(실행 중인 이벤트 루프가 없음). lifespan에서 메인 이벤트 루프를
# 저장해두고 run_coroutine_threadsafe로 스케줄링해 동기/비동기 호출부 모두 지원한다.
_LOOP: asyncio.AbstractEventLoop | None = None


def set_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _LOOP
    _LOOP = loop


@dataclass
class JobRecord:
    id: str
    status: JobStatus = "queued"
    result: Any = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None


_JOBS: dict[str, JobRecord] = {}

# 완료된 job을 무한정 들고 있지 않도록 — 폴링이 끝난 뒷정리용 상한(단순 유지: 개수 기준)
_MAX_FINISHED_JOBS = 200
_MAX_RUNNING_JOBS = 3


def _running_count() -> int:
    return sum(1 for j in _JOBS.values() if j.status in ("queued", "running"))


def _gc_finished() -> None:
    finished = [j for j in _JOBS.values() if j.status in ("done", "error")]
    if len(finished) <= _MAX_FINISHED_JOBS:
        return
    finished.sort(key=lambda j: j.finished_at or 0)
    for j in finished[: len(finished) - _MAX_FINISHED_JOBS]:
        _JOBS.pop(j.id, None)


def get_job(job_id: str) -> JobRecord | None:
    return _JOBS.get(job_id)


def create_job(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> str:
    """fn(*args, **kwargs)를 백그라운드 스레드에서 실행하고 즉시 job_id를 반환.

    fn은 동기 함수(예: rag.pipeline.diagnose, advisor.generate_advice, agent.ask의
    동기 래퍼)여야 한다. 호출 시점에 실행 중인 이벤트 루프가 있어야 한다(FastAPI
    요청 핸들러 내부에서 호출).
    """
    if _running_count() >= _MAX_RUNNING_JOBS:
        raise JobQueueFullError("현재 실행 중인 작업이 많습니다. 잠시 후 다시 시도하세요.")

    job_id = uuid.uuid4().hex
    record = JobRecord(id=job_id)
    _JOBS[job_id] = record

    async def _run() -> None:
        record.status = "running"
        record.started_at = time.time()
        try:
            result = await anyio.to_thread.run_sync(lambda: fn(*args, **kwargs))
            record.result = result
            record.status = "done"
        except Exception as e:
            print(f"[jobs] {job_id} failed:\n{traceback.format_exc()}")
            record.error = f"{type(e).__name__}: {e}"
            record.status = "error"
        finally:
            record.finished_at = time.time()
            _gc_finished()

    if _LOOP is None:
        raise RuntimeError("jobs.set_event_loop()가 앱 시작 시 호출되지 않았습니다.")
    asyncio.run_coroutine_threadsafe(_run(), _LOOP)
    return job_id
