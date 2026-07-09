"""애플리케이션 설정 — .env를 pydantic-settings로 로드.

tools/ 각 모듈은 자체적으로 os.getenv()를 호출하므로(레포 루트의 .env를 각자 load_dotenv),
이 Settings는 backend/ 계층(FastAPI 라우터·잡·스케줄러)에서 필요한 값만 다시 선언한다.
실제 키 읽기 책임은 여전히 tools/ 모듈에 있고, 여기서는 "이 키가 설정되어 있는가"를
/api/system/config 등에서 노출하기 위한 용도가 크다.
"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Ollama
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "gemma4:12b"

    # KMA / aT / KAMIS / NCPMS / Naver / Email — presence-only checks live in
    # backend/config.py::Settings.capability_flags(); actual values are read by tools/*.
    kma_api_key: str = ""
    kma_aws_stn: str = "285"
    greenhouse_nx: int = 60
    greenhouse_ny: int = 127
    at_api_key: str = ""
    kamis_api_key: str = ""
    kamis_api_id: str = ""
    ncpms_api_key: str = ""
    naver_client_id: str = ""
    naver_client_secret: str = ""
    email_from: str = ""
    email_to: str = ""
    email_app_password: str = ""
    email_cooldown_minutes: int = 30
    rag_check_interval_minutes: int = 60

    # CORS — Vite dev server default port
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    def capability_flags(self) -> dict[str, bool]:
        """.env 미설정 시 UI가 우아하게 기능을 숨길 수 있도록 하는 플래그."""
        return {
            "has_kma_key": bool(self.kma_api_key),
            "has_at_key": bool(self.at_api_key),
            "has_kamis_keys": bool(self.kamis_api_key and self.kamis_api_id),
            "has_ncpms_key": bool(self.ncpms_api_key),
            "has_naver_keys": bool(self.naver_client_id and self.naver_client_secret),
            "has_email_config": bool(self.email_from and self.email_app_password),
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
