import { useState } from 'react';
import { api, formatStatus, timeAgo } from '../services/api';
import type { AppState } from '../hooks/useAppState';

interface Props {
  state: AppState;
  refresh: () => Promise<void>;
  toast: (msg: string, type?: 'success' | 'error' | 'info') => void;
}

export function Deployments({ state, refresh, toast }: Props) {
  const [showDeploy, setShowDeploy] = useState(false);
  const [showNuke, setShowNuke] = useState(false);
  const [repoName, setRepoName] = useState('');
  const [vplinkKey, setVplinkKey] = useState('');
  const [deploying, setDeploying] = useState(false);
  const [removing, setRemoving] = useState<string | null>(null);
  const [nuking, setNuking] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);

  const deployments = Object.values(state.deployments);
  const activeAccount = state.activeAccount;

  const handleDeploy = async () => {
    if (!vplinkKey.trim()) { toast('VPLINK_KEY is required', 'error'); return; }
    setDeploying(true);
    try {
      const dep = await api.deploy(repoName, vplinkKey);
      toast('Deployed ' + dep.name, 'success');
      setShowDeploy(false);
      setRepoName('');
      setVplinkKey('');
      await refresh();
    } catch (e: any) {
      toast('Deploy failed: ' + e.message, 'error');
    } finally {
      setDeploying(false);
    }
  };

  const handleRemove = async (name: string) => {
    setRemoving(name);
    try {
      await api.removeDeployment(name);
      toast('Removed ' + name, 'success');
      setSelected(null);
      await refresh();
    } catch (e: any) {
      toast('Remove failed: ' + e.message, 'error');
    } finally {
      setRemoving(null);
    }
  };

  const handleNuke = async () => {
    setNuking(true);
    try {
      const result = await api.nukeAll();
      toast('Nuked: ' + result.deleted + ' repos deleted', 'success');
      setShowNuke(false);
      setSelected(null);
      await refresh();
    } catch (e: any) {
      toast('Nuke failed: ' + e.message, 'error');
    } finally {
      setNuking(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Deployments</h1>
          <p className="text-sm text-gray-400 mt-1">{deployments.length} active</p>
        </div>
        <div className="flex gap-2">
          {deployments.length > 0 && (
            <button className="btn-danger text-xs" onClick={() => setShowNuke(true)}>Nuke All</button>
          )}
          <button className="btn-primary" onClick={() => setShowDeploy(true)} disabled={!activeAccount}>+ Deploy</button>
        </div>
      </div>

      {!activeAccount && (
        <div className="card border-yellow-500/20 bg-yellow-500/5">
          <p className="text-sm text-yellow-300">Add and select an account first</p>
        </div>
      )}

      {deployments.length === 0 ? (
        <div className="card text-center py-12">
          <span className="text-4xl mb-3 block opacity-30">⚡</span>
          <p className="text-gray-400 text-sm">No deployments yet</p>
          <button className="btn-primary mt-4" onClick={() => setShowDeploy(true)} disabled={!activeAccount}>
            Deploy your first instance
          </button>
        </div>
      ) : (
        <div className="space-y-2">
          {deployments.map(dep => {
            const sf = formatStatus(dep.status);
            return (
              <div
                key={dep.name}
                className="card flex items-center gap-4 cursor-pointer hover:bg-white/[0.07] transition-all touch-manipulation"
                onClick={() => setSelected(dep.name)}
              >
                <div className={`w-3 h-3 rounded-full flex-shrink-0 ${
                  dep.status === 'success' ? 'bg-green-500' :
                  dep.status === 'deployed' ? 'bg-blue-500 animate-pulse-soft' :
                  dep.status === 'failure' ? 'bg-red-500' : 'bg-gray-500'
                }`} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-medium text-white">{dep.name}</span>
                    <span className={sf.className}>{sf.label}</span>
                  </div>
                  <p className="text-xs text-gray-500 mt-0.5">
                    Key: {dep.key} · {dep.account} · {timeAgo(dep.created_at)}
                  </p>
                </div>
                <svg className="w-4 h-4 text-gray-500 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                </svg>
              </div>
            );
          })}
        </div>
      )}

      {showDeploy && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4 animate-fade-in" onClick={() => !deploying && setShowDeploy(false)}>
          <div className="glass rounded-2xl p-6 w-full max-w-md animate-scale-in" onClick={e => e.stopPropagation()}>
            <h3 className="text-lg font-semibold text-white mb-4">New Deployment</h3>
            <div className="space-y-4">
              <div>
                <label className="text-xs text-gray-400 mb-1.5 block">Repository name (optional)</label>
                <input className="input-field" placeholder="auto-generated if empty" value={repoName} onChange={e => setRepoName(e.target.value)} disabled={deploying} />
              </div>
              <div>
                <label className="text-xs text-gray-400 mb-1.5 block">VPLINK_KEY *</label>
                <input className="input-field" placeholder="e.g. UbpV2D" value={vplinkKey} onChange={e => setVplinkKey(e.target.value)} disabled={deploying} autoFocus />
              </div>
              <div className="flex gap-2 justify-end">
                <button className="btn-ghost" onClick={() => setShowDeploy(false)} disabled={deploying}>Cancel</button>
                <button className="btn-primary" onClick={handleDeploy} disabled={deploying || !vplinkKey.trim()}>
                  {deploying ? 'Deploying...' : 'Deploy'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {showNuke && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4 animate-fade-in" onClick={() => !nuking && setShowNuke(false)}>
          <div className="glass rounded-2xl p-6 w-full max-w-md animate-scale-in border-red-500/20" onClick={e => e.stopPropagation()}>
            <h3 className="text-lg font-semibold text-white mb-2">Nuke All Deployments</h3>
            <p className="text-sm text-gray-400 mb-4">This will delete ALL {deployments.length} repos from GitHub. Cannot be undone.</p>
            <div className="flex gap-2 justify-end">
              <button className="btn-ghost" onClick={() => setShowNuke(false)} disabled={nuking}>Cancel</button>
              <button className="btn-danger" onClick={handleNuke} disabled={nuking}>
                {nuking ? 'Nuking...' : 'Delete ' + deployments.length + ' repos'}
              </button>
            </div>
          </div>
        </div>
      )}

      {selected && state.deployments[selected] && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4 animate-fade-in" onClick={() => setSelected(null)}>
          <div className="glass rounded-2xl p-6 w-full max-w-md animate-scale-in" onClick={e => e.stopPropagation()}>
            <h3 className="text-lg font-semibold text-white mb-3">{selected}</h3>
            <div className="space-y-3 mb-4">
              <a href={state.deployments[selected].repo_url} target="_blank" rel="noopener" className="btn-ghost w-full text-left text-sm">View Repository</a>
              <div className="p-3 rounded-xl bg-white/[0.03]">
                <p className="text-xs text-gray-400">VPLINK_KEY</p>
                <p className="text-sm text-white font-mono">{state.deployments[selected].key}</p>
              </div>
              <div className="p-3 rounded-xl bg-white/[0.03]">
                <p className="text-xs text-gray-400">Account</p>
                <p className="text-sm text-white">{state.deployments[selected].account}</p>
              </div>
            </div>
            <div className="flex gap-2 justify-end">
              <button className="btn-ghost" onClick={() => setSelected(null)}>Close</button>
              <button className="btn-danger" onClick={() => handleRemove(selected)} disabled={removing === selected}>
                {removing === selected ? 'Removing...' : 'Remove'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
