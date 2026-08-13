"""WebSocket 엔드포인트.

여기 코드는 얇게 유지한다 — 인증하고, 메시지를 받아 GameManager 에 넘기고, 끊기면 정리.
게임 규칙은 전부 app/game.py 안에 있다.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.game import manager

logger = logging.getLogger(__name__)
router = APIRouter()

# 정책 위반으로 끊을 때 쓰는 코드 (WebSocket close code, 4000~4999 는 앱 정의 영역)
WS_UNAUTHORIZED = 4401
WS_ROOM_NOT_FOUND = 4404


@router.websocket("/ws/rooms/{code}")
async def game_socket(websocket: WebSocket, code: str, token: str = "") -> None:
    code = code.upper()
    game = manager.get(code)
    if game is None:
        await websocket.close(code=WS_ROOM_NOT_FOUND, reason="room not found")
        return

    player = manager.find_player_by_token(game, token)
    if player is None:
        # 토큰이 없거나 틀리면 붙여 주지 않는다. 방 코드만으로는 들어올 수 없다.
        await websocket.close(code=WS_UNAUTHORIZED, reason="invalid token")
        return

    await websocket.accept()
    await manager.attach(game, player, websocket)

    try:
        while True:
            message = await websocket.receive_json()
            if not isinstance(message, dict):
                continue
            await manager.handle_message(game, player, message)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("소켓 처리 중 오류 (room=%s slot=%s)", code, player.slot)
    finally:
        await manager.detach(game, player, websocket)
