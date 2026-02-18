import { useState } from 'react';
import type { ShopItem } from './types';
import { getRarityColor, ITEM_RARITIES } from './types';

interface InventoryTableProps {
  items: ShopItem[];
  onUpdateItem: (itemId: string, updates: Partial<ShopItem>) => void;
  onRemoveItem: (itemId: string) => void;
  onOpenAddItem: () => void;
}

type SortField = 'name' | 'price_gp' | 'quantity' | 'rarity' | 'category';
type SortDir = 'asc' | 'desc';

const RARITY_ORDER = ['common', 'uncommon', 'rare', 'very_rare', 'legendary'];

export function InventoryTable({ items, onUpdateItem, onRemoveItem, onOpenAddItem }: InventoryTableProps) {
  const [sortField, setSortField] = useState<SortField>('name');
  const [sortDir, setSortDir] = useState<SortDir>('asc');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editPrice, setEditPrice] = useState('');
  const [editQty, setEditQty] = useState('');

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortDir('asc');
    }
  };

  const sorted = [...items].sort((a, b) => {
    let cmp = 0;
    if (sortField === 'rarity') {
      cmp = RARITY_ORDER.indexOf(a.rarity) - RARITY_ORDER.indexOf(b.rarity);
    } else if (sortField === 'price_gp' || sortField === 'quantity') {
      cmp = (a[sortField] ?? 0) - (b[sortField] ?? 0);
    } else {
      cmp = (a[sortField] ?? '').toString().localeCompare((b[sortField] ?? '').toString());
    }
    return sortDir === 'asc' ? cmp : -cmp;
  });

  const startEdit = (item: ShopItem) => {
    setEditingId(item.entity_id || null);
    setEditPrice(item.price_gp.toString());
    setEditQty(item.quantity.toString());
  };

  const saveEdit = (itemId: string) => {
    const updates: Partial<ShopItem> = {};
    const price = parseFloat(editPrice);
    const qty = parseInt(editQty);
    if (!isNaN(price)) updates.price_gp = price;
    if (!isNaN(qty) && qty >= 0) updates.quantity = qty;
    onUpdateItem(itemId, updates);
    setEditingId(null);
  };

  const SortHeader = ({ field, label }: { field: SortField; label: string }) => (
    <th
      className="px-3 py-2 text-left text-xs font-medium text-gray-400 uppercase cursor-pointer hover:text-gray-200 select-none"
      onClick={() => handleSort(field)}
    >
      {label}
      {sortField === field && (
        <span className="ml-1">{sortDir === 'asc' ? '\u25B2' : '\u25BC'}</span>
      )}
    </th>
  );

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <h4 className="font-medium text-sm text-gray-300">
          Inventory ({items.length} items)
        </h4>
        <button
          onClick={onOpenAddItem}
          className="px-3 py-1 text-xs bg-green-700 hover:bg-green-600 rounded transition-colors"
        >
          + Add Item
        </button>
      </div>

      <div className="overflow-auto max-h-[400px] rounded-lg border border-gray-700">
        <table className="w-full text-sm">
          <thead className="bg-gray-800 sticky top-0">
            <tr>
              <SortHeader field="name" label="Item" />
              <SortHeader field="rarity" label="Rarity" />
              <SortHeader field="category" label="Type" />
              <SortHeader field="price_gp" label="Price (gp)" />
              <SortHeader field="quantity" label="Qty" />
              <th className="px-3 py-2 text-right text-xs font-medium text-gray-400 uppercase">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-700/50">
            {sorted.map(item => (
              <tr
                key={item.entity_id || item.name}
                className="hover:bg-gray-700/30 transition-colors"
              >
                <td className="px-3 py-2">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{item.name}</span>
                    {item.magical && (
                      <span className="px-1.5 py-0.5 bg-purple-600/30 text-purple-300 text-xs rounded">
                        Magic
                      </span>
                    )}
                  </div>
                  {item.description && (
                    <div className="text-xs text-gray-500 mt-0.5 max-w-xs truncate">
                      {item.description}
                    </div>
                  )}
                </td>
                <td className={`px-3 py-2 text-xs ${getRarityColor(item.rarity)}`}>
                  {ITEM_RARITIES.find(r => r.value === item.rarity)?.label || item.rarity}
                </td>
                <td className="px-3 py-2 text-xs text-gray-400 capitalize">
                  {item.category}
                </td>
                <td className="px-3 py-2">
                  {editingId === item.entity_id ? (
                    <input
                      type="number"
                      value={editPrice}
                      onChange={e => setEditPrice(e.target.value)}
                      className="w-20 px-2 py-1 bg-gray-600 rounded text-xs border border-gray-500 focus:border-amber-500 focus:outline-none"
                      min="0"
                      step="0.1"
                    />
                  ) : (
                    <span className="text-amber-400">{item.price_gp}</span>
                  )}
                </td>
                <td className="px-3 py-2">
                  {editingId === item.entity_id ? (
                    <input
                      type="number"
                      value={editQty}
                      onChange={e => setEditQty(e.target.value)}
                      className="w-16 px-2 py-1 bg-gray-600 rounded text-xs border border-gray-500 focus:border-amber-500 focus:outline-none"
                      min="0"
                    />
                  ) : (
                    <span>{item.quantity}</span>
                  )}
                </td>
                <td className="px-3 py-2 text-right">
                  <div className="flex items-center justify-end gap-1">
                    {editingId === item.entity_id ? (
                      <>
                        <button
                          onClick={() => saveEdit(item.entity_id!)}
                          className="px-2 py-1 text-xs bg-green-700 hover:bg-green-600 rounded transition-colors"
                        >
                          Save
                        </button>
                        <button
                          onClick={() => setEditingId(null)}
                          className="px-2 py-1 text-xs bg-gray-600 hover:bg-gray-500 rounded transition-colors"
                        >
                          Cancel
                        </button>
                      </>
                    ) : (
                      <>
                        <button
                          onClick={() => startEdit(item)}
                          className="px-2 py-1 text-xs bg-gray-600 hover:bg-gray-500 rounded transition-colors"
                          title="Edit price/quantity"
                        >
                          Edit
                        </button>
                        <button
                          onClick={() => item.entity_id && onRemoveItem(item.entity_id)}
                          className="px-2 py-1 text-xs bg-red-700/50 hover:bg-red-600 rounded transition-colors"
                          title="Remove from inventory"
                        >
                          Remove
                        </button>
                      </>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {items.length === 0 && (
          <div className="text-center text-gray-500 py-8 text-sm">
            No items in inventory
          </div>
        )}
      </div>
    </div>
  );
}
