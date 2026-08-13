"""딜링(카드 배분). design.md §3.

티어 가중치를 적용한 비복원 추출.
`random.choices` 는 복원추출이라 같은 종이 손패에 중복될 수 있어서 쓰지 않는다.
"""

from __future__ import annotations

import random
from collections.abc import Sequence

from app.battle import Card
from app.roster import TIER_WEIGHTS


def weighted_sample_without_replacement(
    population: Sequence, weights: Sequence[float], k: int, rng: random.Random
) -> list:
    """가중치 비복원 추출.

    구현: Efraimidis-Spirakis 알고리즘.
    각 원소에 key = U^(1/w) (U~Uniform(0,1)) 를 매겨 상위 k개를 고르면
    가중치에 비례한 비복원 추출이 된다. 뽑을 때마다 재정규화하는 것보다 간단하고 빠르다.
    """
    if k >= len(population):
        return list(population)

    keyed = []
    for item, w in zip(population, weights, strict=True):
        if w <= 0:
            continue
        u = rng.random()
        # u == 0.0 이면 log(0) 이므로 아주 작은 값으로 밀어 준다.
        u = max(u, 1e-12)
        keyed.append((u ** (1.0 / w), item))

    keyed.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in keyed[:k]]


def deal_hand(pool: Sequence, hand_size: int, rng: random.Random | None = None) -> list[Card]:
    """로스터(models.Pokemon 행 목록)에서 손패 하나를 만든다.

    반환되는 Card 는 매번 새 card_id 를 갖는 새 인스턴스다.
    두 플레이어에게 각각 호출하므로, 같은 종이 양쪽에 나올 수는 있다(설계 의도).
    """
    rng = rng or random.Random()
    weights = [TIER_WEIGHTS.get(row.tier, 1.0) for row in pool]
    picked = weighted_sample_without_replacement(pool, weights, hand_size, rng)
    return [Card.from_row(row) for row in picked]
