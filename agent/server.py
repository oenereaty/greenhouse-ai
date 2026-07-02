"""Greenhouse MCP server — exposes sensor, growth, and decision-history tools.

BI2026(온실 진단 앱)의 mcp_server.py에서 이식. agent/agent.py가 서브프로세스로
직접 실행하므로(`python agent/server.py`), 저장소 루트를 sys.path에 추가해
tools/·rag/ 패키지를 임포트할 수 있게 한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.server.fastmcp import FastMCP
from tools.simulator import generate_sensor_data, generate_history
from tools.growth_data import query as growth_query, latest as growth_latest, add_record
from rag.pipeline import load_decisions

mcp = FastMCP("greenhouse")


@mcp.tool()
def get_sensor_data() -> dict:
    """현재 온실 센서 데이터 조회 (온도·습도·CO2·일사량)."""
    return generate_sensor_data()


@mcp.tool()
def get_sensor_history(hours: int = 24) -> list:
    """최근 N시간 온실 센서 시계열 데이터 조회.

    Args:
        hours: 조회할 시간 수 (기본 24시간)
    """
    return generate_history(hours=hours)


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
