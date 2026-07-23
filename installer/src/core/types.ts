export type OS = "linux" | "macos" | "windows" | "termux";
export type Distro =
  | "ubuntu"
  | "debian"
  | "fedora"
  | "arch"
  | "opensuse"
  | "manjaro"
  | "centos"
  | "rhel"
  | "alpine"
  | "unknown";
export type Arch = "x64" | "arm64" | "armv7" | "armv6" | "x86" | "unknown";
export type Shell = "bash" | "zsh" | "fish" | "powershell" | "cmd" | "unknown";
export type PackageManagerType =
  | "apt"
  | "dnf"
  | "yum"
  | "pacman"
  | "zypper"
  | "brew"
  | "winget"
  | "pkg"
  | "snap"
  | "flatpak"
  | "unknown";

export interface PlatformInfo {
  os: OS;
  distro: Distro;
  distroVersion: string;
  arch: Arch;
  shell: Shell;
  packageManagers: PackageManagerType[];
  isRoot: boolean;
  isWSL: boolean;
  isDocker: boolean;
  hostname: string;
  username: string;
  homeDir: string;
  configDir: string;
  dataDir: string;
  cacheDir: string;
  tempDir: string;
  shellProfiles: string[];
}

export interface InstalledPackage {
  name: string;
  version: string;
  manager: PackageManagerType;
  installed: boolean;
}

export interface PackageDefinition {
  name: string;
  displayName: string;
  description: string;
  category: "core" | "dev" | "tools" | "languages" | " editors" | "containers" | "custom";
  required: boolean;
  detectCommand: string;
  detectVersionFlag?: string;
  install: Record<PackageManagerType, string | null>;
  installAlt?: Record<string, string>;
  postInstall?: string;
  envVars?: Record<string, string>;
  PATH?: string[];
  verifyAfterInstall?: string;
  conflicts?: string[];
  dependsOn?: string[];
}

export interface DownloadSpec {
  url: string;
  name: string;
  version: string;
  sha256?: string;
  size?: number;
  type: "binary" | "archive" | "config" | "script";
  archiveType?: "zip" | "tar.gz" | "tar.xz" | "tar.bz2";
  extractPath?: string;
  installPath?: string;
  executable?: boolean;
}

export interface InstallerConfig {
  version: string;
  installDir: string;
  configDir: string;
  logDir: string;
  packages: string[];
  envVars: Record<string, string>;
  PATH: string[];
  customPackages: PackageDefinition[];
  platform_overrides: Record<OS, Partial<InstallerConfig>>;
}

export interface InstallStep {
  id: string;
  name: string;
  type: "package" | "download" | "config" | "env" | "script" | "verify";
  status: "pending" | "running" | "success" | "error" | "skipped" | "rollback";
  error?: string;
  duration?: number;
  rollback?: () => Promise<void>;
}

export interface InstallResult {
  success: boolean;
  steps: InstallStep[];
  errors: string[];
  warnings: string[];
  duration: number;
  installedPackages: string[];
  downloadedFiles: string[];
}

export interface VerificationResult {
  name: string;
  installed: boolean;
  version: string | null;
  status: "ok" | "outdated" | "missing" | "error";
  path?: string;
}

export interface UpdateInfo {
  currentVersion: string;
  latestVersion: string;
  updateAvailable: boolean;
  downloadUrl?: string;
  changelog?: string;
}
