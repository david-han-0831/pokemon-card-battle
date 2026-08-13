"""PokeAPI → 우리 DB 시딩 스크립트.

실행:
    python -m scripts.seed                     # 로스터 + 기술 시딩
    python -m scripts.seed --show-distribution # 시딩 후 BST 분포/티어 컷라인 확인
    python -m scripts.seed --show-movesets     # 포켓몬별로 뽑힌 기술 4개 확인
    python -m scripts.seed --force             # 이미 있어도 다시 긁어서 갱신

왜 캐싱하는가 (교육 포인트):
  - PokeAPI 는 무료 공개 API 다. 게임 턴마다 호출하면 남의 서버에 민폐고,
    응답이 100~300ms 라 실시간 게임에 쓸 수 없고, 그쪽이 죽으면 우리도 죽는다.
  - 로스터와 기술은 거의 안 바뀌는 데이터다. 한 번 긁어서 우리 DB 에 넣어두면 끝.
  - 기술은 특히 그렇다. 포켓몬마다 따로 부르면 2000번 넘게 부르게 되는데,
    이름으로 합집합을 먼저 만들어 한 번씩만 부르면 1/3 로 줄어든다.
    이 "합집합 먼저, 요청은 나중에" 패턴이 이 스크립트의 핵심이다.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections import Counter

import httpx
from sqlalchemy import delete, select

from app.db import SessionLocal, engine
from app.models import Base, Move, Pokemon, PokemonMove, TypeInfo
from app.type_chart import TYPES
from app.roster import (
    MOVES_PER_POKEMON,
    ROSTER_DEX_IDS,
    TIER_THRESHOLDS,
    TIER_WEIGHTS,
    pick_moveset,
    tier_for_bst,
)

POKEAPI = "https://pokeapi.co/api/v2"
CONCURRENCY = 8  # 공개 API 이므로 동시 요청은 얌전하게

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("seed")


# 레벨업 + 기술머신(TM/HM)까지만 본다. 교배·교육기까지 넣으면 포켓몬마다 100개가 넘고
# "이 포켓몬이 실제로 쓸 법한 기술"과도 멀어진다.
#
# 레벨업만 쓰면 안 되는 이유: 1세대 자력기 풀은 타입이 지독하게 좁다.
# 이상해꽃의 공격 자력기는 풀·노말 두 타입뿐이라 기술 4개가 풀 3 + 노말 1 이 된다.
# 타입 상성이 재미의 축인데 낼 수 있는 타입이 하나면 고를 게 없다.
# 기술머신은 실제 게임에서도 커버리지를 채우는 수단이므로 여기 포함하는 게 맞다.
LEARN_METHODS = {"level-up", "machine"}


def pick_sprite(data: dict) -> str:
    """official-artwork 을 우선한다 — 해상도가 높아 Three.js 빌보드에 쓰기 좋다."""
    sprites = data.get("sprites", {})
    official = sprites.get("other", {}).get("official-artwork", {}).get("front_default")
    return official or sprites.get("front_default") or ""


def pick_korean_name(payload: dict, fallback: str) -> str:
    for entry in payload.get("names", []):
        if entry.get("language", {}).get("name") == "ko":
            return entry["name"]
    return fallback


def pick_korean_flavor(payload: dict) -> str:
    """기술 설명(한글). 여러 버전이 쌓여 있으므로 가장 최근 것을 쓴다."""
    ko = [
        e["flavor_text"]
        for e in payload.get("flavor_text_entries", [])
        if e.get("language", {}).get("name") == "ko"
    ]
    if not ko:
        return ""
    # 게임 텍스트라 줄바꿈·폼피드가 섞여 있다.
    return " ".join(ko[-1].split())


# 타입 아이콘은 세대·게임별로 여러 벌이 있다. 최신 쪽을 우선한다.
ICON_GENERATION_PREFERENCE = ("generation-ix", "generation-viii", "generation-vii", "generation-vi")


def pick_type_icon(payload: dict, key: str) -> str:
    """`/type/{name}` sprites 에서 아이콘 하나를 고른다.

    구조가 sprites[세대][게임]{name_icon, symbol_icon} 로 2단계인데
    비어 있는 칸이 많아서(구세대엔 symbol_icon 이 없다) 선호 세대 순으로 훑다가
    처음 나오는 걸 쓴다.

    key="name_icon"   → 타입 이름이 적힌 가로로 긴 배지
    key="symbol_icon" → 심볼만 있는 정사각 아이콘
    """
    sprites = payload.get("sprites") or {}
    generations = [g for g in ICON_GENERATION_PREFERENCE if g in sprites]
    generations += [g for g in sprites if g not in generations]

    for gen in generations:
        for game in (sprites.get(gen) or {}).values():
            icon = (game or {}).get(key)
            if icon:
                return icon
    return ""


def learnable_move_names(pokemon: dict) -> set[str]:
    names = set()
    for entry in pokemon["moves"]:
        if any(
            detail["move_learn_method"]["name"] in LEARN_METHODS
            for detail in entry["version_group_details"]
        ):
            names.add(entry["move"]["name"])
    return names


async def fetch_json(client: httpx.AsyncClient, url: str, sem: asyncio.Semaphore) -> dict:
    async with sem:
        res = await client.get(url)
        res.raise_for_status()
        return res.json()


async def seed(force: bool) -> tuple[list[Pokemon], dict[int, list[Move]]]:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as session:
        existing = set((await session.execute(select(Pokemon.dex_id))).scalars().all())
        has_moves = set(
            (await session.execute(select(PokemonMove.pokemon_dex_id))).scalars().all()
        )
        has_types = set((await session.execute(select(TypeInfo.name))).scalars().all())

    need_seed = (
        force
        or set(ROSTER_DEX_IDS) - existing
        or set(ROSTER_DEX_IDS) - has_moves
        or set(TYPES) - has_types
    )
    if not need_seed:
        logger.info("이미 %d마리 + 기술이 들어 있습니다. 다시 긁으려면 --force.", len(existing))
        return await load_all()

    sem = asyncio.Semaphore(CONCURRENCY)
    async with httpx.AsyncClient(timeout=30.0) as client:
        logger.info("0/3 타입 %d종 (한글명 + 아이콘)...", len(TYPES))
        type_payloads = await asyncio.gather(
            *(fetch_json(client, f"{POKEAPI}/type/{t}", sem) for t in TYPES)
        )

        logger.info("1/3 포켓몬 %d마리...", len(ROSTER_DEX_IDS))
        mons = await asyncio.gather(
            *(fetch_json(client, f"{POKEAPI}/pokemon/{d}", sem) for d in ROSTER_DEX_IDS)
        )
        species = await asyncio.gather(
            *(fetch_json(client, f"{POKEAPI}/pokemon-species/{d}", sem) for d in ROSTER_DEX_IDS)
        )

        # ★ 합집합을 먼저 만들고 한 번씩만 부른다.
        move_names = sorted(set().union(*(learnable_move_names(m) for m in mons)))
        naive = sum(len(learnable_move_names(m)) for m in mons)
        logger.info("2/3 기술 %d개 (중복 제거 안 했으면 %d번 부를 뻔했다)...", len(move_names), naive)
        move_payloads = await asyncio.gather(
            *(fetch_json(client, f"{POKEAPI}/move/{n}", sem) for n in move_names)
        )

    by_name = {p["name"]: p for p in move_payloads}

    # --- 기술 레코드 (공격 기술만) ---
    move_rows: dict[str, Move] = {}
    for payload in move_payloads:
        if payload["damage_class"]["name"] not in ("physical", "special"):
            continue
        if not payload["power"]:
            continue
        move_rows[payload["name"]] = Move(
            id=payload["id"],
            name=payload["name"],
            name_ko=pick_korean_name(payload, payload["name"]),
            type=payload["type"]["name"],
            damage_class=payload["damage_class"]["name"],
            power=payload["power"],
            accuracy=payload["accuracy"] or 100,  # null = 반드시 명중
            pp=payload["pp"] or 10,
            flavor_ko=pick_korean_flavor(payload),
        )

    type_rows = [
        TypeInfo(
            name=payload["name"],
            name_ko=pick_korean_name(payload, payload["name"]),
            icon_url=pick_type_icon(payload, "name_icon"),
            symbol_url=pick_type_icon(payload, "symbol_icon"),
        )
        for payload in type_payloads
    ]
    missing_icon = [t.name for t in type_rows if not t.icon_url]
    if missing_icon:
        logger.warning("타입 아이콘을 못 찾았습니다: %s", missing_icon)

    # --- 포켓몬 + 기술 배치 ---
    logger.info("3/3 저장 중...")
    pokemon_rows: list[Pokemon] = []
    movesets: dict[int, list[str]] = {}

    for mon, spec in zip(mons, species, strict=True):
        stats = {s["stat"]["name"]: s["base_stat"] for s in mon["stats"]}
        types = [t["type"]["name"] for t in sorted(mon["types"], key=lambda t: t["slot"])]
        bst = sum(stats.values())

        candidates = [
            {
                "name": name,
                "type": by_name[name]["type"]["name"],
                "power": by_name[name]["power"],
                "accuracy": by_name[name]["accuracy"],
                "damage_class": by_name[name]["damage_class"]["name"],
                # drain: 음수면 반동기, 양수면 흡수기. 둘 다 구현 안 했으므로 제외 대상.
                "drain": (by_name[name].get("meta") or {}).get("drain", 0),
            }
            for name in learnable_move_names(mon)
            if name in move_rows
        ]
        chosen = pick_moveset(candidates, types)
        if len(chosen) < MOVES_PER_POKEMON:
            logger.warning("%s: 기술이 %d개뿐입니다", mon["name"], len(chosen))
        movesets[mon["id"]] = [c["name"] for c in chosen]

        pokemon_rows.append(
            Pokemon(
                dex_id=mon["id"],
                name=mon["name"],
                name_ko=pick_korean_name(spec, mon["name"]),
                types=types,
                hp=stats["hp"],
                attack=stats["attack"],
                defense=stats["defense"],
                special_attack=stats["special-attack"],
                special_defense=stats["special-defense"],
                speed=stats["speed"],
                bst=bst,
                tier=tier_for_bst(bst),
                sprite_url=pick_sprite(mon),
            )
        )

    async with SessionLocal() as session:
        for type_row in type_rows:
            await session.merge(type_row)
        for move in move_rows.values():
            await session.merge(move)
        await session.flush()

        for row in pokemon_rows:
            await session.merge(row)
        await session.flush()

        # 기술 배치는 통째로 갈아엎는다 (선정 규칙이 바뀌면 결과가 달라지므로)
        await session.execute(delete(PokemonMove))
        for dex_id, names in movesets.items():
            for slot, name in enumerate(names):
                session.add(
                    PokemonMove(pokemon_dex_id=dex_id, slot=slot, move_id=move_rows[name].id)
                )
        await session.commit()

    logger.info(
        "타입 %d종, 포켓몬 %d마리, 공격기술 %d개 저장 완료.",
        len(type_rows), len(pokemon_rows), len(move_rows),
    )
    return await load_all()


async def load_all() -> tuple[list[Pokemon], dict[int, list[Move]]]:
    async with SessionLocal() as session:
        rows = list(
            (await session.execute(select(Pokemon).order_by(Pokemon.bst.desc()))).scalars().all()
        )
        movesets = {row.dex_id: [pm.move for pm in row.moves] for row in rows}
    return rows, movesets


def show_distribution(rows: list[Pokemon]) -> None:
    print("\n=== BST 분포 (내림차순) ===")
    prev_tier = None
    for row in rows:
        if row.tier != prev_tier:
            floor = dict(TIER_THRESHOLDS)[row.tier]
            print(f"\n--- {row.tier} 티어 (BST >= {floor}, 딜링 가중치 {TIER_WEIGHTS[row.tier]}) ---")
            prev_tier = row.tier
        print(f"  {row.bst:>3}  #{row.dex_id:<4} {row.name_ko} ({row.name}) [{'/'.join(row.types)}]")

    counts = Counter(r.tier for r in rows)
    total_weight = sum(TIER_WEIGHTS[r.tier] for r in rows)
    print("\n=== 티어별 마릿수 / 카드 1장이 그 티어일 확률 ===")
    for tier in ("S", "A", "B", "C"):
        n = counts.get(tier, 0)
        if n:
            print(f"  {tier}: {n:>2}마리   딜링 확률 = {n * TIER_WEIGHTS[tier] / total_weight:6.1%}")


def show_movesets(rows: list[Pokemon], movesets: dict[int, list[Move]]) -> None:
    print("\n=== 기술 구성 (자속 1개 + 타입 다양성) ===")
    for row in sorted(rows, key=lambda r: r.dex_id):
        print(f"\n#{row.dex_id} {row.name_ko} [{'/'.join(row.types)}]")
        for move in movesets.get(row.dex_id, []):
            stab = "  <STAB>" if move.type in row.types else ""
            print(
                f"    {move.name_ko:<12} {move.type:<9} {move.damage_class:<8} "
                f"위력{move.power:>4}  명중{move.accuracy:>4}  PP{move.pp:>3}{stab}"
            )
    type_counts = Counter(len({m.type for m in mv}) for mv in movesets.values() if mv)
    print("\n포켓몬별 기술 타입 가짓수 분포:", dict(sorted(type_counts.items())))


async def main() -> None:
    parser = argparse.ArgumentParser(description="PokeAPI 로스터 + 기술 시딩")
    parser.add_argument("--force", action="store_true", help="이미 있어도 다시 긁는다")
    parser.add_argument("--show-distribution", action="store_true", help="BST 분포 출력")
    parser.add_argument("--show-movesets", action="store_true", help="기술 구성 출력")
    args = parser.parse_args()

    rows, movesets = await seed(force=args.force)
    if args.show_distribution:
        show_distribution(rows)
    if args.show_movesets:
        show_movesets(rows, movesets)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
