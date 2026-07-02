"""
backtest_price.py
KAMIS 토마토 도매가격 2년치 + KMA 기상 데이터 백테스트

목적:
  1. 가격 계절성 패턴 확인 (어느 달이 고가/저가)
  2. 한파(최저기온) → 가격 상승 시차 분석
  3. 예측 기능 구현 가치 검증

실행: conda run -n BI2026 python backtest_price.py
"""

import json
import os
import ssl
import time
import warnings
from datetime import date, timedelta, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
warnings.filterwarnings("ignore")

# ── 한글 폰트 ──────────────────────────────────────────────────────────────
for font in ["AppleGothic", "Malgun Gothic", "NanumGothic", "DejaVu Sans"]:
    try:
        matplotlib.rc("font", family=font)
        break
    except Exception:
        pass
matplotlib.rc("axes", unicode_minus=False)

# ── 설정 ────────────────────────────────────────────────────────────────────
KAMIS_URL     = "https://www.kamis.or.kr/service/price/xml.do"
KMA_ASOS_URL  = "http://apis.data.go.kr/1360000/AsosDalyInfoService/getWthrDataList"

KAMIS_KEY     = os.getenv("KAMIS_API_KEY", "")
KAMIS_ID      = os.getenv("KAMIS_API_ID", "")
KMA_KEY       = os.getenv("KMA_API_KEY", "")
COUNTRY_CODE  = os.getenv("KAMIS_COUNTRY_CODE", "1101")  # 서울가락

KMA_ASOS_STN  = "146"   # 전주 (김제 인근 ASOS 관측소)
TOMATO_CAT    = "200"
TOMATO_ITEM   = "214"

END_DATE      = date.today()
START_DATE    = END_DATE.replace(year=END_DATE.year - 2)

OUT_PATH      = Path(__file__).parent / "backtest_result.png"


# ── KAMIS SSL 우회 세션 ────────────────────────────────────────────────────
class _LegacySSL(HTTPAdapter):
    def init_poolmanager(self, *a, **kw):
        ctx = create_urllib3_context()
        ctx.set_ciphers("DEFAULT@SECLEVEL=0")
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        kw["ssl_context"] = ctx
        super().init_poolmanager(*a, **kw)

def _kamis_session():
    s = requests.Session()
    s.mount("https://", _LegacySSL())
    return s


# ── KAMIS 데이터 수집 ────────────────────────────────────────────────────
def _fetch_kamis_chunk(sess, start: date, end: date, kind_code: str) -> list:
    params = {
        "action":             "periodProductList",
        "p_cert_key":         KAMIS_KEY,
        "p_cert_id":          KAMIS_ID,
        "p_returntype":       "json",
        "p_itemcategorycode": TOMATO_CAT,
        "p_itemcode":         TOMATO_ITEM,
        "p_kindcode":         kind_code,
        "p_startday":         start.isoformat(),
        "p_endday":           end.isoformat(),
        "p_countrycode":      COUNTRY_CODE,
        "p_convert_kg_yn":    "N",
    }
    try:
        resp = sess.get(KAMIS_URL, params=params, timeout=15)
        resp.raise_for_status()
        data  = json.loads(resp.text)
        items = data.get("data", {}).get("item", [])
        if isinstance(items, dict):
            items = [items]
        return [r for r in (items or []) if isinstance(r, dict)]
    except Exception as e:
        print(f"    KAMIS 오류: {e}")
        return []


def fetch_kamis_2yr() -> pd.DataFrame:
    """2년치 KAMIS 상품(01) 가격 — 90일 단위 분할 조회."""
    print(f"■ KAMIS 데이터 수집 ({START_DATE} ~ {END_DATE})")
    sess = _kamis_session()
    all_rows = []

    cur = START_DATE
    while cur < END_DATE:
        chunk_end = min(cur + timedelta(days=89), END_DATE)
        rows = _fetch_kamis_chunk(sess, cur, chunk_end, "01")
        print(f"  {cur} ~ {chunk_end}: {len(rows)}건")
        all_rows.extend(rows)
        cur = chunk_end + timedelta(days=1)
        time.sleep(0.35)

    records = []
    for r in all_rows:
        if r.get("countyname") != "평균":
            continue
        yyyy    = r.get("yyyy", "2024")
        regday  = r.get("regday", "")
        price_s = r.get("price", "")
        try:
            mm, dd = regday.split("/")
            dt     = date(int(yyyy), int(mm), int(dd))
            price  = int(str(price_s).replace(",", "").strip())
            if price > 0:
                records.append({"date": pd.Timestamp(dt), "price": price})
        except Exception:
            continue

    if not records:
        raise RuntimeError("KAMIS 데이터 없음 — KAMIS_API_KEY / KAMIS_API_ID 확인 필요")

    df = (pd.DataFrame(records)
            .drop_duplicates("date")
            .sort_values("date")
            .set_index("date"))
    # 주간 평균으로 리샘플
    df = df["price"].resample("W-MON").mean().dropna().reset_index()
    print(f"  → {len(df)}주치 데이터 확보\n")
    return df


