# 🍅 Greenhouse AI — 온실 토마토 의사결정 지원 시스템

LLM + RAG + MCP 도구를 결합한 한국 온실 토마토 특화 AI 어드바이저.
기상청 API + 온실 센서 실시간 데이터를 기반으로 착과 실패·병해를 사전 예측하고 주간 자동 리포트를 생성합니다.

## 아키텍처

```
LLM (Claude)
  ├── MCP Tools (실시간)
  │     ├── 온실 센서 / 시뮬레이터
  │     ├── 기상청 KMA API
  │     ├── VPD 계산기
  │     ├── GDD 누적기
  │     └── 병해 위험도 모델
  └── RAG (지식베이스)
        ├── 토마토 작물생리학
        ├── 농진청 재배 매뉴얼 (PDF)
        └── 병해충 동정 가이드
```

## 설치

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # API 키 입력
```

## 환경변수 (.env)

```
KMA_API_KEY=기상청_API_키
ANTHROPIC_API_KEY=Claude_API_키
OPENAI_API_KEY=임베딩용_OpenAI_키
GREENHOUSE_NX=60
GREENHOUSE_NY=127
```

## 실행

```bash
# 1. 지식베이스 인덱싱 (최초 1회)
python -m rag.pipeline

# 2. 에이전트 대화
python -m agent.agent

# 3. 주간 리포트 생성
python -m reports.weekly_report
```

## 도구 개별 테스트

```bash
python tools/vpd_calculator.py
python tools/gdd_calculator.py
python tools/kma_api.py
python tools/sensor_simulator.py
```

## 프로젝트 구조

```
greenhouse-ai/
├── tools/                  # MCP 도구들 (각각 독립 실행 가능)
│   ├── vpd_calculator.py
│   ├── gdd_calculator.py
│   ├── disease_risk.py
│   ├── kma_api.py
│   └── sensor_simulator.py
├── rag/
│   └── pipeline.py         # 문서 로드 → 청킹 → 벡터 DB
├── agent/
│   └── agent.py            # LangChain Tool Calling 에이전트
├── knowledge_base/
│   └── tomato_physiology.md
├── reports/
│   └── weekly_report.py
└── data/
    └── raw/                # PDF 원본 (gitignore)
```
