/** 배틀 화면 — 스테이지 + (손패 | 기술바) + 결과 연출. */

import { useEffect, useMemo, useRef, useState } from 'react'
import BattleStage from '../three/BattleStage'
import CardTile from '../components/CardTile'
import MoveBar from '../components/MoveBar'

/** 서버가 준 남은 시간(ms)에서 초 카운트다운을 굴린다. 시간의 기준은 어디까지나 서버다. */
function useCountdown(deadlineMs) {
  const [remaining, setRemaining] = useState(deadlineMs)
  const endsAtRef = useRef(null)

  useEffect(() => {
    if (deadlineMs == null) {
      endsAtRef.current = null
      setRemaining(null)
      return
    }
    endsAtRef.current = performance.now() + deadlineMs
    setRemaining(deadlineMs)

    const id = setInterval(() => {
      setRemaining(Math.max(0, endsAtRef.current - performance.now()))
    }, 200)
    return () => clearInterval(id)
  }, [deadlineMs])

  return remaining
}

function HpBar({ side, fighter, align }) {
  if (!fighter) return null
  const ratio = fighter.max_hp ? fighter.hp / fighter.max_hp : 0
  const tone = ratio > 0.5 ? 'ok' : ratio > 0.2 ? 'warn' : 'danger'
  return (
    <div className={`hpbar hpbar--${align}`}>
      <div className="hpbar__top">
        <strong>{fighter.card.name_ko}</strong>
        <span className={`badge tier-badge-${fighter.card.tier}`}>{fighter.card.tier}</span>
      </div>
      <div className="hpbar__track">
        <div className={`hpbar__fill hpbar__fill--${tone}`} style={{ width: `${ratio * 100}%` }} />
      </div>
      <div className="hpbar__num">
        {fighter.hp} / {fighter.max_hp}
        <span className="hpbar__owner">{side}</span>
      </div>
    </div>
  )
}

function effLabel(value) {
  if (value === 0) return '효과가 없다…'
  if (value >= 2) return '효과가 굉장했다!'
  if (value <= 0.5) return '효과가 별로다…'
  return null
}

function TurnLog({ turn }) {
  if (!turn) return null
  return (
    <div className="turnlog">
      <span className="turnlog__head">TURN {turn.turn}</span>
      {turn.events.map((e, i) => {
        const who = e.actor === 'you' ? '내' : '상대'
        if (!e.hit) {
          return (
            <p key={i} className="turnlog__line">
              {who} <b>{e.move.name_ko}</b> — 빗나갔다!
            </p>
          )
        }
        const label = effLabel(e.multiplier)
        return (
          <p key={i} className="turnlog__line">
            {who} <b>{e.move.name_ko}</b> → <b>{e.damage}</b> 데미지
            {label && <span className={`mult mult--${e.multiplier > 1 ? 'good' : e.multiplier === 0 ? 'zero' : 'bad'}`}>{label}</span>}
            {e.recoil > 0 && <span className="turnlog__recoil">반동 {e.recoil}</span>}
            {e.fainted_target && <span className="turnlog__faint">쓰러졌다!</span>}
          </p>
        )
      })}
      {turn.auto_move && <p className="turnlog__auto">시간 초과 — 자동 선택됨</p>}
    </div>
  )
}

function RoundBanner({ result }) {
  const text =
    result.winner === 'you' ? '라운드 승리' :
    result.winner === 'opponent' ? '라운드 패배' : '무승부'
  return (
    <div className={`banner banner--${result.winner}`}>
      <div className="banner__side">
        <strong>{result.you.card.name_ko}</strong>
        <span className="banner__score">{result.you.hp} HP</span>
      </div>
      <div className="banner__verdict">
        <span className="banner__round">ROUND {result.round} · {result.turns}턴</span>
        <h2>{text}</h2>
      </div>
      <div className="banner__side banner__side--opp">
        <strong>{result.opponent.card.name_ko}</strong>
        <span className="banner__score">{result.opponent.hp} HP</span>
      </div>
    </div>
  )
}

