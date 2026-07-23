import { describe, it, expect, test } from "bun:test";
import { detectPlatform, getPrimaryPackageManager } from "../src/core/platform";
import {
  PACKAGE_REGISTRY,
  getPackageByName,
  getPackagesByCategory,
  searchPackages,
} from "../src/packages/definitions";
import { Verifier } from "../src/core/verification";

describe("Platform Detection", () => {
  it("should detect a valid OS", () => {
    const platform = detectPlatform();
    expect(["linux", "macos", "windows", "termux"]).toContain(platform.os);
  });

  it("should detect architecture", () => {
    const platform = detectPlatform();
    expect(["x64", "arm64", "armv7", "armv6", "x86", "unknown"]).toContain(
      platform.arch
    );
  });

  it("should detect shell", () => {
    const platform = detectPlatform();
    expect(["bash", "zsh", "fish", "powershell", "cmd", "unknown"]).toContain(
      platform.shell
    );
  });

  it("should have home directory", () => {
    const platform = detectPlatform();
    expect(platform.homeDir).toBeTruthy();
  });

  it("should have config directory", () => {
    const platform = detectPlatform();
    expect(platform.configDir).toBeTruthy();
  });
});

describe("Package Manager", () => {
  it("should detect a package manager", () => {
    const platform = detectPlatform();
    const manager = getPrimaryPackageManager(platform.packageManagers);
    expect(manager).not.toBe("unknown");
  });
});

describe("Package Registry", () => {
  it("should have packages defined", () => {
    expect(PACKAGE_REGISTRY.length).toBeGreaterThan(0);
  });

  it("should find git package", () => {
    const git = getPackageByName("git");
    expect(git).toBeDefined();
    expect(git?.name).toBe("git");
    expect(git?.displayName).toBe("Git");
  });

  it("should find packages by category", () => {
    const corePkgs = getPackagesByCategory("core");
    expect(corePkgs.length).toBeGreaterThan(0);
    for (const pkg of corePkgs) {
      expect(pkg.category).toBe("core");
    }
  });

  it("should search packages", () => {
    const results = searchPackages("python");
    expect(results.length).toBeGreaterThan(0);
    expect(results.some((p) => p.name === "python3")).toBe(true);
  });

  it("should have install commands for all managers", () => {
    for (const pkg of PACKAGE_REGISTRY) {
      expect(pkg.install).toBeDefined();
      expect(typeof pkg.install).toBe("object");
    }
  });

  it("should have detect commands", () => {
    for (const pkg of PACKAGE_REGISTRY) {
      expect(pkg.detectCommand).toBeTruthy();
    }
  });
});

describe("Verification", () => {
  it("should detect git if installed", () => {
    const platform = detectPlatform();
    const verifier = new Verifier(platform);
    const result = verifier.checkPackage("git");
    expect(result.name).toBe("git");
    expect(typeof result.installed).toBe("boolean");
  });

  it("should verify multiple packages", () => {
    const platform = detectPlatform();
    const verifier = new Verifier(platform);
    const results = verifier.checkAll(["git", "curl"]);
    expect(results.length).toBe(2);
    for (const r of results) {
      expect(r.name).toBeTruthy();
      expect(typeof r.installed).toBe("boolean");
    }
  });

  it("should compute summary", () => {
    const platform = detectPlatform();
    const verifier = new Verifier(platform);
    const results = verifier.checkAll(["git", "curl", "node"]);
    const summary = verifier.getSummary(results);
    expect(summary.total).toBe(3);
    expect(summary.installed + summary.missing).toBe(3);
  });
});
