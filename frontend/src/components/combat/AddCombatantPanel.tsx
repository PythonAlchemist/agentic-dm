import { useState, useEffect } from 'react';
import { combatAPI } from '../../api/client';
import type { AvailableNPC } from '../../api/client';
import type { SetupCombatant } from './types';

interface AddCombatantPanelProps {
  onClose: () => void;
  onAdd: (combatant: SetupCombatant & { x?: number; y?: number }) => void;
  midCombat?: boolean;
}

export function AddCombatantPanel({ onClose, onAdd, midCombat }: AddCombatantPanelProps) {
  const [mode, setMode] = useState<'manual' | 'npc'>('npc');
  const [name, setName] = useState('');
  const [hp, setHp] = useState(10);
  const [ac, setAc] = useState(12);
  const [initiativeBonus, setInitiativeBonus] = useState(0);
  const [count, setCount] = useState(1);

  // NPC selection state
  const [availableNPCs, setAvailableNPCs] = useState<AvailableNPC[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [loadingNPCs, setLoadingNPCs] = useState(false);
  const [selectedNPC, setSelectedNPC] = useState<AvailableNPC | null>(null);
  const [isFriendly, setIsFriendly] = useState(false);

  // Load available NPCs
  useEffect(() => {
    const loadNPCs = async () => {
      setLoadingNPCs(true);
      try {
        const npcs = await combatAPI.searchNPCs(searchQuery || undefined, false, 20);
        setAvailableNPCs(npcs);
      } catch (err) {
        console.error('Failed to load NPCs:', err);
      } finally {
        setLoadingNPCs(false);
      }
    };

    const debounce = setTimeout(loadNPCs, 300);
    return () => clearTimeout(debounce);
  }, [searchQuery]);

  const handleSelectNPC = (npc: AvailableNPC) => {
    setSelectedNPC(npc);
    setName(npc.name);
    setHp(npc.hp);
    setAc(npc.ac);
    setInitiativeBonus(npc.initiative_bonus);
    setIsFriendly(false);
  };

  const handleSubmit = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!name.trim()) return;

    for (let i = 0; i < count; i++) {
      const suffix = count > 1 ? ` ${i + 1}` : '';
      onAdd({
        name: name.trim() + suffix,
        initiative_bonus: initiativeBonus,
        hp,
        max_hp: hp,
        ac,
        is_player: false,
        is_npc: selectedNPC !== null,
        is_friendly: selectedNPC !== null ? isFriendly : undefined,
        npc_id: selectedNPC?.entity_id,
      });
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-[60]">
      <div className="bg-gray-800 rounded-lg shadow-xl w-full max-w-lg p-6">
        <h3 className="text-lg font-bold mb-4">
          {midCombat ? 'Add to Combat' : 'Add Monster/NPC'}
        </h3>

        {/* Mode Toggle */}
        <div className="flex gap-2 mb-4">
          <button
            type="button"
            onClick={() => { setMode('npc'); setSelectedNPC(null); }}
            className={`flex-1 py-2 rounded-lg transition-colors ${
              mode === 'npc'
                ? 'bg-purple-600 text-white'
                : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
            }`}
          >
            AI NPCs
          </button>
          <button
            type="button"
            onClick={() => { setMode('manual'); setSelectedNPC(null); }}
            className={`flex-1 py-2 rounded-lg transition-colors ${
              mode === 'manual'
                ? 'bg-blue-600 text-white'
                : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
            }`}
          >
            Manual Entry
          </button>
        </div>

        {mode === 'npc' ? (
          // NPC Selection Mode
          <div className="space-y-4">
            <div>
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search NPCs..."
                className="w-full px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-purple-500"
                autoFocus
              />
            </div>

            {/* NPC List */}
            <div className="max-h-60 overflow-y-auto space-y-2">
              {loadingNPCs ? (
                <div className="text-center text-gray-400 py-4">Loading NPCs...</div>
              ) : availableNPCs.length === 0 ? (
                <div className="text-center text-gray-400 py-4">
                  No AI NPCs found. Use Manual Entry to add basic monsters.
                </div>
              ) : (
                availableNPCs.map((npc) => (
                  <button
                    key={npc.entity_id}
                    type="button"
                    onClick={() => handleSelectNPC(npc)}
                    className={`w-full p-3 rounded-lg text-left transition-colors ${
                      selectedNPC?.entity_id === npc.entity_id
                        ? 'bg-purple-600/30 border-2 border-purple-500'
                        : 'bg-gray-700/50 hover:bg-gray-700 border border-transparent'
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <div>
                        <div className="font-medium">{npc.name}</div>
                        <div className="text-sm text-gray-400">
                          {npc.race} {npc.role} | CR {npc.challenge_rating}
                        </div>
                      </div>
                      <div className="text-right text-sm">
                        <div className="text-red-400">HP: {npc.hp}</div>
                        <div className="text-blue-400">AC: {npc.ac}</div>
                      </div>
                    </div>
                  </button>
                ))
              )}
            </div>

            {selectedNPC && (
              <div className="border-t border-gray-700 pt-4 space-y-4">
                {/* Friendly Toggle */}
                <div className="flex items-center justify-between p-3 bg-gray-700/50 rounded-lg">
                  <div>
                    <div className="font-medium">Friendly NPC</div>
                    <div className="text-sm text-gray-400">Fights alongside the party</div>
                  </div>
                  <button
                    type="button"
                    onClick={() => setIsFriendly(!isFriendly)}
                    className={`relative w-14 h-8 rounded-full transition-colors ${
                      isFriendly ? 'bg-green-600' : 'bg-gray-600'
                    }`}
                  >
                    <div
                      className={`absolute top-1 w-6 h-6 bg-white rounded-full transition-transform ${
                        isFriendly ? 'translate-x-7' : 'translate-x-1'
                      }`}
                    />
                  </button>
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm text-gray-400 mb-1">Count</label>
                    <input
                      type="number"
                      min={1}
                      max={10}
                      value={count}
                      onChange={(e) => setCount(parseInt(e.target.value) || 1)}
                      className="w-full px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg"
                    />
                  </div>
                  <div className="flex items-end">
                    <button
                      type="button"
                      onClick={() => handleSubmit()}
                      className={`w-full px-4 py-2 rounded-lg transition-colors ${
                        isFriendly
                          ? 'bg-green-600 hover:bg-green-700'
                          : 'bg-purple-600 hover:bg-purple-700'
                      }`}
                    >
                      Add {count > 1 ? `${count}x ${selectedNPC.name}` : selectedNPC.name}
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        ) : (
          // Manual Entry Mode
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
                <label className="block text-sm text-gray-400 mb-1">AC</label>
                <input
                  type="number"
                  min={1}
                  value={ac}
                  onChange={(e) => setAc(parseInt(e.target.value) || 10)}
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

            <div className="text-sm text-gray-500 bg-gray-700/30 p-3 rounded-lg">
              Manual entries are DM-controlled. For AI-controlled NPCs with autonomous combat actions, use the AI NPCs tab.
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
        )}

        {/* Close button for NPC mode */}
        {mode === 'npc' && (
          <div className="flex justify-end mt-4 pt-4 border-t border-gray-700">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg transition-colors"
            >
              Cancel
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
