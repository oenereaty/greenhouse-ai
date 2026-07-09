"""실제 온실 센서 리포트(xlsx) 통합 → file/온실_센서데이터_통합.csv 생성.

file/sensor_reports/ 아래 3개 원본 리포트를 시간순으로 합치고, 겹치는
구간은 중복 제거하며, 내부온도/습도 컬럼명이 기간별로 다른 것을
(내부온도(1) vs 평균(내부온도(1+2))) 하나로 통일한다.
"""
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).parent.parent
REPORTS_DIR = BASE_DIR / "file" / "sensor_reports"
OUT_CSV = BASE_DIR / "file" / "온실_센서데이터_통합.csv"

REPORT_FILES = [
    "report260101_260323.xlsx",
    "report.xlsx",
    "report_방울.xlsx",
]

# 원본 컬럼명 → 통합 스키마
RENAME_MAP = {
    "저장시간": "timestamp",
    "외부온도": "outdoor_temp",
    "풍향": "wind_dir",
    "풍속": "wind_speed",
    "감우": "rain",
    "외부일사": "solar",
    "누적일사(외부)": "solar_cum",
    "내부온도(1)": "indoor_temp",
    "내부습도(1)": "indoor_rh",
    "평균(내부온도(1+2))": "indoor_temp",
    "평균(내부습도(1+2))": "indoor_rh",
    "CO2농도(1)": "co2",
    "수분부족분": "moisture_deficit",
    "포화수분": "saturation_moisture",
    "절대습도": "abs_humidity",
    "이슬점": "dew_point",
}

OUT_COLUMNS = [
    "timestamp", "outdoor_temp", "wind_dir", "wind_speed", "rain",
    "solar", "solar_cum", "indoor_temp", "indoor_rh", "co2",
    "moisture_deficit", "saturation_moisture", "abs_humidity", "dew_point",
]


def main() -> None:
    frames = []
    for fname in REPORT_FILES:
        path = REPORTS_DIR / fname
        df = pd.read_excel(path)
        df = df.rename(columns=RENAME_MAP)
        for col in OUT_COLUMNS:
            if col not in df.columns:
                df[col] = pd.NA
        frames.append(df[OUT_COLUMNS])

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.sort_values("timestamp")
    combined = combined.drop_duplicates(subset="timestamp", keep="last")
    combined.to_csv(OUT_CSV, index=False, encoding="utf-8")

    print(f"완료: {len(combined)}행 저장 → {OUT_CSV}")
    print(f"  기간: {combined['timestamp'].min()} ~ {combined['timestamp'].max()}")


if __name__ == "__main__":
    main()
