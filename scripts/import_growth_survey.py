"""실측 생육조사 리포트(file/시설원예_생육정보_2026-07-08.xlsx) → growth_data.csv 전체 교체.

기존 growth_data.csv(샘플/참조농가 혼재 데이터)를 실제 조사값으로 교체한다.
원본은 구역 구분이 없는 단일 온실 조사 데이터라 zone="A"로 저장한다.
생장길이·엽장·엽폭처럼 기존 스키마에 없는 값은 notes 필드에 요약해 보존한다.
"""
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).parent.parent
SRC_XLSX = BASE_DIR / "file" / "시설원예_생육정보_2026-07-08.xlsx"
GROWTH_CSV = BASE_DIR / "growth_data.csv"

COLUMNS = [
    "date", "zone", "crop_height_cm", "leaf_count", "fruit_count",
    "truss_count", "stem_diameter_mm", "truss_height_cm", "notes",
]


def main() -> None:
    df = pd.read_excel(SRC_XLSX)

    rows = []
    for _, r in df.iterrows():
        truss_fruits = [r.get("화방착과수1(개)", 0), r.get("화방착과수2(개)", 0), r.get("화방착과수3(개)", 0)]
        truss_fruits = [float(v) if pd.notna(v) else 0.0 for v in truss_fruits]

        notes = (
            f"{int(r['주차'])}주차 · 생장길이{r['생장길이(mm)']:.0f}mm · "
            f"엽장{r['엽장(mm)']:.0f}mm · 엽폭{r['엽폭(mm)']:.0f}mm"
        )
        rows.append({
            "date": str(r["조사일"])[:10],
            "zone": "A",
            "crop_height_cm": round(r["초장(mm)"] / 10, 1),
            "leaf_count": round(r["엽수(개)"]),
            "fruit_count": round(sum(truss_fruits)),
            "truss_count": sum(1 for v in truss_fruits if v > 0),
            "stem_diameter_mm": round(r["줄기직경(mm)"], 1),
            "truss_height_cm": round(r["화방높이(mm)"] / 10, 1),
            "notes": notes,
        })

    rows.sort(key=lambda x: x["date"])

    if GROWTH_CSV.exists():
        bak = GROWTH_CSV.with_suffix(".csv.bak2")
        bak.write_text(GROWTH_CSV.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"기존 growth_data.csv 백업 → {bak}")

    import csv
    with GROWTH_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    sample_flag = BASE_DIR / ".growth_data_is_sample"
    if sample_flag.exists():
        sample_flag.unlink()

    print(f"완료: {len(rows)}행 저장 → {GROWTH_CSV}")
    print(f"  기간: {rows[0]['date']} ~ {rows[-1]['date']}")


if __name__ == "__main__":
    main()