export default function Battle({ state, ready, playCard, useMove, rematch, clearError }) {
  const {
    room, hand, phase, playedCardId, opponentPlayed,
    me, opponent, chosenMoveId, opponentChose, lastTurn, roundResult, gameOver,
  } = state
  const remaining = useCountdown(state.deadlineMs)

  const selectedCard = useMemo(() => {
    if (me) return me.card
    if (playedCardId) return hand.find((c) => c.card_id === playedCardId) ?? null
    return null
  }, [me, playedCardId, hand])

  const waiting = room?.status === 'waiting'
  const selecting = phase === 'selecting'
  const battling = phase === 'battling'

  return (
    <div className="battle">
      <header className="topbar">
        <div className="topbar__room">
          <span className="label">방 코드</span>
          <strong className="mono">{room?.room_code}</strong>
        </div>

        <div className="scoreboard">
          <div className="scoreboard__side">
            <span>{room?.you.name}</span>
            <strong>{room?.board.you ?? 0}</strong>
          </div>
          <div className="scoreboard__mid">
            {phase === 'over'
              ? 'FINAL'
              : `ROUND ${state.round || '-'} / ${state.totalRounds}${battling ? ` · TURN ${state.turn}` : ''}`}
          </div>
          <div className="scoreboard__side scoreboard__side--opp">
            <strong>{room?.board.opponent ?? 0}</strong>
            <span>{room?.opponent?.name ?? '대기 중'}</span>
          </div>
        </div>

        <div className="topbar__timer">
          {remaining != null && (selecting || battling) && !roundResult && (
            <span className={remaining < 6000 ? 'timer timer--urgent' : 'timer'}>
              {Math.ceil(remaining / 1000)}s
            </span>
          )}
        </div>
      </header>

      <div className="stage-wrap">
        <BattleStage
          myCard={selectedCard}
          opponentCard={opponent?.card ?? null}
          opponentPlayed={opponentPlayed}
          hitKey={lastTurn ? `${state.round}-${lastTurn.turn}` : null}
          events={lastTurn?.events}
        />

        {(battling || phase === 'reveal') && (
          <div className="hud">
            <HpBar side="나" fighter={me} align="left" />
            <HpBar side="상대" fighter={opponent} align="right" />
          </div>
        )}

        {battling && <TurnLog turn={lastTurn} />}
        {phase === 'reveal' && roundResult && <RoundBanner result={roundResult} />}

        {selecting && (
          <div className="stage-status">
            {playedCardId
              ? opponentPlayed
                ? '전투 시작!'
                : '상대가 포켓몬을 고르는 중…'
              : '내보낼 포켓몬을 선택하세요'}
            <span className="stage-status__hidden">
              상대 손패 {state.opponentHandCount}장 (내용은 서버가 안 보내 줍니다)
            </span>
          </div>
        )}

        {waiting && (
          <div className="overlay">
            <div className="overlay__card">
              <h2>대기실</h2>
              {room?.opponent ? (
                <p>
                  {room.opponent.name} 입장 완료 —{' '}
                  {room.opponent.ready ? '준비 완료' : '아직 준비 안 됨'}
                </p>
              ) : (
                <p>
                  상대를 기다리는 중… 방 코드{' '}
                  <strong className="mono">{room?.room_code}</strong> 를 알려주세요.
                </p>
              )}
              <button className="btn btn--primary" onClick={ready} disabled={!room?.opponent}>
                {room?.you.ready ? '준비 취소' : '준비 완료'}
              </button>
            </div>
          </div>
        )}

        {phase === 'over' && gameOver && (
          <div className="overlay">
            <div className="overlay__card">
              <h2 className={`result result--${gameOver.result}`}>
                {gameOver.result === 'win' ? '승리!' : gameOver.result === 'lose' ? '패배' : '무승부'}
              </h2>
              <p className="final-score">
                {gameOver.board.you} <span>—</span> {gameOver.board.opponent}
              </p>
              <button className="btn btn--primary" onClick={rematch}>재대결</button>
              {state.opponentWantsRematch && <p className="hint">상대가 재대결을 원합니다</p>}
            </div>
          </div>
        )}

        {state.opponentLeft && phase !== 'over' && (
          <div className="toast">상대 연결이 끊겼습니다. 재접속을 기다리는 중…</div>
        )}
      </div>

      {battling ? (
        <MoveBar
          me={me}
          opponent={opponent}
          disabled={chosenMoveId != null || !!lastTurn}
          chosenMoveId={chosenMoveId}
          onUse={useMove}
        />
      ) : (
        <section className="hand">
          <div className="hand__label">
            내 손패 <b>{hand.length}</b>장
            {opponentChose && <span className="hand__note">상대 선택 완료</span>}
          </div>
          <div className="hand__grid">
            {hand.map((card) => (
              <CardTile
                key={card.card_id}
                card={card}
                selected={card.card_id === playedCardId}
                disabled={!selecting || !!playedCardId}
                onSelect={playCard}
              />
            ))}
            {hand.length === 0 && !waiting && <p className="hand__empty">손패를 다 썼습니다.</p>}
          </div>
        </section>
      )}

      {state.error && (
        <div className="toast toast--error" onClick={clearError}>
          {state.error.message}
        </div>
      )}
    </div>
  )
}
