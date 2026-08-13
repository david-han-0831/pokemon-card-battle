"""전투 엔진 단위 테스트.

battle.py 가 DB·소켓을 모르고 난수도 인자로 받는 순수 모듈이라 이렇게 가볍게 테스트할 수 있다.
"게임 규칙을 I/O 에서 떼어 놓으면 테스트가 쉬워진다"를 보여주는 예제.
"""

from __future__ import annotations

import random

import pytest

from app.battle import (
    LEVEL,
    STRUGGLE,
    STRUGGLE_ID,
    Card,
    Fighter,
    Move,
    accuracy_check,
    damage,
    move_multiplier,
    resolve_turn,
    round_winner,
    scaled_hp,
    scaled_stat,
    turn_order,
)
from app.dealing import weighted_sample_without_replacement
from app.roster import expected_power, pick_moveset, tier_for_bst
from app.type_chart import CHART, TYPES, best_multiplier, single_multiplier


def mk_move(name, type_, power=90, accuracy=100, damage_class="physical", pp=10, move_id=None):
    return Move(
        move_id=move_id if move_id is not None else abs(hash(name)) % 10000,
        name=name,
        name_ko=name,
        type=type_,
        damage_class=damage_class,
        power=power,
        accuracy=accuracy,
        pp=pp,
    )


def mk_card(
    name,
    types,
    *,
    moves=None,
    hp=100,
    attack=100,
    defense=100,
    special_attack=100,
    special_defense=100,
    speed=100,
    scaled=False,
):
    """scaled=False 면 종족값을 주고 내부에서 레벨50 환산한다 (from_row 와 같은 취급)."""
    bst = hp + attack + defense + special_attack + special_defense + speed
    conv_hp = hp if scaled else scaled_hp(hp)
    conv = (lambda v: v) if scaled else scaled_stat
    return Card(
        card_id=name,
        dex_id=1,
        name=name,
        name_ko=name,
        types=types,
        tier=tier_for_bst(bst),
        sprite_url="",
        max_hp=conv_hp,
        attack=conv(attack),
        defense=conv(defense),
        special_attack=conv(special_attack),
        special_defense=conv(special_defense),
        speed=conv(speed),
        bst=bst,
        moves=moves if moves is not None else [mk_move("tackle", "normal")],
    )


# ---------- 타입 상성 ----------

def test_chart_only_lists_non_neutral_matchups():
    """표에 적힌 값은 전부 1.0 이 아니어야 한다 (1.0 은 생략이 규칙)."""
    for attacker, row in CHART.items():
        assert attacker in TYPES
        for defender, mult in row.items():
            assert defender in TYPES, f"{attacker}→{defender}: 모르는 타입"
            assert mult != 1.0, f"{attacker}→{defender}: 1.0 은 적지 않는다"


@pytest.mark.parametrize(
    ("attacker", "defender", "expected"),
    [
        ("water", ["fire"], 2.0),
        ("fire", ["water"], 0.5),
        ("normal", ["ghost"], 0.0),
        ("electric", ["ground"], 0.0),
        ("ice", ["ground", "flying"], 4.0),
        ("grass", ["fire", "flying"], 0.25),
        ("fighting", ["normal"], 2.0),
    ],
)
def test_single_multiplier(attacker, defender, expected):
    assert single_multiplier(attacker, defender) == expected


def test_best_multiplier_picks_the_better_type():
    """카드 선택 화면의 참고용 배율 — 공격자 타입 중 유리한 쪽."""
    assert best_multiplier(["water", "flying"], ["grass"]) == 2.0
    assert best_multiplier(["fire", "flying"], ["grass", "psychic"]) == 2.0


# ---------- 능력치 환산 ----------

def test_scaled_stats_match_the_official_formula():
    """레벨 50, 개체값 31, 노력치 0 기준."""
    assert LEVEL == 50
    assert scaled_hp(78) == 78 + 75    # 리자몽 HP 종족값 78 → 153
    assert scaled_stat(109) == 109 + 20  # 특공 109 → 129
    assert scaled_hp(255) > scaled_hp(100)


# ---------- 데미지 ----------

def test_damage_uses_the_official_formula():
    """base = ((2*L/5 + 2) * 위력 * 공격 / 방어) / 50 + 2, roll 고정.

    자속이 붙지 않도록 공격자 타입과 다른 기술을 쓴다.
    """
    atk = mk_card("a", ["water"], attack=100, scaled=True)
    dfn = mk_card("b", ["normal"], defense=100, scaled=True)
    move = mk_move("ember", "fire", power=90)

    dealt, mult = damage(move, atk, dfn, rng=random.Random(0), roll=1.0)
    expected_base = ((2 * 50 / 5 + 2) * 90 * 100 / 100) / 50 + 2  # = 41.6
    assert mult == 1.0
    assert dealt == int(expected_base)


