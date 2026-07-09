"""NCPMS(국가농작물병해충관리시스템) OpenAPI 클라이언트.

엔드포인트: http://ncpms.rda.go.kr/npmsAPI/service
서비스코드:
    SVC01 : 병해충 목록 조회(검색)  — cropName 등으로 목록 + sickKey 획득
    SVC05 : 병 상세정보           — sickKey로 증상·발생조건·방제법·이미지

키 발급: ncpms.rda.go.kr → OpenAPI → 활용신청 → .env에 NCPMS_API_KEY 추가

주의: 응답은 XML이며 서비스/버전에 따라 태그명이 다를 수 있어, 후보 태그를
여러 개 시도하는 방어적 파서(_find/_find_all)를 사용한다. 키 연동 후 실호출로
정확한 태그명을 확정한다.
"""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

BASE_URL = "http://ncpms.rda.go.kr/npmsAPI/service"
DEFAULT_CROP = "토마토"


# ---------------------------------------------------------------------------
# 내부 유틸
# ---------------------------------------------------------------------------

def _get_key() -> str:
    key = os.getenv("NCPMS_API_KEY", "")
    if not key:
        raise RuntimeError(
            "NCPMS_API_KEY가 .env에 없습니다. "
            "ncpms.rda.go.kr(또는 data.go.kr)에서 병해충 검색 OpenAPI 활용신청 후 키를 추가하세요."
        )
    return key


def _call(params: dict) -> ET.Element:
    """NCPMS API 호출 → XML 루트 반환."""
    q = {"apiKey": _get_key(), **params}
    resp = requests.get(BASE_URL, params=q, timeout=10)
    resp.raise_for_status()
    try:
        return ET.fromstring(resp.content)
    except ET.ParseError as e:
        raise RuntimeError(f"NCPMS 응답 파싱 실패: {e} · 앞부분: {resp.text[:200]}")


def _find(elem: ET.Element, *tags: str) -> str:
    """후보 태그명 중 먼저 값이 있는 것의 텍스트 반환(없으면 '')."""
    for t in tags:
        node = elem.find(t)
        if node is not None and (node.text or "").strip():
            return node.text.strip()
    return ""


def _iter_items(root: ET.Element) -> list[ET.Element]:
    """목록 응답에서 개별 아이템 요소들을 찾음(다양한 래핑 대응)."""
    for path in ("./list/item", ".//item", "./body/items/item", ".//list"):
        found = root.findall(path)
        if found:
            return found
    return []


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------

def search_diseases(crop: str = DEFAULT_CROP, rows: int = 100, start: int = 1) -> list[dict]:
    """작물명으로 병해충 목록 조회(SVC01).

    Returns: [{"sickKey", "name", "crop", "kind", "thumb"}, ...]
    """
    root = _call({
        "serviceCode": "SVC01",
        "serviceType": "AA001",
        "cropName":    crop,
        "displayCount": rows,
        "startPoint":   start,
    })

    out: list[dict] = []
    for it in _iter_items(root):
        key = _find(it, "sickKey", "pestKey", "key")
        if not key:
            continue
        out.append({
            "sickKey": key,
            "name":    _find(it, "sickNameKor", "pestNameKor", "cntntsSj", "name"),
            "crop":    _find(it, "cropName", "crop") or crop,
            "kind":    _find(it, "divName", "sickCategory", "kind") or "병해충",
            "thumb":   _find(it, "oriImg", "thumbImg", "imageUrl", "img"),
        })
    return out


def disease_detail(sick_key: str, service_code: str = "SVC05") -> dict:
    """병 상세정보 조회(SVC05).

    SVC05는 content-type이 XML이지만 실제로는 JSON을 반환한다.
    Returns: {"name", "crop", "symptoms", "condition", "prevention", "chemical", "images"}
    """
    key = _get_key()
    resp = requests.get(BASE_URL, params={"apiKey": key, "serviceCode": service_code, "sickKey": sick_key}, timeout=10)
    resp.raise_for_status()

    # SVC05 실제 응답은 JSON (content-type 헤더 무시)
    try:
        svc = resp.json().get("service", {})
    except ValueError:
        # JSON 파싱 실패 시 XML 폴백
        root = ET.fromstring(resp.content)
        node = _iter_items(root)[0] if _iter_items(root) else root
        return {
            "name":       _find(node, "sickNameKor", "name"),
            "crop":       _find(node, "cropName"),
            "symptoms":   _find(node, "symptoms"),
            "condition":  _find(node, "developmentCondition"),
            "prevention": _find(node, "preventionMethod"),
            "chemical":   "",
            "images":     [],
        }

    images: list[str] = []
    for img in svc.get("imageList", []):
        for field in ("oriImg", "thumbImg"):
            url = (img.get(field) or "").strip()
            if url.startswith("http"):
                images.append(url)

    return {
        "name":       svc.get("sickNameKor", ""),
        "crop":       svc.get("cropName", ""),
        "symptoms":   svc.get("symptoms", ""),
        "condition":  svc.get("developmentCondition", ""),
        "prevention": svc.get("preventionMethod", ""),
        "chemical":   svc.get("chemicalPrvnbeMth", ""),
        "images":     list(dict.fromkeys(images))[:6],
    }


def has_key() -> bool:
    """API 키 설정 여부(존재만 확인, 값 노출 안 함)."""
    return bool(os.getenv("NCPMS_API_KEY", ""))


if __name__ == "__main__":
    print("=== NCPMS 토마토 병해충 목록 테스트 ===")
    try:
        lst = search_diseases("토마토", rows=10)
        print(f"목록 {len(lst)}건")
        for d in lst[:5]:
            print(" ", d["sickKey"], d["kind"], d["name"])
        if lst:
            det = disease_detail(lst[0]["sickKey"])
            print("상세:", det["name"], "| 증상:", det["symptoms"][:40], "| 방제:", det["prevention"][:40])
    except Exception as e:
        print("ERR", type(e).__name__, e)
