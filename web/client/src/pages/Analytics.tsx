import { useMemo } from 'react';
import type { AppState } from '../hooks/useAppState';

interface Props {
  state: AppState;
  refresh: () => Promise<void>;
  toast: (msg: string, type?: 'success' | 'error' | 'info') => void;
}

export function Analytics({ state }: Props) {
  const deployments = Object.values(state.deployments);
  const accounts = Object.values(state.accounts);

  const statusCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    deployments.forEach(d => { counts[d.status] = (counts[d.status] || 0) + 1; });
    return counts;
  }, [deployments]);

  const accountCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    deployments.forEach(d => { counts[d.account] = (counts[d.account] || 0) + 1; });
    return counts;
  }, [deployments]);

  const maxStatus = Math.max(...Object.values(statusCounts), 1);
  const maxAcct = Math.max(...Object.values(accountCounts), 1);

  const statusColors: Record<string, string> = {
    success: 'bg-green-500',
    deployed: 'bg-blue-500',
    failure: 'bg-red-500',
    error: 'bg-red-500',
    in_progress: 'bg-yellow-500',
    no_runs: 'bg-gray-500',
    unknown: 'bg-gray-600',
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Analytics</h1>
        <p className="text-sm text-gray-400 mt-1">Status breakdown across all deployments</p>
      </div>

      <div className="card">
        <h2 className="text-sm font-semibold text-white mb-4">Status Breakdown</h2>
        {Object.keys(statusCounts).length === 0 ? (
          <p className="text-sm text-gray-500 py-4 text-center">No data to show</p>
        ) : (
          <div className="space-y-3">
            {Object.entries(statusCounts).sort((a, b) => b[1] - a[1]).map(([status, count]) => (
              <div key={status} className="flex items-center gap-3">
                <span className="text-xs text-gray-400 w-24 text-right capitalize">{status}</span>
                <div className="flex-1 h-6 bg-white/5 rounded-lg overflow-hidden">
                  <div
                    className={`h-full rounded-lg ${statusColors[status] || 'bg-gray-500'} transition-all duration-500`}
                    style={{ width: `${(count / maxStatus) * 100}%` }}
                  />
                </div>
                <span className="text-xs text-gray-300 w-8 text-right font-mono">{count}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="card">
        <h2 className="text-sm font-semibold text-white mb-4">Per-Account Deployments</h2>
        {accounts.length === 0 ? (
          <p className="text-sm text-gray-500 py-4 text-center">No accounts configured</p>
        ) : (
          <div className="space-y-3">
            {accounts.map(acct => {
              const count = accountCounts[acct.name] || 0;
              return (
                <div key={acct.name} className="flex items-center gap-3">
                  <span className="text-xs text-gray-400 w-24 text-right truncate">{acct.username || acct.name}</span>
                  <div className="flex-1 h-6 bg-white/5 rounded-lg overflow-hidden">
                    <div
                      className="h-full rounded-lg bg-brand-500 transition-all duration-500"
                      style={{ width: `${maxAcct > 0 ? (count / maxAcct) * 100 : 0}%` }}
                    />
                  </div>
                  <span className="text-xs text-gray-300 w-8 text-right font-mono">{count}</span>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="card text-center">
          <p className="text-3xl font-bold text-white">{deployments.length}</p>
          <p className="text-xs text-gray-400 mt-1">Total Deployments</p>
        </div>
        <div className="card text-center">
          <p className="text-3xl font-bold text-white">{accounts.length}</p>
          <p className="text-xs text-gray-400 mt-1">Total Accounts</p>
        </div>
      </div>
    </div>
  );
}
