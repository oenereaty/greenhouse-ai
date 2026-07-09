"""RAG pipeline: 지식베이스(md/pdf) 로딩, BGE-M3 임베딩, ChromaDB + MMR 검색.

BI2026(온실 진단 앱)에서 이식 — OpenAI 임베딩 대신 로컬 BGE-M3(CPU) 사용,
Claude API 대신 로컬 Ollama 사용 (agent/agent.py 참고).
"""
import json
import math
import re
import yaml
import requests
import numpy as np
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
# Embedding function (BGE-M3, CPU, 무료·오프라인) — 모듈 단위 싱글턴
# ---------------------------------------------------------------------------

_EF: "SentenceTransformerEmbeddingFunction | None" = None


def _make_ef() -> "SentenceTransformerEmbeddingFunction":
    return SentenceTransformerEmbeddingFunction(
        model_name="BAAI/bge-m3",
        device="cpu",
        normalize_embeddings=True,
    )


def _get_ef() -> "SentenceTransformerEmbeddingFunction":
    """모델 로딩 비용을 최초 1회로 제한하는 싱글턴 getter."""
    global _EF
    if _EF is None:
        _EF = _make_ef()
    return _EF


# ---------------------------------------------------------------------------
# OCR (EasyOCR) — 스캔 PDF 전용 싱글턴
# ---------------------------------------------------------------------------

_OCR_READER = None


def _get_ocr_reader():
    """EasyOCR 리더 싱글턴 — 첫 호출 시 모델 다운로드(약 200 MB, 이후 캐시)."""
    global _OCR_READER
    if _OCR_READER is None:
        import easyocr
        _OCR_READER = easyocr.Reader(["ko", "en"], gpu=False, verbose=False)
    return _OCR_READER


def _ocr_pdf_text(pdf_path: Path) -> str:
    """pymupdf로 각 페이지를 이미지 렌더링 후 EasyOCR로 텍스트 추출."""
    try:
        import fitz
        ocr = _get_ocr_reader()
        doc = fitz.open(str(pdf_path))
        pages_text = []
        for page_num, page in enumerate(doc, 1):
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # 144 DPI
            img_bytes = pix.tobytes("png")
            results = ocr.readtext(img_bytes, detail=0, paragraph=True)
            pages_text.append("\n".join(results))
            print(f"[RAG] OCR: {pdf_path.name} {page_num}/{len(doc)}p")
        return "\n\n".join(pages_text)
    except Exception as e:
        print(f"[RAG] OCR 실패 {pdf_path.name}: {e}")
        return ""

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


# 기관 발간 자료 중 특정 생육단계·시기에 한정되지 않고(=연중 상시 적용 가능)
# 온도·습도·CO2 등 구체적 제어 임계값을 담은 PDF만 direct_control_rule=True로
# 승격한다(2026-07 내용 검토 확인). 나머지 PDF(대학 강의자료, 농약 카탈로그,
# OCR 품질이 낮은 문서, 특정 생육단계/월에만 해당하는 가이드)는 임계값을
# 잘못 적용할 위험이 있어 기존대로 배경 설명(C등급)으로만 인용한다.
_TRUSTED_PDF_AUTHORITY: dict[str, str] = {
    "토마토 스마트 온실 관리 매뉴얼.PDF": "농촌진흥청 국립원예특작과학원 (2017)",
    "토마토 환경관리 가이드라인 2018 자료.pdf": "스마트 온실환경관리 가이드라인 (2018)",
}


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
        print(f"[RAG] 스캔 PDF 감지 → OCR 시도: {pdf_path.name}")
        full_text = _ocr_pdf_text(pdf_path)
        if not full_text:
            print(f"[RAG] OCR 실패 — 건너뜀: {pdf_path.name}")
            return []
        source_label = "pdf_ocr"
    else:
        source_label = "pdf"

    trusted_authority = _TRUSTED_PDF_AUTHORITY.get(pdf_path.name)

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
                "variable": source_label,
                "section": f"chunk_{idx}",
                "direct_control_rule": "True" if trusted_authority else "False",
                "authority": trusted_authority or pdf_path.stem,
                "reliability": "high" if trusted_authority else source_label,
                "use_for": "reference",
            },
        })
        start += chunk_size - overlap
        idx += 1

    label = "OCR PDF" if source_label == "pdf_ocr" else "PDF"
    print(f"[RAG] {label} 로드: {pdf_path.name} → {len(chunks)}개 청크")
    return chunks

# ---------------------------------------------------------------------------
# Vectorstore (ChromaDB 1.x direct API)
# ---------------------------------------------------------------------------

def build_vectorstore(force_rebuild: bool = False) -> chromadb.Collection:
    """Create or load persistent ChromaDB collection."""
    ef = _get_ef()
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

