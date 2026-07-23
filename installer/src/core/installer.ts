import type {
  PlatformInfo,
  PackageDefinition,
  InstallStep,
  InstallResult,
  VerificationResult,
} from "./types";
import { detectPlatform, getPrimaryPackageManager } from "./platform";
import { PackageInstaller, exec as pkgExec } from "./package-manager";
import { EnvironmentManager } from "./environment";
import { Downloader } from "./downloader";
import { ConfigManager } from "./config";
import { Logger } from "./logger";
import { RollbackManager, createPackageRollback } from "./rollback";
import { Verifier } from "./verification";
import { UpdateChecker } from "./update";
import {
  PACKAGE_REGISTRY,
  getPackageByName,
  getRequiredPackages,
} from "../packages/definitions";

export interface InstallerOptions {
  packages?: string[];
  skipRequired?: boolean;
  upgrade?: boolean;
  dryRun?: boolean;
  nonInteractive?: boolean;
  customPackages?: PackageDefinition[];
  envVars?: Record<string, string>;
  PATH?: string[];
}

export class Installer {
  platform: PlatformInfo;
  installer: PackageInstaller;
  environment: EnvironmentManager;
  downloader: Downloader;
  config: ConfigManager;
  logger: Logger;
  rollback: RollbackManager;
  verifier: Verifier;
  updater: UpdateChecker;
  steps: InstallStep[] = [];

  constructor() {
    this.platform = detectPlatform();
    this.config = new ConfigManager(this.platform);
    this.logger = new Logger(this.config.getLogDir(), "installer");
    this.installer = new PackageInstaller(this.platform);
    this.environment = new EnvironmentManager(this.platform);
    this.downloader = new Downloader(
      this.platform.cacheDir,
      this.platform.tempDir
    );
    this.rollback = new RollbackManager();
    this.verifier = new Verifier(this.platform);
    this.updater = new UpdateChecker(
      "1.0.0",
      "adittaya",
      "workflow-vplink"
    );
  }

  async run(options: InstallerOptions = {}): Promise<InstallResult> {
    const startTime = Date.now();
    const allSteps: InstallStep[] = [];
    const errors: string[] = [];
    const warnings: string[] = [];
    const installedPackages: string[] = [];
    const downloadedFiles: string[] = [];

    this.logger.info("Starting installer", {
      platform: this.platform.os,
      distro: this.platform.distro,
      arch: this.platform.arch,
      manager: this.installer.getManager(),
    });

    try {
      allSteps.push(this.createStep("detect-env", "Detect environment", "verify"));
      this.logger.info(
        `Detected: ${this.platform.os} ${this.platform.distro} ${this.platform.arch}`
      );
      allSteps[allSteps.length - 1].status = "success";

      if (options.envVars) {
        for (const [name, value] of Object.entries(options.envVars)) {
          this.config.setEnvVar(name, value);
        }
      }

      if (options.PATH) {
        for (const p of options.PATH) {
          this.config.addPath(p);
        }
      }

      const packages = this.resolvePackages(options);

      allSteps.push(
        this.createStep("update-index", "Update package index", "package")
      );
      await this.installer.updateIndex();
      allSteps[allSteps.length - 1].status = "success";

      for (const pkg of packages) {
        const step = this.createStep(
          `install-${pkg.name}`,
          `Installing ${pkg.displayName}`,
          "package"
        );
        allSteps.push(step);

        if (options.dryRun) {
          step.status = "skipped";
          continue;
        }

        const detectResult = this.installer.detectPackage(pkg);
        if (detectResult.installed && !options.upgrade) {
          this.logger.info(
            `${pkg.displayName} already installed (${detectResult.version})`
          );
          step.status = "skipped";
          continue;
        }

        const installCmd = this.installer.getInstallCommand(pkg);
        if (!installCmd) {
          this.logger.warn(
            `No install command for ${pkg.displayName} on ${this.installer.getManager()}`
          );
          step.status = "skipped";
          warnings.push(
            `No install command for ${pkg.displayName} on ${this.installer.getManager()}`
          );
          continue;
        }

        this.logger.info(`Installing ${pkg.displayName}...`);
        const result = await this.installer.install(pkg.name);

        if (result.success) {
          this.logger.success(`${pkg.displayName} installed`);
          step.status = "success";
          installedPackages.push(pkg.name);

          if (pkg.postInstall) {
            try {
              pkgExec(pkg.postInstall);
            } catch (e: any) {
              this.logger.warn(
                `Post-install script failed for ${pkg.displayName}: ${e.message}`
              );
            }
          }

          this.rollback.push(
            createPackageRollback(pkg.name, (name) =>
              this.installer.uninstall(name)
            )
          );

          if (pkg.verifyAfterInstall) {
            try {
              pkgExec(pkg.verifyAfterInstall);
            } catch (e: any) {
              warnings.push(
                `Verification failed for ${pkg.displayName}: ${e.message}`
              );
            }
          }
        } else {
          this.logger.error(
            `Failed to install ${pkg.displayName}: ${result.output}`
          );
          step.status = "error";
          step.error = result.output;
          errors.push(`Failed to install ${pkg.displayName}: ${result.output}`);
        }
      }

      allSteps.push(
        this.createStep("setup-env", "Configure environment", "env")
      );
      try {
        const installDir = this.config.getInstallDir();
        this.environment.addPath(installDir);

        for (const [name, value] of Object.entries(this.config.getEnvVars())) {
          this.environment.setEnvVar(name, value);
        }
        allSteps[allSteps.length - 1].status = "success";
      } catch (e: any) {
        allSteps[allSteps.length - 1].status = "error";
        allSteps[allSteps.length - 1].error = e.message;
        warnings.push(`Environment setup warning: ${e.message}`);
      }

      allSteps.push(
        this.createStep("verify", "Verify installation", "verify")
      );
      const verificationResults = this.verifier.checkAll(
        this.config.getPackages(),
        options.customPackages
      );
      const summary = this.verifier.getSummary(verificationResults);
      this.logger.info(
        `Verification: ${summary.installed}/${summary.total} installed`
      );
      allSteps[allSteps.length - 1].status = "success";

      allSteps.push(
        this.createStep("cleanup", "Cleanup", "script")
      );
      this.downloader.cleanTemp();
      this.installer.clean();
      allSteps[allSteps.length - 1].status = "success";

    } catch (e: any) {
      this.logger.error(`Installation failed: ${e.message}`);
      errors.push(e.message);

      if (!options.dryRun) {
        this.logger.info("Attempting rollback...");
        const rollbackResult = await this.rollback.rollback();
        if (!rollbackResult.success) {
          errors.push(...rollbackResult.errors);
        }
      }
    }

    const duration = Date.now() - startTime;

    return {
      success: errors.length === 0,
      steps: allSteps,
      errors,
      warnings,
      duration,
      installedPackages,
      downloadedFiles,
    };
  }

