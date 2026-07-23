import { execSync } from "child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync, statSync } from "fs";
import { join } from "path";
import { createHash } from "crypto";
import type { DownloadSpec } from "./types";

export class Downloader {
  private cacheDir: string;
  private tempDir: string;

  constructor(cacheDir: string, tempDir: string) {
    this.cacheDir = cacheDir;
    this.tempDir = tempDir;
    mkdirSync(cacheDir, { recursive: true });
    mkdirSync(tempDir, { recursive: true });
  }

  private exec(cmd: string, timeout: number = 300000): string {
    try {
      return execSync(cmd, {
        encoding: "utf-8",
        timeout,
        stdio: ["pipe", "pipe", "pipe"],
      }).trim();
    } catch (e: any) {
      throw new Error(`Command failed: ${cmd}\n${e.message}`);
    }
  }

  private getCachePath(spec: DownloadSpec): string {
    const ext = spec.archiveType ? `.${spec.archiveType}` : "";
    const filename = `${spec.name}-${spec.version}${ext}`;
    return join(this.cacheDir, filename);
  }

  async download(
    spec: DownloadSpec,
    onProgress?: (percent: number) => void
  ): Promise<string> {
    const cachePath = this.getCachePath(spec);

    if (existsSync(cachePath)) {
      if (spec.sha256) {
        const hash = this.sha256(cachePath);
        if (hash === spec.sha256) {
          return cachePath;
        }
      } else {
        return cachePath;
      }
    }

    const tempPath = join(this.tempDir, `${spec.name}-${spec.version}-download`);

    try {
      this.exec(`curl -fSL --retry 3 --retry-delay 2 -o "${tempPath}" "${spec.url}"`, 600000);

      if (spec.sha256) {
        const hash = this.sha256(tempPath);
        if (hash !== spec.sha256) {
          throw new Error(
            `Checksum mismatch: expected ${spec.sha256}, got ${hash}`
          );
        }
      }

      if (spec.size) {
        const actualSize = statSync(tempPath).size;
        if (actualSize !== spec.size) {
          throw new Error(
            `Size mismatch: expected ${spec.size}, got ${actualSize}`
          );
        }
      }

      this.exec(`cp "${tempPath}" "${cachePath}"`);
      this.exec(`rm -f "${tempPath}"`);

      return cachePath;
    } catch (e: any) {
      this.exec(`rm -f "${tempPath}"`, 5000);
      throw e;
    }
  }

  async downloadFromGitHub(
    owner: string,
    repo: string,
    version: string,
    filename: string
  ): Promise<string> {
    const url = `https://github.com/${owner}/${repo}/releases/download/${version}/${filename}`;
    const spec: DownloadSpec = {
      url,
      name: `${repo}`,
      version,
      type: "binary",
    };
    return this.download(spec);
  }

  async extract(
    archivePath: string,
    destDir: string,
    type?: string
  ): Promise<string> {
    mkdirSync(destDir, { recursive: true });

    const archiveType =
      type ||
      (archivePath.endsWith(".tar.gz")
        ? "tar.gz"
        : archivePath.endsWith(".tar.xz")
          ? "tar.xz"
          : archivePath.endsWith(".tar.bz2")
            ? "tar.bz2"
            : archivePath.endsWith(".zip")
              ? "zip"
              : "tar.gz");

    switch (archiveType) {
      case "tar.gz":
      case "tar.xz":
      case "tar.bz2":
        this.exec(`tar xf "${archivePath}" -C "${destDir}" --strip-components=0`);
        break;
      case "zip":
        this.exec(`unzip -o "${archivePath}" -d "${destDir}"`);
        break;
      default:
        this.exec(`tar xf "${archivePath}" -C "${destDir}"`);
    }

    return destDir;
  }

  async installBinary(
    sourcePath: string,
    installPath: string,
    executable: boolean = true
  ): Promise<void> {
    const dir = installPath.substring(0, installPath.lastIndexOf("/"));
    mkdirSync(dir, { recursive: true });
    this.exec(`cp "${sourcePath}" "${installPath}"`);
    if (executable) {
      this.exec(`chmod +x "${installPath}"`);
    }
  }

  private sha256(filePath: string): string {
    const content = readFileSync(filePath);
    return createHash("sha256").update(content).digest("hex");
  }

  verifyDownload(filePath: string, expectedSha256?: string): boolean {
    if (!existsSync(filePath)) return false;
    if (!expectedSha256) return true;
    return this.sha256(filePath) === expectedSha256;
  }

  cleanTemp(): void {
    try {
      this.exec(`rm -rf "${this.tempDir}"/*`, 10000);
    } catch {
      /* ignore */
    }
  }

  async downloadConfig(
    url: string,
    destPath: string
  ): Promise<void> {
    const dir = destPath.substring(0, destPath.lastIndexOf("/"));
    mkdirSync(dir, { recursive: true });
    this.exec(`curl -fSL --retry 3 -o "${destPath}" "${url}"`, 60000);
  }
}
