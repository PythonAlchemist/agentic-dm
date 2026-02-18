import { useState } from 'react';
import type { ShopProfile, ShopChatMessage } from './types';

interface ShopkeeperCardProps {
  shop: ShopProfile;
  chatMessages: ShopChatMessage[];
  isLoading: boolean;
  onSendMessage: (message: string, playerName?: string) => void;
}

export function ShopkeeperCard({ shop, chatMessages, isLoading, onSendMessage }: ShopkeeperCardProps) {
  const [message, setMessage] = useState('');
  const [playerName, setPlayerName] = useState('');

  const handleSend = () => {
    if (!message.trim()) return;
    onSendMessage(message.trim(), playerName || undefined);
    setMessage('');
  };

  const personality = shop.shopkeeper_personality as Record<string, unknown> | undefined;
  const traits = (personality?.personality_traits as string[]) || [];
  const speechStyle = (personality?.speech_style as string) || 'casual';
  const catchphrases = (personality?.catchphrases as string[]) || [];
  const knowledgeDomains = (personality?.knowledge_domains as string[]) || [];

  return (
    <div className="space-y-4">
      {/* Shopkeeper Info */}
      <div className="bg-gray-700/50 rounded-lg p-4">
        <div className="flex items-start gap-3">
          <div className="w-10 h-10 rounded-full bg-amber-600/30 flex items-center justify-center text-lg flex-shrink-0">
            {shop.shop_specialty === 'potions' ? '\u2697\uFE0F' :
             shop.shop_specialty === 'weapons' ? '\u2694\uFE0F' :
             shop.shop_specialty === 'armor' ? '\uD83D\uDEE1\uFE0F' :
             shop.shop_specialty === 'magic_items' ? '\u2728' :
             shop.shop_specialty === 'scrolls' ? '\uD83D\uDCDC' :
             '\uD83C\uDFEA'}
          </div>
          <div className="flex-1 min-w-0">
            <h4 className="font-medium">{shop.shopkeeper_name || 'Shopkeeper'}</h4>
            <div className="text-xs text-gray-400">
              {shop.shopkeeper_race && <span className="capitalize">{shop.shopkeeper_race}</span>}
              {shop.shopkeeper_race && ' | '}
              <span className="capitalize">{speechStyle} speech</span>
            </div>
            {shop.shopkeeper_description && (
              <p className="text-sm text-gray-300 mt-2">{shop.shopkeeper_description}</p>
            )}
          </div>
        </div>

        {/* Personality Details */}
        <div className="mt-3 flex flex-wrap gap-2">
          {traits.map((trait, i) => (
            <span key={i} className="px-2 py-0.5 bg-gray-600 rounded text-xs text-gray-300">
              {trait}
            </span>
          ))}
        </div>

        {knowledgeDomains.length > 0 && (
          <div className="mt-2 text-xs text-gray-400">
            <span className="font-medium">Knows about:</span>{' '}
            {knowledgeDomains.join(', ')}
          </div>
        )}

        {catchphrases.length > 0 && (
          <div className="mt-2 text-xs text-gray-500 italic">
            "{catchphrases[0]}"
          </div>
        )}
      </div>

      {/* Chat Area */}
      <div className="bg-gray-800 rounded-lg border border-gray-700">
        <div className="px-3 py-2 border-b border-gray-700 flex items-center justify-between">
          <span className="text-sm font-medium">Chat with {shop.shopkeeper_name || 'Shopkeeper'}</span>
          <input
            type="text"
            value={playerName}
            onChange={e => setPlayerName(e.target.value)}
            placeholder="Player name"
            className="w-32 px-2 py-1 bg-gray-700 rounded text-xs border border-gray-600 focus:border-amber-500 focus:outline-none"
          />
        </div>

        {/* Messages */}
        <div className="h-48 overflow-y-auto p-3 space-y-2">
          {chatMessages.length === 0 && (
            <div className="text-center text-gray-500 text-xs py-4">
              Start a conversation with the shopkeeper
            </div>
          )}
          {chatMessages.map((msg, i) => (
            <div
              key={i}
              className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
            >
              <div
                className={`max-w-[80%] px-3 py-2 rounded-lg text-sm ${
                  msg.role === 'user'
                    ? 'bg-blue-600/30 text-blue-100'
                    : 'bg-amber-600/20 text-amber-100'
                }`}
              >
                {msg.role === 'shopkeeper' && (
                  <div className="text-xs text-amber-400 font-medium mb-1">
                    {shop.shopkeeper_name || 'Shopkeeper'}
                  </div>
                )}
                <div>{msg.content}</div>
                {msg.transactions && msg.transactions.length > 0 && (
                  <div className="mt-1 space-y-1">
                    {msg.transactions.map((tx, j) => (
                      <div key={j} className="px-2 py-1 bg-green-700/30 border border-green-600/40 rounded text-xs text-green-300">
                        Sold: {tx.qty}x {tx.item} @ {tx.price_each} gp = {tx.total} gp
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}
          {isLoading && (
            <div className="flex justify-start">
              <div className="px-3 py-2 bg-amber-600/20 rounded-lg text-sm text-amber-400 animate-pulse">
                {shop.shopkeeper_name || 'Shopkeeper'} is thinking...
              </div>
            </div>
          )}
        </div>

        {/* Input */}
        <div className="p-2 border-t border-gray-700 flex gap-2">
          <input
            type="text"
            value={message}
            onChange={e => setMessage(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleSend()}
            placeholder="Say something to the shopkeeper..."
            className="flex-1 px-3 py-2 bg-gray-700 rounded-lg text-sm border border-gray-600 focus:border-amber-500 focus:outline-none"
            disabled={isLoading}
          />
          <button
            onClick={handleSend}
            disabled={isLoading || !message.trim()}
            className="px-4 py-2 bg-amber-600 hover:bg-amber-700 rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
}
