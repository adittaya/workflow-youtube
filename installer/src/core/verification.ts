import { execSync } from "child_process";
import { existsSync } from "fs";
import type { PackageDefinition, VerificationResult, PlatformInfo } from "./types";

function exec(cmd: string, timeout: number = 10000): string {
  try {
    return execSync(cmd, {
      encoding: "utf-8",
      timeout,
      stdio: ["pipe", "pipe", "pipe"],
    }).trim();
  } catch {
    return "";
  }
}

const BUILT_IN_CHECKS: Record<string, { command: string; versionFlag: string }> = {
  git: { command: "git", versionFlag: "--version" },
  curl: { command: "curl", versionFlag: "--version" },
  wget: { command: "wget", versionFlag: "--version" },
  node: { command: "node", versionFlag: "--version" },
  npm: { command: "npm", versionFlag: "--version" },
  bun: { command: "bun", versionFlag: "--version" },
  python3: { command: "python3", versionFlag: "--version" },
  pip3: { command: "pip3", versionFlag: "--version" },
  java: { command: "java", versionFlag: "-version" },
  docker: { command: "docker", versionFlag: "--version" },
  code: { command: "code", versionFlag: "--version" },
  gcc: { command: "gcc", versionFlag: "--version" },
  make: { command: "make", versionFlag: "--version" },
  cmake: { command: "cmake", versionFlag: "--version" },
  rustc: { command: "rustc", versionFlag: "--version" },
  cargo: { command: "cargo", versionFlag: "--version" },
  go: { command: "go", versionFlag: "version" },
  ruby: { command: "ruby", versionFlag: "--version" },
  java: { command: "java", versionFlag: "-version" },
  unzip: { command: "unzip", versionFlag: "-v" },
  jq: { command: "jq", versionFlag: "--version" },
  tree: { command: "tree", versionFlag: "--version" },
  htop: { command: "htop", versionFlag: "--version" },
  tmux: { command: "tmux", versionFlag: "-V" },
  vim: { command: "vim", versionFlag: "--version" },
  nano: { command: "nano", versionFlag: "--version" },
  ssh: { command: "ssh", versionFlag: "-V" },
};

export class Verifier {
  private platform: PlatformInfo;

  constructor(platform: PlatformInfo) {
    this.platform = platform;
  }

  checkPackage(name: string): VerificationResult {
    const check = BUILT_IN_CHECKS[name];
    if (!check) {
      return {
        name,
        installed: false,
        version: null,
        status: "missing",
      };
    }

    if (!this.isCommandAvailable(check.command)) {
      return {
        name,
        installed: false,
        version: null,
        status: "missing",
      };
    }

    try {
      let version = exec(`${check.command} ${check.versionFlag}`, 5000);
      version = this.parseVersion(version);

      return {
        name,
        installed: true,
        version,
        status: "ok",
        path: exec(`which ${check.command} 2>/dev/null`) || undefined,
      };
    } catch {
      return {
        name,
        installed: true,
        version: null,
        status: "ok",
        path: exec(`which ${check.command} 2>/dev/null`) || undefined,
      };
    }
  }

  checkCustomPackage(definition: PackageDefinition): VerificationResult {
    try {
      const output = exec(definition.detectCommand, 5000);
      if (output) {
        return {
          name: definition.name,
          installed: true,
          version: this.parseVersion(output),
          status: "ok",
          path: exec(`which ${definition.detectCommand.split(" ")[0]} 2>/dev/null`) || undefined,
        };
      }
    } catch {
      /* not installed */
    }

    return {
      name: definition.name,
      installed: false,
      version: null,
      status: "missing",
    };
  }

  checkAll(
    packages: string[],
    customPackages?: PackageDefinition[]
  ): VerificationResult[] {
    const results: VerificationResult[] = [];

    for (const pkg of packages) {
      results.push(this.checkPackage(pkg));
    }

    if (customPackages) {
      for (const pkg of customPackages) {
        results.push(this.checkCustomPackage(pkg));
      }
    }

    return results;
  }

  isCommandAvailable(command: string): boolean {
    const whichCmd =
      this.platform.os === "windows" ? `where ${command}` : `which ${command}`;
    try {
      const result = exec(whichCmd, 5000);
      return result.length > 0 && !result.includes("not found");
    } catch {
      return false;
    }
  }

  private parseVersion(output: string): string {
    const versionMatch = output.match(
      /(\d+\.\d+[\.\d]*)|v(\d+\.\d+[\.\d]*)/
    );
    if (versionMatch) {
      return versionMatch[0].replace(/^v/, "");
    }
    const lines = output.split("\n");
    for (const line of lines) {
      const m = line.match(/(\d+\.\d+[\.\d]*)/);
      if (m) return m[1];
    }
    return output.split("\n")[0].trim();
  }

  getSummary(results: VerificationResult[]): {
    total: number;
    installed: number;
    missing: number;
    outdated: number;
  } {
    return {
      total: results.length,
      installed: results.filter((r) => r.installed).length,
      missing: results.filter((r) => !r.installed).length,
      outdated: results.filter((r) => r.status === "outdated").length,
    };
  }
}
