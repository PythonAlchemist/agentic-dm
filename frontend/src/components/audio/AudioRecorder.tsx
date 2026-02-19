import { useState } from 'react';
import { useMediaRecorder, extensionForMime, getSupportedMime } from './useMediaRecorder';

interface Props {
  onRecordingComplete: (file: File, sessionNumber?: number) => void;
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60).toString().padStart(2, '0');
  const s = (seconds % 60).toString().padStart(2, '0');
  return `${m}:${s}`;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function AudioRecorder({ onRecordingComplete }: Props) {
  const {
    status,
    elapsed,
    audioLevel,
    audioBlob,
    error,
    startRecording,
    stopRecording,
    reset,
  } = useMediaRecorder();

  const [sessionNumber, setSessionNumber] = useState('');

  const handleUpload = () => {
    if (!audioBlob) return;
    const mime = getSupportedMime() || 'audio/webm';
    const ext = extensionForMime(mime);
    const filename = `session-recording-${Date.now()}.${ext}`;
    const file = new File([audioBlob], filename, { type: mime });
    const num = sessionNumber ? parseInt(sessionNumber, 10) : undefined;
    onRecordingComplete(file, num);
  };

  // --- Idle state ---
  if (status === 'idle') {
    return (
      <div className="space-y-4">
        <div className="border-2 border-dashed border-gray-600 rounded-xl p-8 text-center">
          <div className="text-3xl mb-2">🎙️</div>
          <p className="text-gray-300">Click below to start recording</p>
          <p className="text-gray-500 text-sm mt-1">
            Your microphone audio will be captured for transcription
          </p>
        </div>
        <button
          onClick={startRecording}
          className="w-full py-3 px-4 bg-red-600 hover:bg-red-500 rounded-lg font-medium transition-colors"
        >
          Start Recording
        </button>
      </div>
    );
  }

  // --- Requesting mic permission ---
  if (status === 'requesting') {
    return (
      <div className="border-2 border-dashed border-gray-600 rounded-xl p-8 text-center">
        <div className="text-3xl mb-2 animate-pulse">🎙️</div>
        <p className="text-gray-300">Requesting microphone access...</p>
        <p className="text-gray-500 text-sm mt-1">Please allow the permission prompt</p>
      </div>
    );
  }

  // --- Recording ---
  if (status === 'recording' || status === 'stopping') {
    return (
      <div className="space-y-4">
        <div className="border-2 border-red-500/50 rounded-xl p-8 text-center space-y-4">
          {/* Pulsing red dot + timer */}
          <div className="flex items-center justify-center gap-3">
            <span className="relative flex h-3 w-3">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-3 w-3 bg-red-500" />
            </span>
            <span className="text-2xl font-mono text-white">{formatTime(elapsed)}</span>
          </div>

          {/* Level meter */}
          <div className="w-full h-2 bg-gray-700 rounded-full overflow-hidden">
            <div
              className="h-full bg-red-500 rounded-full transition-[width] duration-100"
              style={{ width: `${Math.max(2, audioLevel * 100)}%` }}
            />
          </div>
          <p className="text-gray-400 text-xs">
            {status === 'stopping' ? 'Stopping...' : 'Recording in progress'}
          </p>
        </div>

        <button
          onClick={stopRecording}
          disabled={status === 'stopping'}
          className="w-full py-3 px-4 bg-gray-600 hover:bg-gray-500 disabled:bg-gray-700 disabled:text-gray-500 rounded-lg font-medium transition-colors"
        >
          {status === 'stopping' ? 'Stopping...' : 'Stop Recording'}
        </button>
      </div>
    );
  }

  // --- Done ---
  if (status === 'done' && audioBlob) {
    return (
      <div className="space-y-4">
        <div className="border-2 border-green-500/50 rounded-xl p-6 text-center space-y-2">
          <div className="text-3xl">✅</div>
          <p className="text-white font-medium">Recording Complete</p>
          <p className="text-gray-400 text-sm">
            Duration: {formatTime(elapsed)} &middot; Size: {formatSize(audioBlob.size)}
          </p>
          <button
            onClick={reset}
            className="text-gray-400 hover:text-white text-xs underline transition-colors mt-1"
          >
            Discard and re-record
          </button>
        </div>

        {/* Session number input */}
        <div>
          <label className="text-sm text-gray-400 block mb-1">
            Session Number (optional)
          </label>
          <input
            type="number"
            min="1"
            value={sessionNumber}
            onChange={(e) => setSessionNumber(e.target.value)}
            placeholder="e.g. 12"
            className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-white text-sm focus:outline-none focus:border-blue-500"
          />
        </div>

        <button
          onClick={handleUpload}
          className="w-full py-3 px-4 bg-blue-600 hover:bg-blue-500 rounded-lg font-medium transition-colors"
        >
          Upload &amp; Transcribe
        </button>
      </div>
    );
  }

  // --- Error ---
  if (status === 'error') {
    return (
      <div className="space-y-4">
        <div className="border-2 border-red-500/30 rounded-xl p-6 text-center space-y-2">
          <div className="text-3xl">⚠️</div>
          <p className="text-red-400 font-medium">Recording Error</p>
          <p className="text-gray-400 text-sm">{error}</p>
        </div>
        <button
          onClick={reset}
          className="w-full py-3 px-4 bg-gray-600 hover:bg-gray-500 rounded-lg font-medium transition-colors"
        >
          Try Again
        </button>
      </div>
    );
  }

  return null;
}
