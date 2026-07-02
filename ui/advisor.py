"""조치 제안 생성(LLM) + 농장주 응답 로깅."""
import json
import os
from datetime import datetime
from pathlib import Path

import requests

ADVICE_LOG = Path(__file__).parent.parent / "advice_log.json"
OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"

RAG_CHECK_FILE = Path(__file__).parent.parent / ".last_rag_check"
RAG_CHECK_INTERVAL = int(os.getenv("RAG_CHECK_INTERVAL_MINUTES", "60"))

_ALERT_SYSTEM = (
    "당신은 토마토 온실 관리 전문가입니다. "
    "현재 센서값과 아래 참고 문서를 보고, 지금 즉각 조치가 필요한 위험 상황인지 판단하세요.\n"
    "반드시 아래 세 줄 형식으로만 답하세요:\n"
    "경보: 예 또는 아니오\n"
    "상황: [현재 상태 한 문장 — 수치 포함, 왜 문제인지]\n"
    "조치: [지금 당장 해야 할 조치 한 문장]\n"
    "경보가 아니오이면 상황과 조치는 '정상'이라고만 쓰세요."
)

_SYSTEM = (
    "당신은 토마토 온실 관리 전문가입니다. "
    "현재 센서값과 참고 규칙을 보고, 농장주가 지금 당장 취해야 할 조치 1가지를 제안하십시오. "
    "반드시 아래 두 줄 형식으로만 답하십시오:\n"
    "상황: [현재 온실 상태 한 문장 — 수치 포함]\n"
    "제안: [구체적인 조치 1가지 한 문장]"
)


def generate_advice(
    sensor: dict,
    outdoor: dict | None,
    rag_context: str,
    model: str = "gemma3:12b",
) -> dict:
    """현재 상황 요약 + 조치 1가지를 LLM으로 생성."""
    od = outdoor or {}
    user_msg = (
        f"현재 온실 상태:\n"
        f"- 온도 {sensor.get('temp')}℃  습도 {sensor.get('rh')}%  "
        f"CO₂ {sensor.get('co2')}ppm  일사 {sensor.get('solar')}W/m²\n"
        f"- 외기 {od.get('outdoor_temp', '?')}℃  "
        f"풍속 {od.get('wind_speed', '?')}m/s ({od.get('wind_dir_kor', '')})\n\n"
        f"참고 규칙:\n{rag_context}"
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user",   "content": user_msg},
        ],
        "stream": False,
    }
    resp = requests.post(OLLAMA_CHAT_URL, json=payload, timeout=60)
    resp.raise_for_status()
    raw = resp.json()["message"]["content"].strip()

    situation, recommendation = "", raw
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("상황:"):
            situation = stripped[3:].strip()
        elif stripped.startswith("제안:"):
            recommendation = stripped[3:].strip()

    return {
        "situation":      situation or raw,
        "recommendation": recommendation,
        "generated_at":   datetime.now().isoformat(timespec="seconds"),
        "sensor":         sensor,
        "outdoor":        od or None,
    }


def save_response(advice: dict, response: str) -> dict:
    """농장주 응답을 로그에 추가. response: 'y' | 'n' | 자유 텍스트."""
    entry = {
        **advice,
        "farmer_response": response,
        "responded_at":    datetime.now().isoformat(timespec="seconds"),
    }
    log = _load_raw()
    log.append(entry)
    ADVICE_LOG.write_text(
        json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return entry


def load_log(n: int = 20) -> list[dict]:
    return _load_raw()[-n:]


def _load_raw() -> list:
    if not ADVICE_LOG.exists():
        return []
    try:
        return json.loads(ADVICE_LOG.read_text(encoding="utf-8"))
    except Exception:
        return []


def rag_alert_check(sensor: dict, outdoor: dict | None, col, model: str = "gemma3:12b") -> dict:
    """PDF/RAG 기반 위험 상황 감지. Returns {alert, situation, recommendation}."""
    from rag.pipeline import search as rag_search, calc_vpd

    temp = float(sensor.get("temp", 0))
    rh = float(sensor.get("rh", 100))
    co2 = float(sensor.get("co2", 0))
    solar = float(sensor.get("solar", 0))
    vpd = calc_vpd(temp, rh)
    od = outdoor or {}

    query = f"온도 {temp}℃ 습도 {rh}% CO2 {co2}ppm VPD {vpd}kPa 위험 주의 이상 조치"
    docs = rag_search(col, query, n_results=5)
    context = "\n\n".join(d["text"][:400] for d in docs)

    outdoor_line = (
        f"외기 {od.get('outdoor_temp','?')}℃, 풍속 {od.get('wind_speed','?')}m/s"
        if od else ""
    )
    user_msg = (
        f"현재 온실:\n"
        f"온도 {temp}℃  습도 {rh}%  CO₂ {int(co2)}ppm  일사 {solar}W/m²  VPD {vpd}kPa\n"
        f"{outdoor_line}\n\n"
        f"참고 문서:\n{context}"
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _ALERT_SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        "stream": False,
    }
    resp = requests.post(OLLAMA_CHAT_URL, json=payload, timeout=90)
    resp.raise_for_status()
    raw = resp.json()["message"]["content"].strip()

    alert = False
    situation = "정상"
    recommendation = "정상"
    for line in raw.splitlines():
        s = line.strip()
        if s.startswith("경보:"):
            alert = "예" in s
        elif s.startswith("상황:"):
            situation = s[3:].strip()
        elif s.startswith("조치:"):
            recommendation = s[3:].strip()

    mark_rag_checked()
    return {"alert": alert, "situation": situation, "recommendation": recommendation}


def is_rag_check_due() -> bool:
    if not RAG_CHECK_FILE.exists():
        return True
    try:
        last = datetime.fromisoformat(RAG_CHECK_FILE.read_text().strip())
        return (datetime.now() - last).total_seconds() / 60 >= RAG_CHECK_INTERVAL
    except Exception:
        return True


def mark_rag_checked():
    RAG_CHECK_FILE.write_text(datetime.now().isoformat(), encoding="utf-8")
