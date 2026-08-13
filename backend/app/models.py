"""DB 모델. design.md §7."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class Pokemon(Base):
    """PokeAPI 에서 긁어온 로스터 캐시.

    매 요청마다 PokeAPI 를 때리면 (1) 느리고 (2) 남의 서버에 민폐고
    (3) 그쪽이 죽으면 우리 게임도 죽는다. 그래서 시딩 한 번으로 우리 DB 에 복사해 둔다.
    """

    __tablename__ = "pokemon"

    dex_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    name_ko: Mapped[str] = mapped_column(String(64), nullable=False)
    types: Mapped[list[str]] = mapped_column(ARRAY(String(16)), nullable=False)

    hp: Mapped[int] = mapped_column(Integer, nullable=False)
    attack: Mapped[int] = mapped_column(Integer, nullable=False)
    defense: Mapped[int] = mapped_column(Integer, nullable=False)
    special_attack: Mapped[int] = mapped_column(Integer, nullable=False)
    special_defense: Mapped[int] = mapped_column(Integer, nullable=False)
    speed: Mapped[int] = mapped_column(Integer, nullable=False)

    bst: Mapped[int] = mapped_column(Integer, nullable=False)
    tier: Mapped[str] = mapped_column(String(1), nullable=False)

    sprite_url: Mapped[str] = mapped_column(String(512), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # 기술 4개. selectin 으로 미리 당겨 온다 — 게임 중엔 로스터를 메모리에 통째로 올려 두므로
    # lazy 로딩이 남아 있으면 세션이 닫힌 뒤 터진다.
    moves: Mapped[list["PokemonMove"]] = relationship(
        order_by="PokemonMove.slot", lazy="selectin", cascade="all, delete-orphan"
    )


class TypeInfo(Base):
    """타입 18종의 한글명과 공식 아이콘.

    PokeAPI 는 **기술 이미지는 주지 않지만** 타입 아이콘은 준다
    (`/type/{name}` → sprites). 기술 버튼·카드 칩을 글자 대신 이 배지로 그린다.
    """

    __tablename__ = "types"

    name: Mapped[str] = mapped_column(String(16), primary_key=True)
    name_ko: Mapped[str] = mapped_column(String(16), nullable=False)
    # 이름이 적힌 가로로 긴 배지. 기술 버튼처럼 넓은 자리에 쓴다.
    icon_url: Mapped[str] = mapped_column(String(512), nullable=False)
    # 심볼만 있는 정사각 아이콘. 손패 카드처럼 좁은 자리에 쓴다.
    symbol_url: Mapped[str] = mapped_column(String(512), nullable=False, default="")


class Move(Base):
    """공격 기술. PokeAPI `/move/{name}` 캐시.

    변화기술(damage_class=status)은 담지 않는다 — 상태이상까지 구현하면
    예제 스코프를 넘는다(design.md §11).
    """

    __tablename__ = "moves"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # PokeAPI move id
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    name_ko: Mapped[str] = mapped_column(String(64), nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    damage_class: Mapped[str] = mapped_column(String(16), nullable=False)  # physical | special
    power: Mapped[int] = mapped_column(Integer, nullable=False)
    accuracy: Mapped[int] = mapped_column(Integer, nullable=False)  # null(반드시 명중)은 100 으로 저장
    pp: Mapped[int] = mapped_column(Integer, nullable=False)
    # 기술 설명(한글). 툴팁에 쓴다. PokeAPI flavor_text_entries 에서 가져온다.
    flavor_ko: Mapped[str] = mapped_column(String(512), nullable=False, default="")


class PokemonMove(Base):
    """포켓몬이 가진 기술 4개. slot 0~3."""

    __tablename__ = "pokemon_moves"

    pokemon_dex_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("pokemon.dex_id", ondelete="CASCADE"), primary_key=True
    )
    slot: Mapped[int] = mapped_column(Integer, primary_key=True)
    move_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("moves.id", ondelete="CASCADE"), nullable=False
    )

    move: Mapped[Move] = relationship(lazy="joined")


class Room(Base):
    __tablename__ = "rooms"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    code: Mapped[str] = mapped_column(String(8), unique=True, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="waiting", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    players: Mapped[list["RoomPlayer"]] = relationship(
        back_populates="room", cascade="all, delete-orphan", lazy="selectin"
    )


class RoomPlayer(Base):
    __tablename__ = "room_players"
    __table_args__ = (UniqueConstraint("room_id", "slot", name="uq_room_slot"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    room_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False
    )
    slot: Mapped[int] = mapped_column(Integer, nullable=False)
    display_name: Mapped[str] = mapped_column(String(32), nullable=False)
    # 이 토큰이 곧 신원이다. 클라이언트에 1회만 발급되고, WS 접속 시 제시한다.
    player_token: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)

    room: Mapped[Room] = relationship(back_populates="players")


class RoundRecord(Base):
    """끝난 라운드의 결과만 적재한다. 진행 중 상태는 인메모리(GameManager)."""

    __tablename__ = "rounds"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    room_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False, index=True
    )
    game_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    round_no: Mapped[int] = mapped_column(Integer, nullable=False)

    slot0_dex_id: Mapped[int] = mapped_column(Integer, nullable=False)
    slot1_dex_id: Mapped[int] = mapped_column(Integer, nullable=False)
    # 라운드가 끝났을 때 남은 체력. 0 이면 쓰러진 것.
    slot0_hp_left: Mapped[int] = mapped_column(Integer, nullable=False)
    slot1_hp_left: Mapped[int] = mapped_column(Integer, nullable=False)
    turns: Mapped[int] = mapped_column(Integer, nullable=False)
    winner_slot: Mapped[int | None] = mapped_column(Integer, nullable=True)  # None = 무승부

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
