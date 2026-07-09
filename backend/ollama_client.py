"""Ollama /api/chat 호출을 한 곳에 모은 헬퍼.

기존 ui/app.py에는 호출 지점마다 model="gemma4:12b"가 하드코딩되어 있었다.
여기서는 backend.config.Settings.ollama_host/ollama_model을 기본값으로 쓰고,
호출부는 system prompt·options·timeout만 넘기면 된다.
"""
import requests

from backend.config import get_settings

# Ollama's default context window (~2k tokens) silently truncates long prompts
# (RAG context, many news articles), which makes the model return an empty
# response. Guarantee a sane window unless the caller overrides it explicitly.
DEFAULT_NUM_CTX = 8192

# gemma4:12b는 사고형(thinking) 모델이라 응답을 message.content가 아니라
# message.thinking에 먼저 채운다. num_predict가 너무 작으면 사고 과정만 쓰다가
# 토큰이 끝나 content가 항상 빈 채로 남는다(2026-07 실측 확인 — 재시도만으로는
# 해결 안 됨). 사고를 끝내고 content까지 쓸 수 있도록 충분히 크게 잡는다.
DEFAULT_NUM_PREDICT = 3072


def chat(
    messages: list[dict],
    model: str | None = None,
    options: dict | None = None,
    timeout: int = 300,
    max_attempts: int = 4,
) -> str:
    """messages는 이미 완성된 형태({"role":..., "content":..., "images": [...]?} 포함)로 전달."""
    settings = get_settings()
    merged_options = {"num_ctx": DEFAULT_NUM_CTX, "num_predict": DEFAULT_NUM_PREDICT}
    if options:
        merged_options.update(options)
    payload: dict = {
        "model": model or settings.ollama_model,
        "messages": messages,
        "stream": False,
        "options": merged_options,
    }
    content = ""
    for _ in range(max_attempts):
        resp = requests.post(f"{settings.ollama_host}/api/chat", json=payload, timeout=timeout)
        resp.raise_for_status()
        content = resp.json()["message"]["content"].strip()
        if content:
            return content
    raise RuntimeError(f"Ollama returned an empty response after {max_attempts} attempts")
