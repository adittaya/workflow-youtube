import { useState, useCallback } from 'react';
import { useAppState, type Screen } from './hooks/useAppState';
import { useToast, ToastContainer } from './hooks/useToast';
import { Dashboard } from './pages/Dashboard';
import { Deployments } from './pages/Deployments';
import { Accounts } from './pages/Accounts';
import { Analytics } from './pages/Analytics';
import { SettingsPage } from './pages/Settings';
import { SyncPage } from './pages/Sync';

const NAV_ITEMS: { id: Screen; icon: string; label: string; shortcut: string }[] = [
  { id: 'dashboard', icon: '◉', label: 'Dashboard', shortcut: '1' },
  { id: 'deployments', icon: '⚡', label: 'Deployments', shortcut: '2' },
  { id: 'accounts', icon: '👤', label: 'Accounts', shortcut: '3' },
  { id: 'analytics', icon: '📊', label: 'Analytics', shortcut: '4' },
  { id: 'settings', icon: '⚙', label: 'Settings', shortcut: '5' },
  { id: 'sync', icon: '↻', label: 'Sync', shortcut: '6' },
];

export function App() {
  const { state, setScreen, refresh } = useAppState();
  const { toasts, addToast, removeToast } = useToast();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const handleNav = useCallback((screen: Screen) => {
    setScreen(screen);
    setSidebarOpen(false);
  }, [setScreen]);

  const toast = useCallback((msg: string, type?: 'success' | 'error' | 'info') => {
    addToast(msg, type);
  }, [addToast]);

  const renderScreen = () => {
    const props = { state, refresh, toast };
    switch (state.screen) {
      case 'dashboard': return <Dashboard {...props} />;
      case 'deployments': return <Deployments {...props} />;
      case 'accounts': return <Accounts {...props} />;
      case 'analytics': return <Analytics {...props} />;
      case 'settings': return <SettingsPage {...props} />;
      case 'sync': return <SyncPage {...props} />;
      default: return <Dashboard {...props} />;
    }
  };

  return (
    <div className="h-screen w-screen flex flex-col bg-gray-950 overflow-hidden">
      <ToastContainer toasts={toasts} onRemove={removeToast} />

      {/* Header */}
      <header className="flex-shrink-0 h-14 glass border-b border-white/10 flex items-center px-4 gap-3 z-30">
        <button
          className="btn-icon lg:hidden"
          onClick={() => setSidebarOpen(!sidebarOpen)}
          aria-label="Toggle menu"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            {sidebarOpen
              ? <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              : <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />}
          </svg>
        </button>
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-brand-400 to-brand-600 flex items-center justify-center text-white font-bold text-sm shadow-lg shadow-brand-500/30">
            V
          </div>
          <span className="font-semibold text-white text-sm hidden sm:block">VPLink</span>
          <span className="text-xs text-gray-500 hidden sm:block">v3.0</span>
        </div>
        <div className="flex-1" />
        <div className="flex items-center gap-4 text-xs text-gray-400">
          <span className="hidden sm:flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse-soft" />
            {Object.keys(state.accounts).length} accounts
          </span>
          <span className="hidden sm:flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-brand-400" />
            {Object.keys(state.deployments).length} deploys
          </span>
          {state.activeAccount && (
            <span className="badge-info hidden md:inline-flex">
              @{state.activeAccount.username || state.activeAccount.name}
            </span>
          )}
        </div>
      </header>

      <div className="flex-1 flex overflow-hidden">
        {/* Mobile overlay */}
        {sidebarOpen && (
          <div
            className="fixed inset-0 bg-black/50 z-30 lg:hidden animate-fade-in"
            onClick={() => setSidebarOpen(false)}
          />
        )}

        {/* Sidebar */}
        <aside className={`
          fixed lg:static inset-y-0 left-0 z-40 w-60 pt-14 lg:pt-0
          glass border-r border-white/10 flex flex-col py-3 px-2
          transform transition-transform duration-300 ease-out
          ${sidebarOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'}
        `}>
          <nav className="flex-1 flex flex-col gap-1 mt-2 lg:mt-0">
            {NAV_ITEMS.map(item => (
              <button
                key={item.id}
                className={state.screen === item.id ? 'nav-item-active' : 'nav-item'}
                onClick={() => handleNav(item.id)}
              >
                <span className="text-lg w-6 text-center">{item.icon}</span>
                <span className="flex-1 text-left">{item.label}</span>
                <kbd className="hidden lg:inline text-[10px] text-gray-600 bg-white/5 px-1.5 py-0.5 rounded">
                  {item.shortcut}
                </kbd>
              </button>
            ))}
          </nav>
          <div className="mt-auto pt-3 border-t border-white/5">
            <button className="btn-ghost w-full text-xs text-gray-500" onClick={() => window.location.reload()}>
              ↻ Refresh
            </button>
          </div>
        </aside>

        {/* Main content */}
        <main className="flex-1 overflow-y-auto p-4 sm:p-6 lg:p-8">
          <div className="max-w-6xl mx-auto animate-fade-in">
            {renderScreen()}
          </div>
        </main>
      </div>
    </div>
  );
}
