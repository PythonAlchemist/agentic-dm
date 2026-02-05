import type { Combatant } from './types';
import { getCombatantFaction, FACTION_COLORS } from './types';

interface BattleMapTokenProps {
  combatant: Combatant;
  isCurrentTurn: boolean;
  isSelected: boolean;
  onClick: () => void;
}

function getInitials(name: string): string {
  const words = name.split(/[\s-]+/);
  if (words.length === 1) return name.slice(0, 2).toUpperCase();
  return (words[0][0] + words[1][0]).toUpperCase();
}

export function BattleMapToken({ combatant, isCurrentTurn, isSelected, onClick }: BattleMapTokenProps) {
  const faction = getCombatantFaction(combatant);
  const colors = FACTION_COLORS[faction];
  const isDead = combatant.hp <= 0;
  const hpPercent = Math.max(0, (combatant.hp / combatant.max_hp) * 100);

  return (
    <button
      onClick={onClick}
      className={`
        w-9 h-9 rounded-full flex flex-col items-center justify-center
        relative cursor-pointer transition-all
        ${colors.token} ${isDead ? 'opacity-40' : ''}
        ${isSelected ? 'ring-2 ring-yellow-400 ring-offset-1 ring-offset-gray-900 scale-110 z-10' : ''}
        ${isCurrentTurn && !isSelected ? 'ring-2 ring-yellow-500/60 animate-pulse' : ''}
        hover:scale-110 hover:z-10
      `}
      title={`${combatant.name} (HP: ${combatant.hp}/${combatant.max_hp})`}
    >
      {/* Initials */}
      <span className="text-[10px] font-bold leading-none text-white drop-shadow-sm">
        {getInitials(combatant.name)}
      </span>

      {/* HP bar at bottom of token */}
      {!isDead && (
        <div className="absolute bottom-0 left-1 right-1 h-[3px] bg-gray-900/60 rounded-full overflow-hidden">
          <div
            className={`h-full transition-all ${
              hpPercent > 50 ? 'bg-green-400' : hpPercent > 25 ? 'bg-yellow-400' : 'bg-red-400'
            }`}
            style={{ width: `${hpPercent}%` }}
          />
        </div>
      )}

      {/* Dead X */}
      {isDead && (
        <span className="absolute inset-0 flex items-center justify-center text-red-400 text-lg font-bold">
          X
        </span>
      )}
    </button>
  );
}
