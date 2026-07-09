"""Streamlit UI: greenhouse RAG diagnosis — 6-tab layout."""
import sys
import json
import math
import io
import random
import time
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import altair as alt
from datetime import datetime, date, timedelta
from pathlib import Path


def calc_abs_humidity(temp: float, rh: float) -> float:
    """절대 습도 (g/m³) — Tetens 공식 기반"""
    return round(rh / 100 * 6.112 * math.exp(17.67 * temp / (temp + 243.5)) * 216.7 / (temp + 273.15), 1)


def calc_saturation_ah(temp: float) -> float:
    """포화 절대습도 (g/m³) — 상대습도 100% 기준(그 온도가 머금을 수 있는 최대 수분)."""
    return calc_abs_humidity(temp, 100.0)


def calc_moisture_deficit(temp: float, rh: float) -> float:
    """수분부족분 HD (g/m³) = 포화 절대습도 − 현재 절대습도."""
    return round(calc_saturation_ah(temp) - calc_abs_humidity(temp, rh), 1)


# KMA 단기예보 하늘상태(SKY) → (라벨, 아이콘, 광량 추정) · 강수형태(PTY)
_SKY_LABEL = {"1": ("맑음", "☀️", "강"), "3": ("구름많음", "⛅", "중"), "4": ("흐림", "☁️", "약")}
_PTY_LABEL = {"0": "", "1": "비", "2": "비/눈", "3": "눈", "4": "소나기"}


def sky_info(sky: str | None, pty: str | None = None) -> tuple[str, str]:
    """(하늘상태 표시, 예보 광량 추정) 반환. 광량은 KMA에 직접값이 없어 하늘상태 기반 추정."""
    _lbl, _icon, _light = _SKY_LABEL.get(str(sky), ("—", "", "—"))
    _p = _PTY_LABEL.get(str(pty), "")
    disp = f"{_icon} {_lbl}" + (f"·{_p}" if _p else "")
    return disp, _light


def _env_interpret(temp: float, rh: float, vpd: float, co2: int, solar: float,
                    outdoor: dict | None = None) -> list[dict]:
    """센서값 → 자연어 해석 카드 목록 반환.
    각 항목: {icon, title, body, level}  (level: ok / warn / danger)

    습도는 RH를 1차 직접제어 기준(ASABE 2015 A등급, 지식베이스 02_vpd.md)으로 판단하고,
    환기가 필요한 경우 외기 습도를 함께 확인한다(04_ventilation.md 조치원칙 — 외기가
    더 습하면 환기 대신 온도를 소폭 올리는 편이 효과적). VPD는 보조 참고 지표로 유지한다.
    """
    cards = []
    _out_rh = (outdoor or {}).get("outdoor_rh")

    def _vent_note() -> str:
        if _out_rh is None:
            return "환기를 검토하되, 외기 습도를 먼저 확인하세요(외기도 습하면 환기 대신 온도를 올리는 게 효과적입니다)."
        if _out_rh < rh - 10:
            return f"외기 습도({_out_rh}%)가 더 낮아 환기가 효과적입니다. 창을 여세요."
        return f"외기 습도({_out_rh}%)도 높아 환기 효과가 제한적입니다. 실내 온도를 1~2℃ 올려 상대습도를 낮추는 방법을 검토하세요."

    # ── 습도(RH) 1차 판단 — ASABE A등급 기준 (02_vpd.md)
    if rh >= 90:
        cards.append({"icon": "💧", "title": f"습도 {rh}% — 과습 위험",
                      "body": f"90% 초과는 화분 열스트레스·균류 병해(잿빛곰팡이·역병) 위험 구간입니다. {_vent_note()}",
                      "level": "danger"})
    elif rh >= 80:
        cards.append({"icon": "💧", "title": f"습도 {rh}% — 다소 과습",
                      "body": f"적정 상한(70~80%)에 근접했습니다. {_vent_note()}",
                      "level": "warn"})
    elif rh < 50:
        _dry_note = (
            f" (외기 습도 {_out_rh}%도 낮아 창을 닫는 게 유리합니다.)"
            if _out_rh is not None and _out_rh < rh else ""
        )
        cards.append({"icon": "🏜️", "title": f"습도 {rh}% — 건조",
                      "body": f"50% 미만은 증산 과다·칼슘 이동 저해(배꼽썩음 위험) 구간입니다. 창을 닫고 관수 횟수를 늘리세요.{_dry_note}",
                      "level": "warn"})
    else:
        cards.append({"icon": "✅", "title": f"습도 {rh}% — 적정 구간",
                      "body": "ASABE 기준 적정 범위(50~90%, 최적 50~70%)입니다. 현재 환경을 유지하세요.",
                      "level": "ok"})

    # ── VPD 해석 (보조 참고 지표 — 02_vpd.md 논문 참고범위 기준으로 통일)
    if vpd < 0.3:
        cards.append({"icon": "💦", "title": f"VPD {vpd} kPa — 과습 참고치 이하",
                      "body": "증산이 억제될 수 있는 참고 구간입니다(0.3 kPa 미만). 위 습도 판단을 우선 기준으로 삼으세요.",
                      "level": "warn"})
    elif vpd <= 1.2:
        cards.append({"icon": "✅", "title": f"VPD {vpd} kPa — 적정 참고범위",
                      "body": "증산·광합성에 무난한 참고 범위입니다(0.5–1.2 kPa).",
                      "level": "ok"})
    elif vpd <= 2.0:
        cards.append({"icon": "🔥", "title": f"VPD {vpd} kPa — 건조장해 참고치",
                      "body": "1.5 kPa 초과는 기공이 닫히기 시작할 수 있는 참고 구간입니다. 차광·관수를 검토하세요.",
                      "level": "warn"})
    else:
        cards.append({"icon": "🚨", "title": f"VPD {vpd} kPa — 극건조 참고치",
                      "body": "2.0 kPa 초과는 심각한 수분 스트레스 참고 구간입니다. 즉각 차광·관수·환기가 필요합니다.",
                      "level": "danger"})

    # ── 온도 해석
    if temp >= 32:
        cards.append({"icon": "🌡️", "title": f"온도 {temp}℃ — 고온 경보",
                      "body": f"32℃ 이상은 착과·화분 불활성화 위험입니다. 즉시 환기하고 차광 스크린을 활용하세요.",
                      "level": "danger"})
    elif temp >= 28:
        cards.append({"icon": "🌡️", "title": f"온도 {temp}℃ — 약간 고온",
                      "body": "토마토 적정 주간 온도(22–26℃)를 초과합니다. 환기 개도를 높여 온도를 낮추세요.",
                      "level": "warn"})
    elif temp < 12:
        cards.append({"icon": "❄️", "title": f"온도 {temp}℃ — 저온 경보",
                      "body": "12℃ 미만은 저온 장해·냉해 위험 구간입니다. 난방기를 즉시 점검하세요.",
                      "level": "danger"})

    # ── CO₂ 해석
    if co2 < 400:
        cards.append({"icon": "🍃", "title": f"CO₂ {co2} ppm — 광합성 한계 접근",
                      "body": "대기 수준(400 ppm) 이하입니다. 일사가 있는 낮 시간대에는 CO₂ 시비를 고려하세요.",
                      "level": "warn"})
    elif co2 > 1200 and solar > 100:
        cards.append({"icon": "🍃", "title": f"CO₂ {co2} ppm — 환기 검토 필요",
                      "body": "CO₂가 높고 일사도 있습니다. 과도한 CO₂는 기공을 닫아 오히려 광합성을 억제할 수 있습니다. 환기로 1000 ppm 이하를 목표로 조절하세요.",
                      "level": "warn"})

    # ── 일사 해석 (낮 시간 기준)
    now_h = datetime.now().hour
    if 8 <= now_h <= 16:
        if solar < 100:
            cards.append({"icon": "☁️", "title": f"일사 {solar} W/m² — 저일조",
                          "body": "낮 시간대이지만 일사가 매우 낮습니다. CO₂ 시비 효과가 낮고 VPD 관리가 어려울 수 있습니다. 보광 여부를 검토하세요.",
                          "level": "warn"})
        elif solar > 800:
            cards.append({"icon": "☀️", "title": f"일사 {solar} W/m² — 강광",
                          "body": "강한 일사로 잎 온도가 기온보다 높아질 수 있습니다. VPD가 높아져 기공이 닫히기 전에 차광 스크린으로 증산을 유지하세요.",
                          "level": "warn"})

    return cards


def _metric_box(label: str, value: str, sub: str = "") -> str:
    """둥근 테두리 박스 HTML 메트릭 카드"""
    sub_html = f'<div style="font-size:0.75em;color:#868e96;margin-top:2px">{sub}</div>' if sub else ""
    return (
        f'<div style="border:1.5px solid #dee2e6;border-radius:12px;padding:10px 14px;'
        f'background:#f8f9fa;margin-bottom:8px">'
        f'<div style="font-size:0.78em;color:#868e96;margin-bottom:4px">{label}</div>'
        f'<div style="font-size:1.25em;font-weight:700;color:#212529">{value}</div>'
        f'{sub_html}</div>'
    )

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CHAT_EXAMPLES = [
    "오후에 일사가 떨어지면 환기 어떻게 해야 해?",
    "흐린 날 난방 기준이 뭐야?",
    "지금 VPD가 높은데 어떻게 내려?",
    "CO2 시비 언제 멈춰야 해?",
    "야간 온도 설정 어떻게 하면 돼?",
    "고온 경보 나면 제일 먼저 뭐 해야 해?",
    "외기가 더 뜨거울 때 환기 열면 안 되는 거야?",
    "결로가 생기면 어떻게 대응해?",
    "토마토 착과기에 온도 어떻게 맞춰?",
]

from rag.pipeline import build_vectorstore, calc_vpd, diagnose, load_decisions, search
from tools.kma_client import fetch_aws, ventilation_hint, DEFAULT_LAT, DEFAULT_LON, latlon_to_grid
from tools.kma_api import get_short_forecast


@st.cache_data(ttl=1800, show_spinner=False)
def _load_forecast() -> list[dict]:
    """설정 위치의 KMA 단기예보(3일치, 시간별) 조회 — 30분 캐시."""
    nx, ny = latlon_to_grid(DEFAULT_LAT, DEFAULT_LON)
    return get_short_forecast(nx, ny)
from tools.sensor_client import fetch_sensors, generate_mock, get_recent_series
from tools.growth_data import (query as growth_query, latest as growth_latest, add_record,
                               ensure_sample_csv, is_sample_data, assess_growth)
from agent.agent import ask as mcp_ask, DEFAULT_MODEL as MCP_DEFAULT_MODEL


def _is_timeout_error(e: BaseException) -> bool:
    """asyncio TaskGroup은 ReadTimeout을 ExceptionGroup으로 감싸 str(e)에 노출하지 않으므로 재귀적으로 확인."""
    if "timed out" in str(e).lower() or "timeout" in str(e).lower():
        return True
    return any(_is_timeout_error(sub) for sub in getattr(e, "exceptions", ()))
from tools.at_client import (fetch_price_range, fetch_price_range_by_markets,
                              fetch_all_grades, fetch_grades_by_markets, fetch_auction_ledger,
                              dummy_price, GRADE_KINDCODES as _AT_GRADE_CODES)
from tools.kamis_client import fetch_shipment_price_history, fetch_shipment_price_history_static
from tools.naver_news import fetch_price_factor_articles
from tools.nutrient_log import (add_entry as nutrient_add, flat_entries as nutrient_flat)

_BRIEFING_SYSTEM = (
    "당신은 농업 전문 데이터 분석가이자 AI 농업 컨설턴트입니다. "
    "아래 제공된 뉴스 기사 목록만 근거로 토마토 가격 변동 요인을 분석해 브리핑하십시오.\n"
    "- 단순 가격 전망이 아니라 자재비, 인건비, 기상 상황 등 외부 요인을 중심으로 서술하십시오.\n"
    "- '예상됩니다' 대신 '현재 [변수]로 인해 [현상]이 지속될 가능성이 제기되고 있습니다'와 같은 "
    "중립적·분석적 어조를 사용하십시오.\n"
    "- 제공된 기사 목록에 없는 내용은 지어내지 마십시오.\n"
    "- 답변 마지막에 반드시 참고한 기사의 출처(기사 제목/매체/날짜)를 목록으로 명시하십시오."
)

_PLAN_SYSTEM = (
    "당신은 토마토 온실 관리 전문가입니다. 농가의 영농일지에 기록된 다가오는 계획과 "
    "참고자료를 바탕으로, 오늘부터 그 계획일까지 미리 준비하거나 점검해야 할 일을 "
    "간결하게 안내하십시오.\n"
    "- 남은 일수를 고려해 지금 당장 할 일과 계획일 직전에 할 일을 구분하십시오.\n"
    "- 참고자료에서 확인되지 않는 내용은 일반 상식 수준으로만 제안하고 그렇게 명시하십시오.\n"
    "- 3~5개 항목의 짧은 체크리스트 형태로 답하십시오."
)

_NUTRIENT_SYSTEM = (
    "당신은 작물영양학 전문가입니다. 농가가 입력한 양액 조성 수치(N/P/K/Ca/Mg/EC/pH)와 "
    "관찰된 증상, 과거 조성 이력, 참고자료를 바탕으로 다음을 분석하십시오.\n"
    "1. 증상과 가장 관련 있어 보이는 성분(부족 또는 과잉)\n"
    "2. 그렇게 판단한 근거 (수치·증상·참고자료 인용)\n"
    "3. 조성 비율 조정 제안 (구체적 수치 변화 방향)\n"
    "참고자료에서 확인되지 않는 내용은 추정임을 명시하십시오. "
    "이 분석은 참고용이며 정확한 처방은 전문가 확인이 필요함을 마지막에 안내하십시오."
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
    "전문가의 확인을 받으십시오."
)


@st.cache_data(ttl=300, show_spinner=False)
def _load_ledger() -> dict:
    """실시간 경매 원장 로더 (5분 캐시)."""
    return fetch_auction_ledger()
from advisor import (generate_advice, save_response as save_advice_response,
                     load_log as load_advice_log,
                     rag_alert_check, is_rag_check_due)
from tools.notifier import is_in_cooldown, send_alert_email, cooldown_remaining_min
from tools.diary_data import (load_all as diary_load, add_entry as diary_add,
                              delete_entry as diary_delete, day_entries as diary_day,
                              day_tags as diary_day_tags, to_csv as diary_to_csv,
                              save_attachment as diary_save_attachment, ATTACH_DIR as DIARY_ATTACH_DIR)
from tools.goal_manager import (load as goal_load,
                                set_harvest_date as goal_set_harvest, dday as goal_dday,
                                harvest_stage as goal_stage, HARVEST_STAGE_SOURCE,
                                GOAL_HINTS)
from tools.pest_forecast import assess_risk, PEST_RISK_RULES
from tools.ncpms_client import search_diseases as ncpms_search, disease_detail as ncpms_detail, has_key as ncpms_has_key


@st.cache_data(ttl=86400, show_spinner=False)
def _ncpms_list(crop: str = "토마토") -> list[dict]:
    """NCPMS 병해충 목록 (하루 캐시)."""
    return ncpms_search(crop, rows=100)


@st.cache_data(ttl=86400, show_spinner=False)
def _ncpms_detail(sick_key: str) -> dict:
    """NCPMS 병 상세 (하루 캐시)."""
    return ncpms_detail(sick_key)


