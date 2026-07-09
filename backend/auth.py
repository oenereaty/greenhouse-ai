"""API 키 검증 — 백엔드를 외부에 노출할 때만 활성화된다.

BACKEND_API_KEY가 .env에 비어 있으면(로컬 개발 기본값) 검증을 건너뛴다 —
로컬에서 프론트가 그냥 붙던 기존 흐름을 그대로 유지하기 위함이다. 실제로
공개 URL로 배포할 때만 이 값을 설정해 x-api-key 헤더를 요구하게 된다.

파일 다운로드(엑셀 내보내기 등) 링크는 <a href>로 직접 여는 방식이라
fetch()처럼 x-api-key 헤더를 붙일 수 없다 — 그래서 헤더가 없으면 쿼리
파라미터 api_key도 함께 허용한다(frontend/src/api/client.ts::fileUrl 참고).
"""
from fastapi import Header, HTTPException, Query

from backend.config import get_settings


def verify_api_key(
    x_api_key: str | None = Header(default=None),
    api_key: str | None = Query(default=None),
) -> None:
    expected = get_settings().backend_api_key
    if not expected:
        return
    if x_api_key == expected or api_key == expected:
        return
    raise HTTPException(status_code=401, detail="Invalid or missing x-api-key")
