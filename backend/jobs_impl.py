"""job store(backend/jobs.py)로 실행되는 느린 작업들의 실제 구현.

diagnose()/generate_advice()/agent.ask()처럼 이미 그대로 콜러블인 함수는 라우터에서
바로 jobs.create_job(fn, ...)에 넘기면 되므로 여기 없다. 여기 있는 것들은 기존
ui/app.py에 인라인으로 있던 "RAG 검색 + 프롬프트 조립 + Ollama 호출 + 부수효과 저장"
오케스트레이션을 포팅한 것들이다.
"""
from backend.ollama_client import chat as ollama_chat

_BRIEFING_SYSTEM = (
    "당신은 농업 전문 데이터 분석가이자 AI 농업 컨설턴트입니다. "
    "아래 제공된 뉴스 기사 목록만 근거로 토마토 가격 변동 요인을 분석해 브리핑하십시오.\n"
    "- 구조적 일반론을 금지합니다. '기후 변화', '노동력 감소', '인건비 부담'처럼 당연한 말만 반복하지 마십시오.\n"
    "- 최저임금, 유가, 면세유, 환율, 전기요금, 비료·농자재, 물류비, 수입물량, 출하량, 폭염·호우 같은 "
    "뉴스 속보성 변수만 뽑아 가격 영향 방향을 설명하십시오.\n"
    "- 각 항목은 '변수 -> 토마토 가격에 미치는 방향 -> 지금 확인할 지표' 순서로 쓰십시오.\n"
    "- 기사에 구체적 단기 신호가 없으면 억지로 일반론을 만들지 말고 '오늘 수집 기사만으로는 급박한 가격 변수 확인 불가'라고 쓰십시오.\n"
    "- '예상됩니다' 대신 '현재 [변수] 기사로 인해 [비용/수급] 압력이 제기되고 있습니다'와 같은 중립적·분석적 어조를 사용하십시오.\n"
    "- 제공된 기사 목록에 없는 내용은 지어내지 마십시오.\n"
    "- 굵게 표시를 위한 ** 같은 마크다운 강조 기호를 쓰지 마십시오.\n"
    "- 답변 마지막에 반드시 참고한 기사의 출처(기사 제목/매체/날짜)를 목록으로 명시하십시오.\n"
    "- 5문단 이내로 짧고 긴급 브리핑처럼 작성하십시오.\n"
    "- '매우', '극심', '심각' 등 과장된 표현은 쓰지 말고 사실과 수치에 기반한 중립적 어조로 쓰십시오."
)

_PLAN_SYSTEM = (
    "당신은 토마토 온실 관리 전문가입니다. 농가의 영농일지에 기록된 다가오는 계획과 "
    "참고자료를 바탕으로, 오늘부터 그 계획일까지 미리 준비하거나 점검해야 할 일을 "
    "간결하게 안내하십시오.\n"
    "- 남은 일수를 고려해 지금 당장 할 일과 계획일 직전에 할 일을 구분하십시오.\n"
    "- '환기 잘 되는지 확인하세요', '병해충 주의하세요'처럼 재배 경력이 있는 농가라면 이미 "
    "아는 당연한 일반론은 쓰지 마십시오. 이번 계획·시기·최근 일지 기록에 실제로 해당하는 "
    "구체적인 점검 항목만 쓰십시오.\n"
    "- 이 농가는 해당 온실의 실제 여건을 농촌진흥청 등 일반 참고자료보다 더 잘 알고 있을 "
    "수 있습니다. 제안은 단정적 지시가 아니라 '~인지 확인해 보세요' 형태로, 농가가 다르게 "
    "판단할 수 있는 여지를 남기십시오.\n"
    "- 현재 온실 센서값이 주어지면 계획과 관련 있을 때만 참고해 한 문장 정도로 자연스럽게 "
    "반영하십시오. 여러 조건을 저울질하거나 우선순위를 재판단하려 하지 말고, 있는 그대로 "
    "참고만 하십시오.\n"
    "- 참고자료에서 확인되지 않는 내용은 일반 상식 수준으로만 제안하고 그렇게 명시하십시오.\n"
    "- 3~5개 항목의 짧은 체크리스트 형태로 답하십시오.\n"
    "- '매우', '극심', '심각' 등 과장된 표현은 쓰지 말고 사실과 수치에 기반한 중립적 어조로 쓰십시오."
)

