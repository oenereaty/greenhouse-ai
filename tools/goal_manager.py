"""농장 목표 관리 — 저장/로드 + D-day 계산."""
import json
from datetime import date
from pathlib import Path

from tools.demo_clock import demo_now


def _today() -> date:
    """발표용 고정 "오늘"(tools/demo_clock.py) — 센서·기상과 같은 기준일을 쓴다."""
    return demo_now().date()

GOAL_FILE = Path(__file__).parent.parent / "goal_settings.json"

# 환경 목표(사이드바 다중선택). 출하기간(수확 목표일)은 캘린더에서 별도 관리.
GOAL_OPTIONS = ["당도 향상", "수확량 증가", "생식생장 유지"]

# 목표별 환경 힌트 (AI 분석 카드에 한 줄 추가)
# 주야간 온도차(DIF) 5~7℃는 knowledge_base/01_temperature.md의 근거값과 통일
# (2026-07-10, 코드 내 서로 다른 수치가 쓰이고 있던 것을 정정).
GOAL_HINTS: dict[str, str] = {
    "당도 향상":    "당도 향상 목표: 주야간 온도차(DIF) 5~7°C 유지, 수확 전 VPD를 0.6–0.9 kPa로 관리하세요.",
    "수확량 증가":  "수확량 목표: VPD 0.3–0.7 kPa · CO₂ 800–1000 ppm · 안정적 온도(22–26°C)가 핵심입니다.",
    "생식생장 유지":"생식생장 목표: 주간 온도 24–26°C, VPD 0.6 kPa↑, 야간 온도를 낮게 유지하세요.",
}


def load() -> dict:
    if not GOAL_FILE.exists():
        return {"goals": [], "harvest_date": None}
    try:
        return json.loads(GOAL_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"goals": [], "harvest_date": None}


