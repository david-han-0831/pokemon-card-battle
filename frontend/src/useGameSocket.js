/**
 * 게임 소켓 훅.
 *
 * 서버가 보내는 메시지를 받아 화면이 쓰는 상태로 바꾸는 게 전부다.
 * **판정도, HP·PP 관리도 여기서 하지 않는다** — 전부 서버가 한다.
 * 클라이언트는 서버가 알려준 것만 그린다(= 서버 권위 모델).
 *
 * 한 라운드의 단계:
 *   selecting → 포켓몬 선택 (상대 손패 비공개)
 *   battling  → 턴제 전투 (상대 포켓몬 공개, 단 남은 PP 는 끝까지 비공개)
 *   reveal    → 라운드 결과
 */

import { useCallback, useEffect, useReducer, useRef } from 'react'
import { socketUrl } from './api'

const initialState = {
  connected: false,
  /** waiting | selecting | battling | reveal | over */
  phase: 'waiting',
  room: null,

  hand: [],
  opponentHandCount: 0,

  round: 0,
  totalRounds: 6,
  turn: 0,
  maxTurns: 30,
  deadlineMs: null,

  /** 카드 선택 단계 */
  playedCardId: null,
  opponentPlayed: false,

  /** 전투 단계 */
  me: null,        // {card, hp, max_hp, moves:[{...pp}], out_of_pp}
  opponent: null,  // {card, hp, max_hp, moves:[{...pp 없음}]}
  chosenMoveId: null,
  opponentChose: false,
  lastTurn: null,  // {turn, events:[...], auto_move}

  roundResult: null,
  gameOver: null,
  opponentWantsRematch: false,
  opponentLeft: false,
  error: null,
}

function reducer(state, action) {
  switch (action.type) {
    case 'connected':
      return { ...state, connected: true, error: null }
    case 'disconnected':
      return { ...state, connected: false }

    case 'room_state': {
      const backToLobby = action.payload.status === 'waiting'
      return {
        ...state,
        room: action.payload,
        totalRounds: action.payload.total_rounds,
        opponentLeft: action.payload.opponent
          ? !action.payload.opponent.connected
          : state.opponentLeft,
        ...(backToLobby
          ? { phase: 'waiting', gameOver: null, roundResult: null, lastTurn: null, hand: [] }
          : {}),
      }
    }

    case 'deal':
      return {
        ...state,
        hand: action.payload.hand,
        opponentHandCount: action.payload.opponent_hand_count,
        gameOver: null,
        roundResult: null,
        opponentWantsRematch: false,
      }

    case 'round_start':
      return {
        ...state,
        phase: 'selecting',
        round: action.payload.round,
        deadlineMs: action.payload.deadline_ms,
        // 새로고침 복구: 이미 낸 카드가 있으면 서버가 그 id 를 돌려준다.
        playedCardId: action.payload.you_played ?? null,
        opponentPlayed: false,
        roundResult: null,
        lastTurn: null,
        me: null,
        opponent: null,
      }

    case 'play_accepted':
      // 서버가 승인한 뒤에야 "냈다"고 표시한다.
      // 낙관적 업데이트를 하면 거부당했을 때 화면과 서버가 어긋난다.
      return { ...state, playedCardId: action.payload.card_id }

    case 'opponent_played':
      return { ...state, opponentPlayed: true }

    case 'battle_start':
      return {
        ...state,
        phase: 'battling',
        round: action.payload.round,
        maxTurns: action.payload.max_turns,
        me: action.payload.you,
        opponent: action.payload.opponent,
        opponentHandCount: action.payload.hand_counts.opponent,
        hand: state.hand.filter((c) => c.card_id !== action.payload.you.card.card_id),
        playedCardId: null,
        opponentPlayed: false,
        lastTurn: null,
      }

    case 'turn_start':
      return {
        ...state,
        phase: 'battling',
        turn: action.payload.turn,
        deadlineMs: action.payload.deadline_ms,
        chosenMoveId: action.payload.you_chose ?? null,
        opponentChose: false,
        lastTurn: null,
      }

    case 'move_accepted':
      return { ...state, chosenMoveId: action.payload.move_id }

    case 'opponent_move_selected':
      return { ...state, opponentChose: true }

    case 'turn_result':
      return {
        ...state,
        lastTurn: action.payload,
        me: action.payload.you,
        opponent: action.payload.opponent,
        chosenMoveId: null,
        opponentChose: false,
        deadlineMs: null,
      }

    case 'round_result':
      return {
        ...state,
        phase: 'reveal',
        roundResult: action.payload,
        me: action.payload.you,
        opponent: action.payload.opponent,
        opponentHandCount: action.payload.hand_counts.opponent,
        // 상단 점수판도 여기서 갱신해야 한다.
        // room_state 는 라운드마다 오지 않으므로, 빼먹으면 점수판이 0:0 에 멈춘다.
        room: state.room
          ? { ...state.room, board: action.payload.board, round: action.payload.round }
          : state.room,
        deadlineMs: null,
      }

    case 'game_over':
      return { ...state, phase: 'over', gameOver: action.payload }

    case 'opponent_wants_rematch':
      return { ...state, opponentWantsRematch: true }

    case 'opponent_left':
      return { ...state, opponentLeft: true }

    case 'error':
      return { ...state, error: action.payload }

    case 'clear_error':
      return { ...state, error: null }

    default:
      return state
  }
}

export function useGameSocket(ticket) {
  const [state, dispatch] = useReducer(reducer, initialState)
  const socketRef = useRef(null)

  useEffect(() => {
    if (!ticket) return

    const ws = new WebSocket(socketUrl(ticket.room_code, ticket.player_token))
    socketRef.current = ws

    ws.onopen = () => dispatch({ type: 'connected' })
    ws.onclose = () => dispatch({ type: 'disconnected' })
    ws.onmessage = (event) => {
      const { type, payload } = JSON.parse(event.data)
      if (type === 'pong') return
      dispatch({ type, payload })
    }

    // 30초마다 핑 — 중간 프록시가 유휴 연결을 끊는 걸 막는다.
    const keepalive = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'ping', payload: {} }))
      }
    }, 30_000)

    return () => {
      clearInterval(keepalive)
      ws.close()
      socketRef.current = null
    }
  }, [ticket])

  const send = useCallback((type, payload = {}) => {
    const ws = socketRef.current
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type, payload }))
    }
  }, [])

  return {
    state,
    ready: () => send('ready'),
    playCard: (cardId) => send('play_card', { card_id: cardId }),
    useMove: (moveId) => send('use_move', { move_id: moveId }),
    rematch: () => send('rematch'),
    clearError: () => dispatch({ type: 'clear_error' }),
  }
}
