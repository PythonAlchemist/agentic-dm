import { useState, useCallback, useRef, useEffect } from 'react';

type Status = 'idle' | 'requesting' | 'recording' | 'stopping' | 'done' | 'error';

interface MediaRecorderState {
  status: Status;
  elapsed: number;
  audioLevel: number;
  audioBlob: Blob | null;
  error: string | null;
  startRecording: () => void;
  stopRecording: () => void;
  reset: () => void;
}

const MIME_CANDIDATES = [
  'audio/webm;codecs=opus',
  'audio/webm',
  'audio/mp4',
  'audio/ogg;codecs=opus',
];

function getSupportedMime(): string | undefined {
  return MIME_CANDIDATES.find((m) => MediaRecorder.isTypeSupported(m));
}

function extensionForMime(mime: string): string {
  if (mime.includes('webm')) return 'webm';
  if (mime.includes('mp4')) return 'm4a';
  if (mime.includes('ogg')) return 'ogg';
  return 'webm';
}

function friendlyError(err: unknown): string {
  if (err instanceof DOMException) {
    if (err.name === 'NotAllowedError') {
      return 'Microphone access was denied. Please allow microphone permissions in your browser settings and try again.';
    }
    if (err.name === 'NotFoundError') {
      return 'No microphone found. Please connect a microphone and try again.';
    }
  }
  if (err instanceof Error) return err.message;
  return 'An unknown error occurred while accessing the microphone.';
}

export { extensionForMime, getSupportedMime };
export type { Status as MediaRecorderStatus };

export function useMediaRecorder(): MediaRecorderState {
  const [status, setStatus] = useState<Status>('idle');
  const [elapsed, setElapsed] = useState(0);
  const [audioLevel, setAudioLevel] = useState(0);
  const [audioBlob, setAudioBlob] = useState<Blob | null>(null);
  const [error, setError] = useState<string | null>(null);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const rafRef = useRef<number | null>(null);
  const mimeRef = useRef<string>('audio/webm');
  const startTimeRef = useRef<number>(0);

  const cleanup = useCallback(() => {
    // Stop animation frame
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }

    // Stop timer
    if (timerRef.current !== null) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }

    // Close audio context
    if (audioContextRef.current) {
      audioContextRef.current.close().catch(() => {});
      audioContextRef.current = null;
      analyserRef.current = null;
    }

    // Stop all stream tracks
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }

    // Stop media recorder
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      try {
        mediaRecorderRef.current.stop();
      } catch {
        // already stopped
      }
    }
    mediaRecorderRef.current = null;

    setAudioLevel(0);
  }, []);

  // Cleanup on unmount
  useEffect(() => cleanup, [cleanup]);

  const updateLevel = useCallback(() => {
    if (!analyserRef.current) return;
    const data = new Uint8Array(analyserRef.current.fftSize);
    analyserRef.current.getByteTimeDomainData(data);

    // Compute RMS
    let sum = 0;
    for (let i = 0; i < data.length; i++) {
      const v = (data[i] - 128) / 128;
      sum += v * v;
    }
    const rms = Math.sqrt(sum / data.length);
    setAudioLevel(Math.min(1, rms * 3)); // boost for visibility

    rafRef.current = requestAnimationFrame(updateLevel);
  }, []);

  const startRecording = useCallback(async () => {
    setError(null);
    setAudioBlob(null);
    setElapsed(0);
    chunksRef.current = [];
    setStatus('requesting');

    const mime = getSupportedMime();
    if (!mime) {
      setError('Your browser does not support audio recording. Please try Chrome or Firefox.');
      setStatus('error');
      return;
    }
    mimeRef.current = mime;

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      setError(friendlyError(err));
      setStatus('error');
      return;
    }
    streamRef.current = stream;

    // Set up audio analyser for level metering
    try {
      const ctx = new AudioContext();
      audioContextRef.current = ctx;
      const source = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 256;
      source.connect(analyser);
      analyserRef.current = analyser;
    } catch {
      // Level metering is non-critical; continue without it
    }

    // Create MediaRecorder
    const recorder = new MediaRecorder(stream, { mimeType: mime });
    mediaRecorderRef.current = recorder;

    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) {
        chunksRef.current.push(e.data);
      }
    };

    recorder.onstop = () => {
      const blob = new Blob(chunksRef.current, { type: mimeRef.current });
      setAudioBlob(blob);
      setStatus('done');
      cleanup();
    };

    recorder.onerror = () => {
      setError('Recording failed unexpectedly.');
      setStatus('error');
      cleanup();
    };

    recorder.start(1000); // collect data every second
    startTimeRef.current = Date.now();
    setStatus('recording');

    // Elapsed timer
    timerRef.current = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startTimeRef.current) / 1000));
    }, 500);

    // Start level metering
    if (analyserRef.current) {
      rafRef.current = requestAnimationFrame(updateLevel);
    }
  }, [cleanup, updateLevel]);

  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'recording') {
      setStatus('stopping');
      mediaRecorderRef.current.stop();
      // onstop handler will set status to 'done' and call cleanup
    }
  }, []);

  const reset = useCallback(() => {
    cleanup();
    setStatus('idle');
    setElapsed(0);
    setAudioLevel(0);
    setAudioBlob(null);
    setError(null);
    chunksRef.current = [];
  }, [cleanup]);

  return {
    status,
    elapsed,
    audioLevel,
    audioBlob,
    error,
    startRecording,
    stopRecording,
    reset,
  };
}
