"""로스터 명단과 티어 규칙. design.md §2, §3.

여기엔 "어떤 포켓몬을 쓸지"와 "티어를 어떻게 나눌지"만 있다.
실제 스탯은 PokeAPI 에서 긁어서 DB 에 캐싱한다 (scripts/seed.py).
"""

from __future__ import annotations

# 1세대 중간~최종 진화형 40마리. 전설계(144~146, 150, 151)는 제외 — BST 가 튀어서
# 티어 가중치 설계가 무의미해진다.
ROSTER_DEX_IDS: tuple[int, ...] = (
    3,    # venusaur
    6,    # charizard
    9,    # blastoise
    12,   # butterfree
    15,   # beedrill
    20,   # raticate
    24,   # arbok
    28,   # sandslash
    31,   # nidoqueen
    34,   # nidoking
    38,   # ninetales
    42,   # golbat
    45,   # vileplume
    51,   # dugtrio
    53,   # persian
    57,   # primeape
    59,   # arcanine
    65,   # alakazam
    68,   # machamp
    73,   # tentacruel
    76,   # golem
    78,   # rapidash
    82,   # magneton
    85,   # dodrio
    91,   # cloyster
    94,   # gengar
    95,   # onix
    103,  # exeggutor
    105,  # marowak
    110,  # weezing
    112,  # rhydon
    114,  # tangela
    121,  # starmie
    122,  # mr-mime
    123,  # scyther
    127,  # pinsir
    130,  # gyarados
    131,  # lapras
    143,  # snorlax
    149,  # dragonite
)

# BST 컷라인 (내림차순으로 평가). design.md §3
TIER_THRESHOLDS: tuple[tuple[str, int], ...] = (
    ("S", 520),
    ("A", 470),
    ("B", 420),
    ("C", 0),
)

# 딜링 가중치 — 낮은 티어일수록 잘 나온다.
TIER_WEIGHTS: dict[str, float] = {
    "S": 1.0,
    "A": 2.0,
    "B": 3.0,
    "C": 5.0,
}


# ---------- 기술 선정 규칙 (design.md §4-1) ----------

MOVES_PER_POKEMON = 4

# 기술 후보 필터.
#
# 위력 상한 110 이 핵심이다. 1세대 포켓몬이 배우는 위력 120 이상 기술은 사실상 전부
# **대가가 붙어 있다** — 이판사판태클/플레어드라이브(반동), 솔라빔(차지 턴),
# 역린(연속기 후 혼란), 엄청난힘(능력 하락), 대폭발(자신 기절).
# 우리는 그 대가를 구현하지 않으므로 그대로 넣으면 "무조건 이거 쓰면 됨"이 되어
# 기술 선택이라는 게임의 축이 통째로 사라진다. 그래서 잘라낸다.
MIN_MOVE_POWER = 10
MAX_MOVE_POWER = 110
MIN_MOVE_ACCURACY = 70


def expected_power(move: dict) -> float:
    """위력 × 명중률. 기술을 비교할 때 쓰는 값."""
    return move["power"] * (move["accuracy"] or 100) / 100


def pick_moveset(candidates: list[dict], own_types: list[str]) -> list[dict]:
    """공격 기술 후보에서 4개를 고른다.

    candidates 는 {name, type, power, accuracy, damage_class, ...} 딕셔너리 목록.

    규칙:
      1. **자속(STAB) 기술 1개**를 반드시 넣는다. 자기 타입 중 가장 센 것.
      2. 나머지는 **서로 다른 타입**에서 가장 센 것을 골라 채운다.
      3. 그래도 모자라면 위력순으로 채운다.

    2번이 핵심이다. 단순히 위력순으로 4개를 뽑으면 리자몽이
    플레어드라이브/연옥/열풍/화염방사 — 전부 불꽃 기술을 들고 나온다.
    타입 상성이 재미의 축인 게임에서 기술 타입이 하나면 선택할 게 없어진다.
    """
    usable = [
        m
        for m in candidates
        if m["damage_class"] in ("physical", "special")
        and m["power"]
        and MIN_MOVE_POWER <= m["power"] <= MAX_MOVE_POWER
        and (m["accuracy"] or 100) >= MIN_MOVE_ACCURACY
        # drain != 0 은 반동기(음수) 또는 흡수기(양수). 둘 다 구현하지 않았으므로 제외.
        and not m.get("drain")
    ]
    # **기대 위력**(위력 × 명중률) 내림차순.
    #
    # 그냥 위력순으로 정렬하면 안 된다. 눈보라(위력 110, 명중 70)가
    # 냉동빔(위력 90, 명중 100)을 밀어내는데, 기댓값은 77 vs 90 으로 오히려 손해다.
    # 명중률을 곱해야 "실제로 더 센 기술"이 뽑힌다.
    usable.sort(key=lambda m: (-expected_power(m), -(m["accuracy"] or 100)))

    picked: list[dict] = []
    used_types: set[str] = set()

    stab = next((m for m in usable if m["type"] in own_types), None)
    if stab:
        picked.append(stab)
        used_types.add(stab["type"])

    for move in usable:
        if len(picked) >= MOVES_PER_POKEMON:
            break
        if move in picked or move["type"] in used_types:
            continue
        picked.append(move)
        used_types.add(move["type"])

    for move in usable:  # 타입이 모자라면 중복 타입이라도 채운다
        if len(picked) >= MOVES_PER_POKEMON:
            break
        if move not in picked:
            picked.append(move)

    return picked[:MOVES_PER_POKEMON]


def tier_for_bst(bst: int) -> str:
    """BST 총합에서 티어를 계산한다. 하드코딩된 티어 표는 없다."""
    for tier, floor in TIER_THRESHOLDS:
        if bst >= floor:
            return tier
    return "C"
