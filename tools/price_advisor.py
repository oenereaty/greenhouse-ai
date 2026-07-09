"""
price_advisor.py
계절성 기반 판매 방향 제안 — 실거래 아카이브(전주·대전오정·대전노은, 2021~2026,
tools/auction_archive.monthly_seasonal_cycle) 기준 월별 중앙값 활용.

이전엔 서울 가락시장 2년 백테스트(2024-07~2026-07) 하드코딩값을 썼는데, 이 농가가
실제 출하하는 지역 시장과 달라 대표성이 떨어졌다. 2026-07-10부로 실거래 38만여
건이 쌓인 로컬 아카이브로 교체하고(archive_history.csv, gitignore 로컬 전용),
"다음 달 상승/하락 예상" 문구도 연도별 변동폭 없이 확정적으로 들리던 걸
"과거 평균 참고치, 예측 아님"으로 완화했다(연도별 변동성이 커서 — 예: 3월 중앙값이
연도별로 1만~1.9만원대까지 벌어짐. 사용자 피드백).

아카이브가 비어 있으면(신규 클론 등, auction_history.csv 미생성) _FALLBACK_MONTHLY로
대체한다 — 이 경우 detail_lines에 대체 출처임을 명시해 값을 숨기지 않는다.
"""
from datetime import date

# 아카이브가 아직 없을 때만 쓰는 최후 대체값 — 서울 가락시장 2024-07~2026-07
# 백테스트(상품·4kg). 실거래 아카이브가 있으면 항상 그쪽을 우선한다.
_FALLBACK_MONTHLY: dict[int, int] = {
    1:  36_156, 2:  23_315, 3:  13_357, 4:  14_035, 5:  16_925, 6:  24_107,
    7:  31_384, 8:  38_762, 9:  55_256, 10: 52_090, 11: 35_875, 12: 20_706,
}

_MONTH_KOR = {
    1:"1월", 2:"2월", 3:"3월", 4:"4월", 5:"5월", 6:"6월",
    7:"7월", 8:"8월", 9:"9월", 10:"10월", 11:"11월", 12:"12월",
}

# 출하 유리 판단 기준: 계절평균 대비 +20% 이상
BULLISH_THRESHOLD = 1.20
# 직거래 유리 판단 기준: 계절평균 대비 -15% 이하
BEARISH_THRESHOLD = 0.85


def _seasonal_source() -> tuple[dict[int, int], dict[int, dict], str]:
    """(월별 4kg 중앙값, 월별 연도간 변동폭, 출처 설명) 반환."""
    try:
        from tools.auction_archive import monthly_seasonal_cycle
        cycle = monthly_seasonal_cycle()
        if cycle["combined_4kg"] and len(cycle["combined_4kg"]) == 12:
            return (
                cycle["combined_4kg"],
                cycle["combined_range_4kg"],
                f"전주·대전오정·대전노은 실거래 {cycle['year_range']} 중앙값",
            )
    except Exception:
        pass
    return _FALLBACK_MONTHLY, {}, "서울 가락시장 백테스트(2024-07~2026-07, 아카이브 없어 대체)"


def get_sales_advice(
    current_price: int | None,
    month: int | None = None,
) -> dict:
    """
    현재 도매가와 계절 평균을 비교해 판매 방향 제안.

    Args:
        current_price: 오늘 상품 4kg 도매가 (원)
        month:         비교 기준 월 (None이면 오늘 날짜 사용)

    Returns:
        signal        : "출하" | "직거래" | "보통" | "없음"
        ratio         : 현재가 / 계절평균
        seasonal_avg  : 이달 계절 평균가
        next_trend    : "상승" | "하락" | "유지" (과거 평균 기준 경향 — 예측 아님)
        headline      : 짧은 제안 문구
        detail_lines  : 상세 설명 (list[str])
    """
    if not current_price or current_price <= 0:
        return {
            "signal": "없음", "ratio": None,
            "seasonal_avg": None, "next_trend": None,
            "headline": "가격 데이터 없음", "detail_lines": [],
        }

    monthly_avg, monthly_range, source = _seasonal_source()
    m        = month or date.today().month
    seasonal = monthly_avg[m]
    ratio    = current_price / seasonal
    diff_pct = (ratio - 1) * 100

    # 다음 달 경향 — 과거 평균끼리의 단순 비교이며 미래 예측이 아니다.
    next_m   = (m % 12) + 1
    next_avg = monthly_avg[next_m]
    t_pct    = (next_avg - seasonal) / seasonal * 100
    rng      = monthly_range.get(next_m)
    range_note = f" (단, 연도별로 {rng['최소']:,}~{rng['최대']:,}원까지 편차 있음)" if rng else ""
    if t_pct >= 10:
        next_trend  = "상승"
        trend_line  = f"다음 달({_MONTH_KOR[next_m]})은 과거 평균 기준 {t_pct:+.0f}% 더 높았던 경향{range_note} — 예측이 아닌 참고치입니다."
    elif t_pct <= -10:
        next_trend  = "하락"
        trend_line  = f"다음 달({_MONTH_KOR[next_m]})은 과거 평균 기준 {t_pct:+.0f}% 더 낮았던 경향{range_note} — 예측이 아닌 참고치입니다."
    else:
        next_trend  = "유지"
        trend_line  = f"다음 달({_MONTH_KOR[next_m]}) 과거 평균은 비슷한 수준이었습니다{range_note}."

    season_line = (
        f"현재 {current_price:,}원 / {_MONTH_KOR[m]} 과거 평균 {seasonal:,}원 "
        f"({diff_pct:+.0f}%) — 출처: {source}"
    )

    if ratio >= BULLISH_THRESHOLD:
        return {
            "signal":       "출하",
            "ratio":        ratio,
            "seasonal_avg": seasonal,
            "next_trend":   next_trend,
            "headline":     "시장 출하 우선",
            "detail_lines": [season_line, trend_line],
        }
    elif ratio <= BEARISH_THRESHOLD:
        return {
            "signal":       "직거래",
            "ratio":        ratio,
            "seasonal_avg": seasonal,
            "next_trend":   next_trend,
            "headline":     "직거래 우선",
            "detail_lines": [season_line, trend_line],
        }
    else:
        return {
            "signal":       "보통",
            "ratio":        ratio,
            "seasonal_avg": seasonal,
            "next_trend":   next_trend,
            "headline":     "보통 구간 — 노동 여건에 따라 결정",
            "detail_lines": [season_line, trend_line],
        }
