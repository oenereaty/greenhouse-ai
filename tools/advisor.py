"""조치 제안 생성(LLM) + 농장주 응답 로깅.

FastAPI 백엔드와 MCP 에이전트가 공용으로 사용해야 하므로 tools 계층에 둔다.
"""
import json
import os
from datetime import datetime
from pathlib import Path

import requests

from tools.demo_clock import demo_now

BASE_DIR = Path(__file__).parent.parent
ADVICE_LOG = BASE_DIR / "advice_log.json"
OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"

RAG_CHECK_FILE = BASE_DIR / ".last_rag_check"
RAG_CHECK_INTERVAL = int(os.getenv("RAG_CHECK_INTERVAL_MINUTES", "60"))

_ALERT_SYSTEM = (
    "당신은 토마토 온실 관리 전문가입니다. "
    "현재 센서값과 아래 참고 문서를 보고, 지금 즉각 조치가 필요한 위험 상황인지 판단하세요.\n"
    "제어 우선순위는 온도·습도 안정화가 1순위이고 CO₂ 관리는 그 다음입니다. "
    "습도 90% 이상 또는 온도 28℃ 이상이면 CO₂ 시비보다 환기·순환·차광을 우선하십시오. "
    "환기가 필요한 상태에서는 CO₂ 시비를 제안하지 마십시오.\n"
    "반드시 아래 세 줄 형식으로만 답하세요:\n"
    "경보: 예 또는 아니오\n"
    "상황: [현재 상태 한 문장 — 수치 포함, 왜 문제인지, 참고한 문서의 실제 파일명을 대괄호로 "
    "인용 예: [02_vpd.md]]\n"
    "조치: [지금 당장 해야 할 조치 한 문장, 참고 파일명 인용]\n"
    "경보가 아니오이면 상황과 조치는 '정상'이라고만 쓰세요.\n"
    "참고 문서에서 확인되지 않는 내용은 기재하지 마세요. "
    "[근거1]처럼 번호로만 인용하지 말고 반드시 실제 파일명을 쓰십시오. "
    "'매우', '극심', '심각' 등 과장된 표현은 쓰지 말고 사실과 수치에 기반한 중립적 어조로 쓰십시오."
)

_SYSTEM = (
    "당신은 토마토 온실 관리 전문가입니다. "
    "현재 센서값과 참고 규칙을 보고, 농장주가 지금 당장 취해야 할 조치 1가지를 제안하십시오. "
    "제어 우선순위는 온도·습도 안정화가 1순위이고 CO₂ 관리는 그 다음입니다. "
    "습도 90% 이상 또는 온도 28℃ 이상이면 CO₂ 부족보다 환기·순환·차광으로 온습도를 먼저 낮추십시오. "
    "단, 외기 습도도 높거나(예: 90% 이상) 강수 중이면 창을 크게 여는 단순 환기로는 실내 절대습도가 "
    "낮아지지 않고 온도만 떨어져 결로·고습성 병해 위험이 커질 수 있습니다 — 이 경우 큰 폭 개방 환기 "
    "대신 순환팬 가동과 제한적 환기, 필요하면 소폭 난방을 함께 권하십시오. "
    "온도가 적정 범위여도 습도가 위험 수준이면 '현 상태 유지'라고만 하지 말고, 습도를 낮추기 위한 "
    "순환·제한적 환기·난방 조치를 함께 제시하십시오. "
    "환기가 필요한 상태에서는 CO₂ 시비를 제안하지 말고, 일사량이 있는 낮 시간 CO₂ 하락은 광합성 소비로 "
    "해석할 수 있다고 설명하십시오. "
    "CO₂ 시비를 제안하기 전에 반드시 현재 시각과 일사량으로 광합성 가능 여부를 확인하십시오. "
    "일사량이 매우 낮거나(예: 30W/m² 미만) 야간 시간대라면 광합성이 거의 일어나지 않으므로 CO₂가 낮아도 "
    "시비를 제안하지 마십시오. 단, 야간 CO₂ 저하를 '작물 호흡' 때문이라고 설명하지 마십시오 — 호흡은 "
    "야간에 CO₂를 오히려 높이는 방향이므로, 대기 수준(약 400ppm)보다 낮은 야간 CO₂는 센서 오차·직전 "
    "환기·외기 유입 가능성으로 설명하십시오. "
    "생육 상태(화방높이 기준 생식/영양생장 균형, 초장·줄기두께 추세)가 주어지면 온습도 조치와 함께 고려하십시오 — "
    "예: 영양생장이 우세하면 주야간 온도차 확대나 야간온도 소폭 하강처럼 생식생장을 유도하는 방향을 우선 검토하고, "
    "생식생장이 우세하면 무리한 변온으로 과실 비대를 방해하지 않도록 하십시오. 단, 온습도 위험(과습·고온)이 있으면 그것이 항상 1순위입니다. "
    "반드시 아래 두 줄 형식으로만 답하십시오:\n"
    "상황: [현재 온실 상태 한 문장 — 수치 포함, 참고한 문서의 실제 파일명을 대괄호로 "
    "인용 예: [01_temperature.md]]\n"
    "제안: [구체적인 조치 1가지 한 문장, 참고 파일명 인용]\n"
    "참고 문서에서 확인되지 않는 내용은 기재하지 마세요. "
    "[근거1]처럼 번호로만 인용하지 말고 반드시 실제 파일명을 쓰십시오. "
    "'매우', '극심', '심각' 등 과장된 표현은 쓰지 말고 사실과 수치에 기반한 중립적 어조로 쓰십시오."
)


