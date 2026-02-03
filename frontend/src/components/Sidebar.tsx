import type { DMMode } from '../types';

interface Props {
  mode: DMMode;
  onModeChange: (mode: DMMode) => void;
  sessionId: string | null;
  onNewSession: () => void;
  onClearHistory: () => void;
  onOpenCampaign: () => void;
  onOpenPlayers: () => void;
  onOpenCombat: () => void;
}

export function Sidebar({
  mode,
  onModeChange,
  sessionId,
  onNewSession,
  onClearHistory,
  onOpenCampaign,
  onOpenPlayers,
  onOpenCombat,
}: Props) {
  return (
    <aside className="w-64 bg-gray-900 border-r border-gray-700 flex flex-col">
      {/* Logo */}
      <div className="p-4 border-b border-gray-700">
        <h1 className="text-xl font-bold text-white flex items-center gap-2">
          🎲 DM Assistant
        </h1>
        <p className="text-xs text-gray-400 mt-1">AI-Powered D&D 5e</p>
      </div>

      {/* Mode Selector */}
      <div className="p-4 border-b border-gray-700">
        <label className="text-sm text-gray-400 block mb-2">Mode</label>
        <div className="flex gap-2">
          <button
            onClick={() => onModeChange('assistant')}
            className={`flex-1 py-2 px-3 rounded-lg text-sm font-medium transition-colors ${
              mode === 'assistant'
                ? 'bg-blue-600 text-white'
                : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
            }`}
          >
            Assistant
          </button>
          <button
            onClick={() => onModeChange('autonomous')}
            className={`flex-1 py-2 px-3 rounded-lg text-sm font-medium transition-colors ${
              mode === 'autonomous'
                ? 'bg-purple-600 text-white'
                : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
            }`}
          >
            DM Mode
          </button>
        </div>
        <p className="text-xs text-gray-500 mt-2">
          {mode === 'assistant'
            ? 'Helps you run your game with rules lookups and suggestions.'
            : 'Takes the DM seat and runs the game for you.'}
        </p>
      </div>

      {/* Quick Actions */}
      <div className="p-4 border-b border-gray-700">
        <label className="text-sm text-gray-400 block mb-2">Quick Actions</label>
        <div className="space-y-2">
          <QuickAction label="Roll Dice" command="/roll 1d20" icon="🎲" />
          <QuickAction label="Generate NPC" command="/npc merchant" icon="👤" />
          <QuickAction label="Create Encounter" command="/encounter medium" icon="⚔️" />
        </div>
      </div>

      {/* Session Info */}
      <div className="p-4 border-b border-gray-700">
        <label className="text-sm text-gray-400 block mb-2">Session</label>
        {sessionId ? (
          <div className="text-xs text-gray-500 font-mono truncate mb-2">
            {sessionId.slice(0, 8)}...
          </div>
        ) : (
          <div className="text-xs text-gray-500 mb-2">No active session</div>
        )}
        <div className="flex gap-2">
          <button
            onClick={onNewSession}
            className="flex-1 py-2 px-3 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm transition-colors"
          >
            New Session
          </button>
          <button
            onClick={onClearHistory}
            className="py-2 px-3 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm transition-colors"
            title="Clear History"
          >
            🗑️
          </button>
        </div>
      </div>

      {/* Campaign & Tools */}
      <div className="p-4 border-b border-gray-700 space-y-2">
        <label className="text-sm text-gray-400 block mb-2">Campaign Tools</label>
        <button
          onClick={onOpenCampaign}
          className="w-full py-2 px-4 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm transition-colors flex items-center justify-center gap-2"
        >
          <span>🗺️</span>
          <span>Knowledge Graph</span>
        </button>
        <button
          onClick={onOpenPlayers}
          className="w-full py-2 px-4 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm transition-colors flex items-center justify-center gap-2"
        >
          <span>👥</span>
          <span>Manage Players</span>
        </button>
        <button
          onClick={onOpenCombat}
          className="w-full py-2 px-4 bg-red-600/80 hover:bg-red-600 rounded-lg text-sm transition-colors flex items-center justify-center gap-2"
        >
          <span>⚔️</span>
          <span>Combat Tracker</span>
        </button>
      </div>

      {/* Help */}
      <div className="mt-auto p-4 border-t border-gray-700">
        <div className="text-xs text-gray-500 space-y-1">
          <p>
            <strong>Commands:</strong>
          </p>
          <p>/roll [dice] - Roll dice</p>
          <p>/npc [role] - Generate NPC</p>
          <p>/encounter - Create encounter</p>
        </div>
      </div>
    </aside>
  );
}

interface QuickActionProps {
  label: string;
  command: string;
  icon: string;
}

function QuickAction({ label, command, icon }: QuickActionProps) {
  const handleClick = () => {
    // Copy command to clipboard or insert into chat
    navigator.clipboard.writeText(command);
  };

  return (
    <button
      onClick={handleClick}
      className="w-full flex items-center gap-2 p-2 bg-gray-800 hover:bg-gray-700 rounded-lg text-sm transition-colors text-left"
    >
      <span>{icon}</span>
      <span className="flex-1">{label}</span>
      <span className="text-gray-500 text-xs font-mono">{command.split(' ')[0]}</span>
    </button>
  );
}
