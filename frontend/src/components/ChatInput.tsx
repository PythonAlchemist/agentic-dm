import { useState, useRef, useEffect, type KeyboardEvent } from 'react';

interface Props {
  onSend: (message: string) => void;
  disabled?: boolean;
  placeholder?: string;
}

export function ChatInput({ onSend, disabled, placeholder }: Props) {
  const [message, setMessage] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize textarea
  useEffect(() => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = 'auto';
      textarea.style.height = `${Math.min(textarea.scrollHeight, 200)}px`;
    }
  }, [message]);

  const handleSubmit = () => {
    if (message.trim() && !disabled) {
      onSend(message.trim());
      setMessage('');
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div className="flex items-end gap-2 p-4 bg-gray-800 border-t border-gray-700">
      <div className="flex-1 relative">
        <textarea
          ref={textareaRef}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder || "Ask the DM anything... (or use /roll, /npc, /encounter)"}
          disabled={disabled}
          rows={1}
          className="w-full px-4 py-3 bg-gray-700 border border-gray-600 rounded-lg resize-none focus:outline-none focus:border-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
        />
      </div>

      <button
        onClick={handleSubmit}
        disabled={!message.trim() || disabled}
        className="px-6 py-3 bg-blue-600 hover:bg-blue-700 rounded-lg font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {disabled ? (
          <span className="flex items-center gap-2">
            <LoadingSpinner />
            Thinking...
          </span>
        ) : (
          'Send'
        )}
      </button>
    </div>
  );
}

function LoadingSpinner() {
  return (
    <svg
      className="animate-spin h-5 w-5"
      xmlns="http://www.w3.org/2000/svg"
      fill="none"
      viewBox="0 0 24 24"
    >
      <circle
        className="opacity-25"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="4"
      />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
      />
    </svg>
  );
}
