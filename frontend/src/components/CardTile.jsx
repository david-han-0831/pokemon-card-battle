/** 손패 카드 1장. 클릭하면 서버에 제출한다. */

import TypeChip from './TypeChip'

export default function CardTile({ card, disabled, selected, onSelect }) {
  return (
    <button
      type="button"
      className={`card tier-${card.tier} ${selected ? 'is-selected' : ''}`}
      disabled={disabled}
      onClick={() => onSelect(card.card_id)}
      title={`BST ${card.bst} · ${card.moves?.map((m) => m.name_ko).join(' / ') ?? ''}`}
    >
      <span className="card__tier">{card.tier}</span>
      <img className="card__sprite" src={card.sprite_url} alt={card.name_ko} loading="lazy" />
      <span className="card__name">{card.name_ko}</span>
      <span className="card__types">
        {card.types.map((t) => (
          <TypeChip key={t} type={t} variant="symbol" />
        ))}
      </span>
      <span className="card__stats">
        HP <b>{card.stats.hp}</b>
        <span className="dot">·</span>
        공 <b>{card.stats.attack}</b>/<b>{card.stats.special_attack}</b>
        <span className="dot">·</span>
        속 <b>{card.stats.speed}</b>
      </span>
      {card.moves && (
        <span className="card__moves">
          {card.moves.map((m) => (
            <TypeChip key={m.move_id} type={m.type} variant="symbol" className="typeicon--tiny" />
          ))}
        </span>
      )}
    </button>
  )
}
