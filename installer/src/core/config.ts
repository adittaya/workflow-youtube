import { mkdirSync, readFileSync, writeFileSync, existsSync } from "fs";
import { join } from "path";
import type { InstallerConfig } from "./types";
import type { PlatformInfo } from "./types";

const DEFAULT_CONFIG: InstallerConfig = {
  version: "1.0.0",
  installDir: "",
  configDir: "",
  logDir: "",
  packages: [
    "git",
    "curl",
    "wget",
    "unzip",
    "build-essential",
    "nodejs",
    "npm",
    "python3",
    "python3-pip",
    "docker",
  ],
  envVars: {},
  PATH: [],
  customPackages: [],
  platform_overrides: {},
};

export class ConfigManager {
  private configPath: string;
  private config: InstallerConfig;
  private platform: PlatformInfo;

  constructor(platform: PlatformInfo) {
    this.platform = platform;
    const configDir = join(platform.configDir);
    mkdirSync(configDir, { recursive: true });
    this.configPath = join(configDir, "config.json");

    this.config = this.load();
    this.setDefaults();
  }

  private setDefaults(): void {
    this.config.installDir =
      this.config.installDir ||
      (this.platform.os === "windows"
        ? join(process.env.LOCALAPPDATA || "", "installer", "bin")
        : join(this.platform.homeDir, ".local", "bin"));
    this.config.configDir = this.config.configDir || this.platform.configDir;
    this.config.logDir =
      this.config.logDir ||
      join(
        this.platform.os === "windows"
          ? process.env.LOCALAPPDATA || ""
          : join(this.platform.homeDir, ".local", "share"),
        "installer",
        "logs"
      );
  }

  load(): InstallerConfig {
    try {
      if (existsSync(this.configPath)) {
        const raw = readFileSync(this.configPath, "utf-8");
        return { ...DEFAULT_CONFIG, ...JSON.parse(raw) };
      }
    } catch {
      /* ignore */
    }
    return { ...DEFAULT_CONFIG };
  }

  save(): void {
    mkdirSync(this.config.configDir, { recursive: true });
    writeFileSync(this.configPath, JSON.stringify(this.config, null, 2));
  }

  get(): InstallerConfig {
    return this.config;
  }

  set(updates: Partial<InstallerConfig>): void {
    this.config = { ...this.config, ...updates };
    this.save();
  }

  addPackage(name: string): void {
    if (!this.config.packages.includes(name)) {
      this.config.packages.push(name);
      this.save();
    }
  }

  removePackage(name: string): void {
    this.config.packages = this.config.packages.filter((p) => p !== name);
    this.save();
  }

  setEnvVar(name: string, value: string): void {
    this.config.envVars[name] = value;
    this.save();
  }

  removeEnvVar(name: string): void {
    delete this.config.envVars[name];
    this.save();
  }

  addPath(pathEntry: string): void {
    if (!this.config.PATH.includes(pathEntry)) {
      this.config.PATH.push(pathEntry);
      this.save();
    }
  }

  getInstallDir(): string {
    return this.config.installDir;
  }

  getConfigDir(): string {
    return this.config.configDir;
  }

  getLogDir(): string {
    return this.config.logDir;
  }

  getPackages(): string[] {
    return this.config.packages;
  }

  getEnvVars(): Record<string, string> {
    return this.config.envVars;
  }

  getPATH(): string[] {
    return this.config.PATH;
  }

  exportConfig(): string {
    return JSON.stringify(this.config, null, 2);
  }

  importConfig(json: string): void {
    this.config = { ...DEFAULT_CONFIG, ...JSON.parse(json) };
    this.save();
  }
}
