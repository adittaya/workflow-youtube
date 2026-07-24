import { useState, useEffect } from 'react';
import { api, formatStatus, timeAgo, type DiscoveryDeployment } from '../services/api';
import type { AppState } from '../hooks/useAppState';

interface Props {
  state: AppState;
  refresh: () => Promise<void>;
  toast: (msg: string, type?: 'success' | 'error' | 'info') => void;
}

export function Dashboard({ state, refresh, toast }: Props) {
  const [discovery, setDiscovery] = useState<DiscoveryDeployment[]>([]);
  const [loadingDiscovery, setLoadingDiscovery] = useState(false);

  const accounts = Object.values(state.accounts);
  const deployments = Object.values(state.deployments);
  const activeAccount = state.activeAccount;

  const statusCounts = deployments.reduce(
    (acc, d) => {
      const s = d.status;
      if (s === 'success') acc.success++;
      else if (s === 'in_progress') acc.running++;
      else if (s === 'failure' || s === 'error') acc.error++;
      else acc.other++;
      return acc;
    },
    { success: 0, running: 0, error: 0, other: 0 }
  );

  useEffect(() => {
    if (!activeAccount?.token) return;
    setLoadingDiscovery(true);
    api.discover(activeAccount.token)
      .then(setDiscovery)
      .catch(() => {})
      .finally(() => setLoadingDiscovery(false));
  }, [activeAccount?.token]);

  const statCards = [
    { label: 'Accounts', value: accounts.length, icon: '👤', color: 'from-blue-500/20 to-blue-600/10', border: 'border-blue-500/20' },
    { label: 'Deployments', value: deployments.length, icon: '⚡', color: 'from-brand-500/20 to-brand-600/10', border: 'border-brand-500/20' },
    { label: 'Running', value: statusCounts.running, icon: '◉', color: 'from-yellow-500/20 to-yellow-600/10', border: 'border-yellow-500/20' },
    { label: 'Errors', value: statusCounts.error, icon: '✕', color: 'from-red-500/20 to-red-600/10', border: 'border-red-500/20' },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Dashboard</h1>
        <p className="text-sm text-gray-400 mt-1">VPLink automation control center</p>
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
          {loadingDiscovery && <span className="text-xs text-gray-500 animate-pulse-soft">Scanning...</span>}
        </div>
        {discovery.length === 0 ? (
          <p className="text-sm text-gray-500 py-4 text-center">
            {activeAccount ? 'No deployments found on this account' : 'Add an account to see live status'}
          </p>
        ) : (
          <div className="space-y-2">
            {discovery.slice(0, 8).map(dep => {
              const sf = formatStatus(dep.status);
              return (
                <div key={dep.repo_name} className="flex items-center gap-3 p-3 rounded-xl bg-white/[0.03] hover:bg-white/[0.06] transition-colors touch-manipulation">
                  <div className={`w-2 h-2 rounded-full flex-shrink-0 ${dep.status === 'success' ? 'bg-green-500' : dep.status === 'in_progress' ? 'bg-yellow-500 animate-pulse' : 'bg-gray-500'}`} />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-white truncate">{dep.repo_name}</span>
                      <span className={sf.className}>{sf.label}</span>
                    </div>
                    <p className="text-xs text-gray-500 mt-0.5">
                      Key: {dep.key} · {dep.total_runs} runs · {dep.last_run ? timeAgo(dep.last_run.created_at) : 'no runs'}
                    </p>
                  </div>
                  <a
                    href={dep.repo_url}
                    target="_blank"
                    rel="noopener"
                    className="btn-icon flex-shrink-0"
                    onClick={e => e.stopPropagation()}
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                    </svg>
                  </a>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {deployments.length > 0 && (
        <div className="card">
          <h2 className="text-sm font-semibold text-white mb-3">Recent Deployments</h2>
          <div className="space-y-2">
            {deployments.slice(0, 5).map(dep => {
              const sf = formatStatus(dep.status);
              return (
                <div key={dep.name} className="flex items-center gap-3 p-2.5 rounded-xl bg-white/[0.02]">
                  <div className={`w-2 h-2 rounded-full ${dep.status === 'deployed' ? 'bg-blue-500' : dep.status === 'success' ? 'bg-green-500' : 'bg-gray-500'}`} />
                  <span className="text-sm text-white flex-1 truncate">{dep.name}</span>
                  <span className={sf.className}>{sf.label}</span>
                  <span className="text-xs text-gray-500">{timeAgo(dep.created_at)}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
