import { useState } from 'react';
import { api, timeAgo } from '../services/api';
import type { AppState } from '../hooks/useAppState';

interface Props {
  state: AppState;
  refresh: () => Promise<void>;
  toast: (msg: string, type?: 'success' | 'error' | 'info') => void;
}

export function SyncPage({ state, refresh, toast }: Props) {
  const [syncing, setSyncing] = useState(false);
  const [result, setResult] = useState<{ new: string[]; updated: string[]; total: number } | null>(null);

  const accounts = Object.values(state.accounts);

  const handleSync = async () => {
    setSyncing(true);
    setResult(null);
    try {
      const res = await api.sync();
      setResult(res);
      const parts: string[] = [];
      if (res.new.length > 0) parts.push(res.new.length + ' new');
      if (res.updated.length > 0) parts.push(res.updated.length + ' updated');
      toast(parts.length > 0 ? 'Synced: ' + parts.join(', ') : 'All up to date', 'success');
      await refresh();
    } catch (e: any) {
      toast('Sync failed: ' + e.message, 'error');
    } finally {
      setSyncing(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">GitHub Sync</h1>
        <p className="text-sm text-gray-400 mt-1">Real-time deployment discovery from GitHub</p>
      </div>

      <div className="card">
        <div className="text-center py-6">
          <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-brand-400 to-brand-600 flex items-center justify-center text-3xl mx-auto mb-4 shadow-xl shadow-brand-500/30">
            ↻
          </div>
          <h3 className="text-lg font-semibold text-white mb-2">Sync from GitHub</h3>
          <p className="text-sm text-gray-400 mb-6">
            Scans all vplink-* repos across your accounts.
            <br />GitHub repos ARE the database.
          </p>
          <button
            className="btn-primary text-base px-8 py-3"
            onClick={handleSync}
            disabled={syncing || accounts.length === 0}
          >
            {syncing ? (
              <><span className="animate-spin">↻</span> Syncing...</>
            ) : (
              'Sync Now'
            )}
          </button>
          {accounts.length === 0 && (
            <p className="text-xs text-gray-500 mt-3">Add an account first</p>
          )}
        </div>
      </div>

      {result && (
        <div className="card animate-slide-up">
          <h3 className="text-sm font-semibold text-white mb-3">Last Sync Result</h3>
          <div className="grid grid-cols-3 gap-3 mb-4">
            <div className="text-center p-3 rounded-xl bg-white/[0.03]">
              <p className="text-2xl font-bold text-white">{result.total}</p>
              <p className="text-xs text-gray-400">Total</p>
            </div>
            <div className="text-center p-3 rounded-xl bg-green-500/10">
              <p className="text-2xl font-bold text-green-400">{result.new.length}</p>
              <p className="text-xs text-gray-400">New</p>
            </div>
            <div className="text-center p-3 rounded-xl bg-blue-500/10">
              <p className="text-2xl font-bold text-blue-400">{result.updated.length}</p>
              <p className="text-xs text-gray-400">Updated</p>
            </div>
          </div>
          {result.new.length > 0 && (
            <div>
              <p className="text-xs text-gray-400 mb-2">New repos discovered:</p>
              <div className="space-y-1">
                {result.new.map(name => (
                  <div key={name} className="flex items-center gap-2 text-sm p-2 rounded-lg bg-green-500/5 border border-green-500/10">
                    <span className="text-green-400">+</span>
                    <span className="text-white">{name}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      <div className="card">
        <h3 className="text-sm font-semibold text-white mb-3">How Sync Works</h3>
        <div className="space-y-3 text-xs text-gray-400">
          <div className="flex items-start gap-3">
            <span className="w-6 h-6 rounded-lg bg-brand-500/20 text-brand-400 flex items-center justify-center flex-shrink-0 text-xs font-bold">1</span>
            <p>Scans all GitHub repos matching <code className="text-brand-400">vplink-*</code> across your accounts</p>
          </div>
          <div className="flex items-start gap-3">
            <span className="w-6 h-6 rounded-lg bg-brand-500/20 text-brand-400 flex items-center justify-center flex-shrink-0 text-xs font-bold">2</span>
            <p>Checks each repo's latest workflow run for status</p>
          </div>
          <div className="flex items-start gap-3">
            <span className="w-6 h-6 rounded-lg bg-brand-500/20 text-brand-400 flex items-center justify-center flex-shrink-0 text-xs font-bold">3</span>
            <p>Reads the VPLINK_KEY variable from each repo</p>
          </div>
          <div className="flex items-start gap-3">
            <span className="w-6 h-6 rounded-lg bg-brand-500/20 text-brand-400 flex items-center justify-center flex-shrink-0 text-xs font-bold">4</span>
            <p>Merges with local cache - new repos auto-imported, existing ones updated</p>
          </div>
        </div>
      </div>
    </div>
  );
}
