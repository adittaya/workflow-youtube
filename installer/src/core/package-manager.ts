import { execSync } from "child_process";
import type {
  PackageManagerType,
  InstalledPackage,
  PackageDefinition,
  PlatformInfo,
} from "./types";
import { getPrimaryPackageManager } from "./platform";

interface PackageManagerCommands {
  install: (name: string) => string;
  uninstall: (name: string) => string;
  update: () => string;
  upgrade: () => string;
  isInstalled: (name: string) => string;
  getVersion: (name: string) => string;
  list: () => string;
  search: (query: string) => string;
  clean: () => string;
}

const MANAGER_COMMANDS: Record<PackageManagerType, PackageManagerCommands> = {
  apt: {
    install: (n) => `DEBIAN_FRONTEND=noninteractive apt-get install -y ${n}`,
    uninstall: (n) => `apt-get remove -y ${n}`,
    update: () => "apt-get update -qq",
    upgrade: () => "apt-get upgrade -y",
    isInstalled: (n) => `dpkg -l ${n} 2>/dev/null | grep -q "^ii"`,
    getVersion: (n) => `dpkg -s ${n} 2>/dev/null | grep Version | awk '{print $2}'`,
    list: () => "dpkg -l | awk '/^ii/ {print $2, $3}'",
    search: (q) => `apt-cache search ${q}`,
    clean: () => "apt-get clean && apt-get autoremove -y",
  },
  dnf: {
    install: (n) => `dnf install -y ${n}`,
    uninstall: (n) => `dnf remove -y ${n}`,
    update: () => "dnf check-update || true",
    upgrade: () => "dnf upgrade -y",
    isInstalled: (n) => `dnf list installed ${n} 2>/dev/null | grep -q "${n}"`,
    getVersion: (n) => `rpm -q --queryformat '%{VERSION}' ${n} 2>/dev/null || dnf list installed ${n} 2>/dev/null | awk 'NR==2{print $2}'`,
    list: () => "dnf list installed | tail -n +2 | awk '{print $1, $2}'",
    search: (q) => `dnf search ${q}`,
    clean: () => "dnf clean all",
  },
  yum: {
    install: (n) => `yum install -y ${n}`,
    uninstall: (n) => `yum remove -y ${n}`,
    update: () => "yum check-update || true",
    upgrade: () => `yum update -y`,
    isInstalled: (n) => `yum list installed ${n} 2>/dev/null | grep -q "${n}"`,
    getVersion: (n) => `rpm -q --queryformat '%{VERSION}' ${n} 2>/dev/null`,
    list: () => "yum list installed | tail -n +2 | awk '{print $1, $2}'",
    search: (q) => `yum search ${q}`,
    clean: () => "yum clean all",
  },
  pacman: {
    install: (n) => `pacman -S --noconfirm ${n}`,
    uninstall: (n) => `pacman -R --noconfirm ${n}`,
    update: () => "pacman -Sy",
    upgrade: () => "pacman -Syu --noconfirm",
    isInstalled: (n) => `pacman -Qi ${n} &>/dev/null`,
    getVersion: (n) => `pacman -Qi ${n} 2>/dev/null | grep Version | awk '{print $3}'`,
    list: () => "pacman -Q | awk '{print $1, $2}'",
    search: (q) => `pacman -Ss ${q}`,
    clean: () => "pacman -Sc --noconfirm",
  },
  zypper: {
    install: (n) => `zypper install -y ${n}`,
    uninstall: (n) => `zypper remove -y ${n}`,
    update: () => "zypper refresh",
    upgrade: () => "zypper update -y",
    isInstalled: (n) => `rpm -q ${n} &>/dev/null`,
    getVersion: (n) => `rpm -q --queryformat '%{VERSION}' ${n} 2>/dev/null`,
    list: () => "rpm -qa | awk '{print $1}'",
    search: (q) => `zypper search ${q}`,
    clean: () => "zypper clean --all",
  },
  brew: {
    install: (n) => `brew install ${n}`,
    uninstall: (n) => `brew uninstall ${n}`,
    update: () => "brew update",
    upgrade: () => "brew upgrade",
    isInstalled: (n) => `brew list ${n} &>/dev/null`,
    getVersion: (n) => `brew list --versions ${n} 2>/dev/null | awk '{print $2}'`,
    list: () => "brew list --formula | while read p; do echo \"$p $(brew list --versions $p | awk '{print $2}')\"; done",
    search: (q) => `brew search ${q}`,
    clean: () => "brew cleanup",
  },
  winget: {
    install: (n) => `winget install --id ${n} --accept-package-agreements --accept-source-agreements`,
    uninstall: (n) => `winget uninstall --id ${n}`,
    update: () => "winget upgrade --all --accept-package-agreements",
    upgrade: () => "winget upgrade --all --accept-package-agreements",
    isInstalled: (n) => `winget list --id ${n} 2>/dev/null | grep -q "${n}"`,
    getVersion: (n) => `winget list --id ${n} 2>/dev/null | awk 'NR==3{print $3}'`,
    list: () => "winget list",
    search: (q) => `winget search ${q}`,
    clean: () => "echo 'No cleanup needed for winget'",
  },
  pkg: {
    install: (n) => `pkg install -y ${n}`,
    uninstall: (n) => `pkg uninstall -y ${n}`,
    update: () => "pkg update -y",
    upgrade: () => "pkg upgrade -y",
    isInstalled: (n) => `pkg list-installed 2>/dev/null | grep -q "${n}"`,
    getVersion: (n) => `pkg list-installed ${n} 2>/dev/null | awk '{print $2}'`,
    list: () => "pkg list-installed | awk '{print $1, $2}'",
    search: (q) => `pkg search ${q}`,
    clean: () => "pkg clean -y",
  },
  snap: {
    install: (n) => `snap install ${n}`,
    uninstall: (n) => `snap remove ${n}`,
    update: () => "snap refresh",
    upgrade: () => "snap refresh",
    isInstalled: (n) => `snap list ${n} &>/dev/null`,
    getVersion: (n) => `snap list ${n} 2>/dev/null | awk 'NR==2{print $2}'`,
    list: () => "snap list | awk 'NR>1{print $1, $2}'",
    search: (q) => `snap find ${q}`,
    clean: () => "snap list | awk 'NR>1{print $1}' | xargs -I{} snap list {} | grep disabled | awk '{print $1}' | xargs -r snap remove",
  },
  flatpak: {
    install: (n) => `flatpak install -y flathub ${n}`,
    uninstall: (n) => `flatpak uninstall -y ${n}`,
    update: () => "flatpak update -y",
    upgrade: () => "flatpak update -y",
    isInstalled: (n) => `flatpak list --app 2>/dev/null | grep -qi "${n}"`,
    getVersion: (n) => `flatpak list --app 2>/dev/null | grep -i "${n}" | awk '{print $NF}'`,
    list: () => "flatpak list --app | awk -F'\\t' '{print $1, $NF}'",
    search: (q) => `flatpak search ${q}`,
    clean: () => "flatpak uninstall --unused -y",
  },
  unknown: {
    install: () => "echo 'No package manager available'",
    uninstall: () => "echo 'No package manager available'",
    update: () => "echo 'No package manager available'",
    upgrade: () => "echo 'No package manager available'",
    isInstalled: () => "false",
    getVersion: () => "",
    list: () => "",
    search: () => "",
    clean: () => "echo 'No package manager available'",
  },
};

