"""xlsx + CSV 실측 생육 데이터를 growth_data.csv로 임포트.

Zone A: 생육정보 토마토.xlsx        (사용자 농장 실측 — 2025-09-26 정식 주기, 이전 주기 대체)
Zone B: 전라북도_농가데이터셋_토마토.csv  (전북 임실군 참조 농가)

실행:
    python scripts/import_growth_data.py
"""
import csv
import math
from datetime import timedelta
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).parent.parent
GROWTH_CSV = BASE_DIR / "growth_data.csv"
SAMPLE_FLAG = BASE_DIR / ".growth_data_is_sample"

COLUMNS = [
    "date", "zone", "crop_height_cm", "leaf_count", "fruit_count",
    "truss_count", "stem_diameter_mm", "truss_height_cm", "notes",
]

XLSX_PATH = BASE_DIR / "file" / "생육정보 토마토.xlsx"
CSV_PATH  = BASE_DIR / "file" / "전라북도_농가데이터셋_토마토.csv"

# Zone A 정식 초기 추정 기준 — 실측 초장(누적) 값이 없고 주간 생장길이만 있어
# Zone B와 동일한 관례로 베이스라인에서부터 누적한다.
ZONE_A_BASELINE_CM = 50.0

# 원본 xlsx의 알려진 데이터 오류 보정값 (사용자 확인 완료, tomato-yield 2026-07-09).
#  - 2026-04-24(29주차): 생장길이 4개 표본이 엑셀에 의해 날짜(1900-xx-xx)로 잘못
#    변환되어 저장됨 — 1899-12-30 기준 일련번호로 역산한 mm값으로 대체.
#  - 2025-10-03(6주차 두번째, 표본4): 줄기굵기 140mm은 11~13mm대인 나머지 표본과
#    비교해 명백한 소수점 오타로 보고 14.0mm로 보정.
_GROWTH_MM_FIX = {("2026-04-24", 1): 290.0, ("2026-04-24", 2): 210.0,
                  ("2026-04-24", 3): 180.0, ("2026-04-24", 4): 240.0}
_STEM_MM_FIX = {("2025-10-03", 4): 14.0}


def _safe_int(val, default: int = 0) -> int:
    try:
        v = float(val)
        return default if math.isnan(v) else int(round(v))
    except (TypeError, ValueError):
        return default


def _safe_float(val, default: float = 0.0) -> float:
    try:
        v = float(val)
        return default if math.isnan(v) else round(v, 1)
    except (TypeError, ValueError):
        return default


