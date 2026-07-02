"""Streamlit UI: greenhouse RAG diagnosis — 6-tab layout."""
import sys
import json
import random
import time
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
from datetime import datetime, date
from pathlib import Path

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

PEST_LOG = Path(__file__).parent.parent / "pest_log.json"

from rag.pipeline import build_vectorstore, calc_vpd, diagnose, load_decisions, chat_query, search
from tools.kma_client import fetch_aws, ventilation_hint, DEFAULT_LAT, DEFAULT_LON
from tools.sensor_client import fetch_sensors, generate_mock
from tools.growth_data import query as growth_query, latest as growth_latest, add_record, ensure_sample_csv, is_sample_data
from agent.agent import ask as mcp_ask, DEFAULT_MODEL as MCP_DEFAULT_MODEL
from tools.kamis_client import fetch_today_price, fetch_price_range, fetch_all_grades, dummy_price
from tools.price_advisor import get_sales_advice
from advisor import (generate_advice, save_response as save_advice_response,
                     load_log as load_advice_log,
                     rag_alert_check, is_rag_check_due)
from tools.notifier import is_in_cooldown, send_alert_email, cooldown_remaining_min

st.set_page_config(page_title="온실 진단 도우미", layout="wide")
st.markdown("""<style>
section[data-testid="stSidebar"] { min-width: 360px !important; max-width: 360px !important; }
</style>""", unsafe_allow_html=True)
st.title("토마토 온실 진단 도우미")
st.caption("RAG 기반 실시간 센서 진단 · PO필름 온실 전용 · 현재 상태 반응형")

# ---------------------------------------------------------------------------
# Vectorstore
# ---------------------------------------------------------------------------

@st.cache_resource(show_spinner="BGE-M3 임베딩 모델 로딩 중...")
def _get_col():
    return build_vectorstore()

col_db = _get_col()

# ---------------------------------------------------------------------------
# Pest log helpers
# ---------------------------------------------------------------------------

def _load_pest_log() -> list:
    if not PEST_LOG.exists():
        return []
    try:
        return json.loads(PEST_LOG.read_text(encoding="utf-8"))
    except Exception:
        return []

def _save_pest_log(entries: list) -> None:
    PEST_LOG.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")

# ---------------------------------------------------------------------------
# Session state init
# ---------------------------------------------------------------------------

_defaults = {
    "sensor_data":        generate_mock(),
    "outdoor_data":       None,
    "outdoor_error":      None,
    "aws_data":           None,
    "aws_error":          None,
    "kamis_data":         None,
    "kamis_error":        None,
    "kamis_grades":       None,
    "last_result":        None,
    "last_error":         None,
    "last_auto_run":      0.0,
    "sensor_mode":        "자동 (API/시뮬레이션)",
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
        "precipitation": aw.get("rainfall_60m", 0),
        "pty":           1 if aw.get("rainfall_60m", 0) > 0 else 0,
        "pty_label":     "비" if aw.get("rainfall_60m", 0) > 0 else "",
        "wf_kor":        f"AWS {aw['stn']}지점",
        "source":        "KMA AWS",
    }

