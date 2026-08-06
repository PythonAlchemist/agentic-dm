import { useState, useEffect, useCallback } from 'react';
import { useAudioTranscription } from './useAudioTranscription';
import { AudioUpload } from './AudioUpload';
import { AudioRecorder } from './AudioRecorder';
import { TranscriptEditor } from './TranscriptEditor';
import { TranscriptionStatus } from './TranscriptionStatus';
import { EntityPreviewGraph } from './EntityPreviewGraph';
import { playerAPI, audioAPI } from '../../api/client';
import type { TranscriptHistoryItem, TranscriptDetail } from '../../types';

type InputMode = 'upload' | 'record';

const ENTITY_TYPE_COLORS: Record<string, { bg: string; text: string }> = {
  PC: { bg: 'bg-green-600/30', text: 'text-green-300' },
  NPC: { bg: 'bg-blue-600/30', text: 'text-blue-300' },
  LOCATION: { bg: 'bg-orange-600/30', text: 'text-orange-300' },
  ITEM: { bg: 'bg-purple-600/30', text: 'text-purple-300' },
  FACTION: { bg: 'bg-red-600/30', text: 'text-red-300' },
  EVENT: { bg: 'bg-cyan-600/30', text: 'text-cyan-300' },
  MONSTER: { bg: 'bg-pink-600/30', text: 'text-pink-300' },
  SPELL: { bg: 'bg-yellow-600/30', text: 'text-yellow-300' },
  QUEST: { bg: 'bg-orange-600/30', text: 'text-orange-300' },
  LORE: { bg: 'bg-gray-600/30', text: 'text-gray-300' },
  SESSION: { bg: 'bg-indigo-600/30', text: 'text-indigo-300' },
};

function formatDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

