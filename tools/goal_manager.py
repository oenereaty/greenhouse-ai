"""농장 목표 관리 — 저장/로드 + D-day 계산."""
import json
from datetime import date
from pathlib import Path

GOAL_FILE = Path(__file__).parent.parent / "goal_settings.json"

# 환경 목표(사이드바 다중선택). 출하기간(수확 목표일)은 캘린더에서 별도 관리.
GOAL_OPTIONS = ["당도 향상", "수확량 증가", "생식생장 유지"]

# 목표별 환경 힌트 (AI 분석 카드에 한 줄 추가)
GOAL_HINTS: dict[str, str] = {
    "당도 향상":    "당도 향상 목표: 주야 일교차 8°C↑ 유지, 수확 전 VPD를 0.6–0.9 kPa로 관리하세요.",
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
        return (target - date.today()).days
    except ValueError:
        return None


# 수확 단계별 안내 근거 출처 (앱에 함께 표기)
HARVEST_STAGE_SOURCE = "출처: 농촌진흥청 국립원예특작과학원, 토마토 스마트 온실 관리 매뉴얼(2017)"


# 달력 기반 단계 → 실측 착과수/화방수로 기대할 수 있는 대략적인 진행 단계.
# 순서가 빠를수록(0에 가까울수록) 초기 생육. 교차검증에만 쓰는 거친 매핑이다.
_STAGE_PROGRESS = {
    "개화·착과기": 0,
    "과실 비대기": 1,
    "성숙 전환·착색 시작": 2,
    "착색·수확기": 3,
    "수확기 도래": 3,
}


def _actual_progress_hint() -> tuple[int, str] | None:
    """실측 착과수·화방수로 대략적인 생육 진행도(0~3)를 추정 — 달력 기반 단계와의
    교차검증용. LLM 미사용(순수 규칙)이라 빠르고 안전하다."""
    from tools.growth_data import latest

    rows = latest("전체")
    fruits = [float(r["fruit_count"]) for r in rows if r.get("fruit_count") not in ("", None)]
    trusses = [float(r["truss_count"]) for r in rows if r.get("truss_count") not in ("", None)]
    if not fruits and not trusses:
        return None
    avg_fruit = sum(fruits) / len(fruits) if fruits else 0
    avg_truss = sum(trusses) / len(trusses) if trusses else 0
    if avg_fruit >= 8 or avg_truss >= 4:
        return 3, f"평균 착과 {avg_fruit:.1f}개·화방 {avg_truss:.1f}개로 착색·수확기에 가까운 상태"
    if avg_fruit >= 3:
        return 1, f"평균 착과 {avg_fruit:.1f}개·화방 {avg_truss:.1f}개로 과실 비대기 수준"
    return 0, f"평균 착과 {avg_fruit:.1f}개·화방 {avg_truss:.1f}개로 개화·착과 초기 수준"


def harvest_stage(days_left: int | None) -> dict | None:
    """남은 일수(D-day)를 토마토 재배 단계로 매핑해 관리·타이밍 조언 반환.

    사용자가 입력한 "수확 목표일" 역산이 메인 로직이지만, 실측 착과수·화방수
    (growth_data.latest)와 교차검증해 목표일과 실제 생육이 크게 어긋나면
    "consistency_note" 필드로 알려준다 — 실측 기반 상세 판단은
    harvest_strategy.py의 _growth_summary()(화방높이·초장·줄기두께 기반)를
    함께 참고할 것.

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
         "consistency_note": 실측과 어긋날 때만 존재} 또는 None
    """
    result = _calendar_stage(days_left)
    if result is None:
        return result

    hint = _actual_progress_hint()
    if hint is not None:
        actual_progress, actual_desc = hint
        calendar_progress = _STAGE_PROGRESS.get(result["stage"])
        if calendar_progress is not None and abs(actual_progress - calendar_progress) >= 2:
            result["consistency_note"] = (
                f"참고: 목표일 기준으로는 '{result['stage']}'이지만, 실측 생육 데이터는 {actual_desc}입니다. "
                "수확 목표일이 실제 생육 속도와 맞는지 확인해 보세요."
            )
    return result


def _calendar_stage(days_left: int | None) -> dict | None:
    if days_left is None:
        return None
    if days_left < 0:
        return {
            "stage": "수확기 도래",
            "manage": "착색이 완료된 화방부터 순차 수확하세요. 과숙을 넘기지 않도록 주의합니다.",
            "timing": "이미 목표일을 지났습니다. 남은 과실은 빠르게 수확·출하하세요.",
        }
    if days_left <= 7:
        return {
            "stage": "착색·수확기",
            "manage": "일평균 12℃ 이하면 착색이 불량해집니다. 야간온도를 확보하세요.",
            "timing": "예정보다 빠르면 일평균온도를 낮춰(1℃↓ ≈ 생육 10% 지연) 출하일을 맞추세요.",
        }
    if days_left <= 20:
        return {
            "stage": "성숙 전환·착색 시작",
            "manage": "야간온도를 낮게 유지해 당도를 높이고, 과습으로 인한 열과를 주의하세요.",
            "timing": "착색이 늦으면 주간온도를 유지·상승시켜 성숙을 앞당깁니다.",
        }
    if days_left <= 45:
        return {
            "stage": "과실 비대기",
            "manage": "주야간 온도차(DIF)를 3~5℃로 유지하세요. 야간온도가 낮으면 당도가 오르고 수확이 빨라집니다.",
            "timing": "예정보다 늦으면 일평균온도를 1℃ 높이세요(생육 속도 약 10%↑ — 단, 온도를 높이면 수확량이 줄어들 수 있어 품질과 함께 확인하세요).",
        }
    return {
        "stage": "개화·착과기",
        "manage": "생육적온 일평균 18~20℃, 최저 13℃ 이상·최고 29℃ 이하로 관리하세요. 35℃ 이상 고온은 꽃에 장해를 일으켜 기형과 원인이 됩니다.",
        "timing": "일평균온도가 높을수록 개화→수확 소요일수가 줄어드는 경향입니다(정확한 일수는 품종·재배환경에 따라 달라 실측 생육 데이터로 확인하세요).",
    }
