import {
  ACCOUNTS_FILE,
  DEPLOYMENTS_FILE,
  SETTINGS_FILE,
  loadJson,
  saveJson,
  DATA_DIR,
} from "../utils/storage";
import {
  GitHubAccount,
  discoverDeployments,
  getAccountInfo,
  validateToken,
  createRepo,
  deleteRepo,
  DeploymentInfo,
} from "./github";
import { execSync } from "child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "fs";

export interface LocalDeployment {
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

export function loadAccounts(): Record<string, GitHubAccount> {
  return loadJson(ACCOUNTS_FILE);
}

export function saveAccounts(accounts: Record<string, GitHubAccount>) {
  saveJson(ACCOUNTS_FILE, accounts);
}

export function loadDeployments(): Record<string, LocalDeployment> {
  return loadJson(DEPLOYMENTS_FILE);
}

export function saveDeployments(deps: Record<string, LocalDeployment>) {
  saveJson(DEPLOYMENTS_FILE, deps);
}

export function loadSettings(): Settings {
  return loadJson(SETTINGS_FILE);
}

export function saveSettings(settings: Settings) {
  saveJson(SETTINGS_FILE, settings);
}

export function getActiveAccount(): GitHubAccount | null {
  const settings = loadSettings();
  const accounts = loadAccounts();
  if (!settings.active_account) return null;
  return accounts[settings.active_account] || null;
}

export async function addAccount(
  name: string,
  token: string
): Promise<{ username: string; scopes: string[] }> {
  const { username, scopes } = await validateToken(token);
  const accounts = loadAccounts();
  accounts[name] = { name, token, username };
  saveAccounts(accounts);
  return { username, scopes };
}

export function removeAccount(name: string): boolean {
  const accounts = loadAccounts();
  if (!accounts[name]) return false;
  delete accounts[name];
  saveAccounts(accounts);
  const settings = loadSettings();
  if (settings.active_account === name) {
    settings.active_account = undefined;
    saveSettings(settings);
  }
  return true;
}

export function switchAccount(name: string): boolean {
  const accounts = loadAccounts();
  if (!accounts[name]) return false;
  const settings = loadSettings();
  settings.active_account = name;
  saveSettings(settings);
  return true;
}

export async function syncFromGitHub(): Promise<{
  accounts: Record<string, GitHubAccount>;
  deployments: Record<string, LocalDeployment>;
  newRepos: string[];
  updatedRepos: string[];
}> {
  const accounts = loadAccounts();
  const existingDeps = loadDeployments();
  const newRepos: string[] = [];
  const updatedRepos: string[] = [];

  for (const [name, acct] of Object.entries(accounts)) {
    try {
      const { username } = await getAccountInfo(acct.token);
      acct.username = username;
    } catch {
      continue;
    }

    try {
      const remoteDeps = await discoverDeployments(acct.token);
      for (const dep of remoteDeps) {
        if (existingDeps[dep.repo_name]) {
          existingDeps[dep.repo_name].status = dep.status;
          existingDeps[dep.repo_name].account = name;
          updatedRepos.push(dep.repo_name);
        } else {
          existingDeps[dep.repo_name] = {
            name: dep.repo_name,
            key: dep.key,
            account: name,
            repo_url: dep.repo_url,
            status: dep.status,
            created_at: new Date().toISOString(),
          };
          newRepos.push(dep.repo_name);
        }
      }
    } catch {
      continue;
    }
  }

  saveAccounts(accounts);
  saveDeployments(existingDeps);

  return { accounts, deployments: existingDeps, newRepos, updatedRepos };
}

export async function deployNew(
  name: string | null,
  key: string
): Promise<LocalDeployment> {
  const acct = getActiveAccount();
  if (!acct) throw new Error("No active account. Add one first.");

  const repoName = name || `vplink-${Date.now().toString(36)}`;
  const fullRepoName = repoName.startsWith("vplink-")
    ? repoName
    : `vplink-${repoName}`;

  const result = await createRepo(fullRepoName, acct.token, true);

  const templateDir = `${DATA_DIR}/template`;
  if (!existsSync(templateDir)) {
    execSync(
      `git clone --depth 1 https://github.com/adittaya/workflow-vplink.git "${templateDir}"`,
      { stdio: "ignore" }
    );
  }

  const repoDir = `${DATA_DIR}/repos/${fullRepoName}`;
  mkdirSync(`${DATA_DIR}/repos`, { recursive: true });

  execSync(`rm -rf "${repoDir}" && cp -r "${templateDir}" "${repoDir}"`, {
    stdio: "ignore",
  });

  const settings = loadSettings();
  const secrets: Record<string, string> = {
    VPLINK_KEY: key,
  };
  if (settings.supabase_url) secrets.SUPABASE_URL = settings.supabase_url;
  if (settings.supabase_key) secrets.SUPABASE_KEY = settings.supabase_key;
  if (settings.supabase_secret)
    secrets.SUPABASE_SECRET = settings.supabase_secret;

  const owner = acct.username || acct.name;
  try {
    execSync(
      `cd "${repoDir}" && git init -b main && git remote add origin https://${acct.token}@github.com/${owner}/${fullRepoName}.git && git add -A && git commit -m "init: vplink automation relay" && git push --force origin main`,
      { stdio: "ignore" }
    );
  } catch {
    /* continue anyway */
  }

  const dep: LocalDeployment = {
    name: fullRepoName,
    key,
    account: acct.name,
    repo_url: result.html_url,
    status: "deployed",
    created_at: new Date().toISOString(),
  };

  const deps = loadDeployments();
  deps[fullRepoName] = dep;
  saveDeployments(deps);

  return dep;
}

export async function removeDeployment(name: string): Promise<boolean> {
  const deps = loadDeployments();
  const dep = deps[name];
  if (!dep) return false;

  const accounts = loadAccounts();
  const acct = accounts[dep.account];
  if (acct) {
    try {
      const owner = acct.username || acct.name;
      await deleteRepo(owner, name, acct.token);
    } catch {
      /* repo may already be deleted */
    }
  }

  delete deps[name];
  saveDeployments(deps);
  return true;
}

export async function nukeAll(): Promise<{
  deleted: number;
  removed: number;
  errors: string[];
}> {
  const deps = loadDeployments();
  const accounts = loadAccounts();
  let deleted = 0;
  let removed = 0;
  const errors: string[] = [];

  for (const [name, dep] of Object.entries(deps)) {
    const acct = accounts[dep.account];
    if (acct) {
      try {
        const owner = acct.username || acct.name;
        await deleteRepo(owner, name, acct.token);
        deleted++;
      } catch (e: any) {
        errors.push(`${name}: ${e.message}`);
      }
    }
    removed++;
  }

  saveDeployments({});
  return { deleted, removed, errors };
}

export function formatStatus(status: string): {
  color: string;
  label: string;
} {
  switch (status) {
    case "success":
      return { color: "#22c55e", label: "success" };
    case "in_progress":
    case "queued":
    case "pending":
      return { color: "#eab308", label: status };
    case "error":
    case "failure":
      return { color: "#ef4444", label: status };
    case "stopped":
      return { color: "#6b7280", label: "stopped" };
    case "deployed":
      return { color: "#3b82f6", label: "deployed" };
    case "imported":
      return { color: "#8b5cf6", label: "imported" };
    default:
      return { color: "#9ca3af", label: status };
  }
}
