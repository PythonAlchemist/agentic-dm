import { useState } from 'react';
import type { ShopItem } from './types';
import { ITEM_CATEGORIES, ITEM_RARITIES } from './types';

interface AddItemModalProps {
  onClose: () => void;
  onAdd: (item: Omit<ShopItem, 'entity_id'>) => void;
}

export function AddItemModal({ onClose, onAdd }: AddItemModalProps) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [priceGp, setPriceGp] = useState('10');
  const [quantity, setQuantity] = useState('1');
  const [rarity, setRarity] = useState('common');
  const [category, setCategory] = useState('gear');
  const [magical, setMagical] = useState(false);
  const [weight, setWeight] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;

    onAdd({
      name: name.trim(),
      description: description.trim() || undefined,
      price_gp: parseFloat(priceGp) || 0,
      quantity: parseInt(quantity) || 1,
      rarity,
      category,
      magical,
      weight: weight ? parseFloat(weight) : undefined,
    });

    onClose();
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-gray-800 rounded-xl border border-gray-700 w-full max-w-md mx-4 shadow-2xl">
        <div className="px-5 py-4 border-b border-gray-700 flex items-center justify-between">
          <h3 className="font-medium">Add Custom Item</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-white transition-colors">
            \u2715
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          {/* Name */}
          <div>
            <label className="text-sm text-gray-400 block mb-1">Item Name *</label>
            <input
              type="text"
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="e.g. Potion of Speed"
              className="w-full px-3 py-2 bg-gray-700 rounded-lg text-sm border border-gray-600 focus:border-amber-500 focus:outline-none"
              required
              autoFocus
            />
          </div>

          {/* Description */}
          <div>
            <label className="text-sm text-gray-400 block mb-1">Description</label>
            <textarea
              value={description}
              onChange={e => setDescription(e.target.value)}
              placeholder="Optional item description"
              className="w-full px-3 py-2 bg-gray-700 rounded-lg text-sm border border-gray-600 focus:border-amber-500 focus:outline-none resize-none"
              rows={2}
            />
          </div>

          {/* Price & Quantity */}
          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="text-sm text-gray-400 block mb-1">Price (gp)</label>
              <input
                type="number"
                value={priceGp}
                onChange={e => setPriceGp(e.target.value)}
                min="0"
                step="0.1"
                className="w-full px-3 py-2 bg-gray-700 rounded-lg text-sm border border-gray-600 focus:border-amber-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="text-sm text-gray-400 block mb-1">Quantity</label>
              <input
                type="number"
                value={quantity}
                onChange={e => setQuantity(e.target.value)}
                min="1"
                className="w-full px-3 py-2 bg-gray-700 rounded-lg text-sm border border-gray-600 focus:border-amber-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="text-sm text-gray-400 block mb-1">Weight (lb)</label>
              <input
                type="number"
                value={weight}
                onChange={e => setWeight(e.target.value)}
                min="0"
                step="0.1"
                placeholder="Optional"
                className="w-full px-3 py-2 bg-gray-700 rounded-lg text-sm border border-gray-600 focus:border-amber-500 focus:outline-none"
              />
            </div>
          </div>

          {/* Rarity & Category */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-sm text-gray-400 block mb-1">Rarity</label>
              <select
                value={rarity}
                onChange={e => setRarity(e.target.value)}
                className="w-full px-3 py-2 bg-gray-700 rounded-lg text-sm border border-gray-600 focus:border-amber-500 focus:outline-none"
              >
                {ITEM_RARITIES.map(r => (
                  <option key={r.value} value={r.value}>{r.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-sm text-gray-400 block mb-1">Category</label>
              <select
                value={category}
                onChange={e => setCategory(e.target.value)}
                className="w-full px-3 py-2 bg-gray-700 rounded-lg text-sm border border-gray-600 focus:border-amber-500 focus:outline-none"
              >
                {ITEM_CATEGORIES.map(c => (
                  <option key={c.value} value={c.value}>{c.label}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Magical */}
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={magical}
              onChange={e => setMagical(e.target.checked)}
              className="rounded border-gray-600 bg-gray-700 text-amber-500 focus:ring-amber-500"
            />
            <span className="text-sm">Magical item</span>
          </label>

          {/* Actions */}
          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-4 py-2 bg-amber-600 hover:bg-amber-700 rounded-lg text-sm font-medium transition-colors"
            >
              Add Item
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
