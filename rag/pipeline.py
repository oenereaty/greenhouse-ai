"""RAG pipeline: 지식베이스(md/pdf) 로딩, BGE-M3 임베딩, ChromaDB 검색.

BI2026(온실 진단 앱)에서 이식 — OpenAI 임베딩 대신 로컬 BGE-M3(CPU) 사용,
Claude API 대신 로컬 Ollama 사용 (agent/agent.py 참고).
"""
import json
import math
import re
import yaml
import requests
from datetime import datetime
from pathlib import Path

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
from pypdf import PdfReader

BASE_DIR = Path(__file__).parent.parent
CHROMA_DIR = str(BASE_DIR / "chroma_db")
DECISIONS_FILE = BASE_DIR / "decisions.json"
KNOWLEDGE_BASE_DIR = BASE_DIR / "knowledge_base"
COLLECTION_NAME = "greenhouse"
OLLAMA_URL = "http://localhost:11434/api/generate"

# ---------------------------------------------------------------------------
# Embedding function (BGE-M3, CPU, 무료·오프라인)
# ---------------------------------------------------------------------------

def _make_ef():
    return SentenceTransformerEmbeddingFunction(
        model_name="BAAI/bge-m3",
        device="cpu",
        normalize_embeddings=True,
    )

# ---------------------------------------------------------------------------
# VPD calculation (Magnus formula)
# ---------------------------------------------------------------------------

def calc_vpd(temp_c: float, rh_percent: float) -> float:
    """Temperature(℃) + RH(%) → VPD(kPa) via Magnus formula."""
    es = 0.6108 * math.exp(17.27 * temp_c / (temp_c + 237.3))
    return round(es * (1 - rh_percent / 100), 3)

# ---------------------------------------------------------------------------
# Document loading & chunking
# ---------------------------------------------------------------------------

def _parse_frontmatter(text: str):
    if not text.startswith("---"):
        return {}, text
    end = text.find("---", 3)
    if end == -1:
        return {}, text
    fm = yaml.safe_load(text[3:end].strip()) or {}
    return fm, text[end + 3:].strip()

def _section_meta_map(fm: dict) -> dict:
    return {c["section"]: c for c in fm.get("chunks", []) if "section" in c}

def _split_by_h2(body: str) -> list[tuple[str, str]]:
    """Split markdown body by ## headers. Returns [(header, content), ...]."""
    parts = re.split(r"^##\s+(.+)$", body, flags=re.MULTILINE)
    if len(parts) < 3:
        return [("", body)]
    result = []
    for i in range(1, len(parts) - 1, 2):
        result.append((parts[i].strip(), parts[i + 1].strip()))
    return result

def load_chunks() -> list[dict]:
    """knowledge_base/ 아래 모든 md/pdf 파일을 {text, metadata} 청크로 반환."""
    chunks = []

    for md_path in sorted(KNOWLEDGE_BASE_DIR.glob("*.md")):
        text = md_path.read_text(encoding="utf-8")
        fm, body = _parse_frontmatter(text)
        sec_map = _section_meta_map(fm)
        for section, content in _split_by_h2(body):
            if not content.strip():
                continue
            sec_info = sec_map.get(section, {})
            meta = {
                "source_file": md_path.name,
                "variable": str(fm.get("variable", "")),
                "section": section,
                "direct_control_rule": str(sec_info.get("direct_control_rule", False)),
                "authority": str(sec_info.get("authority", "")),
                "reliability": str(sec_info.get("reliability", "")),
                "use_for": str(sec_info.get("use_for", "")),
            }
            chunks.append({"text": content, "metadata": meta})

    pdf_raw = list(KNOWLEDGE_BASE_DIR.rglob("*.pdf")) + list(KNOWLEDGE_BASE_DIR.rglob("*.PDF"))
    pdf_files = list({p.resolve(): p for p in pdf_raw if not p.name.startswith(".")}.values())
    for pdf_path in pdf_files:
        chunks.extend(_load_pdf_chunks(pdf_path))

    return chunks