  private resolvePackages(options: InstallerOptions): PackageDefinition[] {
    const packages: PackageDefinition[] = [];
    const packageNames = options.packages || this.config.getPackages();

    for (const name of packageNames) {
      if (name.startsWith("custom:")) {
        const customName = name.slice(7);
        const custom = (options.customPackages || []).find(
          (p) => p.name === customName
        );
        if (custom) packages.push(custom);
        continue;
      }

      const pkg = getPackageByName(name);
      if (pkg) {
        if (pkg.required && options.skipRequired) continue;
        packages.push(pkg);
      }
    }

    if (options.customPackages) {
      packages.push(...options.customPackages);
    }

    return packages;
  }

  private createStep(
    id: string,
    name: string,
    type: InstallStep["type"]
  ): InstallStep {
    return { id, name, type, status: "pending" };
  }

  async doctor(): Promise<{
    platform: PlatformInfo;
    packages: VerificationResult[];
    config: any;
    issues: string[];
  }> {
    const packages = this.verifier.checkAll(this.config.getPackages());
    const issues: string[] = [];

    if (!this.platform.packageManagers.length) {
      issues.push("No package manager detected");
    }

    for (const pkg of getRequiredPackages()) {
      const result = this.verifier.checkPackage(pkg.name);
      if (!result.installed) {
        issues.push(`Required package missing: ${pkg.displayName}`);
      }
    }

    return {
      platform: this.platform,
      packages,
      config: this.config.get(),
      issues,
    };
  }

  async verify(): Promise<VerificationResult[]> {
    return this.verifier.checkAll(this.config.getPackages());
  }

  async uninstall(removeConfig: boolean = false): Promise<{
    success: boolean;
    errors: string[];
  }> {
    const errors: string[] = [];
    const installed = await this.installer.listInstalled();

    for (const pkg of installed) {
      if (this.config.getPackages().includes(pkg.name)) {
        const result = await this.installer.uninstall(pkg.name);
        if (!result.success) {
          errors.push(`Failed to uninstall ${pkg.name}: ${result.output}`);
        }
      }
    }

    if (removeConfig) {
      try {
        const { rmSync } = require("fs");
        rmSync(this.config.getConfigDir(), { recursive: true, force: true });
      } catch (e: any) {
        errors.push(`Failed to remove config: ${e.message}`);
      }
    }

    return { success: errors.length === 0, errors };
  }

  async status(): Promise<{
    installed: string[];
    missing: string[];
    config: any;
  }> {
    const packages = this.config.getPackages();
    const installed: string[] = [];
    const missing: string[] = [];

    for (const name of packages) {
      const pkg = getPackageByName(name);
      if (pkg) {
        const result = this.installer.detectPackage(pkg);
        if (result.installed) {
          installed.push(name);
        } else {
          missing.push(name);
        }
      }
    }

    return {
      installed,
      missing,
      config: this.config.get(),
    };
  }

  async update(): Promise<{
    success: boolean;
    message: string;
  }> {
    return this.updater.selfUpdate();
  }
}
