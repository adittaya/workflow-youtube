import { readFileSync, writeFileSync, existsSync, appendFileSync } from "fs";
import { join } from "path";
import { execSync } from "child_process";
import type { PlatformInfo } from "./types";

export interface EnvVar {
  name: string;
  value: string;
  description?: string;
}

export class EnvironmentManager {
  private platform: PlatformInfo;

  constructor(platform: PlatformInfo) {
    this.platform = platform;
  }

  getPathVariable(): string {
    return this.platform.os === "windows" ? "Path" : "PATH";
  }

  getShellConfigFiles(): string[] {
    const home = this.platform.homeDir;
    const files: string[] = [];

    if (this.platform.os === "windows") {
      const psProfile = execSync(
        'powershell -NoProfile -Command "echo $PROFILE" 2>/dev/null || echo ""',
        { encoding: "utf-8", timeout: 5000 }
      ).trim();
      if (psProfile && existsSync(psProfile)) {
        files.push(psProfile);
      }
      return files;
    }

    const shellConfigs: Record<string, string[]> = {
      bash: [".bashrc", ".bash_profile", ".profile"],
      zsh: [".zshrc", ".zprofile"],
      fish: [".config/fish/config.fish"],
    };

    const configs = shellConfigs[this.platform.shell] || shellConfigs.bash;
    for (const c of configs) {
      const full = join(home, c);
      if (existsSync(full)) files.push(full);
    }

    return files;
  }

  isInFile(filePath: string, entry: string): boolean {
    if (!existsSync(filePath)) return false;
    const content = readFileSync(filePath, "utf-8");
    return content.includes(entry);
  }

  appendToShellConfig(entry: string, comment?: string): string[] {
    const files = this.getShellConfigFiles();
    const modified: string[] = [];

    for (const file of files) {
      if (this.platform.os === "windows") {
        if (!this.isInFile(file, entry)) {
          const line = comment
            ? `# ${comment}\n${entry}`
            : entry;
          appendFileSync(file, `\n${line}\n`);
          modified.push(file);
        }
      } else if (this.platform.shell === "fish") {
        const fishEntry = entry
          .replace(/export (\w+)=(.*)/, "set -gx $1 $2")
          .replace(/\$PATH/, "$PATH");
        if (!this.isInFile(file, fishEntry)) {
          const line = comment
            ? `# ${comment}\n${fishEntry}`
            : fishEntry;
          appendFileSync(file, `\n${line}\n`);
          modified.push(file);
        }
      } else {
        if (!this.isInFile(file, entry)) {
          const line = comment
            ? `# ${comment}\n${entry}`
            : entry;
          appendFileSync(file, `\n${line}\n`);
          modified.push(file);
        }
      }
    }

    return modified;
  }

  addPath(pathEntry: string): string[] {
    const entries: string[] = [];

    if (this.platform.os === "windows") {
      entries.push(`[Environment]::SetEnvironmentVariable("Path", "$env:Path;${pathEntry}", "User")`);
    } else if (this.platform.shell === "fish") {
      entries.push(`fish_add_path -p ${pathEntry}`);
    } else {
      entries.push(`export PATH="${pathEntry}:$PATH"`);
    }

    const modified: string[] = [];
    for (const entry of entries) {
      const files = this.appendToShellConfig(entry, `Added by installer: ${pathEntry}`);
      modified.push(...files);
    }

    return modified;
  }

  setEnvVar(name: string, value: string): string[] {
    const entries: string[] = [];

    if (this.platform.os === "windows") {
      entries.push(`[Environment]::SetEnvironmentVariable("${name}", "${value}", "User")`);
    } else if (this.platform.shell === "fish") {
      entries.push(`set -gx ${name} "${value}"`);
    } else {
      entries.push(`export ${name}="${value}"`);
    }

    const modified: string[] = [];
    for (const entry of entries) {
      const files = this.appendToShellConfig(entry, `Added by installer: ${name}`);
      modified.push(...files);
    }

    return modified;
  }

  removeEnvVar(name: string): void {
    const files = this.getShellConfigFiles();
    for (const file of files) {
      if (!existsSync(file)) continue;
      const content = readFileSync(file, "utf-8");
      const patterns = [
        new RegExp(`export ${name}=.*\\n?`, "g"),
        new RegExp(`set -gx ${name}.*\\n?`, "g"),
        new RegExp(`.*${name}.*\\n?`, "g"),
      ];
      let newContent = content;
      for (const pattern of patterns) {
        newContent = newContent.replace(pattern, "");
      }
      if (newContent !== content) {
        writeFileSync(file, newContent);
      }
    }
  }

  getEnvVar(name: string): string | null {
    if (this.platform.os === "windows") {
      try {
        return (
          execSync(
            `powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('${name}', 'User')" 2>/dev/null`,
            { encoding: "utf-8", timeout: 5000 }
          ).trim() || null
        );
      } catch {
        return null;
      }
    }
    return process.env[name] || null;
  }

  backupShellConfigs(): string[] {
    const files = this.getShellConfigFiles();
    const backups: string[] = [];
    const backupDir = join(this.platform.configDir, "backups");
    execSync(`mkdir -p "${backupDir}"`, { stdio: "ignore" });

    for (const file of files) {
      const name = file.replace(/\//g, "_").replace(/\\/g, "_");
      const backupPath = join(backupDir, `${name}.backup`);
      try {
        execSync(`cp "${file}" "${backupPath}"`, { stdio: "ignore" });
        backups.push(backupPath);
      } catch {
        /* skip */
      }
    }

    return backups;
  }
}
