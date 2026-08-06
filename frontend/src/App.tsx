import { useState, useEffect, useCallback } from 'react';
import { ChatPanel, Sidebar, CampaignLanding, KnowledgeGraph, EntityDetail, PlayerManager, CombatDashboard, ShopDashboard, AudioTranscriber } from './components';
import { useChat } from './hooks/useChat';
import { useCampaign } from './hooks/useCampaign';
import { playerAPI } from './api/client';
import type { Entity, Player, CampaignCreate, CampaignUpdate, Campaign } from './types';

function App() {
  const {
    campaigns,
    activeCampaign,
    isLoading: campaignsLoading,
    selectCampaign,
    deselectCampaign,
    createCampaign,
    updateCampaign,
  } = useCampaign();

  const {
    messages,
    sessionId,
    isLoading,
    sendMessage,
    newSession,
    clearHistory,
    addMessage,
  } = useChat(activeCampaign?.id);

  const [showKnowledgeGraph, setShowKnowledgeGraph] = useState(false);
  const [showPlayerManager, setShowPlayerManager] = useState(false);
  const [showCombatTracker, setShowCombatTracker] = useState(false);
  const [showShop, setShowShop] = useState(false);
  const [showAudioTranscriber, setShowAudioTranscriber] = useState(false);
  const [showNewCampaignForm, setShowNewCampaignForm] = useState(false);
  const [showEditCampaignForm, setShowEditCampaignForm] = useState(false);
  const [selectedEntity, setSelectedEntity] = useState<Entity | null>(null);
  const [players, setPlayers] = useState<Player[]>([]);

  // Load players for combat tracker
  useEffect(() => {
    const loadPlayers = async () => {
      try {
        const data = await playerAPI.list();
        setPlayers(data);
      } catch {
        // Silently fail - players are optional
      }
    };
    loadPlayers();
  }, [showCombatTracker]);

  const handleSelectEntity = (entity: Entity) => {
    setSelectedEntity(entity);
  };

  const handleNavigateEntity = (entity: Entity) => {
    setSelectedEntity(entity);
  };

  const handleCreateCampaign = useCallback(
    async (data: CampaignCreate) => {
      await createCampaign(data);
      setShowNewCampaignForm(false);
    },
    [createCampaign]
  );

  const handleUpdateCampaign = useCallback(
    async (id: string, data: CampaignUpdate) => {
      await updateCampaign(id, data);
      setShowEditCampaignForm(false);
    },
    [updateCampaign]
  );

  const handleDeselectCampaign = useCallback(() => {
    deselectCampaign();
    setShowCombatTracker(false);
    setShowShop(false);
    setShowAudioTranscriber(false);
    setShowKnowledgeGraph(false);
    setShowPlayerManager(false);
    setSelectedEntity(null);
  }, [deselectCampaign]);

  return (
    <>
      {activeCampaign ? (
        <div className="h-screen flex bg-gray-900 text-white">
          <Sidebar
            activeCampaign={activeCampaign}
            onDeselectCampaign={handleDeselectCampaign}
            onEditCampaign={() => setShowEditCampaignForm(true)}
            sessionId={sessionId}
            onNewSession={newSession}
            onClearHistory={clearHistory}
            onOpenCampaign={() => setShowKnowledgeGraph(true)}
            onOpenPlayers={() => setShowPlayerManager(true)}
            onOpenCombat={() => setShowCombatTracker(!showCombatTracker)}
            onOpenShop={() => setShowShop(!showShop)}
            onOpenAudio={() => setShowAudioTranscriber(!showAudioTranscriber)}
            combatActive={showCombatTracker}
            shopActive={showShop}
            audioActive={showAudioTranscriber}
          />

          {/* Combat Dashboard (inline, takes ~60% when active) */}
          {showCombatTracker && (
            <CombatDashboard
              onClose={() => setShowCombatTracker(false)}
              players={players}
              onNPCTurn={addMessage}
            />
          )}

          {/* Shop Dashboard (inline, takes ~60% when active) */}
          {showShop && (
            <ShopDashboard
              onClose={() => setShowShop(false)}
            />
          )}

          {/* Audio Transcriber (inline, takes ~60% when active) */}
          {showAudioTranscriber && (
            <AudioTranscriber
              onClose={() => setShowAudioTranscriber(false)}
            />
          )}

          {/* Chat Panel (full width normally, ~40% during combat) */}
          <ChatPanel
            messages={messages}
            onSendMessage={sendMessage}
            isLoading={isLoading}
            activeCampaign={activeCampaign}
            className={(showCombatTracker || showShop || showAudioTranscriber) ? 'flex-1 min-w-[320px]' : 'flex-1'}
          />

          {/* Knowledge Graph */}
          {showKnowledgeGraph && (
            <KnowledgeGraph
              onClose={() => setShowKnowledgeGraph(false)}
              onSelectEntity={handleSelectEntity}
              campaignId={activeCampaign.id}
            />
          )}

          {/* Player Manager */}
          {showPlayerManager && (
            <PlayerManager
              onClose={() => setShowPlayerManager(false)}
            />
          )}

          {/* Entity Detail Modal */}
          {selectedEntity && (
            <EntityDetail
              entity={selectedEntity}
              onClose={() => setSelectedEntity(null)}
              onNavigate={handleNavigateEntity}
            />
          )}
        </div>
      ) : (
        <CampaignLanding
          campaigns={campaigns}
          isLoading={campaignsLoading}
          onSelectCampaign={selectCampaign}
          onNewCampaign={() => setShowNewCampaignForm(true)}
        />
      )}

      {/* New Campaign Modal — outside conditional so it works from landing page */}
      {showNewCampaignForm && (
        <NewCampaignModal
          onClose={() => setShowNewCampaignForm(false)}
          onCreate={handleCreateCampaign}
        />
      )}

      {/* Edit Campaign Modal */}
      {showEditCampaignForm && activeCampaign && (
        <EditCampaignModal
          campaign={activeCampaign}
          onClose={() => setShowEditCampaignForm(false)}
          onSave={handleUpdateCampaign}
        />
      )}
    </>
  );
}

