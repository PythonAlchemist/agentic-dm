import { useState } from 'react';
import type { Combatant, CombatState, Player } from '../types';

interface Props {
  onClose: () => void;
  players?: Player[];
}

export function CombatTracker({ onClose, players = [] }: Props) {
  const [combatState, setCombatState] = useState<CombatState | null>(null);
  const [combatants, setCombatants] = useState<Combatant[]>([]);
  const [showAddCombatant, setShowAddCombatant] = useState(false);

  const rollInitiative = () => {
    // Roll initiative for all combatants and sort
    const withInitiative = combatants.map((c) => ({
      ...c,
      initiative: Math.floor(Math.random() * 20) + 1 + (c.initiative_bonus || 0),
    }));
    withInitiative.sort((a, b) => b.initiative - a.initiative);

    setCombatState({
      round: 1,
      initiative_order: withInitiative,
      current_turn_idx: 0,
      active: true,
    });
  };

  const addFromPlayers = () => {
    const playerCombatants: Combatant[] = players
      .filter((p) => p.active_pc)
      .map((p) => ({
        name: p.active_pc!.name,
        initiative: 0,
        initiative_bonus: p.active_pc!.initiative_bonus || 0,
        hp: p.active_pc!.hp || 10,
        max_hp: p.active_pc!.max_hp || 10,
        is_player: true,
        player_id: p.id,
        player_name: p.name,
        pc_id: p.active_pc!.id,
        character_name: p.active_pc!.name,
        conditions: [],
      }));

    setCombatants((prev) => [...prev, ...playerCombatants]);
  };

  const addCombatant = (combatant: Combatant) => {
    setCombatants((prev) => [...prev, combatant]);
    setShowAddCombatant(false);
  };

  const removeCombatant = (index: number) => {
    setCombatants((prev) => prev.filter((_, i) => i !== index));
  };

  const nextTurn = () => {
    if (!combatState) return;

    let nextIdx = combatState.current_turn_idx + 1;
    let newRound = combatState.round;

    if (nextIdx >= combatState.initiative_order.length) {
      nextIdx = 0;
      newRound += 1;
    }

    // Skip dead combatants
    while (combatState.initiative_order[nextIdx].hp <= 0) {
      nextIdx += 1;
      if (nextIdx >= combatState.initiative_order.length) {
        nextIdx = 0;
        newRound += 1;
      }
    }

    setCombatState({
      ...combatState,
      current_turn_idx: nextIdx,
      round: newRound,
    });
  };

  const applyDamage = (index: number, damage: number) => {
    if (!combatState) return;

    const updated = [...combatState.initiative_order];
    updated[index] = {
      ...updated[index],
      hp: Math.max(0, updated[index].hp - damage),
    };

    setCombatState({
      ...combatState,
      initiative_order: updated,
    });
  };

  const applyHealing = (index: number, healing: number) => {
    if (!combatState) return;

    const updated = [...combatState.initiative_order];
    updated[index] = {
      ...updated[index],
      hp: Math.min(updated[index].max_hp, updated[index].hp + healing),
    };

    setCombatState({
      ...combatState,
      initiative_order: updated,
    });
  };

  const endCombat = () => {
    setCombatState(null);
    setCombatants([]);
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-gray-800 rounded-lg shadow-xl w-full max-w-4xl max-h-[85vh] flex flex-col">
        {/* Header */}
        <div className="px-6 py-4 border-b border-gray-700 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <h2 className="text-xl font-bold">Combat Tracker</h2>
            {combatState && (
              <span className="px-3 py-1 bg-red-600/30 text-red-400 rounded-full text-sm">
                Round {combatState.round}
              </span>
            )}
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-white transition-colors"
          >
            ✕
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6">
          {!combatState ? (
            // Setup Phase
            <div className="space-y-6">
              <div className="flex items-center justify-between">
                <h3 className="font-medium">Combatants</h3>
                <div className="flex gap-2">
                  {players.length > 0 && (
                    <button
                      onClick={addFromPlayers}
                      className="px-3 py-1 text-sm bg-green-600 hover:bg-green-700 rounded transition-colors"
                    >
                      + Add Players
                    </button>
                  )}
                  <button
                    onClick={() => setShowAddCombatant(true)}
                    className="px-3 py-1 text-sm bg-blue-600 hover:bg-blue-700 rounded transition-colors"
                  >
                    + Add Monster/NPC
                  </button>
                </div>
              </div>

              {combatants.length === 0 ? (
                <div className="text-center text-gray-400 py-8">
                  Add combatants to start combat
                </div>
              ) : (
                <div className="space-y-2">
                  {combatants.map((c, idx) => (
                    <div
                      key={idx}
                      className={`p-3 rounded-lg flex items-center justify-between ${
                        c.is_player ? 'bg-blue-600/20' : 'bg-red-600/20'
                      }`}
                    >
                      <div>
                        <div className="font-medium">{c.name}</div>
                        <div className="text-sm text-gray-400">
                          {c.is_player ? `${c.player_name}'s character` : 'Monster/NPC'}
                          {' | '}Init: +{c.initiative_bonus || 0}
                          {' | '}HP: {c.hp}/{c.max_hp}
                        </div>
                      </div>
                      <button
                        onClick={() => removeCombatant(idx)}
                        className="text-gray-400 hover:text-red-400 transition-colors"
                      >
                        ✕
                      </button>
                    </div>
                  ))}
                </div>
              )}

              {combatants.length >= 2 && (
                <div className="flex justify-center pt-4">
                  <button
                    onClick={rollInitiative}
                    className="px-6 py-3 bg-red-600 hover:bg-red-700 rounded-lg font-medium transition-colors"
                  >
                    Roll Initiative & Start Combat
                  </button>
                </div>
              )}
            </div>
          ) : (
            // Combat Phase
            <div className="space-y-4">
              {combatState.initiative_order.map((c, idx) => (
                <CombatantCard
                  key={idx}
                  combatant={c}
                  isCurrentTurn={idx === combatState.current_turn_idx}
                  onDamage={(dmg) => applyDamage(idx, dmg)}
                  onHeal={(heal) => applyHealing(idx, heal)}
                />
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-gray-700 flex justify-between items-center">
          {combatState ? (
            <>
              <div className="text-sm text-gray-400">
                Current: {combatState.initiative_order[combatState.current_turn_idx]?.name}
              </div>
              <div className="flex gap-3">
                <button
                  onClick={endCombat}
                  className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg transition-colors"
                >
                  End Combat
                </button>
                <button
                  onClick={nextTurn}
                  className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors"
                >
                  Next Turn
                </button>
              </div>
            </>
          ) : (
            <button
              onClick={onClose}
              className="ml-auto px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg transition-colors"
            >
              Close
            </button>
          )}
        </div>
      </div>

      {/* Add Combatant Modal */}
      {showAddCombatant && (
        <AddCombatantModal
          onClose={() => setShowAddCombatant(false)}
          onAdd={addCombatant}
        />
      )}
    </div>
  );
}

interface CombatantCardProps {
  combatant: Combatant;
  isCurrentTurn: boolean;
  onDamage: (damage: number) => void;
  onHeal: (healing: number) => void;
}

function CombatantCard({ combatant, isCurrentTurn, onDamage, onHeal }: CombatantCardProps) {
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

interface AddCombatantModalProps {
  onClose: () => void;
  onAdd: (combatant: Combatant) => void;
}

function AddCombatantModal({ onClose, onAdd }: AddCombatantModalProps) {
  const [name, setName] = useState('');
  const [hp, setHp] = useState(10);
  const [initiativeBonus, setInitiativeBonus] = useState(0);
  const [count, setCount] = useState(1);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;

    for (let i = 0; i < count; i++) {
      const suffix = count > 1 ? ` ${i + 1}` : '';
      onAdd({
        name: name.trim() + suffix,
        initiative: 0,
        initiative_bonus: initiativeBonus,
        hp,
        max_hp: hp,
        is_player: false,
        conditions: [],
      });
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-[60]">
      <div className="bg-gray-800 rounded-lg shadow-xl w-full max-w-md p-6">
        <h3 className="text-lg font-bold mb-4">Add Monster/NPC</h3>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm text-gray-400 mb-1">Name *</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., Goblin"
              className="w-full px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-blue-500"
              autoFocus
            />
          </div>
          <div className="grid grid-cols-3 gap-4">
            <div>
              <label className="block text-sm text-gray-400 mb-1">HP</label>
              <input
                type="number"
                min={1}
                value={hp}
                onChange={(e) => setHp(parseInt(e.target.value) || 1)}
                className="w-full px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-blue-500"
              />
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1">Init Bonus</label>
              <input
                type="number"
                value={initiativeBonus}
                onChange={(e) => setInitiativeBonus(parseInt(e.target.value) || 0)}
                className="w-full px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-blue-500"
              />
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1">Count</label>
              <input
                type="number"
                min={1}
                max={20}
                value={count}
                onChange={(e) => setCount(parseInt(e.target.value) || 1)}
                className="w-full px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-blue-500"
              />
            </div>
          </div>
          <div className="flex justify-end gap-3 pt-4">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!name.trim()}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors disabled:opacity-50"
            >
              Add {count > 1 ? `${count} Combatants` : 'Combatant'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
