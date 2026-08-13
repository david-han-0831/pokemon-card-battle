"""게임 루프 통합 테스트 — 가짜 WebSocket 으로 GameManager 를 직접 굴린다.

DB 도 서버도 안 띄우고 돌아간다. GameManager 가 DB 를 건드리는 지점이
`_persist_round` / `_mark_room_finished` 두 곳뿐이라 그것만 막으면 되기 때문이다.

가장 중요한 검증: **상대 정보가 새지 않는가** (design.md §6).
  - 카드 선택 단계: 상대 손패 전체가 비공개
  - 전투 단계: 상대 포켓몬은 공개되지만 **남은 PP 와 이번 턴 선택**은 비공개
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import pytest

from app import game as game_module
from app.battle import STRUGGLE_ID
from app.config import settings
from app.game import GameManager
from app.roster import tier_for_bst


class FakeSocket:
    """send_json 을 기록만 하는 가짜 소켓."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, data: dict) -> None:
        self.sent.append(data)

    async def close(self, code: int = 1000) -> None:
        pass

    def of_type(self, msg_type: str) -> list[dict]:
        return [m["payload"] for m in self.sent if m["type"] == msg_type]

    def last(self, msg_type: str) -> dict | None:
        found = self.of_type(msg_type)
        return found[-1] if found else None

    def types(self) -> list[str]:
        return [m["type"] for m in self.sent]


def fake_move(move_id: int, name: str, type_: str, power: int = 80, pp: int = 10):
    return SimpleNamespace(
        id=move_id, name=name, name_ko=name, type=type_,
        damage_class="physical", power=power, accuracy=100, pp=pp,
        flavor_ko=f"{name} 설명",
    )


def fake_pokemon(dex_id: int, name: str, types: list[str], base: int):
    bst = base * 6
    moves = [
        fake_move(dex_id * 10 + i, f"{name}-move{i}", t, power=60 + i * 10)
        for i, t in enumerate(["normal", "fire", "water", "grass"])
    ]
    return SimpleNamespace(
        dex_id=dex_id, name=name, name_ko=name, types=types,
        tier=tier_for_bst(bst), sprite_url=f"https://example.test/{dex_id}.png",
        hp=base, attack=base, defense=base, special_attack=base,
        special_defense=base, speed=base + dex_id, bst=bst,
        moves=[SimpleNamespace(slot=i, move=m) for i, m in enumerate(moves)],
    )


POOL = [
    fake_pokemon(1, "water-a", ["water"], 90),
    fake_pokemon(2, "fire-a", ["fire"], 95),
    fake_pokemon(3, "grass-a", ["grass"], 85),
    fake_pokemon(4, "electric-a", ["electric"], 80),
    fake_pokemon(5, "ground-a", ["ground"], 75),
    fake_pokemon(6, "psychic-a", ["psychic"], 88),
    fake_pokemon(7, "ghost-a", ["ghost"], 92),
    fake_pokemon(8, "dragon-a", ["dragon"], 70),
    fake_pokemon(9, "steel-a", ["steel"], 78),
    fake_pokemon(10, "fairy-a", ["fairy"], 82),
    fake_pokemon(11, "rock-a", ["rock"], 74),
    fake_pokemon(12, "ice-a", ["ice"], 86),
]


@pytest.fixture
async def manager(monkeypatch):
    """DB 를 끊고, 연출 대기와 타이머를 없앤 매니저."""
    mgr = GameManager()
    mgr._pool = POOL

    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(mgr, "_persist_round", noop)
    monkeypatch.setattr(mgr, "_mark_room_finished", noop)
    monkeypatch.setattr(game_module, "ROUND_INTERMISSION", 0.0)
    monkeypatch.setattr(game_module, "TURN_INTERMISSION", 0.0)
    monkeypatch.setattr(settings, "round_timeout_seconds", 0)
    monkeypatch.setattr(settings, "turn_timeout_seconds", 0)
    yield mgr

    # fixture 가 async 여야 이벤트 루프가 닫히기 **전에** 정리된다.
    pending = [
        task
        for g in mgr._games.values()
        for task in (g._timer_task, g._pacing_task, g.db_task)
        if task and not task.done()
    ]
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


async def settle(times: int = 12) -> None:
    """백그라운드 태스크(다음 턴/라운드 예약)가 돌 틈을 준다."""
    for _ in range(times):
        await asyncio.sleep(0)