def _load_pdf_chunks(pdf_path: Path, chunk_size: int = 800, overlap: int = 100) -> list[dict]:
    """Parse a PDF and split into overlapping text chunks.

    Tries pymupdf first (better Korean support), falls back to pypdf.
    Scanned image-only PDFs produce no text and are skipped gracefully.
    """
    full_text = ""

    try:
        import fitz  # pymupdf
        doc = fitz.open(str(pdf_path))
        full_text = "\n".join(page.get_text() for page in doc)
    except ImportError:
        pass
    except Exception as e:
        print(f"[RAG] pymupdf 실패 {pdf_path.name}: {e}")

    if not full_text.strip():
        try:
            reader = PdfReader(str(pdf_path))
            full_text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as e:
            print(f"[RAG] pypdf 실패 {pdf_path.name}: {e}")
            return []

    full_text = re.sub(r"\n{3,}", "\n\n", full_text).strip()
    if not full_text:
        print(f"[RAG] 스캔 PDF (텍스트 없음) 건너뜀: {pdf_path.name} — OCR 필요")
        return []

    words = full_text.split()
    chunks = []
    start = 0
    idx = 0
    while start < len(words):
        end = start + chunk_size
        chunk_text = " ".join(words[start:end])
        chunks.append({
            "text": chunk_text,
            "metadata": {
                "source_file": pdf_path.name,
                "variable": "pdf",
                "section": f"chunk_{idx}",
                "direct_control_rule": "False",
                "authority": pdf_path.stem,
                "reliability": "pdf",
                "use_for": "reference",
            },
        })
        start += chunk_size - overlap
        idx += 1

    print(f"[RAG] PDF 로드: {pdf_path.name} → {len(chunks)}개 청크")
    return chunks

# ---------------------------------------------------------------------------
# Vectorstore (ChromaDB 1.x direct API)
# ---------------------------------------------------------------------------

def build_vectorstore(force_rebuild: bool = False) -> chromadb.Collection:
    """Create or load persistent ChromaDB collection."""
    ef = _make_ef()
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    existing = {c.name for c in client.list_collections()}

    if COLLECTION_NAME in existing and not force_rebuild:
        col = client.get_collection(COLLECTION_NAME, embedding_function=ef)
        count = col.count()
        if count > 0:
            return col
        client.delete_collection(COLLECTION_NAME)

    if COLLECTION_NAME in existing:
        client.delete_collection(COLLECTION_NAME)

    col = client.create_collection(
        COLLECTION_NAME,
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},
    )
    chunks = load_chunks()
    col.add(
        documents=[c["text"] for c in chunks],
        metadatas=[c["metadata"] for c in chunks],
        ids=[f"chunk_{i}" for i in range(len(chunks))],
    )
    print(f"[RAG] 벡터스토어 생성 완료: {len(chunks)}개 청크")
    return col

def search(col: chromadb.Collection, query: str, n_results: int = 6) -> list[dict]:
    results = col.query(query_texts=[query], n_results=n_results)
    docs = []
    for text, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        docs.append({"text": text, "meta": meta, "distance": round(dist, 4)})
    return docs

def retrieve(query: str, k: int = 4) -> list[str]:
    """agent/agent.py의 tool_retrieve_knowledge용 간이 래퍼."""
    col = build_vectorstore()
    return [d["text"] for d in search(col, query, n_results=k)]

# ---------------------------------------------------------------------------
# LLM (Ollama direct HTTP)
# ---------------------------------------------------------------------------