def _control_priority_note(sensor: dict) -> str:
    try:
        temp = float(sensor.get("temp", 0))
        rh = float(sensor.get("rh", 0))
        co2 = float(sensor.get("co2", 0))
        solar = float(sensor.get("solar", 0))
    except (TypeError, ValueError):
        return "제어 우선순위: 온도·습도 안정화가 1순위이고 CO₂ 관리는 그 다음입니다."

    is_night = solar < 30
    co2_note = (
        "CO₂가 낮다면 낮 시간 광합성 소비 가능성으로 해석하세요."
        if not is_night else
        "지금은 야간(일사량 낮음)이라 CO₂ 저하를 광합성 소비로 설명하지 마세요 — 호흡은 야간에 CO₂를 "
        "오히려 높이는 방향이므로, 야간에 CO₂가 낮게 측정되면 센서 오차·직전 환기·외기 유입 가능성을 "
        "언급하세요."
    )
    if rh >= 90 or temp >= 28:
        return (
            "제어 우선순위: 현재는 온도·습도 안정화가 1순위입니다. "
            "환기·순환·차광이 필요한 상태이므로 CO₂ 시비를 제안하지 마세요. "
            f"{co2_note}"
        )
    if co2 < 400 and solar > 100:
        return (
            "제어 우선순위: CO₂ 시비는 온도·습도가 안정적이고 "
            "환기 개도를 낮게 유지할 수 있을 때만 검토하세요."
        )
    return "제어 우선순위: 온도·습도 안정화가 1순위이고 CO₂ 관리는 그 다음입니다."