# Auto-fetch KAMIS
if st.session_state.kamis_data is None and st.session_state.kamis_error is None:
    try:
        st.session_state.kamis_data   = fetch_today_price()
        st.session_state.kamis_grades = fetch_all_grades()
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
# Sidebar — sensor input + controls only
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("센서 입력")
    sensor_mode = st.radio(
        "입력 방식",
        ["자동 (API/시뮬레이션)", "수동 (슬라이더)"],
        index=0,
        horizontal=True,
    )

    if sensor_mode == "수동 (슬라이더)":
        sd    = st.session_state.sensor_data
        temp  = st.slider("온도 (℃)",      15.0, 40.0,  float(sd.get("temp",  28.0)), 0.5)
        rh    = st.slider("상대습도 (%)",    30,   100,   int(sd.get("rh",     65)),    1)
        co2   = st.slider("CO2 (ppm)",     300,  2000,  int(sd.get("co2",    420)),   10)
        solar = st.slider("일사량 (W/m²)", 0,    1200,  int(sd.get("solar",  300)),   10)
        st.session_state.sensor_data = {
            "temp": temp, "rh": rh, "co2": co2, "solar": solar,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "source": "manual",
        }
    else:
        sensor_url = st.text_input(
            "센서 API URL",
            placeholder="http://192.168.1.x/api/sensors  (비워두면 시뮬레이션)",
            help="실제 IoT API URL. 비워두면 시간대 기반 시뮬레이션 사용.",
        )
        if st.button("지금 동기화", use_container_width=True):
            with st.spinner("센서 데이터 동기화 중..."):
                st.session_state.sensor_data = fetch_sensors(sensor_url)

        sd = st.session_state.sensor_data
        src = sd.get("source", "")
        if src == "simulation":
            st.error("⚠️ 가짜값 — 시뮬레이션 중", icon="🔴")
        elif src == "api":
            st.success(f"실측  ·  {sd.get('timestamp','')[:19]}", icon="🟢")
        else:
            st.caption(f"{src}  ·  {sd.get('timestamp','')[:19]}")
        if sd.get("api_error"):
            st.warning(f"API 오류 → 시뮬레이션 사용: {sd['api_error']}")
        c1, c2 = st.columns(2)
        c1.metric("온도",      f"{sd['temp']}℃")
        c2.metric("습도",      f"{sd['rh']}%")
        c1.metric("CO₂(ppm)", f"{int(sd['co2'])}")
        c2.metric("일사(W/m²)", f"{sd.get('solar', 0)}")

    sd    = st.session_state.sensor_data
    temp  = float(sd["temp"])
    rh    = float(sd["rh"])
    co2   = float(sd["co2"])
    solar = float(sd.get("solar", 0))
    vpd_now = calc_vpd(temp, rh)

    if sensor_mode == "수동 (슬라이더)":
        st.metric("VPD (계산값)", f"{vpd_now} kPa")

    st.divider()

    # ── 토마토 도매가 + 판매 방향 제안 ─────────────────────────
    st.subheader("토마토 도매가 (KAMIS)")
    _kgd = st.session_state.kamis_grades
    if _kgd and not st.session_state.kamis_error:
        _sa = _kgd.get("상", {})
        _ma = _kgd.get("중", {})

        def _dod_html(dod):
            if dod is None:
                return ""
            arrow = "▲" if dod > 0 else ("▼" if dod < 0 else "─")
            color = "#e03131" if dod > 0 else ("#1971c2" if dod < 0 else "#868e96")
            return f'<div style="font-size:0.75em;color:{color}">{arrow} {abs(dod):,}원</div>'

        _sa_price = _sa.get("price_kg_str", "—")
        _ma_price = _ma.get("price_kg_str", "—")
        st.markdown(f"""
<div style="display:flex;gap:6px;margin-bottom:4px">
  <div style="flex:1;padding:8px 10px;background:#f8f9fa;border-radius:8px;min-width:0">
    <div style="font-size:0.72em;color:#868e96;margin-bottom:2px">상품</div>
    <div style="font-size:1.05em;font-weight:700;white-space:nowrap">{_sa_price}원/kg</div>
    {_dod_html(_sa.get("dod_change"))}
  </div>
  <div style="flex:1;padding:8px 10px;background:#f8f9fa;border-radius:8px;min-width:0">
    <div style="font-size:0.72em;color:#868e96;margin-bottom:2px">중품</div>
    <div style="font-size:1.05em;font-weight:700;white-space:nowrap">{_ma_price}원/kg</div>
    {_dod_html(_ma.get("dod_change"))}
  </div>
</div>
<div style="font-size:0.72em;color:#adb5bd;margin-bottom:6px">{_kgd.get('date','')} · 서울가락 · 4kg 단위</div>
""", unsafe_allow_html=True)

        # 판매 방향 제안
        _adv = get_sales_advice(_sa.get("price"))
        _sig = _adv["signal"]
        if _sig == "출하":
            st.success(f"📦 {_adv['headline']}")
        elif _sig == "직거래":
            st.info(f"🛒 {_adv['headline']}")
        elif _sig == "보통":
            st.warning(f"⚖️ {_adv['headline']}")
        for _line in _adv["detail_lines"]:
            st.caption(_line)
    elif st.session_state.kamis_error:
        st.caption("가격 조회 실패")
    else:
        st.caption(".env에 KAMIS 키 설정 후 조회 가능")

    st.divider()

    st.subheader("자동 진단")
    auto_mode    = st.toggle("자동 진단 켜기", value=False)
    interval_min = st.select_slider(
        "실행 간격",
        options=[10, 15, 30, 60],
        value=30,
        format_func=lambda x: f"{x}분",
        disabled=not auto_mode,
    )
    interval_sec = interval_min * 60

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
    model   = st.selectbox("Ollama 모델",
                           ["gemma3:12b", "llama3.2", "llama3.1", "mistral", "qwen2.5"], index=0)
    run_btn = st.button("진단하기", type="primary", use_container_width=True)

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

