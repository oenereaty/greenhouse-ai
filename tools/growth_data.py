"""Growth data handler: read/write CSV, query by zone and date range."""
import csv
import random
from datetime import date, datetime, timedelta
from pathlib import Path

from tools.demo_clock import demo_now

GROWTH_CSV = Path(__file__).parent.parent / "growth_data.csv"
_SAMPLE_FLAG = Path(__file__).parent.parent / ".growth_data_is_sample"


def _not_future(row_date: str) -> bool:
    """발표용 고정 "오늘"(tools/demo_clock.py) 이후 날짜 행은 조회에서 숨긴다 —
    생육데이터 05-25·06-01처럼 날짜를 추정해 넣은 이상치 주차가 "최신 현황"으로
    잡히지 않게 한다(사용자 확인, 2026-07-10)."""
    return row_date <= demo_now().date().isoformat()

COLUMNS = [
    "date", "zone", "crop_height_cm", "leaf_count", "fruit_count",
    "truss_count", "stem_diameter_mm", "truss_height_cm", "notes",
]

# 화방높이 판정을 문헌상 절대 밴드(예: 10~15cm)로 고정하지 않고, 초장·줄기두께와
# 같은 방식으로 전 주(trend_days) 대비 변화로 판정한다 — 절대 기준값은 문헌마다
# 편차가 크고(10~15cm vs 10~20cm) 품종·계절·재배전략에 따라 달라져 단일 절대값
# 비교가 오히려 오판을 유발한다는 현장 피드백 반영. (2026-07-10: 기존엔 21일
# 평균·추세 창으로 판정했는데, 다른 지표와 기준이 달라 헷갈린다는 피드백으로
# 전 주 대비 비교로 통일.)
TRUSS_TREND_TOLERANCE_CM = 1.5  # 전 주 대비 변화가 이 안이면 "보합(균형)"으로 판정

_migrated = False


def _migrate_if_needed() -> None:
    """구(舊) CSV(truss_height_cm 없음)를 신 스키마로 1회 마이그레이션."""
    global _migrated
    if _migrated or not GROWTH_CSV.exists():
        _migrated = True
        return
    with GROWTH_CSV.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        existing_cols = reader.fieldnames or []
        rows = list(reader)
    _migrated = True
    if "truss_height_cm" in existing_cols:
        return

    bak = GROWTH_CSV.with_suffix(".csv.bak")
    if not bak.exists():
        with GROWTH_CSV.open(encoding="utf-8") as f:
            bak.write_text(f.read(), encoding="utf-8")

    for row in rows:
        row.setdefault("truss_height_cm", "")
    with GROWTH_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"[growth] truss_height_cm 컬럼 추가 마이그레이션 완료 (백업: {bak})")


def ensure_sample_csv():
    """Create a sample CSV if none exists."""
    _migrate_if_needed()
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
                "truss_height_cm": round(12 + random.uniform(-3, 3), 1),
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
    """Return growth records filtered by zone and last N days.

    Cutoff is relative to the latest date in the dataset, not today,
    so historical datasets remain navigable via the N-weeks slider.
    """
    ensure_sample_csv()
    all_rows: list[dict] = []
    with GROWTH_CSV.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if zone != "전체" and row["zone"] != zone:
                continue
            if not _not_future(row["date"]):
                continue
            all_rows.append(row)
    if not all_rows:
        return []
    max_date = max(r["date"] for r in all_rows)
    cutoff = (datetime.strptime(max_date, "%Y-%m-%d").date() - timedelta(days=days)).isoformat()
    return [r for r in all_rows if r["date"] >= cutoff]