async def setup_match(mgr):
    """방 생성 → 두 명 접속 → 양쪽 준비 → 딜링 → 1라운드 카드 선택 단계까지."""
    game = mgr.create_game("TEST01", uuid.uuid4())
    p0 = mgr.add_player(game, 0, "token-0", "앨리스")
    p1 = mgr.add_player(game, 1, "token-1", "밥")

    ws0, ws1 = FakeSocket(), FakeSocket()
    await mgr.attach(game, p0, ws0)
    await mgr.attach(game, p1, ws1)

    await mgr.handle_message(game, p0, {"type": "ready"})
    await mgr.handle_message(game, p1, {"type": "ready"})
    await settle()
    return game, p0, p1, ws0, ws1


async def send_cards(mgr, game, p0, p1, index: int = 0):
    """양쪽이 손패에서 포켓몬을 하나씩 낸다 → 전투 시작."""
    for p in (p0, p1):
        card_id = list(p.hand.keys())[index]
        await mgr.handle_message(game, p, {"type": "play_card", "payload": {"card_id": card_id}})
    await settle()


async def take_turn(mgr, game, p0, p1):
    """양쪽이 쓸 수 있는 기술 중 첫 번째를 쓴다."""
    for p in (p0, p1):
        if p.chosen_move_id is None and p.fighter:
            move_id = p.fighter.usable_move_ids()[0]
            await mgr.handle_message(game, p, {"type": "use_move", "payload": {"move_id": move_id}})
    await settle()


async def finish_round(mgr, game, p0, p1, max_turns: int = 60):
    """한 라운드가 끝날 때까지 턴을 돌린다."""
    start = game.round_no
    for _ in range(max_turns):
        if game.round_no != start or game.status in ("finished", "selecting"):
            break
        await take_turn(mgr, game, p0, p1)


# ---------- 딜링 ----------

async def test_deal_gives_six_cards_with_four_moves_each(manager):
    _, p0, p1, ws0, _ = await setup_match(manager)

    deal = ws0.last("deal")
    assert len(deal["hand"]) == settings.hand_size
    assert deal["opponent_hand_count"] == settings.hand_size
    for card in deal["hand"]:
        assert len(card["moves"]) == 4
        for move in card["moves"]:
            assert move["pp"] == move["max_pp"]  # 내 카드니까 PP 가 보인다


async def test_hand_has_no_duplicate_species(manager):
    _, p0, _, _, _ = await setup_match(manager)
    dex_ids = [c.dex_id for c in p0.hand.values()]
    assert len(dex_ids) == len(set(dex_ids))


# ---------- 히든 정보: 카드 선택 단계 ----------

async def test_opponent_hand_never_leaks_before_battle(manager):
    """내 소켓이 받은 모든 바이트에 상대 카드 ID 가 없어야 한다."""
    game, p0, p1, ws0, _ = await setup_match(manager)
    opponent_ids = set(p1.hand.keys())

    # 한쪽만 냈을 때 — 아직 공개 시점이 아니다.
    await manager.handle_message(
        game, p1, {"type": "play_card", "payload": {"card_id": next(iter(p1.hand))}}
    )

    transcript = repr(ws0.sent)
    assert not [cid for cid in opponent_ids if cid in transcript]
    assert ws0.of_type("opponent_played") == [{}]  # 냈다는 사실만


async def test_deal_only_contains_own_cards(manager):
    _, p0, p1, ws0, ws1 = await setup_match(manager)
    mine = {c["card_id"] for c in ws0.last("deal")["hand"]}
    theirs = {c["card_id"] for c in ws1.last("deal")["hand"]}
    assert mine.isdisjoint(theirs)
    assert mine == set(p0.hand.keys())


# ---------- 히든 정보: 전투 단계 ----------

async def test_battle_start_reveals_opponent_but_hides_pp(manager):
    """전투가 시작되면 상대 포켓몬은 공개된다. 단, 남은 PP 는 끝까지 비공개."""
    game, p0, p1, ws0, _ = await setup_match(manager)
    await send_cards(manager, game, p0, p1)

    battle = ws0.last("battle_start")
    assert battle["opponent"]["card"]["name_ko"]           # 상대가 뭔지는 보인다
    assert battle["opponent"]["hp"] == battle["opponent"]["max_hp"]

    for move in battle["opponent"]["moves"]:
        assert "max_pp" in move       # 기술이 뭔지는 보이고
        assert "pp" not in move       # 몇 번 남았는지는 안 보인다
    for move in battle["you"]["moves"]:
        assert move["pp"] == move["max_pp"]