def generate_advice(
    sensor: dict,
    outdoor: dict | None,
    rag_context: str,
    model: str = "gemma4:12b",
    growth_context: str = "",
) -> dict:
    """현재 상황 요약 + 조치 1가지를 LLM으로 생성.

    growth_context: 구역별 생식/영양생장 균형(화방높이)·초장·줄기두께 추세 요약.
    비어 있으면(생육 기록 없음) 해당 줄을 생략한다 — 온도·습도만으로 판단.
    """
    od = outdoor or {}
    growth_line = f"- 생육 상태: {growth_context}\n" if growth_context else ""
    user_msg = (
        f"현재 온실 상태 ({sensor.get('timestamp', '?')} 기준):\n"
        f"- 온도 {sensor.get('temp')}℃  습도 {sensor.get('rh')}%  "
        f"CO₂ {sensor.get('co2')}ppm  일사 {sensor.get('solar')}W/m²\n"
        f"- 외기 {od.get('outdoor_temp', '?')}℃  "
        f"풍속 {od.get('wind_speed', '?')}m/s ({od.get('wind_dir_kor', '')})\n"
        f"{growth_line}"
        f"- {_control_priority_note(sensor)}\n\n"
        f"참고 규칙:\n{rag_context}"
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        "stream": False,
        # gemma4는 사고형(thinking) 모델이라 응답을 message.content가 아니라
        # message.thinking에 먼저 채운다. num_predict가 작으면(Ollama 기본
        # ~2048토큰) 사고 과정만 쓰다가 토큰이 끝나 content가 항상 빈 채로
        # 남는다(재시도로도 해결 안 됨 — 실측 확인). 사고를 끝내고 content까지
        # 쓸 수 있도록 충분히 크게 잡는다.
        "options": {"num_ctx": 8192, "num_predict": 4096},
    }
    raw = ""
    for _ in range(6):
        resp = requests.post(OLLAMA_CHAT_URL, json=payload, timeout=300)
        resp.raise_for_status()
        raw = resp.json()["message"]["content"].strip()
        if raw:
            break

    situation, recommendation = "", ""
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("상황:"):
            situation = stripped[3:].strip()
        elif stripped.startswith("제안:"):
            recommendation = stripped[3:].strip()

    if not situation and not recommendation and raw:
        # LLM이 "상황:"/"제안:" 형식을 지키지 않은 경우 — 원문이라도 보여준다.
        situation = raw

    return {
        "situation": situation or ("LLM이 빈 응답을 반환했습니다. 다시 시도해 주세요." if not raw else raw),
        "recommendation": recommendation,
        "generated_at": demo_now().isoformat(timespec="seconds"),
        "sensor": sensor,
        "outdoor": od or None,
    }


def save_response(advice: dict, response: str) -> dict:
    """농장주 응답을 로그에 추가. response: 'y' | 'n' | 자유 텍스트."""
    entry = {
        **advice,
        "farmer_response": response,
        "responded_at": demo_now().isoformat(timespec="seconds"),
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


def rag_alert_check(sensor: dict, outdoor: dict | None, col, model: str = "gemma4:12b") -> dict:
    """PDF/RAG 기반 위험 상황 감지. Returns {alert, situation, recommendation}."""
    from rag.pipeline import calc_vpd, search as rag_search

    temp = float(sensor.get("temp", 0))
    rh = float(sensor.get("rh", 100))
    co2 = float(sensor.get("co2", 0))
    solar = float(sensor.get("solar", 0))
    vpd = calc_vpd(temp, rh)
    od = outdoor or {}

    query = f"온도 {temp}℃ 습도 {rh}% CO2 {co2}ppm VPD {vpd}kPa 위험 주의 이상 조치"
    docs = rag_search(col, query, n_results=5)
    context = "\n\n".join(
        f"[{d['meta'].get('source_file')}] {d['text'][:400]}" for d in docs
    )

    outdoor_line = (
        f"외기 {od.get('outdoor_temp','?')}℃, 풍속 {od.get('wind_speed','?')}m/s"
        if od else ""
    )
    user_msg = (
        f"현재 온실:\n"
        f"온도 {temp}℃  습도 {rh}%  CO₂ {int(co2)}ppm  일사 {solar}W/m²  VPD {vpd}kPa\n"
        f"{_control_priority_note(sensor)}\n"
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
        # gemma4는 사고형 모델이라 num_predict가 작으면 사고만 하다 끝나 content가
        # 항상 빈 채로 남는다 — generate_advice()와 동일 원인/수정.
        "options": {"num_ctx": 8192, "num_predict": 3072},
    }
    raw = ""
    for _ in range(4):
        resp = requests.post(OLLAMA_CHAT_URL, json=payload, timeout=300)
        resp.raise_for_status()
        raw = resp.json()["message"]["content"].strip()
        if raw:
            break

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


def mark_rag_checked() -> None:
    RAG_CHECK_FILE.write_text(datetime.now().isoformat(), encoding="utf-8")