def _mmr_select(
    query_emb: list[float],
    candidates: list[dict],
    k: int,
    lambda_: float = 0.6,
) -> list[dict]:
    """Greedy MMR: λ·sim(q,d) - (1-λ)·max_sim(d, 이미 선택된 문서).

    lambda_가 클수록 관련성 우선, 작을수록 다양성 우선.
    """
    if len(candidates) <= k:
        return candidates

    q = np.array(query_emb, dtype=np.float32)
    embs = np.array([c["_emb"] for c in candidates], dtype=np.float32)

    q_norm = q / (np.linalg.norm(q) + 1e-10)
    norms = np.linalg.norm(embs, axis=1, keepdims=True) + 1e-10
    embs_norm = embs / norms

    rel = embs_norm @ q_norm  # (N,) 관련성 점수

    selected: list[int] = []
    remaining = list(range(len(candidates)))

    for _ in range(k):
        if not remaining:
            break
        if not selected:
            best = remaining[int(np.argmax(rel[remaining]))]
        else:
            sel_embs = embs_norm[selected]
            scores = [
                lambda_ * float(rel[i])
                - (1 - lambda_) * float(np.max(embs_norm[i] @ sel_embs.T))
                for i in remaining
            ]
            best = remaining[int(np.argmax(scores))]
        selected.append(best)
        remaining.remove(best)

    return [candidates[i] for i in selected]


def search(
    col: chromadb.Collection,
    query: str,
    n_results: int = 6,
    fetch_k: int = 20,
    use_mmr: bool = True,
    lambda_mmr: float = 0.6,
) -> list[dict]:
    """cosine으로 fetch_k개 후보를 뽑고 MMR로 다양성 확보한 n_results개 반환."""
    count = col.count()
    if count == 0:
        return []
    actual_n = min(n_results, count)
    actual_fetch = min(max(fetch_k, n_results), count)

    if use_mmr and actual_fetch > actual_n:
        raw = col.query(
            query_texts=[query],
            n_results=actual_fetch,
            include=["documents", "metadatas", "distances", "embeddings"],
        )
        docs = [
            {"text": t, "meta": m, "distance": round(d, 4), "_emb": e}
            for t, m, d, e in zip(
                raw["documents"][0],
                raw["metadatas"][0],
                raw["distances"][0],
                raw["embeddings"][0],
            )
        ]
        q_emb = _get_ef()([query])[0]
        docs = _mmr_select(q_emb, docs, actual_n, lambda_=lambda_mmr)
        for doc in docs:
            doc.pop("_emb", None)
    else:
        raw = col.query(
            query_texts=[query],
            n_results=actual_n,
            include=["documents", "metadatas", "distances"],
        )
        docs = [
            {"text": t, "meta": m, "distance": round(d, 4)}
            for t, m, d in zip(
                raw["documents"][0],
                raw["metadatas"][0],
                raw["distances"][0],
            )
        ]

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
- 토마토 농가 제어 우선순위는 온도·습도 안정화가 1순위이고 CO2 관리는 그 다음
- 습도 90% 이상 또는 온도 28℃ 이상이면 CO2 시비보다 환기·순환·차광을 우선
- 단, 외기 습도도 높거나(예: 90% 이상) 강수 중이면 창을 크게 여는 단순 환기로는 실내 절대습도가
  낮아지지 않고 온도만 떨어져 결로·고습성 병해(잿빛곰팡이·잎곰팡이 등) 위험이 커질 수 있음 —
  이 경우 큰 폭 개방 환기 대신 순환팬 가동 + 제한적 환기 + 필요시 소폭 난방을 권할 것
- 환기가 필요한 상태에서는 CO2 시비를 권하지 말 것. 낮 시간(일사량 있는 시간대) CO2 하락은
  광합성 소비로 해석 가능
- CO2 시비는 온도·습도가 안정적이고 환기 개도를 낮게 유지할 수 있을 때만 검토
- CO2 시비 판단 시 반드시 현재 시각·일사량으로 광합성 가능 여부를 먼저 확인할 것. 일사량이 매우 낮거나
  (예: 30W/m² 미만) 야간 시간대라면 광합성이 거의 일어나지 않으므로 CO2가 낮아도 시비를 권하지 말 것.
  단, 야간 CO2 저하를 "작물 호흡" 때문이라고 설명하지 말 것 — 호흡은 야간에 CO2를 오히려 높이는
  방향이므로, 대기 수준(약 400ppm)보다 낮은 야간 CO2는 센서 오차·직전 환기·외기 유입 가능성으로
  설명할 것(광합성 소비로 설명하는 것은 일사량이 있는 낮 시간에만 해당)
- 온도가 적정 범위여도 습도가 위험 수준(90% 이상)이면 "현 상태 유지"라고만 하지 말고, 습도를
  낮추기 위한 순환·제한적 환기·난방 조치를 함께 제시할 것
- 환기 판단 시 외기 조건을 반드시 반영할 것
- 응답 형식 엄수
- 각 수치·판단·조치 뒤에 반드시 참고한 문서의 실제 파일명을 대괄호로 인용할 것
  (예: 차광 우선 [04_ventilation.md]). [근거1]처럼 번호로만 인용하지 말 것