function ReviewPanel({
  jobStatus,
  onConfirm,
  onDiscard,
}: {
  jobStatus: import('../../types').AudioJobStatus;
  onConfirm: () => void;
  onDiscard: () => void;
}) {
  const [showDetails, setShowDetails] = useState(false);
  const entities = jobStatus.entities || [];
  const relationships = jobStatus.relationships || [];

  return (
    <div className="space-y-4">
      <div className="bg-amber-900/20 border border-amber-700/50 rounded-lg p-4 space-y-2">
        <h3 className="font-medium text-amber-400">Review Knowledge Base Preview</h3>
        <p className="text-sm text-gray-400">
          These entities and relationships will be added to the knowledge graph. Hover over nodes to explore connections.
        </p>
      </div>

      {/* Entity breakdown badges */}
      {jobStatus.entity_counts && Object.keys(jobStatus.entity_counts).length > 0 && (
        <div className="flex flex-wrap gap-2">
          {Object.entries(jobStatus.entity_counts).map(([type, count]) => {
            const colors = ENTITY_TYPE_COLORS[type] || { bg: 'bg-gray-700', text: 'text-gray-300' };
            return (
              <span key={type} className={`px-2 py-0.5 rounded text-xs font-medium ${colors.bg} ${colors.text}`}>
                {type}: {count}
              </span>
            );
          })}
        </div>
      )}

      {/* Graph preview */}
      {entities.length > 0 && (
        <EntityPreviewGraph
          entities={entities}
          relationships={relationships}
          height={350}
        />
      )}

      {/* Collapsible detail lists */}
      <button
        onClick={() => setShowDetails(!showDetails)}
        className="text-sm text-gray-400 hover:text-gray-300 transition-colors flex items-center gap-1"
      >
        <span className={`transition-transform inline-block ${showDetails ? 'rotate-90' : ''}`}>&#9654;</span>
        {showDetails ? 'Hide' : 'Show'} entity &amp; relationship details ({entities.length} entities, {relationships.length} relationships)
      </button>

      {showDetails && (
        <>
          {entities.length > 0 && (
            <div className="bg-gray-700/50 rounded-lg p-4 space-y-3">
              <h3 className="text-sm font-medium text-gray-300">
                Entities ({entities.length})
              </h3>
              <div className="space-y-1.5 max-h-[25vh] overflow-y-auto">
                {entities.map((entity, i) => {
                  const colors = ENTITY_TYPE_COLORS[entity.entity_type] || { bg: 'bg-gray-700', text: 'text-gray-300' };
                  return (
                    <div key={`${entity.name}-${entity.entity_type}-${i}`} className="flex items-center gap-2 text-sm">
                      <span className={`flex-shrink-0 px-1.5 py-0.5 rounded text-xs font-medium ${colors.bg} ${colors.text}`}>
                        {entity.entity_type}
                      </span>
                      <span className="text-white">{entity.name}</span>
                      <span className="text-gray-600 text-xs">{Math.round(entity.confidence * 100)}%</span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {relationships.length > 0 && (
            <div className="bg-gray-700/50 rounded-lg p-4 space-y-3">
              <h3 className="text-sm font-medium text-gray-300">
                Relationships ({relationships.length})
              </h3>
              <div className="space-y-1 max-h-[20vh] overflow-y-auto">
                {relationships.map((rel, i) => (
                  <div key={i} className="flex items-center gap-2 text-xs">
                    <span className="text-white font-medium">{rel.source}</span>
                    <span className="text-gray-500 italic">{rel.type.replace(/_/g, ' ').toLowerCase()}</span>
                    <span className="text-white font-medium">{rel.target}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}

      {/* Action buttons */}
      <div className="flex gap-3">
        <button
          onClick={onConfirm}
          className="flex-1 py-2 px-4 bg-green-700 hover:bg-green-600 rounded-lg text-sm font-medium transition-colors"
        >
          Confirm &amp; Add to Knowledge Base
        </button>
        <button
          onClick={onDiscard}
          className="py-2 px-4 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm transition-colors"
        >
          Discard &amp; Start Over
        </button>
      </div>
    </div>
  );
}

interface Props {
  onClose: () => void;
}

export function AudioTranscriber({ onClose }: Props) {
  const { phase, jobStatus, error, upload, submitMappings, confirmEntities, reset } = useAudioTranscription();
  const [existingPlayers, setExistingPlayers] = useState<string[]>([]);
  const [inputMode, setInputMode] = useState<InputMode>('upload');
  const [historyItems, setHistoryItems] = useState<TranscriptHistoryItem[]>([]);
  const [selectedTranscript, setSelectedTranscript] = useState<TranscriptDetail | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);

  const loadHistory = useCallback(() => {
    setHistoryLoading(true);
    audioAPI.listTranscripts()
      .then(res => setHistoryItems(res.transcripts))
      .catch(() => {})
      .finally(() => setHistoryLoading(false));
  }, []);

  // Load player names for autocomplete
  useEffect(() => {
    playerAPI.list().then(players => {
      setExistingPlayers(players.map(p => p.name));
    }).catch(() => {});
  }, []);

  // Load history on mount and when a job completes
  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  useEffect(() => {
    if (phase === 'completed') {
      loadHistory();
    }
  }, [phase, loadHistory]);

  const openTranscript = (jobId: string) => {
    audioAPI.getTranscript(jobId)
      .then(detail => setSelectedTranscript(detail))
      .catch(() => {});
  };

  const isActive = phase !== 'idle' && phase !== 'completed' && phase !== 'error' && phase !== 'review';

  return (
    <div className="flex-[2] flex flex-col bg-gray-800 border-r border-gray-700 min-w-0">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-700 flex items-center justify-between bg-gray-900/50 flex-shrink-0">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-bold">Session Transcript</h2>
          {isActive && (
            <span className="px-2 py-0.5 bg-blue-600/30 text-blue-400 rounded-full text-xs font-medium">
              Processing
            </span>
          )}
          {phase === 'review' && (
            <span className="px-2 py-0.5 bg-amber-600/30 text-amber-400 rounded-full text-xs font-medium">
              Review
            </span>
          )}
          {phase === 'completed' && (
            <span className="px-2 py-0.5 bg-green-600/30 text-green-400 rounded-full text-xs font-medium">
              Done
            </span>
          )}
        </div>
        <button
          onClick={onClose}
          className="text-gray-400 hover:text-white transition-colors"
          title="Close"
        >
          ✕
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Status bar (shown during active processing) */}
        {phase !== 'idle' && (
          <TranscriptionStatus
            phase={jobStatus?.phase || phase}
            error={error}
          />
        )}

        {/* Transcript detail view */}
        {selectedTranscript && phase === 'idle' && (
          <div className="space-y-4">
            <button
              onClick={() => setSelectedTranscript(null)}
              className="flex items-center gap-1 text-sm text-gray-400 hover:text-white transition-colors"
            >
              &larr; Back to list
            </button>

            <div className="space-y-1">
              <h3 className="font-medium text-white">{selectedTranscript.filename}</h3>
              <p className="text-xs text-gray-400">
                {new Date(selectedTranscript.completed_at).toLocaleDateString()} &middot;{' '}
                {selectedTranscript.session_number != null && `Session ${selectedTranscript.session_number} · `}
                {selectedTranscript.total_duration != null && `${formatDuration(selectedTranscript.total_duration)} · `}
                {selectedTranscript.segment_count != null && `${selectedTranscript.segment_count} segments`}
              </p>
            </div>

            {/* Speakers */}
            {selectedTranscript.speaker_mappings.length > 0 && (
              <div className="bg-gray-700/50 rounded-lg p-3 space-y-1">
                <p className="text-xs text-gray-400 font-medium mb-2">Speakers</p>
                {selectedTranscript.speaker_mappings.map((s, i) => (
                  <div key={i} className="flex items-center gap-2 text-sm">
                    <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${
                      s.role === 'dm' ? 'bg-purple-600/30 text-purple-300' : 'bg-blue-600/30 text-blue-300'
                    }`}>
                      {s.role.toUpperCase()}
                    </span>
                    <span className="text-white">{s.player_name}</span>
                    {s.character_name && (
                      <span className="text-gray-400">as {s.character_name}</span>
                    )}
                  </div>
                ))}
              </div>
            )}

            {/* Processing stats */}
            {selectedTranscript.transcript_result && (
              <div className="grid grid-cols-2 gap-2 text-sm bg-gray-700/50 rounded-lg p-3">
                <div className="text-gray-400">Entities Extracted</div>
                <div className="text-white">{selectedTranscript.transcript_result.entities_extracted}</div>
                <div className="text-gray-400">Relationships</div>
                <div className="text-white">{selectedTranscript.transcript_result.relationships_created}</div>
                <div className="text-gray-400">Processing Time</div>
                <div className="text-white">{(selectedTranscript.transcript_result.processing_time_ms / 1000).toFixed(1)}s</div>
              </div>
            )}

            {/* Full transcript text */}
            <div className="bg-gray-900 rounded-lg p-3 max-h-[60vh] overflow-y-auto">
              <pre className="text-xs text-gray-300 whitespace-pre-wrap font-mono leading-relaxed">
                {selectedTranscript.transcript_text}
              </pre>
            </div>
          </div>
        )}

        {/* Phase-specific content */}
        {(phase === 'idle' || phase === 'uploading') && !selectedTranscript && (
          <>
            {/* Mode toggle */}
            <div className="flex rounded-lg bg-gray-700/50 p-0.5">
              <button
                onClick={() => setInputMode('upload')}
                className={`flex-1 py-1.5 px-3 rounded-md text-sm font-medium transition-colors ${
                  inputMode === 'upload'
                    ? 'bg-gray-600 text-white'
                    : 'text-gray-400 hover:text-gray-300'
                }`}
              >
                Upload File
              </button>
              <button
                onClick={() => setInputMode('record')}
                className={`flex-1 py-1.5 px-3 rounded-md text-sm font-medium transition-colors ${
                  inputMode === 'record'
                    ? 'bg-gray-600 text-white'
                    : 'text-gray-400 hover:text-gray-300'
                }`}
              >
                Record Session
              </button>
            </div>

            {inputMode === 'upload' ? (
              <AudioUpload onUpload={upload} isUploading={phase === 'uploading'} />
            ) : (
              <AudioRecorder onRecordingComplete={upload} />
            )}

            {/* History list */}
            {historyItems.length > 0 && (
              <div className="space-y-2 pt-2 border-t border-gray-700">
                <h3 className="text-sm font-medium text-gray-400">Previous Transcripts</h3>
                {historyLoading ? (
                  <p className="text-xs text-gray-500">Loading...</p>
                ) : (
                  <div className="space-y-1">
                    {historyItems.map(item => (
                      <button
                        key={item.job_id}
                        onClick={() => openTranscript(item.job_id)}
                        className="w-full text-left p-2.5 bg-gray-700/40 hover:bg-gray-700/70 rounded-lg transition-colors"
                      >
                        <div className="text-sm text-white truncate">{item.filename}</div>
                        <div className="flex items-center gap-2 mt-0.5 text-xs text-gray-400">
                          <span>{new Date(item.completed_at).toLocaleDateString()}</span>
                          {item.session_number != null && <span>Session {item.session_number}</span>}
                          {item.total_duration != null && <span>{formatDuration(item.total_duration)}</span>}
                          {item.entities_extracted != null && <span>{item.entities_extracted} entities</span>}
                        </div>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </>
        )}

        {(phase === 'polling') && (
          <div className="text-center py-8">
            <div className="text-4xl mb-3">🎙️</div>
            <p className="text-gray-300">Transcribing your audio...</p>
            <p className="text-gray-500 text-sm mt-1">This may take a few minutes for longer recordings.</p>
          </div>
        )}

        {phase === 'mapping' && jobStatus?.speaker_samples && (
          <TranscriptEditor
            segments={jobStatus.segments ?? []}
            speakerSamples={jobStatus.speaker_samples}
            existingPlayers={existingPlayers}
            onSubmit={submitMappings}
            isProcessing={false}
          />
        )}

        {phase === 'processing' && (
          <div className="text-center py-8">
            <div className="text-4xl mb-3">🧠</div>
            <p className="text-gray-300">Extracting entities and building knowledge graph...</p>
          </div>
        )}

        {phase === 'review' && jobStatus && (
          <ReviewPanel
            jobStatus={jobStatus}
            onConfirm={confirmEntities}
            onDiscard={reset}
          />
        )}

        {phase === 'completed' && jobStatus?.transcript_result && (
          <div className="space-y-4">
            <div className="bg-green-900/20 border border-green-700/50 rounded-lg p-4 space-y-2">
              <h3 className="font-medium text-green-400">Transcript Processed Successfully</h3>
              <div className="grid grid-cols-2 gap-2 text-sm">
                <div className="text-gray-400">Session ID</div>
                <div className="text-white font-mono text-xs">{jobStatus.transcript_result.session_id}</div>
                <div className="text-gray-400">Segments</div>
                <div className="text-white">{jobStatus.transcript_result.segments_processed}</div>
                <div className="text-gray-400">Entities Extracted</div>
                <div className="text-white">{jobStatus.transcript_result.entities_extracted}</div>
                <div className="text-gray-400">Entities Created</div>
                <div className="text-white">{jobStatus.transcript_result.entities_created}</div>
                <div className="text-gray-400">Relationships</div>
                <div className="text-white">{jobStatus.transcript_result.relationships_created}</div>
                <div className="text-gray-400">Processing Time</div>
                <div className="text-white">{(jobStatus.transcript_result.processing_time_ms / 1000).toFixed(1)}s</div>
              </div>

              {/* Entity breakdown by type */}
              {Object.keys(jobStatus.transcript_result.entity_counts).length > 0 && (
                <div className="mt-3 pt-3 border-t border-green-700/30">
                  <p className="text-xs text-gray-400 mb-2">Entity breakdown:</p>
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(jobStatus.transcript_result.entity_counts).map(([type, count]) => {
                      const colors = ENTITY_TYPE_COLORS[type] || { bg: 'bg-gray-700', text: 'text-gray-300' };
                      return (
                        <span key={type} className={`px-2 py-0.5 rounded text-xs font-medium ${colors.bg} ${colors.text}`}>
                          {type}: {count}
                        </span>
                      );
                    })}
                  </div>
                </div>
              )}

              {jobStatus.transcript_result.errors.length > 0 && (
                <div className="mt-3 pt-3 border-t border-yellow-700/30">
                  <p className="text-xs text-yellow-400 mb-1">Warnings ({jobStatus.transcript_result.errors.length}):</p>
                  {jobStatus.transcript_result.errors.slice(0, 5).map((err, i) => (
                    <p key={i} className="text-xs text-gray-400">{err}</p>
                  ))}
                </div>
              )}
            </div>

            {/* Extracted entities list */}
            {jobStatus.transcript_result.entities && jobStatus.transcript_result.entities.length > 0 && (
              <div className="bg-gray-700/50 rounded-lg p-4 space-y-3">
                <h3 className="text-sm font-medium text-gray-300">
                  Entities Extracted ({jobStatus.transcript_result.entities.length})
                </h3>
                <div className="space-y-1.5 max-h-[30vh] overflow-y-auto">
                  {jobStatus.transcript_result.entities.map((entity, i) => {
                    const colors = ENTITY_TYPE_COLORS[entity.entity_type] || { bg: 'bg-gray-700', text: 'text-gray-300' };
                    return (
                      <div key={`${entity.name}-${entity.entity_type}-${i}`} className="flex items-center gap-2 text-sm">
                        <span className={`flex-shrink-0 px-1.5 py-0.5 rounded text-xs font-medium ${colors.bg} ${colors.text}`}>
                          {entity.entity_type}
                        </span>
                        <span className="text-white">{entity.name}</span>
                        <span className="text-gray-600 text-xs">{Math.round(entity.confidence * 100)}%</span>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Extracted relationships */}
            {jobStatus.transcript_result.relationships && jobStatus.transcript_result.relationships.length > 0 && (
              <div className="bg-gray-700/50 rounded-lg p-4 space-y-3">
                <h3 className="text-sm font-medium text-gray-300">
                  Relationships ({jobStatus.transcript_result.relationships.length})
                </h3>
                <div className="space-y-1 max-h-[20vh] overflow-y-auto">
                  {jobStatus.transcript_result.relationships.map((rel, i) => (
                    <div key={i} className="flex items-center gap-2 text-xs">
                      <span className="text-white font-medium">{rel.source}</span>
                      <span className="text-gray-500 italic">{rel.type.replace(/_/g, ' ').toLowerCase()}</span>
                      <span className="text-white font-medium">{rel.target}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <button
              onClick={reset}
              className="w-full py-2 px-4 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm transition-colors"
            >
              Process Another Recording
            </button>
          </div>
        )}

        {phase === 'error' && (
          <div className="space-y-3">
            <div className="bg-red-900/20 border border-red-700/50 rounded-lg p-4">
              <h3 className="font-medium text-red-400 mb-1">Error</h3>
              <p className="text-sm text-gray-300">{error}</p>
            </div>
            <button
              onClick={reset}
              className="w-full py-2 px-4 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm transition-colors"
            >
              Try Again
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
