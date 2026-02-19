import { useState, useEffect, useMemo } from 'react';
import type { SpeakerSample, SpeakerMappingEntry } from './types';

interface Props {
  speakerSamples: SpeakerSample[];
  existingPlayers: string[];
  onSubmit: (mappings: SpeakerMappingEntry[], sessionNumber?: number, campaignId?: string) => void;
  isProcessing: boolean;
}

interface MappingRow {
  speaker_index: number;
  role: 'dm' | 'player';
  player_name: string;
  character_name: string;
}

export function SpeakerMapper({ speakerSamples, existingPlayers, onSubmit, isProcessing }: Props) {
  const [mappings, setMappings] = useState<MappingRow[]>([]);
  const [sessionNumber, setSessionNumber] = useState<string>('');
  const [campaignId, setCampaignId] = useState<string>('');

  // Auto-suggest DM for highest-utterance speaker
  const suggestedDmIndex = useMemo(() => {
    if (speakerSamples.length === 0) return -1;
    return speakerSamples.reduce((maxIdx, s, i, arr) =>
      s.utterance_count > arr[maxIdx].utterance_count ? i : maxIdx
    , 0);
  }, [speakerSamples]);

  // Initialize mappings from speaker samples
  useEffect(() => {
    setMappings(
      speakerSamples.map((s, i) => ({
        speaker_index: s.speaker_index,
        role: i === suggestedDmIndex ? 'dm' : 'player',
        player_name: i === suggestedDmIndex ? 'DM' : '',
        character_name: '',
      }))
    );
  }, [speakerSamples, suggestedDmIndex]);

  const updateMapping = (index: number, field: keyof MappingRow, value: string) => {
    setMappings(prev => {
      const updated = [...prev];
      updated[index] = { ...updated[index], [field]: value };
      // If switching to DM, set name to DM and clear character
      if (field === 'role' && value === 'dm') {
        updated[index].player_name = 'DM';
        updated[index].character_name = '';
      } else if (field === 'role' && value === 'player') {
        updated[index].player_name = '';
      }
      return updated;
    });
  };

  const canSubmit = mappings.every(m => m.player_name.trim() !== '');

  const handleSubmit = () => {
    const entries: SpeakerMappingEntry[] = mappings.map(m => ({
      speaker_index: m.speaker_index,
      role: m.role,
      player_name: m.player_name.trim(),
      character_name: m.character_name.trim() || undefined,
    }));
    const num = sessionNumber ? parseInt(sessionNumber, 10) : undefined;
    onSubmit(entries, num, campaignId || undefined);
  };

  const formatDuration = (seconds: number): string => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.round(seconds % 60);
    return mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
  };

  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-400">
        {speakerSamples.length} speakers detected. Map each to a player or DM.
      </p>

      {mappings.map((mapping, i) => {
        const sample = speakerSamples.find(s => s.speaker_index === mapping.speaker_index);
        return (
          <div
            key={mapping.speaker_index}
            className="bg-gray-700/50 border border-gray-600 rounded-lg p-4 space-y-3"
          >
            {/* Speaker header */}
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-white">
                Speaker {mapping.speaker_index}
              </span>
              {sample && (
                <span className="text-xs text-gray-400">
                  {sample.utterance_count} utterances · {formatDuration(sample.total_duration)}
                </span>
              )}
            </div>

            {/* Sample utterances */}
            {sample && sample.sample_texts.length > 0 && (
              <div className="space-y-1">
                {sample.sample_texts.slice(0, 3).map((text, j) => (
                  <p key={j} className="text-xs text-gray-400 italic truncate">
                    "{text}"
                  </p>
                ))}
              </div>
            )}

            {/* Role selector */}
            <div className="grid grid-cols-3 gap-2">
              <div>
                <label className="text-xs text-gray-500 block mb-1">Role</label>
                <select
                  value={mapping.role}
                  onChange={(e) => updateMapping(i, 'role', e.target.value)}
                  className="w-full px-2 py-1.5 bg-gray-700 border border-gray-600 rounded text-sm text-white focus:outline-none focus:border-blue-500"
                >
                  <option value="player">Player</option>
                  <option value="dm">DM</option>
                </select>
              </div>

              <div>
                <label className="text-xs text-gray-500 block mb-1">Player Name</label>
                <input
                  type="text"
                  value={mapping.player_name}
                  onChange={(e) => updateMapping(i, 'player_name', e.target.value)}
                  placeholder="e.g. Alex"
                  list={`players-${mapping.speaker_index}`}
                  disabled={mapping.role === 'dm'}
                  className="w-full px-2 py-1.5 bg-gray-700 border border-gray-600 rounded text-sm text-white focus:outline-none focus:border-blue-500 disabled:opacity-50"
                />
                {existingPlayers.length > 0 && (
                  <datalist id={`players-${mapping.speaker_index}`}>
                    {existingPlayers.map(p => (
                      <option key={p} value={p} />
                    ))}
                  </datalist>
                )}
              </div>

              <div>
                <label className="text-xs text-gray-500 block mb-1">Character Name</label>
                <input
                  type="text"
                  value={mapping.character_name}
                  onChange={(e) => updateMapping(i, 'character_name', e.target.value)}
                  placeholder="e.g. Thorin"
                  disabled={mapping.role === 'dm'}
                  className="w-full px-2 py-1.5 bg-gray-700 border border-gray-600 rounded text-sm text-white focus:outline-none focus:border-blue-500 disabled:opacity-50"
                />
              </div>
            </div>
          </div>
        );
      })}

      {/* Session metadata */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs text-gray-500 block mb-1">Session Number</label>
          <input
            type="number"
            min="1"
            value={sessionNumber}
            onChange={(e) => setSessionNumber(e.target.value)}
            placeholder="e.g. 12"
            className="w-full px-2 py-1.5 bg-gray-700 border border-gray-600 rounded text-sm text-white focus:outline-none focus:border-blue-500"
          />
        </div>
        <div>
          <label className="text-xs text-gray-500 block mb-1">Campaign ID (optional)</label>
          <input
            type="text"
            value={campaignId}
            onChange={(e) => setCampaignId(e.target.value)}
            placeholder="e.g. campaign_abc"
            className="w-full px-2 py-1.5 bg-gray-700 border border-gray-600 rounded text-sm text-white focus:outline-none focus:border-blue-500"
          />
        </div>
      </div>

      {/* Submit */}
      <button
        onClick={handleSubmit}
        disabled={!canSubmit || isProcessing}
        className="w-full py-3 px-4 bg-purple-600 hover:bg-purple-500 disabled:bg-gray-700 disabled:text-gray-500 rounded-lg font-medium transition-colors"
      >
        {isProcessing ? 'Processing...' : 'Map Speakers & Process Transcript'}
      </button>
    </div>
  );
}
