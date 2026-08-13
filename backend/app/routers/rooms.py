"""방 생성/입장 REST.

WebSocket 은 인증 헤더를 붙이기 번거로우므로, 여기서 발급한 `player_token` 을
쿼리스트링으로 제시하게 한다. 토큰이 곧 신원이다.

⚠️ **이 라우터는 DB 를 기다리지 않는다.**
방·손패·판정은 전부 메모리(GameManager)에 있고 DB 는 나중에 볼 기록일 뿐이라,
커밋을 await 할 이유가 없다. 디스크가 느린 순간 사용자가 로비에서 멈춘 채
기다리게 되는 걸 막는다(자세한 근거는 GameManager.schedule_db 주석).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException

from app.game import manager, new_player_token, new_room_code
from app.schemas import CreateRoomRequest, JoinRoomRequest, RoomStatusOut, RoomTicket

router = APIRouter(prefix="/api/rooms", tags=["rooms"])


@router.post("", response_model=RoomTicket, status_code=201)
async def create_room(body: CreateRoomRequest) -> RoomTicket:
    # 코드 충돌은 사실상 없지만(32^6 ≈ 10억), 살아 있는 방과 겹치면 곤란하므로 재시도.
    for _ in range(10):
        code = new_room_code()
        if manager.get(code) is None:
            break
    else:
        raise HTTPException(status_code=503, detail="방 코드를 발급하지 못했습니다. 다시 시도하세요.")

    token = new_player_token()
    game = manager.create_game(code, uuid.uuid4())
    manager.add_player(game, slot=0, token=token, name=body.display_name)
    manager.persist_room(game, body.display_name, token)  # 뒤에서 기록

    return RoomTicket(room_code=code, player_token=token, slot=0)


@router.post("/{code}/join", response_model=RoomTicket)
async def join_room(code: str, body: JoinRoomRequest) -> RoomTicket:
    code = code.upper()
    game = manager.get(code)
    if game is None:
        raise HTTPException(status_code=404, detail="그런 방이 없습니다.")
    if len(game.players) >= 2:
        raise HTTPException(status_code=409, detail="방이 가득 찼습니다.")

    token = new_player_token()
    manager.add_player(game, slot=1, token=token, name=body.display_name)
    manager.persist_player(game, 1, body.display_name, token)  # 뒤에서 기록
    await manager.broadcast_room_state(game)

    return RoomTicket(room_code=code, player_token=token, slot=1)


@router.get("/{code}", response_model=RoomStatusOut)
async def get_room(code: str) -> RoomStatusOut:
    code = code.upper()
    game = manager.get(code)
    if game is None:
        raise HTTPException(status_code=404, detail="그런 방이 없습니다.")
    return RoomStatusOut(room_code=code, status=game.status, player_count=len(game.players))
