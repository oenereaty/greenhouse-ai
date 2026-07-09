"""환경값 계산 + 규칙 기반 해석 — 순수 함수, LLM/네트워크 호출 없음.

기존에 ui/app.py에 인라인으로 있던 계산(VPD·절대습도 등 4곳에 중복)과 해석 로직을
한 곳으로 모은 것. FastAPI 백엔드(backend/routers/environment.py)의 단일 출처이며,
프론트엔드는 이 값을 다시 계산하지 않고 그대로 표시만 한다.
"""
from __future__ import annotations

import math
from datetime import datetime

# ---------------------------------------------------------------------------
# 순수 계산
# ---------------------------------------------------------------------------


def calc_vpd(temp_c: float, rh_percent: float) -> float:
    """포화수증기압차(VPD, kPa) — Tetens 공식."""
    svp = 0.6108 * math.exp(17.27 * temp_c / (temp_c + 237.3))
    avp = svp * (rh_percent / 100)
    return round(svp - avp, 3)


def calc_abs_humidity(temp: float, rh: float) -> float:
    """절대 습도 (g/m³) — Tetens 공식 기반."""
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
    lbl, icon, light = _SKY_LABEL.get(str(sky), ("—", "", "—"))
    p = _PTY_LABEL.get(str(pty), "")
    disp = f"{icon} {lbl}" + (f"·{p}" if p else "")
    return disp, light


# ---------------------------------------------------------------------------
# 규칙 기반 해석 (LLM 아님)
# ---------------------------------------------------------------------------


