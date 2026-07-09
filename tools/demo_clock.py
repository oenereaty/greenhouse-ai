"""발표용 '오늘' 고정 시각 — sensor_client·kma_client가 같은 날짜를 가리키도록
단일 출처로 둔다 (전에 sensor_client.py 안에만 있던 값을 여기로 옮김 — 두 모듈이
각자 다른 날짜를 하드코딩하면 다음에 날짜를 또 바꿀 때 한쪽만 고치는 실수가
나기 쉽다).

2026-07-11 발표를 위해 실측 데이터가 가장 안정적으로 갖춰진 날짜(생육데이터
마지막 실측일 2026-05-18, 센서 CSV 범위 안, KMA AWS 실측 아카이브에도 실측치
존재 확인)로 고정했다 — 사용자 확인, 2026-07-10. 이후 2026-05-19로 재조정
— 사용자 확인, 2026-07-10.

시:분:초는 실제 현재 시각을 그대로 써서 발표 진행 중에도 자연스럽게 값이
바뀐다. 날짜만 고정한다.

단기예보(KMA DFS)는 여기 적용하지 않는다 — 예보는 그 시점 발표분만 존재하는
상품이라 과거 날짜의 예보 자체가 아예 없다(재조회해도 항상 실제 오늘 기준
예보만 온다). 그 패널은 그대로 실제 오늘 날짜로 남는다.
"""
from datetime import datetime

DEMO_DATE = (2026, 5, 19)


def demo_now() -> datetime:
    now = datetime.now()
    year, month, day = DEMO_DATE
    return now.replace(year=year, month=month, day=day)
