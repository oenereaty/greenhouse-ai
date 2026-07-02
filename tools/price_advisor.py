"""
price_advisor.py
계절성 기반 판매 방향 제안 — 백테스트 결과(2024-07 ~ 2026-07) 기반 월별 평균가 활용
"""
from datetime import date

# 백테스트 결과: 상품·서울가락·4kg 기준 월별 평균가 (원)
MONTHLY_AVG: dict[int, int] = {
    1:  36_156,
    2:  23_315,
    3:  13_357,
    4:  14_035,
    5:  16_925,
    6:  24_107,
    7:  31_384,
    8:  38_762,
    9:  55_256,
    10: 52_090,
    11: 35_875,
    12: 20_706,
}

_MONTH_KOR = {
    1:"1월", 2:"2월", 3:"3월", 4:"4월", 5:"5월", 6:"6월",
    7:"7월", 8:"8월", 9:"9월", 10:"10월", 11:"11월", 12:"12월",
}

# 출하 유리 판단 기준: 계절평균 대비 +20% 이상
BULLISH_THRESHOLD = 1.20
# 직거래 유리 판단 기준: 계절평균 대비 -15% 이하
BEARISH_THRESHOLD = 0.85


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
        next_trend    : "상승" | "하락" | "유지"
        headline      : 짧은 제안 문구
        detail_lines  : 상세 설명 (list[str])
    """
    if not current_price or current_price <= 0:
        return {
            "signal": "없음", "ratio": None,
            "seasonal_avg": None, "next_trend": None,
            "headline": "가격 데이터 없음", "detail_lines": [],
        }

    m        = month or date.today().month
    seasonal = MONTHLY_AVG[m]
    ratio    = current_price / seasonal
    diff_pct = (ratio - 1) * 100

    # 다음 달 트렌드
    next_m   = (m % 12) + 1
    next_avg = MONTHLY_AVG[next_m]
    t_pct    = (next_avg - seasonal) / seasonal * 100
    if t_pct >= 10:
        next_trend  = "상승"
        trend_line  = f"다음 달({_MONTH_KOR[next_m]}) 계절 평균 상승 예상 ({t_pct:+.0f}%) — 일부 보유 고려"
    elif t_pct <= -10:
        next_trend  = "하락"
        trend_line  = f"다음 달({_MONTH_KOR[next_m]}) 계절 평균 하락 예상 ({t_pct:+.0f}%) — 서둘러 출하가 유리"
    else:
        next_trend  = "유지"
        trend_line  = f"다음 달({_MONTH_KOR[next_m]}) 가격 비슷한 수준 예상"

    season_line = (
        f"현재 {current_price:,}원 / {_MONTH_KOR[m]} 평균 {seasonal:,}원 "
        f"({diff_pct:+.0f}%)"
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