def test_stab_gives_fifty_percent_more():
    atk = mk_card("a", ["fire"], attack=100, scaled=True)
    dfn = mk_card("b", ["normal"], defense=100, scaled=True)
    rng = random.Random(0)

    same_type, _ = damage(mk_move("m", "fire"), atk, dfn, rng=rng, roll=1.0)
    off_type, _ = damage(mk_move("m", "normal"), atk, dfn, rng=rng, roll=1.0)
    assert same_type == pytest.approx(off_type * 1.5, rel=0.02)


def test_type_effectiveness_scales_damage():
    atk = mk_card("a", ["normal"], attack=100, scaled=True)
    water = mk_card("w", ["water"], defense=100, scaled=True)
    fire = mk_card("f", ["fire"], defense=100, scaled=True)
    rng = random.Random(0)

    strong, m1 = damage(mk_move("m", "water"), atk, fire, rng=rng, roll=1.0)
    weak, m2 = damage(mk_move("m", "fire"), atk, water, rng=rng, roll=1.0)
    assert (m1, m2) == (2.0, 0.5)
    assert strong == pytest.approx(weak * 4, rel=0.05)


def test_immune_matchup_deals_zero():
    atk = mk_card("a", ["electric"], scaled=True)
    ground = mk_card("g", ["ground"], scaled=True)
    dealt, mult = damage(mk_move("bolt", "electric"), atk, ground, rng=random.Random(0))
    assert (dealt, mult) == (0, 0.0)


def test_physical_and_special_use_different_stats():
    """방어가 종잇장이고 특방이 두꺼운 상대에겐 물리기가 더 아파야 한다."""
    atk = mk_card("a", ["normal"], attack=100, special_attack=100, scaled=True)
    wall = mk_card("w", ["normal"], defense=50, special_defense=200, scaled=True)
    rng = random.Random(0)

    phys, _ = damage(mk_move("p", "normal", damage_class="physical"), atk, wall, rng=rng, roll=1.0)
    spec, _ = damage(mk_move("s", "normal", damage_class="special"), atk, wall, rng=rng, roll=1.0)
    assert phys > spec * 3


def test_damage_roll_stays_in_range():
    atk = mk_card("a", ["normal"], scaled=True)
    dfn = mk_card("b", ["normal"], scaled=True)
    move = mk_move("m", "normal")
    rng = random.Random(7)
    rolls = [damage(move, atk, dfn, rng=rng)[0] for _ in range(200)]
    low, high = min(rolls), max(rolls)
    assert low >= high * 0.84  # 0.85~1.00 폭


def test_damage_never_reaches_zero_against_a_wall():
    """상성이 0배가 아닌 한 데미지는 0이 되지 않는다 — 영원히 안 끝나는 라운드를 막는다.

    공식 끝의 `+ 2` 항이 이 바닥을 만든다. 방어가 아무리 높아도 2 언저리는 들어간다.
    """
    weak = mk_card("w", ["normal"], attack=1, scaled=True)
    wall = mk_card("t", ["normal"], defense=10_000, scaled=True)
    dealt, mult = damage(mk_move("m", "normal", power=10), weak, wall, rng=random.Random(0))
    assert mult == 1.0
    assert 1 <= dealt <= 3


# ---------- 명중 ----------

def test_accuracy_check_respects_the_rate():
    rng = random.Random(1234)
    hits = sum(accuracy_check(mk_move("m", "normal", accuracy=70), rng) for _ in range(4000))
    assert 0.66 < hits / 4000 < 0.74


def test_perfect_accuracy_never_misses():
    rng = random.Random(1)
    move = mk_move("m", "normal", accuracy=100)
    assert all(accuracy_check(move, rng) for _ in range(500))


# ---------- 턴 순서 ----------

def test_faster_pokemon_moves_first():
    fast = Fighter.create(mk_card("fast", ["normal"], speed=120))
    slow = Fighter.create(mk_card("slow", ["normal"], speed=60))
    assert turn_order(fast, slow, random.Random(0)) == (0, 1)
    assert turn_order(slow, fast, random.Random(0)) == (1, 0)


def test_speed_tie_is_a_coin_flip():
    a = Fighter.create(mk_card("a", ["normal"], speed=100))
    b = Fighter.create(mk_card("b", ["normal"], speed=100))
    firsts = [turn_order(a, b, random.Random(s))[0] for s in range(200)]
    assert set(firsts) == {0, 1}


