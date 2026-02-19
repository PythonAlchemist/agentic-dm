import { useState, useEffect } from 'react';
import { useAudioTranscription } from './useAudioTranscription';
import { AudioUpload } from './AudioUpload';
import { AudioRecorder } from './AudioRecorder';
import { SpeakerMapper } from './SpeakerMapper';
import { TranscriptionStatus } from './TranscriptionStatus';
import { playerAPI } from '../../api/client';

type InputMode = 'upload' | 'record';

interface Props {
  onClose: () => void;
}

export function AudioTranscriber({ onClose }: Props) {
  const { phase, jobStatus, error, upload, submitMappings, reset } = useAudioTranscription();
  const [existingPlayers, setExistingPlayers] = useState<string[]>([]);
  const [inputMode, setInputMode] = useState<InputMode>('upload');

  // Load player names for autocomplete
  useEffect(() => {
    playerAPI.list().then(players => {
      setExistingPlayers(players.map(p => p.name));
    }).catch(() => {});
  }, []);

  const isActive = phase !== 'idle' && phase !== 'completed' && phase !== 'error';

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

        {/* Phase-specific content */}
        {(phase === 'idle' || phase === 'uploading') && (
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
          <SpeakerMapper
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

              {/* Entity breakdown */}
              {Object.keys(jobStatus.transcript_result.entity_counts).length > 0 && (
                <div className="mt-3 pt-3 border-t border-green-700/30">
                  <p className="text-xs text-gray-400 mb-2">Entity breakdown:</p>
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(jobStatus.transcript_result.entity_counts).map(([type, count]) => (
                      <span key={type} className="px-2 py-0.5 bg-gray-700 rounded text-xs text-gray-300">
                        {type}: {count}
                      </span>
                    ))}
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
