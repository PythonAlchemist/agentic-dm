import type { ShopProfile, ShopItem, ShopChatMessage } from '../../types';

// Re-export for convenience
export type { ShopProfile, ShopItem, ShopChatMessage };

// Shop specialties for the setup form
export const SHOP_SPECIALTIES = [
  { value: 'weapons', label: 'Weapons' },
  { value: 'armor', label: 'Armor' },
  { value: 'potions', label: 'Potions' },
  { value: 'general', label: 'General Store' },
  { value: 'magic_items', label: 'Magic Items' },
  { value: 'curiosities', label: 'Curiosities' },
  { value: 'scrolls', label: 'Scrolls' },
  { value: 'adventuring_gear', label: 'Adventuring Gear' },
  { value: 'blacksmith', label: 'Blacksmith' },
] as const;

export const SHOP_SIZES = [
  { value: 'small', label: 'Small (5-10 items)', description: 'Modest selection, common goods' },
  { value: 'medium', label: 'Medium (10-20 items)', description: 'Good variety, some rare finds' },
  { value: 'large', label: 'Large (20-40 items)', description: 'Extensive stock, rare items available' },
] as const;

export const ITEM_RARITIES = [
  { value: 'common', label: 'Common', color: 'text-gray-300' },
  { value: 'uncommon', label: 'Uncommon', color: 'text-green-400' },
  { value: 'rare', label: 'Rare', color: 'text-blue-400' },
  { value: 'very_rare', label: 'Very Rare', color: 'text-purple-400' },
  { value: 'legendary', label: 'Legendary', color: 'text-yellow-400' },
] as const;

export const ITEM_CATEGORIES = [
  { value: 'weapon', label: 'Weapon' },
  { value: 'armor', label: 'Armor' },
  { value: 'potion', label: 'Potion' },
  { value: 'scroll', label: 'Scroll' },
  { value: 'wondrous', label: 'Wondrous Item' },
  { value: 'gear', label: 'Gear' },
  { value: 'tool', label: 'Tool' },
  { value: 'ammunition', label: 'Ammunition' },
] as const;

export function getRarityColor(rarity: string): string {
  return ITEM_RARITIES.find(r => r.value === rarity)?.color || 'text-gray-300';
}