# ---------- 턴 처리 ----------

def test_knocked_out_pokemon_does_not_retaliate():
    """먼저 때려서 쓰러뜨리면 상대는 반격하지 못한다 — 스피드가 중요한 이유."""
    nuke = mk_move("nuke", "normal", power=110, move_id=1)
    fast = Fighter.create(mk_card("fast", ["normal"], attack=200, speed=200, moves=[nuke]))
    frail = Fighter.create(
        mk_card("frail", ["normal"], hp=1, defense=1, speed=1, moves=[mk_move("t", "normal", move_id=2)])
    )

    events = resolve_turn({0: fast, 1: frail}, {0: nuke, 1: frail.card.moves[0]}, random.Random(0))
    assert len(events) == 1
    assert events[0].actor == 0
    assert events[0].fainted_target
    assert frail.fainted and not fast.fainted


def test_both_sides_act_when_nobody_faints():
    move_a = mk_move("a", "normal", power=40, move_id=1)
    move_b = mk_move("b", "normal", power=40, move_id=2)
    a = Fighter.create(mk_card("a", ["normal"], hp=200, speed=120, moves=[move_a]))
    b = Fighter.create(mk_card("b", ["normal"], hp=200, speed=60, moves=[move_b]))

    events = resolve_turn({0: a, 1: b}, {0: move_a, 1: move_b}, random.Random(0))
    assert [e.actor for e in events] == [0, 1]
    assert a.hp < a.card.max_hp and b.hp < b.card.max_hp


def test_using_a_move_spends_pp():
    move = mk_move("m", "normal", pp=5, move_id=1)
    a = Fighter.create(mk_card("a", ["normal"], hp=200, moves=[move]))
    b = Fighter.create(mk_card("b", ["normal"], hp=200, moves=[mk_move("x", "normal", move_id=2)]))

    assert a.pp[1] == 5
    resolve_turn({0: a, 1: b}, {0: move, 1: b.card.moves[0]}, random.Random(0))
    assert a.pp[1] == 4


def test_a_miss_deals_no_damage_but_still_costs_pp():
    always_miss = mk_move("miss", "normal", accuracy=1, pp=5, move_id=1)
    a = Fighter.create(mk_card("a", ["normal"], hp=200, moves=[always_miss]))
    b = Fighter.create(mk_card("b", ["normal"], hp=200, moves=[mk_move("x", "normal", move_id=2)]))
    before = b.hp

    events = resolve_turn({0: a, 1: b}, {0: always_miss, 1: b.card.moves[0]}, random.Random(3))
    miss_event = next(e for e in events if e.actor == 0)
    assert miss_event.hit is False
    assert miss_event.damage == 0
    assert b.hp == before
    assert a.pp[1] == 4


# ---------- 발버둥 ----------

def test_out_of_pp_leaves_only_struggle():
    move = mk_move("m", "normal", pp=1, move_id=1)
    f = Fighter.create(mk_card("a", ["normal"], moves=[move]))
    assert f.usable_move_ids() == [1]

    f.pp[1] = 0
    assert f.out_of_pp
    assert f.usable_move_ids() == [STRUGGLE_ID]
    assert f.move_by_id(STRUGGLE_ID) is STRUGGLE


def test_struggle_ignores_type_immunity():
    """발버둥은 노말이지만 고스트에게도 통한다."""
    ghost = mk_card("g", ["ghost"])
    assert move_multiplier(STRUGGLE, ghost) == 1.0
    assert move_multiplier(mk_move("tackle", "normal"), ghost) == 0.0


def test_struggle_hurts_the_user():
    """발버둥은 준 데미지의 1/4 을 자신도 받는다.

    a 를 더 빠르게 만들어 먼저 행동하게 한다. 그래야 이벤트에 기록된 actor_hp 가
    '자기 반동만 반영된' 값이 된다 (뒤이어 b 의 발버둥도 a 를 때리므로).
    """
    a = Fighter.create(mk_card("a", ["normal"], hp=200, attack=150, speed=200, moves=[]))
    b = Fighter.create(mk_card("b", ["normal"], hp=200, speed=10, moves=[]))
    a.pp, b.pp = {}, {}

    events = resolve_turn({0: a, 1: b}, {0: STRUGGLE, 1: STRUGGLE}, random.Random(0))
    hit = next(e for e in events if e.actor == 0)
    assert hit.recoil == max(1, int(hit.damage * 0.25))
    assert hit.actor_hp == a.card.max_hp - hit.recoil
    assert a.hp < hit.actor_hp  # b 의 반격까지 맞아서 더 줄어 있다


