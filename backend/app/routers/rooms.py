"""방 생성/입장 REST.

WebSocket 은 인증 헤더를 붙이기 번거로우므로, 여기서 발급한 `player_token` 을
쿼리스트링으로 제시하게 한다. 토큰이 곧 신원이다.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.game import manager, new_player_token, new_room_code
from app.models import Room, RoomPlayer
from app.schemas import CreateRoomRequest, JoinRoomRequest, RoomStatusOut, RoomTicket

router = APIRouter(prefix="/api/rooms", tags=["rooms"])


@router.post("", response_model=RoomTicket, status_code=201)
async def create_room(
    body: CreateRoomRequest,
    session: AsyncSession = Depends(get_session),
) -> RoomTicket:
    # 코드 충돌은 사실상 없지만(32^6 ≈ 10억), 살아 있는 방과 겹치면 곤란하므로 재시도.
    for _ in range(10):
        code = new_room_code()
        if manager.get(code) is None:
            break
    else:
        raise HTTPException(status_code=503, detail="방 코드를 발급하지 못했습니다. 다시 시도하세요.")

    token = new_player_token()
    room = Room(code=code, status="waiting")
    room.players.append(
        RoomPlayer(slot=0, display_name=body.display_name, player_token=token)
    )
    session.add(room)
    await session.commit()
    await session.refresh(room)

    game = manager.create_game(code, room.id)
    manager.add_player(game, slot=0, token=token, name=body.display_name)

    return RoomTicket(room_code=code, player_token=token, slot=0)


@router.post("/{code}/join", response_model=RoomTicket)
async def join_room(
    code: str,
    body: JoinRoomRequest,
    session: AsyncSession = Depends(get_session),
) -> RoomTicket:
    code = code.upper()
    game = manager.get(code)
    if game is None:
        raise HTTPException(status_code=404, detail="그런 방이 없습니다.")
    if len(game.players) >= 2:
        raise HTTPException(status_code=409, detail="방이 가득 찼습니다.")

    token = new_player_token()
    room = (await session.execute(select(Room).where(Room.code == code))).scalar_one_or_none()
    if room is None:
        raise HTTPException(status_code=404, detail="그런 방이 없습니다.")

    session.add(
        RoomPlayer(room_id=room.id, slot=1, display_name=body.display_name, player_token=token)
    )
    await session.commit()

    manager.add_player(game, slot=1, token=token, name=body.display_name)
    await manager.broadcast_room_state(game)

    return RoomTicket(room_code=code, player_token=token, slot=1)


@router.get("/{code}", response_model=RoomStatusOut)
async def get_room(code: str) -> RoomStatusOut:
    code = code.upper()
    game = manager.get(code)
    if game is None:
        raise HTTPException(status_code=404, detail="그런 방이 없습니다.")
    return RoomStatusOut(room_code=code, status=game.status, player_count=len(game.players))