if auto_mode:
    elapsed   = time.time() - st.session_state.last_auto_run
    remaining = max(0.0, interval_sec - elapsed)
    if remaining == 0:
        with st.spinner("[자동] 센서 동기화..."):
            st.session_state.sensor_data = fetch_sensors("")
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
                "precipitation": aw.get("rainfall_60m", 0),
                "pty": 1 if aw.get("rainfall_60m", 0) > 0 else 0,
                "pty_label": "비" if aw.get("rainfall_60m", 0) > 0 else "",
                "wf_kor": f"AWS {aw['stn']}지점", "source": "KMA AWS",
            }
        except Exception as e:
            st.session_state.aws_error = str(e)
        with st.spinner("[자동] LLM 진단 중..."):
            _run_diagnosis()
    else:
        time.sleep(1)
        st.rerun()

# ---------------------------------------------------------------------------
# 6 tabs — matching reference repo structure
# ---------------------------------------------------------------------------

tab_env, tab_growth, tab_weather, tab_control, tab_pest, tab_ai = st.tabs([
    "환경 데이터", "생육 데이터", "기상 데이터", "온실 제어", "방제 기록", "AI 상담",
])

# ===========================================================================
# TAB 1: 환경 데이터  (Desktop1 — top metric cards → middle charts → bottom chart)
# ===========================================================================
with tab_env:
    src = sd.get("source", "")
    if src == "simulation":
        st.error("⚠️ 가짜값 — 시뮬레이션 중", icon="🔴")
    elif src == "api":
        st.caption(f"🟢 실측  ·  {sd.get('timestamp','')[:19]}")
    else:
        st.caption(f"✏️ 수동  ·  {sd.get('timestamp','')[:19]}")

    # ── 상단: 5개 메트릭 카드 ────────────────────────────────────
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("🌡 온도",    f"{temp}℃")
    m2.metric("💧 습도",    f"{rh}%")
    m3.metric("🍃 CO₂",    f"{int(co2)} ppm")
    m4.metric("☀️ 일사",   f"{solar} W/m²")
    m5.metric("💨 VPD",    f"{vpd_now} kPa")

    st.divider()

    # ── 중단·하단: 시계열 차트 (판단 기록 활용) ────────────────
    records = load_decisions()
    if records:
        df_hist = pd.DataFrame([{
            "시간":       r.get("timestamp", "")[:16],
            "온도(℃)":   r.get("sensor_input", {}).get("temp"),
            "습도(%)":   r.get("sensor_input", {}).get("rh"),
            "VPD(kPa)":  r.get("vpd_calculated"),
            "CO₂(ppm)":  r.get("sensor_input", {}).get("co2"),
            "일사(W/m²)": r.get("sensor_input", {}).get("solar"),
        } for r in records])
        for col_name in ["온도(℃)", "습도(%)", "VPD(kPa)", "CO₂(ppm)", "일사(W/m²)"]:
            df_hist[col_name] = pd.to_numeric(df_hist[col_name], errors="coerce")

        ch1, ch2 = st.columns(2)
        with ch1:
            st.subheader("온도 & 습도 추이")
            st.line_chart(df_hist.set_index("시간")[["온도(℃)", "습도(%)"]])
        with ch2:
            st.subheader("VPD 추이")
            st.line_chart(df_hist.set_index("시간")[["VPD(kPa)"]])

        st.subheader("CO₂ & 일사 변화")
        st.line_chart(df_hist.set_index("시간")[["CO₂(ppm)", "일사(W/m²)"]])
    else:
        st.info("사이드바에서 **진단하기**를 누르면 환경 데이터 추이가 여기에 표시됩니다.")

    st.divider()

    # ── 내부 vs 외기 상세 비교 ────────────────────────────────
    st.subheader("현재 환경 상세")
    d1, d2 = st.columns(2)
    with d1:
        st.caption("온실 내부")
        st.metric("온도", f"{temp}℃")
        st.metric("습도", f"{rh}%")
        st.metric("CO₂", f"{int(co2)} ppm")
        st.metric("일사", f"{solar} W/m²")
        st.metric("VPD", f"{vpd_now} kPa")
    with d2:
        od = st.session_state.outdoor_data
        st.caption("외기 (KMA AWS)")
        if od:
            st.metric("외기온도", f"{od['outdoor_temp']}℃",
                      delta=f"{temp - od['outdoor_temp']:+.1f}℃ 차", delta_color="inverse")
            st.metric("외기습도", f"{od['outdoor_rh']}%")
            st.metric("외기VPD",  f"{od['outdoor_vpd']} kPa")
            st.metric("풍속",    f"{round(od['wind_speed'],1)} m/s ({od.get('wind_dir_kor','')})")
        else:
            st.caption("외기 데이터 없음 (.env에 KMA_API_KEY 필요)")

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
        g_days = st.slider("최근 N일", 7, 30, 14, key="g_days")

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

    if growth_records:
        df_g = pd.DataFrame(growth_records)
        for col_name in ["crop_height_cm", "fruit_count", "leaf_count"]:
            df_g[col_name] = pd.to_numeric(df_g[col_name], errors="coerce")

        st.subheader("초장 추이")
        st.line_chart(df_g.pivot_table(index="date", columns="zone",
                                       values="crop_height_cm", aggfunc="mean"))

        gc1, gc2 = st.columns(2)
        with gc1:
            st.subheader("착과수 추이")
            st.bar_chart(df_g.pivot_table(index="date", columns="zone",
                                          values="fruit_count", aggfunc="mean"))
        with gc2:
            st.subheader("엽수 추이")
            st.line_chart(df_g.pivot_table(index="date", columns="zone",
                                           values="leaf_count", aggfunc="mean"))

        with st.expander("전체 데이터 보기"):
            st.dataframe(df_g, use_container_width=True, hide_index=True)
    else:
        st.info("해당 조건의 생육 데이터가 없습니다.")

    st.divider()
    st.subheader("토마토 도매가격 추이 (KAMIS)")
    price_days = st.slider("조회 기간 (일)", 7, 30, 14, key="price_days")
    if st.button("가격 추이 조회", key="price_range_btn"):
        try:
            price_series = fetch_price_range(days=price_days)
            if price_series:
                df_p = pd.DataFrame(price_series)
                df_p["price"] = pd.to_numeric(df_p["price"], errors="coerce")
                df_p = df_p.dropna(subset=["price"])
                st.line_chart(df_p.set_index("date")["price"])
                st.caption(f"단위: 원 / 출처: KAMIS {df_p.iloc[0]['market'] if len(df_p) else ''}")
            else:
                st.info("조회된 가격 데이터가 없습니다.")
        except Exception as e:
            st.warning(str(e))

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
            f_truss = st.number_input("화방수",        0,  30, 3,   1)
            f_stem  = st.number_input("줄기직경 (mm)", 0.0, 50.0, 9.0, 0.1)
        f_notes   = st.text_input("비고")
        if st.form_submit_button("기록 저장"):
            add_record(zone=f_zone, crop_height_cm=f_height,
                       leaf_count=int(f_leaf), fruit_count=int(f_fruit),
                       truss_count=int(f_truss), stem_diameter_mm=f_stem, notes=f_notes)
            st.success(f"구역 {f_zone} 생육 데이터 저장 완료")
            st.rerun()