interface NewCampaignModalProps {
  onClose: () => void;
  onCreate: (data: CampaignCreate) => void;
}

function NewCampaignModal({ onClose, onCreate }: NewCampaignModalProps) {
  const [name, setName] = useState('');
  const [setting, setSetting] = useState('');
  const [theme, setTheme] = useState('');
  const [ruleSystem, setRuleSystem] = useState('D&D 5e');
  const [premise, setPremise] = useState('');
  const [levelRange, setLevelRange] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;

    onCreate({
      name: name.trim(),
      setting: setting.trim() || undefined,
      theme: theme.trim() || undefined,
      rule_system: ruleSystem.trim() || 'D&D 5e',
      premise: premise.trim() || undefined,
      level_range: levelRange.trim() || undefined,
    });
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-gray-800 rounded-xl p-6 w-full max-w-lg border border-gray-700">
        <h2 className="text-xl font-bold mb-4">New Campaign</h2>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm text-gray-400 mb-1">Campaign Name *</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-sm focus:outline-none focus:border-blue-500"
              placeholder="e.g., Curse of Strahd"
              autoFocus
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm text-gray-400 mb-1">Setting</label>
              <input
                type="text"
                value={setting}
                onChange={(e) => setSetting(e.target.value)}
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-sm focus:outline-none focus:border-blue-500"
                placeholder="e.g., Forgotten Realms"
              />
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1">Theme</label>
              <input
                type="text"
                value={theme}
                onChange={(e) => setTheme(e.target.value)}
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-sm focus:outline-none focus:border-blue-500"
                placeholder="e.g., dark fantasy"
              />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm text-gray-400 mb-1">Rule System</label>
              <input
                type="text"
                value={ruleSystem}
                onChange={(e) => setRuleSystem(e.target.value)}
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-sm focus:outline-none focus:border-blue-500"
              />
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1">Level Range</label>
              <input
                type="text"
                value={levelRange}
                onChange={(e) => setLevelRange(e.target.value)}
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-sm focus:outline-none focus:border-blue-500"
                placeholder="e.g., 1-10"
              />
            </div>
          </div>
          <div>
            <label className="block text-sm text-gray-400 mb-1">Premise</label>
            <textarea
              value={premise}
              onChange={(e) => setPremise(e.target.value)}
              rows={3}
              className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-sm focus:outline-none focus:border-blue-500 resize-none"
              placeholder="What's the campaign about?"
            />
          </div>
          <div className="flex gap-3 justify-end">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!name.trim()}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Create Campaign
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

interface EditCampaignModalProps {
  campaign: Campaign;
  onClose: () => void;
  onSave: (id: string, data: CampaignUpdate) => void;
}