PROMPT_TEMPLATE = """\
당신은 토마토 PO필름 온실 관리를 지원하는 농업 의사결정 도우미입니다.
주어진 RAG 문서를 바탕으로 현재 센서 상태를 진단하고 조치를 안내합니다.

[규칙]
- direct_control_rule=True 문서만 제어 판단 기준으로 사용
- direct_control_rule=False (생리근거) 문서는 "생리적 배경"으로만 인용, 제어 임계값 사용 금지
- VPD는 참고값으로만, 단일 임계값 제어 기준 금지
- 환기 판단 시 외기 조건을 반드시 반영할 것
- 응답 형식 엄수

현재 온실 내부 센서값:
- 온도: {temp}℃
- 상대습도: {rh}%
- CO2: {co2} ppm
- 일사량: {solar} W/m²
- VPD (계산값): {vpd} kPa

{outdoor_section}참고 문서 ({n_docs}건):
{context}

---
아래 형식으로 한국어로 답변하세요:

[현재 상태]
(온실 내부 센서값 요약 + VPD 해석{outdoor_hint})

[진단]
- 온도: (적정/주의/위험) — 근거
- 습도·VPD: (적정/주의/위험) — 근거
- CO2: (적정/주의/위험) — 근거
- 일사·환기: (적정/부족/과다) — 일사량 및 외기 조건 반영한 근거

[조치]
(현재 상태 기준 구체적 권고 조치)
⚠️ 이 조치는 현재 센서값 기반 반응형 판단이며, 1~2시간 후 예측이 아닙니다.

[근거]
(사용한 문서 출처 명시)

[주의]
- 센서 이상 가능성
- 품종·생육단계 미확인 시 임계값 오차 가능
- 자동제어 전 현장 확인 필요
"""

def _format_context(docs: list[dict]) -> str:
    parts = []
    for i, d in enumerate(docs, 1):
        m = d["meta"]
        grade = "A등급(제어기준)" if m.get("direct_control_rule") == "True" else "C등급(설명전용)"
        parts.append(
            f"[문서{i}] {m.get('source_file')} / {m.get('section')} / {grade} / 출처: {m.get('authority')}\n"
            f"{d['text'][:600]}"
        )
    return "\n\n".join(parts)

def call_ollama(prompt: str, model: str = "gemma3:12b", timeout: int = 120) -> str:
    resp = requests.post(
        OLLAMA_URL,
        json={"model": model, "prompt": prompt, "stream": False},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json().get("response", "").strip()

def diagnose(
    temp: float,
    rh: float,
    co2: float,
    solar: float,
    col: chromadb.Collection,
    model: str = "gemma3:12b",
    outdoor: dict | None = None,
) -> dict:
    vpd = calc_vpd(temp, rh)
    query = f"온도 {temp}℃ 습도 {rh}% CO2 {co2}ppm 일사 {solar}W/m² VPD {vpd}kPa 토마토 온실 진단 조치 환기판단"
    docs = search(col, query, n_results=6)

    if outdoor:
        ot, oh = outdoor["outdoor_temp"], outdoor["outdoor_rh"]
        ov = outdoor["outdoor_vpd"]
        ws = round(outdoor["wind_speed"], 1)
        rn = outdoor.get("precipitation", 0)
        wf = outdoor.get("wf_kor") or outdoor.get("sky_label", "—")
        obs = outdoor.get("obs_time", "")
        grid = f"격자 {outdoor.get('grid_x')},{outdoor.get('grid_y')}"
        outdoor_section = (
            f"외기 조건 (KMA 동네예보 / {wf} / {grid} / {obs}):\n"
            f"- 외기온도: {ot}℃  외기습도: {oh}%  외기VPD: {ov} kPa\n"
            f"- 풍속: {ws} m/s ({outdoor.get('wind_dir_kor','')})  강수: {rn} mm\n"
            f"- 실내외 온도차: {temp - ot:+.1f}℃ "
            f"({'환기 냉각 가능' if temp > ot else '외기가 더 뜨거움 → 차광·포그 우선'})\n\n"
        )
        outdoor_hint = " + 외기 조건 요약"
    else:
        outdoor_section = ""
        outdoor_hint = ""

    prompt = PROMPT_TEMPLATE.format(
        temp=temp, rh=rh, co2=co2, solar=solar, vpd=vpd,
        n_docs=len(docs),
        context=_format_context(docs),
        outdoor_section=outdoor_section,
        outdoor_hint=outdoor_hint,
    )
    response = call_ollama(prompt, model=model)

    sources = [
        f"{d['meta'].get('source_file')}##{d['meta'].get('section')}"
        for d in docs
        if d["meta"].get("direct_control_rule") == "True"
    ]
    record = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "sensor_input": {"temp": temp, "rh": rh, "co2": co2, "solar": solar},
        "vpd_calculated": vpd,
        "outdoor": outdoor,
        "llm_response": response,
        "sources": sources,
        "farmer_action": None,
    }
    _save_decision(record)
    return {"vpd": vpd, "response": response, "record": record}

