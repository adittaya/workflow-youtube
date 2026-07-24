const BASE = '/api';

async function request<T = any>(path: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ error: resp.statusText }));
    throw new Error(err.error || resp.statusText);
  }
  return resp.json();
}

export interface Account {
  name: string;
  token: string;
  username?: string;
}

export interface Deployment {
  name: string;
  key: string;
  account: string;
  repo_url: string;
  status: string;
  created_at: string;
}

export interface Settings {
  supabase_url?: string;
  supabase_key?: string;
  supabase_secret?: string;
  active_account?: string;
}

export interface WorkflowRun {
  id: number;
  name: string;
  status: string;
  conclusion: string | null;
  created_at: string;
  html_url: string;
  run_number: number;
}

export interface DiscoveryDeployment {
  repo_name: string;
  owner: string;
  key: string;
  status: string;
  repo_url: string;
  last_run: WorkflowRun | null;
  total_runs: number;
  is_public: boolean;
}

export const api = {
  health: () => request<{ ok: boolean; version: string }>('/health'),

  getAccounts: () => request<Record<string, Account>>('/accounts'),
  addAccount: (name: string, token: string) =>
    request<{ ok: boolean; username: string; scopes: string[] }>('/accounts', {
      method: 'POST', body: JSON.stringify({ name, token }),
    }),
  removeAccount: (name: string) =>
    request('/accounts', { method: 'DELETE', body: JSON.stringify({ name }) }),
  setActiveAccount: (name: string) =>
    request('/accounts/active', { method: 'POST', body: JSON.stringify({ name }) }),

  getSettings: () => request<Settings>('/settings'),
  saveSettings: (s: Settings) =>
    request('/settings', { method: 'POST', body: JSON.stringify(s) }),

  getDeployments: () => request<Record<string, Deployment>>('/deployments'),
  deploy: (name: string, key: string) =>
    request<Deployment>('/deploy', { method: 'POST', body: JSON.stringify({ name, key }) }),
  removeDeployment: (name: string) =>
    request('/deploy/remove', { method: 'POST', body: JSON.stringify({ name }) }),
  nukeAll: () =>
    request<{ deleted: number; errors: string[] }>('/deploy/nuke', { method: 'POST' }),

  sync: () =>
    request<{ new: string[]; updated: string[]; total: number }>('/sync', { method: 'POST' }),

  discover: (token: string) =>
    request<DiscoveryDeployment[]>(`/github/discover?token=${encodeURIComponent(token)}`),
  getWorkflow: (token: string, owner: string, repo: string) =>
    request<{ id: number; state: string; name: string } | { error: string }>(
      `/github/workflow?token=${encodeURIComponent(token)}&owner=${owner}&repo=${repo}`
    ),
  getRuns: (token: string, owner: string, repo: string) =>
    request<WorkflowRun[]>(`/github/runs?token=${encodeURIComponent(token)}&owner=${owner}&repo=${repo}`),
  getLog: (token: string, owner: string, repo: string, runId: number) =>
    request<{ logs: string[]; destination: string }>(
      `/github/log?token=${encodeURIComponent(token)}&owner=${owner}&repo=${repo}&run_id=${runId}`
    ),
  downloadLog: (token: string, owner: string, repo: string, runId: number) =>
    request<{ log: string }>(
      `/github/log/download?token=${encodeURIComponent(token)}&owner=${owner}&repo=${repo}&run_id=${runId}`
    ),
};

export function formatStatus(status: string): { color: string; label: string; className: string } {
  switch (status) {
    case 'success': return { color: '#22c55e', label: 'Success', className: 'badge-success' };
    case 'in_progress': case 'queued': case 'pending':
      return { color: '#eab308', label: status, className: 'badge-warning' };
    case 'error': case 'failure':
      return { color: '#ef4444', label: status, className: 'badge-error' };
    case 'stopped': return { color: '#6b7280', label: 'Stopped', className: 'badge-neutral' };
    case 'deployed': return { color: '#3b82f6', label: 'Deployed', className: 'badge-info' };
    default: return { color: '#9ca3af', label: status, className: 'badge-neutral' };
  }
}

export function timeAgo(ts: string | null): string {
  if (!ts) return 'never';
  const diff = Date.now() - new Date(ts).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}
