"""MCP ↔ Ollama bridge: agent/server.py 를 서브프로세스로 실행해
도구를 Ollama /api/chat에 노출하고, 도구 호출을 실행한 뒤 모델이
최종 텍스트 응답을 낼 때까지 반복한다.

BI2026(온실 진단 앱)의 mcp_client.py에서 이식 — LangChain+Claude API 대신
실제 MCP 프로토콜 + 로컬 Ollama 사용.
"""
import asyncio
import json
import sys
from pathlib import Path

import requests
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

BASE_DIR = Path(__file__).parent
OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"
DEFAULT_MODEL = "gemma4:12b"
MAX_TOOL_ROUNDS = 6  # prevent runaway loops


# ---------------------------------------------------------------------------
# MCP tool schema → Ollama tool format conversion
# ---------------------------------------------------------------------------

def _mcp_tool_to_ollama(tool) -> dict:
    """Convert an MCP Tool object to Ollama /api/chat tools format."""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": tool.inputSchema if tool.inputSchema else {"type": "object", "properties": {}},
        },
    }


# ---------------------------------------------------------------------------
# Ollama /api/chat call (synchronous)
# ---------------------------------------------------------------------------

def _chat(messages: list, tools: list, model: str, timeout: int = 600) -> dict:
    payload = {
        "model": model,
        "messages": messages,
        "tools": tools,
        "stream": False,
        # gemma4는 사고형 모델이라 num_predict가 작으면 사고만 하다 끝나 content가
        # 빈 채로 남는다(backend/ollama_client.py와 동일 원인/수정).
        "options": {"num_ctx": 8192, "num_predict": 3072},
    }
    resp = requests.post(OLLAMA_CHAT_URL, json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Main async agent loop
# ---------------------------------------------------------------------------

async def run_agent(
    question: str,
    rag_context: str = "",
    model: str = DEFAULT_MODEL,
    system_prompt: str | None = None,
) -> str:
    """Run a full RAG + MCP + Ollama agent turn.

    Args:
        question: 사용자 질문
        rag_context: RAG로 검색된 문서 컨텍스트 (선택)
        model: Ollama 모델명
        system_prompt: 커스텀 시스템 프롬프트

    Returns:
        최종 LLM 응답 텍스트
    """
    server_params = StdioServerParameters(
        command=sys.executable,
        args=[str(BASE_DIR / "server.py")],
        env=None,
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools_result = await session.list_tools()
            ollama_tools = [_mcp_tool_to_ollama(t) for t in tools_result.tools]

            if system_prompt is None:
                system_prompt = (
                    "당신은 한국 온실 토마토 재배를 지원하는 농업 AI 어시스턴트입니다.\n"
                    "제공된 도구로 실시간 센서·생육·가격 데이터를 조회하고, "
                    "RAG 지식베이스를 참고하여 한국어로 정확하고 실용적인 조언을 제공합니다.\n"
                    "도구를 먼저 호출하여 실제 데이터를 확인한 뒤 답변하세요.\n"
                    "CO2 시비 여부를 판단할 때는 센서 데이터의 timestamp(현재 시각)와 일사량을 반드시 확인해 "
                    "광합성이 가능한 시간대인지 먼저 판단하세요. 일사량이 매우 낮거나(예: 30W/m² 미만) "
                    "야간 시간대라면 광합성이 거의 일어나지 않으므로 CO2가 낮게 측정되더라도 시비를 권하지 마세요. "
                    "단, 야간 CO2 저하를 '작물 호흡' 때문이라고 설명하지 마세요 — 호흡은 야간에 CO2를 오히려 "
                    "높이는 방향이므로, 대기 수준(약 400ppm)보다 낮은 야간 CO2는 센서 오차·직전 환기·외기 유입 "
                    "가능성으로 설명하세요(광합성 소비로 설명하는 것은 일사량이 있는 낮 시간에만 해당합니다).\n"
                    "습도 90% 이상 또는 온도 28℃ 이상이면 환기·순환·차광을 우선하세요. 단, 외기 습도도 높거나 "
                    "강수 중이면 창을 크게 여는 단순 환기로는 실내 절대습도가 낮아지지 않고 온도만 떨어져 결로·"
                    "고습성 병해 위험이 커질 수 있으므로, 이 경우 큰 폭 개방 환기 대신 순환팬 가동과 제한적 "
                    "환기, 필요하면 소폭 난방을 함께 권하세요. 온도가 적정 범위여도 습도가 위험 수준이면 "
                    "'현 상태 유지'라고만 하지 말고 습도를 낮추는 조치를 함께 제시하세요.\n"
                    "'매우', '극심', '심각' 등 과장된 표현은 쓰지 말고 사실과 수치에 기반한 중립적 어조로 답하세요."
                )

            user_content = question
            if rag_context:
                user_content = (
                    f"[참고 문서]\n{rag_context}\n\n"
                    f"[질문]\n{question}"
                )

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ]

            for _ in range(MAX_TOOL_ROUNDS):
                result = _chat(messages, ollama_tools, model)
                msg = result.get("message", {})
                tool_calls = msg.get("tool_calls", [])

                if not tool_calls:
                    return msg.get("content", "").strip()

                messages.append({"role": "assistant", **msg})

                for tc in tool_calls:
                    fn = tc.get("function", {})
                    tool_name = fn.get("name", "")
                    tool_args = fn.get("arguments", {})
                    if isinstance(tool_args, str):
                        try:
                            tool_args = json.loads(tool_args)
                        except json.JSONDecodeError:
                            tool_args = {}

                    try:
                        call_result = await session.call_tool(tool_name, tool_args)
                        tool_output = json.dumps(
                            [c.text if hasattr(c, "text") else str(c) for c in call_result.content],
                            ensure_ascii=False,
                        )
                    except Exception as e:
                        tool_output = f"도구 실행 오류: {e}"

                    messages.append({
                        "role": "tool",
                        "content": tool_output,
                    })

            return "최대 도구 호출 횟수에 도달했습니다. 다시 시도하세요."


# ---------------------------------------------------------------------------
# Convenience wrapper for sync callers (e.g. Streamlit, reports/weekly_report.py)
# ---------------------------------------------------------------------------

def ask(
    question: str,
    rag_context: str = "",
    model: str = DEFAULT_MODEL,
) -> str:
    """Synchronous wrapper around run_agent."""
    return asyncio.run(run_agent(question, rag_context=rag_context, model=model))


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "현재 온실 상태를 진단하고 필요한 조치를 알려줘."
    print(f"\n질문: {q}\n{'─'*60}")
    answer = ask(q)
    print(answer)
