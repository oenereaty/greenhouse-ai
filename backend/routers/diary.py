"""메모·일지 탭 — 영농일지 CRUD/첨부, 수확 목표일, 다가오는 계획(job), 양액 로그(job)."""
from datetime import date, timedelta
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel
from starlette.responses import FileResponse, PlainTextResponse

from backend import jobs
from tools import diary_data, goal_manager, nutrient_log
from tools.pesticide_db import AUTOCOMPLETE_TERMS, DISEASE_MAP, detect_all_tags, detect_diseases, get_autocomplete

router = APIRouter(prefix="/api/diary", tags=["diary"])


# ---------------------------------------------------------------------------
# 일지 CRUD
# ---------------------------------------------------------------------------

@router.get("")
def get_diary(date_str: str | None = None) -> dict | list:
    if date_str:
        return diary_data.day_entries(date_str)
    return diary_data.load_all()


class DiaryEntryIn(BaseModel):
    date: str
    content: str
    tags: list[str] = []
    pesticides: list[str] = []
    attachments: list[dict] = []  # [{stored_name, original_name}, ...]


@router.post("")
def add_diary_entry(body: DiaryEntryIn) -> dict:
    diary_data.add_entry(body.date, body.content, body.tags, body.pesticides, body.attachments)
    return {"ok": True}


@router.delete("/{date_str}/{idx}")
def delete_diary_entry(date_str: str, idx: int) -> dict:
    diary_data.delete_entry(date_str, idx)
    return {"ok": True}


@router.get("/tags")
def get_tags(date_str: str) -> list[str]:
    return diary_data.day_tags(date_str)


class DetectTagsIn(BaseModel):
    text: str


@router.post("/detect-tags")
def detect_tags(body: DetectTagsIn) -> dict:
    diseases = detect_diseases(body.text)
    return {
        "tags": detect_all_tags(body.text),
        "diseases": diseases,
        "disease_info": {
            d: {"desc": DISEASE_MAP[d]["desc"], "pesticides": DISEASE_MAP[d]["pesticides"]}
            for d in diseases
        },
    }


@router.get("/autocomplete")
def autocomplete(prefix: str, max_results: int = 6) -> list[str]:
    return get_autocomplete(prefix, max_results=max_results)


@router.get("/autocomplete-terms")
def autocomplete_terms() -> list[str]:
    """고스트텍스트 에디터가 클라이언트에서 매칭할 전체 자동완성 후보 목록."""
    return AUTOCOMPLETE_TERMS


@router.get("/export", response_class=PlainTextResponse)
def export_csv() -> str:
    return diary_data.to_csv()


# ---------------------------------------------------------------------------
# 첨부파일 — {stored_name, original_name} 쌍으로 저장(레거시 문자열 목록도 계속 지원)
# ---------------------------------------------------------------------------

@router.post("/{date_str}/attachments")
async def upload_attachment(date_str: str, file: UploadFile = File(...)) -> dict:
    content = await file.read()
    try:
        stored_name = diary_data.save_attachment(date_str, file.filename or "file", content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"stored_name": stored_name, "original_name": file.filename or stored_name}


@router.get("/attachments/{stored_name}")
def get_attachment(stored_name: str) -> FileResponse:
    try:
        path = diary_data.attachment_path(stored_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="첨부파일을 찾을 수 없습니다.") from e
    return FileResponse(path)


# ---------------------------------------------------------------------------
# 수확 목표일 / D-day / 생육 단계
# ---------------------------------------------------------------------------

@router.get("/harvest-status")
def harvest_status() -> dict:
    settings = goal_manager.load()
    harvest_date = settings.get("harvest_date")
    dd = goal_manager.dday(harvest_date)
    stage = goal_manager.harvest_stage(dd)
    return {"harvest_date": harvest_date, "dday": dd, "stage": stage}


class HarvestDateIn(BaseModel):
    harvest_date: str | None = None


@router.post("/harvest-date")
def set_harvest_date(body: HarvestDateIn) -> dict:
    goal_manager.set_harvest_date(body.harvest_date)
    return {"ok": True}


# ---------------------------------------------------------------------------
# 다가오는 계획 AI 준비사항 확인 (job, 날짜별 캐시)
# ---------------------------------------------------------------------------

_PLAN_CHECK_CACHE: dict[str, str] = {}


