import { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import type { DiarizedSegment, SpeakerSample, SpeakerMappingEntry } from './types';

// Speaker color palette
const SPEAKER_COLORS = [
  { bg: 'bg-blue-600/30', text: 'text-blue-300', border: 'border-blue-500/50' },
  { bg: 'bg-green-600/30', text: 'text-green-300', border: 'border-green-500/50' },
  { bg: 'bg-yellow-600/30', text: 'text-yellow-300', border: 'border-yellow-500/50' },
  { bg: 'bg-pink-600/30', text: 'text-pink-300', border: 'border-pink-500/50' },
  { bg: 'bg-cyan-600/30', text: 'text-cyan-300', border: 'border-cyan-500/50' },
  { bg: 'bg-orange-600/30', text: 'text-orange-300', border: 'border-orange-500/50' },
  { bg: 'bg-purple-600/30', text: 'text-purple-300', border: 'border-purple-500/50' },
  { bg: 'bg-red-600/30', text: 'text-red-300', border: 'border-red-500/50' },
];

function getSpeakerColor(speakerIndex: number) {
  return SPEAKER_COLORS[speakerIndex % SPEAKER_COLORS.length];
}

function formatTimestamp(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

// --- Sub-component: MappingProgress ---

interface MappingProgressProps {
  speakerIndices: number[];
  mappings: Map<number, MappingRow>;
}

function MappingProgress({ speakerIndices, mappings }: MappingProgressProps) {
  const mapped = speakerIndices.filter(i => mappings.has(i) && mappings.get(i)!.player_name.trim() !== '').length;
  return (
    <div className="flex items-center gap-2 text-xs text-gray-400">
      <span>{mapped}/{speakerIndices.length} speakers mapped</span>
      <div className="flex gap-1">
        {speakerIndices.map(i => {
          const isMapped = mappings.has(i) && mappings.get(i)!.player_name.trim() !== '';
          const color = isMapped ? getSpeakerColor(i) : null;
          return (
            <div
              key={i}
              className={`w-2 h-2 rounded-full ${
                isMapped ? `${color!.bg}` : 'bg-gray-600'
              }`}
            />
          );
        })}
      </div>
    </div>
  );
}

// --- Sub-component: SpeakerPopover ---

interface SpeakerPopoverProps {
  speakerIndex: number;
  sample?: SpeakerSample;
  existingPlayers: string[];
  mapping: MappingRow;
  onSave: (mapping: MappingRow) => void;
  onClose: () => void;
}

function SpeakerPopover({ speakerIndex, sample, existingPlayers, mapping, onSave, onClose }: SpeakerPopoverProps) {
  const [role, setRole] = useState<'dm' | 'player'>(mapping.role);
  const [playerName, setPlayerName] = useState(mapping.player_name);
  const [characterName, setCharacterName] = useState(mapping.character_name);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [onClose]);

  // Auto-set player_name to DM when switching role
  useEffect(() => {
    if (role === 'dm') {
      setPlayerName('DM');
      setCharacterName('');
    } else if (playerName === 'DM') {
      setPlayerName('');
    }
  }, [role]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleSave = () => {
    onSave({
      speaker_index: speakerIndex,
      role,
      player_name: playerName.trim(),
      character_name: characterName.trim(),
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={onClose}>
      <div className="absolute inset-0 bg-black/50" />
      <div
        ref={panelRef}
        className="relative z-10 bg-gray-800 border border-gray-600 rounded-lg p-4 w-80 shadow-xl space-y-3"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h4 className="text-sm font-medium text-white">Speaker {speakerIndex}</h4>
          <button onClick={onClose} className="text-gray-400 hover:text-white text-sm">✕</button>
        </div>

        {/* Sample utterances */}
        {sample && sample.sample_texts.length > 0 && (
          <div className="space-y-1 bg-gray-900/50 rounded p-2">
            <p className="text-xs text-gray-500 mb-1">Sample utterances:</p>
            {sample.sample_texts.slice(0, 3).map((text, i) => (
              <p key={i} className="text-xs text-gray-400 italic truncate">"{text}"</p>
            ))}
          </div>
        )}

        {/* Role dropdown */}
        <div>
          <label className="text-xs text-gray-500 block mb-1">Role</label>
          <select
            value={role}
            onChange={e => setRole(e.target.value as 'dm' | 'player')}
            className="w-full px-2 py-1.5 bg-gray-700 border border-gray-600 rounded text-sm text-white focus:outline-none focus:border-blue-500"
          >
            <option value="player">Player</option>
            <option value="dm">DM</option>
          </select>
        </div>

        {/* Player name */}
        <div>
          <label className="text-xs text-gray-500 block mb-1">Player Name</label>
          <input
            type="text"
            value={playerName}
            onChange={e => setPlayerName(e.target.value)}
            placeholder="e.g. Alex"
            list={`popover-players-${speakerIndex}`}
            disabled={role === 'dm'}
            className="w-full px-2 py-1.5 bg-gray-700 border border-gray-600 rounded text-sm text-white focus:outline-none focus:border-blue-500 disabled:opacity-50"
          />
          {existingPlayers.length > 0 && (
            <datalist id={`popover-players-${speakerIndex}`}>
              {existingPlayers.map(p => <option key={p} value={p} />)}
            </datalist>
          )}
        </div>

        {/* Character name */}
        <div>
          <label className="text-xs text-gray-500 block mb-1">Character Name</label>
          <input
            type="text"
            value={characterName}
            onChange={e => setCharacterName(e.target.value)}
            placeholder="e.g. Thorin"
            disabled={role === 'dm'}
            className="w-full px-2 py-1.5 bg-gray-700 border border-gray-600 rounded text-sm text-white focus:outline-none focus:border-blue-500 disabled:opacity-50"
          />
        </div>

        {/* Actions */}
        <div className="flex gap-2 pt-1">
          <button
            onClick={handleSave}
            disabled={!playerName.trim()}
            className="flex-1 py-1.5 px-3 bg-purple-600 hover:bg-purple-500 disabled:bg-gray-700 disabled:text-gray-500 rounded text-sm font-medium transition-colors"
          >
            Save
          </button>
          <button
            onClick={onClose}
            className="flex-1 py-1.5 px-3 bg-gray-700 hover:bg-gray-600 rounded text-sm transition-colors"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

// --- Sub-component: TranscriptLine ---

interface TranscriptLineProps {
  segment: DiarizedSegment;
  mapping?: MappingRow;
  onClick: () => void;
}

function TranscriptLine({ segment, mapping, onClick }: TranscriptLineProps) {
  const isMapped = mapping && mapping.player_name.trim() !== '';
  const color = getSpeakerColor(segment.speaker);

  const label = isMapped
    ? (mapping!.character_name || mapping!.player_name)
    : `Speaker ${segment.speaker}`;

  return (
    <div className="flex gap-2 py-1 text-sm leading-relaxed">
      <span className="text-gray-600 text-xs font-mono flex-shrink-0 pt-0.5 select-none">
        {formatTimestamp(segment.start)}
      </span>
      <button
        onClick={onClick}
        className={`flex-shrink-0 px-1.5 py-0.5 rounded text-xs font-medium cursor-pointer transition-colors ${
          isMapped
            ? `${color.bg} ${color.text}`
            : 'bg-gray-700 text-gray-400 border border-dashed border-gray-500'
        }`}
        title={`Click to map Speaker ${segment.speaker}`}
      >
        {label}
      </button>
      <span className="text-gray-300">{segment.text}</span>
    </div>
  );
}

// --- Main: TranscriptEditor ---

interface MappingRow {
  speaker_index: number;
  role: 'dm' | 'player';
  player_name: string;
  character_name: string;
}

interface Props {
  segments: DiarizedSegment[];
  speakerSamples: SpeakerSample[];
  existingPlayers: string[];
  onSubmit: (mappings: SpeakerMappingEntry[], sessionNumber?: number, campaignId?: string) => void;
  isProcessing: boolean;
}

export function TranscriptEditor({ segments, speakerSamples, existingPlayers, onSubmit, isProcessing }: Props) {
  const [mappings, setMappings] = useState<Map<number, MappingRow>>(new Map());
  const [activeSpeaker, setActiveSpeaker] = useState<number | null>(null);
  const [sessionNumber, setSessionNumber] = useState('');
  const [campaignId, setCampaignId] = useState('');

  // Unique speaker indices from segments
  const speakerIndices = useMemo(() => {
    const set = new Set(segments.map(s => s.speaker));
    return Array.from(set).sort((a, b) => a - b);
  }, [segments]);

  // Auto-suggest DM for highest-utterance speaker
  useEffect(() => {
    if (speakerSamples.length === 0) return;
    const dmIdx = speakerSamples.reduce((maxIdx, s, i, arr) =>
      s.utterance_count > arr[maxIdx].utterance_count ? i : maxIdx
    , 0);
    const dmSpeaker = speakerSamples[dmIdx].speaker_index;

    setMappings(new Map([[dmSpeaker, {
      speaker_index: dmSpeaker,
      role: 'dm',
      player_name: 'DM',
      character_name: '',
    }]]));
  }, [speakerSamples]);

  const saveSpeakerMapping = useCallback((row: MappingRow) => {
    setMappings(prev => {
      const next = new Map(prev);
      next.set(row.speaker_index, row);
      return next;
    });
    setActiveSpeaker(null);
  }, []);

  const handleSubmit = () => {
    const entries: SpeakerMappingEntry[] = speakerIndices.map(i => {
      const m = mappings.get(i);
      if (m && m.player_name.trim()) {
        return {
          speaker_index: i,
          role: m.role,
          player_name: m.player_name.trim(),
          character_name: m.character_name.trim() || undefined,
        };
      }
      // Default unmapped speakers to "Speaker N"
      return {
        speaker_index: i,
        role: 'player' as const,
        player_name: `Speaker ${i}`,
      };
    });
    const num = sessionNumber ? parseInt(sessionNumber, 10) : undefined;
    onSubmit(entries, num, campaignId || undefined);
  };

  const activeSample = activeSpeaker !== null
    ? speakerSamples.find(s => s.speaker_index === activeSpeaker)
    : undefined;

  const activeMapping = activeSpeaker !== null
    ? (mappings.get(activeSpeaker) ?? {
        speaker_index: activeSpeaker,
        role: 'player' as const,
        player_name: '',
        character_name: '',
      })
    : null;

  return (
    <div className="space-y-4">
      {/* Header with progress */}
      <div className="flex items-center justify-between">
        <p className="text-sm text-gray-400">
          Click speaker labels to assign names.
        </p>
        <MappingProgress speakerIndices={speakerIndices} mappings={mappings} />
      </div>

      {/* Transcript scroll area */}
      <div className="bg-gray-900 rounded-lg p-3 max-h-[50vh] overflow-y-auto space-y-0.5">
        {segments.map((seg, i) => (
          <TranscriptLine
            key={i}
            segment={seg}
            mapping={mappings.get(seg.speaker)}
            onClick={() => setActiveSpeaker(seg.speaker)}
          />
        ))}
      </div>

      {/* Session metadata */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs text-gray-500 block mb-1">Session Number</label>
          <input
            type="number"
            min="1"
            value={sessionNumber}
            onChange={e => setSessionNumber(e.target.value)}
            placeholder="e.g. 12"
            className="w-full px-2 py-1.5 bg-gray-700 border border-gray-600 rounded text-sm text-white focus:outline-none focus:border-blue-500"
          />
        </div>
        <div>
          <label className="text-xs text-gray-500 block mb-1">Campaign ID (optional)</label>
          <input
            type="text"
            value={campaignId}
            onChange={e => setCampaignId(e.target.value)}
            placeholder="e.g. campaign_abc"
            className="w-full px-2 py-1.5 bg-gray-700 border border-gray-600 rounded text-sm text-white focus:outline-none focus:border-blue-500"
          />
        </div>
      </div>

      {/* Submit */}
      <button
        onClick={handleSubmit}
        disabled={isProcessing}
        className="w-full py-3 px-4 bg-purple-600 hover:bg-purple-500 disabled:bg-gray-700 disabled:text-gray-500 rounded-lg font-medium transition-colors"
      >
        {isProcessing ? 'Processing...' : 'Map Speakers & Process Transcript'}
      </button>

      {/* Speaker popover */}
      {activeSpeaker !== null && activeMapping && (
        <SpeakerPopover
          speakerIndex={activeSpeaker}
          sample={activeSample}
          existingPlayers={existingPlayers}
          mapping={activeMapping}
          onSave={saveSpeakerMapping}
          onClose={() => setActiveSpeaker(null)}
        />
      )}
    </div>
  );
}
