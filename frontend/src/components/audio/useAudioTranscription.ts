import { useState, useCallback, useRef, useEffect } from 'react';
import { audioAPI } from '../../api/client';
import type { AudioJobStatus, SpeakerMappingEntry } from './types';

const POLL_INTERVAL = 2000;

type Phase = 'idle' | 'uploading' | 'polling' | 'mapping' | 'processing' | 'review' | 'completed' | 'error';

export interface AudioTranscriptionState {
  phase: Phase;
  jobId: string | null;
  jobStatus: AudioJobStatus | null;
  error: string | null;
  upload: (file: File, sessionNumber?: number) => Promise<void>;
  submitMappings: (mappings: SpeakerMappingEntry[], sessionNumber?: number, campaignId?: string) => Promise<void>;
  confirmEntities: () => Promise<void>;
  reset: () => void;
}

export function useAudioTranscription(): AudioTranscriptionState {
  const [phase, setPhase] = useState<Phase>('idle');
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<AudioJobStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const startPolling = useCallback((id: string) => {
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const status = await audioAPI.getStatus(id);
        setJobStatus(status);

        if (status.phase === 'awaiting_mapping') {
          stopPolling();
          setPhase('mapping');
        } else if (status.phase === 'awaiting_review') {
          stopPolling();
          setPhase('review');
        } else if (status.phase === 'completed') {
          stopPolling();
          setPhase('completed');
        } else if (status.phase === 'failed') {
          stopPolling();
          setError(status.error || 'Transcription failed');
          setPhase('error');
        }
      } catch (err) {
        stopPolling();
        setError(err instanceof Error ? err.message : 'Failed to poll status');
        setPhase('error');
      }
    }, POLL_INTERVAL);
  }, [stopPolling]);

  // Clean up polling on unmount
  useEffect(() => stopPolling, [stopPolling]);

  const upload = useCallback(async (file: File, sessionNumber?: number) => {
    setPhase('uploading');
    setError(null);
    setJobStatus(null);

    try {
      const result = await audioAPI.upload(file, sessionNumber);
      setJobId(result.job_id);
      setPhase('polling');
      startPolling(result.job_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed');
      setPhase('error');
    }
  }, [startPolling]);

  const submitMappings = useCallback(async (
    mappings: SpeakerMappingEntry[],
    sessionNumber?: number,
    campaignId?: string,
  ) => {
    if (!jobId) return;

    setPhase('processing');
    setError(null);

    try {
      await audioAPI.mapSpeakers(jobId, mappings, sessionNumber, campaignId);
      startPolling(jobId);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to submit mappings');
      setPhase('error');
    }
  }, [jobId, startPolling]);

  const confirmEntities = useCallback(async () => {
    if (!jobId) return;

    try {
      await audioAPI.confirmEntities(jobId);
      // Poll once more to get the completed status with transcript_result
      startPolling(jobId);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to confirm entities');
      setPhase('error');
    }
  }, [jobId, startPolling]);

  const reset = useCallback(() => {
    stopPolling();
    setPhase('idle');
    setJobId(null);
    setJobStatus(null);
    setError(null);
  }, [stopPolling]);

  return { phase, jobId, jobStatus, error, upload, submitMappings, confirmEntities, reset };
}