@st.cache_data(ttl=86400, show_spinner=False)
def _pest_thumb_map() -> dict[str, str]:
    """병해충 이름 → NCPMS 썸네일 URL (병해 예찰 카드 hover 이미지용).

    NCPMS 공식 명칭은 '병'·'성' 등 접미사 표기가 달라 그대로는 잘 일치하지 않는다
    (예: '잎곰팡이' vs '잎곰팡이병', '세균성점무늬병' vs '세균점무늬병').
    접미사를 정규화한 뒤 부분일치로 매칭한다.

    예외를 여기서 삼키면 st.cache_data가 빈 dict를 24시간 캐시해버려 일시적인
    NCPMS 네트워크 오류가 이후 재시도를 막게 되므로, 호출부에서 처리하도록 그대로 전파한다.
    """
    items = _ncpms_list("토마토")

    def _norm(s: str) -> str:
        return s.replace("병", "").replace("성", "")

    thumbs = [(d["name"], d["thumb"]) for d in items if d.get("name") and d.get("thumb")]
    result: dict[str, str] = {}
    for rule_name in PEST_RISK_RULES:
        rn = _norm(rule_name)
        if len(rn) < 2:
            continue
        for ncpms_name, thumb in thumbs:
            nn = _norm(ncpms_name)
            if len(nn) >= 2 and (rn in nn or nn in rn):
                result[rule_name] = thumb
                break
    return result
from tools.pesticide_db import (DISEASE_MAP, detect_diseases, get_autocomplete,
                                AUTOCOMPLETE_TERMS, TAG_COLORS, detect_all_tags,
                                SPRAY_ACTIONS, PEST_NAMES)

# 영농일지 인라인 자동완성 에디터 (ghost-text + Tab 수락)
_DIARY_EDITOR = components.declare_component(
    "diary_editor",
    path=str(Path(__file__).parent / "diary_editor"),
)

