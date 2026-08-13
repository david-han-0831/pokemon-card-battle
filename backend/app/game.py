"""게임 상태 관리자 (인메모리).

여기가 이 프로젝트의 심장이자, 히든 정보 처리(design.md §6)의 핵심이다.

원칙 3가지:
  1. **서버가 진실이다.** 손패도, HP·PP 도, 판정도, 타이머도 전부 서버가 갖는다.
     클라이언트가 보내는 건 "이 카드/기술을 쓰겠다"는 의사표시뿐이고, 서버가 검증한다.
  2. **브로드캐스트 금지.** 두 플레이어에게 같은 메시지를 뿌리는 순간 정보가 샌다.
     항상 소켓별로 페이로드를 따로 만든다(`_send_to`).
  3. **진행 중 상태는 DB 에 안 넣는다.** 턴마다 DB 를 때리면 실시간 응답이 느려진다.
     끝난 라운드 결과만 비동기로 적재한다.

라운드 하나의 생애:
    selecting  포켓몬 선택 (상대 손패·선택 비공개)
      ↓ 양쪽 제출
    battling   턴제 전투 (여기서 처음 서로의 포켓몬이 공개된다)
      ↓ 한쪽 기절 / 30턴 초과
    라운드 종료 → 다음 라운드 or 게임 종료
"""

from __future__ import annotations

import asyncio
import logging
import random
import secrets
import time
import uuid
from dataclasses import dataclass, field

from fastapi import WebSocket
from sqlalchemy import select

from app.battle import (
    STRUGGLE_ID,
    Card,
    Fighter,
    Move,
    resolve_turn,
    round_winner,
)
from app.config import settings
from app.dealing import deal_hand
from app.db import SessionLocal
from app.models import Pokemon, Room, RoundRecord

logger = logging.getLogger(__name__)

ROOM_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 헷갈리는 0/O/1/I 제외
ROUND_INTERMISSION = 3.5  # 라운드 결과 연출 시간
# 턴 결과 연출 시간. 프론트가 이벤트를 0.9초 간격으로 재생하므로(공격 2회 = 1.8초)
# 그보다 여유를 둬야 이펙트가 잘리지 않는다.
TURN_INTERMISSION = 2.8


def new_room_code() -> str:
    return "".join(secrets.choice(ROOM_CODE_ALPHABET) for _ in range(6))


def new_player_token() -> str:
    return secrets.token_urlsafe(24)


@dataclass
class Player:
    slot: int
    token: str
    name: str
    ws: WebSocket | None = None
    ready: bool = False
    wants_rematch: bool = False
    hand: dict[str, Card] = field(default_factory=dict)

    # 카드 선택 단계
    played_card_id: str | None = None
    auto_played: bool = False

    # 전투 단계
    fighter: Fighter | None = None
    chosen_move_id: int | None = None
    auto_move: bool = False

    wins: int = 0

    @property
    def connected(self) -> bool:
        return self.ws is not None


@dataclass
class Game:
    code: str
    room_id: uuid.UUID
    players: dict[int, Player] = field(default_factory=dict)
    status: str = "waiting"  # waiting | selecting | battling | finished
    game_no: int = 1
    round_no: int = 0
    turn_no: int = 0
    deadline: float | None = None  # time.monotonic() 기준
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _timer_task: asyncio.Task | None = None
    _pacing_task: asyncio.Task | None = None

    def opponent_of(self, slot: int) -> Player | None:
        return self.players.get(1 - slot)


