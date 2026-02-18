import { useState, useEffect } from 'react';
import { useShopState } from './useShopState';
import { ShopSetup } from './ShopSetup';
import { InventoryTable } from './InventoryTable';
import { ShopkeeperCard } from './ShopkeeperCard';
import { AddItemModal } from './AddItemModal';

interface ShopDashboardProps {
  onClose: () => void;
}

export function ShopDashboard({ onClose }: ShopDashboardProps) {
  const {
    activeShop,
    shops,
    chatMessages,
    isLoading,
    isGenerating,
    error,
    loadShops,
    generateShop,
    selectShop,
    closeShop,
    addItem,
    updateItem,
    removeItem,
    deleteShop,
    sendChatMessage,
  } = useShopState();

  const [showAddItem, setShowAddItem] = useState(false);
  const [activeTab, setActiveTab] = useState<'inventory' | 'shopkeeper'>('inventory');

  // Load existing shops on mount
  useEffect(() => {
    loadShops();
  }, [loadShops]);

  return (
    <div className="flex-[2] flex flex-col bg-gray-800 border-r border-gray-700 min-w-0">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-700 flex items-center justify-between bg-gray-900/50 flex-shrink-0">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-bold">Shop</h2>
          {activeShop && (
            <span className="px-2 py-0.5 bg-amber-600/30 text-amber-400 rounded-full text-xs font-medium">
              {activeShop.name}
            </span>
          )}
          {(isLoading || isGenerating) && (
            <span className="text-yellow-400 text-xs animate-pulse">
              {isGenerating ? 'Generating...' : 'Loading...'}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {activeShop && (
            <>
              <button
                onClick={() => setActiveTab('inventory')}
                className={`px-2 py-1 text-xs rounded transition-colors ${
                  activeTab === 'inventory'
                    ? 'bg-amber-600 text-white'
                    : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                }`}
              >
                Inventory
              </button>
              <button
                onClick={() => setActiveTab('shopkeeper')}
                className={`px-2 py-1 text-xs rounded transition-colors ${
                  activeTab === 'shopkeeper'
                    ? 'bg-amber-600 text-white'
                    : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                }`}
              >
                Shopkeeper
              </button>
              <button
                onClick={closeShop}
                className="px-2 py-1 text-xs bg-gray-700 hover:bg-gray-600 rounded transition-colors"
              >
                Back
              </button>
            </>
          )}
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-white transition-colors text-sm"
            title="Close shop panel"
          >
            \u2715
          </button>
        </div>
      </div>

      {/* Error Display */}
      {error && (
        <div className="mx-4 mt-3 p-2 bg-red-600/20 border border-red-600 rounded text-red-400 text-xs flex-shrink-0">
          {error}
        </div>
      )}

      {/* Content */}
      <div className="flex-1 overflow-hidden p-3 min-h-0">
        {!activeShop ? (
          <div className="overflow-y-auto h-full space-y-6">
            {/* Existing Shops List */}
            {shops.length > 0 && (
              <div>
                <h3 className="font-medium text-sm text-gray-300 mb-3">Existing Shops</h3>
                <div className="space-y-2">
                  {shops.map(shop => (
                    <div
                      key={shop.entity_id}
                      className="flex items-center justify-between p-3 bg-gray-700/50 rounded-lg hover:bg-gray-700 transition-colors"
                    >
                      <button
                        onClick={() => selectShop(shop.entity_id)}
                        className="flex-1 text-left"
                      >
                        <div className="font-medium">{shop.name}</div>
                        <div className="text-xs text-gray-400">
                          {shop.shop_specialty} | {shop.inventory.length} items | {shop.gold_reserves} gp
                          {shop.shopkeeper_name && ` | ${shop.shopkeeper_name}`}
                        </div>
                      </button>
                      <button
                        onClick={() => deleteShop(shop.entity_id)}
                        className="ml-2 px-2 py-1 text-xs text-red-400 hover:bg-red-600/20 rounded transition-colors"
                      >
                        Delete
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Generate New Shop */}
            <ShopSetup
              isGenerating={isGenerating}
              onGenerate={generateShop}
            />
          </div>
        ) : (
          <div className="overflow-y-auto h-full space-y-4">
            {/* Shop Header Info */}
            <div className="bg-gray-700/30 rounded-lg p-3">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="font-medium text-lg">{activeShop.name}</h3>
                  <div className="text-xs text-gray-400 mt-1">
                    <span className="capitalize">{activeShop.shop_specialty.replace('_', ' ')}</span>
                    {' | '}
                    <span className="capitalize">{activeShop.shop_size}</span> shop
                    {' | '}
                    <span className="text-amber-400">{activeShop.gold_reserves} gp</span> reserves
                  </div>
                </div>
              </div>
              {activeShop.description && (
                <p className="text-sm text-gray-300 mt-2">{activeShop.description}</p>
              )}
            </div>

            {/* Tab Content */}
            {activeTab === 'inventory' ? (
              <InventoryTable
                items={activeShop.inventory}
                onUpdateItem={updateItem}
                onRemoveItem={removeItem}
                onOpenAddItem={() => setShowAddItem(true)}
              />
            ) : (
              <ShopkeeperCard
                shop={activeShop}
                chatMessages={chatMessages}
                isLoading={isLoading}
                onSendMessage={sendChatMessage}
              />
            )}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="px-4 py-3 border-t border-gray-700 flex justify-between items-center bg-gray-900/50 flex-shrink-0">
        {activeShop ? (
          <div className="text-xs text-gray-400">
            {activeShop.inventory.length} items |{' '}
            {activeShop.inventory.reduce((sum, i) => sum + i.price_gp * i.quantity, 0).toFixed(0)} gp total value
          </div>
        ) : (
          <div className="text-xs text-gray-400">
            {shops.length} shop{shops.length !== 1 ? 's' : ''} created
          </div>
        )}
        <button
          onClick={onClose}
          className="px-3 py-1.5 text-sm bg-gray-700 hover:bg-gray-600 rounded-lg transition-colors"
        >
          Close
        </button>
      </div>

      {/* Add Item Modal */}
      {showAddItem && (
        <AddItemModal
          onClose={() => setShowAddItem(false)}
          onAdd={addItem}
        />
      )}
    </div>
  );
}
