import { useEffect, useRef } from 'react';
import { ChatMessage } from './ChatMessage';
import { ChatInput } from './ChatInput';
import type { ChatMessage as ChatMessageType } from '../types';

interface Props {
  messages: ChatMessageType[];
  onSendMessage: (message: string) => void;
  isLoading: boolean;
  mode: 'assistant' | 'autonomous';
  className?: string;
}

export function ChatPanel({ messages, onSendMessage, isLoading, mode, className }: Props) {
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  return (
    <div className={`flex flex-col bg-gray-800 ${className || 'flex-1'}`}>
      {/* Header */}
      <header className="px-4 py-3 bg-gray-800 border-b border-gray-700 flex items-center justify-between">
        <div>
          <h2 className="font-semibold">
            {mode === 'assistant' ? 'DM Assistant' : 'Autonomous DM'}
          </h2>
          <p className="text-sm text-gray-400">
            {mode === 'assistant'
              ? 'Ask about rules, generate NPCs, build encounters'
              : 'Let the AI run your game session'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span
            className={`px-2 py-1 rounded text-xs font-medium ${
              mode === 'assistant'
                ? 'bg-blue-600/20 text-blue-400'
                : 'bg-purple-600/20 text-purple-400'
            }`}
          >
            {mode === 'assistant' ? 'Assistant Mode' : 'DM Mode'}
          </span>
        </div>
      </header>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4">
        {messages.length === 0 ? (
          <EmptyState mode={mode} onSendMessage={onSendMessage} />
        ) : (
          <>
            {messages.map((message, index) => (
              <ChatMessage key={index} message={message} />
            ))}
            {isLoading && <ThinkingIndicator />}
            <div ref={messagesEndRef} />
          </>
        )}
      </div>

      {/* Input */}
      <ChatInput
        onSend={onSendMessage}
        disabled={isLoading}
        placeholder={
          mode === 'assistant'
            ? "Ask about rules, generate NPCs, build encounters..."
            : "Describe your action or speak to the DM..."
        }
      />
    </div>
  );
}

interface EmptyStateProps {
  mode: 'assistant' | 'autonomous';
  onSendMessage: (message: string) => void;
}

function EmptyState({ mode, onSendMessage }: EmptyStateProps) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center text-center px-8">
      <div className="text-6xl mb-4">🎲</div>
      <h3 className="text-xl font-semibold mb-2">
        {mode === 'assistant' ? 'Welcome, Dungeon Master!' : 'Ready to Play?'}
      </h3>
      <p className="text-gray-400 max-w-md mb-6">
        {mode === 'assistant'
          ? "I'm here to help you run your D&D game. Ask me about rules, generate NPCs, create encounters, or anything else you need."
          : "I'll be your Dungeon Master today. Tell me about your character and let's begin the adventure!"}
      </p>
      <div className="grid grid-cols-2 gap-4 max-w-lg">
        <SuggestionCard
          icon="📖"
          title="Rules Question"
          example="How does grappling work?"
          onClick={() => onSendMessage("How does grappling work?")}
        />
        <SuggestionCard
          icon="👤"
          title="Generate NPC"
          example="/npc innkeeper"
          onClick={() => onSendMessage("/npc innkeeper")}
        />
        <SuggestionCard
          icon="⚔️"
          title="Build Encounter"
          example="/encounter medium dungeon 3"
          onClick={() => onSendMessage("/encounter medium dungeon 3")}
        />
        <SuggestionCard
          icon="🎲"
          title="Roll Dice"
          example="/roll 2d6+3"
          onClick={() => onSendMessage("/roll 2d6+3")}
        />
      </div>
    </div>
  );
}

interface SuggestionCardProps {
  icon: string;
  title: string;
  example: string;
  onClick: () => void;
}

function SuggestionCard({ icon, title, example, onClick }: SuggestionCardProps) {
  return (
    <button
      onClick={onClick}
      className="p-4 bg-gray-700/50 rounded-lg text-left hover:bg-gray-700 transition-colors cursor-pointer w-full"
    >
      <div className="text-2xl mb-2">{icon}</div>
      <div className="font-medium text-sm">{title}</div>
      <div className="text-xs text-gray-400 font-mono mt-1">{example}</div>
    </button>
  );
}

function ThinkingIndicator() {
  return (
    <div className="flex justify-start mb-4">
      <div className="flex items-start gap-2">
        <div className="w-8 h-8 rounded-full bg-purple-600 flex items-center justify-center text-sm font-bold">
          DM
        </div>
        <div className="px-4 py-2 bg-gray-700 rounded-lg rounded-bl-none">
          <div className="flex items-center gap-1">
            <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
            <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
            <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
          </div>
        </div>
      </div>
    </div>
  );
}
