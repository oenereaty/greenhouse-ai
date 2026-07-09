"""토마토 병해충 환경 연계 위험 예찰.

NCPMS 도감의 발생조건과 원예 문헌을 구조화한 규칙(PEST_RISK_RULES)을,
현재 온실 환경(온도·상대습도)과 대조해 '지금 위험한 병해충'을 순위로 산출한다.

규칙 근거: tools/pesticide_db.py의 DISEASE_MAP desc(발생조건) + 일반 재배 문헌.
습도 방향(humid)은 발생을 촉진하는 습도 조건:
    "high"  = 다습(고습)에서 촉진   → 현재 습도 높을수록 위험
    "low"   = 건조에서 촉진         → 현재 습도 낮을수록 위험
    "any"   = 습도 영향 약함(온도 위주)
"""
from __future__ import annotations

# disease/pest → 발생 촉진 조건
# temp: (최저, 최고) 촉진 온도(℃) · humid: "high"|"low"|"any" · kind: "병"|"충"
# pathogen_type: 병해 원인 분류(곰팡이성/난균성/세균성/해충 등). 해충은 바이러스 매개 여부도 note와 함께 표시한다.
PEST_RISK_RULES: dict[str, dict] = {
    "잿빛곰팡이":     {"temp": (15, 25), "humid": "high", "kind": "병", "pathogen_type": "곰팡이성", "note": "저온·다습(습도 85%↑), 잎 결로 시 급증"},
    "잎곰팡이":       {"temp": (20, 28), "humid": "high", "kind": "병", "pathogen_type": "곰팡이성", "note": "고온다습, 환기 불량 하우스에서 다발"},
    "역병":           {"temp": (15, 25), "humid": "high", "kind": "병", "pathogen_type": "난균성", "note": "과습 + 잎 습윤 지속 시 폭발적"},
    "세균성점무늬병": {"temp": (20, 28), "humid": "high", "kind": "병", "pathogen_type": "세균성", "note": "결로·강우 시 전파, 다습 조건"},
    "흰가루병":       {"temp": (20, 25), "humid": "low",  "kind": "병", "pathogen_type": "곰팡이성", "note": "다소 건조·주야 온도차 클 때"},
    "진딧물":         {"temp": (20, 28), "humid": "low",  "kind": "충", "pathogen_type": "해충·바이러스 매개 가능", "note": "건조·따뜻할 때 번식 빠름, 바이러스 매개"},
    "가루이":         {"temp": (25, 30), "humid": "any",  "kind": "충", "pathogen_type": "해충·바이러스 매개 가능", "note": "고온에서 세대 단축, 바이러스 매개"},
    "총채벌레":       {"temp": (25, 30), "humid": "low",  "kind": "충", "pathogen_type": "해충·바이러스 매개 가능", "note": "고온건조, TSWV(칼라병) 매개"},
    "응애":           {"temp": (27, 32), "humid": "low",  "kind": "충", "pathogen_type": "해충", "note": "고온건조에서 폭발적 증식"},
    "담배나방":       {"temp": (25, 30), "humid": "any",  "kind": "충", "pathogen_type": "해충", "note": "고온기 야간 산란, 과실 식해"},
}

# 위험 등급 → (라벨, 정렬 가중치)
_LEVELS = {"high": ("높음", 3), "watch": ("주의", 2), "low": ("낮음", 1)}


def _temp_match(temp: float, lo: float, hi: float) -> bool:
    return lo <= temp <= hi


def _temp_near(temp: float, lo: float, hi: float, margin: float = 3.0) -> bool:
    return (lo - margin) <= temp <= (hi + margin)


def _humid_match(rh: float, direction: str, high_th: float = 80.0, low_th: float = 60.0) -> bool:
    if direction == "high":
        return rh >= high_th
    if direction == "low":
        return rh <= low_th
    return True  # "any"


def assess_one(name: str, rule: dict, temp: float, rh: float) -> dict:
    """단일 병해충의 현재 환경 위험도 판정."""
    lo, hi = rule["temp"]
    direction = rule["humid"]
    t_hit   = _temp_match(temp, lo, hi)
    t_near  = _temp_near(temp, lo, hi)
    h_hit   = _humid_match(rh, direction)

    if t_hit and h_hit:
        level = "high"
    elif (t_hit or t_near) and (h_hit or direction == "any"):
        level = "watch"
    else:
        level = "low"

    label, weight = _LEVELS[level]
    reasons = []
    reasons.append(f"온도 {temp:.0f}℃ {'적합' if t_hit else ('근접' if t_near else '벗어남')}(촉진 {lo}~{hi}℃)")
    if direction == "high":
        reasons.append(f"습도 {rh:.0f}% {'높음→촉진' if h_hit else '낮음→억제'}(다습성)")
    elif direction == "low":
        reasons.append(f"습도 {rh:.0f}% {'낮음→촉진' if h_hit else '높음→억제'}(건조성)")
    else:
        reasons.append(f"습도 영향 작음(온도 위주)")

    return {
        "name":   name,
        "kind":   rule["kind"],
        "pathogen_type": rule.get("pathogen_type", ""),
        "level":  level,
        "label":  label,
        "weight": weight,
        "note":   rule["note"],
        "reason": " · ".join(reasons),
    }


def assess_risk(temp: float, rh: float) -> list[dict]:
    """현재 온도·습도로 전체 병해충 위험도를 산출(위험 높은 순 정렬)."""
    results = [assess_one(n, r, temp, rh) for n, r in PEST_RISK_RULES.items()]
    # 위험등급 desc, 같은 등급이면 병(병해) 우선, 이름순
    results.sort(key=lambda x: (-x["weight"], 0 if x["kind"] == "병" else 1, x["name"]))
    return results


def top_risks(temp: float, rh: float, min_level: str = "watch") -> list[dict]:
    """min_level 이상(watch/high)인 병해충만 반환."""
    floor = _LEVELS[min_level][1]
    return [r for r in assess_risk(temp, rh) if r["weight"] >= floor]


def _norm(s: str) -> str:
    return s.replace("병", "").replace("성", "")


def pest_thumb_map(ncpms_items: list[dict]) -> dict[str, str]:
    """NCPMS search_diseases() 결과 → {PEST_RISK_RULES 이름: 썸네일 URL}.

    NCPMS 공식 명칭은 '병'·'성' 등 접미사 표기가 달라 그대로는 잘 일치하지 않는다
    (예: '잎곰팡이' vs '잎곰팡이병', '세균성점무늬병' vs '세균점무늬병').
    접미사를 정규화한 뒤 부분일치로 매칭한다.
    """
    thumbs = [(d["name"], d["thumb"]) for d in ncpms_items if d.get("name") and d.get("thumb")]
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
