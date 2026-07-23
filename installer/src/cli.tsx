#!/usr/bin/env bun
import { createCliRenderer } from "@opentui/core";
import { createRoot } from "@opentui/react";
import { InstallerApp } from "./interactive/app";
import { Installer } from "./core/installer";
import type { InstallerOptions } from "./core/installer";

const args = process.argv.slice(2);
const command = args[0] || "";

function printHelp() {
  console.log(`
\x1b[34m⚡ Installer\x1b[0m v1.0.0 — Production-Grade Cross-Platform Bootstrap

\x1b[1mUSAGE:\x1b[0m
  installer                    Launch interactive TUI
  installer <command>          Run a specific command

\x1b[1mCOMMANDS:\x1b[0m
  install [packages...]        Install packages (interactive or specified)
  update                       Check for self-updates
  repair                       Re-run installation to fix issues
  doctor                       Diagnose system and show issues
  verify                       Verify all installed packages
  config                       Show current configuration
  uninstall [--config]         Remove installed packages
  logs                         Show installer logs
  version                      Show version
  status                       Show package status
  platform                     Show platform information

\x1b[1mOPTIONS:\x1b[0m
  --dry-run                    Show what would be done
  --upgrade                    Upgrade existing packages
  --skip-required              Skip required packages
  --packages pkg1,pkg2         Comma-separated package list
  --help, -h                   Show this help
  --version, -v                Show version

\x1b[1mEXAMPLES:\x1b[0m
  installer                          Launch interactive TUI
  installer install                  Install default packages
  installer install git nodejs       Install specific packages
  installer doctor                   Diagnose system
  installer verify                   Verify installations
  installer uninstall --config       Remove everything

\x1b[1mPLATFORMS:\x1b[0m
  Linux (Ubuntu, Debian, Fedora, Arch, openSUSE)
  macOS (Homebrew)
  Windows (Winget)
  Termux (pkg)
`);
}

function printVersion() {
  console.log("installer v1.0.0");
}

function parseOptions(args: string[]): InstallerOptions & { command: string } {
  const options: InstallerOptions & { command: string } = {
    command: args[0] || "",
    packages: [],
    dryRun: false,
    upgrade: false,
    skipRequired: false,
    nonInteractive: true,
  };

  for (let i = 1; i < args.length; i++) {
    const arg = args[i];
    if (arg === "--dry-run") options.dryRun = true;
    else if (arg === "--upgrade") options.upgrade = true;
    else if (arg === "--skip-required") options.skipRequired = true;
    else if (arg === "--packages" && args[i + 1]) {
      options.packages = args[++i].split(",").map((s) => s.trim());
    } else if (!arg.startsWith("-") && options.packages!.length === 0) {
      options.packages = [arg, ...args.slice(i + 1).filter((a) => !a.startsWith("-"))];
      break;
    }
  }

  return options;
}

if (args.includes("--help") || args.includes("-h") || command === "help") {
  printHelp();
  process.exit(0);
}

if (args.includes("--version") || args.includes("-v") || command === "version") {
  printVersion();
  process.exit(0);
}

