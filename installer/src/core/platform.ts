import { execSync } from "child_process";
import { homedir, platform, arch, hostname, userInfo } from "os";
import { existsSync, readFileSync } from "fs";
import { join } from "path";
import type {
  OS,
  Distro,
  Arch,
  Shell,
  PackageManagerType,
  PlatformInfo,
} from "./types";

function exec(cmd: string, fallback: string = ""): string {
  try {
    return execSync(cmd, { encoding: "utf-8", timeout: 10000 }).trim();
  } catch {
    return fallback;
  }
}

function detectOS(): OS {
  const p = platform();
  if (p === "linux") {
    if (existsSync("/data/data/com.termux")) return "termux";
    return "linux";
  }
  if (p === "darwin") return "macos";
  if (p === "win32") return "windows";
  return "linux";
}

function detectDistro(): { distro: Distro; version: string } {
  if (platform() !== "linux") return { distro: "unknown", version: "" };

  const osRelease = existsSync("/etc/os-release")
    ? readFileSync("/etc/os-release", "utf-8")
    : "";

  const id = osRelease.match(/^ID=(.+)$/m)?.[1]?.replace(/"/g, "") || "";
  const versionId = osRelease.match(/^VERSION_ID=(.+)$/m)?.[1]?.replace(/"/g, "") || "";

  const distroMap: Record<string, Distro> = {
    ubuntu: "ubuntu",
    debian: "debian",
    fedora: "fedora",
    arch: "arch",
    manjaro: "manjaro",
    opensuse: "opensuse",
    "opensuse-leap": "opensuse",
    "opensuse-tumbleweed": "opensuse",
    centos: "centos",
    rhel: "rhel",
    alpine: "alpine",
  };

  return {
    distro: distroMap[id] || "unknown",
    version: versionId,
  };
}

function detectArch(): Arch {
  const a = arch();
  const map: Record<string, Arch> = {
    x64: "x64",
    arm64: "arm64",
    arm: "armv7",
    x86: "x86",
  };
  return map[a] || "unknown";
}

function detectShell(): Shell {
  const shellPath = process.env.SHELL || "";
  if (shellPath.includes("zsh")) return "zsh";
  if (shellPath.includes("fish")) return "fish";
  if (shellPath.includes("bash")) return "bash";
  if (platform() === "win32") {
    if (process.env.PSModulePath) return "powershell";
    return "cmd";
  }
  return "bash";
}

function detectPackageManagers(): PackageManagerType[] {
  const managers: PackageManagerType[] = [];

  const checks: [string, PackageManagerType][] = [
    ["apt", "apt"],
    ["apt-get", "apt"],
    ["dnf", "dnf"],
    ["yum", "yum"],
    ["pacman", "pacman"],
    ["zypper", "zypper"],
    ["brew", "brew"],
    ["winget", "winget"],
    ["pkg", "pkg"],
    ["snap", "snap"],
    ["flatpak", "flatpak"],
  ];

  for (const [cmd, manager] of checks) {
    if (exec(`which ${cmd} 2>/dev/null`)) {
      if (!managers.includes(manager)) {
        managers.push(manager);
      }
    }
  }

  return managers;
}

function detectRoot(): boolean {
  if (platform() === "win32") return false;
  return exec("id -u") === "0";
}

function detectWSL(): boolean {
  if (platform() !== "linux") return false;
  try {
    const version = readFileSync("/proc/version", "utf-8");
    return version.toLowerCase().includes("microsoft");
  } catch {
    return false;
  }
}

function detectDocker(): boolean {
  return (
    existsSync("/.dockerenv") ||
    existsSync("/run/.containerenv") ||
    exec("cat /proc/1/cgroup 2>/dev/null").includes("docker")
  );
}

function getConfigDir(): string {
  const os = detectOS();
  if (os === "windows") {
    return join(process.env.APPDATA || "", "installer");
  }
  const xdg = process.env.XDG_CONFIG_HOME || join(homedir(), ".config");
  return join(xdg, "installer");
}

function getDataDir(): string {
  const os = detectOS();
  if (os === "windows") {
    return join(process.env.LOCALAPPDATA || "", "installer");
  }
  const xdg = process.env.XDG_DATA_HOME || join(homedir(), ".local", "share");
  return join(xdg, "installer");
}

function getCacheDir(): string {
  const os = detectOS();
  if (os === "windows") {
    return join(process.env.LOCALAPPDATA || "", "installer", "cache");
  }
  const xdg = process.env.XDG_CACHE_HOME || join(homedir(), ".cache");
  return join(xdg, "installer");
}

function getTempDir(): string {
  const os = detectOS();
  if (os === "windows") return process.env.TEMP || "C:\\Temp";
  return "/tmp/installer";
}

function getShellProfiles(): string[] {
  const home = homedir();
  const profiles: string[] = [];
  const candidates = [".bashrc", ".zshrc", ".profile", ".bash_profile", ".zprofile"];
  for (const c of candidates) {
    if (existsSync(join(home, c))) {
      profiles.push(join(home, c));
    }
  }
  if (platform() === "win32") {
    const psProfile = exec(
      'powershell -NoProfile -Command "echo $PROFILE" 2>/dev/null'
    );
    if (psProfile && !psProfile.includes("error")) {
      profiles.push(psProfile);
    }
  }
  return profiles;
}

export function detectPlatform(): PlatformInfo {
  const os = detectOS();
  const { distro, distroVersion } = detectDistro();
  const info: PlatformInfo = {
    os,
    distro,
    distroVersion,
    arch: detectArch(),
    shell: detectShell(),
    packageManagers: detectPackageManagers(),
    isRoot: detectRoot(),
    isWSL: detectWSL(),
    isDocker: detectDocker(),
    hostname: hostname(),
    username: userInfo().username,
    homeDir: homedir(),
    configDir: getConfigDir(),
    dataDir: getDataDir(),
    cacheDir: getCacheDir(),
    tempDir: getTempDir(),
    shellProfiles: getShellProfiles(),
  };
  return info;
}

export function getPrimaryPackageManager(
  managers: PackageManagerType[]
): PackageManagerType {
  const priority: PackageManagerType[] = [
    "apt",
    "dnf",
    "yum",
    "pacman",
    "zypper",
    "brew",
    "winget",
    "pkg",
  ];
  for (const m of priority) {
    if (managers.includes(m)) return m;
  }
  return managers[0] || "unknown";
}

export function formatPlatform(info: PlatformInfo): string {
  const parts = [
    `${info.os}`,
    info.distro !== "unknown" ? info.distro : "",
    info.distroVersion,
    info.arch,
  ].filter(Boolean);
  return parts.join(" ");
}
