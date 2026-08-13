import { useState } from 'react'
import Lobby from './screens/Lobby'
import Battle from './screens/Battle'
import { useGameSocket } from './useGameSocket'

export default function App() {
  // 방 생성/입장 REST 응답. 이걸 갖고 있으면 배틀 화면, 없으면 로비.
  const [ticket, setTicket] = useState(null)
  const game = useGameSocket(ticket)

  if (!ticket) return <Lobby onTicket={setTicket} />

  if (!game.state.connected && !game.state.room) {
    return <div className="loading">서버에 연결하는 중…</div>
  }

  return (
    <Battle
      state={game.state}
      ready={game.ready}
      playCard={game.playCard}
      useMove={game.useMove}
      rematch={game.rematch}
      clearError={game.clearError}
    />
  )
}
