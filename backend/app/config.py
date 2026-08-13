"""환경설정. .env 파일을 읽어 타입 검증된 설정 객체로 만든다."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://pkm:pkm@localhost:5433/pokemon_battle"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # 제한시간(초). 0 이면 타이머 비활성화
    round_timeout_seconds: float = 30   # 포켓몬 선택
    turn_timeout_seconds: float = 20    # 기술 선택

    # 게임 규칙 — design.md §2, §3, §5
    hand_size: int = 6
    total_rounds: int = 6
    max_turns: int = 30  # 한 라운드가 무한정 늘어지지 않게

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
