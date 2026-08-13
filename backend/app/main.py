"""FastAPI 앱 엔트리포인트.

실행:
    uvicorn app.main:app --reload --port 8000

⚠️ 워커는 1개로 띄운다. 게임 상태가 프로세스 메모리에 있어서
   워커가 여러 개면 방이 프로세스마다 갈라진다 (app/game.py 주석 참조).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import engine
from app.game import manager
from app.models import Base
from app.routers import pokemon as pokemon_router
from app.routers import rooms as rooms_router
from app.ws import router as ws_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 예제 프로젝트라 마이그레이션 도구(Alembic) 없이 create_all 로 테이블을 만든다.
    # 실무에서는 스키마 변경 이력을 남겨야 하므로 Alembic 을 쓴다.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 로스터는 게임 중 매번 조회하면 낭비다. 시작할 때 한 번 메모리에 올린다.
    await manager.load_pool()
    if manager.pool_size == 0:
        logger.warning("로스터가 비어 있습니다. `python -m scripts.seed` 를 먼저 실행하세요.")

    yield

    await engine.dispose()


app = FastAPI(title="Pokémon Card Battle", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(pokemon_router.router)
app.include_router(rooms_router.router)
app.include_router(ws_router)


@app.get("/health", tags=["meta"])
async def health() -> dict:
    return {"status": "ok", "roster": manager.pool_size}
