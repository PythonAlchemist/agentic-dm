import { useState, useEffect, useCallback } from 'react';
import { campaignManagementAPI } from '../api/client';
import type { Campaign, CampaignCreate, CampaignUpdate } from '../types';

const STORAGE_KEY = 'agentic-dm-active-campaign';

export function useCampaign() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [activeCampaign, setActiveCampaign] = useState<Campaign | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadCampaigns = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await campaignManagementAPI.list();
      setCampaigns(data);
      return data;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load campaigns');
      return [];
    } finally {
      setIsLoading(false);
    }
  }, []);

  const selectCampaign = useCallback(
    (id: string) => {
      const campaign = campaigns.find((c) => c.id === id) || null;
      setActiveCampaign(campaign);
      if (campaign) {
        localStorage.setItem(STORAGE_KEY, id);
      } else {
        localStorage.removeItem(STORAGE_KEY);
      }
    },
    [campaigns]
  );

  const createCampaign = useCallback(
    async (data: CampaignCreate) => {
      try {
        const created = await campaignManagementAPI.create(data);
        setCampaigns((prev) => [...prev, created]);
        setActiveCampaign(created);
        localStorage.setItem(STORAGE_KEY, created.id);
        return created;
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to create campaign');
        return null;
      }
    },
    []
  );

  const updateCampaign = useCallback(
    async (id: string, data: CampaignUpdate) => {
      try {
        const updated = await campaignManagementAPI.update(id, data);
        setCampaigns((prev) => prev.map((c) => (c.id === id ? updated : c)));
        if (activeCampaign?.id === id) {
          setActiveCampaign(updated);
        }
        return updated;
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to update campaign');
        return null;
      }
    },
    [activeCampaign?.id]
  );

  const deselectCampaign = useCallback(() => {
    setActiveCampaign(null);
    localStorage.removeItem(STORAGE_KEY);
  }, []);

  // Load campaigns on mount and restore from localStorage (no auto-select)
  useEffect(() => {
    const init = async () => {
      const data = await loadCampaigns();
      if (data.length === 0) return;

      const savedId = localStorage.getItem(STORAGE_KEY);
      const saved = savedId ? data.find((c: Campaign) => c.id === savedId) : null;
      if (saved) {
        setActiveCampaign(saved);
      }
    };
    init();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return {
    campaigns,
    activeCampaign,
    isLoading,
    error,
    loadCampaigns,
    selectCampaign,
    deselectCampaign,
    createCampaign,
    updateCampaign,
  };
}
