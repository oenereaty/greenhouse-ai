"""영농일지 CRUD — diary.json 기반 저장. 하루 여러 건(시간별) 구조.

저장 구조:
    { "YYYY-MM-DD": [
        {"time": "HH:MM", "content": str, "tags": [str], "pesticides": [str], "updated": "YYYY-MM-DD"},
        ...
    ] }

구(舊) 형식(날짜당 단건 dict)과 memo_log.json(리스트)은 최초 load 시 자동 병합.
"""
import csv
import io
import json
import re
import uuid
from datetime import datetime
from pathlib import Path

from tools.demo_clock import demo_now

DIARY_FILE = Path(__file__).parent.parent / "diary.json"
_MEMO_FILE = Path(__file__).parent.parent / "memo_log.json"
_PEST_LOG_FILE = Path(__file__).parent.parent / "pest_log.json"
ATTACH_DIR = Path(__file__).parent.parent / "attachments"
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SAFE_SUFFIXES = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp",
    ".pdf", ".txt", ".csv", ".xlsx", ".xls",
}
_MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024

_migrated = False


# ---------------------------------------------------------------------------
# 내부 IO
# ---------------------------------------------------------------------------

def _read_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write(data: dict) -> None:
    DIARY_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _entry(time_str: str, content: str, tags, pesticides, updated: str, attachments=None) -> dict:
    return {
        "time":        time_str or "",
        "content":     content or "",
        "tags":        list(tags or []),
        "pesticides":  list(pesticides or []),
        "attachments": list(attachments or []),
        "updated":     updated,
    }


# ---------------------------------------------------------------------------
# 마이그레이션 (구 형식 + memo_log → 신 구조)
# ---------------------------------------------------------------------------

def _normalize(raw: dict) -> tuple[dict, bool]:
    """구 형식(날짜:dict)을 신 형식(날짜:list)으로 변환. (data, changed) 반환."""
    changed = False
    out: dict = {}
    for d, v in (raw or {}).items():
        if isinstance(v, list):
            out[d] = v
        elif isinstance(v, dict):
            # 단건 dict → 리스트 (빈 내용은 제외)
            if (v.get("content") or "").strip() or v.get("tags"):
                out[d] = [_entry(v.get("time", ""), v.get("content", ""),
                                 v.get("tags"), v.get("pesticides"),
                                 v.get("updated", d))]
            changed = True
    return out, changed


def _migrate() -> None:
    """최초 1회: diary(단건) + memo_log(리스트)를 신 구조로 병합. 원본 백업."""
    raw = _read_json(DIARY_FILE) or {}
    data, changed = _normalize(raw)

    memo = _read_json(_MEMO_FILE)
    if isinstance(memo, list) and memo:
        for m in memo:
            d = m.get("date")
            if not d:
                continue
            data.setdefault(d, []).append(
                _entry(m.get("time", ""), m.get("content", ""),
                       m.get("tags"), m.get("pesticides"), m.get("date", d))
            )
        changed = True
        try:  # memo_log 백업 후 비활성화 (재병합 방지)
            _MEMO_FILE.rename(_MEMO_FILE.with_suffix(".json.migrated"))
        except Exception:
            pass

    # 구(舊) 방제 기록(pest_log.json)을 영농일지 기록으로 흡수
    pest_log = _read_json(_PEST_LOG_FILE)
    if isinstance(pest_log, list) and pest_log:
        for p in pest_log:
            d = p.get("일자")
            if not d:
                continue
            zone = p.get("구역", "전체")
            target = p.get("병해충", "")
            chem = p.get("약품명", "")
            content = f"[{zone}구역] {target} 방제 — {chem}".strip()
            data.setdefault(d, []).append(
                _entry("", content, [target, "방제"], [chem], p.get("입력 시각", d)[:10] or d)
            )
        changed = True
        try:  # pest_log 백업 후 비활성화 (재병합 방지)
            _PEST_LOG_FILE.rename(_PEST_LOG_FILE.with_suffix(".json.migrated"))
        except Exception:
            pass

    if changed:
        bak = DIARY_FILE.with_suffix(".json.bak")
        if raw and not bak.exists():
            bak.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        _write(data)


