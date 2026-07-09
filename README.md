# 🍅 Greenhouse AI — 온실 토마토 의사결정 지원 시스템

LLM + RAG + MCP 도구를 결합한 한국 온실 토마토 특화 AI 어드바이저.
기상청 API + 온실 센서 실시간 데이터를 기반으로 착과 실패·병해를 사전 예측하고,
KAMIS 도매가격 기반 판매 방향(출하/직거래)을 제안하며 주간 자동 리포트를 생성합니다.

LLM과 임베딩은 전부 **로컬**(Ollama + BGE-M3)에서 동작합니다 — 클라우드 API 비용 없음.

## 아키텍처

```
React UI (frontend/, Vite)
  └── FastAPI backend (backend/main.py)
        ├── REST API routers (environment/growth/weather/prices/control/chat/diary)
        ├── background jobs (backend/jobs.py)
        └── scheduler (backend/scheduler.py)

LLM (로컬 Ollama, gemma4:12b)
  ├── MCP Tools (agent/server.py, 실시간)
  │     ├── 온실 센서 / 시뮬레이터 (tools/simulator.py, tools/sensor_client.py)
  │     ├── 생육 데이터 CSV (tools/growth_data.py)
  │     └── 진단 이력 (rag/pipeline.py)
  ├── 개별 계산 도구 (tools/)
  │     ├── VPD 계산기 (vpd_calculator.py)
  │     ├── GDD 누적기 (gdd_calculator.py)
  │     ├── 병해 위험도 모델 (disease_risk.py)
  │     ├── 기상청 단기예보 (kma_api.py) / AWS 실시간관측 (kma_client.py)
  │     └── KAMIS 도매가격 + 판매 방향 제안 (kamis_client.py, price_advisor.py)
  └── RAG (rag/pipeline.py, BGE-M3 임베딩 + ChromaDB)
        └── knowledge_base/ (작물생리학 md + 농진청 재배 매뉴얼 PDF)

ui/app.py — 레거시 Streamlit 대시보드 (React 이전 완료 전까지 병행 유지)
```

## 설치

```bash
conda create -n greenhouse-ai python=3.11 -y
conda activate greenhouse-ai
pip install -r requirements.txt
cp .env.example .env  # API 키 입력
```

### React 프론트엔드

```bash
cd frontend
npm install
```

### 로컬 LLM (Ollama)

```bash
brew install ollama
ollama serve &
ollama pull gemma4:12b
```

## 환경변수 (.env)

`.env.example` 참고. 주요 항목:

```
KMA_API_KEY=기상청_API_Hub_키       # AWS 실시간 관측
GREENHOUSE_NX=60                    # 기상청 단기예보 격자좌표
GREENHOUSE_NY=127
KAMIS_API_KEY=KAMIS_키              # 토마토 도매가격
KAMIS_API_ID=KAMIS_ID
EMAIL_FROM=...                      # Gmail 경보 발송
EMAIL_APP_PASSWORD=...
```

## 실행

```bash
# 1. 지식베이스 인덱싱 (최초 1회, 첫 실행 시 BGE-M3 다운로드로 수 분 소요)
python -m rag.pipeline

# 2. FastAPI 백엔드 (레포 루트에서 실행)
uvicorn backend.main:app --reload

# 3. React 프론트엔드 (다른 터미널)
cd frontend
npm run dev

# 4. MCP 에이전트 CLI 대화
python -m agent.agent "오늘 온실 상태 점검해줘"

# 5. 주간 리포트 생성
python -m reports.weekly_report
```

### 레거시 Streamlit 실행

React 이전이 완료될 때까지 기존 Streamlit UI도 유지합니다.

```bash
streamlit run ui/app.py
```

## 도구 개별 테스트

```bash
python tools/vpd_calculator.py
python tools/gdd_calculator.py
python tools/disease_risk.py
python tools/kma_api.py
python tools/kma_client.py
python tools/kamis_client.py
python tools/sensor_client.py
```

## 백테스트 (가격 계절성 분석)

```bash
python scripts/backtest_price.py
```

## 프로젝트 구조

```
greenhouse-ai/
├── frontend/               # React + TypeScript + Vite UI
│   └── src/
├── backend/                # FastAPI API 서버
│   ├── main.py
│   ├── jobs.py
│   └── routers/
├── tools/                  # 계산·API 도구 (각각 독립 실행 가능)
│   ├── vpd_calculator.py
│   ├── gdd_calculator.py
│   ├── disease_risk.py
│   ├── kma_api.py          # 기상청 단기예보 (3일)
│   ├── kma_client.py       # 기상청 AWS 실시간관측 + 동네예보
│   ├── kamis_client.py     # KAMIS 도매가격
│   ├── price_advisor.py    # 계절성 기반 판매 방향 제안
│   ├── sensor_client.py    # 실 IoT API 또는 시뮬레이션
│   ├── simulator.py        # MCP 서버용 센서 시뮬레이터
│   ├── growth_data.py      # 생육 데이터 CSV
│   ├── advisor.py          # 조치 제안 생성 + 이상 감지
│   ├── notifier.py         # 이메일 경보
│   └── sensor_simulator.py # (참고용, 미사용)
├── rag/
│   └── pipeline.py         # 문서 로드 → 청킹 → BGE-M3 임베딩 → ChromaDB 검색 + LLM 진단
├── agent/
│   ├── agent.py            # MCP ↔ Ollama 브리지 (도구 호출 에이전트)
│   └── server.py           # MCP 서버 (센서·생육·진단이력 도구 노출)
├── knowledge_base/
│   ├── tomato_physiology.md
│   ├── 01_temperature.md ~ 04_ventilation.md
│   └── *.pdf                # 농진청 재배 매뉴얼 등 참고자료
├── ui/
│   ├── app.py               # 레거시 Streamlit 대시보드
│   └── advisor.py           # tools.advisor 호환 wrapper
├── reports/
│   └── weekly_report.py
└── scripts/
    └── backtest_price.py     # KAMIS 가격 계절성 백테스트
```
