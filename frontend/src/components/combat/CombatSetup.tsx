import type { Player } from '../../types';
import type { SetupCombatant } from './types';

interface CombatSetupProps {
  setupCombatants: SetupCombatant[];
  players: Player[];
  isLoading: boolean;
  onAddFromPlayers: () => void;
  onOpenAddCombatant: () => void;
  onRemoveCombatant: (index: number) => void;
  onStartCombat: () => void;
}

export function CombatSetup({
  setupCombatants,
  players,
  isLoading,
  onAddFromPlayers,
  onOpenAddCombatant,
  onRemoveCombatant,
  onStartCombat,
}: CombatSetupProps) {
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h3 className="font-medium">Combatants</h3>
        <div className="flex gap-2">
          {players.length > 0 && (
            <button
              onClick={onAddFromPlayers}
              className="px-3 py-1 text-sm bg-green-600 hover:bg-green-700 rounded transition-colors"
            >
              + Add Players
            </button>
          )}
          <button
            onClick={onOpenAddCombatant}
            className="px-3 py-1 text-sm bg-blue-600 hover:bg-blue-700 rounded transition-colors"
          >
            + Add Monster/NPC
          </button>
        </div>
      </div>

      {setupCombatants.length === 0 ? (
        <div className="text-center text-gray-400 py-8">
          Add combatants to start combat
        </div>
      ) : (
        <div className="space-y-2">
          {setupCombatants.map((c, idx) => (
            <div
              key={idx}
              className={`p-3 rounded-lg flex items-center justify-between ${
                c.is_player
                  ? 'bg-blue-600/20'
                  : c.is_friendly
                    ? 'bg-green-600/20 border border-green-500/30'
                    : c.is_npc
                      ? 'bg-purple-600/20 border border-purple-500/30'
                      : 'bg-red-600/20'
              }`}
            >
              <div>
                <div className="font-medium flex items-center gap-2">
                  {c.name}
                  {c.is_npc && (
                    <span className="px-2 py-0.5 bg-purple-600 text-purple-100 text-xs rounded">
                      AI
                    </span>
                  )}
                  {c.is_friendly && (
                    <span className="px-2 py-0.5 bg-green-600 text-green-100 text-xs rounded">
                      Friendly
                    </span>
                  )}
                </div>
                <div className="text-sm text-gray-400">
                  {c.is_player
                    ? `${c.player_name}'s character`
                    : c.is_npc
                      ? 'AI-controlled NPC'
                      : 'DM-controlled Monster'}
                  {' | '}Init: +{c.initiative_bonus || 0}
                  {' | '}HP: {c.hp}/{c.max_hp}
                  {' | '}AC: {c.ac}
                </div>
              </div>
              <button
                onClick={() => onRemoveCombatant(idx)}
                className="text-gray-400 hover:text-red-400 transition-colors"
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      )}

      {setupCombatants.length >= 2 && (
        <div className="flex justify-center pt-4">
          <button
            onClick={onStartCombat}
            disabled={isLoading}
            className="px-6 py-3 bg-red-600 hover:bg-red-700 rounded-lg font-medium transition-colors disabled:opacity-50"
          >
            {isLoading ? 'Starting...' : 'Roll Initiative & Start Combat'}
          </button>
        </div>
      )}
    </div>
  );
}