- 참고 문서에서 직접 확인되지 않는 내용은 "문서에서 확인되지 않습니다" 명시
- '매우', '극심', '심각' 등 과장된 표현은 쓰지 말고 사실과 수치에 기반한 중립적 어조로 쓸 것

현재 시각: {now}

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
    for d in docs:
        m = d["meta"]
        grade = "A등급(제어기준)" if m.get("direct_control_rule") == "True" else "C등급(설명전용)"
        parts.append(
            f"[{m.get('source_file')}] / {m.get('section')} / {grade} / 출처: {m.get('authority')}\n"
            f"{d['text'][:600]}"
        )
    return "\n\n".join(parts)

def call_ollama(
    prompt: str,
    model: str = "gemma4:12b",
    timeout: int = 120,
    num_ctx: int = 8192,
    num_predict: int = 4096,
    max_attempts: int = 6,
) -> str:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        # Ollama's default context window (~2k tokens) silently truncates the long
        # RAG prompt (instructions + 6 retrieved docs). Pin a window large enough
        # for the retrieved context plus the answer.
        "options": {"num_ctx": num_ctx, "num_predict": num_predict},
    }
    # gemma4 still returns an empty completion for this prompt maybe a third of the
    # time even with a large context window, so retry a few times before failing.
    for _ in range(max_attempts):
        resp = requests.post(OLLAMA_URL, json=payload, timeout=timeout)
        resp.raise_for_status()
        response = resp.json().get("response", "").strip()
        if response:
            return response
    raise RuntimeError(
        f"Ollama returned an empty response after {max_attempts} attempts"
    )

def diagnose(
    temp: float,
    rh: float,
    co2: float,
    solar: float,
    col: chromadb.Collection,
    model: str = "gemma4:12b",
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
        now=datetime.now().strftime("%Y-%m-%d %H:%M (%a)"),
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
당신은 토마토 온실 관리를 지원하는 농업 의사결정 도우미입니다.
현재 온실 센서값과 지식베이스를 바탕으로 농가 질문에 한국어로 간결하게 답변합니다.
답변할 때 VPD·온도·CO₂ 등 수치 근거를 반드시 포함하고 구체적인 설정값을 제시하세요.
토마토 농가 제어 우선순위는 온도·습도 안정화가 1순위이고 CO₂ 관리는 그 다음입니다.
습도 90% 이상 또는 온도 28℃ 이상이면 CO₂ 시비보다 환기·순환·차광을 우선하고,
환기가 필요한 상태에서는 CO₂ 시비를 권하지 마세요.

현재 온실 내부 센서값:
- 온도: {temp}℃  습도: {rh}%  CO2: {co2}ppm  일사: {solar}W/m²  VPD: {vpd}kPa
{temp_analysis_section}{outdoor_section}
참고 문서 ({n_docs}건):
{context}

대화 기록:
{history}

농가 질문: {question}

실용적이고 간결하게 답변하세요.
각 사실·수치·조치 뒤에 참고한 문서의 실제 파일명을 대괄호로 인용하세요
(예: VPD 1.5 kPa 초과 시 기공 폐쇄 [02_vpd.md]). [근거3]처럼 번호로만 인용하지 마세요.
참고 문서에서 확인되지 않는 내용은 "문서에서 확인되지 않습니다"라고 명시하세요.
"""

def chat_query(
    question: str,
    col: "chromadb.Collection",
    sensor: dict,
    history: list,
    model: str = "gemma4:12b",
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

    day_avg  = sensor.get("day_avg_temp")
    rec_night = sensor.get("rec_night_temp")
    if day_avg and rec_night:
        temp_analysis_section = (
            f"오늘 주간 평균 온도: {day_avg}℃ → 권장 야간 설정 온도: {rec_night}℃ "
            f"(주야간 5℃ 차 기준)\n"
        )
    else:
        temp_analysis_section = ""

    prompt = CHAT_PROMPT_TEMPLATE.format(
        temp=sensor["temp"], rh=sensor["rh"], co2=sensor["co2"],
        solar=sensor.get("solar", 0), vpd=vpd,
        temp_analysis_section=temp_analysis_section,
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

def update_latest_decision_action(action: str, advice: dict | None = None) -> dict | None:
    """최신 LLM 판단 기록에 농장주 조치 응답을 반영."""
    records = load_decisions()
    if not records:
        return None

    latest = records[-1]
    if action == "y":
        label = "허용"
    elif action == "n":
        label = "거부"
    else:
        label = "직접 입력"

    recommendation = (advice or {}).get("recommendation") or (advice or {}).get("situation") or ""
    action_text = f"{label}: {recommendation}".strip()
    if action not in ("y", "n"):
        action_text = f"{label}: {action}"

    latest["farmer_action"] = action_text
    latest["farmer_action_at"] = datetime.now().isoformat(timespec="seconds")
    records[-1] = latest
    DECISIONS_FILE.write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return latest

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
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true", help="chroma_db 강제 재구축")
    args = ap.parse_args()

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
    col = build_vectorstore(force_rebuild=args.rebuild)
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