_PLAN_FEEDBACK_SYSTEM = (
    "당신은 토마토 온실 관리 전문가입니다. 이전에 다가오는 계획에 대한 준비사항 체크리스트를 "
    "제안했는데, 농가가 그 제안에 대해 의견(이의 제기, 현장 사정, 범위 조정 요청 등)을 남겼습니다.\n"
    "- 농가의 의견을 먼저 인정하십시오. 농가는 해당 온실의 실제 여건을 참고자료보다 더 잘 알고 "
    "있을 수 있습니다. 농가 의견이 타당하면 그대로 받아들여 체크리스트를 수정하십시오.\n"
    "- 농가 의견이 참고자료와 어긋나는데 근거가 불충분해 보이면, 반박하지 말고 '참고자료 기준은 "
    "~이지만, 농가님 판단대로 ~로 조정해도 괜찮습니다' 형태로 절충안을 제시하십시오.\n"
    "- 이전 체크리스트를 처음부터 다시 설명하지 말고, 농가 의견을 반영해 달라진 부분 위주로 "
    "간결하게 답하십시오.\n"
    "- '매우', '극심', '심각' 등 과장된 표현은 쓰지 말고 사실과 수치에 기반한 중립적 어조로 쓰십시오."
)

_NUTRIENT_SYSTEM = (
    "당신은 작물영양학 전문가입니다. 농가가 입력한 양액 조성 수치(N/P/K/Ca/Mg/EC/pH)와 "
    "관찰된 증상, 과거 조성 이력, 참고자료를 바탕으로 다음을 분석하십시오.\n"
    "1. 증상과 가장 관련 있어 보이는 성분(부족 또는 과잉)\n"
    "2. 그렇게 판단한 근거 (수치·증상·참고자료 인용)\n"
    "3. 조성 비율 조정 제안 (구체적 수치 변화 방향)\n"
    "참고자료에서 확인되지 않는 내용은 추정임을 명시하십시오. "
    "이 분석은 참고용이며 정확한 처방은 전문가 확인이 필요함을 마지막에 안내하십시오. "
    "'매우', '극심', '심각' 등 과장된 표현은 쓰지 말고 사실과 수치에 기반한 중립적 어조로 쓰십시오."
)

_DISEASE_SYSTEM = (
    "당신은 농업 전문 데이터 분석가이자 AI 농업 컨설턴트입니다. "
    "사용자가 업로드한 병해 이미지와 증상 설명을 바탕으로 병해를 진단하십시오.\n"
    "사용자 메시지에 지식베이스 참고자료가 포함되어 있으면, 사진 속 증상을 그 자료와 반드시 "
    "대조한 뒤 가장 가능성 높은 병해명을 판단하고, 일치하는 자료가 있으면 자료명을 함께 언급하십시오. "
    "참고자료에서 확인되지 않는 병명은 추측임을 명시하십시오.\n"
    "반드시 아래 순서로만 답변하십시오:\n"
    "1. 의심되는 병해명 및 가능성\n"
    "2. 병해의 주요 특징\n"
    "3. 농촌진흥청/전문 기관에 근거한 일반적인 방제 방법\n"
    "4. [경고] 본 진단은 AI 보조 도구일 뿐, 정확한 진단을 위해 반드시 인근 농업기술센터나 "
    "전문가의 확인을 받으십시오.\n"
    "'매우', '극심', '심각' 등 과장된 표현은 쓰지 말고 사실과 수치에 기반한 중립적 어조로 쓰십시오."
)


def _rag_context(query: str, n_results: int = 3) -> str:
    from rag.pipeline import build_vectorstore, search
    col = build_vectorstore()
    docs = search(col, query, n_results=n_results)
    if not docs:
        return "(관련 참고자료 없음)"
    return "\n\n".join(f"[{d['meta'].get('source_file')}]\n{d['text'][:400]}" for d in docs)


def run_price_briefing(per_query_count: int = 5) -> dict:
    from backend.config import get_settings
    from tools.naver_news import fetch_price_factor_articles

    settings = get_settings()
    articles = fetch_price_factor_articles(
        settings.naver_client_id, settings.naver_client_secret, per_query_count=per_query_count,
    )
    if not articles:
        return {"content": "관련 뉴스 기사를 찾지 못했습니다.", "articles": []}

    src_lines = "\n".join(
        f"- 검색축: {a.get('query', '기타')} | 제목: {a['title']} | 매체: {a['media']} | 날짜: {a['pub_date']} | 요약: {a['description']}"
        for a in articles
    )
    content = ollama_chat(
        messages=[
            {"role": "system", "content": _BRIEFING_SYSTEM},
            {"role": "user", "content":
                f"다음은 오늘 수집된 관련 뉴스 기사 목록입니다:\n\n{src_lines}\n\n"
                "위 기사들을 근거로 토마토 가격 변동 요인 브리핑을 작성하세요. "
                "최저임금·유가·환율·전기요금·농자재·물류비·수급·기상 재해처럼 단기적으로 변하는 변수만 우선하십시오."},
        ],
        options={"num_predict": 4096, "num_ctx": 8192},
        timeout=300,
    )
    return {"content": content, "articles": articles}