st.set_page_config(page_title="온실 진단 도우미", layout="wide")
st.markdown("""<style>
.pest-hover { position:relative; cursor:help; border-bottom:1px dotted #868e96; }
.pest-hover .pest-tip-img {
    display:none; position:absolute; z-index:9999; top:22px; left:0;
    width:170px; max-width:45vw; border:2px solid #fff; border-radius:6px;
    box-shadow:0 2px 12px rgba(0,0,0,.28); background:#fff;
}
.pest-hover:hover .pest-tip-img { display:block; }
</style>""", unsafe_allow_html=True)
_title_col, _time_col = st.columns([3, 1])
_title_col.title("토마토 온실 진단 도우미")
_title_col.caption("RAG 기반 실시간 센서 진단 · 현재 상태 반응형")
_time_col.markdown(
    f"<div style='text-align:right;padding-top:16px;font-size:1.1em;font-weight:600'>"
    f"{datetime.now().strftime('%Y-%m-%d')}</div>"
    f"<div style='text-align:right;font-size:1.6em;font-weight:700;color:#1971c2'>"
    f"{datetime.now().strftime('%H:%M:%S')}</div>",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Vectorstore
# ---------------------------------------------------------------------------

@st.cache_resource(show_spinner="BGE-M3 임베딩 모델 로딩 중...")
def _get_col():
    return build_vectorstore()

col_db = _get_col()

# ---------------------------------------------------------------------------
# Session state init
# ---------------------------------------------------------------------------

_defaults = {
    "sensor_data":        fetch_sensors(),
    "outdoor_data":       None,
    "outdoor_error":      None,
    "aws_data":           None,
    "aws_error":          None,
    "kamis_data":         None,
    "kamis_error":        None,
    "kamis_grades":       None,
    "kamis_by_market":    [],
    "last_result":        None,
    "last_error":         None,
    "last_auto_run":      0.0,
    "chat_history":       [],
    "chat_example_queue": [],
    "current_advice":     None,
    "advice_error":       None,
    "email_status":       None,
    "email_alerts":       [],
}
for k, v in _defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# Auto-fetch AWS
if st.session_state.aws_data is None and st.session_state.aws_error is None:
    try:
        st.session_state.aws_data = fetch_aws()
    except Exception as e:
        st.session_state.aws_error = str(e)

if st.session_state.aws_data and st.session_state.outdoor_data is None:
    aw = st.session_state.aws_data
    st.session_state.outdoor_data = {
        "obs_time":      aw["obs_time"],
        "outdoor_temp":  aw["temp"],
        "outdoor_rh":    aw["rh"],
        "outdoor_vpd":   aw["vpd"],
        "wind_speed":    aw["wind_speed"],
        "wind_dir_kor":  aw["wind_dir_kor"],
        "wind_dir_deg":  aw.get("wind_dir_deg"),
        "precipitation": aw.get("rainfall_60m", 0),
        "pty":           1 if aw.get("rainfall_60m", 0) > 0 else 0,
        "pty_label":     "비" if aw.get("rainfall_60m", 0) > 0 else "",
        "wf_kor":        f"AWS {aw['stn']}지점",
        "source":        "KMA AWS",
    }

# Auto-fetch aT 공판장 경락가격
if st.session_state.kamis_data is None and st.session_state.kamis_error is None:
    with st.spinner("공판장 경락가격 조회 중..."):
        try:
            kgd = fetch_all_grades()
            st.session_state.kamis_grades = kgd
            mid = kgd.get("중", {})
            p   = mid.get("price")
            st.session_state.kamis_data = {
                "date":       kgd["date"],
                "item":       "토마토",
                "market":     kgd["market"],
                "grade":      "중",
                "price":      p,
                "price_str":  f"{p:,}원" if p else "데이터 없음",
                "dod_change": mid.get("dod_change"),
                "source":     "aT 공판장 경락가격",
            }
            try:
                st.session_state.kamis_by_market = fetch_grades_by_markets()
            except Exception:
                st.session_state.kamis_by_market = []
        except Exception as e:
            st.session_state.kamis_data  = dummy_price()
            st.session_state.kamis_error = str(e)

# ---------------------------------------------------------------------------
# RAG alert check + advice auto-populate (once per session / per cooldown)
# ---------------------------------------------------------------------------

if st.session_state.email_status is None and is_rag_check_due():
    import os as _os
    _has_pw = bool(_os.getenv("EMAIL_APP_PASSWORD", ""))
    with st.spinner("PDF 문서 기반 이상 상황 점검 중..."):
        try:
            _rag = rag_alert_check(
                st.session_state.sensor_data,
                st.session_state.outdoor_data,
                col_db,
            )
            _sit  = _rag["situation"]
            _rec  = _rag["recommendation"]
            if st.session_state.current_advice is None:
                import datetime as _dt
                st.session_state.current_advice = {
                    "situation":      _sit  if _sit  not in ("정상", "") else "현재 온실 상태가 정상 범위입니다.",
                    "recommendation": _rec  if _rec  not in ("정상", "") else "현재 온실 상태는 정상 범위입니다.",
                    "generated_at":   _dt.datetime.now().isoformat(timespec="seconds"),
                    "sensor":         st.session_state.sensor_data,
                    "outdoor":        st.session_state.outdoor_data,
                    "auto": True,
                }
            if _rag["alert"]:
                _label = f"AI 감지: {_sit}"
                st.session_state.email_alerts = [_label]
                if is_in_cooldown():
                    st.session_state.email_status = "cooldown"
                elif not _has_pw:
                    st.session_state.email_status = "no_key"
                else:
                    try:
                        send_alert_email([_label], st.session_state.sensor_data,
                                         situation=_sit, recommendation=_rec)
                        st.session_state.email_status = "sent"
                    except Exception as _e:
                        st.session_state.email_status = f"error:{_e}"
            else:
                st.session_state.email_status = "ok"
        except Exception as _e:
            st.session_state.email_status = f"error:{_e}"
elif st.session_state.email_status is None:
    st.session_state.email_status = "ok"

# ---------------------------------------------------------------------------
# 7 tabs
# ---------------------------------------------------------------------------

tab_env, tab_growth, tab_weather, tab_price, tab_control, tab_ai, tab_note = st.tabs([
    "환경 데이터", "생육 데이터", "기상 데이터", "가격 정보", "온실 제어", "AI 상담", "메모·일지",
])

# 선택한 탭을 rerun(자동 진단·저장 등) 후에도 유지 — 활성 탭 인덱스를 URL(?t=)에
# 저장하고, 리렌더로 첫 탭으로 돌아가면 저장된 탭을 다시 활성화한다. (콘텐츠 블록은 불변)
components.html(
    """
<script>
(function(){
  const KEY = 't';
  const doc = window.parent.document;
  function sync(){
    const tabs = doc.querySelectorAll('button[role="tab"]');
    if(!tabs.length) return;                       // 진단 중 탭 미표시 → 대기
    const url = new URL(window.parent.location);
    let saved = parseInt(url.searchParams.get(KEY));
    if(isNaN(saved) || saved < 0 || saved >= tabs.length) saved = 0;
    tabs.forEach((t, i) => {
      if(!t.__persistBound){                        // 클릭 시 선택 인덱스 저장
        t.__persistBound = true;
        t.addEventListener('click', () => {
          const u = new URL(window.parent.location);
          u.searchParams.set(KEY, i);
          window.parent.history.replaceState({}, '', u);
        });
      }
    });
    // 리렌더로 다른 탭이 활성화됐으면 저장된 탭을 복원 (idempotent)
    if(tabs[saved] && tabs[saved].getAttribute('aria-selected') !== 'true'){
      tabs[saved].click();
    }
  }
  setInterval(sync, 400);
  sync();
})();
</script>
""",
    height=0,
)

# ---------------------------------------------------------------------------
# 센서 입력 (구 사이드바 → 환경 데이터 탭 상단)
# ---------------------------------------------------------------------------
with tab_env:
    st.subheader("센서 입력")
    if st.button("지금 동기화", key="sensor_sync_btn"):
        with st.spinner("센서 데이터 동기화 중..."):
            st.session_state.sensor_data = fetch_sensors()

    sd  = st.session_state.sensor_data
    src = sd.get("source", "")
    if src == "csv":
        st.success("📊 CSV 실측 · 온도·습도·CO₂·외부일사", icon="🟢")
    elif src == "simulation":
        st.warning("⚠️ 시뮬레이션 (CSV 로드 실패)", icon="🟡")
    else:
        st.caption(f"✏️ 수동  ·  {sd.get('timestamp','')[:19]}")
    if sd.get("solar_is_mock"):
        st.caption("☀️ 일사량: 목업값 (원본 데이터 없음)")
    _sol_mock = sd.get("solar_is_mock")
    c1, c2 = st.columns(2)
    c1.metric("온도",      f"{sd['temp']}℃")
    c2.metric("습도",      f"{sd['rh']}%")
    c1.metric("CO₂(ppm)", f"{int(sd['co2'])}")
    c2.metric(f"외부일사(W/m²){' ⚠️' if _sol_mock else ''}", f"{sd.get('solar', 0)}")
    if sd.get("cum_solar") is not None:
        st.caption(f"외부 누적 일사({'목업' if _sol_mock else '실측'}): {int(sd['cum_solar'])} Wh/m²")
    st.divider()

sd      = st.session_state.sensor_data
temp    = float(sd["temp"])
rh      = float(sd["rh"])
co2     = float(sd["co2"])
solar   = float(sd.get("solar", 0))
vpd_now = calc_vpd(temp, rh)


# ---------------------------------------------------------------------------
# 자동 진단 · Ollama 모델 · 이메일 경보 (구 사이드바 → 온실 제어 탭 상단)
# ---------------------------------------------------------------------------
with tab_control:
    st.subheader("자동 진단")
    st.caption("설정 간격마다 센서 동기화 → RAG 문서 기반 LLM 진단을 자동 실행합니다.")
    auto_mode    = st.toggle("자동 진단 켜기", value=False)
    interval_min = st.select_slider(
        "실행 간격",
        options=[10, 15, 30, 60],
        value=30,
        format_func=lambda x: f"{x}분",
        disabled=not auto_mode,
    )
    interval_sec = interval_min * 60

    model   = "gemma4:12b"
    run_btn = st.button("진단하기", type="primary", use_container_width=True)

    st.divider()

    st.subheader("이메일 경보")
    _es = st.session_state.email_status
    _ea = st.session_state.email_alerts
    if _es == "sent":
        st.success("경보 발송됨", icon="📧")
        for a in _ea:
            st.caption(f"• {a}")
        st.caption(f"쿨다운 {cooldown_remaining_min()}분 남음")
    elif _es == "cooldown":
        st.info(f"쿨다운 중 ({cooldown_remaining_min()}분 남음)", icon="⏳")
    elif _es == "no_key":
        st.warning("EMAIL_APP_PASSWORD 미설정", icon="🔑")
    elif _es and _es.startswith("error:"):
        st.error(_es[6:], icon="❌")
    else:
        st.caption("정상 범위 — 경보 없음")

    if st.button("지금 테스트 발송", key="test_email_btn"):
        try:
            send_alert_email(
                ["테스트 경보"], st.session_state.sensor_data,
                situation="이메일 연동 테스트",
                recommendation="이 메시지가 수신되면 설정 완료입니다.",
            )
            st.session_state.email_status = "sent"
            st.session_state.email_alerts = ["테스트 경보"]
            st.rerun()
        except Exception as e:
            st.error(str(e))
    st.divider()

# ---------------------------------------------------------------------------
# Diagnosis helpers
# ---------------------------------------------------------------------------

def _run_diagnosis():
    st.session_state.last_result = None
    st.session_state.last_error  = None
    try:
        result = diagnose(
            temp=temp, rh=rh, co2=co2, solar=solar,
            col=col_db, model=model,
            outdoor=st.session_state.outdoor_data,
        )
        st.session_state.last_result   = result
        st.session_state.last_auto_run = time.time()
    except Exception as e:
        st.session_state.last_error = str(e)

if run_btn:
    with st.spinner("LLM 진단 중..."):
        _run_diagnosis()

# 자동 진단: 대기 중 폴링은 fragment(부분 실행)로 처리해 전체 페이지가 매초
# rerun되지 않게 하고(탭 리셋·깜빡임 방지), 인터벌 도달 시에만 전체 rerun한다.
if auto_mode and st.session_state.pop("auto_diagnose_now", False):
    with st.spinner("[자동] 센서 동기화..."):
        st.session_state.sensor_data = fetch_sensors()
        sd    = st.session_state.sensor_data
        temp  = float(sd["temp"])
        rh    = float(sd["rh"])
        co2   = float(sd["co2"])
        solar = float(sd.get("solar", 0))
    try:
        st.session_state.aws_data = fetch_aws()
        aw = st.session_state.aws_data
        st.session_state.outdoor_data = {
            "obs_time": aw["obs_time"], "outdoor_temp": aw["temp"],
            "outdoor_rh": aw["rh"], "outdoor_vpd": aw["vpd"],
            "wind_speed": aw["wind_speed"], "wind_dir_kor": aw["wind_dir_kor"],
            "wind_dir_deg": aw.get("wind_dir_deg"),
            "precipitation": aw.get("rainfall_60m", 0),
            "pty": 1 if aw.get("rainfall_60m", 0) > 0 else 0,
            "pty_label": "비" if aw.get("rainfall_60m", 0) > 0 else "",
            "wf_kor": f"AWS {aw['stn']}지점", "source": "KMA AWS",
        }
    except Exception as e:
        st.session_state.aws_error = str(e)
    with st.spinner("[자동] LLM 진단 중..."):
        _run_diagnosis()
    st.session_state.last_auto_run = time.time()  # 실패해도 인터벌 유지(재시도 폭주 방지)

if auto_mode:
    @st.fragment(run_every="5s")
    def _auto_poll():
        # 부분 실행(전체 페이지 rerun 아님). 인터벌 도달 시에만 전체 rerun을 건다.
        if time.time() - st.session_state.last_auto_run >= interval_sec:
            st.session_state.auto_diagnose_now = True
            st.rerun(scope="app")
    _auto_poll()

# ---------------------------------------------------------------------------
# 공통: 주간 온도 분석 (탭 전체에서 공유)
# ---------------------------------------------------------------------------

def _compute_temp_analysis(decisions: list) -> dict:
    """오늘 주간(6~18시) 온도 평균으로 야간 권장 온도를 계산한다."""
    today = date.today().isoformat()
    day_t, night_t = [], []
    for r in decisions:
        if not r.get("timestamp", "").startswith(today):
            continue
        try:
            hour = int(r["timestamp"][11:13])
            t    = float(r.get("sensor_input", {}).get("temp") or 0)
            if t > 0:
                (day_t if 6 <= hour < 18 else night_t).append(t)
        except Exception:
            pass
    if day_t:
        day_avg = round(sum(day_t) / len(day_t), 1)
        return {
            "day_avg":       day_avg,
            "day_max":       round(max(day_t), 1),
            "day_min":       round(min(day_t), 1),
            "night_avg":     round(sum(night_t) / len(night_t), 1) if night_t else None,
            "rec_night":     round(max(16.0, min(22.0, day_avg - 5.0)), 1),
            "has_day_data":  True,
        }
    return {"has_day_data": False, "rec_night": round(max(16.0, min(22.0, temp - 5.0)), 1)}

_temp_analysis = _compute_temp_analysis(load_decisions())

# ===========================================================================
# TAB 1: 환경 데이터  (Desktop1 — top metric cards → middle charts → bottom chart)
# ===========================================================================
with tab_env:
    _src = sd.get("source", "")
    if _src == "csv":
        _frozen_note = f" (최신 실측 고정 · {sd.get('data_timestamp','')})" if sd.get("is_frozen") else ""
        st.success(
            f"📊 온실 실측 (온도·습도·CO₂·외부일사){_frozen_note}  ·  {sd.get('timestamp','')[:19]}",
            icon="🟢",
        )
        if sd.get("solar_is_mock"):
            st.warning("☀️ 일사량은 **목업값** (CSV 로드 실패로 시뮬레이션)", icon="⚠️")
    elif _src == "simulation":
        st.error("⚠️ 가짜값 — 시뮬레이션 중  (일사량 포함 전체 목업)", icon="🔴")
    else:
        st.caption(f"✏️ 수동  ·  {sd.get('timestamp','')[:19]}")

    # ── 상단: 6개 메트릭 카드 ────────────────────────────────────
    ah_now = calc_abs_humidity(temp, rh)
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("🌡 온도",      f"{temp}℃")
    m2.metric("💧 습도",      f"{rh}%")
    m3.metric("💦 절대습도",  f"{ah_now} g/m³")
    m4.metric("🍃 CO₂",      f"{int(co2)} ppm")
    m5.metric(f"☀️ 외부 일사{' ⚠️목업' if sd.get('solar_is_mock') else ''}", f"{solar} W/m²")
    m6.metric("💨 VPD",      f"{vpd_now} kPa")

    # ── 현재 환경 위험도 (환경 해석 + 병해충 예찰 통합, 초록/노랑/빨강 3단계) ──
    _interps = _env_interpret(temp, rh, vpd_now, int(co2), solar, outdoor=st.session_state.outdoor_data)
    _pest_risks = assess_risk(temp, rh)
    _pest_hi = [r for r in _pest_risks if r["label"] != "낮음"]

    # 서로 다른 두 카드 체계를 {icon, title, body, sev(0=안전,1=주의,2=위험)}로 통일
    _SEV = {"ok": 0, "warn": 1, "danger": 2, "safe": 0, "caution": 1, "risk": 2,
            "낮음": 0, "주의": 1, "높음": 2}
    _pest_label_map = {"높음": "risk", "주의": "caution", "낮음": "safe"}
    try:
        _pest_thumbs = _pest_thumb_map() if ncpms_has_key() else {}
    except Exception:
        _pest_thumbs = {}

    _all_cards = [
        {"icon": c["icon"], "title": c["title"], "body": c["body"], "sev": _SEV[c["level"]], "drugs": None, "thumb": ""}
        for c in _interps
    ] + [
        {"icon": "🦠", "title": r["name"],
         "body": f'{r["reason"]}<br><span style="color:#495057">{r["note"]}</span>',
         "sev": _SEV[r["label"]],
         "drugs": DISEASE_MAP.get(r["name"], {}).get("pesticides", [])[:3],
         "thumb": _pest_thumbs.get(r["name"], "")}
        for r in _pest_hi
    ]
    _all_cards.sort(key=lambda c: -c["sev"])
    _urgent = [c for c in _all_cards if c["sev"] >= 1]

    _overall_sev = max((c["sev"] for c in _all_cards), default=0)
    _sev_badge = {0: "🟢 안전", 1: "🟡 주의", 2: "🔴 위험"}[_overall_sev]
    _sev_color = {2: "#c92a2a", 1: "#d9a400"}
    _sev_bg    = {2: "#ffe3e3", 1: "#fff9db"}

    with st.expander(f"현재 환경 위험도 — {_sev_badge}", expanded=False):
        if not _urgent:
            st.success("✅ 현재 주의가 필요한 환경·병해충 조건이 없습니다.", icon="✅")
        else:
            _top, _rest = _urgent[:2], _urgent[2:]
            for _card in _top:
                _tc, _bg = _sev_color[_card["sev"]], _sev_bg[_card["sev"]]
                _name_html = (
                    f'<span class="pest-hover">{_card["title"]}<img class="pest-tip-img" src="{_card["thumb"]}"></span>'
                    if _card["thumb"] else _card["title"]
                )
                _drug_html = (
                    f'<div style="font-size:0.85em;color:#1971c2;margin-top:3px">💊 {" / ".join(_card["drugs"])}</div>'
                    if _card["drugs"] else ""
                )
                st.markdown(
                    f'<div style="background:{_bg};border-left:4px solid {_tc};border-radius:8px;'
                    f'padding:10px 13px;margin-bottom:8px">'
                    f'<div style="font-weight:700;color:{_tc};margin-bottom:4px">'
                    f'{_card["icon"]} {_name_html}</div>'
                    f'<div style="font-size:0.88em;color:#212529;line-height:1.5">{_card["body"]}</div>'
                    f'{_drug_html}'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            if _rest:
                with st.expander(f"더 보기 ({len(_rest)}건)"):
                    for _card in _rest:
                        _tc = _sev_color[_card["sev"]]
                        st.markdown(f"**{_card['icon']} {_card['title']}**", unsafe_allow_html=True)
                        st.caption(_card["body"].replace("<br>", " · ").replace('<span style="color:#495057">', "").replace("</span>", ""))
                        if _card["drugs"]:
                            st.caption("💊 " + " / ".join(_card["drugs"]))

        with st.expander("전체 병해충 위험도 표"):
            st.dataframe(pd.DataFrame([
                {"병해충": r["name"], "구분": r["kind"], "위험도": r["label"], "발생조건": r["note"]}
                for r in _pest_risks
            ]), use_container_width=True, hide_index=True)

        # 활성 목표 힌트
        _active_goal_hints = [
            GOAL_HINTS[g] for g in goal_load().get("goals", [])
            if GOAL_HINTS.get(g)
        ]
        if _active_goal_hints:
            st.markdown("---")
            st.markdown("**🎯 현재 목표 기반 관리 팁**")
            for _hint in _active_goal_hints:
                st.info(_hint, icon="💡")

        if _pest_hi:
            st.caption(
                "📝 방제 기록은 메모·일지 → 영농일지에서 남겨주세요. "
                "예) \"A구역 잿빛곰팡이 방제 — 보스칼리드 살포\"처럼 적으면 자동 태그되고, "
                "병해충 도감은 AI 상담 탭에서 조회할 수 있습니다."
            )

    # ── 최근 환경 패턴 Altair 차트 (실측 시계열) ──────────
    _hr_col1, _hr_col2 = st.columns([3, 1])
    with _hr_col1:
        st.subheader("📊 온실 환경 패턴 (실측)")
    with _hr_col2:
        _chart_hours = st.radio("기간", [6, 18, 24], index=2, horizontal=True,
                                 format_func=lambda h: f"{h}시간", key="env_chart_hours")
    _series = get_recent_series(hours=_chart_hours)
    if _series:
        _df_env = pd.DataFrame([
            {
                "시각": pd.Timestamp(r["timestamp"]),
                "내부온도(℃)":  r["temp"],
                "내부습도(%)":  r["rh"],
                "CO₂(ppm)":   int(r["co2"]),
                "일사량(W/m²)": r["solar"],
                "VPD(kPa)":   calc_vpd(r["temp"], r["rh"]),
            }
            for r in _series
        ])

        _x = alt.X("시각:T", title="시각", axis=alt.Axis(format="%m/%d %H:%M"))
        _base = alt.Chart(_df_env).encode(x=_x)

        # ① 온도 + 습도 듀얼 Y축
        _tl = _base.mark_line(color="#e03131", strokeWidth=2).encode(
            y=alt.Y("내부온도(℃):Q", title="온도 (℃)"),
            tooltip=["시각:T", "내부온도(℃):Q"])
        _rl = _base.mark_line(color="#1971c2", strokeWidth=2, strokeDash=[5, 3]).encode(
            y=alt.Y("내부습도(%):Q", title="습도 (%)"),
            tooltip=["시각:T", "내부습도(%):Q"])
        _chart_tr = (
            alt.layer(_tl, _rl)
            .resolve_scale(y="independent")
            .properties(title="🌡 온도(빨강) & 💧 습도(파랑·점선)", height=230)
        )

        # ② CO2
        _cl = _base.mark_line(color="#2f9e44", strokeWidth=2).encode(
            y=alt.Y("CO₂(ppm):Q", title="CO₂ (ppm)"),
            tooltip=["시각:T", "CO₂(ppm):Q"])
        _chart_co2 = _cl.properties(title="🍃 CO₂ — 주간 광합성 소비 · 야간 축적", height=230)

        # ③ 외부 일사량 area (실측)
        _sa = _base.mark_area(color="#f59f00", opacity=0.35).encode(
            y=alt.Y("일사량(W/m²):Q", title="일사량 (W/m²)"))
        _sl = _base.mark_line(color="#e67700", strokeWidth=2).encode(y="일사량(W/m²):Q")
        _chart_sol = (
            alt.layer(_sa, _sl)
            .properties(title="☀️ 외부 일사(실측)", height=230)
        )

        # ④ VPD + 적정범위 색띠
        _vpd_band = alt.Chart(pd.DataFrame({"y1": [0.3], "y2": [0.7]})).mark_rect(
            color="#d3f9d8", opacity=0.5).encode(y="y1:Q", y2="y2:Q")
        _vl = _base.mark_line(color="#862e9c", strokeWidth=2).encode(
            y=alt.Y("VPD(kPa):Q", title="VPD (kPa)"),
            tooltip=["시각:T", "VPD(kPa):Q"])
        _chart_vpd = (
            alt.layer(_vpd_band, _vl)
            .properties(title="💨 VPD — 녹색 구간 = 최적 구간 (0.3–0.7 kPa)", height=230)
        )

        _ec1, _ec2 = st.columns(2)
        with _ec1:
            st.altair_chart(_chart_tr,  use_container_width=True)
            st.altair_chart(_chart_co2, use_container_width=True)
        with _ec2:
            st.altair_chart(_chart_sol, use_container_width=True)
            st.altair_chart(_chart_vpd, use_container_width=True)
        st.caption(f"출처: 온실 실측 센서 로그 · 5분 간격 (최근 {_chart_hours}시간)")

    # ── 오늘 누적 일사량 ──────────────────────────────────
    _cum = sd.get("cum_solar")
    if _cum is not None:
        quality = "좋음 ☀️" if solar >= 400 else ("보통 🌤" if solar >= 150 else "부족 ☁️")
        _cum_tag = "목업" if sd.get("solar_is_mock") else "실측"
        _cum_note = "⚠️ 시뮬레이션 목업값" if sd.get("solar_is_mock") else "CSV 외부 일사량의 시간 합"
        st.info(
            f"☀️ **오늘 외부 누적 일사({_cum_tag}):** {int(_cum)} Wh/m²  |  "
            f"현재 외부 {solar} W/m²  |  광량 **{quality}**  ·  {_cum_note}"
        )

    st.divider()

    # ── 내부 vs 외기 상세 비교 ────────────────────────────────
    st.subheader("현재 환경 상세")
    d1, d2 = st.columns(2)
    with d1:
        st.caption("온실 내부")
        da1, da2 = st.columns(2)
        da1.metric("🌡 온도",    f"{temp} ℃")
        da2.metric("💧 상대습도", f"{rh} %")
        db1, db2 = st.columns(2)
        db1.metric("💦 절대습도", f"{ah_now} g/m³")
        db2.metric("🍃 CO₂",    f"{int(co2)} ppm")
        dc1, dc2 = st.columns(2)
        dc1.metric(f"☀️ 외부 일사({'목업' if sd.get('solar_is_mock') else '실측'})", f"{solar} W/m²")
        dc2.metric("💨 VPD",    f"{vpd_now} kPa")
        dd1, dd2 = st.columns(2)
        dd1.metric("💧 포화수분",  f"{calc_saturation_ah(temp)} g/m³",
                   help="이 온도가 머금을 수 있는 최대 수분(RH 100%)")
        dd2.metric("🟡 수분부족",  f"{calc_moisture_deficit(temp, rh)} g/m³",
                   help="포화수분 − 현재 절대습도. 클수록 건조(증산 활발)")
    with d2:
        od = st.session_state.outdoor_data
        st.caption("🌳 온실 외부 (야외) · KMA AWS")
        if od:
            diff    = temp - od["outdoor_temp"]
            out_ah  = calc_abs_humidity(od["outdoor_temp"], od["outdoor_rh"])
            oa1, oa2 = st.columns(2)
            oa1.metric("🌡 야외 온도",     f"{od['outdoor_temp']} ℃", f"실내외 {diff:+.1f}℃")
            oa2.metric("💧 야외 습도",     f"{od['outdoor_rh']} %")
            ob1, ob2 = st.columns(2)
            ob1.metric("💦 야외 절대습도", f"{out_ah} g/m³")
            ob2.metric("💨 야외 VPD",    f"{od['outdoor_vpd']} kPa")
            oc1, oc2 = st.columns(2)
            oc1.metric("🌬 풍속",        f"{round(od['wind_speed'],1)} m/s",
                       f"{od.get('wind_dir_kor','')} {od.get('wind_dir_deg','—')}°")
            oc2.metric("🟡 야외 수분부족",
                       f"{calc_moisture_deficit(od['outdoor_temp'], od['outdoor_rh'])} g/m³")
        else:
            st.caption("야외 데이터 없음 (.env에 KMA_API_KEY 필요)")

# ===========================================================================
# TAB 2: 생육 데이터
# ===========================================================================
with tab_growth:
    ensure_sample_csv()
    st.subheader("생육 데이터 모니터링")
    if is_sample_data():
        st.error("⚠️ 가짜값 — 자동 생성된 샘플 데이터입니다. 하단 폼으로 실측값을 입력하면 이 경고가 사라집니다.", icon="⚠️")

    g_col1, g_col2 = st.columns([1, 2])
    with g_col1:
        g_zone = st.selectbox("구역", ["전체", "A", "B", "C"], key="g_zone")
        g_weeks = st.slider("최근 N주", 1, 42, 42, key="g_weeks")
        g_days  = g_weeks * 7

    growth_records = growth_query(zone=g_zone, days=g_days)
    latest_records = growth_latest(zone=g_zone)

    with g_col2:
        st.caption("최신 생육 현황")
        if latest_records:
            lcols = st.columns(len(latest_records))
            for i, rec in enumerate(latest_records):
                with lcols[i]:
                    st.metric(f"구역 {rec['zone']} 초장", f"{rec['crop_height_cm']} cm")
                    st.caption(
                        f"엽수 {rec['leaf_count']} · 착과 {rec['fruit_count']} · "
                        f"화방 {rec['truss_count']} · 줄기 {rec['stem_diameter_mm']} mm"
                    )
                    st.caption(f"{rec['date']} | {rec.get('notes','')}")

    # ── 핵심 3지표: 초장·줄기두께(추세) + 화방높이(균형 판정) ────────
    _assess = assess_growth(zone=g_zone)
    if _assess:
        st.caption("핵심 생육 지표 — 초장·줄기두께는 4주 전 대비 추세, 화방높이는 균형 밴드 판정 "
                    "(문헌 근거: 화방높이 10~15cm = 생식/영양생장 균형)")
        _acols = st.columns(len(_assess))
        for i, a in enumerate(_assess):
            with _acols[i]:
                st.markdown(f"**구역 {a['zone']}** ({a['date']})")
                if a["truss_status"]:
                    _t_icon = {"균형": "✅", "생식생장 과다": "⚠️", "영양생장 과다": "⚠️",
                               "측정 재확인 필요": "🔍"}[a["truss_status"]]
                    st.markdown(f"{_t_icon} 화방높이: **{a['truss_status']}**")
                    st.caption(a["truss_desc"])
                else:
                    st.caption(a["truss_desc"])
                st.caption(a["crop_height_cm_trend_desc"])
                st.caption(a["stem_diameter_mm_trend_desc"])
        st.divider()

    if growth_records:
        df_g = pd.DataFrame(growth_records)
        for col_name in ["crop_height_cm", "fruit_count", "leaf_count"]:
            df_g[col_name] = pd.to_numeric(df_g[col_name], errors="coerce")

        # ── 이상치 감지 (구역별 날짜 정렬 후 delta 계산) ────────
        def _flag_outliers(df: pd.DataFrame) -> pd.DataFrame:
            df = df.copy()
            df["date_dt"] = pd.to_datetime(df["date"])
            chunks = []
            for zone, g in df.groupby("zone"):
                g = g.sort_values("date_dt").copy()
                g["_delta_cm"]   = g["crop_height_cm"].diff()
                g["_delta_days"] = g["date_dt"].diff().dt.days.fillna(1)
                g["_cpw"]        = (g["_delta_cm"] / g["_delta_days"] * 7).round(1)
                # 음수 성장(-5cm↓) 또는 주당 50cm 초과 = 이상치
                g["_outlier"] = (g["_delta_cm"] < -5) | (g["_cpw"] > 50)
                chunks.append(g)
            return pd.concat(chunks) if chunks else df

        df_g = _flag_outliers(df_g)
        _outlier_rows = df_g[df_g["_outlier"] == True]

        if not _outlier_rows.empty:
            for _, _or in _outlier_rows.iterrows():
                st.warning(
                    f"⚠️ 이상치 제외 — 구역 {_or['zone']} · {_or['date']} · "
                    f"전 측정 대비 {_or['_delta_cm']:+.1f} cm "
                    f"(주간 환산 {_or['_cpw']:+.1f} cm/주)",
                    icon="⚠️",
                )

        df_g_clean = df_g[df_g["_outlier"] != True].copy()

        # ── 초장 절대값 ─────────────────────────────────────────
        st.subheader("초장 추이")
        df_g_pos = df_g_clean[df_g_clean["crop_height_cm"] >= 0].copy()
        _height_avg = (df_g_pos.groupby(["date", "zone"], as_index=False)["crop_height_cm"]
                       .mean())
        _height_chart = alt.Chart(_height_avg).mark_line(point=True).encode(
            x=alt.X("date:T", title="날짜"),
            y=alt.Y("crop_height_cm:Q", title="초장 (cm)",
                    scale=alt.Scale(domainMin=0, nice=True)),
            color=alt.Color("zone:N", title="구역"),
        ).properties(height=280)
        st.altair_chart(_height_chart, use_container_width=True)

        # ── 주간 성장량: 실측 간격으로 정규화 (cm/주) ────────────
        st.subheader("주간 성장량 (cm/주, 측정 간격 정규화)")
        _cpw_pivot = df_g_pos.pivot_table(
            index="date", columns="zone", values="_cpw", aggfunc="mean"
        ).sort_index().dropna(how="all")
        if not _cpw_pivot.empty:
            st.bar_chart(_cpw_pivot)
            st.caption("측정 간격(일수)으로 나눠 주당 성장량으로 환산 · 이상치 제외됨")
        else:
            st.caption("2회 이상 측정값이 있어야 성장량을 계산할 수 있습니다.")

        gc1, gc2 = st.columns(2)
        with gc1:
            st.subheader("착과수 추이")
            st.bar_chart(df_g.pivot_table(index="date", columns="zone",
                                          values="fruit_count", aggfunc="mean"))
        with gc2:
            st.subheader("엽수 추이")
            st.line_chart(df_g.pivot_table(index="date", columns="zone",
                                           values="leaf_count", aggfunc="mean").clip(lower=0))

        with st.expander("전체 데이터 보기", expanded=True):
            st.dataframe(df_g, use_container_width=True, hide_index=True)
            _xl_buf = io.BytesIO()
            df_g.to_excel(_xl_buf, index=False, engine="openpyxl")
            st.download_button(
                "📥 엑셀로 내보내기",
                data=_xl_buf.getvalue(),
                file_name=f"growth_data_{date.today().isoformat()}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
    else:
        st.info("해당 조건의 생육 데이터가 없습니다.")

    st.divider()
    st.subheader("생육 측정값 입력")
    with st.form("growth_form"):
        fc1, fc2, fc3 = st.columns(3)
        with fc1:
            f_zone   = st.selectbox("구역", ["A", "B", "C"])
            f_height = st.number_input("초장 (cm)", 0.0, 300.0, 50.0, 0.1)
        with fc2:
            f_leaf  = st.number_input("엽수",   0, 100, 15, 1)
            f_fruit = st.number_input("착과수", 0, 200,  5, 1)
        with fc3:
            f_truss      = st.number_input("화방수",        0,  30, 3,   1)
            f_stem       = st.number_input("줄기직경 (mm)", 0.0, 50.0, 9.0, 0.1)
        f_truss_height = st.number_input(
            "화방높이 (cm) — 생장점~첫 화방 거리", 0.0, 60.0, 12.0, 0.5,
            help="10~15cm이 생식/영양생장 균형 구간입니다.",
        )
        f_notes   = st.text_input("비고")
        if st.form_submit_button("기록 저장"):
            add_record(zone=f_zone, crop_height_cm=f_height,
                       leaf_count=int(f_leaf), fruit_count=int(f_fruit),
                       truss_count=int(f_truss), stem_diameter_mm=f_stem,
                       truss_height_cm=f_truss_height, notes=f_notes)
            st.success(f"구역 {f_zone} 생육 데이터 저장 완료")
            st.rerun()

# ===========================================================================
# TAB 3: 기상 데이터
# ===========================================================================
with tab_weather:
    # ── 헤더: 현재 날짜/시각 + 새로고침 ────────────────────────
    wh_left, wh_right = st.columns([3, 1])
    wh_left.markdown(
        f"**현재:** {datetime.now().strftime('%Y년 %m월 %d일 (%a) %H:%M')}  "
        f"·  조회 기준: KMA AWS"
    )
    if wh_right.button("🔄 기상 새로고침", use_container_width=True, key="weather_refresh"):
        try:
            st.session_state.aws_data  = fetch_aws()
            st.session_state.aws_error = None
            aw = st.session_state.aws_data
            st.session_state.outdoor_data = {
                "obs_time":      aw["obs_time"],
                "outdoor_temp":  aw["temp"],
                "outdoor_rh":    aw["rh"],
                "outdoor_vpd":   aw["vpd"],
                "wind_speed":    aw["wind_speed"],
                "wind_dir_kor":  aw["wind_dir_kor"],
                "wind_dir_deg":  aw.get("wind_dir_deg"),
                "precipitation": aw.get("rainfall_60m", 0),
                "pty":           1 if aw.get("rainfall_60m", 0) > 0 else 0,
                "pty_label":     "비" if aw.get("rainfall_60m", 0) > 0 else "",
                "wf_kor":        f"AWS {aw['stn']}지점",
                "source":        "KMA AWS",
            }
            # ── 기상 특보 자동 감지 → Gmail 알림 ─────────────────
            _warnings = []
            if aw.get("rainfall_60m", 0) >= 10:
                _warnings.append(f"강수 특보: 60분 강수량 {aw['rainfall_60m']}mm")
            if aw.get("wind_speed", 0) >= 10:
                _warnings.append(f"강풍 특보: 풍속 {aw['wind_speed']}m/s")
            if aw.get("temp", 0) >= 35:
                _warnings.append(f"고온 특보: 외기 {aw['temp']}℃")
            if aw.get("temp", 0) <= 0:
                _warnings.append(f"저온 특보: 외기 {aw['temp']}℃")
            if _warnings and not is_in_cooldown():
                import os as _os2
                if _os2.getenv("EMAIL_APP_PASSWORD"):
                    try:
                        send_alert_email(
                            _warnings,
                            st.session_state.sensor_data,
                            situation="기상 특보 감지",
                            recommendation="즉각 점검이 필요합니다.",
                        )
                        st.session_state.email_status = "sent"
                        st.session_state.email_alerts = _warnings
                    except Exception:
                        pass
            if _warnings:
                st.session_state["weather_warnings"] = _warnings
            else:
                st.session_state.pop("weather_warnings", None)
        except Exception as e:
            st.session_state.aws_error = str(e)
        st.rerun()

    # 기상 특보 배너
    if st.session_state.get("weather_warnings"):
        for _w in st.session_state["weather_warnings"]:
            st.error(f"⚠️ {_w}", icon="🚨")

    st.divider()

    # ── 외부 현황: 메트릭 카드 ──────────────────────────────────
    st.subheader("외부 현황 (KMA AWS 실시간 관측)")
    aw = st.session_state.aws_data
    if st.session_state.aws_error:
        st.warning(st.session_state.aws_error, icon="⚠️")
        st.caption(".env에 KMA_API_KEY / KMA_AWS_STN 설정 필요")
    elif aw:
        st.caption(f"AWS 지점 {aw['stn']} · 관측 시각: {aw['obs_time']}")

        # 8개 메트릭 카드 (2행 4열)
        wm1, wm2, wm3, wm4 = st.columns(4)
        wm1.metric("🌡 외기온도",  f"{aw['temp']}℃",
                   delta=f"실내외 {temp - aw['temp']:+.1f}℃" if temp else None, delta_color="inverse")
        wm2.metric("💧 외기습도",  f"{aw['rh']}%")
        wm3.metric("💦 절대습도",  f"{calc_abs_humidity(aw['temp'], aw['rh'])} g/m³")
        wm4.metric("💨 VPD",      f"{aw['vpd']} kPa")

        wm5, wm6, wm7, wm8 = st.columns(4)
        wm5.metric("🌬 풍속",     f"{aw['wind_speed']} m/s",
                   f"{aw.get('wind_dir_kor','')} {aw.get('wind_dir_deg','—')}°")
        wm6.metric("🌡 이슬점",   f"{aw.get('dewpoint', '—')}℃")
        wm7.metric("🔵 기압",     f"{aw.get('pressure_hpa', '—')} hPa")
        wm8.metric("🌧 일강수량", f"{aw.get('rainfall_day', 0)} mm")

        wm9, wm10, wm11, wm12 = st.columns(4)
        wm9.metric("💧 포화수분",  f"{calc_saturation_ah(aw['temp'])} g/m³",
                   help="이 온도가 머금을 수 있는 최대 수분(RH 100%)")
        wm10.metric("🟡 수분부족", f"{calc_moisture_deficit(aw['temp'], aw['rh'])} g/m³",
                    help="포화수분 − 현재 절대습도")

        if aw.get("rainfall_60m", 0) > 0:
            st.warning(f"강수 감지: 최근 60분 {aw['rainfall_60m']} mm", icon="🌧")

        # ── 기상 분석 요약 ──────────────────────────────────────
        st.divider()
        st.subheader("기상 분석")
        an1, an2 = st.columns(2)

        with an1:
            # 온도 분석
            ot = aw["temp"]
            if ot >= 35:
                temp_label, temp_color = "고온 경보 🔴", "#e03131"
            elif ot >= 30:
                temp_label, temp_color = "고온 주의 🟠", "#f76707"
            elif ot >= 20:
                temp_label, temp_color = "적정 🟢", "#2f9e44"
            elif ot >= 10:
                temp_label, temp_color = "서늘 🔵", "#1971c2"
            else:
                temp_label, temp_color = "저온 경보 🟣", "#6741d9"

            # 풍속 분석
            ws = aw["wind_speed"]
            if ws >= 10:
                wind_label = "강풍 — 천창 폐쇄 권장"
            elif ws >= 5:
                wind_label = "강한 바람 — 천창 개방 제한"
            elif ws >= 2:
                wind_label = f"적정 바람 ({aw.get('wind_dir_kor','')}방향) — 자연환기 가능"
            else:
                wind_label = "무풍 — 자연환기 효율 낮음, 환풍기 고려"

            # 강수 분석
            rain = aw.get("rainfall_60m", 0)
            rain_label = f"비 {rain}mm/h — 천창 폐쇄 필수" if rain > 0 else "강수 없음"

            st.markdown(
                f'<div style="border:1.5px solid #dee2e6;border-radius:12px;padding:14px 16px;background:#f8f9fa">'
                f'<div style="font-weight:700;margin-bottom:8px">🌤 외기 상태 분석</div>'
                f'<div style="margin-bottom:6px">온도: <span style="color:{temp_color};font-weight:600">{temp_label}</span> ({ot}℃)</div>'
                f'<div style="margin-bottom:6px">바람: {wind_label}</div>'
                f'<div>강수: {rain_label}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

        with an2:
            # 일사량 분석 (온실 내 센서 기준)
            today_str_w = date.today().isoformat()
            today_recs_w = [r for r in load_decisions()
                            if r.get("timestamp", "").startswith(today_str_w)]
            solars_w = [r.get("sensor_input", {}).get("solar", 0) or 0 for r in today_recs_w]
            avg_sol = sum(solars_w) / len(solars_w) if solars_w else solar

            if avg_sol >= 500:
                sol_label, sol_color = "충분 ☀️ — CO₂ 시비 효과 높음", "#2f9e44"
            elif avg_sol >= 250:
                sol_label, sol_color = "보통 🌤 — 표준 관리 유지", "#f76707"
            elif avg_sol >= 100:
                sol_label, sol_color = "부족 ⛅ — 광합성 속도 저하 주의", "#1971c2"
            else:
                sol_label, sol_color = "매우 부족 ☁️ — CO₂ 시비 중단 고려", "#6741d9"

            # 환기 판단
            od = st.session_state.outdoor_data
            if od:
                hint = ventilation_hint(od, indoor_temp=temp)
            else:
                hint = "외기 데이터 없음"

            st.markdown(
                f'<div style="border:1.5px solid #dee2e6;border-radius:12px;padding:14px 16px;background:#f8f9fa">'
                f'<div style="font-weight:700;margin-bottom:8px">☀️ 일사·환기 분석</div>'
                f'<div style="margin-bottom:6px">광량: <span style="color:{sol_color};font-weight:600">{sol_label}</span></div>'
                f'<div style="margin-bottom:6px">현재 일사: {solar} W/m²  (오늘 평균 {avg_sol:.0f} W/m²)</div>'
                f'<div>환기: {hint}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

        # 강수·천창 경보
        if od and od.get("pty", 0) > 0:
            st.warning(f"{od['pty_label']} 감지 → 천창 즉시 폐쇄 권장", icon="🌧")
    else:
        st.caption(".env에 KMA_API_KEY 설정 후 조회 가능")

    # ── 시간별 예보 (KMA 단기예보) ───────────────────────────────
    st.divider()
    st.subheader("🕐 시간별 예보 (KMA 단기예보)")
    st.caption("외부 온도·상대습도·하늘상태(운량)·강수확률 예보 · 예보광량은 하늘상태 기반 추정값")
    try:
        _fc = _load_forecast()
    except Exception as _fe:
        _fc = None
        _is_auth = "401" in str(_fe) or "Unauthorized" in str(_fe)
        _msg = ("단기예보 키 인증 실패(401) — 현재 KMA_API_KEY는 AWS 실황용입니다. "
                "시간별 예보는 data.go.kr의 단기예보(getVilageFcst) serviceKey가 별도로 필요합니다."
                if _is_auth else
                "시간별 예보를 불러올 수 없습니다 (KMA 단기예보 키/설정 확인).")
        st.info(_msg)
    if _fc:
        _now_s = datetime.now().strftime("%Y%m%d%H%M")
        _upcoming = [f for f in _fc if (f["date"] + f["time"]) >= _now_s][:12]
        if _upcoming:
            _rows = []
            for _f in _upcoming:
                _sky_disp, _light = sky_info(_f.get("SKY"), _f.get("PTY"))
                _rows.append({
                    "시각":          f"{_f['date'][4:6]}/{_f['date'][6:8]} {_f['time'][:2]}시",
                    "외부온도(℃)":   _f.get("TMP", "—"),
                    "상대습도(%)":   _f.get("REH", "—"),
                    "하늘상태(운량)": _sky_disp,
                    "예보광량(추정)": _light,
                    "강수확률(%)":   _f.get("POP", "—"),
                })
            st.dataframe(pd.DataFrame(_rows), use_container_width=True, hide_index=True)
        else:
            st.caption("표시할 예보 시각이 없습니다.")

# ===========================================================================
# TAB 4: 가격 정보
# ===========================================================================
with tab_price:
    kgd = st.session_state.kamis_grades

    sub_status, sub_briefing = st.tabs(["경매현황", "시장 동향 브리핑"])

    # =====================================================================
    # 서브탭 1: 경매현황 — 실시간 경매 원장 + 시세판 + 시장비교 + 과거 5년 비교
    # (구 경매비교·과거 가격 비교 서브탭 통합 — 가시성 개선)
    # =====================================================================
    with sub_status:
        if st.session_state.kamis_error:
            st.warning(st.session_state.kamis_error, icon="⚠️")

        # 실시간 경매 원장 로드
        try:
            _led = _load_ledger()
        except Exception:
            _led = None
            st.info("경매 원장을 불러올 수 없습니다. (.env의 AT_API_KEY 설정·활성화 확인)")

        if _led and _led["rows"]:
            _s = _led["stats"]
            st.subheader("실시간 경매현황")
            st.caption(
                f"{_led['date']} · {_s['count']}건 · 단량당 경락가 기준 · "
                "출처: aT 도매시장 실시간 경매정보"
            )

            # 최소 / 평균 / 최대 카드
            _mc1, _mc2, _mc3 = st.columns(3)
            _mc1.metric("최소가", f"{_s['min']:,}원" if _s['min'] else "—")
            _mc2.metric("평균가", f"{_s['avg']:,}원" if _s['avg'] else "—")
            _mc3.metric("최대가", f"{_s['max']:,}원" if _s['max'] else "—")

            # 경매 원장 표 (단량당 경락가 내림차순) — 등급(특/상/중/하) 표시,
            # 매매구분·부류·품목·거래일자는 화면에서 생략(가시성 개선)
            _df_led = pd.DataFrame(_led["rows"])
            _led_cols = [c for c in
                         ["경락일시", "도매시장", "법인", "등급", "품종", "출하지",
                          "단량", "수량", "단량당 경락가(원)"]
                         if c in _df_led.columns]
            _df_led_display = _df_led[_led_cols].copy()
            _df_led_display["단량당 경락가(원)"] = _df_led_display["단량당 경락가(원)"].apply(
                lambda x: f"{x:,}" if pd.notna(x) else "—"
            )
            st.dataframe(_df_led_display, use_container_width=True, hide_index=True)
            st.download_button(
                "⬇️ CSV 다운로드",
                _df_led_display.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"경매현황_{_led['date']}.csv",
                mime="text/csv",
                key="ledger_csv",
            )
            st.caption("※ 컬럼 헤더 클릭 시 정렬 가능 · 등급은 당일 낙찰가 4등분 근사값입니다.")
        elif _led is not None:
            st.info("오늘 경매 데이터가 아직 없습니다. (경매 시작 전이거나 미집계)")

        # 전월·전년 비교 (등급 근사값)
        if kgd:
            with st.expander("전월·전년 비교 (등급 근사)"):
                def _fmt_p(v):
                    return f"{v:,}원" if v else "—"
                _drows = []
                for _gn2 in ["상", "중", "하"]:
                    _g2   = kgd.get(_gn2, {})
                    _dod2 = _g2.get("dod_change")
                    _drows.append({
                        "등급":      _gn2,
                        "금일(4kg)": _fmt_p(_g2.get("price")),
                        "금일(/kg)": _fmt_p(_g2.get("price_kg")),
                        "전일비":    (f"{_dod2:+,}원" if _dod2 is not None else "—"),
                        "전월":      _fmt_p(_g2.get("prev_month")),
                        "전년":      _fmt_p(_g2.get("prev_year")),
                    })
                st.dataframe(pd.DataFrame(_drows).set_index("등급"), use_container_width=True)
                st.caption("등급 = 낙찰가를 상/중/하 3등분한 근사값")

        st.divider()

        # ── 일자별 시세판 ──────────────────────────────────────────
        st.subheader("일자별 가격 시세판")
        pr_c1, pr_c2 = st.columns([1, 3])
        with pr_c1:
            pr_days  = st.slider("조회 기간 (일)", 7, 90, 30, key="pr_days")
            pr_grade = st.selectbox("등급", ["상", "중", "하"], key="pr_grade")
            pr_fetch = st.button("조회", type="primary", use_container_width=True, key="pr_fetch")

        if pr_fetch or "price_board" in st.session_state:
            if pr_fetch:
                with st.spinner("가격 데이터 조회 중..."):
                    try:
                        _kc = _AT_GRADE_CODES[pr_grade]
                        _series = fetch_price_range(days=pr_days, kind_code=_kc)
                        st.session_state["price_board"] = _series
                        st.session_state["price_board_grade"] = pr_grade
                    except Exception as e:
                        st.session_state.pop("price_board", None)
                        with pr_c2:
                            st.warning(str(e))

            _board = st.session_state.get("price_board", [])
            _board_grade = st.session_state.get("price_board_grade", pr_grade)
            if _board:
                df_b = pd.DataFrame(_board)
                df_b["price"] = pd.to_numeric(df_b["price"], errors="coerce")
                df_b = df_b.dropna(subset=["price"]).sort_values("date", ascending=False)
                df_b["전일비"] = df_b["price"].diff(-1)
                df_b["전일비"] = df_b["전일비"].apply(
                    lambda x: (f"▲ {int(x):,}" if x > 0 else (f"▼ {int(-x):,}" if x < 0 else "─")) if pd.notna(x) else "—"
                )
                df_b["가격(4kg)"] = df_b["price"].apply(lambda x: f"{int(x):,}원")
                df_b["가격(kg)"]  = df_b["price"].apply(lambda x: f"{int(x/4):,}원")
                df_b_display = df_b[["date", "가격(4kg)", "가격(kg)", "전일비"]].rename(columns={"date": "날짜"})

                with pr_c2:
                    st.caption(f"{_board_grade}품 · {len(df_b)}일치 · {_board[-1]['market'] if _board else ''}")
                    st.dataframe(df_b_display, use_container_width=True, hide_index=True)

                st.subheader(f"가격 추이 ({_board_grade}품)")
                _pc_df = df_b.sort_values("date")[["date", "price"]].copy().reset_index(drop=True)

                # 선형 추세선 계산 (numpy 최소제곱)
                _n = len(_pc_df)
                if _n >= 2:
                    import numpy as _np
                    _x = _np.arange(_n)
                    _y = _pc_df["price"].to_numpy(dtype=float)
                    _slope, _intercept = _np.polyfit(_x, _y, 1)
                    _pc_df["trend"] = (_intercept + _slope * _x).round(0)
                    _trend_dir = "▲ 상승" if _slope > 0 else ("▼ 하락" if _slope < 0 else "─ 보합")
                    _trend_color = "#e03131" if _slope > 0 else ("#1971c2" if _slope < 0 else "#868e96")
                else:
                    _pc_df["trend"] = _pc_df["price"]
                    _trend_dir, _trend_color, _slope = "─ 보합", "#868e96", 0.0

                _pc_base = alt.Chart(_pc_df).encode(
                    x=alt.X("date:N", title="날짜", axis=alt.Axis(labelAngle=-30)),
                )
                _pc_line = _pc_base.mark_line(color="#1971c2", strokeWidth=2, point=True).encode(
                    y=alt.Y("price:Q", title="가격 (원/4kg)", scale=alt.Scale(zero=True)),
                    tooltip=[
                        alt.Tooltip("date:N", title="날짜"),
                        alt.Tooltip("price:Q", title="가격(4kg)", format=","),
                    ],
                )
                _pc_trend = _pc_base.mark_line(
                    color=_trend_color, strokeWidth=1.8, strokeDash=[6, 3], opacity=0.8
                ).encode(
                    y=alt.Y("trend:Q", scale=alt.Scale(zero=True)),
                    tooltip=[alt.Tooltip("trend:Q", title="추세(4kg)", format=",")],
                )
                _pc_chart = (_pc_line + _pc_trend).properties(height=300)

                st.altair_chart(_pc_chart, use_container_width=True)

                # 추세 요약
                _daily_chg = int(abs(_slope))
                st.caption(
                    f"실선: 실제 가격 · 점선: 선형 추세  |  "
                    f"추세: **{_trend_dir}** (일평균 {_daily_chg:,}원)  |  "
                    f"단위: 원/4kg · 출처: aT 공판장 경락가격"
                )

        st.divider()

        # ── 시장 간 가격 비교 (구 '경매비교' 서브탭 통합) ──────────────
        st.subheader("🏪 시장 간 가격 비교")
        st.caption("여러 도매시장의 최근 경락가를 겹쳐 비교 → 어느 시장에 낼지·언제 낼지 판단용")
        cmp_c1, cmp_c2 = st.columns([1, 3])
        with cmp_c1:
            cmp_days  = st.slider("비교 기간 (일)", 7, 30, 14, key="cmp_days")
            cmp_grade = st.selectbox("등급", ["상", "중", "하"], key="cmp_grade")
            cmp_fetch = st.button("비교 조회", type="primary", use_container_width=True, key="cmp_fetch")

        if cmp_fetch:
            with st.spinner("시장별 가격 조회 중..."):
                try:
                    st.session_state["market_cmp"] = fetch_price_range_by_markets(
                        days=cmp_days, kind_code=cmp_grade)
                    st.session_state["market_cmp_grade"] = cmp_grade
                    st.session_state["market_cmp_days"] = cmp_days
                except Exception as e:
                    st.session_state.pop("market_cmp", None)
                    with cmp_c2:
                        st.warning(str(e))

        _cmp = st.session_state.get("market_cmp", [])
        if _cmp:
            _cmp_days_used = st.session_state.get("market_cmp_days", cmp_days)
            df_c = pd.DataFrame(_cmp)
            df_c["price"] = pd.to_numeric(df_c["price"], errors="coerce")
            df_c = df_c.dropna(subset=["price"])

            if df_c.empty:
                st.info("조회된 시장별 가격 데이터가 없습니다. (해당 기간 경락 데이터 없음)")
            else:
                # 시장별 다중 라인 비교 차트
                _cmp_chart = alt.Chart(df_c).mark_line(point=True, strokeWidth=2).encode(
                    x=alt.X("date:N", title="날짜", axis=alt.Axis(labelAngle=-30)),
                    y=alt.Y("price:Q", title="가격 (원/4kg)", scale=alt.Scale(zero=False)),
                    color=alt.Color("market:N", title="시장"),
                    tooltip=[
                        alt.Tooltip("date:N", title="날짜"),
                        alt.Tooltip("market:N", title="시장"),
                        alt.Tooltip("price:Q", title="가격(4kg)", format=","),
                    ],
                ).properties(height=320)
                st.altair_chart(_cmp_chart, use_container_width=True)

                # 시장별 최근 평균·최근가·추세 요약
                import numpy as _np2
                _sum_rows = []
                for _mk, _grp in df_c.groupby("market"):
                    _grp = _grp.sort_values("date")
                    _prices = _grp["price"].to_numpy(dtype=float)
                    _avg = int(_prices.mean())
                    if len(_prices) >= 2:
                        _sl = float(_np2.polyfit(_np2.arange(len(_prices)), _prices, 1)[0])
                        _dir = "▲ 상승" if _sl > 0 else ("▼ 하락" if _sl < 0 else "─ 보합")
                    else:
                        _dir = "─"
                    _sum_rows.append({
                        "시장":          _mk,
                        "최근 평균(4kg)": f"{_avg:,}원",
                        "최근가(4kg)":   f"{int(_prices[-1]):,}원",
                        "추세":          _dir,
                        "_avg":          _avg,
                    })
                _sum_df = pd.DataFrame(_sum_rows).sort_values("_avg", ascending=False)
                _best = _sum_df.iloc[0]["시장"]
                st.dataframe(_sum_df.drop(columns=["_avg"]),
                             use_container_width=True, hide_index=True)
                if len(_sum_df) >= 2:
                    st.success(f"최근 {_cmp_days_used}일 평균가 최고 시장: **{_best}** — 출하처 참고", icon="🏪")
                st.caption(
                    "각 점은 해당일 경락(사후) 집계값 · 시장 간 가격차(spread)와 방향으로 "
                    "출하처·시점을 판단하세요 · 출처: aT 공판장 경락가격"
                )
        else:
            st.caption("'비교 조회'를 누르면 시장별 최근 가격 추이를 겹쳐 비교합니다.")

        st.divider()

        # ── 과거 가격 비교 — 6개월~5년 전 (구 '과거 가격 비교' 서브탭 통합) ──
        st.subheader("🗓 완숙토마토 출하가격 — 과거 비교")
        st.caption(
            "출처: KAMIS 농산물유통정보(가락동 도매시장 상품 기준) · "
            "형식 참고: 농업ON 출하시기 지원 서비스"
        )

        if st.session_state.get("price_history") is None:
            st.session_state["price_history"] = fetch_shipment_price_history_static()

        if st.button("KAMIS 실시간 조회", type="primary", key="history_fetch"):
            with st.spinner("KAMIS 과거 가격 조회 중..."):
                try:
                    st.session_state["price_history"] = fetch_shipment_price_history()
                    st.session_state.pop("price_history_error", None)
                except Exception as e:
                    st.session_state["price_history"] = fetch_shipment_price_history_static()
                    st.session_state["price_history_error"] = str(e)

        if st.session_state.get("price_history_error"):
            st.warning(
                f"실시간 KAMIS 조회 실패 — 아래는 2021~2025년 참고 데이터입니다.\n\n"
                f"{st.session_state['price_history_error']}\n\n"
                "KAMIS_API_KEY / KAMIS_API_ID를 .env에 설정하면 실시간 데이터로 전환됩니다 "
                "(https://www.kamis.or.kr → 회원가입 → API 활용신청).",
                icon="⚠️",
            )

        _hist = st.session_state.get("price_history")
        if _hist:
            _is_static = _hist[0].get("source") == "static"
            if _is_static and not st.session_state.get("price_history_error"):
                st.info(
                    "📎 KAMIS_API_KEY가 없어 2021~2025년 5개 시장 월평균(정적 참고 데이터)을 표시합니다. "
                    "실제 KAMIS 키를 설정하면 실시간 값으로 자동 전환됩니다.",
                    icon="📎",
                )
            _hc = st.columns(len(_hist))
            for i, h in enumerate(_hist):
                with _hc[i]:
                    _delta = f"{h['pct_change']:+.1f}%" if h["pct_change"] is not None else None
                    st.metric(h["label"], f"{h['price']:,}원" if h["price"] else "—", delta=_delta)
                    _date_note = h.get("actual_date") or h["target_date"]
                    if h.get("approximated"):
                        _date_note += " (근사)"
                    st.caption(_date_note)
            st.caption("퍼센트는 1년 더 과거 시점 대비 변화율(전년도 대비)입니다.")
        else:
            st.caption("'KAMIS 실시간 조회'를 누르면 6개월전~5년전 출하가격을 비교합니다.")

    # =====================================================================
    # 서브탭 2: 시장 동향 브리핑 — 뉴스 기반 가격 변동 요인 분석
    # =====================================================================
    with sub_briefing:
        st.subheader("📰 시장 동향 브리핑")
        st.caption("네이버 뉴스에서 자재비·인건비·기상 관련 최신 기사를 수집해 가격 변동 요인을 분석합니다. (버튼을 누른 시점 기준으로 생성됩니다)")

        if st.button("브리핑 생성", type="primary", key="briefing_fetch"):
            import os as _os
            _naver_id = _os.getenv("NAVER_CLIENT_ID")
            _naver_secret = _os.getenv("NAVER_CLIENT_SECRET")
            if not _naver_id or not _naver_secret:
                st.warning("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET이 .env에 설정되어 있지 않습니다.")
            else:
                with st.spinner("뉴스 수집 및 분석 중..."):
                    try:
                        _articles = fetch_price_factor_articles(_naver_id, _naver_secret, per_query_count=5)
                        if not _articles:
                            st.session_state.pop("market_briefing", None)
                            st.info("관련 뉴스 기사를 찾지 못했습니다.")
                        else:
                            _src_lines = "\n".join(
                                f"- 제목: {a['title']} | 매체: {a['media']} | 날짜: {a['pub_date']} | "
                                f"요약: {a['description']}"
                                for a in _articles
                            )
                            import requests as _req3
                            _payload = {
                                "model": model,
                                "messages": [
                                    {"role": "system", "content": _BRIEFING_SYSTEM},
                                    {"role": "user", "content":
                                        f"다음은 오늘 수집된 관련 뉴스 기사 목록입니다:\n\n{_src_lines}\n\n"
                                        "위 기사들을 근거로 토마토 가격 변동 요인 브리핑을 작성하세요."},
                                ],
                                "stream": False,
                                "options": {"num_predict": 4096, "num_ctx": 8192},
                            }
                            _r3 = _req3.post("http://localhost:11434/api/chat", json=_payload, timeout=300)
                            _r3.raise_for_status()
                            st.session_state["market_briefing"] = {
                                "content": _r3.json()["message"]["content"].strip(),
                                "articles": _articles,
                            }
                    except Exception as e:
                        st.session_state.pop("market_briefing", None)
                        st.warning(str(e))

        _briefing = st.session_state.get("market_briefing")
        if _briefing:
            st.markdown(_briefing["content"])
            with st.expander(f"수집된 기사 원문 ({len(_briefing['articles'])}건)"):
                for a in _briefing["articles"]:
                    st.markdown(f"- [{a['title']}]({a['link']}) · {a['media']} · {a['pub_date']}")
        else:
            st.caption("'브리핑 생성'을 누르면 최신 뉴스 기반 가격 변동 요인 분석을 생성합니다.")


# ===========================================================================
# TAB 5: 온실 제어
# ===========================================================================
with tab_control:
    # ── 주간 온도 사전 분석 → 야간 권고 ──────────────────────────
    st.subheader("🌡 온도 관리 분석")
    _ta = _temp_analysis

    if _ta["has_day_data"]:
        _tc1, _tc2, _tc3 = st.columns(3)
        _tc1.metric("주간 평균 온도", f"{_ta['day_avg']}℃",
                    f"최고 {_ta['day_max']}℃ / 최저 {_ta['day_min']}℃")
        _tc2.metric("권장 야간 온도", f"{_ta['rec_night']}℃", "주야간 5℃ 차 기준")
        _tc3.metric("현재 야간 평균",
                    f"{_ta['night_avg']}℃" if _ta["night_avg"] else "—",
                    "오늘 18시 이후 측정치")

        _da = _ta["day_avg"]
        if _da > 30:
            st.warning(f"주간 고온({_da}℃) 감지. 야간 {_ta['rec_night']}℃ 이하 목표. 관수·환기 우선 점검.", icon="🌡")
        elif _da >= 22:
            st.success(f"주간 온도 적정({_da}℃). 야간 {_ta['rec_night']}℃ 목표 — 주야간 5℃ 차 유지 시 착과율 향상.", icon="✅")
        else:
            st.error(f"주간 저온({_da}℃). 야간 최소 16℃ 이상 유지 필요. 저온 지속 시 착과 불량 우려.", icon="❄️")

        if _ta["night_avg"]:
            _diff = round(_ta["night_avg"] - _ta["rec_night"], 1)
            if abs(_diff) <= 1.5:
                st.caption(f"✅ 야간 실측 {_ta['night_avg']}℃ — 목표 범위 내")
            elif _diff > 1.5:
                st.caption(f"⚠️ 야간 실측 {_ta['night_avg']}℃ — 목표보다 {_diff}℃ 높음. 냉방·환기 확인")
            else:
                st.caption(f"⚠️ 야간 실측 {_ta['night_avg']}℃ — 목표보다 {abs(_diff)}℃ 낮음. 난방 확인")
    else:
        _is_day = 6 <= datetime.now().hour < 18
        if _is_day:
            st.info(
                f"현재 주간 온도 {temp}℃ 기준 → 오늘 밤 권장 설정 온도: **{_ta['rec_night']}℃** "
                f"(주야간 5℃ 차). '진단하기'를 반복 실행하면 더 정확한 주간 평균이 계산됩니다.", icon="🌡"
            )
        else:
            st.info("주간(6~18시) 진단 기록이 없습니다. 낮 시간에 '진단하기'를 실행하면 야간 온도 권고가 자동으로 계산됩니다.")

    st.divider()

    # ── 조치 제안 카드 ────────────────────────────────────────────
    adv = st.session_state.current_advice

    if adv is None and not st.session_state.advice_error:
        with st.spinner("조치 분석 중..."):
            try:
                from rag.pipeline import search as _rs
                rag_docs = _rs(col_db, f"온도{temp}℃ VPD{vpd_now}kPa CO2{int(co2)}ppm", n_results=3)
                rag_ctx  = "\n\n".join(
                    f"[{d['meta'].get('source_file')}] {d['text'][:300]}" for d in rag_docs
                )
                st.session_state.current_advice = generate_advice(
                    sensor=st.session_state.sensor_data,
                    outdoor=st.session_state.outdoor_data,
                    rag_context=rag_ctx, model=model,
                )
                st.session_state.advice_error = None
            except Exception as e:
                st.session_state.advice_error = str(e)
        st.rerun()
    elif adv is None and st.session_state.advice_error:
        st.error(f"제안 생성 오류: {st.session_state.advice_error}")
        if st.button("🔄 다시 시도", key="adv_retry"):
            st.session_state.advice_error = None
            st.rerun()

    else:
        with st.container(border=True):
            _cc, _rc = st.columns([3, 1])
            _cc.caption(f"🔔 조치 제안  ·  {adv['generated_at']}")
            if _rc.button("🔄 새로 분석", key="adv_refresh", use_container_width=True):
                st.session_state.current_advice = None
                st.rerun()
            st.markdown(f"**상황:** {adv['situation']}")
            st.markdown(f"**제안:** {adv['recommendation']}")
            st.write("")
            by, bn = st.columns(2)
            do_y = by.button("✅ 실행할게요", use_container_width=True, key="adv_y")
            do_n = bn.button("❌ 안 할게요",  use_container_width=True, key="adv_n")
            custom_inp = st.text_input("직접 입력", placeholder="다른 조치를 취했거나 이유를 입력...",
                                       key="adv_custom", label_visibility="collapsed")
            do_custom = st.button("💬 직접 입력 저장", key="adv_custom_save",
                                  disabled=not custom_inp, use_container_width=True)

        if do_y:
            save_advice_response(adv, "y")
            st.session_state.current_advice = None
            st.toast("✅ '실행' 로그 저장됨")
            st.rerun()
        elif do_n:
            save_advice_response(adv, "n")
            st.session_state.current_advice = None
            st.toast("❌ '미실행' 로그 저장됨")
            st.rerun()
        elif do_custom and custom_inp:
            save_advice_response(adv, custom_inp)
            st.session_state.current_advice = None
            st.toast("💬 직접 입력 로그 저장됨")
            st.rerun()

    adv_log = load_advice_log(n=10)
    if adv_log:
        with st.expander(f"조치 응답 이력 ({len(adv_log)}건)", expanded=False):
            for entry in reversed(adv_log):
                resp = entry.get("farmer_response", "")
                icon = "✅" if resp == "y" else ("❌" if resp == "n" else "💬")
                ts   = entry.get("responded_at", "")[:16]
                st.markdown(f"**{icon} {ts}**")
                st.caption(f"상황: {entry.get('situation','')}")
                st.caption(f"제안: {entry.get('recommendation','')}")
                st.caption(f"응답: {'실행' if resp=='y' else ('미실행' if resp=='n' else resp)}")
                st.divider()

    st.divider()

    od = st.session_state.outdoor_data
    if od:
        hint = ventilation_hint(od, indoor_temp=temp)
        st.info(f"🌬 환기 힌트 ({od.get('wf_kor','—')}): {hint}")

    if st.session_state.last_result:
        r = st.session_state.last_result
        st.success(f"진단 완료 — VPD {r['vpd']} kPa  ({r['record']['timestamp']})")
        st.markdown(r["response"])
        with st.expander("RAG 출처"):
            for s in r["record"]["sources"]:
                st.write(f"• {s}")
    elif st.session_state.last_error:
        st.error(f"오류: {st.session_state.last_error}")
        st.info("Ollama 실행 여부 확인: `ollama serve`")
    else:
        st.info("위 **진단하기**를 누르거나 **자동 진단**을 켜세요.")

    st.divider()
    st.subheader("판단 기록 (최근 10건)")
    records = load_decisions()
    if records:
        _hist_rows = []
        for rec in records[-10:][::-1]:
            s   = rec.get("sensor_input", {})
            od_ = rec.get("outdoor") or {}
            _hist_rows.append({
                "시간":       rec.get("timestamp", ""),
                "온도(℃)":   s.get("temp"),
                "습도(%)":   s.get("rh"),
                "CO2(ppm)":  s.get("co2"),
                "일사(W/m²)": s.get("solar", "—"),
                "VPD(kPa)":  rec.get("vpd_calculated"),
                "외기온(℃)": od_.get("outdoor_temp", "—"),
                "풍속(m/s)": round(od_.get("wind_speed", 0), 1) if od_.get("wind_speed") is not None else "—",
                "농민 조치":  rec.get("farmer_action") or "—",
            })
        st.dataframe(pd.DataFrame(_hist_rows), use_container_width=True, hide_index=True)
        with st.expander("최근 진단 전문 보기"):
            lr = records[-1]
            st.caption(f"시간: {lr.get('timestamp')}")
            if lr.get("outdoor"):
                o = lr["outdoor"]
                st.caption(f"외기: {o.get('wf_kor','—')} / {o.get('outdoor_temp')}℃ / {round(o.get('wind_speed',0),1)}m/s")
            st.markdown(lr.get("llm_response", ""))
    else:
        st.caption("아직 판단 기록이 없습니다.")

    st.divider()

    # ── 온실 센서 제어 로그 ──────────────────────────────────────
    st.subheader("🎛 센서 제어 로그")
    _CTRL_LOG = Path(__file__).parent.parent / "control_log.json"

    def _load_ctrl_log() -> list:
        if not _CTRL_LOG.exists():
            return []
        try:
            return json.loads(_CTRL_LOG.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _save_ctrl_log(entries: list) -> None:
        _CTRL_LOG.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")

    ctrl_entries = _load_ctrl_log()

    with st.form("ctrl_log_form"):
        cl1, cl2, cl3 = st.columns(3)
        with cl1:
            cl_target  = st.selectbox("제어 대상", ["천창", "측창", "난방기", "냉방기", "환풍기", "포그", "CO₂공급기", "차광막", "기타"])
            cl_action  = st.selectbox("조치 내용", ["켬", "끔", "개방", "폐쇄", "설정값 변경", "점검", "기타"])
        with cl2:
            cl_setval  = st.text_input("설정값 (선택)", placeholder="예: 25℃, 50%, 개방 30%")
            cl_zone    = st.selectbox("구역", ["전체", "A", "B", "C"])
        with cl3:
            cl_reason  = st.text_input("조치 이유", placeholder="예: VPD 1.8kPa 초과, 고온 경보")
            cl_result  = st.text_input("결과 (선택)", placeholder="예: 온도 2℃ 하강 확인")

        if st.form_submit_button("제어 기록 저장", type="primary"):
            ctrl_entries.append({
                "시각":       datetime.now().isoformat(timespec="seconds"),
                "제어 대상":  cl_target,
                "조치":       cl_action,
                "설정값":     cl_setval or "—",
                "구역":       cl_zone,
                "이유":       cl_reason or "—",
                "결과":       cl_result or "—",
                "센서(당시)": f"온도 {temp}℃ / 습도 {rh}% / VPD {vpd_now}kPa",
            })
            _save_ctrl_log(ctrl_entries)
            st.success(f"'{cl_target} {cl_action}' 제어 로그 저장 완료")
            st.rerun()

    if ctrl_entries:
        df_ctrl = pd.DataFrame(ctrl_entries[::-1])
        st.dataframe(df_ctrl, use_container_width=True, hide_index=True)
        _xl_ctrl = io.BytesIO()
        df_ctrl.to_excel(_xl_ctrl, index=False, engine="openpyxl")
        st.download_button(
            "📥 제어 로그 엑셀 다운로드",
            data=_xl_ctrl.getvalue(),
            file_name=f"control_log_{date.today().isoformat()}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="ctrl_xl_dl",
        )
    else:
        st.caption("제어 기록이 없습니다. 위 폼으로 첫 번째 기록을 추가하세요.")

# ===========================================================================
# TAB: 메모 · AI 상담 (통합)
# ===========================================================================
# (메모+영농일지 통합 → 하단 'with tab_note:' 단일 블록에서 렌더)

with tab_ai:
    # ── 이미지 업로드 분석 (Gemma4 멀티모달) ─────────────────────
    with st.expander("🖼 이미지 업로드 분석 (병해·생육 사진)", expanded=False):
        _img_file = st.file_uploader(
            "사진 업로드 (jpg/png)",
            type=["jpg", "jpeg", "png"],
            key="img_upload",
        )
        _img_question = st.text_input(
            "사진에 대해 질문 (선택)",
            placeholder="예: 이 잎에 어떤 병이 생긴 건가요?",
            key="img_question",
        )
        if _img_file and st.button("이미지 분석", type="primary", key="img_analyze"):
            import base64 as _b64
            _img_b64 = _b64.b64encode(_img_file.read()).decode()
            _img_q   = _img_question or "이 온실 토마토 사진을 분석해서 병해·생육 상태를 진단해줘."
            with st.spinner("이미지 분석 중 (Gemma4 멀티모달)..."):
                try:
                    _pest_rows = col_db.get(where={"source_file": "토마토 병해충 및 방제 list.pdf"})
                    _pest_context = "\n\n".join(_pest_rows.get("documents", []))
                    _disease_docs = search(col_db, f"{_img_q} 토마토 병해충 증상 진단", n_results=3)
                    _ref_context = "\n\n".join(
                        f"[{d['meta'].get('source_file')}]\n{d['text'][:500]}"
                        for d in _disease_docs
                    ) if _disease_docs else "(관련 참고자료 없음)"
                    _img_user_content = (
                        f"{_img_q}\n\n"
                        "[토마토 병해충 및 방제 등록약제 전체 목록]\n"
                        f"{_pest_context}\n\n"
                        "아래는 지식베이스에서 검색된 추가 참고자료입니다.\n\n"
                        f"{_ref_context}"
                    )
                    import requests as _req
                    _payload = {
                        "model": model,
                        "messages": [
                            {"role": "system", "content": _DISEASE_SYSTEM},
                            {
                                "role": "user",
                                "content": _img_user_content,
                                "images": [_img_b64],
                            },
                        ],
                        "stream": False,
                        "options": {"num_predict": 4096, "num_ctx": 32768},
                    }
                    _r = _req.post("http://localhost:11434/api/chat", json=_payload, timeout=300)
                    _r.raise_for_status()
                    _img_ans = _r.json()["message"]["content"].strip()
                except Exception as _e:
                    _img_ans = f"오류: {_e}\n\ngemma4:12b 모델이 로드된 상태에서 Ollama 실행 여부를 확인하세요."
            st.image(_img_file, use_container_width=True)
            st.markdown(_img_ans)

    # ── 병해충 도감 (NCPMS) ────────────────────────────────────────
    with st.expander("병해충 도감 (NCPMS)", expanded=False):
        if not ncpms_has_key():
            st.info("NCPMS 도감을 쓰려면 `.env`에 **NCPMS_API_KEY** 를 추가하세요 "
                    "(ncpms.rda.go.kr → OpenAPI 활용신청).")
        else:
            try:
                _plist = _ncpms_list("토마토")
            except Exception as _pe:
                _plist = []
                st.warning(f"NCPMS 목록 조회 실패: {_pe}")
            if _plist:
                _names = {f"{d['name']} ({d['kind']})": d for d in _plist if d["name"]}
                _sel = st.selectbox("병해충 선택", list(_names.keys()), key="ncpms_sel")
                if _sel and st.button("상세 조회", key="ncpms_detail_btn"):
                    try:
                        st.session_state["ncpms_cur"] = _ncpms_detail(_names[_sel]["sickKey"])
                    except Exception as _de:
                        st.warning(f"상세 조회 실패: {_de}")
                _det = st.session_state.get("ncpms_cur")
                if _det:
                    st.markdown(
                        f"### {_det.get('name','')}  "
                        f"<span style='font-size:0.6em;color:#868e96'>{_det.get('crop','')}</span>",
                        unsafe_allow_html=True)
                    if _det.get("images"):
                        st.image(_det["images"][:3], width=180)
                    for _lbl, _k in [("증상", "symptoms"), ("발생조건", "condition"),
                                     ("방제법", "prevention"), ("화학적 방제", "chemical")]:
                        if _det.get(_k):
                            st.markdown(f"**{_lbl}**  \n{_det[_k]}")
                    st.caption("출처: 국가농작물병해충관리시스템(NCPMS)")
            else:
                st.caption("목록이 비어 있습니다. (키/작물명/서비스코드 확인 필요)")

    st.divider()
    st.subheader("💬 AI 상담 (MCP 에이전트)")
    st.caption(
        f"현재 센서값·외기 조건·지식베이스에 더해, 필요시 Ollama({MCP_DEFAULT_MODEL})가 "
        "센서·생육·진단이력 도구를 직접 호출해 답변합니다.  ·  **Tab**키로 예시 자동완성"
    )

    if not st.session_state.chat_example_queue:
        q = CHAT_EXAMPLES[:]
        random.shuffle(q)
        st.session_state.chat_example_queue = q
    current_example = st.session_state.chat_example_queue[0]

    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if user_q := st.chat_input(f"예) {current_example}", key="chat_diag"):
        st.session_state.chat_example_queue.pop(0)
        st.session_state.chat_history.append({"role": "user", "content": user_q})
        with st.chat_message("user"):
            st.markdown(user_q)
        with st.chat_message("assistant"):
            with st.spinner("MCP 도구 호출 + LLM 추론 중..."):
                try:
                    _rag_docs = search(col_db, user_q, n_results=4)
                    _rag_ctx = "\n\n".join(
                        f"[{d['meta'].get('source_file')}]\n{d['text'][:400]}"
                        for d in _rag_docs
                    )
                    _od = st.session_state.outdoor_data or {}
                    _sd = st.session_state.sensor_data
                    _env_ctx = (
                        f"[현재 센서값] 온도 {_sd.get('temp')}℃ 습도 {_sd.get('rh')}% "
                        f"CO2 {_sd.get('co2')}ppm 일사 {_sd.get('solar')}W/m²\n"
                        f"[외기 조건] {_od.get('outdoor_temp', '?')}℃ "
                        f"풍속 {_od.get('wind_speed', '?')}m/s ({_od.get('wind_dir_kor', '')})"
                    )
                    _full_ctx = f"{_env_ctx}\n\n{_rag_ctx}" if _rag_ctx else _env_ctx
                    answer = mcp_ask(user_q, rag_context=_full_ctx, model=model)
                except Exception as e:
                    if _is_timeout_error(e):
                        answer = (
                            "오류: 응답 시간 초과\n\n"
                            "MCP 에이전트는 도구를 여러 번 호출하며 추론하므로 시간이 오래 걸릴 수 있습니다. "
                            "질문을 더 간단히 나누거나 다시 시도해보세요."
                        )
                    else:
                        answer = f"오류: {e}\n\n- Ollama 실행 여부 확인: `ollama serve`\n- 모델 확인: `ollama list`"
            st.markdown(answer)
            st.session_state.chat_history.append({"role": "assistant", "content": answer})

    if st.session_state.chat_history:
        if st.button("대화 초기화", key="clear_chat"):
            st.session_state.chat_history = []
            st.rerun()

    components.html("""
<script>
(function() {
  function attach() {
    var ta = window.parent.document.querySelector('textarea[data-testid="stChatInputTextArea"]');
    if (!ta) { setTimeout(attach, 400); return; }
    if (ta._tabAC) return;
    ta._tabAC = true;
    ta.addEventListener('keydown', function(e) {
      if (e.key === 'Tab' && ta.value === '') {
        e.preventDefault();
        var ph = ta.getAttribute('placeholder') || '';
        ph = ph.replace(/^예\\) /, '');
        var setter = Object.getOwnPropertyDescriptor(
          window.parent.HTMLTextAreaElement.prototype, 'value'
        ).set;
        setter.call(ta, ph);
        ta.dispatchEvent(new Event('input', { bubbles: true }));
      }
    });
  }
  attach();
})();
</script>
""", height=0)

    st.divider()
    with st.expander("사용 가능한 MCP 도구 목록"):
        st.markdown("""
| 도구 | 설명 |
|------|------|
| `get_sensor_data` | 현재 온실 센서값 (온도·습도·CO2·일사) |
| `get_sensor_history` | 최근 N시간 센서 시계열 |
| `get_growth_data` | 구역별 생육 데이터 (N일치 CSV) |
| `get_growth_latest` | 구역별 최신 생육 현황 |
| `get_decision_history` | 최근 N건 LLM 진단 기록 |
| `add_growth_record` | 새 생육 측정값 기록 |
""")

# ===========================================================================
# TAB 9: 영농일지
# ===========================================================================

def _calendar_html(year: int, month: int, entries: dict, harvest_date: str | None = None) -> str:
    import calendar as _cal
    today_str = date.today().isoformat()
    weeks = _cal.monthcalendar(year, month)
    day_names = ["일", "월", "화", "수", "목", "금", "토"]

    # 병해/충해 이름 집합 (방제 뱃지 병합 대상)
    _DISEASE_NAMES = set(DISEASE_MAP.keys()) | PEST_NAMES

    def _merge_tags(tags: list[str]) -> list[str]:
        """방제 액션 + 병충해명이 함께 있으면 '병충해명 방제' 형태로 병합."""
        spray = [t for t in tags if t in SPRAY_ACTIONS]
        targets = [t for t in tags if t in _DISEASE_NAMES]
        others = [t for t in tags if t not in SPRAY_ACTIONS and t not in _DISEASE_NAMES]
        if spray and targets:
            action = spray[0]
            merged = [f"{d} {action}" for d in targets]
            return merged + spray[1:] + others
        return tags

    def _badge(tag: str) -> str:
        # 병합된 레이블("잿빛곰팡이 방제")은 진한 빨강으로 고정
        bg, fg = TAG_COLORS.get(tag, ("#ffd0d0", "#a61e1e"))
        return (
            f'<span style="display:inline-block;background:{bg};color:{fg};'
            f'font-size:0.6rem;font-weight:600;padding:1px 5px;border-radius:8px;'
            f'margin:1px 1px 0 0;white-space:nowrap;line-height:1.5">{tag}</span>'
        )

    rows_html = ""
    for week in weeks:
        rows_html += "<tr>"
        for wi, day in enumerate(week):
            if day == 0:
                rows_html += '<td class="dc-empty"></td>'
            else:
                ds = f"{year}-{month:02d}-{day:02d}"
                day_list = entries.get(ds, [])  # 하루 여러 건(리스트)
                tags: list[str] = []
                for _e in day_list:
                    tags.extend(_e.get("tags") or [])
                # 저장된 태그가 없으면 그날 내용 전체에서 실시간 감지
                if not tags:
                    _combined = " ".join(_e.get("content", "") for _e in day_list)
                    if _combined.strip():
                        tags = detect_all_tags(_combined)
                tags = list(dict.fromkeys(tags))  # 중복 제거, 순서 유지

                cls = "dc-day"
                if ds == today_str:
                    cls += " dc-today"
                if ds == harvest_date:
                    cls += " dc-harvest"
                if wi == 0:
                    cls += " dc-sun"
                elif wi == 6:
                    cls += " dc-sat"

                # 수확 목표일 배지
                harvest_badge = ""
                if ds == harvest_date:
                    _hd = goal_dday(harvest_date)
                    if _hd is None or _hd > 0:
                        _hlbl = f"🎯 수확 D-{_hd}" if _hd else "🎯 수확"
                    elif _hd == 0:
                        _hlbl = "🎯 수확 D-Day"
                    else:
                        _hlbl = f"🎯 수확 D+{abs(_hd)}"
                    harvest_badge = (
                        f'<div style="background:#e03131;color:#fff;font-size:0.6rem;'
                        f'font-weight:700;padding:1px 5px;border-radius:8px;margin-top:3px;'
                        f'display:inline-block;white-space:nowrap">{_hlbl}</div>'
                    )

                badges_html = "".join(_badge(t) for t in _merge_tags(tags)[:5])
                rows_html += (
                    f'<td class="{cls}"><b>{day}</b>'
                    + harvest_badge
                    + (f'<div class="dc-badges">{badges_html}</div>' if badges_html else "")
                    + "</td>"
                )
        rows_html += "</tr>"

    heads = "".join(f"<th>{n}</th>" for n in day_names)
    return f"""
<style>
.dc-wrap{{width:820px;max-width:100%;table-layout:fixed;border-collapse:collapse;font-family:sans-serif;font-size:0.82rem}}
.dc-wrap th{{padding:6px 2px;text-align:center;color:#777;background:#f4f4f4;border-bottom:2px solid #ddd}}
.dc-wrap td{{border:1px solid #e0e0e0;vertical-align:top;height:72px;padding:4px 5px;background:#fff}}
.dc-wrap td.dc-empty{{background:#f9f9f9}}
.dc-wrap td.dc-today{{background:#fff8dc;border:2px solid #f0c040}}
.dc-wrap td.dc-harvest{{background:#fff0f0;border:2px solid #e03131}}
.dc-wrap td.dc-sun b{{color:#e05050}}
.dc-wrap td.dc-sat b{{color:#4a7fd4}}
.dc-badges{{margin-top:4px;display:flex;flex-wrap:wrap;gap:0}}
</style>
<table class="dc-wrap"><tr>{heads}</tr>{rows_html}</table>
"""


def _render_harvest_info(harvest_date_str: str | None) -> None:
    """수확 목표일 기반 D-day 카드 + 재배 단계 안내를 캘린더 아래에 표출."""
    _dd = goal_dday(harvest_date_str)
    if _dd is None:
        return
    if _dd > 0:
        _dd_color = "#1971c2" if _dd > 14 else "#e67700"
        _dd_label = f"D-{_dd}"
        _dd_sub   = f"수확까지 {_dd}일 남음 ({harvest_date_str})"
    elif _dd == 0:
        _dd_color = "#e03131"
        _dd_label = "D-Day"
        _dd_sub   = "오늘이 수확 목표일입니다!"
    else:
        _dd_color = "#868e96"
        _dd_label = f"D+{abs(_dd)}"
        _dd_sub   = f"수확 목표일 {abs(_dd)}일 초과 ({harvest_date_str})"

    _stage = goal_stage(_dd)
    if _stage:
        st.markdown(
            f'<div style="background:#f1f8f4;border:1px solid #d3f0dd;'
            f'border-radius:8px;padding:11px 15px;margin-top:6px;line-height:1.55">'
            f'<div style="font-weight:700;color:#2f9e44;margin-bottom:5px">'
            f'🌱 현재 단계 · {_stage["stage"]}</div>'
            f'<div style="color:#495057;margin-bottom:3px">✔ <b>이 시기 관리</b> — {_stage["manage"]}</div>'
            f'<div style="color:#495057">⏱ <b>수확 타이밍</b> — {_stage["timing"]}</div>'
            f'<div style="color:#adb5bd;font-size:0.82em;margin-top:6px">{HARVEST_STAGE_SOURCE}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    st.markdown(
        f'<div style="background:#f8f9fa;border-left:5px solid {_dd_color};'
        f'border-radius:8px;padding:12px 16px;margin-top:8px;text-align:center">'
        f'<div style="font-size:2.2em;font-weight:800;color:{_dd_color}">{_dd_label}</div>'
        f'<div style="font-size:0.9em;color:#495057;margin-top:2px">{_dd_sub}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


with tab_note:
    import calendar as _cal_mod

    st.subheader("📅 영농일지")

    # ── 수확 목표일 설정 (캘린더에 🎯 배지 + 아래 정보 자동 표출) ──────────────
    _gs_cal = goal_load()
    _hd_saved_str = _gs_cal.get("harvest_date")
    _hd_saved = None
    if _hd_saved_str:
        try:
            _hd_saved = date.fromisoformat(_hd_saved_str)
        except ValueError:
            _hd_saved = None

    # 달력(≈820px) 폭에 맞춰 오른쪽 여백 컬럼(_hsp)으로 정렬
    _hcol1, _hcol2, _hsp = st.columns([3, 1.3, 1.5])
    with _hcol1:
        _hd_input = st.date_input(
            "🎯 수확 목표일",
            value=_hd_saved,
            format="YYYY-MM-DD",
            key="harvest_date_cal",
        )
    with _hcol2:
        st.markdown("<div style='height:1.8em'></div>", unsafe_allow_html=True)
        _clear_harvest = st.button("목표 해제", key="harvest_clear", use_container_width=True,
                                   disabled=_hd_saved is None)

    if _clear_harvest:
        goal_set_harvest(None)
        st.session_state.pop("harvest_date_cal", None)  # 위젯 상태도 비워 재설정 방지
        st.rerun()

    # 새로 지정하거나 날짜가 바뀌면 저장하고 해당 월로 이동
    _hd_new_str = _hd_input.isoformat() if _hd_input else None
    if _hd_new_str and _hd_new_str != _hd_saved_str:
        goal_set_harvest(_hd_new_str)
        st.session_state.diary_year  = _hd_input.year
        st.session_state.diary_month = _hd_input.month
        st.rerun()

    # ── 달력 월 이동 ────────────────────────────────────────────────────────
    if "diary_year" not in st.session_state:
        st.session_state.diary_year  = date.today().year
        st.session_state.diary_month = date.today().month

    col_prev, col_title, col_next, _cnav = st.columns([1, 4, 1, 5.8])  # 우측 여백으로 달력 폭 정렬
    with col_prev:
        if st.button("◀", key="diary_prev"):
            m = st.session_state.diary_month - 1
            y = st.session_state.diary_year
            if m < 1:
                m = 12; y -= 1
            st.session_state.diary_year = y
            st.session_state.diary_month = m
            st.rerun()
    with col_title:
        st.markdown(
            f"<h4 style='text-align:center;margin:0'>"
            f"{st.session_state.diary_year}년 {st.session_state.diary_month}월</h4>",
            unsafe_allow_html=True,
        )
    with col_next:
        if st.button("▶", key="diary_next"):
            m = st.session_state.diary_month + 1
            y = st.session_state.diary_year
            if m > 12:
                m = 1; y += 1
            st.session_state.diary_year = y
            st.session_state.diary_month = m
            st.rerun()

    # ── 다가오는 계획 AI 선제 알림 ────────────────────────────────────────────
    _diary_entries = diary_load()
    _today_str = date.today().isoformat()
    _lookahead_cutoff = (date.today() + timedelta(days=60)).isoformat()
    _future_dates = sorted(d for d in _diary_entries if _today_str < d <= _lookahead_cutoff)
    if _future_dates:
        _next_plan_date = _future_dates[0]
        _plan_summary = " / ".join(
            e.get("content", "") for e in _diary_entries.get(_next_plan_date, []) if e.get("content", "").strip()
        )
        _days_left = (date.fromisoformat(_next_plan_date) - date.today()).days
        if _plan_summary:
            _cache_key = f"ai_plan_notice_{_next_plan_date}"
            with st.expander(f"📋 다가오는 계획 알림 — {_next_plan_date} ({_days_left}일 후)", expanded=True):
                st.caption(f"영농일지 기록: {_plan_summary}")
                if _cache_key in st.session_state:
                    st.markdown(st.session_state[_cache_key])
                elif st.button("🔬 AI 준비사항 확인", key=f"plan_check_{_next_plan_date}"):
                    with st.spinner("다가오는 계획을 확인하고 준비사항을 안내하는 중..."):
                        try:
                            _plan_docs = search(col_db, _plan_summary, n_results=3)
                            _plan_ref = "\n\n".join(
                                f"[{d['meta'].get('source_file')}]\n{d['text'][:400]}"
                                for d in _plan_docs
                            ) if _plan_docs else "(관련 참고자료 없음)"
                            _plan_user = (
                                f"오늘은 {_today_str}이고, {_next_plan_date}({_days_left}일 후)에 다음 계획이 "
                                f"영농일지에 기록되어 있습니다: \"{_plan_summary}\"\n\n"
                                f"참고자료:\n{_plan_ref}"
                            )
                            import requests as _req4
                            _payload4 = {
                                "model": model,
                                "messages": [
                                    {"role": "system", "content": _PLAN_SYSTEM},
                                    {"role": "user", "content": _plan_user},
                                ],
                                "stream": False,
                                "options": {"num_predict": 1024, "num_ctx": 8192},
                            }
                            _r4 = _req4.post("http://localhost:11434/api/chat", json=_payload4, timeout=300)
                            _r4.raise_for_status()
                            st.session_state[_cache_key] = _r4.json()["message"]["content"].strip()
                            st.rerun()
                        except Exception as _e:
                            st.error(f"준비사항 안내 생성 실패: {_e}")

    # ── 달력 렌더 (수확 목표일 🎯 배지 포함) ─────────────────────────────────
    st.html(_calendar_html(st.session_state.diary_year, st.session_state.diary_month,
                           _diary_entries, harvest_date=_hd_saved_str))

    # ── 수확 목표 정보 자동 표출 (달력 아래) ─────────────────────────────────
    if _hd_saved_str:
        _render_harvest_info(_hd_saved_str)

    st.divider()

    # ── 날짜 선택 ────────────────────────────────────────────────────────────
    _sel_date = st.date_input(
        "날짜 선택",
        value=date.today(),
        key="diary_date_input",
        label_visibility="collapsed",
    )
    _sel_str = _sel_date.isoformat()

    # ── 그날의 기록 목록 (시간별, 개별 삭제) ─────────────────────────────────
    _today_list = diary_day(_sel_str)
    st.markdown(f"#### 🗓 {_sel_str} 기록 ({len(_today_list)}건)")
    if _today_list:
        for _idx, _e in enumerate(_today_list):
            _c_main, _c_del = st.columns([9, 1])
            with _c_main:
                _etags = _e.get("tags") or []
                _tag_str = "  " + " ".join(f"`{t}`" for t in _etags) if _etags else ""
                _epest = _e.get("pesticides") or []
                _pest_html = (
                    f'<div style="font-size:0.8em;color:#2f9e44;margin-top:2px">'
                    f'💊 {", ".join(_epest)}</div>' if _epest else ""
                )
                st.markdown(
                    f'<div style="border-left:3px solid #2f9e44;padding:5px 12px;margin-bottom:6px;'
                    f'background:#f8f9fa;border-radius:0 8px 8px 0">'
                    f'<span style="font-size:0.8em;color:#868e96">⏰ {_e.get("time","")}</span>'
                    f'<span style="font-size:0.8em">{_tag_str}</span>'
                    f'<div>{_e.get("content","")}</div>{_pest_html}</div>',
                    unsafe_allow_html=True,
                )
                for _att_name in (_e.get("attachments") or []):
                    _att_path = DIARY_ATTACH_DIR / _att_name
                    if _att_path.exists():
                        st.download_button(
                            f"📎 {_att_name.split('_', 2)[-1]}",
                            data=_att_path.read_bytes(),
                            file_name=_att_name.split("_", 2)[-1],
                            key=f"diary_att_{_sel_str}_{_idx}_{_att_name}",
                        )
            with _c_del:
                if st.button("🗑", key=f"diary_del_{_sel_str}_{_idx}"):
                    diary_delete(_sel_str, _idx)
                    st.rerun()
    else:
        st.caption("이 날의 기록이 없습니다. 아래에서 첫 기록을 추가하세요.")

    st.divider()

    # ── 새 기록 추가 ─────────────────────────────────────────────────────────
    st.markdown("**➕ 새 기록 추가**")

    _pending_insert = st.session_state.pop("diary_pending_insert", None)
    _pending_key    = st.session_state.get("diary_pending_key", 0)
    # key에 날짜+리셋 카운터 포함 → 추가/날짜변경 시 iframe 재초기화(빈 에디터)
    _reset_cnt = st.session_state.get("diary_reset_cnt", 0)
    _ta_val = _DIARY_EDITOR(
        value="",
        autocomplete_terms=AUTOCOMPLETE_TERMS,
        pending_insert=_pending_insert,
        pending_insert_key=_pending_key,
        key=f"diary_ed_{_sel_str}_{_reset_cnt}",
        default="",
    )
    if _ta_val is None:
        _ta_val = ""

    # ── 방제 감지 → 약품 팝오버 (선택 시 새 기록에 삽입) ─────────────────────
    _all_tags = detect_all_tags(_ta_val) if _ta_val else []
    _detected = detect_diseases(_ta_val) if _ta_val else []
    _picked_pests: list[str] = []
    if _detected:
        _det_label = ", ".join(_detected[:3]) + ("..." if len(_detected) > 3 else "")
        st.info(f"🔍 감지: **{_det_label}** — 방제 약품 목록을 확인하세요.")
        with st.popover("💊 방제 약품 선택", use_container_width=False):
            for _dis in _detected:
                _info = DISEASE_MAP[_dis]
                st.markdown(f"**{_dis}**")
                st.caption(_info["desc"])
                for _p in _info["pesticides"]:
                    if st.checkbox(_p, key=f"pchk_{_sel_str}_{_dis}_{_p}"):
                        _picked_pests.append(_p)
                st.divider()
            if _picked_pests and st.button("✅ 기록에 삽입", key="diary_pest_insert"):
                st.session_state["diary_pending_insert"] = "[방제약품] " + ", ".join(_picked_pests)
                st.session_state["diary_pending_key"] = _pending_key + 1
                st.rerun()

    # ── 파일 첨부 (선택) ─────────────────────────────────────────────────────
    _diary_files = st.file_uploader(
        "📎 파일 첨부 (선택)",
        accept_multiple_files=True,
        key=f"diary_attach_{_sel_str}_{_reset_cnt}",
    )

    # ── 추가 / CSV ───────────────────────────────────────────────────────────
    _btn_add, _btn_csv = st.columns([3, 2])
    with _btn_add:
        if st.button("💾 기록 추가", type="primary", key="diary_add_btn", use_container_width=True):
            if _ta_val.strip():
                _stored_names = [
                    diary_save_attachment(_sel_str, f.name, f.read())
                    for f in (_diary_files or [])
                ]
                diary_add(_sel_str, _ta_val.strip(), _all_tags, _picked_pests, _stored_names)
                st.session_state["diary_reset_cnt"] = _reset_cnt + 1  # 에디터 비우기
                st.success("기록이 추가됐습니다.")
                st.rerun()
            else:
                st.warning("내용을 입력하세요.")
    with _btn_csv:
        _csv_data = diary_to_csv()
        st.download_button(
            "📥 전체 CSV 내보내기",
            data=_csv_data.encode("utf-8-sig"),
            file_name=f"farming_diary_{date.today().isoformat()}.csv",
            mime="text/csv",
            key="diary_csv_dl",
            use_container_width=True,
        )

    # ── 이번 달 기록 목록 ────────────────────────────────────────────────────
    _month_prefix = f"{st.session_state.diary_year}-{st.session_state.diary_month:02d}-"
    _month_days = {k: v for k, v in _diary_entries.items() if k.startswith(_month_prefix)}
    if _month_days:
        _total = sum(len(v) for v in _month_days.values())
        with st.expander(f"이번 달 기록 ({len(_month_days)}일 · {_total}건)", expanded=False):
            for _d in sorted(_month_days):
                _dtags = diary_day_tags(_d)
                _tag_str = "  " + " ".join(f"`{t}`" for t in _dtags) if _dtags else ""
                st.markdown(f"**{_d}**  ({len(_month_days[_d])}건){_tag_str}")
                for _e in sorted(_month_days[_d], key=lambda x: x.get("time", "")):
                    st.caption(f"⏰ {_e.get('time','')}  {_e.get('content','')[:100]}")
                st.divider()

    st.divider()

    # ===========================================================================
    # 양액 조성 기록 + AI 분석
    # ===========================================================================
    st.subheader("🧪 양액 조성 기록")
    st.caption("양액 조성 수치와 관찰된 증상을 날짜별로 기록하고, AI로 성분 부족/과잉 여부를 분석합니다.")

    _nut_date = st.date_input("기록 날짜", value=date.today(), key="nutrient_date_input")
    _nut_date_str = _nut_date.isoformat()

    _nc1, _nc2, _nc3, _nc4, _nc5 = st.columns(5)
    with _nc1:
        _nut_n = st.number_input("N (ppm)", min_value=0.0, value=0.0, step=10.0, key="nut_n")
    with _nc2:
        _nut_p = st.number_input("P (ppm)", min_value=0.0, value=0.0, step=10.0, key="nut_p")
    with _nc3:
        _nut_k = st.number_input("K (ppm)", min_value=0.0, value=0.0, step=10.0, key="nut_k")
    with _nc4:
        _nut_ca = st.number_input("Ca (ppm)", min_value=0.0, value=0.0, step=10.0, key="nut_ca")
    with _nc5:
        _nut_mg = st.number_input("Mg (ppm)", min_value=0.0, value=0.0, step=5.0, key="nut_mg")

    _nc6, _nc7 = st.columns(2)
    with _nc6:
        _nut_ec = st.number_input("EC (mS/cm)", min_value=0.0, value=0.0, step=0.1, key="nut_ec")
    with _nc7:
        _nut_ph = st.number_input("pH", min_value=0.0, value=0.0, step=0.1, key="nut_ph")

    _nut_symptom = st.text_area(
        "관찰된 증상 (선택)",
        placeholder="예: 잎끝이 마르고 아랫잎부터 누렇게 변함",
        key="nut_symptom",
    )

    _nut_recipe = {
        "n": _nut_n, "p": _nut_p, "k": _nut_k, "ca": _nut_ca, "mg": _nut_mg,
        "ec": _nut_ec, "ph": _nut_ph,
    }

    _nb1, _nb2 = st.columns(2)
    with _nb1:
        _nut_save = st.button("💾 기록 저장", type="primary", key="nut_save_btn",
                               use_container_width=True)
    with _nb2:
        _nut_analyze = st.button("🔬 AI 분석 (자동 저장)", key="nut_analyze_btn",
                                  use_container_width=True)

    if _nut_save:
        nutrient_add(_nut_date_str, _nut_recipe, _nut_symptom)
        st.success("양액 조성 기록이 저장됐습니다.")
        st.rerun()

    if _nut_analyze:
        with st.spinner("AI가 양액 조성을 분석 중..."):
            try:
                _past = nutrient_flat(limit=5)
                _past_text = "\n".join(
                    f"- {p['date']}: N{p['recipe'].get('n')}/P{p['recipe'].get('p')}/"
                    f"K{p['recipe'].get('k')}/Ca{p['recipe'].get('ca')}/Mg{p['recipe'].get('mg')} "
                    f"EC{p['recipe'].get('ec')} pH{p['recipe'].get('ph')} "
                    f"— 증상: {p.get('symptom') or '없음'}"
                    for p in _past
                ) or "(과거 기록 없음)"
                _nut_query = f"{_nut_symptom} 양액 결핍 증상 질소 인산 칼리 칼슘 마그네슘 미량원소"
                _nut_docs = search(col_db, _nut_query, n_results=4)
                _nut_ref = "\n\n".join(
                    f"[{d['meta'].get('source_file')}]\n{d['text'][:500]}"
                    for d in _nut_docs
                ) if _nut_docs else "(관련 참고자료 없음)"

                _nut_user = (
                    f"오늘({_nut_date_str}) 양액 조성: N {_nut_n}ppm, P {_nut_p}ppm, K {_nut_k}ppm, "
                    f"Ca {_nut_ca}ppm, Mg {_nut_mg}ppm, EC {_nut_ec}mS/cm, pH {_nut_ph}\n"
                    f"관찰된 증상: {_nut_symptom or '(증상 입력 없음)'}\n\n"
                    f"[최근 조성 이력]\n{_past_text}\n\n"
                    f"[참고자료]\n{_nut_ref}"
                )
                import requests as _req2
                _payload2 = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": _NUTRIENT_SYSTEM},
                        {"role": "user", "content": _nut_user},
                    ],
                    "stream": False,
                    "options": {"num_predict": 2048, "num_ctx": 8192},
                }
                _r2 = _req2.post("http://localhost:11434/api/chat", json=_payload2, timeout=300)
                _r2.raise_for_status()
                _nut_analysis = _r2.json()["message"]["content"].strip()
                nutrient_add(_nut_date_str, _nut_recipe, _nut_symptom, _nut_analysis)
                st.success("분석 완료 및 기록 저장됨.")
                st.markdown(_nut_analysis)
            except Exception as _e:
                st.error(f"분석 실패: {_e}")

    _nut_recent = nutrient_flat(limit=20)
    if _nut_recent:
        with st.expander(f"최근 양액 조성 기록 ({len(_nut_recent)}건)", expanded=False):
            for _rn in _nut_recent:
                _rec = _rn.get("recipe", {})
                st.markdown(
                    f"**{_rn['date']} {_rn.get('time','')}** — "
                    f"N{_rec.get('n','—')}/P{_rec.get('p','—')}/K{_rec.get('k','—')}/"
                    f"Ca{_rec.get('ca','—')}/Mg{_rec.get('mg','—')} "
                    f"EC{_rec.get('ec','—')} pH{_rec.get('ph','—')}"
                )
                if _rn.get("symptom"):
                    st.caption(f"증상: {_rn['symptom']}")
                if _rn.get("ai_analysis"):
                    with st.popover("🔬 AI 분석 결과 보기"):
                        st.markdown(_rn["ai_analysis"])
                st.divider()


# ===========================================================================
# Footer
# ===========================================================================

st.divider()
st.caption(
    "⚠️ 현재 센서값 기반 반응형 판단 보조 도구 — 예측 모델 아님. "
    "자동제어 전 현장 확인 필수. "
    f"업데이트: {datetime.now().strftime('%H:%M:%S')}"
)