# ===========================================================================
# TAB 3: 기상 데이터
# ===========================================================================
with tab_weather:
    w1, w2 = st.columns(2)

    with w1:
        st.subheader("실시간 기상 (KMA AWS)")
        aw = st.session_state.aws_data
        if st.session_state.aws_error:
            st.warning(st.session_state.aws_error, icon="⚠️")
        elif aw:
            st.caption(f"KMA AWS 지점 {aw['stn']} / {aw['obs_time']}")
            wm1, wm2 = st.columns(2)
            wm1.metric("외기온도", f"{aw['temp']}℃")
            wm2.metric("외기습도", f"{aw['rh']}%")
            wm1.metric("VPD",     f"{aw['vpd']} kPa")
            wm2.metric("풍속",    f"{aw['wind_speed']} m/s")
            if aw.get("rainfall_60m", 0) > 0:
                st.warning(f"강수(60분) {aw['rainfall_60m']} mm", icon="🌧")
        else:
            st.caption(".env에 KMA_API_KEY 설정 후 조회 가능")

        od = st.session_state.outdoor_data
        if od:
            st.divider()
            hint = ventilation_hint(od, indoor_temp=temp)
            st.info(f"🌬 환기 힌트: {hint}")
            st.caption(f"기준: 외기 {od['outdoor_temp']}℃ / {od.get('wf_kor','—')}")
            if od.get("pty", 0) > 0:
                st.warning(f"{od['pty_label']} 중 → 천창 주의", icon="🌧")

    with w2:
        st.subheader("토마토 도매가격 (KAMIS)")
        kd  = st.session_state.kamis_data
        kgd = st.session_state.kamis_grades
        if st.session_state.kamis_error:
            st.warning(st.session_state.kamis_error, icon="⚠️")

        if kgd:
            st.caption(f"{kgd['date']} / {kgd['market']} / 단위 4kg")

            _rows = []
            for _gn in ["상", "중", "하"]:
                _g   = kgd.get(_gn, {})
                _dod = _g.get("dod_change")
                if _dod is not None:
                    _ds = f"▲{_dod:,}" if _dod > 0 else (f"▼{abs(_dod):,}" if _dod < 0 else "─")
                else:
                    _ds = "—"
                _rows.append({
                    "등급":    _gn,
                    "4kg(원)": f"{_g['price']:,}"    if _g.get("price")    else "—",
                    "/kg(원)": f"{_g['price_kg']:,}" if _g.get("price_kg") else "—",
                    "전일비":  _ds,
                })
            st.dataframe(pd.DataFrame(_rows).set_index("등급"), use_container_width=True)

            with st.expander("가격 상세보기 (전월·전년·순평년)"):
                def _fmt(v):
                    return f"{v:,}원" if v else "—"
                _drows = []
                for _gn2 in ["상", "중", "하"]:
                    _g2  = kgd.get(_gn2, {})
                    _dod2 = _g2.get("dod_change")
                    _drows.append({
                        "등급":      _gn2,
                        "금일(4kg)": _fmt(_g2.get("price")),
                        "금일(/kg)": _fmt(_g2.get("price_kg")),
                        "전일비":    (f"{_dod2:+,}원" if _dod2 is not None else "—"),
                        "전월":      _fmt(_g2.get("prev_month")),
                        "전년":      _fmt(_g2.get("prev_year")),
                        "순평년":    _fmt(_g2.get("avg_year")),
                    })
                st.dataframe(pd.DataFrame(_drows).set_index("등급"), use_container_width=True)
                st.caption("출처: KAMIS 농산물유통정보 / 서울가락 / 순평년=과거 5년 평균")
        elif kd:
            st.caption(f"{kd['date']} / {kd['market']} / 상등급")
            st.metric("토마토 도매가", kd["price_str"],
                      delta=(f"{kd['dod_change']:+,}원" if kd.get("dod_change") is not None else None))
        else:
            st.caption(".env에 KAMIS_API_KEY / KAMIS_API_ID 설정 후 조회 가능")