def load_zone_a() -> list[dict]:
    """생육정보 토마토.xlsx → Zone A 행 목록.

    표(header)는 4번째 줄(0-index 2)에 있고, 주차마다 표본 1~4가 4행씩 이어진다.
    측정일자/주차는 각 주차 블록의 첫 행에만 적혀 있어 forward-fill이 필요하다.
    33주차(2026-05-18) 이후 34·35주차는 원본에 측정일자가 아예 비어 있어(생장
    관련 수치도 전부 0 — 수확기 종료로 추정) 직전 주차 간격(7일)으로 추정한다.
    """
    raw = pd.read_excel(XLSX_PATH, header=None, skiprows=3).iloc[:, :12].copy()
    raw.columns = [
        "farm", "week", "measured_at", "sample",
        "growth_mm", "truss_h_mm", "stem_mm",
        "leaf_len_mm", "leaf_wid_mm", "leaf_count", "fruit_count", "truss_no",
    ]
    raw["week"] = raw["week"].ffill()
    for c in ["growth_mm", "truss_h_mm", "stem_mm", "leaf_count", "fruit_count", "truss_no"]:
        raw[c] = pd.to_numeric(raw[c], errors="coerce")

    # 주차 블록별 대표 날짜: 블록 내 첫 유효 측정일자. 없으면(34·35주차) 이전
    # 블록 날짜에서 7일씩 더해 추정한다.
    week_dates: dict[float, str] = {}
    last_date = None
    for week in sorted(raw["week"].dropna().unique()):
        block = raw[raw["week"] == week]
        parsed = pd.to_datetime(block["measured_at"], format="%Y.%m.%d", errors="coerce").dropna()
        if len(parsed):
            d = parsed.iloc[0].date()
        else:
            d = last_date + timedelta(days=7)
        week_dates[week] = d.isoformat()
        last_date = d

    raw["date"] = raw["week"].map(week_dates)

    for (d, sample), mm in _GROWTH_MM_FIX.items():
        raw.loc[(raw["date"] == d) & (raw["sample"] == sample), "growth_mm"] = mm
    for (d, sample), mm in _STEM_MM_FIX.items():
        raw.loc[(raw["date"] == d) & (raw["sample"] == sample), "stem_mm"] = mm

    grouped = raw.groupby("date", sort=True).agg(
        growth_mm=("growth_mm", "mean"),
        truss_h_mm=("truss_h_mm", "mean"),
        stem_mm=("stem_mm", "mean"),
        leaf_count=("leaf_count", "mean"),
        fruit_count=("fruit_count", "mean"),
        truss_no=("truss_no", "mean"),
    ).reset_index().sort_values("date")

    rows = []
    cum_h = ZONE_A_BASELINE_CM
    for _, r in grouped.iterrows():
        cum_h += (r["growth_mm"] or 0.0) / 10
        rows.append({
            "date":              r["date"],
            "zone":              "A",
            "crop_height_cm":    round(cum_h, 1),
            "leaf_count":        _safe_int(r["leaf_count"]),
            "fruit_count":       _safe_int(r["fruit_count"]),
            "truss_count":       max(1, _safe_int(r["truss_no"])),
            "stem_diameter_mm":  _safe_float(r["stem_mm"]),
            "truss_height_cm":   round(r["truss_h_mm"] / 10, 1) if r["truss_h_mm"] == r["truss_h_mm"] else "",
            "notes":             "",
        })
    return rows


def load_zone_b() -> list[dict]:
    """CSV → Zone B 행 목록 (전북 임실군 참조 농가).

    초장 정보가 없어 생장길이 누적으로 추정 (기준 50cm).
    """
    df = pd.read_csv(CSV_PATH, encoding="cp949")
    weekly = (
        df[["조사일", "생장길이", "줄기직경", "엽수", "열매수", "착과군"]]
        .dropna(subset=["조사일"])
        .drop_duplicates("조사일")
        .sort_values("조사일")
    )

    rows = []
    cum_h = 50.0  # 정식 초기 추정 기준 (cm)
    for _, r in weekly.iterrows():
        g_mm = _safe_float(r.get("생장길이"))
        cum_h += g_mm / 10  # mm → cm 누적

        rows.append({
            "date":            str(r["조사일"]).split()[0],
            "zone":            "B",
            "crop_height_cm":  round(cum_h, 1),
            "leaf_count":      _safe_int(r.get("엽수")),
            "fruit_count":     _safe_int(r.get("열매수")),
            "truss_count":     _safe_int(r.get("착과군")) or 1,
            "stem_diameter_mm": _safe_float(r.get("줄기직경")),
            "truss_height_cm": "",
            "notes":           "전북 임실군 참조 농가",
        })
    return rows


def main():
    rows_a = load_zone_a()
    rows_b = load_zone_b()
    all_rows = sorted(rows_a + rows_b, key=lambda r: r["date"])

    with GROWTH_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(all_rows)

    if SAMPLE_FLAG.exists():
        SAMPLE_FLAG.unlink()

    def _range(rows: list[dict]) -> str:
        return f"{rows[0]['date']} ~ {rows[-1]['date']}" if rows else "(데이터 없음)"

    print(f"완료: {len(all_rows)}행 저장 → {GROWTH_CSV}")
    print(f"  Zone A (xlsx): {len(rows_a)}행  {_range(rows_a)}")
    print(f"  Zone B (CSV) : {len(rows_b)}행  {_range(rows_b)}")


if __name__ == "__main__":
    main()
