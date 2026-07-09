# legacy_streamlit (보관용)

React + FastAPI로 전환하면서 더 이상 사용하지 않는 **레거시 Streamlit UI** 자료를 모아둔 폴더입니다.
실행에 사용되지 않으며, 참고용으로만 보관합니다.

## 포함 파일

| 항목 | 설명 |
|------|------|
| `ui/app.py` | 기존 Streamlit 대시보드(8탭) 전체 |
| `ui/advisor.py` | `tools.advisor` 재-export 호환 wrapper (더 이상 참조되지 않음) |
| `ui/diary_editor/index.html` | 영농일지 에디터 정적 페이지 |
| `.streamlit/config.toml` | Streamlit 설정 |
| `streamlit.log` | 과거 실행 로그 |

## 참고

- 현재 실행 경로는 `uvicorn backend.main:app` (FastAPI) + `frontend`(Vite) 입니다. README.md 참고.
- `rag/pipeline.py` 하단의 `print("... streamlit run ui/app.py")` 문구는 안내 문자열일 뿐 실제 import는 아닙니다.
- `requirements.txt`의 `streamlit>=1.58` 항목은 이 UI를 다시 돌릴 일이 없다면 제거해도 됩니다.
