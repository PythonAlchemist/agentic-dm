import { useState, useCallback, useRef } from 'react';
import type { ShopProfile, ShopItem, ShopChatMessage } from './types';
import type { ShopGenerateRequest } from '../../types';
import { shopAPI } from '../../api/client';

export function useShopState() {
  const [activeShop, setActiveShop] = useState<ShopProfile | null>(null);
  const [shops, setShops] = useState<ShopProfile[]>([]);
  const [chatMessages, setChatMessages] = useState<ShopChatMessage[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadShops = useCallback(async () => {
    try {
      const result = await shopAPI.list();
      setShops(result);
    } catch {
      // Silently fail - shops may not exist yet
    }
  }, []);

  const generateShop = useCallback(async (request: ShopGenerateRequest) => {
    setIsGenerating(true);
    setError(null);

    try {
      const shop = await shopAPI.generate(request);
      setActiveShop(shop);
      setShops(prev => [shop, ...prev]);
      setChatMessages([]);
      return shop;
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to generate shop';
      setError(msg);
      return null;
    } finally {
      setIsGenerating(false);
    }
  }, []);

  const selectShop = useCallback(async (shopId: string) => {
    setIsLoading(true);
    setError(null);

    try {
      const shop = await shopAPI.get(shopId);
      setActiveShop(shop);
      setChatMessages([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load shop');
    } finally {
      setIsLoading(false);
    }
  }, []);

  const closeShop = useCallback(() => {
    setActiveShop(null);
    setChatMessages([]);
    setError(null);
  }, []);

  const addItem = useCallback(async (item: Omit<ShopItem, 'entity_id'>) => {
    if (!activeShop) return;

    setError(null);
    try {
      const created = await shopAPI.addItem(activeShop.entity_id, item);
      setActiveShop(prev => prev ? {
        ...prev,
        inventory: [...prev.inventory, created],
      } : null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add item');
    }
  }, [activeShop]);

  const updateItem = useCallback(async (itemId: string, updates: Partial<ShopItem>) => {
    if (!activeShop) return;

    setError(null);
    try {
      const updated = await shopAPI.updateItem(activeShop.entity_id, itemId, updates);
      setActiveShop(prev => prev ? {
        ...prev,
        inventory: prev.inventory.map(i =>
          i.entity_id === itemId ? { ...i, ...updated } : i
        ),
      } : null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update item');
    }
  }, [activeShop]);

  const removeItem = useCallback(async (itemId: string) => {
    if (!activeShop) return;

    // Optimistic update
    const prevInventory = activeShop.inventory;
    setActiveShop(prev => prev ? {
      ...prev,
      inventory: prev.inventory.filter(i => i.entity_id !== itemId),
    } : null);

    try {
      await shopAPI.removeItem(activeShop.entity_id, itemId);
    } catch (err) {
      // Rollback
      setActiveShop(prev => prev ? { ...prev, inventory: prevInventory } : null);
      setError(err instanceof Error ? err.message : 'Failed to remove item');
    }
  }, [activeShop]);

  const deleteShop = useCallback(async (shopId: string) => {
    setError(null);
    try {
      await shopAPI.delete(shopId);
      setShops(prev => prev.filter(s => s.entity_id !== shopId));
      if (activeShop?.entity_id === shopId) {
        setActiveShop(null);
        setChatMessages([]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete shop');
    }
  }, [activeShop]);

  // Use a ref to always have the latest chat messages without stale closures
  const chatMessagesRef = useRef(chatMessages);
  chatMessagesRef.current = chatMessages;

  const sendChatMessage = useCallback(async (message: string, playerName?: string) => {
    if (!activeShop) return;

    // Read from ref to always get the latest messages (avoids stale closure)
    const history = chatMessagesRef.current.map(msg => ({
      role: msg.role,
      content: msg.content,
    }));

    setChatMessages(prev => [...prev, { role: 'user', content: message }]);
    setIsLoading(true);

    try {
      const response = await shopAPI.chat(activeShop.entity_id, message, playerName, history);
      setChatMessages(prev => [...prev, {
        role: 'shopkeeper',
        content: response.response,
        transactions: response.transactions.length > 0 ? response.transactions : undefined,
      }]);

      // If transactions occurred, refresh the shop to get updated inventory/gold
      if (response.transactions.length > 0) {
        const updated = await shopAPI.get(activeShop.entity_id);
        setActiveShop(updated);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to chat with shopkeeper');
    } finally {
      setIsLoading(false);
    }
  }, [activeShop]);

  return {
    // State
    activeShop,
    shops,
    chatMessages,
    isLoading,
    isGenerating,
    error,

    // Actions
    loadShops,
    generateShop,
    selectShop,
    closeShop,
    addItem,
    updateItem,
    removeItem,
    deleteShop,
    sendChatMessage,
  };
}