class GameManager:
    """방 코드 → Game. 단일 프로세스 전제.

    (여러 워커로 띄우면 방이 프로세스마다 갈라진다 — 예제 스코프에선 워커 1개로 실행한다.
     실무에선 Redis 같은 공유 저장소로 빼야 한다.)
    """

    def __init__(self) -> None:
        self._games: dict[str, Game] = {}
        self._pool: list[Pokemon] = []  # 로스터 캐시 (서버 시작 시 1회 로드)

    # ---------- 로스터 ----------

    async def load_pool(self) -> None:
        async with SessionLocal() as session:
            rows = (await session.execute(select(Pokemon).order_by(Pokemon.dex_id))).scalars().all()
        self._pool = [r for r in rows if len(r.moves) > 0]
        skipped = len(rows) - len(self._pool)
        logger.info("로스터 %d마리 로드됨%s", len(self._pool),
                    f" (기술 없어 제외 {skipped}마리)" if skipped else "")

    @property
    def pool_size(self) -> int:
        return len(self._pool)

    # ---------- 방 ----------

    def create_game(self, code: str, room_id: uuid.UUID) -> Game:
        game = Game(code=code, room_id=room_id)
        self._games[code] = game
        return game

    def get(self, code: str) -> Game | None:
        return self._games.get(code)

    def add_player(self, game: Game, slot: int, token: str, name: str) -> Player:
        player = Player(slot=slot, token=token, name=name)
        game.players[slot] = player
        return player

    def find_player_by_token(self, game: Game, token: str) -> Player | None:
        for p in game.players.values():
            if secrets.compare_digest(p.token, token):
                return p
        return None

    # ---------- 소켓 입출력 ----------

    async def _send_to(self, player: Player | None, msg_type: str, payload: dict) -> None:
        """플레이어 한 명에게만 보낸다. 소켓이 죽어 있으면 조용히 무시."""
        if player is None or player.ws is None:
            return
        try:
            await player.ws.send_json({"type": msg_type, "payload": payload})
        except Exception:
            logger.debug("send 실패 (slot=%s)", player.slot)
            player.ws = None

    async def _send_error(self, player: Player, code: str, message: str) -> None:
        await self._send_to(player, "error", {"code": code, "message": message})

    # ---------- 상태 통지 ----------

    def _room_state_for(self, game: Game, me: Player) -> dict:
        opp = game.opponent_of(me.slot)
        return {
            "room_code": game.code,
            "status": game.status,
            "round": game.round_no,
            "total_rounds": settings.total_rounds,
            "board": {"you": me.wins, "opponent": opp.wins if opp else 0},
            "you": {"slot": me.slot, "name": me.name, "ready": me.ready},
            "opponent": (
                {
                    "slot": opp.slot,
                    "name": opp.name,
                    "ready": opp.ready,
                    "connected": opp.connected,
                }
                if opp
                else None
            ),
        }

    async def broadcast_room_state(self, game: Game) -> None:
        """이름만 broadcast 지, 실제로는 각자에게 '자기 관점' 페이로드를 따로 만든다."""
        for player in game.players.values():
            await self._send_to(player, "room_state", self._room_state_for(game, player))

    def _remaining_ms(self, game: Game) -> int | None:
        if game.deadline is None:
            return None
        return max(0, int((game.deadline - time.monotonic()) * 1000))

    # ---------- 접속 / 해제 ----------

    async def attach(self, game: Game, player: Player, ws: WebSocket) -> None:
        if player.ws is not None:
            try:
                await player.ws.close(code=4000)
            except Exception:
                pass
        player.ws = ws

        await self._send_to(player, "room_state", self._room_state_for(game, player))
        await self._resend_current_phase(game, player)

        opp = game.opponent_of(player.slot)
        if opp:
            await self._send_to(opp, "room_state", self._room_state_for(game, opp))

    async def _resend_current_phase(self, game: Game, player: Player) -> None:
        """새로고침 복구 — 지금 단계에 맞는 화면을 다시 그릴 수 있게 보낸다."""
        opp = game.opponent_of(player.slot)

        if game.status == "selecting" and player.hand:
            await self._send_hand(game, player)
            await self._send_to(
                player,
                "round_start",
                {
                    "round": game.round_no,
                    "deadline_ms": self._remaining_ms(game),
                    "you_played": player.played_card_id,
                },
            )
            if opp and opp.played_card_id:
                await self._send_to(player, "opponent_played", {})

        elif game.status == "battling" and player.fighter and opp and opp.fighter:
            await self._send_to(player, "battle_start", self._battle_payload(game, player))
            await self._send_to(
                player,
                "turn_start",
                {
                    "turn": game.turn_no,
                    "deadline_ms": self._remaining_ms(game),
                    "you_chose": player.chosen_move_id,
                },
            )
            if opp.chosen_move_id is not None:
                await self._send_to(player, "opponent_move_selected", {})

    async def detach(self, game: Game, player: Player, ws: WebSocket) -> None:
        if player.ws is not ws:
            return  # 이미 새 소켓으로 교체된 뒤의 늦은 정리 — 무시
        player.ws = None
        opp = game.opponent_of(player.slot)
        if opp:
            await self._send_to(opp, "opponent_left", {})
            await self._send_to(opp, "room_state", self._room_state_for(game, opp))

    # ---------- 메시지 라우팅 ----------

    async def handle_message(self, game: Game, player: Player, message: dict) -> None:
        msg_type = message.get("type")
        payload = message.get("payload") or {}

        if msg_type == "ping":
            await self._send_to(player, "pong", {})
        elif msg_type == "ready":
            await self._on_ready(game, player)
        elif msg_type == "play_card":
            await self._on_play_card(game, player, payload.get("card_id"))
        elif msg_type == "use_move":
            await self._on_use_move(game, player, payload.get("move_id"))
        elif msg_type == "rematch":
            await self._on_rematch(game, player)
        else:
            await self._send_error(player, "UNKNOWN_TYPE", f"모르는 메시지 타입: {msg_type}")

    async def _on_ready(self, game: Game, player: Player) -> None:
        async with game.lock:
            if game.status != "waiting":
                await self._send_error(player, "BAD_STATE", "지금은 준비 상태를 바꿀 수 없습니다.")
                return
            player.ready = not player.ready
            await self.broadcast_room_state(game)

            if len(game.players) == 2 and all(p.ready for p in game.players.values()):
                await self._start_game(game)

    async def _on_play_card(self, game: Game, player: Player, card_id: str | None) -> None:
        async with game.lock:
            if game.status != "selecting":
                await self._send_error(player, "BAD_STATE", "지금은 포켓몬을 낼 수 없습니다.")
                return
            if player.played_card_id is not None:
                await self._send_error(player, "ALREADY_PLAYED", "이번 라운드엔 이미 냈습니다.")
                return
            # 🔒 서버 검증: 그 카드가 정말 이 플레이어의 손패에 있는가?
            if not card_id or card_id not in player.hand:
                await self._send_error(player, "INVALID_CARD", "가지고 있지 않은 카드입니다.")
                return

            player.played_card_id = card_id
            player.auto_played = False

            opp = game.opponent_of(player.slot)
            # 상대에게는 "냈다"는 사실만. 어떤 카드인지는 절대 안 보낸다.
            await self._send_to(opp, "opponent_played", {})
            await self._send_to(player, "play_accepted", {"card_id": card_id})

            if opp and opp.played_card_id is not None:
                await self._begin_battle(game)

    async def _on_use_move(self, game: Game, player: Player, move_id) -> None:
        async with game.lock:
            if game.status != "battling" or not player.fighter:
                await self._send_error(player, "BAD_STATE", "지금은 기술을 쓸 수 없습니다.")
                return
            if player.chosen_move_id is not None:
                await self._send_error(player, "ALREADY_CHOSEN", "이번 턴엔 이미 기술을 골랐습니다.")
                return
            if not isinstance(move_id, int):
                await self._send_error(player, "INVALID_MOVE", "기술 ID 가 올바르지 않습니다.")
                return
            # 🔒 서버 검증: 그 기술을 정말 갖고 있고, PP 가 남아 있는가?
            #    발버둥은 쓸 기술이 하나도 없을 때만 허용된다.
            if move_id not in player.fighter.usable_move_ids():
                await self._send_error(player, "INVALID_MOVE", "지금 쓸 수 없는 기술입니다.")
                return

            player.chosen_move_id = move_id
            player.auto_move = False

            opp = game.opponent_of(player.slot)
            # 어떤 기술인지는 안 보낸다 — 동시 선택의 의미가 사라진다.
            await self._send_to(opp, "opponent_move_selected", {})
            await self._send_to(player, "move_accepted", {"move_id": move_id})

            if opp and opp.chosen_move_id is not None:
                await self._resolve_turn(game)

    async def _on_rematch(self, game: Game, player: Player) -> None:
        async with game.lock:
            if game.status != "finished":
                await self._send_error(player, "BAD_STATE", "게임이 끝난 뒤에만 재대결할 수 있습니다.")
                return
            player.wants_rematch = True
            opp = game.opponent_of(player.slot)
            await self._send_to(opp, "opponent_wants_rematch", {})

            if opp and opp.wants_rematch:
                for p in game.players.values():
                    p.wants_rematch = False
                    p.ready = False
                    p.wins = 0
                game.game_no += 1
                game.status = "waiting"
                game.round_no = 0
                await self.broadcast_room_state(game)
                await self._start_game(game)

    # ---------- 게임 진행 ----------

    async def _start_game(self, game: Game) -> None:
        if not self._pool:
            for p in game.players.values():
                await self._send_error(p, "NO_ROSTER", "로스터가 비어 있습니다. 시딩을 먼저 실행하세요.")
            return

        rng = random.Random()
        game.round_no = 0
        for p in game.players.values():
            p.wins = 0
            p.played_card_id = None
            p.fighter = None
            # 딜링은 플레이어마다 독립. 같은 종이 양쪽에 나올 수 있다(설계 의도).
            p.hand = {c.card_id: c for c in deal_hand(self._pool, settings.hand_size, rng)}

        for p in game.players.values():
            await self._send_hand(game, p)

        await self._begin_round(game)

    async def _send_hand(self, game: Game, player: Player) -> None:
        """딜링 전송 — 여기가 히든 정보 필터링의 실제 지점.

        내 패는 카드 전체(기술 포함)를, 상대 패는 **개수만** 보낸다.
        """
        opp = game.opponent_of(player.slot)
        await self._send_to(
            player,
            "deal",
            {
                "hand": [
                    {**c.to_payload(), "moves": [m.to_payload(current_pp=m.pp) for m in c.moves]}
                    for c in player.hand.values()
                ],
                "opponent_hand_count": len(opp.hand) if opp else 0,
            },
        )

    async def _begin_round(self, game: Game) -> None:
        """포켓몬 선택 단계 시작."""
        game.status = "selecting"
        game.round_no += 1
        game.turn_no = 0
        for p in game.players.values():
            p.played_card_id = None
            p.auto_played = False
            p.fighter = None
            p.chosen_move_id = None

        self._arm_timer(game, settings.round_timeout_seconds, self._selection_timeout, game.round_no)

        for p in game.players.values():
            await self._send_to(
                p,
                "round_start",
                {
                    "round": game.round_no,
                    "deadline_ms": self._remaining_ms(game),
                    "you_played": None,
                },
            )
        await self.broadcast_room_state(game)

    async def _begin_battle(self, game: Game) -> None:
        """양쪽이 포켓몬을 냈다 → 전투 시작. 여기서 처음 서로가 공개된다."""
        self._cancel_timer(game)
        game.status = "battling"
        game.turn_no = 0

        for p in game.players.values():
            card = p.hand.pop(p.played_card_id)
            p.fighter = Fighter.create(card)

        for p in game.players.values():
            await self._send_to(p, "battle_start", self._battle_payload(game, p))

        await self._begin_turn(game)

    def _battle_payload(self, game: Game, me: Player) -> dict:
        opp = game.opponent_of(me.slot)
        return {
            "round": game.round_no,
            # private=True → 내 남은 PP + 기술별 상성 배율. 상대 것은 PP 를 뺀다.
            "you": me.fighter.to_payload(private=True, versus=opp.fighter.card),
            "opponent": opp.fighter.to_payload(private=False),
            "hand_counts": {"you": len(me.hand), "opponent": len(opp.hand)},
            "max_turns": settings.max_turns,
        }

    async def _begin_turn(self, game: Game) -> None:
        game.turn_no += 1
        for p in game.players.values():
            p.chosen_move_id = None
            p.auto_move = False

        self._arm_timer(game, settings.turn_timeout_seconds, self._turn_timeout, game.turn_no)

        for p in game.players.values():
            await self._send_to(
                p,
                "turn_start",
                {
                    "turn": game.turn_no,
                    "deadline_ms": self._remaining_ms(game),
                    "you_chose": None,
                },
            )

    # ---------- 타이머 ----------

    def _arm_timer(self, game: Game, seconds: float, handler, marker: int) -> None:
        self._cancel_timer(game)
        game.deadline = (time.monotonic() + seconds) if seconds > 0 else None
        if seconds > 0:
            game._timer_task = asyncio.create_task(self._run_timer(game, seconds, handler, marker))

    def _cancel_timer(self, game: Game) -> None:
        if game._timer_task and not game._timer_task.done():
            game._timer_task.cancel()
        game._timer_task = None
        game.deadline = None

    async def _run_timer(self, game: Game, seconds: float, handler, marker: int) -> None:
        try:
            await asyncio.sleep(seconds)
        except asyncio.CancelledError:
            return
        async with game.lock:
            await handler(game, marker)

    async def _selection_timeout(self, game: Game, round_no: int) -> None:
        """시간 내 미제출 → 서버가 손패에서 랜덤으로 대신 낸다."""
        if game.status != "selecting" or game.round_no != round_no:
            return
        rng = random.Random()
        for p in game.players.values():
            if p.played_card_id is None and p.hand:
                p.played_card_id = rng.choice(list(p.hand.keys()))
                p.auto_played = True
                await self._send_to(game.opponent_of(p.slot), "opponent_played", {})
        await self._begin_battle(game)

    async def _turn_timeout(self, game: Game, turn_no: int) -> None:
        """시간 내 미선택 → 쓸 수 있는 기술 중 랜덤."""
        if game.status != "battling" or game.turn_no != turn_no:
            return
        rng = random.Random()
        for p in game.players.values():
            if p.chosen_move_id is None and p.fighter:
                p.chosen_move_id = rng.choice(p.fighter.usable_move_ids())
                p.auto_move = True
                await self._send_to(game.opponent_of(p.slot), "opponent_move_selected", {})
        await self._resolve_turn(game)

    # ---------- 턴 판정 ----------

    def _move_of(self, player: Player) -> Move:
        move = player.fighter.move_by_id(player.chosen_move_id)
        if move is None:  # 방어적 처리 — 검증을 통과했다면 여기 올 일은 없다
            move = player.fighter.move_by_id(STRUGGLE_ID) or player.fighter.card.moves[0]
        return move

    async def _resolve_turn(self, game: Game) -> None:
        """양쪽 기술 선택 완료 → 한 턴 실행. 반드시 game.lock 안에서 호출된다."""
        self._cancel_timer(game)

        p0, p1 = game.players[0], game.players[1]
        fighters = {0: p0.fighter, 1: p1.fighter}
        chosen = {0: self._move_of(p0), 1: self._move_of(p1)}

        events = resolve_turn(fighters, chosen, random.Random())

        for me in (p0, p1):
            opp = game.opponent_of(me.slot)
            await self._send_to(
                me,
                "turn_result",
                {
                    "turn": game.turn_no,
                    "events": [e.to_payload(me.slot) for e in events],
                    "you": me.fighter.to_payload(private=True, versus=opp.fighter.card),
                    "opponent": opp.fighter.to_payload(private=False),
                    "auto_move": me.auto_move,
                },
            )

        winner = round_winner(fighters, game.turn_no, settings.max_turns)
        if winner is None:
            game._pacing_task = asyncio.create_task(self._next_turn_after_pause(game, game.turn_no))
        else:
            await self._end_round(game, winner)

    async def _next_turn_after_pause(self, game: Game, from_turn: int) -> None:
        try:
            await asyncio.sleep(TURN_INTERMISSION)
        except asyncio.CancelledError:
            return
        async with game.lock:
            if game.status == "battling" and game.turn_no == from_turn:
                await self._begin_turn(game)

    # ---------- 라운드 종료 ----------

    async def _end_round(self, game: Game, winner) -> None:
        p0, p1 = game.players[0], game.players[1]
        winner_slot = None if winner == "draw" else winner
        if winner_slot == 0:
            p0.wins += 1
        elif winner_slot == 1:
            p1.wins += 1

        for me in (p0, p1):
            opp = game.opponent_of(me.slot)
            if winner_slot is None:
                verdict = "draw"
            else:
                verdict = "you" if winner_slot == me.slot else "opponent"
            await self._send_to(
                me,
                "round_result",
                {
                    "round": game.round_no,
                    "turns": game.turn_no,
                    "winner": verdict,
                    "you": me.fighter.to_payload(private=True, versus=opp.fighter.card),
                    "opponent": opp.fighter.to_payload(private=False),
                    "board": {"you": me.wins, "opponent": opp.wins},
                    "hand_counts": {"you": len(me.hand), "opponent": len(opp.hand)},
                },
            )

        asyncio.create_task(
            self._persist_round(
                room_id=game.room_id,
                game_no=game.game_no,
                round_no=game.round_no,
                turns=game.turn_no,
                dex0=p0.fighter.card.dex_id,
                dex1=p1.fighter.card.dex_id,
                hp0=p0.fighter.hp,
                hp1=p1.fighter.hp,
                winner_slot=winner_slot,
            )
        )

        if game.round_no >= settings.total_rounds:
            game.status = "finished"
            game._pacing_task = asyncio.create_task(self._finish_after_pause(game))
        else:
            game._pacing_task = asyncio.create_task(
                self._next_round_after_pause(game, game.round_no)
            )

    async def _next_round_after_pause(self, game: Game, from_round: int) -> None:
        try:
            await asyncio.sleep(ROUND_INTERMISSION)
        except asyncio.CancelledError:
            return
        async with game.lock:
            if game.status == "battling" and game.round_no == from_round:
                await self._begin_round(game)

    async def _finish_after_pause(self, game: Game) -> None:
        try:
            await asyncio.sleep(ROUND_INTERMISSION)
        except asyncio.CancelledError:
            return
        async with game.lock:
            p0, p1 = game.players[0], game.players[1]
            for me in (p0, p1):
                opp = game.opponent_of(me.slot)
                if me.wins > opp.wins:
                    result = "win"
                elif me.wins < opp.wins:
                    result = "lose"
                else:
                    result = "draw"
                await self._send_to(
                    me,
                    "game_over",
                    {"board": {"you": me.wins, "opponent": opp.wins}, "result": result},
                )
        await self._mark_room_finished(game.room_id)

    # ---------- DB 적재 ----------

    async def _persist_round(
        self,
        *,
        room_id: uuid.UUID,
        game_no: int,
        round_no: int,
        turns: int,
        dex0: int,
        dex1: int,
        hp0: int,
        hp1: int,
        winner_slot: int | None,
    ) -> None:
        try:
            async with SessionLocal() as session:
                session.add(
                    RoundRecord(
                        room_id=room_id,
                        game_no=game_no,
                        round_no=round_no,
                        turns=turns,
                        slot0_dex_id=dex0,
                        slot1_dex_id=dex1,
                        slot0_hp_left=hp0,
                        slot1_hp_left=hp1,
                        winner_slot=winner_slot,
                    )
                )
                await session.commit()
        except Exception:
            logger.exception("라운드 기록 실패 (room=%s round=%s)", room_id, round_no)

    async def _mark_room_finished(self, room_id: uuid.UUID) -> None:
        try:
            async with SessionLocal() as session:
                room = await session.get(Room, room_id)
                if room:
                    room.status = "finished"
                    await session.commit()
        except Exception:
            logger.exception("방 상태 갱신 실패 (room=%s)", room_id)


manager = GameManager()
