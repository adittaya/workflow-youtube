import type { InstallStep } from "./types";

export interface RollbackAction {
  id: string;
  description: string;
  execute: () => Promise<void>;
}

export class RollbackManager {
  private actions: RollbackAction[] = [];
  private completed: RollbackAction[] = [];

  push(action: RollbackAction): void {
    this.actions.push(action);
  }

  async rollback(): Promise<{ success: boolean; errors: string[] }> {
    const errors: string[] = [];
    const actions = [...this.actions].reverse();

    for (const action of actions) {
      try {
        await action.execute();
        this.completed.push(action);
      } catch (e: any) {
        errors.push(`Rollback failed for ${action.id}: ${e.message}`);
      }
    }

    this.actions = [];
    return { success: errors.length === 0, errors };
  }

  clear(): void {
    this.actions = [];
  }

  getPending(): RollbackAction[] {
    return [...this.actions];
  }

  getCompleted(): RollbackAction[] {
    return [...this.completed];
  }
}

export function createPackageRollback(
  packageName: string,
  uninstallFn: (name: string) => Promise<{ success: boolean }>
): RollbackAction {
  return {
    id: `uninstall-${packageName}`,
    description: `Uninstall ${packageName}`,
    execute: async () => {
      await uninstallFn(packageName);
    },
  };
}

export function createFileRollback(
  filePath: string,
  backupContent?: string
): RollbackAction {
  const { existsSync, readFileSync, writeFileSync, unlinkSync } = require("fs");
  let originalContent: string | null = null;

  if (existsSync(filePath)) {
    originalContent = readFileSync(filePath, "utf-8");
  }

  return {
    id: `restore-file-${filePath}`,
    description: `Restore ${filePath}`,
    execute: async () => {
      if (backupContent) {
        writeFileSync(filePath, backupContent);
      } else if (originalContent !== null) {
        writeFileSync(filePath, originalContent);
      } else if (existsSync(filePath)) {
        unlinkSync(filePath);
      }
    },
  };
}

export function createEnvRollback(
  envName: string,
  removeFn: (name: string) => void
): RollbackAction {
  return {
    id: `remove-env-${envName}`,
    description: `Remove env var ${envName}`,
    execute: async () => {
      removeFn(envName);
    },
  };
}

export function createPathRollback(
  pathEntry: string,
  files: string[]
): RollbackAction {
  const { readFileSync, writeFileSync, existsSync } = require("fs");

  const backups: Record<string, string> = {};
  for (const f of files) {
    if (existsSync(f)) {
      backups[f] = readFileSync(f, "utf-8");
    }
  }

  return {
    id: `remove-path-${pathEntry}`,
    description: `Remove ${pathEntry} from PATH`,
    execute: async () => {
      for (const f of files) {
        if (existsSync(f) && backups[f]) {
          writeFileSync(f, backups[f]);
        }
      }
    },
  };
}