async def test_opponent_move_choice_is_hidden_until_both_pick(manager):
    """상대가 기술을 골랐을 때 내게 오는 건 '골랐다'는 빈 알림 하나뿐이어야 한다.

    (상대의 기술 *목록*은 battle_start 에서 이미 공개된 정보다. 숨겨야 하는 건
     '그중 이번 턴에 무엇을 골랐는가'이므로, 문자열 검색이 아니라
     '추가로 온 메시지가 무엇인가'로 검사해야 정확하다.)
    """
    game, p0, p1, ws0, _ = await setup_match(manager)
    await send_cards(manager, game, p0, p1)

    before = len(ws0.sent)
    chosen = p1.fighter.usable_move_ids()[0]
    await manager.handle_message(game, p1, {"type": "use_move", "payload": {"move_id": chosen}})

    added = ws0.sent[before:]
    assert added == [{"type": "opponent_move_selected", "payload": {}}]
    assert ws0.last("turn_result") is None  # 아직 결과 없음


async def test_turn_result_reveals_both_moves(manager):
    game, p0, p1, ws0, _ = await setup_match(manager)
    await send_cards(manager, game, p0, p1)
    await take_turn(manager, game, p0, p1)

    result = ws0.of_type("turn_result")[0]
    actors = {e["actor"] for e in result["events"]}
    assert actors <= {"you", "opponent"} and actors
    assert result["you"]["hp"] <= result["you"]["max_hp"]
    # 결과에서도 상대 PP 는 여전히 비공개
    for move in result["opponent"]["moves"]:
        assert "pp" not in move


# ---------- 서버 권위 ----------

async def test_cannot_play_opponents_card(manager):
    game, p0, p1, ws0, _ = await setup_match(manager)
    stolen = next(iter(p1.hand))
    await manager.handle_message(game, p0, {"type": "play_card", "payload": {"card_id": stolen}})
    assert ws0.last("error")["code"] == "INVALID_CARD"
    assert p0.played_card_id is None


async def test_cannot_play_twice_in_one_round(manager):
    game, p0, p1, ws0, _ = await setup_match(manager)
    cards = list(p0.hand.keys())
    await manager.handle_message(game, p0, {"type": "play_card", "payload": {"card_id": cards[0]}})
    await manager.handle_message(game, p0, {"type": "play_card", "payload": {"card_id": cards[1]}})
    assert ws0.last("error")["code"] == "ALREADY_PLAYED"
    assert p0.played_card_id == cards[0]


async def test_cannot_use_a_move_the_pokemon_does_not_have(manager):
    game, p0, p1, ws0, _ = await setup_match(manager)
    await send_cards(manager, game, p0, p1)

    foreign = p1.fighter.card.moves[0].move_id
    if foreign in p0.fighter.usable_move_ids():  # 같은 종을 뽑았으면 확실히 없는 값으로
        foreign = 999_999
    await manager.handle_message(game, p0, {"type": "use_move", "payload": {"move_id": foreign}})
    assert ws0.last("error")["code"] == "INVALID_MOVE"
    assert p0.chosen_move_id is None


async def test_cannot_struggle_while_pp_remains(manager):
    """PP 가 남아 있는데 발버둥을 쓰겠다고 하면 거부된다."""
    game, p0, p1, ws0, _ = await setup_match(manager)
    await send_cards(manager, game, p0, p1)

    await manager.handle_message(game, p0, {"type": "use_move", "payload": {"move_id": STRUGGLE_ID}})
    assert ws0.last("error")["code"] == "INVALID_MOVE"


async def test_cannot_choose_two_moves_in_one_turn(manager):
    game, p0, p1, ws0, _ = await setup_match(manager)
    await send_cards(manager, game, p0, p1)

    usable = p0.fighter.usable_move_ids()
    await manager.handle_message(game, p0, {"type": "use_move", "payload": {"move_id": usable[0]}})
    await manager.handle_message(game, p0, {"type": "use_move", "payload": {"move_id": usable[1]}})
    assert ws0.last("error")["code"] == "ALREADY_CHOSEN"


async def test_move_id_must_be_an_integer(manager):
    game, p0, p1, ws0, _ = await setup_match(manager)
    await send_cards(manager, game, p0, p1)
    await manager.handle_message(game, p0, {"type": "use_move", "payload": {"move_id": "지진"}})
    assert ws0.last("error")["code"] == "INVALID_MOVE"