# ── KMA ASOS 데이터 수집 ─────────────────────────────────────────────────
def fetch_kma_daily() -> pd.DataFrame:
    """KMA ASOS 일자료 — 일최저기온, 일평균기온."""
    print(f"■ KMA ASOS 기상 데이터 수집 (지점 {KMA_ASOS_STN} 전주)")
    all_rows = []
    cur = START_DATE
    while cur < END_DATE:
        chunk_end = min(cur + timedelta(days=89), END_DATE)
        params = {
            "serviceKey": KMA_KEY,
            "pageNo":     1,
            "numOfRows":  999,
            "dataType":   "JSON",
            "dataCd":     "ASOS",
            "dateCd":     "DD",
            "startDt":    cur.strftime("%Y%m%d"),
            "endDt":      chunk_end.strftime("%Y%m%d"),
            "stnIds":     KMA_ASOS_STN,
        }
        try:
            resp  = requests.get(KMA_ASOS_URL, params=params, timeout=15)
            items = resp.json()["response"]["body"]["items"]["item"]
            all_rows.extend(items)
            print(f"  {cur} ~ {chunk_end}: {len(items)}건")
        except Exception as e:
            print(f"  {cur} ~ {chunk_end}: 오류 ({e})")
        cur = chunk_end + timedelta(days=1)
        time.sleep(0.35)

    if not all_rows:
        print("  → KMA 데이터 없음 — 기온 분석 생략\n")
        return pd.DataFrame()

    records = []
    for r in all_rows:
        try:
            dt  = pd.Timestamp(datetime.strptime(str(r["tm"]), "%Y-%m-%d"))
            records.append({
                "date":     dt,
                "avg_temp": float(r.get("avgTa") or "nan"),
                "min_temp": float(r.get("minTa") or "nan"),
            })
        except Exception:
            continue

    df = (pd.DataFrame(records)
            .sort_values("date")
            .set_index("date"))
    weekly = pd.DataFrame({
        "avg_temp": df["avg_temp"].resample("W-MON").mean(),
        "min_temp": df["min_temp"].resample("W-MON").min(),
    }).dropna().reset_index()
    print(f"  → {len(weekly)}주치 데이터 확보\n")
    return weekly


