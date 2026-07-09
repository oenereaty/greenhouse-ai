"""생육 데이터 탭 — 조회/기록 추가/평가/엑셀 내보내기."""
import io

import openpyxl
from fastapi import APIRouter
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from tools.growth_data import add_record, assess_growth, latest, query

router = APIRouter(prefix="/api/growth", tags=["growth"])


class GrowthRecordIn(BaseModel):
    zone: str
    crop_height_cm: float
    leaf_count: int
    fruit_count: int
    truss_count: int
    stem_diameter_mm: float
    truss_height_cm: float | None = None
    notes: str = ""
    record_date: str | None = None


@router.get("")
def list_growth(zone: str = "전체", days: int = 294) -> list[dict]:
    return query(zone=zone, days=days)


@router.get("/latest")
def latest_growth(zone: str = "전체") -> list[dict]:
    return latest(zone=zone)


@router.get("/assessment")
def assessment(zone: str = "전체", trend_days: int = 7, trend_tolerance: int = 3) -> list[dict]:
    return assess_growth(zone=zone, trend_days=trend_days, trend_tolerance=trend_tolerance)


@router.post("")
def create_record(record: GrowthRecordIn) -> dict:
    return add_record(**record.model_dump())


@router.get("/export")
def export(zone: str = "전체", days: int = 294) -> StreamingResponse:
    rows = query(zone=zone, days=days)
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
        headers={"Content-Disposition": "attachment; filename=growth_data.xlsx"},
    )
