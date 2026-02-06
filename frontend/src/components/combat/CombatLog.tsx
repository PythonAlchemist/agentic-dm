import type { CombatLogEntry } from './types';

interface CombatLogProps {
  entries: CombatLogEntry[];
}

export function CombatLog({ entries }: CombatLogProps) {
  return (
    <div className="w-80 bg-gray-900/50 rounded-lg border border-gray-700 flex flex-col">
      <div className="px-3 py-2 border-b border-gray-700 text-sm font-medium text-gray-400">
        Combat Log
      </div>
      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {entries.length === 0 ? (
          <div className="text-center text-gray-500 text-sm py-4">
            NPC actions will appear here...
          </div>
        ) : (
          entries.map((entry) => (
            <CombatLogItem key={entry.id} entry={entry} />
          ))
        )}
      </div>
    </div>
  );
}

function CombatLogItem({ entry }: { entry: CombatLogEntry }) {
  if (entry.type === 'system') {
    return (
      <div className="text-center text-xs text-gray-400 py-1">
        {entry.message}
      </div>
    );
  }

  return (
    <div className="border-l-2 border-purple-500 pl-2 text-sm">
      {/* NPC Name */}
      <div className="font-bold text-purple-400 text-xs uppercase tracking-wide">
        {entry.npcName}
      </div>

      {/* Dialogue */}
      {entry.dialogue && (
        <div className="text-white">"{entry.dialogue}"</div>
      )}

      {/* Stage Directions */}
      <div className="text-xs mt-1 space-y-0.5 font-mono">
        {/* Movement */}
        {entry.movement && (
          <div className="text-blue-400">
            <span className="text-gray-500">Movement:</span> {entry.movement}
          </div>
        )}

        {/* Action */}
        {entry.action && (
          <div className="text-green-400">
            <span className="text-gray-500">Action:</span> {entry.action}
          </div>
        )}

        {/* Target */}
        {entry.target && (
          <div className="text-red-400">{entry.target}</div>
        )}

        {/* Result */}
        {entry.result && (
          <div className={entry.result.includes('Hit') ? 'text-yellow-400 font-bold' : 'text-gray-400'}>
            {entry.result}
          </div>
        )}
      </div>
    </div>
  );
}
