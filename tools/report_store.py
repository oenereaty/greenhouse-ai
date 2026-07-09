"""생성된 리포트 스냅샷 저장/조회 — reports/snapshots/*.json."""
import json
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
SNAPSHOT_DIR = BASE_DIR / "reports" / "snapshots"


def save(report: dict) -> str:
    """리포트를 저장하고 report_id를 반환."""
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    period = report["period"]
    report_id = f"{report['generated_at']}_{period['start']}_{period['end']}"
    path = SNAPSHOT_DIR / f"{report_id}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_id


def list_reports() -> list[dict]:
    """저장된 리포트 목록(메타데이터만, 최신순)."""
    if not SNAPSHOT_DIR.exists():
        return []
    items = []
    for path in SNAPSHOT_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        items.append({
            "report_id": path.stem,
            "period": data["period"],
            "generated_at": data["generated_at"],
            "diary_count": len(data.get("diary", [])),
            "disease_count": len(data.get("disease_log", [])),
        })
    items.sort(key=lambda r: r["report_id"], reverse=True)
    return items


def load(report_id: str) -> dict | None:
    path = SNAPSHOT_DIR / f"{report_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
