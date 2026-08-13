"""로스터 조회 REST. 도감 화면·학습용."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Pokemon, TypeInfo
from app.schemas import PokemonOut, TypeOut

router = APIRouter(prefix="/api", tags=["pokedex"])


@router.get("/types", response_model=list[TypeOut])
async def list_types(session: AsyncSession = Depends(get_session)) -> list[TypeInfo]:
    """타입 18종의 한글명 + 공식 아이콘 URL.

    프론트가 앱 시작 시 **한 번만** 받아서 맵으로 들고 있는다.
    기술 메시지마다 아이콘 URL 을 실어 보내면 WebSocket 페이로드가 쓸데없이 커진다
    — 거의 안 바뀌는 참조 데이터는 따로 받는 게 맞다.
    """
    rows = (await session.execute(select(TypeInfo).order_by(TypeInfo.name))).scalars().all()
    return list(rows)


@router.get("/pokemon", response_model=list[PokemonOut])
async def list_pokemon(session: AsyncSession = Depends(get_session)) -> list[Pokemon]:
    """로스터 전체. 티어는 시딩 때 BST 로 계산되어 저장돼 있다.

    이건 히든 정보가 아니다 — 누구나 볼 수 있는 도감이므로 그대로 내보낸다.
    (숨겨야 하는 건 '상대가 지금 무슨 패를 들고 있는가'이지 '어떤 포켓몬이 존재하는가'가 아니다.)
    """
    rows = (await session.execute(select(Pokemon).order_by(Pokemon.dex_id))).scalars().all()
    return list(rows)
