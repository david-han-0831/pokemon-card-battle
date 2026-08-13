/**
 * 타입별 기술 이펙트 정의.
 *
 * **PokeAPI 는 기술 이미지를 주지 않는다** (`/move/{name}` 에 sprite 계열 키가 아예 없다).
 * 그래서 이펙트는 내려받는 게 아니라 **코드로 만든다** — 스프라이트 빌보드로 3D 를 흉내낸 것과 같은 접근이다.
 *
 * 구조:
 *   - `MODES`  : 파티클을 어떻게 뿌릴지 (분사 패턴). 11가지.
 *   - `EFFECTS`: 타입 18종 → 모드 + 색 + 물리 파라미터.
 *
 * 모드를 공유하되 색·속도·중력·크기가 전부 달라서 18종이 서로 다르게 보인다.
 * 이펙트 하나를 추가하려면 EFFECTS 에 한 줄만 쓰면 된다.
 */

const TAU = Math.PI * 2

/** 각 모드는 파티클 i 의 시작 위치와 속도를 정한다. (x, y, z, vx, vy, vz) */
export const MODES = {
  /** 대상 자리에서 사방으로 터진다 */
  burst(i, n, cfg, from, to, out) {
    const theta = Math.random() * TAU
    const phi = Math.acos(2 * Math.random() - 1)
    const s = cfg.speed * (0.4 + Math.random() * 0.6)
    out.set(to, 1.5, 0,
      Math.sin(phi) * Math.cos(theta) * s,
      Math.cos(phi) * s,
      Math.sin(phi) * Math.sin(theta) * s)
  },

  /** 공격자 쪽에서 대상 쪽으로 날아간다 */
  projectile(i, n, cfg, from, to, out) {
    const dir = Math.sign(to - from) || 1
    const spread = cfg.spread ?? 0.3
    out.set(
      from + dir * 0.7,
      1.5 + (Math.random() - 0.5) * spread * 2,
      (Math.random() - 0.5) * spread * 2,
      dir * cfg.speed * (0.8 + Math.random() * 0.4),
      (Math.random() - 0.5) * cfg.speed * spread * 0.6,
      (Math.random() - 0.5) * cfg.speed * spread * 0.6,
    )
  },

  /** 두 지점을 잇는 직선 위에 촘촘히 깔린다 (광선) */
  beam(i, n, cfg, from, to, out) {
    const t = i / n
    const jitter = cfg.spread ?? 0.12
    out.set(
      from + (to - from) * t,
      1.5 + (Math.random() - 0.5) * jitter * 2,
      (Math.random() - 0.5) * jitter * 2,
      (Math.random() - 0.5) * cfg.speed,
      (Math.random() - 0.5) * cfg.speed,
      (Math.random() - 0.5) * cfg.speed,
    )
  },

  /** 대상 발밑에서 솟구친다 */
  ground(i, n, cfg, from, to, out) {
    const r = Math.random() * 1.3
    const theta = Math.random() * TAU
    out.set(
      to + Math.cos(theta) * r,
      0.05,
      Math.sin(theta) * r,
      Math.cos(theta) * cfg.speed * 0.25,
      cfg.speed * (0.7 + Math.random() * 0.5),
      Math.sin(theta) * cfg.speed * 0.25,
    )
  },

  /** 대상 주위로 퍼지는 수평 링 */
  ring(i, n, cfg, from, to, out) {
    const theta = (i / n) * TAU
    out.set(to, 1.5, 0,
      Math.cos(theta) * cfg.speed,
      (Math.random() - 0.5) * 0.6,
      Math.sin(theta) * cfg.speed)
  },

  /** 대상을 감아 올라가는 나선 */
  spiral(i, n, cfg, from, to, out) {
    const t = i / n
    const theta = t * TAU * 3
    const r = 0.9
    out.set(
      to + Math.cos(theta) * r,
      0.3 + t * 2.2,
      Math.sin(theta) * r,
      -Math.sin(theta) * cfg.speed * 0.5,
      cfg.speed * 0.5,
      Math.cos(theta) * cfg.speed * 0.5,
    )
  },

  /** 큰 파편이 회전하며 흩어진다 */
  shards(i, n, cfg, from, to, out) {
    const theta = Math.random() * TAU
    const s = cfg.speed * (0.6 + Math.random() * 0.8)
    out.set(to, 1.6, 0,
      Math.cos(theta) * s,
      Math.abs(Math.sin(theta)) * s * 0.8 + 1.5,
      (Math.random() - 0.5) * s)
  },

  /** 위에서 쏟아진다 */
  rain(i, n, cfg, from, to, out) {
    out.set(
      to + (Math.random() - 0.5) * 2.4,
      3.4 + Math.random() * 1.2,
      (Math.random() - 0.5) * 1.6,
      0,
      -cfg.speed,
      0,
    )
  },

  /** 바깥 껍질에서 안쪽으로 빨려든다 */
  implode(i, n, cfg, from, to, out) {
    const theta = Math.random() * TAU
    const phi = Math.acos(2 * Math.random() - 1)
    const r = 2.2
    const x = Math.sin(phi) * Math.cos(theta) * r
    const y = Math.cos(phi) * r
    const z = Math.sin(phi) * Math.sin(theta) * r
    out.set(to + x, 1.5 + y, z,
      (-x / r) * cfg.speed, (-y / r) * cfg.speed, (-z / r) * cfg.speed)
  },

  /** 제자리에서 반짝이며 천천히 흩어진다 */
  sparkle(i, n, cfg, from, to, out) {
    const theta = Math.random() * TAU
    const r = Math.random() * 1.4
    out.set(
      to + Math.cos(theta) * r,
      1.0 + Math.random() * 1.4,
      Math.sin(theta) * r,
      (Math.random() - 0.5) * cfg.speed * 0.4,
      cfg.speed * 0.3,
      (Math.random() - 0.5) * cfg.speed * 0.4,
    )
  },

  /** 흐느적거리며 떠오른다 */
  drift(i, n, cfg, from, to, out) {
    const theta = Math.random() * TAU
    const r = Math.random() * 1.1
    out.set(
      to + Math.cos(theta) * r,
      0.9 + Math.random() * 1.2,
      Math.sin(theta) * r,
      Math.cos(theta) * cfg.speed * 0.3,
      cfg.speed * (0.4 + Math.random() * 0.4),
      Math.sin(theta) * cfg.speed * 0.3,
    )
  },
}

