import { useState, useCallback } from 'react';
import { chatAPI } from '../api/client';
import type { ChatMessage, DMMode } from '../types';

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [mode, setMode] = useState<DMMode>('assistant');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const sendMessage = useCallback(
    async (content: string) => {
      if (!content.trim()) return;

      // Add user message immediately
      const userMessage: ChatMessage = {
        role: 'user',
        content,
        timestamp: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, userMessage]);
      setIsLoading(true);
      setError(null);

      try {
        const response = await chatAPI.send({
          message: content,
          session_id: sessionId || undefined,
          mode,
          use_rag: true,
        });

        // Update session ID if new
        if (!sessionId && response.session_id) {
          setSessionId(response.session_id);
        }

        // Add assistant response
        const assistantMessage: ChatMessage = {
          role: 'assistant',
          content: response.response,
          timestamp: new Date().toISOString(),
          sources: response.sources,
          toolResults: response.tool_results,
          suggestions: response.suggestions,
        };
        setMessages((prev) => [...prev, assistantMessage]);
      } catch (err) {
        const errorMessage =
          err instanceof Error ? err.message : 'Failed to send message';
        setError(errorMessage);

        // Add error message to chat
        const errorChatMessage: ChatMessage = {
          role: 'assistant',
          content: `⚠️ Error: ${errorMessage}`,
          timestamp: new Date().toISOString(),
        };
        setMessages((prev) => [...prev, errorChatMessage]);
      } finally {
        setIsLoading(false);
      }
    },
    [sessionId, mode]
  );

  const changeMode = useCallback(
    async (newMode: DMMode) => {
      setMode(newMode);

      // If we have an active session, update it on the server
      if (sessionId) {
        try {
          await chatAPI.changeMode(sessionId, newMode);
        } catch (err) {
          console.error('Failed to change mode on server:', err);
        }
      }
    },
    [sessionId]
  );

  const newSession = useCallback(() => {
    setSessionId(null);
    setMessages([]);
    setError(null);
  }, []);

  const clearHistory = useCallback(async () => {
    if (sessionId) {
      try {
        await chatAPI.clearHistory(sessionId);
      } catch (err) {
        console.error('Failed to clear history on server:', err);
      }
    }
    setMessages([]);
    setError(null);
  }, [sessionId]);

  return {
    messages,
    sessionId,
    mode,
    isLoading,
    error,
    sendMessage,
    changeMode,
    newSession,
    clearHistory,
  };
}
