import { useState, useEffect, useCallback } from 'react';
import { playerAPI, campaignManagementAPI } from '../api/client';
import type { Player, PlayerCreate, PC, PCCreate } from '../types';

interface Props {
  onClose: () => void;
  campaignId?: string;
}

export function PlayerManager({ onClose, campaignId }: Props) {
  const [players, setPlayers] = useState<Player[]>([]);
  const [selectedPlayer, setSelectedPlayer] = useState<Player | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showCreatePlayer, setShowCreatePlayer] = useState(false);
  const [showCreateCharacter, setShowCreateCharacter] = useState(false);

  const loadPlayers = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await playerAPI.list(campaignId);
      setPlayers(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load players');
      setPlayers([]);
    } finally {
      setIsLoading(false);
    }
  }, [campaignId]);

  useEffect(() => {
    loadPlayers();
  }, [loadPlayers]);

  const handleCreatePlayer = async (data: PlayerCreate) => {
    try {
      const newPlayer = await playerAPI.create(data);
      if (campaignId) {
        await campaignManagementAPI.addPlayer(campaignId, newPlayer.id);
      }
      await loadPlayers();
      setShowCreatePlayer(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create player');
    }
  };

  const handleCreateCharacter = async (playerId: string, data: PCCreate) => {
    try {
      await playerAPI.createCharacter(playerId, data);
      await loadPlayers();
      if (selectedPlayer?.id === playerId) {
        const updated = await playerAPI.get(playerId);
        setSelectedPlayer(updated);
      }
      setShowCreateCharacter(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create character');
    }
  };

  const handleSetActiveCharacter = async (playerId: string, pcId: string) => {
    try {
      const updated = await playerAPI.setActiveCharacter(playerId, pcId);
      setSelectedPlayer(updated);
      await loadPlayers();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to set active character');
    }
  };

  const handleDeletePlayer = async (playerId: string) => {
    if (!confirm('Are you sure you want to delete this player?')) return;
    try {
      await playerAPI.delete(playerId);
      if (selectedPlayer?.id === playerId) {
        setSelectedPlayer(null);
      }
      await loadPlayers();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete player');
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-gray-800 rounded-lg shadow-xl w-full max-w-5xl max-h-[85vh] flex flex-col">
        {/* Header */}
        <div className="px-6 py-4 border-b border-gray-700 flex items-center justify-between">
          <h2 className="text-xl font-bold">
            Player Management
            {campaignId && <span className="text-gray-400 text-sm ml-2">(Campaign)</span>}
          </h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-white transition-colors"
          >
            ✕
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 flex overflow-hidden">
          {/* Player List */}
          <div className="w-1/3 border-r border-gray-700 flex flex-col">
            <div className="p-4 border-b border-gray-700">
              <button
                onClick={() => setShowCreatePlayer(true)}
                className="w-full px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors"
              >
                + Add Player
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-4 space-y-2">
              {isLoading ? (
                <div className="text-center text-gray-400 py-8">Loading...</div>
              ) : error ? (
                <div className="text-center text-red-400 py-8">{error}</div>
              ) : players.length === 0 ? (
                <div className="text-center text-gray-400 py-8">No players yet</div>
              ) : (
                players.map((player) => (
                  <PlayerCard
                    key={player.id}
                    player={player}
                    isSelected={selectedPlayer?.id === player.id}
                    onClick={() => setSelectedPlayer(player)}
                  />
                ))
              )}
            </div>
          </div>

          {/* Player Details */}
          <div className="flex-1 overflow-y-auto p-6">
            {selectedPlayer ? (
              <PlayerDetails
                player={selectedPlayer}
                onCreateCharacter={() => setShowCreateCharacter(true)}
                onSetActiveCharacter={(pcId) => handleSetActiveCharacter(selectedPlayer.id, pcId)}
                onDelete={() => handleDeletePlayer(selectedPlayer.id)}
              />
            ) : (
              <div className="h-full flex items-center justify-center text-gray-400">
                Select a player to view details
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-gray-700 flex justify-between items-center">
          <span className="text-sm text-gray-400">{players.length} players</span>
          <button
            onClick={onClose}
            className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg transition-colors"
          >
            Close
          </button>
        </div>
      </div>

      {/* Create Player Modal */}
      {showCreatePlayer && (
        <CreatePlayerModal
          onClose={() => setShowCreatePlayer(false)}
          onCreate={handleCreatePlayer}
        />
      )}

      {/* Create Character Modal */}
      {showCreateCharacter && selectedPlayer && (
        <CreateCharacterModal
          playerName={selectedPlayer.name}
          onClose={() => setShowCreateCharacter(false)}
          onCreate={(data) => handleCreateCharacter(selectedPlayer.id, data)}
        />
      )}
    </div>
  );
}

interface PlayerCardProps {
  player: Player;
  isSelected: boolean;
  onClick: () => void;
}

function PlayerCard({ player, isSelected, onClick }: PlayerCardProps) {
  return (
    <button
      onClick={onClick}
      className={`w-full p-3 rounded-lg text-left transition-colors ${
        isSelected ? 'bg-blue-600' : 'bg-gray-700/50 hover:bg-gray-700'
      }`}
    >
      <div className="font-medium">{player.name}</div>
      {player.active_pc && (
        <div className="text-sm text-gray-300 mt-1">
          Playing: {player.active_pc.name}
        </div>
      )}
      <div className="text-xs text-gray-400 mt-1">
        {player.characters.length} character{player.characters.length !== 1 ? 's' : ''}
      </div>
    </button>
  );
}

interface PlayerDetailsProps {
  player: Player;
  onCreateCharacter: () => void;
  onSetActiveCharacter: (pcId: string) => void;
  onDelete: () => void;
}

function PlayerDetails({ player, onCreateCharacter, onSetActiveCharacter, onDelete }: PlayerDetailsProps) {
  return (
    <div className="space-y-6">
      {/* Player Info */}
      <div>
        <h3 className="text-lg font-bold mb-4">{player.name}</h3>
        <div className="grid grid-cols-2 gap-4 text-sm">
          {player.email && (
            <div>
              <span className="text-gray-400">Email:</span>{' '}
              <span>{player.email}</span>
            </div>
          )}
          {player.discord_id && (
            <div>
              <span className="text-gray-400">Discord:</span>{' '}
              <span>{player.discord_id}</span>
            </div>
          )}
          {player.joined_at && (
            <div>
              <span className="text-gray-400">Joined:</span>{' '}
              <span>{new Date(player.joined_at).toLocaleDateString()}</span>
            </div>
          )}
        </div>
      </div>

      {/* Characters */}
      <div>
        <div className="flex items-center justify-between mb-4">
          <h4 className="font-medium">Characters</h4>
          <button
            onClick={onCreateCharacter}
            className="px-3 py-1 text-sm bg-green-600 hover:bg-green-700 rounded transition-colors"
          >
            + New Character
          </button>
        </div>
        {player.characters.length === 0 ? (
          <div className="text-gray-400 text-sm">No characters yet</div>
        ) : (
          <div className="space-y-2">
            {player.characters.map((pc) => (
              <CharacterCard
                key={pc.id}
                pc={pc}
                isActive={player.active_pc_id === pc.id}
                onSetActive={() => onSetActiveCharacter(pc.id)}
              />
            ))}
          </div>
        )}
      </div>

      {/* Actions */}
      <div className="pt-4 border-t border-gray-700">
        <button
          onClick={onDelete}
          className="px-4 py-2 text-sm bg-red-600/20 hover:bg-red-600/40 text-red-400 rounded transition-colors"
        >
          Delete Player
        </button>
      </div>
    </div>
  );
}

interface CharacterCardProps {
  pc: PC;
  isActive: boolean;
  onSetActive: () => void;
}

function CharacterCard({ pc, isActive, onSetActive }: CharacterCardProps) {
  return (
    <div className={`p-3 rounded-lg ${isActive ? 'bg-green-600/20 border border-green-600/50' : 'bg-gray-700/50'}`}>
      <div className="flex items-center justify-between">
        <div>
          <div className="font-medium">
            {pc.name}
            {isActive && <span className="ml-2 text-xs text-green-400">(Active)</span>}
          </div>
          <div className="text-sm text-gray-300">
            Level {pc.level} {pc.race} {pc.character_class}
          </div>
          {pc.hp !== undefined && pc.max_hp !== undefined && (
            <div className="text-xs text-gray-400 mt-1">
              HP: {pc.hp}/{pc.max_hp}
            </div>
          )}
        </div>
        {!isActive && (
          <button
            onClick={onSetActive}
            className="px-3 py-1 text-sm bg-gray-600 hover:bg-gray-500 rounded transition-colors"
          >
            Set Active
          </button>
        )}
      </div>
    </div>
  );
}

interface CreatePlayerModalProps {
  onClose: () => void;
  onCreate: (data: PlayerCreate) => void;
}

function CreatePlayerModal({ onClose, onCreate }: CreatePlayerModalProps) {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [discordId, setDiscordId] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    onCreate({
      name: name.trim(),
      email: email.trim() || undefined,
      discord_id: discordId.trim() || undefined,
    });
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-[60]">
      <div className="bg-gray-800 rounded-lg shadow-xl w-full max-w-md p-6">
        <h3 className="text-lg font-bold mb-4">Add Player</h3>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm text-gray-400 mb-1">Name *</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-blue-500"
              autoFocus
            />
          </div>
          <div>
            <label className="block text-sm text-gray-400 mb-1">Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-blue-500"
            />
          </div>
          <div>
            <label className="block text-sm text-gray-400 mb-1">Discord ID</label>
            <input
              type="text"
              value={discordId}
              onChange={(e) => setDiscordId(e.target.value)}
              className="w-full px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-blue-500"
            />
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
              Create
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

interface CreateCharacterModalProps {
  playerName: string;
  onClose: () => void;
  onCreate: (data: PCCreate) => void;
}

function CreateCharacterModal({ playerName, onClose, onCreate }: CreateCharacterModalProps) {
  const [name, setName] = useState('');
  const [characterClass, setCharacterClass] = useState('');
  const [level, setLevel] = useState(1);
  const [race, setRace] = useState('');
  const [hp, setHp] = useState<number | ''>('');
  const [initiativeBonus, setInitiativeBonus] = useState(0);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !characterClass.trim()) return;
    onCreate({
      name: name.trim(),
      character_class: characterClass.trim(),
      level,
      race: race.trim() || undefined,
      hp: hp || undefined,
      max_hp: hp || undefined,
      initiative_bonus: initiativeBonus,
    });
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-[60]">
      <div className="bg-gray-800 rounded-lg shadow-xl w-full max-w-md p-6">
        <h3 className="text-lg font-bold mb-4">Create Character for {playerName}</h3>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm text-gray-400 mb-1">Character Name *</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-blue-500"
              autoFocus
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm text-gray-400 mb-1">Class *</label>
              <input
                type="text"
                value={characterClass}
                onChange={(e) => setCharacterClass(e.target.value)}
                placeholder="e.g., Fighter"
                className="w-full px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-blue-500"
              />
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1">Race</label>
              <input
                type="text"
                value={race}
                onChange={(e) => setRace(e.target.value)}
                placeholder="e.g., Human"
                className="w-full px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-blue-500"
              />
            </div>
          </div>
          <div className="grid grid-cols-3 gap-4">
            <div>
              <label className="block text-sm text-gray-400 mb-1">Level</label>
              <input
                type="number"
                min={1}
                max={20}
                value={level}
                onChange={(e) => setLevel(parseInt(e.target.value) || 1)}
                className="w-full px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-blue-500"
              />
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1">HP</label>
              <input
                type="number"
                min={1}
                value={hp}
                onChange={(e) => setHp(e.target.value ? parseInt(e.target.value) : '')}
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
              disabled={!name.trim() || !characterClass.trim()}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors disabled:opacity-50"
            >
              Create
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
