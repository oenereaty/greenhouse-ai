# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

한국 온실 토마토 의사결정 지원 시스템. Streamlit 대시보드 + 로컬 LLM(Ollama + BGE-M3) + 외부 공공 API 클라이언트로 구성됩니다.

## Commands

```cmd
:: 앱 실행 (포트 8505)
streamlit run ui/app.py --server.port 8505

:: RAG 지식베이스 인덱싱 (최초 1회 — BGE-M3 약 1.5 GB 다운로드 및 PDF 청킹)
python -m rag.pipeline

:: MCP 에이전트 CLI (Ollama 실행 중이어야 함)
python -m agent.agent "오늘 온실 상태 점검해줘"

:: 각 도구 단독 테스트 (각 파일에 __main__ 블록 포함)
python tools/sensor_client.py
python tools/kma_api.py
python tools/kma_client.py
python tools/at_client.py
python tools/ncpms_client.py
python tools/vpd_calculator.py
python tools/gdd_calculator.py

:: 가격 백테스트
python scripts/backtest_price.py
```

### 앱 재시작 절차 (중요)

Streamlit은 `app.py`는 rerun마다 다시 읽지만 `import`된 하위 모듈은 `sys.modules` 캐시를 재사용합니다. `tools/`를 수정한 뒤에는 반드시 프로세스를 PID로 완전 종료해야 합니다.

```cmd
netstat -ano | findstr :8505
taskkill //F //PID <PID>
rd /s /q tools\__pycache__
streamlit run ui/app.py --server.port 8505
```

## Architecture

### 전체 흐름

```
ui/app.py (Streamlit 대시보드, 8탭)
  ├── tools/           외부 API 클라이언트 · 계산기 (각 독립 실행 가능)
  ├── rag/pipeline.py  BGE-M3 임베딩 → ChromaDB 검색 → Ollama LLM 진단
  ├── ui/advisor.py    Ollama gemma4:12b 실시간 조언 + 경보 판정
  └── agent/           MCP 서버 (FastMCP) — 도구를 Ollama에 노출
```

### 센서 데이터 계층

`tools/sensor_client.py`가 `file/전라북도_농가데이터셋_토마토.csv`(CP949 인코딩)에서 6월 20~28일 시간별 평균값을 읽어 현재 시각에 맞춰 반환합니다. CSV에 해당 시각이 없으면 `generate_mock()`으로 자동 폴백합니다. 반환값에 `"solar_is_mock"` 플래그가 있어 UI가 실측/시뮬레이션을 구분합니다.

### 외부 API 의존성

| 모듈 | 서비스 | 환경변수 | 비고 |
|------|--------|----------|------|
| `kma_client.py` | 기상청 AWS 실시간 관측 | `KMA_API_KEY` | apihub.kma.go.kr 발급 |
| `kma_api.py` | 기상청 단기예보 3일 | `KMA_API_KEY` | data.go.kr 발급 (별도 활용신청) |
| `at_client.py` | aT 공판장 경락가격 | `AT_API_KEY` | **30일치만 보관** |
| `ncpms_client.py` | NCPMS 병해충 도감 | `NCPMS_API_KEY` | SVC01=XML / SVC05=**JSON** (content-type 무시) |
| `naver_news.py` | 네이버 뉴스 검색 (시장 동향 브리핑) | `NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET` | developers.naver.com 앱 등록 필요 |

> `KMA_API_KEY`는 같은 변수명이지만 apihub.kma.go.kr(AWS관측)과 data.go.kr(단기예보)에 각각 별도 활용신청이 필요합니다.

### 가격 탭 구조

`at_client.py`의 두 함수가 핵심입니다.
- `fetch_auction_ledger()` — 경매현황 서브탭: 12컬럼 원장 + 최소/평균/최대 통계
- `fetch_price_range_by_markets()` — 경매비교 서브탭: 시장별 시계열(익산·전주)
- `naver_news.fetch_price_factor_articles()` + Ollama — 시장 동향 브리핑 서브탭: 뉴스 기사를 근거로 자재비·인건비·기상 등 가격 변동 요인을 분석·요약 (버튼 클릭 시 온디맨드 생성, 자동 스케줄링 아님)

### 병해 예찰 계층

- `tools/pest_forecast.py` — `PEST_RISK_RULES`(10종) + `assess_risk(temp, rh)`: API 키 없이 동작하는 규칙 기반 위험도 판정
- `tools/ncpms_client.py` — NCPMS OpenAPI 도감 조회: `NCPMS_API_KEY` 필요

### RAG / LLM

- `rag/pipeline.py`: `knowledge_base/` 내 md + PDF를 청킹 → BGE-M3(로컬 CPU) → ChromaDB(`chroma_db/`) 저장. `query()` 함수가 MMR 검색 후 Ollama에 컨텍스트를 넘깁니다.
- `ui/advisor.py`: Ollama `gemma4:12b`를 `http://localhost:11434/api/chat`으로 직접 호출. 경보 판정용 프롬프트(`_ALERT_SYSTEM`)와 조치 제안용 프롬프트(`_SYSTEM`)를 별도로 관리합니다.
- `agent/server.py`: FastMCP 서버 — `agent/agent.py`가 서브프로세스로 실행하며 센서·생육·진단이력 도구를 노출합니다.

### 영속 데이터 파일

앱 루트에 JSON/CSV로 상태를 유지합니다: `decisions.json`(RAG 진단이력), `pest_log.json`(방제기록), `diary.json`(영농일지), `work_log.json`(작업일지), `goal_settings.json`(목표 환경값), `growth_data.csv`(생육측정값).

## 환경 설정

```bash
conda create -n greenhouse-ai python=3.11 -y
conda activate greenhouse-ai
pip install -r requirements.txt
cp .env.example .env   # API 키 입력
ollama pull gemma4:12b  # LLM (하드웨어 업그레이드 후 gemma3 → gemma4로 전환)
python -m rag.pipeline  # 지식베이스 최초 인덱싱
```

LLM과 임베딩은 전부 로컬(Ollama + BGE-M3)입니다. 클라우드 LLM API 키는 필요하지 않습니다.
