import { useState, useCallback, useEffect } from "react";
import {
  loadAccounts,
  loadDeployments,
  loadSettings,
  getActiveAccount,
  syncFromGitHub,
  deployNew,
  removeDeployment,
  nukeAll,
  addAccount,
  removeAccount,
  switchAccount,
  type LocalDeployment,
  type Settings,
} from "../services/deploy";
import { type GitHubAccount, discoverDeployments } from "../services/github";
import {
  loadJson,
  saveJson,
  ACCOUNTS_FILE,
  DEPLOYMENTS_FILE,
} from "../utils/storage";

export type Screen =
  | "dashboard"
  | "deployments"
  | "accounts"
  | "analytics"
  | "settings"
  | "sync";

export interface AppState {
  screen: Screen;
  accounts: Record<string, GitHubAccount>;
  deployments: Record<string, LocalDeployment>;
  settings: Settings;
  activeAccount: GitHubAccount | null;
  syncing: boolean;
  lastSync: string | null;
  message: string | null;
  messageType: "info" | "success" | "error" | null;
}

export function useAppState() {
  const [state, setState] = useState<AppState>({
    screen: "dashboard",
    accounts: loadAccounts(),
    deployments: loadDeployments(),
    settings: loadSettings(),
    activeAccount: getActiveAccount(),
    syncing: false,
    lastSync: null,
    message: null,
    messageType: null,
  });

  const refresh = useCallback(() => {
    setState((prev) => ({
      ...prev,
      accounts: loadAccounts(),
      deployments: loadDeployments(),
      settings: loadSettings(),
      activeAccount: getActiveAccount(),
    }));
  }, []);

  const setScreen = useCallback((screen: Screen) => {
    setState((prev) => ({ ...prev, screen, message: null, messageType: null }));
  }, []);

  const showMessage = useCallback(
    (message: string, type: "info" | "success" | "error" = "info") => {
      setState((prev) => ({ ...prev, message, messageType: type }));
    },
    []
  );

  const clearMessage = useCallback(() => {
    setState((prev) => ({ ...prev, message: null, messageType: null }));
  }, []);

  const handleSync = useCallback(async () => {
    setState((prev) => ({ ...prev, syncing: true, message: null }));
    try {
      const result = await syncFromGitHub();
      const parts: string[] = [];
      if (result.newRepos.length > 0)
        parts.push(`${result.newRepos.length} new`);
      if (result.updatedRepos.length > 0)
        parts.push(`${result.updatedRepos.length} updated`);
      const msg =
        parts.length > 0
          ? `Synced: ${parts.join(", ")}`
          : "All up to date";
      setState((prev) => ({
        ...prev,
        syncing: false,
        accounts: result.accounts,
        deployments: result.deployments,
        lastSync: new Date().toISOString(),
        message: msg,
        messageType: "success",
      }));
    } catch (e: any) {
      setState((prev) => ({
        ...prev,
        syncing: false,
        message: `Sync failed: ${e.message}`,
        messageType: "error",
      }));
    }
  }, []);

  const handleDeploy = useCallback(
    async (name: string | null, key: string) => {
      setState((prev) => ({ ...prev, syncing: true }));
      try {
        const dep = await deployNew(name, key);
        setState((prev) => ({
          ...prev,
          syncing: false,
          deployments: {
            ...loadDeployments(),
            [dep.name]: dep,
          },
          message: `Deployed ${dep.name}`,
          messageType: "success",
        }));
      } catch (e: any) {
        setState((prev) => ({
          ...prev,
          syncing: false,
          message: `Deploy failed: ${e.message}`,
          messageType: "error",
        }));
      }
    },
    []
  );

  const handleRemove = useCallback(async (name: string) => {
    setState((prev) => ({ ...prev, syncing: true }));
    try {
      await removeDeployment(name);
      const deps = loadDeployments();
      setState((prev) => ({
        ...prev,
        syncing: false,
        deployments: deps,
        message: `Removed ${name}`,
        messageType: "success",
      }));
    } catch (e: any) {
      setState((prev) => ({
        ...prev,
        syncing: false,
        message: `Remove failed: ${e.message}`,
        messageType: "error",
      }));
    }
  }, []);

  const handleNukeAll = useCallback(async () => {
    setState((prev) => ({ ...prev, syncing: true }));
    try {
      const result = await nukeAll();
      setState((prev) => ({
        ...prev,
        syncing: false,
        deployments: {},
        message: `Nuked: ${result.deleted} repos deleted, ${result.removed} records removed`,
        messageType: result.errors.length > 0 ? "error" : "success",
      }));
    } catch (e: any) {
      setState((prev) => ({
        ...prev,
        syncing: false,
        message: `Nuke failed: ${e.message}`,
        messageType: "error",
      }));
    }
  }, []);

  const handleAddAccount = useCallback(
    async (name: string, token: string) => {
      try {
        const { username, scopes } = await addAccount(name, token);
        const hasRepo = scopes.some((s) => s.includes("repo"));
        const hasWorkflow = scopes.some((s) => s.includes("workflow"));
        const warnings: string[] = [];
        if (!hasRepo) warnings.push("missing repo scope");
        if (!hasWorkflow) warnings.push("missing workflow scope");
        const msg = `Added ${name} (@${username})${
          warnings.length > 0 ? ` ⚠ ${warnings.join(", ")}` : ""
        }`;
        refresh();
        showMessage(msg, warnings.length > 0 ? "error" : "success");
      } catch (e: any) {
        showMessage(`Add account failed: ${e.message}`, "error");
      }
    },
    [refresh, showMessage]
  );

  const handleRemoveAccount = useCallback(
    (name: string) => {
      removeAccount(name);
      refresh();
      showMessage(`Removed account ${name}`, "success");
    },
    [refresh, showMessage]
  );

  const handleSwitchAccount = useCallback(
    (name: string) => {
      switchAccount(name);
      refresh();
      showMessage(`Switched to ${name}`, "success");
    },
    [refresh, showMessage]
  );

  const handleSaveSettings = useCallback(
    (settings: Settings) => {
      saveJson(
        require("path").join(
          require("os").homedir(),
          ".vplink",
          "settings.json"
        ),
        settings
      );
      refresh();
      showMessage("Settings saved", "success");
    },
    [refresh, showMessage]
  );

  return {
    state,
    setScreen,
    refresh,
    showMessage,
    clearMessage,
    handleSync,
    handleDeploy,
    handleRemove,
    handleNukeAll,
    handleAddAccount,
    handleRemoveAccount,
    handleSwitchAccount,
    handleSaveSettings,
  };
}
