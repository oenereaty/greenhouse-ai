"""양액 조성 기록 CRUD — nutrient_log.json 기반. 날짜별 여러 건 구조.

저장 구조:
    { "YYYY-MM-DD": [
        {"time": "HH:MM", "recipe": {"n": float, "p": float, "k": float,
         "ca": float, "mg": float, "ec": float, "ph": float},
         "symptom": str, "ai_analysis": str, "updated": "YYYY-MM-DD"},
        ...
    ] }
"""
import json
from datetime import date, datetime
from pathlib import Path

NUTRIENT_LOG_FILE = Path(__file__).parent.parent / "nutrient_log.json"


def _read() -> dict:
    if not NUTRIENT_LOG_FILE.exists():
        return {}
    try:
        return json.loads(NUTRIENT_LOG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write(data: dict) -> None:
    NUTRIENT_LOG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_all() -> dict:
    """전체 양액 기록 반환 {날짜: [entry, ...]}."""
    return _read()


def day_entries(date_str: str) -> list:
    """특정 날짜의 기록 목록 (시간순)."""
    return sorted(_read().get(date_str, []), key=lambda e: e.get("time", ""))


def flat_entries(limit: int | None = None) -> list:
    """전체 기록을 날짜 내림차순으로 평면화 (비교/조회용)."""
    data = _read()
    rows = []
    for d, entries in data.items():
        for e in entries:
            rows.append({"date": d, **e})
    rows.sort(key=lambda r: (r["date"], r.get("time", "")), reverse=True)
    return rows[:limit] if limit else rows


def add_entry(date_str: str, recipe: dict, symptom: str = "", ai_analysis: str = "") -> int:
    """해당 날짜에 양액 조성 기록 1건 추가. 추가된 항목의 인덱스를 반환."""
    data = _read()
    entry = {
        "time": datetime.now().strftime("%H:%M"),
        "recipe": recipe,
        "symptom": symptom or "",
        "ai_analysis": ai_analysis or "",
        "updated": date.today().isoformat(),
    }
    data.setdefault(date_str, []).append(entry)
    _write(data)
    return len(data[date_str]) - 1


def update_analysis(date_str: str, idx: int, ai_analysis: str) -> None:
    """기록의 AI 분석 결과만 갱신."""
    data = _read()
    entries = data.get(date_str, [])
    if 0 <= idx < len(entries):
        entries[idx]["ai_analysis"] = ai_analysis
        _write(data)


def delete_entry(date_str: str, idx: int) -> None:
    """해당 날짜의 idx번째 기록 삭제. 비면 날짜 키 제거."""
    data = _read()
    entries = data.get(date_str, [])
    if 0 <= idx < len(entries):
        entries.pop(idx)
    if entries:
        data[date_str] = entries
    else:
        data.pop(date_str, None)
    _write(data)


if __name__ == "__main__":
    idx = add_entry(
        date.today().isoformat(),
        {"n": 150, "p": 50, "k": 200, "ca": 150, "mg": 40, "ec": 2.2, "ph": 6.0},
        symptom="잎끝 마름 증상 관찰",
    )
    print("added idx:", idx)
    print(day_entries(date.today().isoformat()))
    delete_entry(date.today().isoformat(), idx)
    print("after delete:", day_entries(date.today().isoformat()))
