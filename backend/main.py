"""FastAPI 진입점.

uvicorn backend.main:app --reload  (레포 루트에서 실행 — tools/rag/agent가
Path(__file__).parent.parent 로 데이터 파일을 찾으므로 실행 위치가 중요하다)
"""
import asyncio
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend import jobs, scheduler
from backend.auth import verify_api_key
from backend.config import get_settings
from backend.jobs import JobQueueFullError


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 동기 라우트 핸들러에서도 job을 스케줄링할 수 있도록 메인 이벤트 루프를 등록
    jobs.set_event_loop(asyncio.get_running_loop())

    # BGE-M3 임베딩 모델 + Chroma 컬렉션을 프로세스 수명 동안 1회만 로드(무거운 초기화)
    from rag.pipeline import build_vectorstore
    app.state.col_db = build_vectorstore()

    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown()


app = FastAPI(title="Greenhouse AI API", lifespan=lifespan, dependencies=[Depends(verify_api_key)])

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(JobQueueFullError)
async def job_queue_full_handler(request: Request, exc: JobQueueFullError) -> JSONResponse:
    return JSONResponse(status_code=429, content={"detail": str(exc)})


def _register_routers() -> None:
    from backend.routers import system, environment, growth, weather, prices, control, chat, diary, reports
    app.include_router(system.router)
    app.include_router(environment.router)
    app.include_router(growth.router)
    app.include_router(weather.router)
    app.include_router(prices.router)
    app.include_router(control.router)
    app.include_router(chat.router)
    app.include_router(diary.router)
    app.include_router(reports.router)


_register_routers()