def _ensure_migrated() -> None:
    global _migrated
    if not _migrated:
        _migrated = True
        _migrate()


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------

def load_all() -> dict:
    """전체 일지 반환 {날짜: [entry, ...]}. 구 형식은 자동 정규화."""
    _ensure_migrated()
    raw = _read_json(DIARY_FILE) or {}
    data, _ = _normalize(raw)
    return data


def day_entries(date_str: str) -> list:
    """특정 날짜의 기록 목록 (시간순)."""
    entries = load_all().get(date_str, [])
    return sorted(entries, key=lambda e: e.get("time", ""))


def add_entry(date_str: str, content: str,
              tags: list[str] | None = None,
              pesticides: list[str] | None = None,
              attachments: list[str] | None = None) -> None:
    """해당 날짜에 시간(현재)과 함께 기록 1건 추가. attachments는 ATTACH_DIR 내 저장된 파일명 목록."""
    data = load_all()
    data.setdefault(date_str, []).append(
        _entry(datetime.now().strftime("%H:%M"), content, tags, pesticides,
               demo_now().date().isoformat(), attachments)
    )
    _write(data)


def save_attachment(date_str: str, filename: str, file_bytes: bytes) -> str:
    """업로드된 파일을 ATTACH_DIR에 저장하고, 충돌 없는 저장 파일명을 반환."""
    if not _DATE_RE.match(date_str):
        raise ValueError("date_str must be YYYY-MM-DD")
    if len(file_bytes) > _MAX_ATTACHMENT_BYTES:
        raise ValueError("attachment is too large")

    ATTACH_DIR.mkdir(exist_ok=True)
    suffix = Path(filename).suffix.lower()
    if suffix not in _SAFE_SUFFIXES:
        raise ValueError("unsupported attachment type")

    stored_name = f"{date_str}_{uuid.uuid4().hex}{suffix}"
    path = (ATTACH_DIR / stored_name).resolve()
    attach_root = ATTACH_DIR.resolve()
    if attach_root not in path.parents:
        raise ValueError("invalid attachment path")

    path.write_bytes(file_bytes)
    return stored_name


def attachment_path(stored_name: str) -> Path:
    """저장된 첨부파일명을 실제 경로로 변환하되 ATTACH_DIR 밖 접근을 차단."""
    if Path(stored_name).name != stored_name:
        raise ValueError("invalid attachment name")
    path = (ATTACH_DIR / stored_name).resolve()
    attach_root = ATTACH_DIR.resolve()
    if attach_root not in path.parents:
        raise ValueError("invalid attachment path")
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(stored_name)
    return path


def delete_entry(date_str: str, idx: int) -> None:
    """해당 날짜의 idx번째(시간순) 기록 삭제. 비면 날짜 키 제거."""
    data = load_all()
    entries = sorted(data.get(date_str, []), key=lambda e: e.get("time", ""))
    if 0 <= idx < len(entries):
        entries.pop(idx)
    if entries:
        data[date_str] = entries
    else:
        data.pop(date_str, None)
    _write(data)


def day_tags(date_str: str) -> list[str]:
    """해당 날짜 전체 기록의 태그 합산(중복 제거, 순서 유지)."""
    tags: list[str] = []
    for e in day_entries(date_str):
        tags.extend(e.get("tags") or [])
    return list(dict.fromkeys(tags))


def to_csv() -> str:
    """전체 일지를 평면화한 CSV 문자열."""
    data = load_all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["날짜", "시간", "내용", "태그", "약품", "수정일"])
    for d in sorted(data):
        for e in sorted(data[d], key=lambda x: x.get("time", "")):
            writer.writerow([
                d,
                e.get("time", ""),
                e.get("content", ""),
                ", ".join(e.get("tags", [])),
                ", ".join(e.get("pesticides", [])),
                e.get("updated", ""),
            ])
    return buf.getvalue()
