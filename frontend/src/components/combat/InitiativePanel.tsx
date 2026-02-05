import type { Combatant } from './types';
import { CombatantCard } from './CombatantCard';

interface InitiativePanelProps {
  combatants: Combatant[];
  currentTurnIdx: number;
  activeTurnName: string | null;
  onDamage: (name: string, damage: number) => void;
  onHeal: (name: string, healing: number) => void;
}

export function InitiativePanel({
  combatants,
  currentTurnIdx,
  activeTurnName,
  onDamage,
  onHeal,
}: InitiativePanelProps) {
  return (
    <div className="w-72 flex flex-col bg-gray-900/30 rounded-lg border border-gray-700 min-h-0">
      <div className="px-3 py-2 border-b border-gray-700 text-sm font-medium text-gray-400 flex-shrink-0">
        Initiative Order
      </div>
      <div className="flex-1 overflow-y-auto p-2 space-y-2">
        {combatants.map((c, idx) => (
          <CombatantCard
            key={idx}
            combatant={c}
            isCurrentTurn={
              activeTurnName
                ? c.name === activeTurnName
                : idx === currentTurnIdx
            }
            onDamage={(dmg) => onDamage(c.name, dmg)}
            onHeal={(heal) => onHeal(c.name, heal)}
          />
        ))}
      </div>
    </div>
  );
}
