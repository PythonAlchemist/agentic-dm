import { useState } from 'react';
import type { Combatant } from './types';

interface CombatantCardProps {
  combatant: Combatant;
  isCurrentTurn: boolean;
  onDamage: (damage: number) => void;
  onHeal: (healing: number) => void;
}

export function CombatantCard({ combatant, isCurrentTurn, onDamage, onHeal }: CombatantCardProps) {
  const [damageInput, setDamageInput] = useState('');
  const [healInput, setHealInput] = useState('');

  const isDead = combatant.hp <= 0;
  const hpPercent = (combatant.hp / combatant.max_hp) * 100;

  const handleDamage = () => {
    const dmg = parseInt(damageInput);
    if (dmg > 0) {
      onDamage(dmg);
      setDamageInput('');
    }
  };

  const handleHeal = () => {
    const heal = parseInt(healInput);
    if (heal > 0) {
      onHeal(heal);
      setHealInput('');
    }
  };

  return (
    <div
      className={`p-4 rounded-lg transition-all ${
        isDead
          ? 'bg-gray-700/30 opacity-50'
          : isCurrentTurn
          ? 'bg-yellow-600/30 border-2 border-yellow-500'
          : combatant.is_player
          ? 'bg-blue-600/20'
          : combatant.is_friendly
          ? 'bg-green-600/20 border border-green-500/30'
          : combatant.is_npc
          ? 'bg-purple-600/20 border border-purple-500/30'
          : 'bg-red-600/20'
      }`}
    >
      <div className="flex items-center gap-4">
        {/* Initiative */}
        <div className="text-center w-12">
          <div className="text-2xl font-bold">{combatant.initiative}</div>
          <div className="text-xs text-gray-400">INIT</div>
        </div>

        {/* Info */}
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <span className="font-medium text-lg">{combatant.name}</span>
            {combatant.is_npc && !combatant.is_player && (
              <span className={`px-2 py-0.5 text-xs rounded ${
                combatant.is_friendly ? 'bg-green-600 text-green-100' : 'bg-purple-600 text-purple-100'
              }`}>
                {combatant.is_friendly ? 'Ally' : 'AI'}
              </span>
            )}
            {isCurrentTurn && !isDead && (
              <span className="px-2 py-0.5 bg-yellow-500 text-black text-xs rounded">CURRENT</span>
            )}
            {isDead && (
              <span className="px-2 py-0.5 bg-gray-600 text-gray-300 text-xs rounded">DOWN</span>
            )}
          </div>
          {combatant.is_player && combatant.player_name && (
            <div className="text-sm text-gray-400">{combatant.player_name}'s character</div>
          )}

          {/* HP Bar */}
          <div className="mt-2">
            <div className="flex items-center gap-2">
              <div className="flex-1 h-3 bg-gray-700 rounded-full overflow-hidden">
                <div
                  className={`h-full transition-all ${
                    hpPercent > 50 ? 'bg-green-500' : hpPercent > 25 ? 'bg-yellow-500' : 'bg-red-500'
                  }`}
                  style={{ width: `${Math.max(0, hpPercent)}%` }}
                />
              </div>
              <span className="text-sm font-mono w-20 text-right">
                {combatant.hp}/{combatant.max_hp}
              </span>
            </div>
          </div>

          {/* Conditions */}
          {combatant.conditions && combatant.conditions.length > 0 && (
            <div className="mt-2 flex gap-1">
              {combatant.conditions.map((cond, i) => (
                <span key={i} className="px-2 py-0.5 bg-purple-600/50 text-purple-200 text-xs rounded">
                  {cond}
                </span>
              ))}
            </div>
          )}
        </div>

        {/* Actions */}
        {!isDead && (
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1">
              <input
                type="number"
                min="1"
                value={damageInput}
                onChange={(e) => setDamageInput(e.target.value)}
                placeholder="Dmg"
                className="w-16 px-2 py-1 text-sm bg-gray-700 border border-gray-600 rounded"
                onKeyDown={(e) => e.key === 'Enter' && handleDamage()}
              />
              <button
                onClick={handleDamage}
                disabled={!damageInput}
                className="px-2 py-1 text-sm bg-red-600 hover:bg-red-700 rounded disabled:opacity-50"
              >
                -
              </button>
            </div>
            <div className="flex items-center gap-1">
              <input
                type="number"
                min="1"
                value={healInput}
                onChange={(e) => setHealInput(e.target.value)}
                placeholder="Heal"
                className="w-16 px-2 py-1 text-sm bg-gray-700 border border-gray-600 rounded"
                onKeyDown={(e) => e.key === 'Enter' && handleHeal()}
              />
              <button
                onClick={handleHeal}
                disabled={!healInput}
                className="px-2 py-1 text-sm bg-green-600 hover:bg-green-700 rounded disabled:opacity-50"
              >
                +
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
