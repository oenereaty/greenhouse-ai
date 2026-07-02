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
DEFAULT_MODEL = "gemma3:12b"
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

def _chat(messages: list, tools: list, model: str, timeout: int = 180) -> dict:
    payload = {
        "model": model,
        "messages": messages,
        "tools": tools,
        "stream": False,
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
                    "도구를 먼저 호출하여 실제 데이터를 확인한 뒤 답변하세요."
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
