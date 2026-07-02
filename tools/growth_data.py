"""Growth data handler: read/write CSV, query by zone and date range."""
import csv
import random
from datetime import date, datetime, timedelta
from pathlib import Path

GROWTH_CSV = Path(__file__).parent.parent / "growth_data.csv"
_SAMPLE_FLAG = Path(__file__).parent.parent / ".growth_data_is_sample"

COLUMNS = [
    "date", "zone", "crop_height_cm", "leaf_count",
    "fruit_count", "truss_count", "stem_diameter_mm", "notes",
]


def ensure_sample_csv():
    """Create a sample CSV if none exists."""
    if GROWTH_CSV.exists():
        return
    rows = []
    zones = ["A", "B", "C"]
    start = date.today() - timedelta(days=29)
    for i in range(30):
        d = start + timedelta(days=i)
        for zone in zones:
            rows.append({
                "date": d.isoformat(),
                "zone": zone,
                "crop_height_cm": round(30 + i * 1.2 + random.uniform(-2, 2), 1),
                "leaf_count": max(8, 14 + i // 3 + random.randint(-1, 1)),
                "fruit_count": max(0, i // 5 + random.randint(0, 2)),
                "truss_count": max(1, 2 + i // 10),
                "stem_diameter_mm": round(8 + i * 0.05 + random.uniform(-0.3, 0.3), 1),
                "notes": "정상" if random.random() > 0.1 else "생육 지연 관찰",
            })
    with GROWTH_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    _SAMPLE_FLAG.touch()
    print(f"[growth] 샘플 CSV 생성: {GROWTH_CSV}")


def is_sample_data() -> bool:
    """샘플 CSV로 시작했으면 True (실측 데이터 추가 전까지 유지)."""
    return _SAMPLE_FLAG.exists()


def query(zone: str = "전체", days: int = 7) -> list[dict]:
    """Return growth records filtered by zone and last N days."""
    ensure_sample_csv()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    results = []
    with GROWTH_CSV.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["date"] < cutoff:
                continue
            if zone != "전체" and row["zone"] != zone:
                continue
            results.append(row)
    return results


def latest(zone: str = "전체") -> list[dict]:
    """Return the most recent record per zone."""
    ensure_sample_csv()
    latest_by_zone: dict[str, dict] = {}
    with GROWTH_CSV.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if zone != "전체" and row["zone"] != zone:
                continue
            z = row["zone"]
            if z not in latest_by_zone or row["date"] > latest_by_zone[z]["date"]:
                latest_by_zone[z] = row
    return list(latest_by_zone.values())


def add_record(
    zone: str,
    crop_height_cm: float,
    leaf_count: int,
    fruit_count: int,
    truss_count: int,
    stem_diameter_mm: float,
    notes: str = "",
    record_date: str | None = None,
) -> dict:
    """Append a new growth record to the CSV."""
    ensure_sample_csv()
    row = {
        "date": record_date or date.today().isoformat(),
        "zone": zone,
        "crop_height_cm": crop_height_cm,
        "leaf_count": leaf_count,
        "fruit_count": fruit_count,
        "truss_count": truss_count,
        "stem_diameter_mm": stem_diameter_mm,
        "notes": notes,
    }
    with GROWTH_CSV.open("a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=COLUMNS).writerow(row)
    return row