def run_image_diagnosis(image_b64: str, question: str) -> str:
    from rag.pipeline import build_vectorstore, search

    col = build_vectorstore()
    q = question or "이 온실 토마토 사진을 분석해서 병해·생육 상태를 진단해줘."
    pest_rows = col.get(where={"source_file": "토마토 병해충 및 방제 list.pdf"})
    pest_context = "\n\n".join(pest_rows.get("documents", []))
    disease_docs = search(col, f"{q} 토마토 병해충 증상 진단", n_results=3)
    ref_context = (
        "\n\n".join(f"[{d['meta'].get('source_file')}]\n{d['text'][:500]}" for d in disease_docs)
        if disease_docs else "(관련 참고자료 없음)"
    )
    user_content = (
        f"{q}\n\n[토마토 병해충 및 방제 등록약제 전체 목록]\n{pest_context}\n\n"
        f"아래는 지식베이스에서 검색된 추가 참고자료입니다.\n\n{ref_context}"
    )
    return ollama_chat(
        messages=[
            {"role": "system", "content": _DISEASE_SYSTEM},
            {"role": "user", "content": user_content, "images": [image_b64]},
        ],
        options={"num_predict": 4096, "num_ctx": 32768},
        timeout=300,
    )


def _current_env_line() -> str:
    """현재 센서·외기값을 사실 나열로만 반환 — 우선순위 판단 지시는 넣지 않는다
    (여러 신호를 저울질하게 하면 gemma4가 결론을 못 내고 사고 루프에 빠지는
    현상이 관찰됨). plan-check는 참고용 사실 한 줄만 필요하다."""
    from tools.sensor_client import fetch_sensors
    try:
        sd = fetch_sensors()
        return f"현재 온실: 온도 {sd.get('temp')}℃ 습도 {sd.get('rh')}% CO2 {sd.get('co2')}ppm"
    except Exception:
        return ""


def run_plan_check(date_str: str, plan_summary: str, days_left: int) -> str:
    from tools.demo_clock import demo_now
    ref = _rag_context(plan_summary, n_results=3)
    env_line = _current_env_line()
    env_part = f"\n{env_line}" if env_line else ""
    user = (
        f"오늘은 {demo_now().date().isoformat()}이고, {date_str}({days_left}일 후)에 다음 계획이 "
        f"영농일지에 기록되어 있습니다: \"{plan_summary}\"{env_part}\n\n참고자료:\n{ref}"
    )
    return ollama_chat(
        messages=[
            {"role": "system", "content": _PLAN_SYSTEM},
            {"role": "user", "content": user},
        ],
        options={"num_predict": 1024, "num_ctx": 8192},
        timeout=300,
    )


def run_plan_check_feedback(
    date_str: str, plan_summary: str, days_left: int, prev_checklist: str, farmer_feedback: str,
) -> str:
    """농가가 이전 체크리스트에 남긴 의견을 반영해 다시 답변."""
    from tools.demo_clock import demo_now
    ref = _rag_context(plan_summary, n_results=3)
    user = (
        f"오늘은 {demo_now().date().isoformat()}이고, {date_str}({days_left}일 후)에 다음 계획이 "
        f"영농일지에 기록되어 있습니다: \"{plan_summary}\"\n\n"
        f"[이전 체크리스트]\n{prev_checklist}\n\n"
        f"[농가 의견]\n{farmer_feedback}\n\n참고자료:\n{ref}"
    )
    return ollama_chat(
        messages=[
            {"role": "system", "content": _PLAN_FEEDBACK_SYSTEM},
            {"role": "user", "content": user},
        ],
        options={"num_predict": 1024, "num_ctx": 8192},
        timeout=300,
    )


def run_nutrient_analysis(date_str: str, idx: int, recipe: dict, symptom: str) -> str:
    from tools.nutrient_log import flat_entries, update_analysis

    history = flat_entries(limit=5)
    history_txt = "\n".join(
        f"{h['date']} {h.get('time','')}: N{h['recipe'].get('n','—')}/P{h['recipe'].get('p','—')}/"
        f"K{h['recipe'].get('k','—')}/Ca{h['recipe'].get('ca','—')}/Mg{h['recipe'].get('mg','—')} "
        f"EC{h['recipe'].get('ec','—')} pH{h['recipe'].get('ph','—')}"
        + (f" · 증상: {h['symptom']}" if h.get("symptom") else "")
        for h in history
    ) or "(이전 기록 없음)"

    query = f"양액 N{recipe.get('n')} P{recipe.get('p')} K{recipe.get('k')} 증상 {symptom}"
    ref = _rag_context(query, n_results=4)
    user = (
        f"[현재 조성] N{recipe.get('n')} P{recipe.get('p')} K{recipe.get('k')} "
        f"Ca{recipe.get('ca')} Mg{recipe.get('mg')} EC{recipe.get('ec')} pH{recipe.get('ph')}\n"
        f"[관찰된 증상] {symptom or '없음'}\n\n[과거 조성 이력]\n{history_txt}\n\n[참고자료]\n{ref}"
    )
    analysis = ollama_chat(
        messages=[
            {"role": "system", "content": _NUTRIENT_SYSTEM},
            {"role": "user", "content": user},
        ],
        options={"num_predict": 2048, "num_ctx": 8192},
        timeout=300,
    )
    update_analysis(date_str, idx, analysis)
    return analysis
