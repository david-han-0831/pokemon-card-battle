/** 기술 4개 선택 바. 전투 중 하단에 뜬다. */

import TypeChip from './TypeChip'

const STRUGGLE_ID = -1

function MoveButton({ move, disabled, selected, onUse }) {
  const empty = move.pp === 0
  const eff = move.effectiveness
  return (
    <button
      type="button"
      className={`move type-${move.type} ${selected ? 'is-selected' : ''} ${empty ? 'is-empty' : ''}`}
      disabled={disabled || empty}
      onClick={() => onUse(move.move_id)}
      title={move.flavor_ko || undefined}
    >
      <span className="move__head">
        <TypeChip type={move.type} />
        <span className="move__name">{move.name_ko}</span>
      </span>
      <span className="move__numbers">
        <span className="move__kind">{move.damage_class === 'physical' ? '물리' : '특수'}</span>
        위력 <b>{move.power}</b> · 명중 <b>{move.accuracy}</b>
      </span>
      <span className="move__pp">
        PP <b>{move.pp}</b>/{move.max_pp}
      </span>
      {move.flavor_ko && <span className="move__flavor">{move.flavor_ko}</span>}
      {eff != null && eff !== 1 && (
        <span className={`move__eff eff-${eff > 1 ? 'good' : eff === 0 ? 'zero' : 'bad'}`}>
          ×{eff}
        </span>
      )}
    </button>
  )
}

export default function MoveBar({ me, opponent, disabled, chosenMoveId, onUse }) {
  if (!me) return null

  if (me.out_of_pp) {
    return (
      <div className="movebar movebar--struggle">
        <p className="movebar__hint">
          쓸 수 있는 기술이 없습니다. <b>발버둥</b>밖에 못 씁니다 — 준 데미지의 1/4 을 자신도 받습니다.
        </p>
        <button
          type="button"
          className={`move move--struggle ${chosenMoveId === STRUGGLE_ID ? 'is-selected' : ''}`}
          disabled={disabled}
          onClick={() => onUse(STRUGGLE_ID)}
        >
          <span className="move__name">발버둥</span>
          <span className="move__numbers">위력 <b>50</b> · 반동 <b>1/4</b></span>
        </button>
      </div>
    )
  }

  return (
    <div className="movebar">
      <div className="movebar__label">
        {disabled ? '상대를 기다리는 중…' : '기술을 선택하세요'}
        <span className="movebar__sub">
          상대 {opponent?.card?.name_ko} — 남은 PP 는 볼 수 없습니다
        </span>
      </div>
      <div className="movebar__grid">
        {me.moves.map((move) => (
          <MoveButton
            key={move.move_id}
            move={move}
            disabled={disabled}
            selected={chosenMoveId === move.move_id}
            onUse={onUse}
          />
        ))}
      </div>
    </div>
  )
}
