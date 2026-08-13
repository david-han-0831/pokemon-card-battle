/**
 * Three.js 배틀 스테이지.
 *
 * 이 프로젝트의 3D 트릭: PokeAPI 는 **2D 스프라이트만** 준다.
 * 그래서 3D 모델을 만드는 대신
 *   - 바닥은 실제 3D (회전하는 원기둥 발판 + 링)
 *   - 캐릭터는 THREE.Sprite = 항상 카메라를 향하는 빌보드
 * 로 섞는다. 2.5D 라고 부르는 이 조합이 에셋 없이 "게임 같은" 화면을 만드는 실전 기법이다.
 *
 * 기술 이펙트도 마찬가지다. PokeAPI 에 기술 이미지가 아예 없으므로
 * 파티클을 **코드로 뿌려서** 만든다 (`typeEffects.js` 에 타입 18종 정의).
 *
 * React 와의 경계: React 는 "무엇을 보여줄지"만 알려주고,
 * 렌더 루프(requestAnimationFrame)는 React 바깥에서 돈다.
 * 매 프레임 setState 하면 React 가 초당 60번 리렌더되므로 절대 그렇게 하지 않는다.
 */

import { useEffect, useRef } from 'react'
import * as THREE from 'three'
import { MODES, effectFor } from './typeEffects'

const MY_SIDE_X = -2.4
const OPP_SIDE_X = 2.4
const EMITTER_COUNT = 4      // 동시에 살아 있을 수 있는 이펙트 수
const EMITTER_CAPACITY = 240 // 이펙트 하나당 파티클 수

/** 상대 카드가 아직 공개되지 않았을 때 쓸 "?" 텍스처를 코드로 만든다. */
function makeHiddenTexture() {
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = 256
  const ctx = canvas.getContext('2d')

  ctx.fillStyle = '#1b2440'
  ctx.beginPath()
  ctx.roundRect(28, 28, 200, 200, 24)
  ctx.fill()
  ctx.strokeStyle = '#4b6bff'
  ctx.lineWidth = 6
  ctx.stroke()

  ctx.fillStyle = '#4b6bff'
  ctx.font = 'bold 120px system-ui, sans-serif'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText('?', 128, 132)

  const texture = new THREE.CanvasTexture(canvas)
  texture.colorSpace = THREE.SRGBColorSpace
  return texture
}

function makePlatform(color) {
  const group = new THREE.Group()

  const disc = new THREE.Mesh(
    new THREE.CylinderGeometry(1.25, 1.35, 0.18, 48),
    new THREE.MeshStandardMaterial({ color: 0x1a2138, roughness: 0.55, metalness: 0.3 })
  )
  group.add(disc)

  const ring = new THREE.Mesh(
    new THREE.TorusGeometry(1.3, 0.05, 12, 64),
    new THREE.MeshBasicMaterial({ color })
  )
  ring.rotation.x = Math.PI / 2
  ring.position.y = 0.12
  group.add(ring)
  group.userData.ring = ring

  return group
}

/**
 * 파티클 방출기 하나.
 *
 * 이펙트마다 파티클 **크기**가 달라야 하는데 PointsMaterial 의 size 는 객체 단위라
 * 하나의 Points 로는 못 한다. 그래서 방출기를 몇 개 만들어 돌려 쓴다.
 * (per-particle size 를 하려면 ShaderMaterial 이 필요한데, 예제엔 과하다.)
 */
function makeEmitter() {
  const positions = new Float32Array(EMITTER_CAPACITY * 3)
  const colors = new Float32Array(EMITTER_CAPACITY * 3)
  positions.fill(-9999) // 안 쓰는 파티클은 화면 밖으로 치워 둔다

  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))
  geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3))

  const material = new THREE.PointsMaterial({
    size: 0.12,
    vertexColors: true,
    transparent: true,
    opacity: 0,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  })

  const points = new THREE.Points(geometry, material)
  points.frustumCulled = false
  points.userData = {
    positions,
    colors,
    velocities: new Float32Array(EMITTER_CAPACITY * 3),
    active: 0,
    life: 0,
    maxLife: 1,
    gravity: 0,
    drag: 0,
  }
  return points
}

const _spawn = {
  set(x, y, z, vx, vy, vz) {
    this.x = x; this.y = y; this.z = z
    this.vx = vx; this.vy = vy; this.vz = vz
  },
}

