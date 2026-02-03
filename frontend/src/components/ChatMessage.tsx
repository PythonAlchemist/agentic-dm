import type { ChatMessage as ChatMessageType } from '../types';

interface Props {
  message: ChatMessageType;
}

export function ChatMessage({ message }: Props) {
  const isUser = message.role === 'user';

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-4`}>
      <div className={`max-w-[80%] ${isUser ? 'order-2' : 'order-1'}`}>
        {/* Avatar */}
        <div className={`flex items-start gap-2 ${isUser ? 'flex-row-reverse' : ''}`}>
          <div
            className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold ${
              isUser ? 'bg-blue-600' : 'bg-purple-600'
            }`}
          >
            {isUser ? 'You' : 'DM'}
          </div>

          {/* Message content */}
          <div
            className={`px-4 py-2 ${
              isUser ? 'message-user' : 'message-assistant'
            }`}
          >
            <div className="markdown whitespace-pre-wrap">{message.content}</div>

            {/* Sources */}
            {message.sources && message.sources.length > 0 && (
              <div className="mt-2 pt-2 border-t border-gray-600 text-xs text-gray-400">
                <span className="font-semibold">Sources:</span>
                <ul className="mt-1">
                  {message.sources.map((source, i) => (
                    <li key={i}>
                      {source.source || source.type}
                      {source.page && ` (p.${source.page})`}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Tool results */}
            {message.toolResults && message.toolResults.length > 0 && (
              <div className="mt-2 pt-2 border-t border-gray-600">
                {message.toolResults.map((result, i) => (
                  <ToolResultDisplay key={i} result={result} />
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Suggestions */}
        {message.suggestions && message.suggestions.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-2 ml-10">
            {message.suggestions.map((suggestion, i) => (
              <button
                key={i}
                className="text-xs px-3 py-1 bg-gray-700 hover:bg-gray-600 rounded-full transition-colors"
              >
                {suggestion}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

interface ToolResultDisplayProps {
  result: { type: string; result: Record<string, unknown> };
}

function ToolResultDisplay({ result }: ToolResultDisplayProps) {
  if (result.type === 'dice') {
    const dice = result.result as {
      expression: string;
      rolls: number[];
      total: number;
      critical: boolean;
    };
    return (
      <div className="text-sm">
        <span className="text-gray-400">🎲 </span>
        <span className="font-mono">
          {dice.expression}: [{dice.rolls.join(', ')}] = {dice.total}
        </span>
        {dice.critical && (
          <span className="ml-2 text-yellow-400 font-bold">Critical!</span>
        )}
      </div>
    );
  }

  return null;
}