function exec(
  cmd: string,
  options: { timeout?: number; ignoreError?: boolean } = {}
): string {
  try {
    return execSync(cmd, {
      encoding: "utf-8",
      timeout: options.timeout || 120000,
      stdio: ["pipe", "pipe", "pipe"],
    }).trim();
  } catch (e: any) {
    if (options.ignoreError) return "";
    throw e;
  }
}

export class PackageInstaller {
  private platform: PlatformInfo;
  private primaryManager: PackageManagerType;
  private sudo: string;

  constructor(platform: PlatformInfo) {
    this.platform = platform;
    this.primaryManager = getPrimaryPackageManager(platform.packageManagers);
    this.sudo = this.platform.isRoot ? "" : "sudo ";
  }

  getManager(): PackageManagerType {
    return this.primaryManager;
  }

  getCommands(manager?: PackageManagerType): PackageManagerCommands {
    return MANAGER_COMMANDS[manager || this.primaryManager];
  }

  async isInstalled(
    name: string,
    manager?: PackageManagerType
  ): Promise<boolean> {
    const cmds = this.getCommands(manager);
    try {
      exec(cmds.isInstalled(name), { ignoreError: true, timeout: 10000 });
      return true;
    } catch {
      return false;
    }
  }

  async getVersion(
    name: string,
    manager?: PackageManagerType
  ): Promise<string | null> {
    const cmds = this.getCommands(manager);
    try {
      return exec(cmds.getVersion(name), { ignoreError: true, timeout: 10000 }) || null;
    } catch {
      return null;
    }
  }

