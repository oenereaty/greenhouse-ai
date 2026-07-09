"""온실 센서 제어 로그 — control_log.json CRUD.

기존 ui/app.py에 인라인으로 있던 _load_ctrl_log/_save_ctrl_log를 다른 tools/*
모듈과 같은 관례(Path(__file__).parent.parent 기준 파일 경로)로 추출한 것.
"""
import json
from datetime import datetime
from pathlib import Path

CONTROL_LOG = Path(__file__).parent.parent / "control_log.json"


def load_all() -> list[dict]:
    if not CONTROL_LOG.exists():
        return []
    try:
        return json.loads(CONTROL_LOG.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(entries: list[dict]) -> None:
    CONTROL_LOG.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")


def add_entry(
    target: str,
    action: str,
    setval: str,
    zone: str,
    reason: str,
    result: str,
    sensor_snapshot: str,
) -> dict:
    entries = load_all()
    entry = {
        "시각":       datetime.now().isoformat(timespec="seconds"),
        "제어 대상":  target,
        "조치":       action,
        "설정값":     setval or "—",
        "구역":       zone,
        "이유":       reason or "—",
        "결과":       result or "—",
        "센서(당시)": sensor_snapshot,
    }
    entries.append(entry)
    _save(entries)
    return entry
