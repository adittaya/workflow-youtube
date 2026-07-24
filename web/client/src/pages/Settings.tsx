import { useState } from 'react';
import { api } from '../services/api';
import type { AppState } from '../hooks/useAppState';

interface Props {
  state: AppState;
  refresh: () => Promise<void>;
  toast: (msg: string, type?: 'success' | 'error' | 'info') => void;
}

export function SettingsPage({ state, refresh, toast }: Props) {
  const [supabaseUrl, setSupabaseUrl] = useState(state.settings.supabase_url || '');
  const [supabaseKey, setSupabaseKey] = useState(state.settings.supabase_key || '');
  const [supabaseSecret, setSupabaseSecret] = useState(state.settings.supabase_secret || '');
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    try {
      await api.saveSettings({
        supabase_url: supabaseUrl,
        supabase_key: supabaseKey,
        supabase_secret: supabaseSecret,
        active_account: state.settings.active_account,
      });
      toast('Settings saved', 'success');
      await refresh();
    } catch (e: any) {
      toast('Save failed: ' + e.message, 'error');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Settings</h1>
        <p className="text-sm text-gray-400 mt-1">Configure your Supabase proxy pool</p>
      </div>

      <div className="card space-y-4">
        <div>
          <label className="text-xs text-gray-400 mb-1.5 block">Supabase URL</label>
          <input
            className="input-field font-mono text-xs"
            placeholder="https://xxxxx.supabase.co"
            value={supabaseUrl}
            onChange={e => setSupabaseUrl(e.target.value)}
          />
        </div>
        <div>
          <label className="text-xs text-gray-400 mb-1.5 block">Supabase Anon Key</label>
          <input
            className="input-field font-mono text-xs"
            type="password"
            placeholder="eyJhbG..."
            value={supabaseKey}
            onChange={e => setSupabaseKey(e.target.value)}
          />
        </div>
        <div>
          <label className="text-xs text-gray-400 mb-1.5 block">Supabase Service Key</label>
          <input
            className="input-field font-mono text-xs"
            type="password"
            placeholder="eyJhbG..."
            value={supabaseSecret}
            onChange={e => setSupabaseSecret(e.target.value)}
          />
        </div>
        <div className="pt-2">
          <button className="btn-primary" onClick={handleSave} disabled={saving}>
            {saving ? 'Saving...' : 'Save Settings'}
          </button>
        </div>
      </div>

      <div className="card">
        <h3 className="text-sm font-semibold text-white mb-2">How it works</h3>
        <div className="space-y-2 text-xs text-gray-400">
          <p>1. Proxies are stored in a Supabase table called <code className="text-brand-400">proxies</code></p>
          <p>2. The automation fetches fresh proxies each rotation</p>
          <p>3. Dead proxies are blacklisted automatically</p>
          <p>4. One proxy IP per session (no mid-session rotation)</p>
        </div>
      </div>
    </div>
  );
}