# ── 분석 & 시각화 ─────────────────────────────────────────────────────────
def analyze(price_df: pd.DataFrame, kma_df: pd.DataFrame):
    print("■ 분석 시작\n")

    price_df = price_df.copy()
    price_df["month"] = price_df["date"].dt.month
    price_df["week"]  = price_df["date"].dt.isocalendar().week.astype(int)

    monthly_avg = price_df.groupby("month")["price"].mean()
    overall_avg = price_df["price"].mean()

    # z-score 이상치
    price_df["z"] = (price_df["price"] - overall_avg) / price_df["price"].std()
    spikes = price_df[price_df["z"] > 1.5]

    # ── 플롯 구성 ──
    has_kma = not kma_df.empty
    n_rows  = 3 if has_kma else 2
    fig, axes = plt.subplots(n_rows, 1, figsize=(14, 5 * n_rows))
    fig.suptitle("토마토 도매가격 백테스트 분석", fontsize=15, fontweight="bold", y=1.01)

    # ── 1. 가격 시계열 ──────────────────────────────────────────────────────
    ax = axes[0]
    ax.plot(price_df["date"], price_df["price"], color="#c0392b", linewidth=1.4, label="주간 평균가")
    ax.fill_between(price_df["date"], price_df["price"], alpha=0.08, color="#c0392b")
    ax.axhline(overall_avg, color="#7f8c8d", linestyle="--", linewidth=1,
               label=f"2년 평균 {int(overall_avg):,}원")
    ax.scatter(spikes["date"], spikes["price"], color="#e74c3c", s=40, zorder=5,
               label=f"이상 고가 ({len(spikes)}회)")
    ax.set_title("토마토 도매가격 추이 (상품·서울가락·4kg)")
    ax.set_ylabel("원 / 4kg")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.25)

    # ── 2. 월별 계절성 ──────────────────────────────────────────────────────
    ax = axes[1]
    colors = ["#e74c3c" if v >= overall_avg else "#3498db" for v in monthly_avg.values]
    ax.bar(monthly_avg.index, monthly_avg.values, color=colors, alpha=0.85, width=0.7)
    ax.axhline(overall_avg, color="#7f8c8d", linestyle="--", linewidth=1,
               label=f"평균 {int(overall_avg):,}원")
    ax.set_title("월별 평균가격 (계절성 패턴)  ■ 빨강=평균 이상  ■ 파랑=평균 이하")
    ax.set_ylabel("원 / 4kg")
    ax.set_xticks(range(1, 13))
    ax.set_xticklabels([f"{m}월" for m in range(1, 13)])
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
    for i, (m, v) in enumerate(monthly_avg.items()):
        ax.text(m, v + 200, f"{int(v):,}", ha="center", va="bottom", fontsize=8)
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.25, axis="y")

    # ── 3. 기온-가격 시차 상관관계 ─────────────────────────────────────────
    lag_results = []
    if has_kma:
        ax = axes[2]
        merged = pd.merge_asof(
            price_df.sort_values("date"),
            kma_df.sort_values("date"),
            on="date", direction="nearest", tolerance=pd.Timedelta("8d")
        ).dropna(subset=["min_temp"])

        lags  = list(range(0, 9))
        corrs = []
        for lag in lags:
            c = merged["price"].corr(merged["min_temp"].shift(lag))
            corrs.append(c)
            lag_results.append((lag, c))

        bar_colors = ["#e74c3c" if c < 0 else "#2ecc71" for c in corrs]
        ax.bar(lags, corrs, color=bar_colors, alpha=0.85, width=0.6)
        ax.axhline(0, color="black", linewidth=0.8)
        ax.axhline(-0.3, color="#e74c3c", linestyle=":", linewidth=1, label="유의 기준선 (|r|=0.3)")
        ax.axhline( 0.3, color="#e74c3c", linestyle=":", linewidth=1)
        ax.set_title("최저기온 → 도매가격 시차 상관관계\n(음수 = '한파 N주 전' → 가격 상승)")
        ax.set_xlabel("시차 (주)")
        ax.set_ylabel("피어슨 상관계수 r")
        ax.set_xticks(lags)
        ax.set_xticklabels([f"{w}주 전" for w in lags])
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.25, axis="y")
        for lag, c in zip(lags, corrs):
            ax.text(lag, c + (0.015 if c >= 0 else -0.03), f"{c:.2f}",
                    ha="center", va="bottom" if c >= 0 else "top", fontsize=8)

    plt.tight_layout()
    plt.savefig(OUT_PATH, dpi=150, bbox_inches="tight")
    print(f"결과 이미지 저장: {OUT_PATH}\n")

    # ── 콘솔 요약 ──────────────────────────────────────────────────────────
    peak_m = monthly_avg.idxmax()
    low_m  = monthly_avg.idxmin()

    print("=" * 50)
    print("계절성 요약")
    print("=" * 50)
    print(f"  2년 평균가   : {int(overall_avg):,}원/4kg")
    print(f"  최고가 달    : {peak_m}월  ({int(monthly_avg[peak_m]):,}원)")
    print(f"  최저가 달    : {low_m}월  ({int(monthly_avg[low_m]):,}원)")
    print(f"  계절 진폭    : {monthly_avg.max()/monthly_avg.min():.2f}배")
    print(f"  이상 고가 횟수: {len(spikes)}회 (z > 1.5)")

    if lag_results:
        print()
        print("기온-가격 시차 상관관계")
        print("=" * 50)
        for lag, c in lag_results:
            bar    = "█" * int(abs(c) * 20)
            direct = "한파→가격↑" if c < 0 else "고온→가격↑"
            sig    = "★ 유의미" if abs(c) >= 0.3 else ""
            print(f"  {lag}주 전: r={c:+.3f}  {bar}  {direct} {sig}")

        best_lag, best_c = min(lag_results, key=lambda x: x[1])
        print()
        if best_c < -0.3:
            print(f"✓ 결론: 한파 {best_lag}주 전 기온과 가격이 유의미하게 연동 (r={best_c:.3f})")
            print(f"  → 예측 기능 구현 가치 있음")
        elif abs(best_c) >= 0.2:
            print(f"△ 결론: 약한 신호 존재 (r={best_c:.3f}) — 추가 변수 필요")
        else:
            print(f"✗ 결론: 기온만으로는 뚜렷한 예측 어려움 — 다른 변수 탐색 필요")
    print()


# ── 메인 ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if not KAMIS_KEY or not KAMIS_ID:
        print("❌ .env에 KAMIS_API_KEY / KAMIS_API_ID 필요")
        raise SystemExit(1)

    price_df = fetch_kamis_2yr()
    kma_df   = fetch_kma_daily() if KMA_KEY else pd.DataFrame()
    analyze(price_df, kma_df)
