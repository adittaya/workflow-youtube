import { Box, Text, useKeyboard } from "@opentui/react";
import { useState, useEffect, useCallback } from "react";
import { Installer, InstallerOptions } from "../core/installer";
import type { InstallStep, VerificationResult, PlatformInfo } from "../core/types";
import { PACKAGE_REGISTRY, getPackageByName } from "../packages/definitions";
import {
  Header,
  Progress,
  PlatformDisplay,
  VerificationDisplay,
  StatusSummary,
} from "./components";

type Screen =
  | "welcome"
  | "platform"
  | "packages"
  | "installing"
  | "results"
  | "doctor"
  | "verify"
  | "status";

export function InstallerApp() {
  const [screen, setScreen] = useState<Screen>("welcome");
  const [installer] = useState(() => new Installer());
  const [steps, setSteps] = useState<InstallStep[]>([]);
  const [selectedPackages, setSelectedPackages] = useState<string[]>(
    installer.config.getPackages()
  );
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [installResult, setInstallResult] = useState<any>(null);
  const [verifyResults, setVerifyResults] = useState<VerificationResult[]>([]);
  const [doctorResult, setDoctorResult] = useState<any>(null);
  const [statusResult, setStatusResult] = useState<any>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [messageType, setMessageType] = useState<"info" | "success" | "error">(
    "info"
  );

  useKeyboard((key) => {
    if (key.name === "escape") {
      if (screen === "welcome") {
        process.exit(0);
      }
      setScreen("welcome");
      setMessage(null);
    }

    switch (screen) {
      case "welcome":
        if (key.name === "1") setScreen("platform");
        else if (key.name === "2") setScreen("packages");
        else if (key.name === "3") runInstall();
        else if (key.name === "4") runDoctor();
        else if (key.name === "5") runVerify();
        else if (key.name === "6") runStatus();
        else if (key.name === "u") runUpdate();
        break;

      case "platform":
        break;

      case "packages":
        if (key.name === "up" || key.name === "k") {
          setSelectedIndex((i) => Math.max(0, i - 1));
        } else if (key.name === "down" || key.name === "j") {
          setSelectedIndex((i) =>
            Math.min(PACKAGE_REGISTRY.length - 1, i + 1)
          );
        } else if (key.name === "space" || key.name === "return") {
          const pkg = PACKAGE_REGISTRY[selectedIndex];
          if (pkg) {
            setSelectedPackages((prev) => {
              if (prev.includes(pkg.name)) {
                return prev.filter((p) => p !== pkg.name);
              }
              return [...prev, pkg.name];
            });
          }
        } else if (key.name === "a") {
          setSelectedPackages(PACKAGE_REGISTRY.map((p) => p.name));
        } else if (key.name === "n") {
          setSelectedPackages([]);
        }
        break;
    }
  });

  const runInstall = useCallback(async () => {
    setScreen("installing");
    setSteps([]);

    const options: InstallerOptions = {
      packages: selectedPackages,
      nonInteractive: true,
    };

    const result = await installer.run(options);
    setInstallResult(result);
    setSteps(result.steps);
    setScreen("results");
    setMessage(
      result.success ? "Installation complete!" : "Installation completed with errors",
      result.success ? "success" : "error"
    );
  }, [installer, selectedPackages]);

  const runDoctor = useCallback(async () => {
    setScreen("doctor");
    const result = await installer.doctor();
    setDoctorResult(result);
  }, [installer]);

  const runVerify = useCallback(async () => {
    setScreen("verify");
    const result = await installer.verify();
    setVerifyResults(result);
  }, [installer]);

  const runStatus = useCallback(async () => {
    setScreen("status");
    const result = await installer.status();
    setStatusResult(result);
  }, [installer]);

  const runUpdate = useCallback(async () => {
    setMessage("Checking for updates...", "info");
    const result = await installer.update();
    setMessage(result.message, result.success ? "success" : "error");
  }, [installer]);

  const renderWelcome = () => (
    <box flexDirection="column" padding={1} gap={1}>
      <text>
        <span fg="#3b82f6" bold>
          Welcome to Installer
        </span>
      </text>
      <text>
        <span fg="#9ca3af">
          Production-grade cross-platform bootstrap installer
        </span>
      </text>
      <box height={1} />
      <box style={{ borderTop: true, borderColor: "#374151", paddingTop: 1 }}>
        <text>
          <span fg="#6b7280">Commands</span>
        </text>
      </box>
      <box flexDirection="row" gap={2}>
        <text>
          <span fg="#6b7280">[1]</span>
        </text>
        <text>
          <span fg="#ffffff">Platform Info</span>
        </text>
      </box>
      <box flexDirection="row" gap={2}>
        <text>
          <span fg="#6b7280">[2]</span>
        </text>
        <text>
          <span fg="#ffffff">Select Packages</span>
        </text>
      </box>
      <box flexDirection="row" gap={2}>
        <text>
          <span fg="#6b7280">[3]</span>
        </text>
        <text>
          <span fg="#22c55e">Install Selected</span>
        </text>
      </box>
      <box flexDirection="row" gap={2}>
        <text>
          <span fg="#6b7280">[4]</span>
        </text>
        <text>
          <span fg="#ffffff">Doctor</span>
        </text>
      </box>
      <box flexDirection="row" gap={2}>
        <text>
          <span fg="#6b7280">[5]</span>
        </text>
        <text>
          <span fg="#ffffff">Verify</span>
        </text>
      </box>
      <box flexDirection="row" gap={2}>
        <text>
          <span fg="#6b7280">[6]</span>
        </text>
        <text>
          <span fg="#ffffff">Status</span>
        </text>
      </box>
      <box flexDirection="row" gap={2}>
        <text>
          <span fg="#6b7280">[U]</span>
        </text>
        <text>
          <span fg="#ffffff">Check Updates</span>
        </text>
      </box>
      <box height={1} />
      <text>
        <span fg="#6b7280">ESC</span> <span fg="#4b5563">quit</span>
      </text>
      {message && (
        <box>
          <text>
            <span
              fg={
                messageType === "success"
                  ? "#22c55e"
                  : messageType === "error"
                    ? "#ef4444"
                    : "#3b82f6"
              }
            >
              {messageType === "success" ? "\u2713" : messageType === "error" ? "\u2717" : "\u2139"}{" "}
              {message}
            </span>
          </text>
        </box>
      )}
    </box>
  );

  const renderPlatform = () => (
    <box flexDirection="column" padding={1} gap={1}>
      <text>
        <span fg="#3b82f6" bold>
          Platform Information
        </span>
      </text>
      <box height={1} />
      <PlatformDisplay platform={installer.platform} />
      <box height={1} />
      <text>
        <span fg="#6b7280">ESC</span> <span fg="#4b5563">back</span>
      </text>
    </box>
  );

  const renderPackages = () => (
    <box flexDirection="column" padding={1} gap={1}>
      <text>
        <span fg="#3b82f6" bold>
          Select Packages ({selectedPackages.length} selected)
        </span>
      </text>
      <box
        flexDirection="row"
        gap={2}
        style={{ borderBottom: true, borderColor: "#374151", paddingBottom: 1 }}
      >
        <text>
          <span fg="#6b7280">[Space]</span> toggle
        </text>
        <text>
          <span fg="#6b7280">[A]</span> all
        </text>
        <text>
          <span fg="#6b7280">[N]</span> none
        </text>
        <text>
          <span fg="#6b7280">[3]</span> install
        </text>
      </box>
      {PACKAGE_REGISTRY.map((pkg, i) => {
        const isSelected = i === selectedIndex;
        const isChecked = selectedPackages.includes(pkg.name);
        return (
          <box key={pkg.name} flexDirection="row" gap={1}>
            <text width={3}>
              <span fg={isSelected ? "#3b82f6" : "#6b7280"}>
                {isSelected ? "\u25b6" : " "}
              </span>
            </text>
            <text width={3}>
              <span fg={isChecked ? "#22c55e" : "#6b7280"}>
                {isChecked ? "[\u2713]" : "[ ]"}
              </span>
            </text>
            <text width={20}>
              <span fg={isChecked ? "#ffffff" : "#9ca3af"}>
                {pkg.displayName}
              </span>
            </text>
            <text>
              <span fg="#6b7280">{pkg.description}</span>
            </text>
          </box>
        );
      })}
    </box>
  );

  const renderInstalling = () => (
    <box flexDirection="column" padding={1} gap={1}>
      <text>
        <span fg="#eab308" bold>
          Installing...
        </span>
      </text>
      <box height={1} />
      <Progress steps={steps} />
    </box>
  );

  const renderResults = () => (
    <box flexDirection="column" padding={1} gap={1}>
      <text>
        <span
          fg={installResult?.success ? "#22c55e" : "#ef4444"}
          bold
        >
          {installResult?.success ? "Installation Complete" : "Installation Failed"}
        </span>
      </text>
      <box height={1} />
      <Progress steps={installResult?.steps || []} />
      <box height={1} />
      {installResult?.errors?.length > 0 && (
        <box flexDirection="column">
          <text>
            <span fg="#ef4444" bold>
              Errors:
            </span>
          </text>
          {installResult.errors.map((e: string, i: number) => (
            <text key={i}>
              <span fg="#ef4444">{e.slice(0, 80)}</span>
            </text>
          ))}
        </box>
      )}
      {installResult?.warnings?.length > 0 && (
        <box flexDirection="column">
          <text>
            <span fg="#eab308" bold>
              Warnings:
            </span>
          </text>
          {installResult.warnings.map((w: string, i: number) => (
            <text key={i}>
              <span fg="#eab308">{w.slice(0, 80)}</span>
            </text>
          ))}
        </box>
      )}
      <StatusSummary
        installed={installResult?.installedPackages?.length || 0}
        missing={installResult?.errors?.length || 0}
        total={installResult?.steps?.length || 0}
        duration={installResult?.duration}
      />
      <box height={1} />
      <text>
        <span fg="#6b7280">ESC</span> <span fg="#4b5563">back to menu</span>
      </text>
    </box>
  );

  const renderDoctor = () => (
    <box flexDirection="column" padding={1} gap={1}>
      <text>
        <span fg="#3b82f6" bold>
          System Doctor
        </span>
      </text>
      <box height={1} />
      {doctorResult && (
        <>
          <PlatformDisplay platform={doctorResult.platform} />
          <box height={1} />
          <text>
            <span fg="#6b7280" bold>
              Package Status:
            </span>
          </text>
          <VerificationDisplay results={doctorResult.packages} />
          {doctorResult.issues.length > 0 && (
            <box flexDirection="column">
              <text>
                <span fg="#ef4444" bold>
                  Issues:
                </span>
              </text>
              {doctorResult.issues.map((issue: string, i: number) => (
                <text key={i}>
                  <span fg="#ef4444">{issue}</span>
                </text>
              ))}
            </box>
          )}
        </>
      )}
      <box height={1} />
      <text>
        <span fg="#6b7280">ESC</span> <span fg="#4b5563">back</span>
      </text>
    </box>
  );

  const renderVerify = () => (
    <box flexDirection="column" padding={1} gap={1}>
      <text>
        <span fg="#3b82f6" bold>
          Verify Installation
        </span>
      </text>
      <box height={1} />
      <VerificationDisplay results={verifyResults} />
      <StatusSummary
        installed={verifyResults.filter((r) => r.installed).length}
        missing={verifyResults.filter((r) => !r.installed).length}
        total={verifyResults.length}
      />
      <box height={1} />
      <text>
        <span fg="#6b7280">ESC</span> <span fg="#4b5563">back</span>
      </text>
    </box>
  );

  const renderStatus = () => (
    <box flexDirection="column" padding={1} gap={1}>
      <text>
        <span fg="#3b82f6" bold>
          System Status
        </span>
      </text>
      <box height={1} />
      {statusResult && (
        <>
          <text>
            <span fg="#22c55e">
              Installed: {statusResult.installed.length}
            </span>
          </text>
          <text>
            <span fg="#ef4444">
              Missing: {statusResult.missing.length}
            </span>
          </text>
          {statusResult.missing.length > 0 && (
            <box flexDirection="column">
              <text>
                <span fg="#6b7280" bold>
                  Missing packages:
                </span>
              </text>
              {statusResult.missing.map((name: string, i: number) => (
                <text key={i}>
                  <span fg="#ef4444">{name}</span>
                </text>
              ))}
            </box>
          )}
        </>
      )}
      <box height={1} />
      <text>
        <span fg="#6b7280">ESC</span> <span fg="#4b5563">back</span>
      </text>
    </box>
  );

  return (
    <box flexDirection="column" style={{ width: "100%", height: "100%" }}>
      <Header version="1.0.0" />
      <box style={{ flexGrow: 1 }}>
        {screen === "welcome" && renderWelcome()}
        {screen === "platform" && renderPlatform()}
        {screen === "packages" && renderPackages()}
        {screen === "installing" && renderInstalling()}
        {screen === "results" && renderResults()}
        {screen === "doctor" && renderDoctor()}
        {screen === "verify" && renderVerify()}
        {screen === "status" && renderStatus()}
      </box>
    </box>
  );
}
