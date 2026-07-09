"""완숙토마토 도매경매 원시 데이터(2021~2026, 4개시장 통합 xlsx)를 auction_history.csv로 백필.

tools/auction_archive.py의 아카이브는 실시간 aT API 수집이 시작된 시점(2026-07-04)부터만
쌓여 있어 과거로 백필이 불가능했다. 이 스크립트는 사용자가 확보한 5년치 원본 경매 데이터를
같은 스키마로 정규화해 archive_ledger_snapshot()에 그대로 흘려보내, 기존 실시간 수집분과
자동으로 중복 제거되며 병합되게 한다.

제외/정규화 내역 (2026-07-09 사용자 확인):
  - 익산 시트 제외 — 2021년 이후 사실상 데이터가 끊겨(2022년 7건, 2023년 0건) 4개 시장
    비교에 넣으면 왜곡됨.
  - 단량 표기를 "{kg}kg 상자"/"{kg}kg 파렛트"로 통일 — 원본이 "5kg 상자"/"5"/"10kg ." 등
    시트·연도별로 제각각이라, tools/auction_archive._price_per_kg()가 기대하는
    "숫자+kg" 패턴에 맞춘다.
  - 단량당 경락가(원) 기준 kg당 단가 20,000원 초과 행 제거 — 8,000,000원/2kg처럼 자릿수가
    통째로 잘못 찍힌 명백한 오입력(분포상 15,000~20,000원대는 22건인데 20,000원을 넘는
    순간 143건으로 급증하고 최대 400만원까지 튀어, 자연스러운 경계로 확인됨).

실행:
    python scripts/import_auction_history.py
"""
from pathlib import Path
import re

import pandas as pd

from tools.auction_archive import archive_ledger_snapshot, archive_summary

BASE_DIR = Path(__file__).parent.parent
XLSX_PATH = BASE_DIR / "file" / "완숙토마토_도매경매_4개시장_2021-2026_통합.xlsx"

EXCLUDED_SHEETS = {"익산"}
PRICE_PER_KG_MAX = 20_000  # 이 값을 넘으면 오입력으로 간주해 제외

COLS = [
    "거래일자", "경락일시", "도매시장", "법인", "매매구분", "부류", "품목", "품종",
    "출하지", "단량", "수량", "단량당 경락가(원)",
]


def _parse_kg(raw: str) -> tuple[float | None, str]:
    """원본 단량 문자열에서 (kg, 포장방식)을 뽑는다. 포장방식은 '상자' 기본, '파렛트' 감지."""
    m = re.match(r"([0-9.]+)", str(raw))
    if not m:
        return None, "상자"
    kg = float(m.group(1))
    unit = "파렛트" if "파렛트" in str(raw) else "상자"
    return kg, unit


def _fmt_kg(kg: float) -> str:
    return f"{kg:g}"


def load_sheet(name: str) -> list[dict]:
    df = pd.read_excel(XLSX_PATH, sheet_name=name, usecols=COLS)
    df["거래일자"] = pd.to_datetime(df["거래일자"]).dt.strftime("%Y-%m-%d")
    df["경락일시"] = pd.to_datetime(df["경락일시"]).dt.strftime("%Y-%m-%d %H:%M:%S")

    parsed = df["단량"].apply(_parse_kg)
    df["단량_kg"] = parsed.apply(lambda t: t[0])
    df["포장방식"] = parsed.apply(lambda t: t[1])
    df = df.dropna(subset=["단량_kg"])
    df = df[df["단량_kg"] > 0]

    df["price_per_kg"] = df["단량당 경락가(원)"] / df["단량_kg"]
    before = len(df)
    df = df[df["price_per_kg"] <= PRICE_PER_KG_MAX]
    dropped = before - len(df)

    rows = []
    for _, r in df.iterrows():
        rows.append({
            "거래일자": r["거래일자"],
            "경락일시": r["경락일시"],
            "도매시장": r["도매시장"],
            "법인": r["법인"],
            "품목": r["품목"],
            "품종": r["품종"],
            "출하지": r["출하지"],
            "단량": f"{_fmt_kg(r['단량_kg'])}kg {r['포장방식']}",
            "수량": r["수량"],
            "단량당 경락가(원)": int(r["단량당 경락가(원)"]),
            "등급": "",
        })
    print(f"  {name}: 원본 {before}건 → 오입력 {dropped}건 제외 → {len(rows)}건")
    return rows


def main() -> None:
    xls = pd.ExcelFile(XLSX_PATH)
    sheets = [s for s in xls.sheet_names if s not in EXCLUDED_SHEETS]
    print(f"대상 시트: {sheets} (제외: {sorted(EXCLUDED_SHEETS)})")

    all_rows = []
    for name in sheets:
        all_rows.extend(load_sheet(name))

    result = archive_ledger_snapshot({"rows": all_rows})
    print(f"완료: 추가 {result['added']}건 / 중복·오입력 스킵 {result['skipped']}건 "
          f"→ 누적 {result['total_rows']}건")
    print(archive_summary())


if __name__ == "__main__":
    main()
