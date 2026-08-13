/**
 * 타입 배지.
 *
 * 한글 타입명을 프론트에 하드코딩하지 않는다. 서버가 `/api/types` 로
 * 한글명과 **PokeAPI 공식 아이콘 URL** 을 함께 내려준다.
 * (PokeAPI 는 기술 이미지는 안 주지만 타입 아이콘은 준다.)
 *
 * 참조 데이터라 앱당 한 번만 받아 모듈 스코프에 캐싱한다 —
 * 컴포넌트마다 fetch 하면 카드 6장 × 타입 2개만큼 요청이 나간다.
 */

import { useEffect, useState } from 'react'
import { fetchTypes } from '../api'

let cache = null
let inflight = null

export function useTypeInfo() {
  const [types, setTypes] = useState(cache)

  useEffect(() => {
    if (cache) return
    inflight =
      inflight ||
      fetchTypes()
        .then((rows) => {
          cache = Object.fromEntries(rows.map((r) => [r.name, r]))
          return cache
        })
        .catch(() => {
          cache = {} // 실패해도 게임은 돌아가야 한다 — 영문 타입명으로 폴백
          return cache
        })

    let alive = true
    inflight.then((c) => alive && setTypes(c))
    return () => {
      alive = false
    }
  }, [])

  return types ?? {}
}

/**
 * variant="badge"  → 타입 이름이 적힌 가로로 긴 배지 (기술 버튼처럼 넓은 자리)
 * variant="symbol" → 정사각 심볼 (손패 카드처럼 좁은 자리)
 */
export default function TypeChip({ type, variant = 'badge', className = '' }) {
  const info = useTypeInfo()[type]
  const src = variant === 'symbol' ? info?.symbol_url || info?.icon_url : info?.icon_url

  if (src) {
    return (
      <img
        className={`typeicon typeicon--${variant} ${className}`}
        src={src}
        alt={info.name_ko}
        title={info.name_ko}
      />
    )
  }
  // 아이콘을 못 받았을 때의 폴백
  return <span className={`chip type-${type} ${className}`}>{info?.name_ko ?? type}</span>
}
