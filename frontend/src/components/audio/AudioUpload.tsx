import { useState, useCallback, useRef } from 'react';

const ALLOWED_EXTENSIONS = ['.mp3', '.wav', '.m4a', '.webm', '.ogg', '.flac'];

interface Props {
  onUpload: (file: File, sessionNumber?: number) => void;
  isUploading: boolean;
}

export function AudioUpload({ onUpload, isUploading }: Props) {
  const [dragActive, setDragActive] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [sessionNumber, setSessionNumber] = useState<string>('');
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const validateFile = useCallback((file: File): boolean => {
    const ext = '.' + file.name.split('.').pop()?.toLowerCase();
    if (!ALLOWED_EXTENSIONS.includes(ext)) {
      setError(`Unsupported file type. Allowed: ${ALLOWED_EXTENSIONS.join(', ')}`);
      return false;
    }
    setError(null);
    return true;
  }, []);

  const handleFile = useCallback((file: File) => {
    if (validateFile(file)) {
      setSelectedFile(file);
    }
  }, [validateFile]);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragActive(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  }, [handleFile]);

  const handleSubmit = () => {
    if (!selectedFile) return;
    const num = sessionNumber ? parseInt(sessionNumber, 10) : undefined;
    onUpload(selectedFile, num);
  };

  return (
    <div className="space-y-4">
      {/* Drop zone */}
      <div
        className={`border-2 border-dashed rounded-xl p-8 text-center transition-colors cursor-pointer ${
          dragActive
            ? 'border-blue-400 bg-blue-400/10'
            : 'border-gray-600 hover:border-gray-500'
        }`}
        onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
        onDragLeave={() => setDragActive(false)}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
      >
        <input
          ref={inputRef}
          type="file"
          className="hidden"
          accept={ALLOWED_EXTENSIONS.join(',')}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) handleFile(file);
          }}
        />

        {selectedFile ? (
          <div>
            <div className="text-3xl mb-2">🎵</div>
            <p className="text-white font-medium">{selectedFile.name}</p>
            <p className="text-gray-400 text-sm mt-1">
              {(selectedFile.size / (1024 * 1024)).toFixed(1)} MB
            </p>
            <p className="text-gray-500 text-xs mt-2">Click or drop to change file</p>
          </div>
        ) : (
          <div>
            <div className="text-3xl mb-2">📁</div>
            <p className="text-gray-300">Drop audio file here or click to browse</p>
            <p className="text-gray-500 text-sm mt-1">
              Supports: {ALLOWED_EXTENSIONS.join(', ')}
            </p>
          </div>
        )}
      </div>

      {error && (
        <p className="text-red-400 text-sm">{error}</p>
      )}

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

      {/* Upload button */}
      <button
        onClick={handleSubmit}
        disabled={!selectedFile || isUploading}
        className="w-full py-3 px-4 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:text-gray-500 rounded-lg font-medium transition-colors"
      >
        {isUploading ? 'Uploading...' : 'Upload & Transcribe'}
      </button>
    </div>
  );
}