/**
 * 타입 18종.
 *   colors : [시작색, 끝색] — 파티클마다 두 색을 섞어 그라데이션을 만든다
 *   gravity: 양수면 떠오르고 음수면 떨어진다
 *   drag   : 클수록 빨리 감속 (0 이면 등속)
 */
export const EFFECTS = {
  normal:   { mode: 'burst',      colors: [0xffffff, 0xb9b9c4], count: 130, size: 0.10, speed: 5.0, gravity: -3, drag: 1.4, life: 0.7 },
  fire:     { mode: 'projectile', colors: [0xff4d00, 0xffd166], count: 200, size: 0.15, speed: 11,  gravity: 2.2, drag: 1.8, life: 0.85, spread: 0.35, impact: true },
  water:    { mode: 'projectile', colors: [0x1f7fff, 0xa8e0ff], count: 190, size: 0.13, speed: 12,  gravity: -5, drag: 0.8, life: 0.9,  spread: 0.4,  impact: true },
  electric: { mode: 'beam',       colors: [0xfff27a, 0xffffff], count: 220, size: 0.11, speed: 7.0, gravity: 0,  drag: 3.0, life: 0.42, spread: 0.18 },
  grass:    { mode: 'spiral',     colors: [0x3ddc6b, 0xd6ff9e], count: 180, size: 0.12, speed: 4.5, gravity: 0.6, drag: 1.0, life: 1.0 },
  ice:      { mode: 'shards',     colors: [0x7fe3ff, 0xffffff], count: 110, size: 0.19, speed: 6.5, gravity: -7, drag: 0.5, life: 0.95 },
  fighting: { mode: 'burst',      colors: [0xff3b3b, 0xffb199], count: 150, size: 0.14, speed: 9.5, gravity: -4, drag: 2.6, life: 0.5 },
  poison:   { mode: 'drift',      colors: [0xb14cff, 0xf0b6ff], count: 160, size: 0.16, speed: 2.6, gravity: 1.6, drag: 0.6, life: 1.25 },
  ground:   { mode: 'ground',     colors: [0xc08a4a, 0x7a5227], count: 200, size: 0.17, speed: 8.0, gravity: -9, drag: 0.3, life: 1.0 },
  flying:   { mode: 'ring',       colors: [0xdcecff, 0xffffff], count: 170, size: 0.11, speed: 7.5, gravity: 0.8, drag: 1.2, life: 0.8 },
  psychic:  { mode: 'ring',       colors: [0xff4dc4, 0xffd0f2], count: 200, size: 0.14, speed: 5.5, gravity: 0,  drag: 0.7, life: 1.0 },
  bug:      { mode: 'burst',      colors: [0xa8d400, 0xe7ff9e], count: 210, size: 0.08, speed: 7.0, gravity: -2, drag: 1.0, life: 0.85 },
  rock:     { mode: 'shards',     colors: [0xa3906b, 0x5f5238], count: 90,  size: 0.24, speed: 6.0, gravity: -11, drag: 0.2, life: 1.05 },
  ghost:    { mode: 'drift',      colors: [0x7a5cff, 0x2a1f4d], count: 150, size: 0.20, speed: 2.0, gravity: 1.2, drag: 0.5, life: 1.4 },
  dragon:   { mode: 'spiral',     colors: [0x4a3bff, 0x9fd0ff], count: 220, size: 0.13, speed: 6.5, gravity: 1.0, drag: 0.8, life: 1.1 },
  dark:     { mode: 'implode',    colors: [0x6b4dff, 0x160f28], count: 190, size: 0.15, speed: 6.0, gravity: 0,  drag: 0,   life: 0.6 },
  steel:    { mode: 'beam',       colors: [0xdbe6f2, 0xffffff], count: 160, size: 0.13, speed: 4.0, gravity: -1, drag: 1.6, life: 0.55, spread: 0.1 },
  fairy:    { mode: 'sparkle',    colors: [0xff8ad1, 0xfff3fb], count: 170, size: 0.15, speed: 2.4, gravity: 0.5, drag: 0.9, life: 1.2 },
}

/** 발버둥은 타입이 노말이지만 상성을 무시하는 기술이라 따로 둔다. */
export const STRUGGLE_EFFECT = {
  mode: 'burst', colors: [0xff6b6b, 0x6b7280], count: 110, size: 0.12,
  speed: 6.0, gravity: -4, drag: 2.0, life: 0.6,
}

export function effectFor(type, moveId) {
  if (moveId === -1) return STRUGGLE_EFFECT
  return EFFECTS[type] ?? EFFECTS.normal
}
