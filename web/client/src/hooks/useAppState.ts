import { useState, useCallback, useEffect } from 'react';
import {
  api,
  type Account,
  type Deployment,
  type Settings,
  type DiscoveryDeployment,
} from '../services/api';

export type Screen = 'dashboard' | 'deployments' | 'accounts' | 'analytics' | 'settings' | 'sync';

export interface AppState {
  screen: Screen;
  accounts: Record<string, Account>;
  deployments: Record<string, Deployment>;
  settings: Settings;
  activeAccount: Account | null;
  discovery: DiscoveryDeployment[];
  syncing: boolean;
  loading: boolean;
  lastSync: string | null;
}

export function useAppState() {
  const [state, setState] = useState<AppState>({
    screen: 'dashboard',
    accounts: {},
    deployments: {},
    settings: {},
    activeAccount: null,
    discovery: [],
    syncing: false,
    loading: true,
    lastSync: null,
  });

  const loadAll = useCallback(async () => {
    try {
      const [accounts, deployments, settings] = await Promise.all([
        api.getAccounts(),
        api.getDeployments(),
        api.getSettings(),
      ]);
      const activeAccount = settings.active_account ? accounts[settings.active_account] || null : null;
      setState(prev => ({ ...prev, accounts, deployments, settings, activeAccount, loading: false }));
    } catch {
      setState(prev => ({ ...prev, loading: false }));
    }
  }, []);

  useEffect(() => { loadAll(); }, [loadAll]);

  const setScreen = useCallback((screen: Screen) => {
    setState(prev => ({ ...prev, screen }));
  }, []);

  const refresh = useCallback(async () => {
    await loadAll();
  }, [loadAll]);

  return { state, setScreen, refresh, loadAll };
}
