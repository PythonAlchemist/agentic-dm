import type { AudioJobPhase } from './types';

interface Props {
  phase: AudioJobPhase | string;
  error?: string | null;
}

const PHASE_CONFIG: Record<string, { label: string; progress: number; color: string }> = {
  uploading: { label: 'Uploading audio file...', progress: 15, color: 'bg-blue-500' },
  transcribing: { label: 'Transcribing with Deepgram...', progress: 45, color: 'bg-blue-500' },
  awaiting_mapping: { label: 'Ready for speaker mapping', progress: 60, color: 'bg-yellow-500' },
  processing_transcript: { label: 'Processing transcript & extracting entities...', progress: 80, color: 'bg-purple-500' },
  awaiting_review: { label: 'Ready for review', progress: 90, color: 'bg-amber-500' },
  completed: { label: 'Complete!', progress: 100, color: 'bg-green-500' },
  failed: { label: 'Failed', progress: 100, color: 'bg-red-500' },
};

export function TranscriptionStatus({ phase, error }: Props) {
  const config = PHASE_CONFIG[phase] || { label: 'Processing...', progress: 50, color: 'bg-gray-500' };

  return (
    <div className="space-y-3">
      {/* Progress bar */}
      <div className="w-full bg-gray-700 rounded-full h-2 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-700 ${config.color}`}
          style={{ width: `${config.progress}%` }}
        />
      </div>

      {/* Status message */}
      <div className="flex items-center gap-2">
        {phase !== 'completed' && phase !== 'failed' && (
          <div className="w-4 h-4 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
        )}
        {phase === 'completed' && <span>✓</span>}
        {phase === 'failed' && <span>✗</span>}
        <span className="text-sm text-gray-300">{config.label}</span>
      </div>

      {error && (
        <p className="text-red-400 text-sm bg-red-400/10 px-3 py-2 rounded-lg">{error}</p>
      )}
    </div>
  );
}