async def test_unknown_message_type_is_rejected(manager):
    game, p0, _, ws0, _ = await setup_match(manager)
    await manager.handle_message(game, p0, {"type": "give_me_s_tier"})
    assert ws0.last("error")["code"] == "UNKNOWN_TYPE"


# ---------- 전투 진행 ----------

async def test_pp_decreases_as_the_battle_goes(manager):
    game, p0, p1, ws0, _ = await setup_match(manager)
    await send_cards(manager, game, p0, p1)

    move_id = p0.fighter.usable_move_ids()[0]
    before = p0.fighter.pp[move_id]
    await take_turn(manager, game, p0, p1)
    assert p0.fighter.pp[move_id] == before - 1


async def test_round_ends_when_a_pokemon_faints(manager):
    game, p0, p1, ws0, ws1 = await setup_match(manager)
    await send_cards(manager, game, p0, p1)
    await finish_round(manager, game, p0, p1)

    result = ws0.last("round_result")
    assert result is not None
    assert result["winner"] in {"you", "opponent", "draw"}
    assert result["turns"] >= 1
    # 진 쪽 HP 는 0
    assert min(result["you"]["hp"], result["opponent"]["hp"]) == 0 or result["turns"] >= settings.max_turns

    mine = ws0.last("round_result")
    theirs = ws1.last("round_result")
    assert mine["board"]["you"] == theirs["board"]["opponent"]


async def test_used_pokemon_leaves_the_hand(manager):
    game, p0, p1, ws0, _ = await setup_match(manager)
    assert len(p0.hand) == settings.hand_size
    await send_cards(manager, game, p0, p1)
    assert len(p0.hand) == settings.hand_size - 1  # 낸 카드는 손패에서 빠진다


async def test_full_game_runs_six_rounds_and_ends(manager):
    game, p0, p1, ws0, ws1 = await setup_match(manager)

    for _ in range(settings.total_rounds):
        await send_cards(manager, game, p0, p1)
        await finish_round(manager, game, p0, p1)

    assert len(ws0.of_type("round_result")) == settings.total_rounds
    assert len(p0.hand) == 0 and len(p1.hand) == 0

    over0, over1 = ws0.last("game_over"), ws1.last("game_over")
    assert over0 and over1
    assert over0["board"]["you"] == over1["board"]["opponent"]
    assert {"win": "lose", "lose": "win", "draw": "draw"}[over0["result"]] == over1["result"]
    assert game.status == "finished"


async def test_rematch_resets_the_board(manager):
    game, p0, p1, ws0, ws1 = await setup_match(manager)
    for _ in range(settings.total_rounds):
        await send_cards(manager, game, p0, p1)
        await finish_round(manager, game, p0, p1)

    await manager.handle_message(game, p0, {"type": "rematch"})
    assert ws1.last("opponent_wants_rematch") == {}

    await manager.handle_message(game, p1, {"type": "rematch"})
    await settle()

    assert game.game_no == 2
    assert p0.wins == 0 and p1.wins == 0
    assert len(p0.hand) == settings.hand_size
    assert game.status == "selecting"


# ---------- 타이머 ----------

async def test_selection_timeout_auto_plays_a_card(manager, monkeypatch):
    monkeypatch.setattr(settings, "round_timeout_seconds", 0.05)
    game, p0, p1, ws0, _ = await setup_match(manager)

    await asyncio.sleep(0.2)  # 아무도 안 낸다

    assert p0.auto_played and p1.auto_played
    assert game.status == "battling"
    assert ws0.last("battle_start") is not None


async def test_turn_timeout_auto_picks_a_move(manager, monkeypatch):
    monkeypatch.setattr(settings, "turn_timeout_seconds", 0.05)
    game, p0, p1, ws0, _ = await setup_match(manager)
    await send_cards(manager, game, p0, p1)

    await asyncio.sleep(0.2)  # 아무도 기술을 안 고른다

    assert ws0.of_type("turn_result")
    assert ws0.of_type("turn_result")[0]["auto_move"] is True


# ---------- 재접속 ----------

async def test_reconnect_during_selection_restores_hand(manager):
    game, p0, p1, ws0, _ = await setup_match(manager)
    original = set(p0.hand.keys())

    await manager.detach(game, p0, ws0)
    ws_new = FakeSocket()
    await manager.attach(game, p0, ws_new)

    assert {c["card_id"] for c in ws_new.last("deal")["hand"]} == original
    assert "round_start" in ws_new.types()


