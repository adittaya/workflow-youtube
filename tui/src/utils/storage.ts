import { execSync } from "child_process";

export const DATA_DIR =
  process.env.VPLINK_HOME || `${process.env.HOME}/.vplink`;
export const ACCOUNTS_FILE = `${DATA_DIR}/accounts.json`;
export const DEPLOYMENTS_FILE = `${DATA_DIR}/deployments.json`;
export const SETTINGS_FILE = `${DATA_DIR}/settings.json`;
export const CONFIG_FILE = `${DATA_DIR}/config.json`;
export const GITHUB_API = "https://api.github.com";

export function ensureDataDir() {
  execSync(`mkdir -p "${DATA_DIR}"`, { stdio: "ignore" });
  for (const f of [ACCOUNTS_FILE, DEPLOYMENTS_FILE, SETTINGS_FILE, CONFIG_FILE]) {
    try {
      execSync(`test -f "${f}" || echo '{}' > "${f}"`, { stdio: "ignore" });
    } catch {
      /* ignore */
    }
  }
}

export function loadJson(path: string): Record<string, any> {
  try {
    return JSON.parse(require("fs").readFileSync(path, "utf-8"));
  } catch {
    return {};
  }
}

export function saveJson(path: string, data: any) {
  require("fs").writeFileSync(path, JSON.stringify(data, null, 2));
}

export function formatTimestamp(ts: string | null): string {
  if (!ts) return "never";
  const d = new Date(ts);
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffH = Math.floor(diffMin / 60);
  if (diffH < 24) return `${diffH}h ago`;
  const diffD = Math.floor(diffH / 24);
  return `${diffD}d ago`;
}

export function truncate(str: string, maxLen: number): string {
  if (str.length <= maxLen) return str;
  return str.slice(0, maxLen - 3) + "...";
}