# ===========================================================================
# TAB 4: 온실 제어
# ===========================================================================
with tab_control:
    # ── 조치 제안 카드 ────────────────────────────────────────────
    adv = st.session_state.current_advice

    if adv is None:
        with st.spinner("조치 분석 중..."):
            try:
                from rag.pipeline import search as _rs
                rag_docs = _rs(col_db, f"온도{temp}℃ VPD{vpd_now}kPa CO2{int(co2)}ppm", n_results=3)
                rag_ctx  = "\n".join(d["text"][:300] for d in rag_docs)
                st.session_state.current_advice = generate_advice(
                    sensor=st.session_state.sensor_data,
                    outdoor=st.session_state.outdoor_data,
                    rag_context=rag_ctx, model=model,
                )
                st.session_state.advice_error = None
            except Exception as e:
                st.session_state.advice_error = str(e)
        st.rerun()
        if st.session_state.advice_error:
            st.error(f"제안 생성 오류: {st.session_state.advice_error}")

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

    ctrl_l, ctrl_r = st.columns([3, 1])
    with ctrl_r:
        st.subheader("센서 현황")
        _src = sd.get("source", "")
        if _src == "simulation":
            st.error("가짜값 (시뮬레이션)", icon="⚠️")
        elif _src == "api":
            st.caption(f"🟢 실측  ·  {sd.get('timestamp','')[:19]}")
        st.metric("온도", f"{temp}℃")
        st.metric("습도", f"{rh}%")
        st.metric("CO2",  f"{int(co2)} ppm")
        st.metric("일사",  f"{solar} W/m²")
        st.metric("VPD",  f"{vpd_now} kPa")
        if auto_mode:
            st.divider()
            _rem = max(0, int(interval_sec - (time.time() - st.session_state.last_auto_run)))
            st.metric("다음 자동 진단", f"{_rem}초 후")

    with ctrl_l:
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
            st.info("사이드바에서 **진단하기**를 누르거나 **자동 진단**을 켜세요.")

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

