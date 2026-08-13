"""전투 엔진. design.md §4.

이 모듈은 DB 도 소켓도 모른다 — 순수 함수/데이터라서 단위 테스트가 쉽다.
난수도 인자로 받는다(`rng`). 안 그러면 데미지 테스트를 쓸 수 없다.
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass, field
from typing import Literal

from app.type_chart import best_multiplier, single_multiplier

# ---------- 규칙 상수 ----------

LEVEL = 50          # 모든 포켓몬은 레벨 50 고정
STAB_BONUS = 1.5    # 자기 타입 기술을 쓰면 1.5배 (Same Type Attack Bonus)
DAMAGE_ROLL = (0.85, 1.00)  # 정식 시리즈와 같은 난수 폭
MAX_TURNS = 30      # 무한 루프 방지

# 발버둥 — PP 가 전부 떨어졌을 때 강제로 쓰는 기술.
STRUGGLE_ID = -1
STRUGGLE_POWER = 50
STRUGGLE_RECOIL = 0.25  # 준 데미지의 1/4 을 자신도 받는다


def scaled_hp(base: int) -> int:
    """레벨 50, 개체값 31, 노력치 0 기준 실제 HP.

    정식 공식: floor((2*B + IV + EV/4) * L / 100) + L + 10
    → L=50, IV=31, EV=0 이면 결국 base + 75 다.
    상수 75 를 그냥 쓰지 않고 공식을 남겨 둔 건, 레벨을 바꾸고 싶을 때
    어디를 건드려야 하는지 보이게 하려는 것.
    """
    return (2 * base + 31) * LEVEL // 100 + LEVEL + 10


def scaled_stat(base: int) -> int:
    """HP 를 제외한 능력치. floor((2*B + IV + EV/4) * L / 100) + 5"""
    return (2 * base + 31) * LEVEL // 100 + 5


# ---------- 데이터 ----------

@dataclass(frozen=True, slots=True)
class Move:
    move_id: int
    name: str
    name_ko: str
    type: str
    damage_class: Literal["physical", "special"]
    power: int
    accuracy: int
    pp: int
    flavor_ko: str = ""

    def to_payload(self, *, current_pp: int | None = None) -> dict:
        """기술 정보. `current_pp` 를 빼면 상대에게 보여줄 수 있는 형태가 된다.

        상대의 남은 PP 는 숨긴다 — 정식 시리즈에서도 안 보이고,
        "무엇을 숨기고 무엇을 보여줄지"를 한 번 더 보여주는 지점이다.
        """
        payload = {
            "move_id": self.move_id,
            "name": self.name,
            "name_ko": self.name_ko,
            "type": self.type,
            "damage_class": self.damage_class,
            "power": self.power,
            "accuracy": self.accuracy,
            "max_pp": self.pp,
            "flavor_ko": self.flavor_ko,
        }
        if current_pp is not None:
            payload["pp"] = current_pp
        return payload


STRUGGLE = Move(
    move_id=STRUGGLE_ID,
    name="struggle",
    name_ko="발버둥",
    type="normal",
    damage_class="physical",
    power=STRUGGLE_POWER,
    accuracy=100,
    pp=0,
    flavor_ko="쓸 수 있는 기술이 없을 때 몸을 부딪쳐 공격한다. 준 데미지의 1/4 을 자신도 받는다.",
)


@dataclass(frozen=True, slots=True)
class Card:
    """손패에 있는 카드 1장 (인메모리 전용). 스탯은 전부 레벨 50 환산값."""

    card_id: str
    dex_id: int
    name: str
    name_ko: str
    types: list[str]
    tier: str
    sprite_url: str
    max_hp: int
    attack: int
    defense: int
    special_attack: int
    special_defense: int
    speed: int
    bst: int
    moves: list[Move]

    @staticmethod
    def from_row(row) -> "Card":
        """models.Pokemon 행 → 카드. 매번 새 card_id 를 붙인다."""
        return Card(
            card_id=uuid.uuid4().hex,
            dex_id=row.dex_id,
            name=row.name,
            name_ko=row.name_ko,
            types=list(row.types),
            tier=row.tier,
            sprite_url=row.sprite_url,
            max_hp=scaled_hp(row.hp),
            attack=scaled_stat(row.attack),
            defense=scaled_stat(row.defense),
            special_attack=scaled_stat(row.special_attack),
            special_defense=scaled_stat(row.special_defense),
            speed=scaled_stat(row.speed),
            bst=row.bst,
            moves=[
                Move(
                    move_id=pm.move.id,
                    name=pm.move.name,
                    name_ko=pm.move.name_ko,
                    type=pm.move.type,
                    damage_class=pm.move.damage_class,
                    power=pm.move.power,
                    accuracy=pm.move.accuracy,
                    pp=pm.move.pp,
                    flavor_ko=pm.move.flavor_ko,
                )
                for pm in row.moves
            ],
        )

    def to_payload(self) -> dict:
        return {
            "card_id": self.card_id,
            "dex_id": self.dex_id,
            "name": self.name,
            "name_ko": self.name_ko,
            "types": self.types,
            "tier": self.tier,
            "bst": self.bst,
            "sprite_url": self.sprite_url,
            "stats": {
                "hp": self.max_hp,
                "attack": self.attack,
                "defense": self.defense,
                "special_attack": self.special_attack,
                "special_defense": self.special_defense,
                "speed": self.speed,
            },
        }


@dataclass(slots=True)
class Fighter:
    """전투 중인 포켓몬 1마리의 가변 상태 (HP, 남은 PP)."""

    card: Card
    hp: int
    pp: dict[int, int] = field(default_factory=dict)

    @staticmethod
    def create(card: Card) -> "Fighter":
        return Fighter(card=card, hp=card.max_hp, pp={m.move_id: m.pp for m in card.moves})

    @property
    def fainted(self) -> bool:
        return self.hp <= 0

    @property
    def hp_ratio(self) -> float:
        return self.hp / self.card.max_hp

    def move_by_id(self, move_id: int) -> Move | None:
        if move_id == STRUGGLE_ID:
            return STRUGGLE if self.out_of_pp else None
        return next((m for m in self.card.moves if m.move_id == move_id), None)

    def has_pp(self, move_id: int) -> bool:
        return self.pp.get(move_id, 0) > 0

    @property
    def out_of_pp(self) -> bool:
        """쓸 수 있는 기술이 하나도 없으면 발버둥밖에 못 쓴다."""
        return not any(v > 0 for v in self.pp.values())

    def usable_move_ids(self) -> list[int]:
        if self.out_of_pp:
            return [STRUGGLE_ID]
        return [m.move_id for m in self.card.moves if self.has_pp(m.move_id)]

    def to_payload(self, *, private: bool, versus: Card | None = None) -> dict:
        """private=True 면 내 것(남은 PP 포함), False 면 상대에게 보여줄 것(PP 제외).

        `versus` 를 주면 기술마다 상성 배율을 함께 계산해 넣는다.
        **상성 계산을 클라이언트에서 하지 않는 이유**: 타입 상성표를 프론트에도 두면
        규칙이 두 군데 살게 되고, 한쪽만 고치는 순간 화면과 판정이 어긋난다.
        규칙은 서버에만 두고 클라이언트는 결과만 그린다.
        """
        moves = []
        for m in self.card.moves:
            entry = m.to_payload(current_pp=self.pp.get(m.move_id) if private else None)
            if private and versus is not None:
                entry["effectiveness"] = move_multiplier(m, versus)
            moves.append(entry)

        payload = {
            "card": self.card.to_payload(),
            "hp": max(0, self.hp),
            "max_hp": self.card.max_hp,
            "moves": moves,
        }
        if private:
            payload["out_of_pp"] = self.out_of_pp
        return payload


# ---------- 계산 ----------

def move_multiplier(move: Move, defender: Card) -> float:
    """기술 타입 → 방어자 타입 배율. 발버둥은 상성을 무시하고 항상 1배."""
    if move.move_id == STRUGGLE_ID:
        return 1.0
    return single_multiplier(move.type, defender.types)


def damage(
    move: Move,
    attacker: Card,
    defender: Card,
    *,
    rng: random.Random,
    roll: float | None = None,
) -> tuple[int, float]:
    """정식 시리즈의 데미지 공식(간소화판).

        base = ((2*L/5 + 2) * 위력 * 공격 / 방어) / 50 + 2
        최종 = base × 자속 × 타입상성 × 난수(0.85~1.00)

    상태이상·급소·날씨·특성은 구현하지 않는다(design.md §11).
    반환값: (데미지, 타입배율)
    """
    multiplier = move_multiplier(move, defender)
    if multiplier == 0:
        return 0, 0.0

    if move.damage_class == "physical":
        atk, dfn = attacker.attack, defender.defense
    else:
        atk, dfn = attacker.special_attack, defender.special_defense

    base = ((2 * LEVEL / 5 + 2) * move.power * atk / dfn) / 50 + 2
    stab = STAB_BONUS if (move.move_id != STRUGGLE_ID and move.type in attacker.types) else 1.0
    if roll is None:
        roll = rng.uniform(*DAMAGE_ROLL)

    return max(1, int(base * stab * multiplier * roll)), multiplier


def accuracy_check(move: Move, rng: random.Random) -> bool:
    return rng.randrange(100) < move.accuracy


# ---------- 턴 처리 ----------

@dataclass(slots=True)
class ActionEvent:
    """한 번의 공격에서 일어난 일. 클라이언트 연출의 재료."""

    actor: int              # slot (0 또는 1)
    move: Move
    hit: bool
    damage: int = 0
    multiplier: float = 1.0
    recoil: int = 0
    target_hp: int = 0
    actor_hp: int = 0
    fainted_target: bool = False
    fainted_actor: bool = False

    def to_payload(self, viewer_slot: int) -> dict:
        return {
            "actor": "you" if self.actor == viewer_slot else "opponent",
            "move": self.move.to_payload(),
            "hit": self.hit,
            "damage": self.damage,
            "multiplier": self.multiplier,
            "recoil": self.recoil,
            "target_hp": self.target_hp,
            "actor_hp": self.actor_hp,
            "fainted_target": self.fainted_target,
            "fainted_actor": self.fainted_actor,
        }


def turn_order(a: Fighter, b: Fighter, rng: random.Random) -> tuple[int, ...]:
    """스피드가 빠른 쪽 먼저. 같으면 동전던지기 (정식 시리즈와 동일)."""
    if a.card.speed != b.card.speed:
        return (0, 1) if a.card.speed > b.card.speed else (1, 0)
    return (0, 1) if rng.random() < 0.5 else (1, 0)


def resolve_turn(
    fighters: dict[int, Fighter],
    chosen: dict[int, Move],
    rng: random.Random,
) -> list[ActionEvent]:
    """한 턴을 처리한다. 양쪽이 고른 기술을 스피드 순으로 실행.

    먼저 때린 쪽이 상대를 쓰러뜨리면 상대는 반격하지 못한다 — 스피드가 중요한 이유.
    """
    events: list[ActionEvent] = []

    for slot in turn_order(fighters[0], fighters[1], rng):
        attacker, defender = fighters[slot], fighters[1 - slot]
        if attacker.fainted or defender.fainted:
            break

        move = chosen[slot]
        if move.move_id != STRUGGLE_ID:
            attacker.pp[move.move_id] = max(0, attacker.pp.get(move.move_id, 0) - 1)

        if not accuracy_check(move, rng):
            events.append(
                ActionEvent(
                    actor=slot, move=move, hit=False,
                    target_hp=defender.hp, actor_hp=attacker.hp,
                )
            )
            continue

        dealt, multiplier = damage(move, attacker.card, defender.card, rng=rng)
        defender.hp = max(0, defender.hp - dealt)

        recoil = 0
        if move.move_id == STRUGGLE_ID and dealt > 0:
            recoil = max(1, int(dealt * STRUGGLE_RECOIL))
            attacker.hp = max(0, attacker.hp - recoil)

        events.append(
            ActionEvent(
                actor=slot, move=move, hit=True,
                damage=dealt, multiplier=multiplier, recoil=recoil,
                target_hp=defender.hp, actor_hp=attacker.hp,
                fainted_target=defender.fainted, fainted_actor=attacker.fainted,
            )
        )

    return events


def round_winner(
    fighters: dict[int, Fighter], turn: int, max_turns: int = MAX_TURNS
) -> Literal[0, 1, None] | str:
    """라운드가 끝났는지, 끝났다면 누가 이겼는지.

    반환: 0 / 1 (승자 slot), "draw", 또는 None(아직 진행 중)
    """
    down0, down1 = fighters[0].fainted, fighters[1].fainted

    if down0 and down1:
        return "draw"          # 발버둥 반동으로 동시에 쓰러질 수 있다
    if down1:
        return 0
    if down0:
        return 1

    if turn >= max_turns:
        # 서로 결정타를 못 내는 교착. 남은 체력 비율로 가른다.
        r0, r1 = fighters[0].hp_ratio, fighters[1].hp_ratio
        if r0 == r1:
            return "draw"
        return 0 if r0 > r1 else 1

    return None


# 타입 상성 요약(카드 선택 화면에서 참고용으로 쓴다)
def matchup_hint(attacker_types: list[str], defender_types: list[str]) -> float:
    return best_multiplier(attacker_types, defender_types)
