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

    # 정확히 일치하는 목록(cors_origins)만으로는 Vercel 미리보기 배포를 못 받는다.
    # 미리보기 URL 은 배포마다 해시가 바뀌기 때문(pokemon-card-battle-<해시>-<팀>.vercel.app).
    # 그래서 패턴으로도 허용한다. 팀 슬러그까지 포함시켜 남의 프로젝트가 걸리지 않게 한다.
    # 비워 두면 패턴 허용을 쓰지 않는다.
    cors_origin_regex: str = ""

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
