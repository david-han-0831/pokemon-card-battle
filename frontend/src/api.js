/**
 * REST 클라이언트.
 *
 * vite.config.js 의 프록시 덕분에 상대 경로 그대로 쓰면 백엔드로 넘어간다.
 * (배포 시엔 VITE_API_BASE 로 절대 주소를 넣으면 된다.)
 */

const BASE = import.meta.env.VITE_API_BASE ?? ''

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (body.detail) detail = body.detail
    } catch {
      /* JSON 이 아니면 상태줄을 그대로 쓴다 */
    }
    throw new Error(detail)
  }
  return res.json()
}

export const createRoom = (displayName) =>
  request('/api/rooms', {
    method: 'POST',
    body: JSON.stringify({ display_name: displayName }),
  })

export const joinRoom = (code, displayName) =>
  request(`/api/rooms/${code.toUpperCase()}/join`, {
    method: 'POST',
    body: JSON.stringify({ display_name: displayName }),
  })

export const fetchRoster = () => request('/api/pokemon')

/** 타입 18종의 한글명 + 공식 아이콘. 거의 안 바뀌는 참조 데이터라 앱당 1회만 받는다. */
export const fetchTypes = () => request('/api/types')

/** WebSocket 주소를 만든다. 토큰은 REST 응답으로 받은 것. */
export function socketUrl(roomCode, token) {
  if (BASE) {
    const url = new URL(BASE)
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
    url.pathname = `/ws/rooms/${roomCode}`
    url.search = `?token=${encodeURIComponent(token)}`
    return url.toString()
  }
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${location.host}/ws/rooms/${roomCode}?token=${encodeURIComponent(token)}`
}
