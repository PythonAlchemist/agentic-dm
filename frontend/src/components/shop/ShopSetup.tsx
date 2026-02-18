import { useState } from 'react';
import { SHOP_SPECIALTIES, SHOP_SIZES } from './types';
import type { ShopGenerateRequest } from '../../types';

interface ShopSetupProps {
  isGenerating: boolean;
  onGenerate: (request: ShopGenerateRequest) => void;
}

export function ShopSetup({ isGenerating, onGenerate }: ShopSetupProps) {
  const [size, setSize] = useState<'small' | 'medium' | 'large'>('medium');
  const [specialty, setSpecialty] = useState('general');
  const [name, setName] = useState('');
  const [keeperName, setKeeperName] = useState('');
  const [keeperRace, setKeeperRace] = useState('');

  const handleGenerate = () => {
    onGenerate({
      size,
      specialty,
      name: name || undefined,
      shopkeeper_name: keeperName || undefined,
      shopkeeper_race: keeperRace || undefined,
    });
  };

  return (
    <div className="space-y-6">
      <h3 className="font-medium text-lg">Generate New Shop</h3>

      {/* Size Selection */}
      <div>
        <label className="text-sm text-gray-400 block mb-2">Shop Size</label>
        <div className="grid grid-cols-3 gap-2">
          {SHOP_SIZES.map(s => (
            <button
              key={s.value}
              onClick={() => setSize(s.value)}
              className={`p-3 rounded-lg text-left transition-colors ${
                size === s.value
                  ? 'bg-amber-600/30 border border-amber-500'
                  : 'bg-gray-700 hover:bg-gray-600 border border-transparent'
              }`}
            >
              <div className="text-sm font-medium">{s.label}</div>
              <div className="text-xs text-gray-400 mt-1">{s.description}</div>
            </button>
          ))}
        </div>
      </div>

      {/* Specialty Selection */}
      <div>
        <label className="text-sm text-gray-400 block mb-2">Specialty</label>
        <div className="grid grid-cols-3 gap-2">
          {SHOP_SPECIALTIES.map(s => (
            <button
              key={s.value}
              onClick={() => setSpecialty(s.value)}
              className={`py-2 px-3 rounded-lg text-sm transition-colors ${
                specialty === s.value
                  ? 'bg-amber-600/30 border border-amber-500'
                  : 'bg-gray-700 hover:bg-gray-600 border border-transparent'
              }`}
            >
              {s.label}
            </button>
          ))}
        </div>
      </div>

      {/* Optional Fields */}
      <div className="grid grid-cols-3 gap-3">
        <div>
          <label className="text-sm text-gray-400 block mb-1">Shop Name (optional)</label>
          <input
            type="text"
            value={name}
            onChange={e => setName(e.target.value)}
            placeholder="Auto-generated"
            className="w-full px-3 py-2 bg-gray-700 rounded-lg text-sm border border-gray-600 focus:border-amber-500 focus:outline-none"
          />
        </div>
        <div>
          <label className="text-sm text-gray-400 block mb-1">Shopkeeper Name (optional)</label>
          <input
            type="text"
            value={keeperName}
            onChange={e => setKeeperName(e.target.value)}
            placeholder="Auto-generated"
            className="w-full px-3 py-2 bg-gray-700 rounded-lg text-sm border border-gray-600 focus:border-amber-500 focus:outline-none"
          />
        </div>
        <div>
          <label className="text-sm text-gray-400 block mb-1">Shopkeeper Race (optional)</label>
          <input
            type="text"
            value={keeperRace}
            onChange={e => setKeeperRace(e.target.value)}
            placeholder="Random"
            className="w-full px-3 py-2 bg-gray-700 rounded-lg text-sm border border-gray-600 focus:border-amber-500 focus:outline-none"
          />
        </div>
      </div>

      {/* Generate Button */}
      <div className="flex justify-center pt-4">
        <button
          onClick={handleGenerate}
          disabled={isGenerating}
          className="px-6 py-3 bg-amber-600 hover:bg-amber-700 rounded-lg font-medium transition-colors disabled:opacity-50"
        >
          {isGenerating ? 'Generating Shop...' : 'Generate Shop'}
        </button>
      </div>
    </div>
  );
}
