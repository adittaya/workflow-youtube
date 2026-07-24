import { useState } from 'react';
import { api } from '../services/api';
import type { AppState } from '../hooks/useAppState';

interface Props {
  state: AppState;
  refresh: () => Promise<void>;
  toast: (msg: string, type?: 'success' | 'error' | 'info') => void;
}

export function Accounts({ state, refresh, toast }: Props) {
  const [showAdd, setShowAdd] = useState(false);
  const [acctName, setAcctName] = useState('');
  const [acctToken, setAcctToken] = useState('');
  const [adding, setAdding] = useState(false);
  const [removing, setRemoving] = useState<string | null>(null);
  const [search, setSearch] = useState('');

  const accounts = Object.values(state.accounts);
  const active = state.activeAccount?.name;
  const filtered = accounts.filter(a =>
    !search || a.name.toLowerCase().includes(search.toLowerCase()) ||
    (a.username || '').toLowerCase().includes(search.toLowerCase())
  );

  const handleAdd = async () => {
    if (!acctName.trim() || !acctToken.trim()) {
      toast('Name and token required', 'error');
      return;
    }
    setAdding(true);
    try {
      const result = await api.addAccount(acctName.trim(), acctToken.trim());
      const warnings: string[] = [];
      if (!result.scopes.some(s => s.includes('repo'))) warnings.push('missing repo scope');
      if (!result.scopes.some(s => s.includes('workflow'))) warnings.push('missing workflow scope');
      const msg = 'Added ' + acctName + ' (@' + result.username + ')' + (warnings.length ? ' — ' + warnings.join(', ') : '');
      toast(msg, warnings.length ? 'info' : 'success');
      if (!active) {
        await api.setActiveAccount(acctName.trim());
      }
      setShowAdd(false);
      setAcctName('');
      setAcctToken('');
      await refresh();
    } catch (e: any) {
      toast('Add failed: ' + e.message, 'error');
    } finally {
      setAdding(false);
    }
  };

  const handleSelect = async (name: string) => {
    try {
      await api.setActiveAccount(name);
      toast('Switched to ' + name, 'success');
      await refresh();
    } catch (e: any) {
      toast('Switch failed: ' + e.message, 'error');
    }
  };

  const handleRemove = async (e: React.MouseEvent, name: string) => {
    e.stopPropagation();
    if (!name) return;
    setRemoving(name);
    try {
      await api.removeAccount(name);
      toast('Removed ' + name, 'success');
      await refresh();
    } catch (e: any) {
      toast('Remove failed: ' + e.message, 'error');
    } finally {
      setRemoving(null);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Accounts</h1>
          <p className="text-sm text-gray-400 mt-1">{accounts.length} account{accounts.length !== 1 ? 's' : ''}</p>
        </div>
        <button className="btn-primary" onClick={() => setShowAdd(true)}>+ Add Account</button>
      </div>

      {accounts.length > 2 && (
        <div className="relative">
          <input
            className="input-field pl-9"
            placeholder="Search accounts..."
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
        </div>
      )}

      {accounts.length === 0 ? (
        <div className="card text-center py-12">
          <span className="text-4xl mb-3 block opacity-30">👤</span>
          <p className="text-gray-400 text-sm">No accounts added yet</p>
          <p className="text-gray-600 text-xs mt-1">Add your GitHub account to start managing deployments</p>
          <button className="btn-primary mt-4" onClick={() => setShowAdd(true)}>Add your first account</button>
        </div>
      ) : filtered.length === 0 ? (
        <div className="card text-center py-8">
          <p className="text-gray-500 text-sm">No accounts matching "{search}"</p>
        </div>
      ) : (
        <div className="space-y-2">
          {filtered.map(acct => (
            <div
              key={acct.name}
              className={`card flex items-center gap-4 cursor-pointer transition-all touch-manipulation ${
                active === acct.name ? 'border-brand-500/30 bg-brand-500/5' : 'hover:bg-white/[0.07]'
              }`}
              onClick={() => handleSelect(acct.name)}
            >
              <div className={`w-10 h-10 rounded-xl flex items-center justify-center text-sm font-bold ${
                active === acct.name
                  ? 'bg-gradient-to-br from-brand-400 to-brand-600 text-white shadow-lg shadow-brand-500/30'
                  : 'bg-white/10 text-gray-400'
              }`}>
                {(acct.username || acct.name).charAt(0).toUpperCase()}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-white">{acct.name}</span>
                  {active === acct.name && <span className="badge-success text-[10px]">Active</span>}
                </div>
                <p className="text-xs text-gray-500">
                  @{acct.username || 'unknown'} · {acct.token.slice(0, 8)}...{acct.token.slice(-4)}
                </p>
              </div>
              <button
                className="btn-icon text-red-400 hover:text-red-300"
                onClick={e => handleRemove(e, acct.name)}
                disabled={removing === acct.name}
              >
                {removing === acct.name ? '...' : (
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                  </svg>
                )}
              </button>
            </div>
          ))}
        </div>
      )}

      {showAdd && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4 animate-fade-in" onClick={() => !adding && setShowAdd(false)}>
          <div className="glass rounded-2xl p-6 w-full max-w-md animate-scale-in" onClick={e => e.stopPropagation()}>
            <h3 className="text-lg font-semibold text-white mb-4">Add GitHub Account</h3>
            <div className="space-y-4">
              <div>
                <label className="text-xs text-gray-400 mb-1.5 block">Account name</label>
                <input className="input-field" placeholder="e.g. main, alt, work" value={acctName} onChange={e => setAcctName(e.target.value)} disabled={adding} autoFocus />
              </div>
              <div>
                <label className="text-xs text-gray-400 mb-1.5 block">GitHub Personal Access Token</label>
                <input className="input-field font-mono" type="password" placeholder="ghp_..." value={acctToken} onChange={e => setAcctToken(e.target.value)} disabled={adding} />
              </div>
              <p className="text-xs text-gray-500">Token needs repo + workflow scopes</p>
              <div className="flex gap-2 justify-end">
                <button className="btn-ghost" onClick={() => setShowAdd(false)} disabled={adding}>Cancel</button>
                <button className="btn-primary" onClick={handleAdd} disabled={adding || !acctName.trim() || !acctToken.trim()}>
                  {adding ? 'Validating...' : 'Add Account'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