if (command === "" || command === "tui") {
  const renderer = await createCliRenderer({ exitOnCtrlC: true });
  createRoot(renderer).render(<InstallerApp />);
} else {
  const options = parseOptions(args);
  const installer = new Installer();

  switch (command) {
    case "install": {
      console.log("\x1b[34m⚡ Starting installation...\x1b[0m\n");
      const result = await installer.run(options);

      console.log("\n" + "─".repeat(50));

      for (const step of result.steps) {
        const icon =
          step.status === "success"
            ? "\x1b[32m✓\x1b[0m"
            : step.status === "error"
              ? "\x1b[31m✗\x1b[0m"
              : step.status === "skipped"
                ? "\x1b[90m—\x1b[0m"
                : "\x1b[90m○\x1b[0m";
        console.log(`${icon} ${step.name}`);
        if (step.error) {
          console.log(`  \x1b[31m${step.error.slice(0, 80)}\x1b[0m`);
        }
      }

      console.log("─".repeat(50));
      if (result.success) {
        console.log(
          `\x1b[32m✓ Installation complete!\x1b[0m (${(result.duration / 1000).toFixed(1)}s)`
        );
      } else {
        console.log(
          `\x1b[31m✗ Installation failed with ${result.errors.length} error(s)\x1b[0m`
        );
        for (const e of result.errors) {
          console.log(`  \x1b[31m${e.slice(0, 80)}\x1b[0m`);
        }
      }
      process.exit(result.success ? 0 : 1);
      break;
    }

    case "doctor": {
      console.log("\x1b[34m⚡ Running system diagnostics...\x1b[0m\n");
      const result = await installer.doctor();

      console.log("\x1b[1mPlatform:\x1b[0m");
      console.log(`  OS: ${result.platform.os}`);
      console.log(`  Distro: ${result.platform.distro}`);
      console.log(`  Arch: ${result.platform.arch}`);
      console.log(`  Shell: ${result.platform.shell}`);
      console.log(
        `  Package managers: ${result.platform.packageManagers.join(", ")}`
      );
      console.log(`  Root: ${result.platform.isRoot}`);
      console.log(`  WSL: ${result.platform.isWSL}`);
      console.log(`  Docker: ${result.platform.isDocker}`);

      console.log("\n\x1b[1mPackages:\x1b[0m");
      for (const pkg of result.packages) {
        const icon = pkg.installed ? "\x1b[32m✓\x1b[0m" : "\x1b[31m✗\x1b[0m";
        const ver = pkg.version ? ` (${pkg.version})` : "";
        console.log(`  ${icon} ${pkg.name}${ver}`);
      }

      if (result.issues.length > 0) {
        console.log("\n\x1b[31mIssues:\x1b[0m");
        for (const issue of result.issues) {
          console.log(`  \x1b[31m✗ ${issue}\x1b[0m`);
        }
      } else {
        console.log("\n\x1b[32m✓ No issues found\x1b[0m");
      }
      process.exit(result.issues.length > 0 ? 1 : 0);
      break;
    }

    case "verify": {
      console.log("\x1b[34m⚡ Verifying installations...\x1b[0m\n");
      const results = await installer.verify();

      for (const r of results) {
        const icon = r.installed ? "\x1b[32m✓\x1b[0m" : "\x1b[31m✗\x1b[0m";
        const ver = r.version ? ` (${r.version})` : " (not installed)";
        console.log(`${icon} ${r.name.padEnd(20)} ${ver.padEnd(20)} ${r.status}`);
      }

      const installed = results.filter((r) => r.installed).length;
      const missing = results.filter((r) => !r.installed).length;
      console.log(
        `\n\x1b[32m${installed}\x1b[0m installed, \x1b[31m${missing}\x1b[0m missing`
      );
      process.exit(0);
      break;
    }

    case "status": {
      console.log("\x1b[34m⚡ Checking status...\x1b[0m\n");
      const result = await installer.status();

      console.log(`\x1b[32mInstalled:\x1b[0m ${result.installed.length}`);
      for (const name of result.installed) {
        console.log(`  \x1b[32m✓\x1b[0m ${name}`);
      }

      console.log(`\n\x1b[31mMissing:\x1b[0m ${result.missing.length}`);
      for (const name of result.missing) {
        console.log(`  \x1b[31m✗\x1b[0m ${name}`);
      }
      process.exit(0);
      break;
    }

    case "platform": {
      const p = installer.platform;
      console.log("\x1b[1mPlatform Information:\x1b[0m");
      console.log(`  OS: ${p.os}`);
      console.log(`  Distro: ${p.distro} ${p.distroVersion}`);
      console.log(`  Arch: ${p.arch}`);
      console.log(`  Shell: ${p.shell}`);
      console.log(`  Hostname: ${p.hostname}`);
      console.log(`  Username: ${p.username}`);
      console.log(`  Home: ${p.homeDir}`);
      console.log(`  Config: ${p.configDir}`);
      console.log(`  Data: ${p.dataDir}`);
      console.log(`  Cache: ${p.cacheDir}`);
      console.log(`  Temp: ${p.tempDir}`);
      console.log(`  Root: ${p.isRoot}`);
      console.log(`  WSL: ${p.isWSL}`);
      console.log(`  Docker: ${p.isDocker}`);
      console.log(`  Pkg managers: ${p.packageManagers.join(", ")}`);
      console.log(`  Shell profiles: ${p.shellProfiles.join(", ")}`);
      process.exit(0);
      break;
    }

    case "config": {
      const config = installer.config.get();
      console.log(JSON.stringify(config, null, 2));
      process.exit(0);
      break;
    }

    case "logs": {
      const logFile = installer.logger.getLogFile();
      console.log(`Log file: ${logFile}`);
      const { readFileSync } = require("fs");
      try {
        console.log(readFileSync(logFile, "utf-8"));
      } catch {
        console.log("No logs found.");
      }
      process.exit(0);
      break;
    }

    case "uninstall": {
      const removeConfig = args.includes("--config");
      console.log("\x1b[34m⚡ Uninstalling...\x1b[0m\n");
      const result = await installer.uninstall(removeConfig);

      if (result.success) {
        console.log("\x1b[32m✓ Uninstall complete\x1b[0m");
      } else {
        console.log("\x1b[31m✗ Uninstall completed with errors\x1b[0m");
        for (const e of result.errors) {
          console.log(`  \x1b[31m${e}\x1b[0m`);
        }
      }
      process.exit(result.success ? 0 : 1);
      break;
    }

    case "update": {
      console.log("\x1b[34m⚡ Checking for updates...\x1b[0m\n");
      const result = await installer.update();
      if (result.success) {
        console.log(`\x1b[32m✓ ${result.message}\x1b[0m`);
      } else {
        console.log(`\x1b[31m✗ ${result.message}\x1b[0m`);
      }
      process.exit(result.success ? 0 : 1);
      break;
    }

    case "repair": {
      console.log("\x1b[34m⚡ Repairing installation...\x1b[0m\n");
      options.upgrade = true;
      const result = await installer.run(options);

      if (result.success) {
        console.log("\x1b[32m✓ Repair complete\x1b[0m");
      } else {
        console.log(
          `\x1b[31m✗ Repair completed with ${result.errors.length} error(s)\x1b[0m`
        );
      }
      process.exit(result.success ? 0 : 1);
      break;
    }

    default:
      console.error(`\x1b[31mUnknown command: ${command}\x1b[0m`);
      console.log("Run 'installer --help' for usage.");
      process.exit(1);
  }
}
