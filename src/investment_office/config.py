# 애플리케이션과 외부 서비스의 실행 설정을 검증해 제공한다.
from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """환경 변수와 로컬 .env 파일에서 읽는 실행 설정."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="INVESTMENT_OFFICE_",
        extra="ignore",
    )

    host: str = "127.0.0.1"
    port: int = Field(default=8765, ge=1, le=65535)
    database_url: str = Field(
        validation_alias=AliasChoices("INVESTMENT_OFFICE_DATABASE_URL", "DATABASE_URL")
    )
    codex_command: str = "codex"
    codex_timeout_seconds: float = Field(default=240.0, gt=0, le=1_800)
    max_parallel_agents: int = Field(default=3, ge=1, le=6)
    market_data_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    provider: str = "codex"


@lru_cache
def get_settings() -> Settings:
    """프로세스에서 동일한 검증 설정 객체를 재사용한다."""

    return Settings()  # type: ignore[call-arg]
