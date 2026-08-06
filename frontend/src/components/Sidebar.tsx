import type { Campaign } from '../types';

interface Props {
  activeCampaign: Campaign;
  onDeselectCampaign: () => void;
  onEditCampaign: () => void;
  sessionId: string | null;
  onNewSession: () => void;
  onClearHistory: () => void;
  onOpenCampaign: () => void;
  onOpenPlayers: () => void;
  onOpenCombat: () => void;
  onOpenShop: () => void;
  onOpenAudio: () => void;
  combatActive?: boolean;
  shopActive?: boolean;
  audioActive?: boolean;
}

export function Sidebar({
  activeCampaign,
  onDeselectCampaign,
  onEditCampaign,
  sessionId,
  onNewSession,
  onClearHistory,
  onOpenCampaign,
  onOpenPlayers,
  onOpenCombat,
  onOpenShop,
  onOpenAudio,
  combatActive,
  shopActive,
  audioActive,
}: Props) {
  return (
    <aside className="w-64 bg-gray-900 border-r border-gray-700 flex flex-col">
      {/* Logo */}
      <div className="p-4 border-b border-gray-700">
        <h1 className="text-xl font-bold text-white flex items-center gap-2">
          DM Assistant
        </h1>
        <p className="text-xs text-gray-400 mt-1">AI-Powered D&D 5e</p>
      </div>

      {/* Campaign Info */}
      <div className="p-4 border-b border-gray-700">
        <button
          onClick={onDeselectCampaign}
          className="text-sm text-gray-400 hover:text-white transition-colors mb-2 flex items-center gap-1"
        >
          &larr; All Campaigns
        </button>
        <div className="flex items-start justify-between gap-1">
          <h2 className="font-semibold text-white leading-tight">{activeCampaign.name}</h2>
          <button
            onClick={onEditCampaign}
            className="px-1.5 py-1 text-gray-400 hover:text-white transition-colors shrink-0"
            title="Edit campaign"
          >
            &#9998;
          </button>
        </div>
        {(activeCampaign.setting || activeCampaign.theme) && (
          <p className="text-xs text-gray-500 mt-1">
            {activeCampaign.setting}
            {activeCampaign.setting && activeCampaign.theme && ' · '}
            {activeCampaign.theme}
          </p>
        )}
        {activeCampaign.status && activeCampaign.status !== 'active' && (
          <span className="inline-block mt-1 text-xs px-2 py-0.5 rounded-full bg-yellow-600/20 text-yellow-400">
            {activeCampaign.status}
          </span>
        )}
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
          className={`w-full py-2 px-4 rounded-lg text-sm transition-colors flex items-center justify-center gap-2 ${
            combatActive
              ? 'bg-red-600 ring-2 ring-red-400 ring-offset-1 ring-offset-gray-900'
              : 'bg-red-600/80 hover:bg-red-600'
          }`}
        >
          <span>⚔️</span>
          <span>{combatActive ? 'Combat Active' : 'Combat Tracker'}</span>
        </button>
        <button
          onClick={onOpenShop}
          className={`w-full py-2 px-4 rounded-lg text-sm transition-colors flex items-center justify-center gap-2 ${
            shopActive
              ? 'bg-amber-600 ring-2 ring-amber-400 ring-offset-1 ring-offset-gray-900'
              : 'bg-amber-600/80 hover:bg-amber-600'
          }`}
        >
          <span>🏪</span>
          <span>{shopActive ? 'Shop Open' : 'Shop'}</span>
        </button>
        <button
          onClick={onOpenAudio}
          className={`w-full py-2 px-4 rounded-lg text-sm transition-colors flex items-center justify-center gap-2 ${
            audioActive
              ? 'bg-blue-600 ring-2 ring-blue-400 ring-offset-1 ring-offset-gray-900'
              : 'bg-blue-600/80 hover:bg-blue-600'
          }`}
        >
          <span>🎙️</span>
          <span>{audioActive ? 'Transcribing' : 'Session Transcript'}</span>
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