CHAT_PROMPT_TEMPLATE = """\
당신은 토마토 PO필름 온실 관리를 지원하는 농업 의사결정 도우미입니다.
현재 온실 센서값과 지식베이스를 바탕으로 농가 질문에 한국어로 간결하게 답변합니다.

현재 온실 내부 센서값:
- 온도: {temp}℃  습도: {rh}%  CO2: {co2}ppm  일사: {solar}W/m²  VPD: {vpd}kPa
{outdoor_section}
참고 문서 ({n_docs}건):
{context}

대화 기록:
{history}

농가 질문: {question}

실용적이고 간결하게 답변하세요. 근거 문서가 있으면 출처(파일명·섹션)를 밝히세요.
"""

def chat_query(
    question: str,
    col: "chromadb.Collection",
    sensor: dict,
    history: list,
    model: str = "gemma3:12b",
    outdoor: dict | None = None,
) -> str:
    """Answer a free-form question using RAG + current sensor context."""
    vpd = calc_vpd(float(sensor["temp"]), float(sensor["rh"]))
    docs = search(col, question, n_results=4)

    history_text = ""
    for msg in history[-6:]:
        role = "농가" if msg["role"] == "user" else "도우미"
        history_text += f"{role}: {msg['content']}\n"

    if outdoor:
        outdoor_section = (
            f"외기 조건: {outdoor['outdoor_temp']}℃ / {outdoor['outdoor_rh']}% / "
            f"풍속 {round(outdoor['wind_speed'], 1)}m/s ({outdoor.get('wind_dir_kor', '')}) / "
            f"{outdoor.get('wf_kor', '—')}\n"
        )
    else:
        outdoor_section = ""

    prompt = CHAT_PROMPT_TEMPLATE.format(
        temp=sensor["temp"], rh=sensor["rh"], co2=sensor["co2"],
        solar=sensor.get("solar", 0), vpd=vpd,
        outdoor_section=outdoor_section,
        n_docs=len(docs),
        context=_format_context(docs),
        history=history_text or "(없음)",
        question=question,
    )
    return call_ollama(prompt, model=model)

# ---------------------------------------------------------------------------
# Decision log (LLM 진단 기록)
# ---------------------------------------------------------------------------

def _save_decision(record: dict):
    records = load_decisions()
    records.append(record)
    DECISIONS_FILE.write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )

def load_decisions() -> list:
    if not DECISIONS_FILE.exists():
        return []
    try:
        return json.loads(DECISIONS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []

# ---------------------------------------------------------------------------
# CLI: build index + quick test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== RAG 파이프라인 테스트 ===\n")

    print("1. 문서 로딩 테스트")
    chunks = load_chunks()
    print(f"   총 청크 수: {len(chunks)}")
    for c in chunks:
        dcr = c["metadata"]["direct_control_rule"]
        print(f"   [{c['metadata']['source_file']}] {c['metadata']['section']} — direct_control_rule={dcr}")

    print("\n2. VPD 계산 테스트")
    for t, rh in [(28, 65), (32, 80), (20, 90)]:
        v = calc_vpd(t, rh)
        print(f"   {t}℃ / {rh}% → VPD {v} kPa")

    print("\n3. 임베딩 + 벡터스토어 구축 (첫 실행 시 BGE-M3 다운로드 수 분 소요)")
    col = build_vectorstore()
    print(f"   컬렉션 청크 수: {col.count()}")

    print("\n4. 검색 테스트")
    queries = [
        "지금 온실이 28도인데 어떻게 해야 해?",
        "야간 온도가 낮으면 어떤 문제가 생겨?",
        "고온일 때 착과율이 왜 떨어져?",
    ]
    for q in queries:
        results = search(col, q, n_results=1)
        r = results[0]
        print(f"\n   질문: {q}")
        print(f"   → [{r['meta']['source_file']}] {r['meta']['section']} (distance={r['distance']})")
        print(f"   → {r['text'][:100]}...")

    print("\n완료. Streamlit 앱 실행: streamlit run ui/app.py")
