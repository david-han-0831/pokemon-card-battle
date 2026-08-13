/** 로비 — 방 만들기 / 코드로 입장. */

import { useState } from 'react'
import { createRoom, joinRoom } from '../api'

export default function Lobby({ onTicket }) {
  const [name, setName] = useState('')
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const run = async (fn) => {
    setBusy(true)
    setError(null)
    try {
      onTicket(await fn())
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const displayName = name.trim() || '플레이어'

  return (
    <div className="lobby">
      <header className="lobby__header">
        <h1>포켓몬 카드 배틀</h1>
        <p>랜덤으로 받은 6마리로 6라운드. 타입 상성이 스탯을 뒤집는다.</p>
      </header>

      <div className="panel">
        <label className="field">
          <span>닉네임</span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="플레이어"
            maxLength={16}
          />
        </label>

        <button
          className="btn btn--primary"
          disabled={busy}
          onClick={() => run(() => createRoom(displayName))}
        >
          {busy ? '서버에 연결하는 중…' : '방 만들기'}
        </button>

        <div className="divider"><span>또는</span></div>

        <label className="field">
          <span>방 코드</span>
          <input
            value={code}
            onChange={(e) => setCode(e.target.value.toUpperCase())}
            placeholder="ABC123"
            maxLength={6}
            className="mono"
          />
        </label>

        <button
          className="btn"
          disabled={busy || code.length !== 6}
          onClick={() => run(() => joinRoom(code, displayName))}
        >
          {busy ? '입장하는 중…' : '입장하기'}
        </button>

        {error && <p className="error">{error}</p>}
      </div>

      <footer className="lobby__hint">
        같은 브라우저에서 시크릿 창을 하나 더 열면 혼자서도 양쪽을 다 해볼 수 있다.
      </footer>
    </div>
  )
}
