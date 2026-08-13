"""Pydantic 스키마. REST 응답 + WebSocket 페이로드의 계약."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TypeOut(BaseModel):
    """타입 참조 데이터. 프론트가 앱 시작 시 한 번 받아 캐싱한다."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    name_ko: str
    icon_url: str     # 이름 배지 (넓은 자리용)
    symbol_url: str   # 정사각 심볼 (좁은 자리용)


class PokemonOut(BaseModel):
    """도감 조회용. 로스터 전체를 그대로 보여주므로 히든 정보가 아니다."""

    model_config = ConfigDict(from_attributes=True)

    dex_id: int
    name: str
    name_ko: str
    types: list[str]
    tier: str
    bst: int
    sprite_url: str
    hp: int
    attack: int
    defense: int
    special_attack: int
    special_defense: int
    speed: int


# WebSocket 페이로드는 여기 두지 않았다.
# 게임 루프에서 초당 여러 번 만들어지는 데이터라 Pydantic 검증 비용을 매번 치를 이유가 없고,
# app/game.py 가 소켓별로 페이로드를 **직접 조립**하는 게 히든 정보 필터링을 눈으로 보이게 한다.
# 대신 계약은 docs/design.md §5 에 문서로 고정해 뒀다.


# ---------- REST ----------

class CreateRoomRequest(BaseModel):
    display_name: str = Field(default="플레이어", max_length=32)


class JoinRoomRequest(BaseModel):
    display_name: str = Field(default="플레이어", max_length=32)


class RoomTicket(BaseModel):
    """방 생성/입장 성공 시 발급. player_token 은 다시 발급되지 않는다."""

    room_code: str
    player_token: str
    slot: int


class RoomStatusOut(BaseModel):
    room_code: str
    status: str
    player_count: int