def save(goals: list[str], harvest_date: str | None) -> None:
    GOAL_FILE.write_text(
        json.dumps({"goals": goals, "harvest_date": harvest_date},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def set_goals(goals: list[str]) -> None:
    """환경 목표(다중선택)만 갱신하고 수확 목표일은 보존."""
    cur = load()
    save(list(goals), cur.get("harvest_date"))


def set_harvest_date(harvest_date: str | None) -> None:
    """수확 목표일만 갱신하고 환경 목표 목록은 보존."""
    cur = load()
    save(cur.get("goals", []), harvest_date)


def dday(harvest_date_str: str | None) -> int | None:
    """수확 목표일까지 남은 일수 (오늘 포함). 음수면 초과."""
    if not harvest_date_str:
        return None
    try:
        target = date.fromisoformat(harvest_date_str)
        return (target - _today()).days
    except ValueError:
        return None


# 수확 단계별 안내 근거 출처 (앱에 함께 표기)
HARVEST_STAGE_SOURCE = "출처: 농촌진흥청 국립원예특작과학원, 토마토 스마트 온실 관리 매뉴얼(2017)"


# 5단계 순서 테이블(0=가장 이른 단계 ~ 4=가장 늦은 단계). 달력(D-day) 판단과
# 생육데이터 판단이 같은 인덱스 체계를 공유해 평균으로 blend할 수 있게 한다.
_STAGE_TABLE = [
    {
        "stage": "개화·착과기",
        "manage": "생육적온 일평균 18~20℃, 최저 13℃ 이상·최고 29℃ 이하로 관리하세요. 35℃ 이상 고온은 꽃에 장해를 일으켜 기형과 원인이 됩니다.",
        "timing": "일평균온도가 높을수록 개화→수확 소요일수가 줄어드는 경향입니다(정확한 일수는 품종·재배환경에 따라 달라 실측 생육 데이터로 확인하세요).",
    },
    {
        "stage": "과실 비대기",
        "manage": "주야간 온도차(DIF)를 5~7℃로 유지하세요. 야간온도가 과도하게 높으면 호흡 소모가 늘어 당도·건물 축적이 줄고 품질이 떨어집니다.",
        "timing": "예정보다 늦으면 일평균온도를 1℃ 높이세요(생육 속도 약 10%↑ — 단, 온도를 높이면 수확량이 줄어들 수 있어 품질과 함께 확인하세요).",
    },
    {
        "stage": "성숙 전환·착색 시작",
        "manage": "야간온도를 15℃ 이상 범위에서 낮게 유지해 당도를 높이고, 과습으로 인한 열과를 주의하세요.",
        "timing": "착색이 늦으면 주간온도를 유지·상승시켜 성숙을 앞당깁니다.",
    },
    {
        "stage": "착색·수확기",
        "manage": "야간온도가 15℃ 미만으로 내려가면 착색 불량·생육 지연 위험이 커집니다. 야간온도를 확보하세요.",
        "timing": "예정보다 빠르면 일평균온도를 낮춰(1℃↓ ≈ 생육 10% 지연) 출하일을 맞추세요.",
    },
    {
        "stage": "수확기 도래",
        "manage": "착색이 완료된 화방부터 순차 수확하세요. 과숙을 넘기지 않도록 주의합니다.",
        "timing": "이미 목표일을 지났습니다. 남은 과실은 빠르게 수확·출하하세요.",
    },
]

# 영농일지 "수확" 태그가 처음 나타난 뒤 이 일수 이내면 "성숙 전환·착색 시작"(2),
# 이보다 오래 이어지면 "착색·수확기"(3)로 추정한다.
_HARVEST_JUST_STARTED_DAYS = 10


def _growth_stage_index() -> tuple[int, str] | None:
    """생육데이터 + 영농일지 "수확" 기록으로 현재 단계 인덱스(0~3)를 추정.

    화방높이·초장 같은 정밀 생육 신호는 harvest_strategy.py의 _growth_summary()가
    이미 다루므로 여기서는 재배 단계 자체를 가리키는 두 신호만 본다:
      1) 영농일지에 "수확" 태그가 있으면 성숙 전환기 이후로 본다(개화·과실비대는
         착과수/화방수만으로는 착색 여부를 알 수 없어 판단 불가) — 처음 나타난
         날짜로부터 지난 일수로 "막 시작"(2) vs "본격 진행"(3)을 나눈다.
      2) "수확" 기록이 아직 없으면 평균 착과수·화방수로 개화·착과기(0)와
         과실 비대기(1)만 구분한다.
    growth_data·diary 둘 다 기록이 없으면 None(생육 신호 없음)을 반환한다.
    """
    from tools.diary_data import load_all
    from tools.growth_data import latest

    today = _today()
    harvest_dates = sorted(
        d for d, entries in load_all().items()
        if d <= today.isoformat() and any("수확" in (e.get("tags") or []) for e in entries)
    )
    if harvest_dates:
        first = date.fromisoformat(harvest_dates[0])
        days_since = (today - first).days
        if days_since <= _HARVEST_JUST_STARTED_DAYS:
            return 2, f"영농일지에 {harvest_dates[0]}부터 수확 기록이 있어(시작 {days_since}일째) 성숙 전환·착색 시작 수준으로 추정"
        return 3, f"영농일지에 {harvest_dates[0]}부터 수확 기록이 이어지고 있어(시작 {days_since}일째) 착색·수확기로 추정"

    rows = latest("전체")
    fruits = [float(r["fruit_count"]) for r in rows if r.get("fruit_count") not in ("", None)]
    trusses = [float(r["truss_count"]) for r in rows if r.get("truss_count") not in ("", None)]
    if not fruits and not trusses:
        return None
    avg_fruit = sum(fruits) / len(fruits) if fruits else 0
    avg_truss = sum(trusses) / len(trusses) if trusses else 0
    if avg_fruit >= 3 or avg_truss >= 3:
        return 1, f"평균 착과 {avg_fruit:.1f}개·화방 {avg_truss:.1f}개로 과실 비대기 수준"
    return 0, f"평균 착과 {avg_fruit:.1f}개·화방 {avg_truss:.1f}개로 개화·착과 초기 수준"


def _calendar_stage_index(days_left: int | None) -> int | None:
    if days_left is None:
        return None
    if days_left < 0:
        return 4
    if days_left <= 7:
        return 3
    if days_left <= 20:
        return 2
    if days_left <= 45:
        return 1
    return 0


def harvest_stage(days_left: int | None) -> dict | None:
    """수확 목표일(D-day)과 실측 생육데이터·영농일지 기록을 동등 가중 평균해
    토마토 재배 단계를 판단하고 관리 조언을 반환한다.

    두 신호 모두 0(개화·착과기)~4(수확기 도래) 인덱스로 정규화한 뒤 평균(반올림)해
    최종 단계를 고른다. 한쪽 신호가 없으면(목표일 미설정 또는 생육 기록 없음) 있는
    신호만 사용한다. 둘 다 없으면 None.

    각 단계의 온도·수치는 다음 출처를 따른다(지식베이스에 임베딩되어 검증 가능):
      - 토마토 스마트 온실 관리 매뉴얼(농촌진흥청 국립원예특작과학원, 2017):
        생육적온 일평균 18~20℃, 최저온도 13℃ 이상·최고온도 29℃ 이하 관리,
        착색 최저온도 12℃, 주야간온도편차(DIF) 관리
      - 토마토 환경관리 가이드라인(2018): 발아적온 25~30℃, 저온 10℃ 이하 생육저하,
        5℃ 생장정지, 35~40℃ 꽃 장해(기형과 원인), 40℃ 생장중지
    24시간 평균온도와 개화→수확 소요일수의 구체적 관계(예: "20℃면 54일")는
    검증 가능한 출처를 찾지 못해 제외했다 — 필요하면 실측 데이터로 직접 캘리브레이션할 것.

    Returns:
        {"stage": 단계명, "manage": 이 시기 관리, "timing": 수확 타이밍 조절,
         "consistency_note": 두 신호가 2단계 이상 어긋날 때만 존재} 또는 None
    """
    cal_idx = _calendar_stage_index(days_left)
    growth = _growth_stage_index()
    growth_idx = growth[0] if growth else None

    if cal_idx is None and growth_idx is None:
        return None
    if cal_idx is None:
        final_idx = growth_idx
    elif growth_idx is None:
        final_idx = cal_idx
    else:
        final_idx = min(4, max(0, int((cal_idx + growth_idx) / 2 + 0.5)))

    result = dict(_STAGE_TABLE[final_idx])
    if cal_idx is not None and growth_idx is not None and abs(cal_idx - growth_idx) >= 2:
        cal_name = _STAGE_TABLE[cal_idx]["stage"]
        growth_name = _STAGE_TABLE[growth_idx]["stage"]
        result["consistency_note"] = (
            f"참고: 수확 목표일 기준으로는 '{cal_name}'이지만, 생육·일지 기록 기준은 "
            f"'{growth_name}'로 추정됩니다({growth[1]}). 두 신호를 평균해 현재 단계를 "
            f"'{result['stage']}'로 표시했습니다."
        )
    return result