async def test_reconnect_during_battle_restores_the_fight(manager):
    game, p0, p1, ws0, _ = await setup_match(manager)
    await send_cards(manager, game, p0, p1)
    await take_turn(manager, game, p0, p1)

    await manager.detach(game, p0, ws0)
    ws_new = FakeSocket()
    await manager.attach(game, p0, ws_new)

    battle = ws_new.last("battle_start")
    assert battle["you"]["hp"] == p0.fighter.hp
    assert "turn_start" in ws_new.types()
    for move in battle["opponent"]["moves"]:
        assert "pp" not in move  # 재접속해도 상대 PP 는 안 준다


async def test_reconnect_restores_already_chosen_move(manager):
    game, p0, p1, ws0, _ = await setup_match(manager)
    await send_cards(manager, game, p0, p1)

    chosen = p0.fighter.usable_move_ids()[0]
    await manager.handle_message(game, p0, {"type": "use_move", "payload": {"move_id": chosen}})

    await manager.detach(game, p0, ws0)
    ws_new = FakeSocket()
    await manager.attach(game, p0, ws_new)

    assert ws_new.last("turn_start")["you_chose"] == chosen


async def test_disconnect_notifies_the_opponent(manager):
    game, p0, _, ws0, ws1 = await setup_match(manager)
    await manager.detach(game, p0, ws0)
    assert ws1.of_type("opponent_left") == [{}]


# ---------- DB 를 기다리지 않는다 ----------

async def test_game_runs_even_when_every_db_write_hangs(monkeypatch):
    """DB 가 완전히 멈춰 있어도 게임은 정상 진행돼야 한다.

    방·손패·판정은 전부 메모리에 있고 DB 는 나중에 볼 기록일 뿐이다.
    (실제로 NAS 디스크가 포화됐을 때 방 생성이 23초 걸려 사용자에겐 멈춘 것처럼 보였다.)
    """
    mgr = GameManager()
    mgr._pool = POOL
    monkeypatch.setattr(game_module, "ROUND_INTERMISSION", 0.0)
    monkeypatch.setattr(game_module, "TURN_INTERMISSION", 0.0)
    monkeypatch.setattr(settings, "round_timeout_seconds", 0)
    monkeypatch.setattr(settings, "turn_timeout_seconds", 0)

    started = []

    async def never_finishes():
        started.append(1)
        await asyncio.Event().wait()  # 영원히 안 끝나는 DB 쓰기

    game = mgr.create_game("SLOWDB", uuid.uuid4())
    mgr.schedule_db(game, never_finishes)  # 방 INSERT 가 걸려 있는 상태

    p0 = mgr.add_player(game, 0, "t0", "앨리스")
    p1 = mgr.add_player(game, 1, "t1", "밥")
    ws0, ws1 = FakeSocket(), FakeSocket()
    await mgr.attach(game, p0, ws0)
    await mgr.attach(game, p1, ws1)
    await mgr.handle_message(game, p0, {"type": "ready"})
    await mgr.handle_message(game, p1, {"type": "ready"})
    await settle()

    # 딜링이 됐다 = DB 가 막혀 있어도 게임은 굴러간다
    assert len(ws0.last("deal")["hand"]) == settings.hand_size

    await send_cards(mgr, game, p0, p1)
    await finish_round(mgr, game, p0, p1)
    assert ws0.last("round_result") is not None
    assert started == [1]  # DB 체인은 첫 단계에서 멈춰 있다

    game.db_task.cancel()
    await asyncio.gather(game.db_task, return_exceptions=True)


async def test_db_writes_are_serialised_per_room(manager):
    """rounds 는 rooms 를 참조(FK)하므로 순서가 뒤집히면 안 된다."""
    game = manager.create_game("ORDER1", uuid.uuid4())
    order = []

    def step(name, delay):
        async def work():
            await asyncio.sleep(delay)
            order.append(name)
        return work

    manager.schedule_db(game, step("room", 0.03))    # 느린 첫 단계
    manager.schedule_db(game, step("player", 0.0))
    manager.schedule_db(game, step("round", 0.0))
    await game.db_task

    assert order == ["room", "player", "round"]


async def test_db_failure_does_not_break_the_chain(manager):
    """앞 단계가 터져도 뒤 단계는 계속 시도한다 — 기록 실패로 게임을 멈추진 않는다."""
    game = manager.create_game("ORDER2", uuid.uuid4())
    done = []

    async def boom():
        raise RuntimeError("디스크 터짐")

    async def ok():
        done.append("ok")

    manager.schedule_db(game, boom)
    manager.schedule_db(game, ok)
    await game.db_task

    assert done == ["ok"]