/** 이펙트 하나를 방출기에 채운다. from/to 는 x 좌표. */
function emit(emitter, cfg, from, to, scale = 1) {
  const { positions, colors, velocities } = emitter.userData
  const spawnFn = MODES[cfg.mode] ?? MODES.burst
  const count = Math.min(cfg.count, EMITTER_CAPACITY)

  const c0 = new THREE.Color(cfg.colors[0])
  const c1 = new THREE.Color(cfg.colors[1])
  const mixed = new THREE.Color()

  for (let i = 0; i < count; i++) {
    spawnFn(i, count, cfg, from, to, _spawn)
    const i3 = i * 3
    positions[i3] = _spawn.x
    positions[i3 + 1] = _spawn.y
    positions[i3 + 2] = _spawn.z
    velocities[i3] = _spawn.vx * scale
    velocities[i3 + 1] = _spawn.vy * scale
    velocities[i3 + 2] = _spawn.vz * scale

    mixed.copy(c0).lerp(c1, Math.random())
    colors[i3] = mixed.r
    colors[i3 + 1] = mixed.g
    colors[i3 + 2] = mixed.b
  }
  // 남는 파티클은 화면 밖으로
  for (let i = count; i < EMITTER_CAPACITY; i++) positions[i * 3 + 1] = -9999

  emitter.geometry.attributes.position.needsUpdate = true
  emitter.geometry.attributes.color.needsUpdate = true
  emitter.material.size = cfg.size * scale
  emitter.material.opacity = 1

  const d = emitter.userData
  d.active = count
  d.life = cfg.life
  d.maxLife = cfg.life
  d.gravity = cfg.gravity
  d.drag = cfg.drag
}

function updateEmitter(emitter, dt) {
  const d = emitter.userData
  if (d.life <= 0) return

  const { positions, velocities, active, gravity, drag } = d
  const damp = Math.max(0, 1 - drag * dt)

  for (let i = 0; i < active; i++) {
    const i3 = i * 3
    velocities[i3] *= damp
    velocities[i3 + 1] = velocities[i3 + 1] * damp + gravity * dt
    velocities[i3 + 2] *= damp
    positions[i3] += velocities[i3] * dt
    positions[i3 + 1] += velocities[i3 + 1] * dt
    positions[i3 + 2] += velocities[i3 + 2] * dt
  }
  emitter.geometry.attributes.position.needsUpdate = true

  d.life = Math.max(0, d.life - dt)
  const t = d.life / d.maxLife
  emitter.material.opacity = t * t  // 끝에서 빠르게 사라지게
  if (d.life === 0) {
    d.active = 0
    for (let i = 0; i < EMITTER_CAPACITY; i++) positions[i * 3 + 1] = -9999
    emitter.geometry.attributes.position.needsUpdate = true
  }
}

