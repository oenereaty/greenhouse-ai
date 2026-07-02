"""이메일 경보 — Gmail SMTP.

Gmail 앱 비밀번호 발급:
  Google 계정 → 보안 → 2단계 인증 켜기 → 앱 비밀번호 생성 (Mail / Mac)
  .env에 EMAIL_APP_PASSWORD=발급된16자리 입력
"""
import math
import os
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

COOLDOWN_FILE = Path(__file__).parent.parent / ".last_email_sent"
COOLDOWN_MINUTES = int(os.getenv("EMAIL_COOLDOWN_MINUTES", "30"))

# 임계값 (.env 또는 기본값)
TEMP_MAX   = float(os.getenv("ALERT_TEMP_MAX",  "35.0"))   # ℃
VPD_MAX    = float(os.getenv("ALERT_VPD_MAX",   "2.5"))    # kPa
CO2_MAX    = float(os.getenv("ALERT_CO2_MAX",   "1500"))   # ppm


def check_threshold(sensor: dict) -> list[str]:
    """임계값 초과 항목 반환. 빈 리스트면 정상."""
    temp = float(sensor.get("temp", 0))
    rh   = float(sensor.get("rh", 100))
    co2  = float(sensor.get("co2", 0))
    es   = 0.6108 * math.exp(17.27 * temp / (temp + 237.3))
    vpd  = round(es * (1 - rh / 100), 3)

    alerts = []
    if temp > TEMP_MAX:
        alerts.append(f"온도 {temp}℃ (기준 {TEMP_MAX}℃ 초과)")
    if vpd > VPD_MAX:
        alerts.append(f"VPD {vpd} kPa (기준 {VPD_MAX} 초과)")
    if co2 > CO2_MAX:
        alerts.append(f"CO₂ {int(co2)} ppm (기준 {int(CO2_MAX)} 초과)")
    return alerts


def is_in_cooldown() -> bool:
    """쿨다운 중이면 True (연속 발송 방지)."""
    if not COOLDOWN_FILE.exists():
        return False
    try:
        last = datetime.fromisoformat(COOLDOWN_FILE.read_text().strip())
        return (datetime.now() - last).total_seconds() / 60 < COOLDOWN_MINUTES
    except Exception:
        return False


def send_alert_email(
    alerts: list[str],
    sensor: dict,
    situation: str = "",
    recommendation: str = "",
) -> None:
    """임계값 초과 경보 이메일 발송."""
    from_addr = os.getenv("EMAIL_FROM", "")
    to_addr   = os.getenv("EMAIL_TO", from_addr)
    password  = os.getenv("EMAIL_APP_PASSWORD", "")

    if not all([from_addr, password]):
        raise RuntimeError(
            "EMAIL_FROM / EMAIL_APP_PASSWORD가 .env에 없습니다.\n"
            "Gmail 앱 비밀번호를 발급 후 입력하세요."
        )

    ts   = datetime.now().strftime("%Y-%m-%d %H:%M")
    temp = sensor.get("temp")
    rh   = sensor.get("rh")
    co2  = sensor.get("co2")
    solar = sensor.get("solar")
    es   = 0.6108 * math.exp(17.27 * float(temp) / (float(temp) + 237.3))
    vpd  = round(es * (1 - float(rh) / 100), 3)

    alert_lines = "\n".join(f"  ⚠️  {a}" for a in alerts)

    ai_block = ""
    if situation or recommendation:
        ai_block = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AI 분석 및 후속 조치
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
        if situation:
            ai_block += f"📋 현재 상황:\n  {situation}\n\n"
        if recommendation:
            ai_block += f"✅ 권장 조치:\n  {recommendation}\n"

    body = f"""\
[온실 경보] {ts}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️  경보 발생 항목
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{alert_lines}

현재 센서 값:
  🌡 온도     {temp} ℃
  💧 습도     {rh} %
  🌿 VPD     {vpd} kPa
  🍃 CO₂     {co2} ppm
  ☀️  일사량   {solar} W/m²
{ai_block}
감지 시각: {ts}

─────────────────────────────
(이 메시지는 온실 진단 시스템이 자동 발송했습니다.)
"""

    subject = f"[온실 경보] {', '.join(a.split('(')[0].strip() for a in alerts)}"

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"]    = from_addr
    msg["To"]      = to_addr

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(from_addr, password)
        server.send_message(msg)

    COOLDOWN_FILE.write_text(datetime.now().isoformat(), encoding="utf-8")


def cooldown_remaining_min() -> int:
    """쿨다운 남은 시간(분). 쿨다운 아니면 0."""
    if not COOLDOWN_FILE.exists():
        return 0
    try:
        last = datetime.fromisoformat(COOLDOWN_FILE.read_text().strip())
        diff = (datetime.now() - last).total_seconds() / 60
        return max(0, int(COOLDOWN_MINUTES - diff))
    except Exception:
        return 0