@router.get("/plan-check/upcoming")
def upcoming_plan() -> dict | None:
    """앞으로 60일 내 가장 가까운, 내용이 있는 일정을 찾아 반환.

    발표용 고정 날짜(tools/demo_clock)를 일부러 안 쓴다 — 영농일지는 실제 시간
    기준으로 쌓인 완료 기록이라, "오늘=2026-05-18"로 맞추면 7월에 실제로 끝난
    방제·수확 기록이 "다가오는 계획"으로 잘못 표시된다(2026-07-10 확인 — 진딧물
    방제 완료 기록이 "45일 후 계획"처럼 보임). 이 기능만 실제 오늘 기준으로
    두면 그런 항목이 안 나온다.
    """
    entries = diary_data.load_all()
    today_str = date.today().isoformat()
    cutoff = (date.today() + timedelta(days=60)).isoformat()
    future_dates = sorted(d for d in entries if today_str < d <= cutoff)
    for d in future_dates:
        summary = " / ".join(e.get("content", "") for e in entries[d] if e.get("content", "").strip())
        if summary:
            days_left = (date.fromisoformat(d) - date.today()).days
            return {"date": d, "summary": summary, "days_left": days_left,
                     "cached_result": _PLAN_CHECK_CACHE.get(d)}
    return None


class PlanCheckIn(BaseModel):
    date: str
    summary: str
    days_left: int


@router.post("/plan-check")
def submit_plan_check(body: PlanCheckIn) -> dict:
    from backend.jobs_impl import run_plan_check

    def _run():
        result = run_plan_check(body.date, body.summary, body.days_left)
        _PLAN_CHECK_CACHE[body.date] = result
        return result

    return {"job_id": jobs.create_job(_run)}


class PlanCheckFeedbackIn(BaseModel):
    date: str
    summary: str
    days_left: int
    feedback: str


@router.post("/plan-check/feedback")
def submit_plan_check_feedback(body: PlanCheckFeedbackIn) -> dict:
    """농가가 이전 체크리스트에 남긴 의견을 반영해 다시 답변(job)."""
    from backend.jobs_impl import run_plan_check_feedback

    prev = _PLAN_CHECK_CACHE.get(body.date, "")

    def _run():
        result = run_plan_check_feedback(body.date, body.summary, body.days_left, prev, body.feedback)
        _PLAN_CHECK_CACHE[body.date] = result
        return result

    return {"job_id": jobs.create_job(_run)}


# ---------------------------------------------------------------------------
# 양액 조성 기록
# ---------------------------------------------------------------------------

class NutrientRecipeIn(BaseModel):
    date: str
    recipe: dict = {}
    symptom: str = ""
    mix: list[dict] | None = None  # [{"product": str, "grams": float}, ...]
    water_liters: float | None = None


@router.get("/nutrient")
def get_nutrient(date_str: str | None = None, flat_limit: int | None = None) -> list:
    if date_str:
        return nutrient_log.day_entries(date_str)
    return nutrient_log.flat_entries(limit=flat_limit)


@router.post("/nutrient")
def add_nutrient(body: NutrientRecipeIn) -> dict:
    idx = nutrient_log.add_entry(body.date, body.recipe, body.symptom, mix=body.mix, water_liters=body.water_liters)
    return {"idx": idx}


@router.post("/nutrient/{date_str}/{idx}/analyze")
def analyze_nutrient(date_str: str, idx: int, body: NutrientRecipeIn) -> dict:
    from backend.jobs_impl import run_nutrient_analysis
    job_id = jobs.create_job(run_nutrient_analysis, date_str, idx, body.recipe, body.symptom)
    return {"job_id": job_id}


# ---------------------------------------------------------------------------
# 비료 제품 DB — 그램수 → ppm 환산용 보증성분표
# ---------------------------------------------------------------------------

@router.get("/fertilizer-products")
def list_fertilizer_products() -> dict:
    from tools.fertilizer_db import all_products
    return all_products()


class FertilizerProductIn(BaseModel):
    name: str
    n: float = 0.0
    p2o5: float = 0.0
    k2o: float = 0.0
    cao: float = 0.0
    mgo: float = 0.0


@router.post("/fertilizer-products")
def add_fertilizer_product(body: FertilizerProductIn) -> dict:
    from tools.fertilizer_db import register_product
    register_product(body.name, body.n, body.p2o5, body.k2o, body.cao, body.mgo)
    return {"ok": True}


@router.delete("/fertilizer-products/{name}")
def remove_fertilizer_product(name: str) -> dict:
    from tools.fertilizer_db import delete_product
    delete_product(name)
    return {"ok": True}