export default function BattleStage({ myCard, opponentCard, opponentPlayed, hitKey, events }) {
  const mountRef = useRef(null)
  const sceneRef = useRef(null)

  // --- 1회 셋업: 씬 / 카메라 / 렌더러 / 애니메이션 루프 ---
  useEffect(() => {
    const mount = mountRef.current
    if (!mount) return

    const scene = new THREE.Scene()
    scene.background = new THREE.Color(0x090d1a)
    scene.fog = new THREE.Fog(0x090d1a, 9, 18)

    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100)
    camera.position.set(0, 3.1, 7.6)
    camera.lookAt(0, 1.1, 0)

    const renderer = new THREE.WebGLRenderer({ antialias: true })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    mount.appendChild(renderer.domElement)

    scene.add(new THREE.AmbientLight(0x93a4ff, 0.7))
    const key = new THREE.DirectionalLight(0xffffff, 1.4)
    key.position.set(3, 6, 5)
    scene.add(key)
    const rim = new THREE.PointLight(0xff5a7a, 1.2, 20)
    rim.position.set(-4, 2, -3)
    scene.add(rim)

    const grid = new THREE.GridHelper(30, 30, 0x2a3a5c, 0x18203a)
    scene.add(grid)

    const myPlatform = makePlatform(0x4b8bff)
    myPlatform.position.set(MY_SIDE_X, 0, 0)
    scene.add(myPlatform)

    const oppPlatform = makePlatform(0xff5a7a)
    oppPlatform.position.set(OPP_SIDE_X, 0, 0)
    scene.add(oppPlatform)

    const hiddenTexture = makeHiddenTexture()
    const makeSprite = () => {
      const sprite = new THREE.Sprite(
        new THREE.SpriteMaterial({ map: hiddenTexture, transparent: true })
      )
      sprite.scale.set(2.3, 2.3, 1)
      sprite.position.y = 1.45
      return sprite
    }

    const mySprite = makeSprite()
    mySprite.position.x = MY_SIDE_X
    scene.add(mySprite)

    const oppSprite = makeSprite()
    oppSprite.position.x = OPP_SIDE_X
    scene.add(oppSprite)

    const emitters = Array.from({ length: EMITTER_COUNT }, () => {
      const e = makeEmitter()
      scene.add(e)
      return e
    })
    let emitterCursor = 0

    const clock = new THREE.Clock()
    const shake = []
    let frameId

    const animate = () => {
      frameId = requestAnimationFrame(animate)
      const dt = Math.min(clock.getDelta(), 0.05) // 탭 전환 후 큰 dt 로 튀는 걸 막는다
      const t = clock.elapsedTime

      myPlatform.rotation.y += dt * 0.35
      oppPlatform.rotation.y -= dt * 0.35

      mySprite.position.y = 1.45 + Math.sin(t * 1.6) * 0.09
      oppSprite.position.y = 1.45 + Math.sin(t * 1.6 + 1.7) * 0.09

      // 맞은 스프라이트는 좌우로 떨리고 붉게 물든다
      for (let i = shake.length - 1; i >= 0; i--) {
        const s = shake[i]
        s.t -= dt
        if (s.t <= 0) {
          s.sprite.position.x = s.x
          s.sprite.material.color.setHex(0xffffff)
          shake.splice(i, 1)
          continue
        }
        s.sprite.position.x = s.x + Math.sin(s.t * 60) * s.t * 0.5
        s.sprite.material.color.setRGB(1, 1 - s.t * 1.2, 1 - s.t * 1.2)
      }

      emitters.forEach((e) => updateEmitter(e, dt))
      renderer.render(scene, camera)
    }
    animate()

    const resize = () => {
      const { clientWidth: w, clientHeight: h } = mount
      if (!w || !h) return
      renderer.setSize(w, h, false)
      camera.aspect = w / h
      camera.updateProjectionMatrix()
    }
    resize()
    const observer = new ResizeObserver(resize)
    observer.observe(mount)

    sceneRef.current = {
      mySprite, oppSprite, hiddenTexture, shake,
      play(cfg, from, to, scale) {
        emit(emitters[emitterCursor], cfg, from, to, scale)
        emitterCursor = (emitterCursor + 1) % EMITTER_COUNT
      },
    }

    return () => {
      cancelAnimationFrame(frameId)
      observer.disconnect()
      scene.traverse((obj) => {
        obj.geometry?.dispose?.()
        if (obj.material) {
          const materials = Array.isArray(obj.material) ? obj.material : [obj.material]
          materials.forEach((m) => {
            m.map?.dispose?.()
            m.dispose()
          })
        }
      })
      hiddenTexture.dispose()
      renderer.dispose()
      mount.removeChild(renderer.domElement)
      sceneRef.current = null
    }
  }, [])

  // --- 카드가 바뀌면 스프라이트 텍스처 교체 ---
  useEffect(() => {
    const ctx = sceneRef.current
    if (!ctx) return

    const loader = new THREE.TextureLoader()
    loader.setCrossOrigin('anonymous')
    let cancelled = false

    const apply = (sprite, card) => {
      if (!card?.sprite_url) {
        sprite.material.map = ctx.hiddenTexture
        sprite.material.needsUpdate = true
        return
      }
      loader.load(card.sprite_url, (texture) => {
        if (cancelled) {
          texture.dispose()
          return
        }
        texture.colorSpace = THREE.SRGBColorSpace
        const previous = sprite.material.map
        sprite.material.map = texture
        sprite.material.needsUpdate = true
        if (previous && previous !== ctx.hiddenTexture) previous.dispose()
      })
    }

    apply(ctx.mySprite, myCard)
    apply(ctx.oppSprite, opponentCard)

    return () => {
      cancelled = true
    }
  }, [myCard?.card_id, opponentCard?.card_id])

  // --- 턴 결과가 오면 기술 타입에 맞는 이펙트를 재생한다 ---
  useEffect(() => {
    const ctx = sceneRef.current
    if (!ctx || !hitKey || !events?.length) return

    const timers = []
    events.forEach((event, index) => {
      const attackerIsMe = event.actor === 'you'
      const from = attackerIsMe ? MY_SIDE_X : OPP_SIDE_X
      const to = attackerIsMe ? OPP_SIDE_X : MY_SIDE_X
      const cfg = effectFor(event.move.type, event.move.move_id)

      timers.push(
        setTimeout(() => {
          // 빗나가면 힘 빠진 이펙트만, 0배면 아주 작게 — 결과가 눈에 보이게 한다
          const scale = !event.hit ? 0.45 : event.multiplier === 0 ? 0.3
            : event.multiplier >= 2 ? 1.35 : event.multiplier <= 0.5 ? 0.7 : 1
          ctx.play(cfg, from, to, scale)

          if (event.hit && event.damage > 0) {
            const victim = attackerIsMe ? ctx.oppSprite : ctx.mySprite
            ctx.shake.push({ sprite: victim, t: 0.35, x: to })
          }
        }, index * 900)
      )
    })

    return () => timers.forEach(clearTimeout)
  }, [hitKey, events])

  // 상대가 카드를 냈지만 아직 공개 전이면 "?" 를 유지한다 — 여기서 정보가 새면 안 된다.
  useEffect(() => {
    const ctx = sceneRef.current
    if (!ctx || opponentCard) return
    ctx.oppSprite.material.opacity = opponentPlayed ? 1 : 0.45
  }, [opponentPlayed, opponentCard])

  return <div ref={mountRef} className="stage" />
}
