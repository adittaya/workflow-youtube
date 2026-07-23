import { execSync } from "child_process";
import type { UpdateInfo } from "./types";

export class UpdateChecker {
  private currentVersion: string;
  private owner: string;
  private repo: string;

  constructor(currentVersion: string, owner: string, repo: string) {
    this.currentVersion = currentVersion;
    this.owner = owner;
    this.repo = repo;
  }

  async checkForUpdate(): Promise<UpdateInfo> {
    try {
      const response = execSync(
        `curl -fsSL "https://api.github.com/repos/${this.owner}/${this.repo}/releases/latest"`,
        { encoding: "utf-8", timeout: 15000 }
      );
      const release = JSON.parse(response);
      const latestVersion = release.tag_name?.replace(/^v/, "") || "0.0.0";
      const updateAvailable = this.compareVersions(
        latestVersion,
        this.currentVersion
      );

      return {
        currentVersion: this.currentVersion,
        latestVersion,
        updateAvailable,
        downloadUrl: release.html_url,
        changelog: release.body || "",
      };
    } catch {
      return {
        currentVersion: this.currentVersion,
        latestVersion: this.currentVersion,
        updateAvailable: false,
      };
    }
  }

  async selfUpdate(): Promise<{ success: boolean; message: string }> {
    try {
      const info = await this.checkForUpdate();
      if (!info.updateAvailable) {
        return { success: true, message: "Already up to date" };
      }

      const downloadUrl = `https://github.com/${this.owner}/${this.repo}/releases/download/v${info.latestVersion}/installer-${process.platform}-${process.arch}`;
      const installPath = process.argv[0];

      execSync(
        `curl -fSL --retry 3 -o "${installPath}.new" "${downloadUrl}"`,
        { timeout: 120000 }
      );
      execSync(`chmod +x "${installPath}.new"`);
      execSync(`mv "${installPath}" "${installPath}.old"`);
      execSync(`mv "${installPath}.new" "${installPath}"`);

      return {
        success: true,
        message: `Updated from ${this.currentVersion} to ${info.latestVersion}`,
      };
    } catch (e: any) {
      return {
        success: false,
        message: `Update failed: ${e.message}`,
      };
    }
  }

  private compareVersions(a: string, b: string): boolean {
    const pa = a.split(".").map(Number);
    const pb = b.split(".").map(Number);
    for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
      const na = pa[i] || 0;
      const nb = pb[i] || 0;
      if (na > nb) return true;
      if (na < nb) return false;
    }
    return false;
  }
}
