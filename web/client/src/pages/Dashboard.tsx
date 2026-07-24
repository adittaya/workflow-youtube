import { useState, useEffect, useCallback } from 'react';
import { api, formatStatus, timeAgo, type StatusDeployment } from '../services/api';
import type { AppState } from '../hooks/useAppState';

interface Props {
  state: AppState;
  refresh: () => Promise<void>;
  toast: (msg: string, type?: 'success' | 'error' | 'info') => void;
}

export function Dashboard({ state, refresh, toast }: Props) {
  const [statuses, setStatuses] = useState<StatusDeployment[]>([]);
  const [loading, setLoading] = useState(false);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  const activeAccount = state.activeAccount;
  const accounts = Object.values(state.accounts);

  const fetchStatus = useCallback(async () => {
    if (!activeAccount?.token) return;
    setLoading(true);
    try {
      const resp = await api.getStatus(activeAccount.token);
      setStatuses(resp.deployments || []);
      setLastRefresh(new Date());
    } catch {
    } finally {
      setLoading(false);
    }
  }, [activeAccount?.token]);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 30000);
    return () => clearInterval(interval);
  }, [fetchStatus]);

  const totalSuccesses = statuses.reduce((s, d) => s + d.total_successes, 0);
  const totalFails = statuses.reduce((s, d) => s + d.consecutive_fails, 0);
  const running = statuses.filter(d => d.status === 'in_progress' || d.status === 'queued').length;
  const withDest = statuses.filter(d => d.destination).length;

  const statCards = [
    { label: 'Deployments', value: statuses.length, icon: '⚡', color: 'from-brand-500/20 to-brand-600/10', border: 'border-brand-500/20' },
    { label: 'Destinations Hit', value: withDest, icon: '🎯', color: 'from-green-500/20 to-green-600/10', border: 'border-green-500/20' },
    { label: 'Running', value: running, icon: '◉', color: 'from-yellow-500/20 to-yellow-600/10', border: 'border-yellow-500/20' },
    { label: 'Consecutive Fails', value: totalFails, icon: '✕', color: totalFails > 0 ? 'from-red-500/20 to-red-600/10' : 'from-gray-500/20 to-gray-600/10', border: totalFails > 0 ? 'border-red-500/20' : 'border-gray-500/20' },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Dashboard</h1>
          <p className="text-sm text-gray-400 mt-1">VPLink automation control center</p>
        </div>
        <div className="flex items-center gap-3">
          {lastRefresh && (
            <span className="text-xs text-gray-500">Updated {timeAgo(lastRefresh.toISOString())}</span>
          )}
          <button
            onClick={fetchStatus}
            disabled={loading}
            className="btn-secondary text-xs"
          >
            {loading ? 'Refreshing...' : 'Refresh'}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {statCards.map(card => (
          <div key={card.label} className={`card bg-gradient-to-br ${card.color} ${card.border} animate-slide-up`}>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-gray-400 mb-1">{card.label}</p>
                <p className="text-2xl font-bold text-white">{card.value}</p>
              </div>
              <span className="text-2xl opacity-50">{card.icon}</span>
            </div>
          </div>
        ))}
      </div>

      {!activeAccount && accounts.length > 0 && (
        <div className="card border-yellow-500/20 bg-yellow-500/5">
          <div className="flex items-center gap-3">
            <span className="text-yellow-400 text-lg">⚠</span>
            <div>
              <p className="text-sm text-yellow-300 font-medium">No active account</p>
              <p className="text-xs text-gray-400">Go to Accounts and tap one to activate it</p>
            </div>
          </div>
        </div>
      )}

      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold text-white">Live Deployment Status</h2>
          {loading && <span className="text-xs text-gray-500 animate-pulse-soft">Scanning...</span>}
        </div>
        {statuses.length === 0 ? (
          <p className="text-sm text-gray-500 py-4 text-center">
            {activeAccount ? 'No deployments found on this account' : 'Add an account to see live status'}
          </p>
        ) : (
          <div className="space-y-2">
            {statuses.map(dep => {
              const sf = formatStatus(dep.status);
              const isRunning = dep.status === 'in_progress' || dep.status === 'queued';
              const hasFailed = dep.consecutive_fails > 0;
              return (
                <div key={dep.repo_name} className="flex items-center gap-3 p-3 rounded-xl bg-white/[0.03] hover:bg-white/[0.06] transition-colors touch-manipulation">
                  <div className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${
                    dep.destination ? 'bg-green-500' :
                    isRunning ? 'bg-yellow-500 animate-pulse' :
                    hasFailed ? 'bg-red-500' : 'bg-gray-500'
                  }`} />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-white truncate">{dep.repo_name}</span>
                      <span className={sf.className}>{sf.label}</span>
                    </div>
                    {dep.destination ? (
                      <p className="text-xs text-green-400 mt-0.5 truncate" title={dep.destination}>
                        → {dep.destination}
                      </p>
                    ) : (
                      <p className="text-xs text-gray-500 mt-0.5">
                        {dep.total_runs} runs · {dep.total_successes} success · {dep.consecutive_fails} fails
                      </p>
                    )}
                    <p className="text-xs text-gray-600 mt-0.5">
                      Last: {dep.last_run_at ? timeAgo(dep.last_run_at) : 'never'}
                      {dep.last_success_at && ` · Hit: ${timeAgo(dep.last_success_at)}`}
                    </p>
                  </div>
                  {dep.last_run_url && (
                    <a
                      href={dep.last_run_url}
                      target="_blank"
                      rel="noopener"
                      className="btn-icon flex-shrink-0"
                      onClick={e => e.stopPropagation()}
                      title="View last run on GitHub"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                      </svg>
                    </a>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {totalSuccesses > 0 && (
        <div className="card">
          <h2 className="text-sm font-semibold text-white mb-3">Destination History</h2>
          <div className="space-y-2">
            {statuses.filter(d => d.destination).map(dep => (
              <div key={dep.repo_name} className="flex items-center gap-3 p-2.5 rounded-xl bg-white/[0.02]">
                <div className="w-2 h-2 rounded-full bg-green-500 flex-shrink-0" />
                <span className="text-sm text-white flex-1 truncate">{dep.repo_name}</span>
                <span className="text-xs text-green-400 truncate max-w-[200px]" title={dep.destination}>
                  {dep.destination}
                </span>
                <span className="text-xs text-gray-500 flex-shrink-0">{dep.total_successes} hits</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