  async install(
    name: string,
    manager?: PackageManagerType,
    useSudo: boolean = true
  ): Promise<{ success: boolean; output: string }> {
    const cmds = this.getCommands(manager);
    const cmd = cmds.install(name);
    const fullCmd = useSudo && !this.platform.isRoot ? `${this.sudo}${cmd}` : cmd;
    try {
      const output = exec(fullCmd, { timeout: 300000 });
      return { success: true, output };
    } catch (e: any) {
      return { success: false, output: e.message };
    }
  }

  async uninstall(
    name: string,
    manager?: PackageManagerType,
    useSudo: boolean = true
  ): Promise<{ success: boolean; output: string }> {
    const cmds = this.getCommands(manager);
    const cmd = cmds.uninstall(name);
    const fullCmd = useSudo && !this.platform.isRoot ? `${this.sudo}${cmd}` : cmd;
    try {
      const output = exec(fullCmd, { timeout: 120000 });
      return { success: true, output };
    } catch (e: any) {
      return { success: false, output: e.message };
    }
  }

  async updateIndex(manager?: PackageManagerType): Promise<void> {
    const cmds = this.getCommands(manager);
    exec(`${this.sudo}${cmds.update()}`, { timeout: 300000, ignoreError: true });
  }

  async upgradeAll(manager?: PackageManagerType): Promise<void> {
    const cmds = this.getCommands(manager);
    exec(`${this.sudo}${cmds.upgrade()}`, { timeout: 600000, ignoreError: true });
  }

  async listInstalled(): Promise<InstalledPackage[]> {
    const cmds = this.getCommands();
    try {
      const output = exec(cmds.list(), { ignoreError: true });
      return output
        .split("\n")
        .filter(Boolean)
        .map((line) => {
          const [name, version] = line.split(/\s+/);
          return {
            name: name || "",
            version: version || "",
            manager: this.primaryManager,
            installed: true,
          };
        });
    } catch {
      return [];
    }
  }

  detectPackage(
    definition: PackageDefinition
  ): { installed: boolean; version: string | null } {
    const cmd = definition.detectCommand;
    try {
      const output = exec(cmd, { ignoreError: true, timeout: 10000 });
      if (output) {
        let version = output;
        if (definition.detectVersionFlag) {
          try {
            version = exec(`${cmd} ${definition.detectVersionFlag}`, {
              ignoreError: true,
              timeout: 10000,
            });
          } catch {
            /* use raw output */
          }
        }
        return { installed: true, version };
      }
      return { installed: false, version: null };
    } catch {
      return { installed: false, version: null };
    }
  }

  getInstallCommand(
    definition: PackageDefinition,
    manager?: PackageManagerType
  ): string | null {
    const mgr = manager || this.primaryManager;
    return definition.install[mgr] || null;
  }

  clean(manager?: PackageManagerType): void {
    const cmds = this.getCommands(manager);
    exec(`${this.sudo}${cmds.clean()}`, { timeout: 120000, ignoreError: true });
  }
}

export { exec };