function EditCampaignModal({ campaign, onClose, onSave }: EditCampaignModalProps) {
  const [name, setName] = useState(campaign.name || '');
  const [setting, setSetting] = useState(campaign.setting || '');
  const [worldDescription, setWorldDescription] = useState(campaign.world_description || '');
  const [theme, setTheme] = useState(campaign.theme || '');
  const [ruleSystem, setRuleSystem] = useState(campaign.rule_system || 'D&D 5e');
  const [levelRange, setLevelRange] = useState(campaign.level_range || '');
  const [houseRules, setHouseRules] = useState(campaign.house_rules || '');
  const [allowedSources, setAllowedSources] = useState(campaign.allowed_sources || '');
  const [premise, setPremise] = useState(campaign.premise || '');
  const [currentStoryArc, setCurrentStoryArc] = useState(campaign.current_story_arc || '');
  const [dmNotes, setDmNotes] = useState(campaign.dm_notes || '');
  const [status, setStatus] = useState(campaign.status || 'active');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;

    const data: CampaignUpdate = {};
    if (name.trim() !== (campaign.name || '')) data.name = name.trim();
    if (setting.trim() !== (campaign.setting || '')) data.setting = setting.trim() || undefined;
    if (worldDescription.trim() !== (campaign.world_description || '')) data.world_description = worldDescription.trim() || undefined;
    if (theme.trim() !== (campaign.theme || '')) data.theme = theme.trim() || undefined;
    if (ruleSystem.trim() !== (campaign.rule_system || '')) data.rule_system = ruleSystem.trim() || undefined;
    if (levelRange.trim() !== (campaign.level_range || '')) data.level_range = levelRange.trim() || undefined;
    if (houseRules.trim() !== (campaign.house_rules || '')) data.house_rules = houseRules.trim() || undefined;
    if (allowedSources.trim() !== (campaign.allowed_sources || '')) data.allowed_sources = allowedSources.trim() || undefined;
    if (premise.trim() !== (campaign.premise || '')) data.premise = premise.trim() || undefined;
    if (currentStoryArc.trim() !== (campaign.current_story_arc || '')) data.current_story_arc = currentStoryArc.trim() || undefined;
    if (dmNotes.trim() !== (campaign.dm_notes || '')) data.dm_notes = dmNotes.trim() || undefined;
    if (status !== (campaign.status || 'active')) data.status = status;

    onSave(campaign.id, data);
  };

  const inputClass = "w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-sm focus:outline-none focus:border-blue-500";
  const labelClass = "block text-sm text-gray-400 mb-1";

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-gray-800 rounded-xl p-6 w-full max-w-2xl border border-gray-700 max-h-[90vh] overflow-y-auto">
        <h2 className="text-xl font-bold mb-4">Edit Campaign</h2>
        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Name & Status */}
          <div className="grid grid-cols-3 gap-4">
            <div className="col-span-2">
              <label className={labelClass}>Campaign Name *</label>
              <input type="text" value={name} onChange={(e) => setName(e.target.value)} className={inputClass} />
            </div>
            <div>
              <label className={labelClass}>Status</label>
              <select value={status} onChange={(e) => setStatus(e.target.value)} className={inputClass}>
                <option value="active">Active</option>
                <option value="paused">Paused</option>
                <option value="completed">Completed</option>
              </select>
            </div>
          </div>

          {/* Setting & Theme */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className={labelClass}>Setting</label>
              <input type="text" value={setting} onChange={(e) => setSetting(e.target.value)} className={inputClass} placeholder="e.g., Forgotten Realms" />
            </div>
            <div>
              <label className={labelClass}>Theme</label>
              <input type="text" value={theme} onChange={(e) => setTheme(e.target.value)} className={inputClass} placeholder="e.g., dark fantasy, political intrigue" />
            </div>
          </div>

          {/* Rule System, Level Range, Sources */}
          <div className="grid grid-cols-3 gap-4">
            <div>
              <label className={labelClass}>Rule System</label>
              <input type="text" value={ruleSystem} onChange={(e) => setRuleSystem(e.target.value)} className={inputClass} />
            </div>
            <div>
              <label className={labelClass}>Level Range</label>
              <input type="text" value={levelRange} onChange={(e) => setLevelRange(e.target.value)} className={inputClass} placeholder="e.g., 1-10" />
            </div>
            <div>
              <label className={labelClass}>Allowed Sources</label>
              <input type="text" value={allowedSources} onChange={(e) => setAllowedSources(e.target.value)} className={inputClass} placeholder="e.g., PHB, XGtE, TCoE" />
            </div>
          </div>

          {/* World Description */}
          <div>
            <label className={labelClass}>World Description</label>
            <textarea value={worldDescription} onChange={(e) => setWorldDescription(e.target.value)} rows={3} className={`${inputClass} resize-none`} placeholder="Describe the broader world and setting..." />
          </div>

          {/* Premise */}
          <div>
            <label className={labelClass}>Premise</label>
            <textarea value={premise} onChange={(e) => setPremise(e.target.value)} rows={3} className={`${inputClass} resize-none`} placeholder="What's the campaign about?" />
          </div>

          {/* Current Story Arc */}
          <div>
            <label className={labelClass}>Current Story Arc</label>
            <textarea value={currentStoryArc} onChange={(e) => setCurrentStoryArc(e.target.value)} rows={3} className={`${inputClass} resize-none`} placeholder="Where is the party in the narrative right now?" />
          </div>

          {/* House Rules */}
          <div>
            <label className={labelClass}>House Rules</label>
            <textarea value={houseRules} onChange={(e) => setHouseRules(e.target.value)} rows={2} className={`${inputClass} resize-none`} placeholder="Any custom rules or modifications..." />
          </div>

          {/* DM Notes */}
          <div>
            <label className={labelClass}>DM Notes (private)</label>
            <textarea value={dmNotes} onChange={(e) => setDmNotes(e.target.value)} rows={3} className={`${inputClass} resize-none`} placeholder="Private notes, upcoming reveals, secret plot points..." />
          </div>

          {/* Buttons */}
          <div className="flex gap-3 justify-end pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm transition-colors">
              Cancel
            </button>
            <button type="submit" disabled={!name.trim()} className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed">
              Save Changes
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default App;
