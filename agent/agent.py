"""온실 토마토 의사결정 에이전트"""
import os
from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool

load_dotenv()

from tools.vpd_calculator import calculate_vpd, interpret_vpd
from tools.gdd_calculator import calculate_daily_gdd, get_growth_stage, is_fruit_set_at_risk
from tools.disease_risk import get_disease_alerts
from tools.sensor_simulator import get_greenhouse_data
from tools.kma_api import get_daily_summary
from rag.pipeline import retrieve


# ── MCP 도구 정의 ──────────────────────────────────────────────

@tool
def tool_get_greenhouse_status() -> dict:
    """현재 온실 내부 환경(온도, 습도, CO2)을 가져옵니다."""
    data = get_greenhouse_data()
    vpd = calculate_vpd(data["temperature"], data["humidity"])
    vpd_info = interpret_vpd(vpd)
    return {**data, "vpd_kpa": vpd, "vpd_status": vpd_info["status"], "vpd_message": vpd_info["message"]}


@tool
def tool_get_disease_risk() -> list:
    """현재 온실 환경 기반 병해 위험도를 계산합니다."""
    data = get_greenhouse_data()
    return get_disease_alerts(data["temperature"], data["humidity"])


@tool
def tool_get_fruit_set_risk(day_temps: list[float], night_temps: list[float]) -> dict:
    """최근 일별 최고·최저 기온 목록으로 착과 실패 위험을 판단합니다."""
    return is_fruit_set_at_risk(day_temps, night_temps)


@tool
def tool_get_weather_forecast() -> list:
    """기상청 3일 예보를 가져옵니다 (외기 기온·습도)."""
    nx = int(os.getenv("GREENHOUSE_NX", 60))
    ny = int(os.getenv("GREENHOUSE_NY", 127))
    return get_daily_summary(nx, ny, days=3)


@tool
def tool_retrieve_knowledge(query: str) -> str:
    """작물생리학 지식베이스에서 관련 정보를 검색합니다."""
    chunks = retrieve(query, k=3)
    return "\n\n".join(chunks)


# ── 에이전트 구성 ───────────────────────────────────────────────

TOOLS = [
    tool_get_greenhouse_status,
    tool_get_disease_risk,
    tool_get_fruit_set_risk,
    tool_get_weather_forecast,
    tool_retrieve_knowledge,
]

SYSTEM_PROMPT = """당신은 한국 온실 토마토 재배 전문 AI 어드바이저입니다.
농부의 질문에 답하거나, 자동 경보를 생성할 때 반드시 도구를 호출하여 실시간 데이터와 작물생리학 지식을 근거로 답변하세요.

답변 원칙:
- 수치 근거를 반드시 포함 (VPD, GDD, 위험도 점수 등)
- 즉각 조치가 필요한 경우 [긴급] 태그를 앞에 붙이세요
- 예측 불확실성이 있으면 솔직히 언급하세요
"""

prompt = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}"),
])

llm = ChatAnthropic(model="claude-sonnet-4-6", temperature=0)
agent = create_tool_calling_agent(llm, TOOLS, prompt)
executor = AgentExecutor(agent=agent, tools=TOOLS, verbose=True)


def ask(question: str) -> str:
    result = executor.invoke({"input": question})
    return result["output"]


if __name__ == "__main__":
    answer = ask("오늘 온실 상태 점검해줘. 착과 위험 있어?")
    print("\n=== 에이전트 답변 ===")
    print(answer)
