import { Box, Text } from "@opentui/react";
import type { InstallStep, VerificationResult, PlatformInfo } from "../core/types";

interface HeaderProps {
  version: string;
}

export function Header({ version }: HeaderProps) {
  return (
    <box
      flexDirection="row"
      justifyContent="space-between"
      padding={1}
      style={{ borderBottom: true, borderColor: "#3b82f6" }}
    >
      <text>
        <span fg="#3b82f6" bold>
          ⚡ Installer
        </span>{" "}
        <span fg="#6b7280">v{version}</span>
      </text>
      <text>
        <span fg="#6b7280">Production-Grade Bootstrap</span>
      </text>
    </box>
  );
}

interface ProgressProps {
  steps: InstallStep[];
  currentStep?: string;
}

export function Progress({ steps, currentStep }: ProgressProps) {
  return (
    <box flexDirection="column" gap={0}>
      {steps.map((step) => {
        const icon =
          step.status === "success"
            ? "\u001b[32m\u2713\u001b[0m"
            : step.status === "error"
              ? "\u001b[31m\u2717\u001b[0m"
              : step.status === "running"
                ? "\u001b[33m\u25cb\u001b[0m"
                : step.status === "skipped"
                  ? "\u001b[90m\u2014\u001b[0m"
                  : "\u001b[90m\u25cb\u001b[0m";

        const color =
          step.status === "success"
            ? "#22c55e"
            : step.status === "error"
              ? "#ef4444"
              : step.status === "running"
                ? "#eab308"
                : "#6b7280";

        return (
          <box key={step.id} flexDirection="row" gap={1}>
            <text width={3}>
              <span fg={color}>{icon}</span>
            </text>
            <text>
              <span fg={color}>{step.name}</span>
              {step.error && (
                <span fg="#ef4444"> — {step.error.slice(0, 60)}</span>
              )}
            </text>
          </box>
        );
      })}
    </box>
  );
}

interface PlatformInfoProps {
  platform: PlatformInfo;
}

export function PlatformDisplay({ platform }: PlatformInfoProps) {
  const items = [
    { label: "OS", value: platform.os },
    { label: "Distro", value: platform.distro },
    { label: "Arch", value: platform.arch },
    { label: "Shell", value: platform.shell },
    { label: "Pkg Manager", value: platform.packageManagers.join(", ") || "none" },
    { label: "Root", value: platform.isRoot ? "yes" : "no" },
    { label: "WSL", value: platform.isWSL ? "yes" : "no" },
    { label: "Docker", value: platform.isDocker ? "yes" : "no" },
  ];

  return (
    <box flexDirection="column" gap={0}>
      {items.map((item) => (
        <box key={item.label} flexDirection="row" gap={1}>
          <text width={15}>
            <span fg="#6b7280">{item.label}:</span>
          </text>
          <text>
            <span fg="#ffffff">{item.value}</span>
          </text>
        </box>
      ))}
    </box>
  );
}

interface VerificationDisplayProps {
  results: VerificationResult[];
}

export function VerificationDisplay({ results }: VerificationDisplayProps) {
  return (
    <box flexDirection="column" gap={0}>
      {results.map((r) => (
        <box key={r.name} flexDirection="row" gap={1}>
          <text width={3}>
            <span fg={r.installed ? "#22c55e" : "#ef4444"}>
              {r.installed ? "\u2713" : "\u2717"}
            </span>
          </text>
          <text width={20}>
            <span fg="#ffffff">{r.name}</span>
          </text>
          <text width={15}>
            <span fg="#6b7280">{r.version || "not installed"}</span>
          </text>
          <text>
            <span fg={r.status === "ok" ? "#22c55e" : "#eab308"}>
              {r.status}
            </span>
          </text>
        </box>
      ))}
    </box>
  );
}

interface StatusSummaryProps {
  installed: number;
  missing: number;
  total: number;
  duration?: number;
}

export function StatusSummary({
  installed,
  missing,
  total,
  duration,
}: StatusSummaryProps) {
  return (
    <box
      flexDirection="row"
      gap={3}
      style={{ borderTop: true, borderColor: "#374151", paddingTop: 1 }}
    >
      <text>
        <span fg="#22c55e">{installed}</span>
        <span fg="#6b7280"> installed</span>
      </text>
      <text>
        <span fg="#ef4444">{missing}</span>
        <span fg="#6b7280"> missing</span>
      </text>
      <text>
        <span fg="#6b7280">{total} total</span>
      </text>
      {duration !== undefined && (
        <text>
          <span fg="#6b7280">{(duration / 1000).toFixed(1)}s</span>
        </text>
      )}
    </box>
  );
}
