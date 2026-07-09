"""NCPMS(국가농작물병해충관리시스템) API → knowledge_base/ncpms_병해도감.md 생성.

search_diseases()로 토마토 병해충 목록을 받고, 각 항목을 disease_detail()로 조회해
증상/발생조건/방제법을 RAG 프레임워크(YAML frontmatter + ## 섹션) 형식으로 저장한다.
정부 공식 DB이므로 authority=NCPMS로 표기하되, 환경 제어 임계값이 아닌 진단·방제
참고 정보이므로 direct_control_rule은 항상 false(C등급 설명전용)로 둔다.
"""
import re
import time
from pathlib import Path

from tools.ncpms_client import disease_detail, search_diseases

BASE_DIR = Path(__file__).parent.parent
OUT_MD = BASE_DIR / "knowledge_base" / "ncpms_병해도감.md"

AUTHORITY = "농촌진흥청 국가농작물병해충관리시스템(NCPMS)"


def _clean(html: str) -> str:
    """<br/> → 줄바꿈, 나머지 HTML 태그 제거."""
    if not html:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


def _disease_section(detail: dict) -> str | None:
    name = detail.get("name", "").strip()
    symptoms = _clean(detail.get("symptoms", ""))
    condition = _clean(detail.get("condition", ""))
    prevention = _clean(detail.get("prevention", ""))
    chemical = _clean(detail.get("chemical", ""))

    if not name or not symptoms:
        return None

    parts = [f"## {name}", "", f"**증상**\n{symptoms}"]
    if condition:
        parts.append(f"**발생조건**\n{condition}")
    if prevention:
        parts.append(f"**방제법**\n{prevention}")
    if chemical:
        parts.append(f"**등록농약**\n{chemical}")
    return "\n\n".join(parts)


def main() -> None:
    items = search_diseases("토마토", rows=200)
    print(f"[NCPMS] 토마토 병해충 {len(items)}건 조회됨")

    sections: list[str] = []
    names: list[str] = []
    for item in items:
        sick_key = item.get("sickKey")
        if not sick_key:
            continue
        detail = disease_detail(sick_key)
        section = _disease_section(detail)
        if section is None:
            print(f"  스킵(증상 정보 없음): {item.get('name')}")
            continue
        sections.append(section)
        names.append(detail.get("name", item.get("name", "")))
        time.sleep(0.2)

    chunks_yaml = "\n".join(
        f"  - section: {n}\n"
        f"    topic: disease_diagnosis\n"
        f"    authority: {AUTHORITY}\n"
        f"    source_type: government_db\n"
        f"    use_for: diagnosis_reference\n"
        f"    direct_control_rule: false\n"
        f"    reliability: high"
        for n in names
    )

    frontmatter = (
        "---\n"
        "crop: tomato\n"
        "variable: disease\n"
        f"chunks:\n{chunks_yaml}\n"
        "---\n\n"
    )

    OUT_MD.write_text(frontmatter + "\n\n".join(sections) + "\n", encoding="utf-8")
    print(f"[NCPMS] {len(names)}개 병해 저장 완료 → {OUT_MD}")

    from rag.pipeline import build_vectorstore
    build_vectorstore(force_rebuild=True)
    print("[NCPMS] 벡터스토어 재빌드 완료")


if __name__ == "__main__":
    main()