def env_interpret(temp: float, rh: float, vpd: float, co2: int, solar: float,
                   outdoor: dict | None = None) -> list[dict]:
    """센서값 → 자연어 해석 카드 목록 반환.
    각 항목: {icon, title, body, level}  (level: ok / warn / danger)

    습도는 RH를 1차 직접제어 기준(ASABE 2015 A등급, 지식베이스 02_vpd.md)으로 판단하고,
    환기가 필요한 경우 외기 습도를 함께 확인한다(04_ventilation.md 조치원칙 — 외기가
    더 습하면 환기 대신 온도를 소폭 올리는 편이 효과적). VPD는 보조 참고 지표로 유지한다.
    """
    cards = []
    out_rh = (outdoor or {}).get("outdoor_rh")
    is_raining = (outdoor or {}).get("pty", 0) not in (0, None)

    def _vent_note() -> str:
        if is_raining:
            return (
                "강수 중이라 창을 크게 여는 단순 환기는 실내 절대습도를 낮추지 못하고 온도만 떨어뜨려 "
                "결로·고습성 병해(잿빛곰팡이·잎곰팡이) 위험을 키울 수 있습니다. 순환팬을 가동하고 "
                "환기는 제한적으로만 하되, 필요하면 소폭 난방으로 결로를 피하세요."
            )
        if out_rh is None:
            return "환기를 검토하되, 외기 습도를 먼저 확인하세요(외기도 습하면 환기 대신 온도를 올리는 게 효과적입니다)."
        if out_rh < rh - 10:
            return f"외기 습도({out_rh}%)가 더 낮아 환기가 효과적입니다. 창을 여세요."
        return f"외기 습도({out_rh}%)도 높아 환기 효과가 제한적입니다. 순환팬을 함께 가동하거나 실내 온도를 1~2℃ 올려 상대습도를 낮추는 방법을 검토하세요."

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
        dry_note = (
            f" (외기 습도 {out_rh}%도 낮아 창을 닫는 게 유리합니다.)"
            if out_rh is not None and out_rh < rh else ""
        )
        cards.append({"icon": "🏜️", "title": f"습도 {rh}% — 건조",
                      "body": f"50% 미만은 증산 과다·칼슘 이동 저해(배꼽썩음 위험) 구간입니다. 창을 닫고 관수 횟수를 늘리세요.{dry_note}",
                      "level": "warn"})
    else:
        cards.append({"icon": "✅", "title": f"습도 {rh}% — 적정 구간",
                      "body": "ASABE 기준 적정 범위(50~90%, 최적 50~70%)입니다. 현재 환경을 유지하세요.",
                      "level": "ok"})

    # ── VPD 해석 (보조 참고 지표 — 02_vpd.md 논문 참고범위 표 기준, 5단계)
    # 02_vpd.md의 "VPD 참고 범위" 표: 과습(<0.3)/병해위험(<0.2), 적정(0.3~1.0~1.2대,
    # 연구별로 0.5~0.8·0.5~1.2·0.3~1.0 등 편차), 다소높음(1.2~1.5, 아직 "위험"은 아님),
    # 위험(>1.5), 생리장해위험(>2.2). 기존 코드는 "다소높음"과 "위험"을 하나로 묶어
    # 1.2 kPa부터 바로 경고를 띄웠는데, 문서 자체는 1.5 kPa까지는 "위험"으로 보지
    # 않으므로(모니터링 필요 단계) 적정 범위를 문서 기준대로 0.3~1.5로 넓힌다.
    if vpd < 0.2:
        cards.append({"icon": "🦠", "title": f"VPD {vpd} kPa — 병해 위험 참고치",
                      "body": "0.2 kPa 미만은 병원균 확산이 빨라지는 참고 구간입니다. 위 습도 판단을 우선 기준으로 삼으세요.",
                      "level": "danger"})
    elif vpd < 0.3:
        cards.append({"icon": "💦", "title": f"VPD {vpd} kPa — 과습 참고치",
                      "body": "증산이 억제될 수 있는 참고 구간입니다(0.3 kPa 미만). 위 습도 판단을 우선 기준으로 삼으세요.",
                      "level": "warn"})
    elif vpd <= 1.5:
        cards.append({"icon": "✅", "title": f"VPD {vpd} kPa — 적정 참고범위",
                      "body": "증산·광합성에 무난한 참고 범위입니다(0.3–1.5 kPa, 연구별 세부 범위는 0.5–0.8~1.2 kPa로 다소 편차가 있습니다). 1.2 kPa를 넘으면 증산이 강해지는 편이니 관수·환기 상태를 함께 확인하세요.",
                      "level": "ok"})
    elif vpd <= 2.2:
        cards.append({"icon": "🔥", "title": f"VPD {vpd} kPa — 건조장해 참고치",
                      "body": "1.5 kPa 초과는 위조·잎말림 위험이 있는 참고 구간입니다. 차광·관수를 검토하세요.",
                      "level": "warn"})
    else:
        cards.append({"icon": "🚨", "title": f"VPD {vpd} kPa — 생리장해 위험 참고치",
                      "body": "2.2 kPa 초과는 기공 폐쇄·생리장해 위험이 큰 참고 구간입니다. 즉각 차광·관수·환기가 필요합니다.",
                      "level": "danger"})

    # ── 온도 해석
    if temp >= 32:
        cards.append({"icon": "🌡️", "title": f"온도 {temp}℃ — 고온 경보",
                      "body": "32℃ 이상은 착과·화분 불활성화 위험입니다. 즉시 환기하고 차광 스크린을 활용하세요.",
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
    climate_first = rh >= 85 or temp >= 28
    if co2 < 400:
        if climate_first:
            cards.append({"icon": "🍃", "title": f"CO₂ {co2} ppm — 온습도 안정 우선",
                          "body": "낮 시간에는 광합성으로 CO₂가 내려갈 수 있습니다. 현재는 토마토 농가 기준상 온도·습도 안정화가 1순위이므로 CO₂ 시비보다 환기·순환·차광으로 고습·고온을 먼저 낮추세요. 환기가 필요한 동안 CO₂ 시비 효율은 낮습니다.",
                          "level": "warn"})
        elif solar > 100:
            cards.append({"icon": "🍃", "title": f"CO₂ {co2} ppm — 광합성 한계 접근",
                          "body": "온도·습도가 안정적이고 환기 개도를 낮게 유지할 수 있을 때만 CO₂ 시비를 검토하세요.",
                          "level": "warn"})
        else:
            cards.append({"icon": "🍃", "title": f"CO₂ {co2} ppm — 저농도",
                          "body": "CO₂는 낮지만 일사가 약하면 시비 효과가 제한적입니다. 온도·습도와 일사 조건을 먼저 확인하세요.",
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
                          "body": "낮 시간대이지만 일사가 낮습니다. CO₂ 시비 효과가 낮고 VPD 관리가 어려울 수 있습니다. 보광 여부를 검토하세요.",
                          "level": "warn"})
        elif solar > 800:
            cards.append({"icon": "☀️", "title": f"일사 {solar} W/m² — 강광",
                          "body": "강한 일사로 잎 온도가 기온보다 높아질 수 있습니다. VPD가 높아져 기공이 닫히기 전에 차광 스크린으로 증산을 유지하세요.",
                          "level": "warn"})

    return cards