def latest(zone: str = "전체") -> list[dict]:
    """Return the most recent record per zone."""
    ensure_sample_csv()
    latest_by_zone: dict[str, dict] = {}
    with GROWTH_CSV.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if zone != "전체" and row["zone"] != zone:
                continue
            if not _not_future(row["date"]):
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
    truss_height_cm: float | None = None,
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
        "truss_height_cm": truss_height_cm if truss_height_cm is not None else "",
        "notes": notes,
    }
    with GROWTH_CSV.open("a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=COLUMNS).writerow(row)
    return row


# 이 값 미만이면 생물학적으로 타당한 범위를 벗어난 것으로 보고 측정 오류를 의심함
TRUSS_HEIGHT_SANITY_MIN = 3.0


def _truss_trend_status(
    truss_height_cm: float,
    baseline: float | None,
    baseline_label: str,
    baseline_date: str | None,
) -> tuple[str, str]:
    """전 주(baseline_label) 대비 화방높이 변화 → (상태, 설명).

    지표는 '생장점(정단)과 첫 개화화방 사이 거리'로, high-wire 토마토에서 생식/영양생장
    균형 진단에 쓰는 측정치다. 절대 밴드(예: 10~15cm)는 문헌·품종·계절에 따라 편차가 커서
    이 온실 자체의 전 주 대비 변화(상승=영양생장 쪽, 하락=생식생장 쪽)로 판정한다 — 초장·
    줄기두께와 같은 비교 기준으로 통일(2026-07-10).
    """
    if truss_height_cm < TRUSS_HEIGHT_SANITY_MIN:
        return "측정 재확인 필요", (
            f"화방높이 {truss_height_cm}cm로 측정되었습니다. 생물학적으로 매우 낮은 값이라 "
            "생장점·개화화방 인식 오류나 입력 오류일 가능성이 있어 재측정을 권합니다."
        )

    if baseline is None:
        return "균형 추정", (
            f"화방높이 {truss_height_cm}cm — 비교할 이전 기록이 없어 추세 판정이 어렵습니다. "
            "최신값만 참고하시고, 다음 주에 다시 확인하면 추세를 판단할 수 있습니다."
        )

    delta = round(truss_height_cm - baseline, 1)
    baseline_desc = f"{baseline_label}({baseline_date}) 대비"

    if delta > TRUSS_TREND_TOLERANCE_CM:
        return "영양생장 쪽으로 추정", (
            f"화방높이 {truss_height_cm}cm — {baseline_desc} {delta:+.1f}cm 상승했습니다. "
            "생장점이 화방보다 빠르게 자라는 방향이라 영양생장이 우세해지는 것으로 추정됩니다. "
            "줄기두께·착과 추세와 함께 판단해 주세요."
        )
    if delta < -TRUSS_TREND_TOLERANCE_CM:
        return "생식생장 쪽으로 추정", (
            f"화방높이 {truss_height_cm}cm — {baseline_desc} {delta:+.1f}cm 하락했습니다. "
            "화방이 생장점을 따라잡는 방향이라 생식생장이 우세해지는 것으로 추정됩니다. "
            "줄기두께·착과 추세와 함께 판단해 주세요."
        )
    return "균형 추정", (
        f"화방높이 {truss_height_cm}cm — {baseline_desc} 변화 {delta:+.1f}cm로 "
        "뚜렷한 추세 없이 보합 상태입니다."
    )


def assess_growth(zone: str = "전체", trend_days: int = 7, trend_tolerance: int = 3) -> list[dict]:
    """구역별 최신 생육 기록에 화방높이 균형 판정 + 변화량(추세)을 덧붙여 반환.

    화방높이·초장·줄기두께·착과수 모두 절대값이 아니라 추세(최근 2~4주 평균·변화량)로
    평가한다 — 표본조사는 개체 일부만 뽑는 방식이라 절대값보다 경향성 파악이 목적이고,
    화방높이의 경우 문헌상 절대 밴드가 품종·계절마다 달라 단일 절대값 비교가 오판을
    유발할 수 있다는 현장 피드백을 반영했다.
    """
    baseline_label = "전 주" if trend_days == 7 else f"{trend_days}일 전"
    ensure_sample_csv()
    all_rows: list[dict] = []
    with GROWTH_CSV.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if zone != "전체" and row["zone"] != zone:
                continue
            if not _not_future(row["date"]):
                continue
            all_rows.append(row)

    by_zone: dict[str, list[dict]] = {}
    for row in all_rows:
        by_zone.setdefault(row["zone"], []).append(row)

    results = []
    for z, rows in by_zone.items():
        rows.sort(key=lambda r: r["date"])
        latest_row = rows[-1]
        latest_date = datetime.strptime(latest_row["date"], "%Y-%m-%d").date()

        target_date = latest_date - timedelta(days=trend_days)
        baseline = None
        for r in rows:
            r_date = datetime.strptime(r["date"], "%Y-%m-%d").date()
            if abs((r_date - target_date).days) <= trend_tolerance:
                baseline = r
                break

        entry = {"zone": z, "date": latest_row["date"]}

        _th = latest_row.get("truss_height_cm", "")
        if _th not in ("", None):
            baseline_th_raw = baseline.get("truss_height_cm") if baseline else None
            baseline_th = float(baseline_th_raw) if baseline_th_raw not in (None, "") else None
            baseline_date = baseline["date"] if baseline and baseline_th is not None else None
            status, desc = _truss_trend_status(float(_th), baseline_th, baseline_label, baseline_date)
            entry["truss_height_cm"] = float(_th)
            entry["truss_status"] = status
            entry["truss_desc"] = desc
        else:
            entry["truss_height_cm"] = None
            entry["truss_status"] = None
            entry["truss_desc"] = "화방높이 미입력"

        for field, label in [
            ("crop_height_cm", "초장"), ("stem_diameter_mm", "줄기두께"), ("fruit_count", "착과수"),
        ]:
            cur = latest_row.get(field, "")
            if baseline and cur not in ("", None) and baseline.get(field) not in ("", None):
                delta = round(float(cur) - float(baseline[field]), 1)
                if field == "crop_height_cm" and delta < 0:
                    # 초장은 생물학적으로 감소하지 않으므로 음수 델타는 표본 측정 편차로 간주하고 0으로 표시
                    entry[f"{field}_trend"] = 0.0
                    entry[f"{field}_trend_desc"] = (
                        f"{label} {baseline_label}({baseline['date']}) 대비 변화 없음 "
                        "(표본 측정 편차로 감소 관측 — 초장은 실제로 줄지 않으므로 0으로 표시)"
                    )
                else:
                    entry[f"{field}_trend"] = delta
                    entry[f"{field}_trend_desc"] = (
                        f"{label} {baseline_label}({baseline['date']}) 대비 {delta:+.1f} 변화"
                    )
            else:
                entry[f"{field}_trend"] = None
                entry[f"{field}_trend_desc"] = f"{label} 추세 비교용 이전 기록 없음(±{trend_tolerance}일 이내)"

        results.append(entry)

    return results


if __name__ == "__main__":
    ensure_sample_csv()
    print(assess_growth("전체"))