# ---------- 라운드 종료 판정 ----------

def make_pair(hp0, hp1, max_hp=200):
    a = Fighter.create(mk_card("a", ["normal"], hp=max_hp, scaled=True))
    b = Fighter.create(mk_card("b", ["normal"], hp=max_hp, scaled=True))
    a.hp, b.hp = hp0, hp1
    return {0: a, 1: b}


def test_round_continues_while_both_stand():
    assert round_winner(make_pair(10, 10), turn=1) is None


def test_fainted_side_loses():
    assert round_winner(make_pair(0, 50), turn=3) == 1
    assert round_winner(make_pair(50, 0), turn=3) == 0


def test_double_faint_is_a_draw():
    """발버둥 반동으로 동시에 쓰러질 수 있다."""
    assert round_winner(make_pair(0, 0), turn=5) == "draw"


def test_turn_cap_decides_by_remaining_hp_ratio():
    assert round_winner(make_pair(120, 40), turn=30, max_turns=30) == 0
    assert round_winner(make_pair(40, 120), turn=30, max_turns=30) == 1
    assert round_winner(make_pair(80, 80), turn=30, max_turns=30) == "draw"


# ---------- 기술 선정 ----------

def moveset_fixture():
    return [
        {"name": "flare", "type": "fire", "power": 90, "accuracy": 100,
         "damage_class": "special", "drain": 0},
        {"name": "blast", "type": "fire", "power": 110, "accuracy": 85,
         "damage_class": "special", "drain": 0},
        {"name": "quake", "type": "ground", "power": 100, "accuracy": 100,
         "damage_class": "physical", "drain": 0},
        {"name": "beam", "type": "ice", "power": 90, "accuracy": 100,
         "damage_class": "special", "drain": 0},
        {"name": "bolt", "type": "electric", "power": 90, "accuracy": 100,
         "damage_class": "special", "drain": 0},
        {"name": "boom", "type": "normal", "power": 250, "accuracy": 100,
         "damage_class": "physical", "drain": 0},          # 위력 상한 초과
        {"name": "blizzard", "type": "ice", "power": 110, "accuracy": 30,
         "damage_class": "special", "drain": 0},           # 명중 하한 미만
        {"name": "recoil", "type": "normal", "power": 110, "accuracy": 100,
         "damage_class": "physical", "drain": -33},        # 반동기
        {"name": "growl", "type": "normal", "power": None, "accuracy": 100,
         "damage_class": "status", "drain": 0},            # 변화기
    ]


def test_moveset_has_four_distinct_types():
    picked = pick_moveset(moveset_fixture(), ["fire"])
    assert len(picked) == 4
    assert len({m["type"] for m in picked}) == 4


def test_moveset_always_includes_stab():
    picked = pick_moveset(moveset_fixture(), ["fire"])
    assert any(m["type"] == "fire" for m in picked)


def test_moveset_excludes_unmodelled_and_unreliable_moves():
    names = {m["name"] for m in pick_moveset(moveset_fixture(), ["fire"])}
    assert "boom" not in names       # 위력 250
    assert "blizzard" not in names   # 명중 30
    assert "recoil" not in names     # 반동
    assert "growl" not in names      # 변화기


def test_expected_power_prefers_reliable_moves():
    accurate = {"power": 90, "accuracy": 100}
    risky = {"power": 110, "accuracy": 70}
    assert expected_power(accurate) > expected_power(risky)


# ---------- 티어 / 딜링 ----------

@pytest.mark.parametrize(
    ("bst", "tier"),
    [(600, "S"), (520, "S"), (519, "A"), (470, "A"), (469, "B"), (420, "B"), (419, "C"), (300, "C")],
)
def test_tier_cutlines(bst, tier):
    assert tier_for_bst(bst) == tier


def test_sample_is_without_replacement():
    picked = weighted_sample_without_replacement(list(range(20)), [1.0] * 20, 6, random.Random(0))
    assert len(picked) == 6 and len(set(picked)) == 6


def test_weights_actually_bias_the_draw():
    rng = random.Random(42)
    counts = {"rare": 0, "common": 0}
    for _ in range(3000):
        picked = weighted_sample_without_replacement(["rare", "common"], [1.0, 5.0], 1, rng)
        counts[picked[0]] += 1
    assert counts["common"] > counts["rare"] * 3


def test_sample_returns_all_when_k_exceeds_population():
    picked = weighted_sample_without_replacement([1, 2, 3], [1.0] * 3, 6, random.Random(0))
    assert sorted(picked) == [1, 2, 3]
