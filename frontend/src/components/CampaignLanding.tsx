import type { Campaign } from '../types';

interface Props {
  campaigns: Campaign[];
  isLoading: boolean;
  onSelectCampaign: (id: string) => void;
  onNewCampaign: () => void;
}

export function CampaignLanding({
  campaigns,
  isLoading,
  onSelectCampaign,
  onNewCampaign,
}: Props) {
  return (
    <div className="min-h-screen bg-gray-900 text-white flex flex-col">
      {/* Header */}
      <header className="p-8 text-center border-b border-gray-700">
        <h1 className="text-3xl font-bold">DM Assistant</h1>
        <p className="text-gray-400 mt-1">AI-Powered D&amp;D 5e</p>
      </header>

      {/* Content */}
      <main className="flex-1 max-w-5xl w-full mx-auto p-8">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-xl font-semibold">Your Campaigns</h2>
          <button
            onClick={onNewCampaign}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg text-sm font-medium transition-colors"
          >
            + New Campaign
          </button>
        </div>

        {isLoading ? (
          <div className="text-center text-gray-400 py-16">Loading campaigns...</div>
        ) : campaigns.length === 0 ? (
          <div className="text-center py-16 bg-gray-800 rounded-xl border border-gray-700">
            <p className="text-gray-400 mb-4">No campaigns yet. Create your first one to get started!</p>
            <button
              onClick={onNewCampaign}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg text-sm font-medium transition-colors"
            >
              + New Campaign
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {campaigns.map((campaign) => (
              <CampaignCard
                key={campaign.id}
                campaign={campaign}
                onClick={() => onSelectCampaign(campaign.id)}
              />
            ))}
          </div>
        )}
      </main>
    </div>
  );
}

interface CampaignCardProps {
  campaign: Campaign;
  onClick: () => void;
}

function CampaignCard({ campaign, onClick }: CampaignCardProps) {
  const statusColors: Record<string, string> = {
    active: 'bg-green-600/20 text-green-400',
    paused: 'bg-yellow-600/20 text-yellow-400',
    completed: 'bg-gray-600/20 text-gray-400',
  };
  const status = campaign.status || 'active';
  const statusClass = statusColors[status] || statusColors.active;

  return (
    <button
      onClick={onClick}
      className="text-left bg-gray-800 hover:bg-gray-750 border border-gray-700 hover:border-gray-600 rounded-xl p-5 transition-colors cursor-pointer"
    >
      <div className="flex items-start justify-between mb-2">
        <h3 className="font-semibold text-lg leading-tight">{campaign.name}</h3>
        <span className={`text-xs px-2 py-0.5 rounded-full whitespace-nowrap ml-2 ${statusClass}`}>
          {status}
        </span>
      </div>

      {(campaign.setting || campaign.theme) && (
        <p className="text-sm text-gray-400 mb-2">
          {campaign.setting}
          {campaign.setting && campaign.theme && ' · '}
          {campaign.theme}
        </p>
      )}

      {campaign.premise && (
        <p className="text-sm text-gray-500 mb-3 line-clamp-2">{campaign.premise}</p>
      )}

      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-500">
        {campaign.rule_system && <span>{campaign.rule_system}</span>}
        {campaign.level_range && <span>Levels {campaign.level_range}</span>}
        {campaign.player_count != null && (
          <span>{campaign.player_count} player{campaign.player_count !== 1 ? 's' : ''}</span>
        )}
      </div>
    </button>
  );
}
