"""비료 제품 → 보증성분(%) DB + 그램수·희석량 → 원소 ppm 환산.

포대의 보증성분표는 관행상 산화물 기준(인산 P2O5 %, 가리 K2O %, 고토 MgO %,
석회 CaO %)으로 표기되므로, 실제 시비 ppm 계산 전에 원소량(P/K/Ca/Mg)으로
환산해야 한다. 환산계수는 분자량비로 고정된 화학 상수다.
"""
from pathlib import Path
import json

# 산화물 → 원소 환산계수 (분자량비, 화학 상수 — 제품에 따라 달라지지 않음)
P2O5_TO_P = 0.436
K2O_TO_K = 0.830
CAO_TO_CA = 0.715
MGO_TO_MG = 0.603

# 표준 단일 화합비료 — 제조사와 무관하게 성분비가 화학적으로 고정된 일반 화합물만
# 담는다. 농가마다 배합비가 다른 복합비료는 여기 추측해 넣지 않고 register_product()로
# 실제 포대의 보증성분표를 등록해서 쓴다.
# 값 기준: 질소전량 N %, 인산 P2O5 %, 가리 K2O %, 석회 CaO %, 고토 MgO %.
GENERIC_PRODUCTS: dict[str, dict[str, float]] = {
    "요소":                  {"n": 46.0, "p2o5": 0.0,  "k2o": 0.0,  "cao": 0.0,  "mgo": 0.0},
    "질산칼슘":               {"n": 15.5, "p2o5": 0.0,  "k2o": 0.0,  "cao": 19.0, "mgo": 0.0},
    "황산마그네슘(황산고토)":  {"n": 0.0,  "p2o5": 0.0,  "k2o": 0.0,  "cao": 0.0,  "mgo": 16.0},
    "황산가리(황산칼륨)":      {"n": 0.0,  "p2o5": 0.0,  "k2o": 50.0, "cao": 0.0,  "mgo": 0.0},
    "염화가리(염화칼륨)":      {"n": 0.0,  "p2o5": 0.0,  "k2o": 60.0, "cao": 0.0,  "mgo": 0.0},
    "제1인산칼륨(MKP)":       {"n": 0.0,  "p2o5": 52.0, "k2o": 34.0, "cao": 0.0,  "mgo": 0.0},
    "인산이암모늄(DAP)":      {"n": 18.0, "p2o5": 46.0, "k2o": 0.0,  "cao": 0.0,  "mgo": 0.0},
    "제1인산암모늄(MAP)":     {"n": 12.0, "p2o5": 61.0, "k2o": 0.0,  "cao": 0.0,  "mgo": 0.0},
}

CUSTOM_PRODUCTS_FILE = Path(__file__).parent.parent / "fertilizer_products.json"


def _load_custom() -> dict[str, dict[str, float]]:
    if not CUSTOM_PRODUCTS_FILE.exists():
        return {}
    try:
        return json.loads(CUSTOM_PRODUCTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_custom(data: dict[str, dict[str, float]]) -> None:
    CUSTOM_PRODUCTS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def all_products() -> dict[str, dict[str, float]]:
    """일반 화합물 + 사용자 등록 제품 전체 (이름이 같으면 사용자 등록이 우선)."""
    merged = dict(GENERIC_PRODUCTS)
    merged.update(_load_custom())
    return merged


def register_product(name: str, n: float = 0.0, p2o5: float = 0.0, k2o: float = 0.0,
                      cao: float = 0.0, mgo: float = 0.0) -> None:
    """포대에 적힌 보증성분표 그대로(N/P2O5/K2O/CaO/MgO %) 실제 제품을 등록한다."""
    data = _load_custom()
    data[name] = {"n": n, "p2o5": p2o5, "k2o": k2o, "cao": cao, "mgo": mgo}
    _save_custom(data)


def delete_product(name: str) -> None:
    data = _load_custom()
    data.pop(name, None)
    _save_custom(data)


def compute_ppm(mix: list[dict], water_liters: float) -> dict:
    """mix=[{"product": str, "grams": float}, ...] + 희석 물량(L) → 원소 ppm(mg/L).

    DB에 없는 product는 계산에서 제외하고 "unknown_products"로 알려준다 — 값을
    지어내지 않는다. 호출부는 이 목록이 비어있지 않으면 사용자에게 해당 제품을
    register_product()로 등록하라고 안내해야 한다.
    """
    totals = {"n": 0.0, "p": 0.0, "k": 0.0, "ca": 0.0, "mg": 0.0}
    unknown: list[str] = []

    if not water_liters or water_liters <= 0:
        return {**{k: None for k in totals}, "unknown_products": [m.get("product", "") for m in (mix or [])]}

    products = all_products()
    for item in mix or []:
        name = item.get("product", "")
        grams = float(item.get("grams", 0) or 0)
        spec = products.get(name)
        if spec is None:
            unknown.append(name)
            continue
        mg_total = grams * 1000  # g -> mg
        totals["n"] += mg_total * (spec.get("n", 0) / 100)
        totals["p"] += mg_total * (spec.get("p2o5", 0) / 100) * P2O5_TO_P
        totals["k"] += mg_total * (spec.get("k2o", 0) / 100) * K2O_TO_K
        totals["ca"] += mg_total * (spec.get("cao", 0) / 100) * CAO_TO_CA
        totals["mg"] += mg_total * (spec.get("mgo", 0) / 100) * MGO_TO_MG

    ppm = {k: round(v / water_liters, 1) for k, v in totals.items()}
    ppm["unknown_products"] = unknown
    return ppm