# ===========================================================================
# TAB 5: 방제 기록
# ===========================================================================
with tab_pest:
    st.subheader("방제 기록")
    pest_entries = _load_pest_log()

    if pest_entries:
        st.dataframe(pd.DataFrame(pest_entries), use_container_width=True, hide_index=True)
    else:
        st.info("방제 기록이 없습니다. 아래 폼으로 첫 번째 기록을 추가하세요.")

    st.divider()
    st.subheader("방제 기록 입력")
    with st.form("pest_form"):
        pf1, pf2, pf3 = st.columns(3)
        with pf1:
            p_date   = st.date_input("방제 일자", value=date.today())
            p_zone   = st.selectbox("구역", ["전체", "A", "B", "C"])
        with pf2:
            p_target = st.text_input("방제 대상 (병해충)")
            p_chem   = st.text_input("약품명")
        with pf3:
            p_dose   = st.text_input("용량 (희석 배수 또는 g/L)")
            p_method = st.selectbox("살포 방법", ["분무", "훈증", "관주", "기타"])
        p_notes = st.text_input("비고")
        if st.form_submit_button("기록 저장"):
            if p_target and p_chem:
                pest_entries.append({
                    "일자":      p_date.isoformat(),
                    "구역":      p_zone,
                    "방제 대상": p_target,
                    "약품명":    p_chem,
                    "용량":      p_dose,
                    "살포 방법": p_method,
                    "비고":      p_notes,
                    "입력 시각": datetime.now().isoformat(timespec="seconds"),
                })
                _save_pest_log(pest_entries)
                st.success("방제 기록이 저장되었습니다.")
                st.rerun()
            else:
                st.warning("방제 대상과 약품명을 입력하세요.")

# ===========================================================================
# TAB 6: AI 상담
# ===========================================================================
with tab_ai:
    st.subheader("💬 자연어 질문")
    st.caption("현재 센서값·외기 조건·지식베이스를 바탕으로 자유롭게 질문하세요.  ·  **Tab**키로 예시 자동완성")

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
            with st.spinner("답변 생성 중..."):
                try:
                    answer = chat_query(
                        question=user_q, col=col_db,
                        sensor=st.session_state.sensor_data,
                        history=st.session_state.chat_history[:-1],
                        model=model, outdoor=st.session_state.outdoor_data,
                    )
                except Exception as e:
                    answer = f"오류: {e}\n\nOllama 실행 여부 확인: `ollama serve`"
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
    st.subheader("MCP 에이전트")
    st.caption(
        f"MCP 서버 도구(센서·생육·진단이력)를 Ollama({MCP_DEFAULT_MODEL})가 직접 호출하여 답변합니다. "
        "RAG 문서 검색도 자동으로 포함됩니다."
    )

    if "mcp_history" not in st.session_state:
        st.session_state.mcp_history = []

    for msg in st.session_state.mcp_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if mcp_q := st.chat_input("예) 지금 온실 상태 보고 B구역 생육 데이터랑 비교해줘", key="chat_mcp"):
        st.session_state.mcp_history.append({"role": "user", "content": mcp_q})
        with st.chat_message("user"):
            st.markdown(mcp_q)
        with st.chat_message("assistant"):
            with st.spinner("MCP 도구 호출 + LLM 추론 중..."):
                try:
                    rag_docs   = search(col_db, mcp_q, n_results=4)
                    rag_ctx    = "\n\n".join(f"[{d['meta'].get('source_file')}] {d['text'][:400]}" for d in rag_docs)
                    mcp_answer = mcp_ask(mcp_q, rag_context=rag_ctx, model=model)
                except Exception as e:
                    mcp_answer = f"오류: {e}\n\n- Ollama 실행 여부 확인: `ollama serve`\n- 모델 확인: `ollama list`"
            st.markdown(mcp_answer)
            st.session_state.mcp_history.append({"role": "assistant", "content": mcp_answer})

    if st.session_state.mcp_history:
        if st.button("MCP 대화 초기화", key="clear_mcp"):
            st.session_state.mcp_history = []
            st.rerun()

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
# Footer
# ===========================================================================

st.divider()
st.caption(
    "⚠️ 현재 센서값 기반 반응형 판단 보조 도구 — 예측 모델 아님. "
    "자동제어 전 현장 확인 필수. "
    f"업데이트: {datetime.now().strftime('%H:%M:%S')}"
)
