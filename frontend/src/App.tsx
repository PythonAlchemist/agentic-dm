import { useState } from 'react';
import { ChatPanel, Sidebar, KnowledgeGraph, EntityDetail } from './components';
import { useChat } from './hooks/useChat';
import type { Entity } from './types';

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
  } = useChat();

  const [showKnowledgeGraph, setShowKnowledgeGraph] = useState(false);
  const [selectedEntity, setSelectedEntity] = useState<Entity | null>(null);

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
      />
      <ChatPanel
        messages={messages}
        onSendMessage={sendMessage}
        isLoading={isLoading}
        mode={mode}
      />

      {/* Knowledge Graph */}
      {showKnowledgeGraph && (
        <KnowledgeGraph
          onClose={() => setShowKnowledgeGraph(false)}
          onSelectEntity={handleSelectEntity}
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
