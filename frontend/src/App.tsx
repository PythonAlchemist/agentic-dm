import { useState, useEffect } from 'react';
import { ChatPanel, Sidebar, KnowledgeGraph, EntityDetail, PlayerManager, CombatDashboard } from './components';
import { useChat } from './hooks/useChat';
import { playerAPI } from './api/client';
import type { Entity, Player } from './types';

function App() {
  const {
    messages,
    sessionId,
    mode,
    isLoading,
    sendMessage,
    changeMode,
    newSession,
    clearHistory,
    addMessage,
  } = useChat();

  const [showKnowledgeGraph, setShowKnowledgeGraph] = useState(false);
  const [showPlayerManager, setShowPlayerManager] = useState(false);
  const [showCombatTracker, setShowCombatTracker] = useState(false);
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

  return (
    <div className="h-screen flex bg-gray-900 text-white">
      <Sidebar
        mode={mode}
        onModeChange={changeMode}
        sessionId={sessionId}
        onNewSession={newSession}
        onClearHistory={clearHistory}
        onOpenCampaign={() => setShowKnowledgeGraph(true)}
        onOpenPlayers={() => setShowPlayerManager(true)}
        onOpenCombat={() => setShowCombatTracker(!showCombatTracker)}
        combatActive={showCombatTracker}
      />

      {/* Combat Dashboard (inline, takes ~60% when active) */}
      {showCombatTracker && (
        <CombatDashboard
          onClose={() => setShowCombatTracker(false)}
          players={players}
          onNPCTurn={addMessage}
        />
      )}

      {/* Chat Panel (full width normally, ~40% during combat) */}
      <ChatPanel
        messages={messages}
        onSendMessage={sendMessage}
        isLoading={isLoading}
        mode={mode}
        className={showCombatTracker ? 'flex-1 min-w-[320px]' : 'flex-1'}
      />

      {/* Knowledge Graph */}
      {showKnowledgeGraph && (
        <KnowledgeGraph
          onClose={() => setShowKnowledgeGraph(false)}
          onSelectEntity={handleSelectEntity}
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
  );
}

export default App;
