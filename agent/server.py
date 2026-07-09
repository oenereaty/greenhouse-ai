"""Greenhouse MCP server — exposes sensor, growth, and decision-history tools.

BI2026(온실 진단 앱)의 mcp_server.py에서 이식. agent/agent.py가 서브프로세스로
직접 실행하므로(`python agent/server.py`), 저장소 루트를 sys.path에 추가해
tools/·rag/ 패키지를 임포트할 수 있게 한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.server.fastmcp import FastMCP
from tools.sensor_client import fetch_sensors, get_recent_series
from tools.growth_data import query as growth_query, latest as growth_latest, add_record
from rag.pipeline import load_decisions

mcp = FastMCP("greenhouse")


@mcp.tool()
def get_sensor_data() -> dict:
    """현재 온실 센서 데이터 조회 (온도·습도·CO2·일사량) — 실측 CSV 기반."""
    return fetch_sensors()


@mcp.tool()
def get_sensor_history(hours: int = 24) -> list:
    """최근 N시간 온실 센서 시계열 데이터 조회 — 실측 CSV 기반.

    Args:
        hours: 조회할 시간 수 (기본 24시간)
    """
    return get_recent_series(hours=hours)


@mcp.tool()
def get_growth_data(zone: str = "전체", days: int = 7) -> list:
    """구역별 생육 데이터 조회 (초장·엽수·착과수·화방수·줄기직경).

    Args:
        zone: 구역 코드 (A/B/C/전체)
        days: 최근 몇 일치 조회 (기본 7일)
    """
    return growth_query(zone=zone, days=days)


@mcp.tool()
def get_growth_latest(zone: str = "전체") -> list:
    """구역별 최신 생육 데이터만 조회.

    Args:
        zone: 구역 코드 (A/B/C/전체)
    """
    return growth_latest(zone=zone)


@mcp.tool()
def get_decision_history(n: int = 5) -> list:
    """최근 N건 LLM 진단 기록 조회.

    Args:
        n: 조회할 기록 수 (기본 5)
    """
    records = load_decisions()
    return records[-n:] if records else []


@mcp.tool()
def get_price_info() -> dict:
    """오늘 토마토 등급별 경락가, 계절 대비 판매 시점 제안, 최근 시장별 평균가,
    산지·시장별 프리미엄 상위 목록을 조회 — aT 실시간 경매정보 기반.

    호출 시 오늘 경매 원장을 자동으로 누적 아카이브에 저장해 향후 계절/지역
    사이클 분석에 쓰인다. 시장 간 라우팅(예: 가락 vs 익산)을 물어보면 이 데이터의
    "시장별_최근_평균가"로 비교하되, 실제 순수익 판단에는 사용자가 알고 있는
    물류비(운송비)를 직접 물어봐서 반영할 것 — 물류비를 임의로 가정하지 말 것.
    """
    from tools.at_client import fetch_all_grades, fetch_auction_ledger
    from tools.auction_archive import archive_ledger_snapshot, origin_market_cycle
    from tools.price_advisor import get_sales_advice

    ledger = fetch_auction_ledger()
    try:
        archive_ledger_snapshot(ledger)
    except Exception:
        pass

    grades = fetch_all_grades()
    mid_price = grades.get("중", {}).get("price")
    advice = get_sales_advice(mid_price)
    cycle = origin_market_cycle(days=180, min_count=3)

    return {
        "오늘_등급별_경락가": grades,
        "판매_시점_제안": advice,
        "시장별_최근_평균가": cycle.get("market_summary", []),
        "산지_시장_프리미엄_상위": cycle.get("rows", [])[:10],
    }


@mcp.tool()
def get_price_history(start_date: str, end_date: str) -> dict:
    """지정 기간(YYYY-MM-DD ~ YYYY-MM-DD) 동안 어느 도매시장이 토마토 가격이
    가장 높았는지 비교. "3일 전", "작년 7월엔 어디가 제일 비쌌어" 같은 질문에 씀.

    두 단계로 조회한다:
    1. 최근 며칠(우리 실시간 경매 아카이브 수집 시작 이후)이면 16개 시장 + 산지
       정보까지 포함해 반환한다.
    2. 아카이브에 없는 오래된 과거(작년 등)면 KAMIS 농산물유통정보로 대체
       조회한다 — 단 이 경우 서울가락·부산·대구·광주·대전 5개 시장만 비교
       가능하다(다른 시장은 KAMIS에 도매 데이터 없음, 2026-07 실측 확인).
    두 소스 모두 데이터가 없으면 빈 결과를 반환하니, 그 경우 "해당 기간 데이터가
    없습니다"라고 답하고 추측하지 말 것.

    "3일 전"처럼 특정 하루를 콕 집어 묻더라도 start_date=end_date로 정확히 그
    하루만 조회하지 말고 앞뒤로 하루씩 넓혀(예: 3일 전이면 start_date=4일 전,
    end_date=2일 전) 조회할 것 — 경매가 없는 날이나 수집 공백이 있을 수 있다.

    Args:
        start_date: 조회 시작일 (YYYY-MM-DD) — 질문 시점보다 하루 이상 여유 있게 잡을 것
        end_date: 조회 종료일 (YYYY-MM-DD) — 질문 시점보다 하루 이상 여유 있게 잡을 것
    """
    from datetime import date as _date

    from tools.auction_archive import market_avg_in_range
    from tools.kamis_client import fetch_market_avg_for_period

    start = _date.fromisoformat(start_date)
    end = _date.fromisoformat(end_date)

    archive_rows = market_avg_in_range(start, end)
    if archive_rows:
        return {
            "기간": f"{start_date} ~ {end_date}",
            "출처": "실시간 경매 아카이브 (16개 시장)",
            "시장별_평균가": archive_rows,
        }

    try:
        kamis_rows = fetch_market_avg_for_period(start, end)
    except RuntimeError:
        kamis_rows = []  # KAMIS 키 미설정
    if kamis_rows:
        return {
            "기간": f"{start_date} ~ {end_date}",
            "출처": "KAMIS 농산물유통정보 (서울가락·부산·대구·광주·대전 5개 시장만)",
            "시장별_평균가": kamis_rows,
        }

    return {
        "기간": f"{start_date} ~ {end_date}",
        "출처": None,
        "시장별_평균가": [],
        "안내": "해당 기간 데이터를 찾을 수 없습니다.",
    }


@mcp.tool()
def add_growth_record(
    zone: str,
    crop_height_cm: float,
    leaf_count: int,
    fruit_count: int,
    truss_count: int,
    stem_diameter_mm: float,
    notes: str = "",
) -> dict:
    """새 생육 측정값을 CSV에 기록.

    Args:
        zone: 구역 코드 (A/B/C)
        crop_height_cm: 초장 (cm)
        leaf_count: 엽수
        fruit_count: 착과수
        truss_count: 화방수
        stem_diameter_mm: 줄기직경 (mm)
        notes: 비고
    """
    return add_record(
        zone=zone,
        crop_height_cm=crop_height_cm,
        leaf_count=leaf_count,
        fruit_count=fruit_count,
        truss_count=truss_count,
        stem_diameter_mm=stem_diameter_mm,
        notes=notes,
    )


if __name__ == "__main__":
    mcp.run()
