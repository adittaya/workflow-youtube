import { Box, Text } from "@opentui/react";
import type { Screen } from "../hooks/useAppState";

interface HeaderProps {
  activeScreen: Screen;
  syncing: boolean;
  accountCount: number;
  deployCount: number;
}

const SCREEN_LABELS: Record<Screen, string> = {
  dashboard: "Dashboard",
  deployments: "Deployments",
  accounts: "Accounts",
  analytics: "Analytics",
  settings: "Settings",
  sync: "Sync",
};

export function Header({
  activeScreen,
  syncing,
  accountCount,
  deployCount,
}: HeaderProps) {
  return (
    <box
      flexDirection="row"
      justifyContent="space-between"
      padding={1}
      style={{ borderBottom: true, borderColor: "#3b82f6" }}
    >
      <text>
        <span fg="#3b82f6" bold>
          VPLink
        </span>{" "}
        <span fg="#6b7280">
          v3.0 —{" "}
          {syncing ? (
            <span fg="#eab308">syncing...</span>
          ) : (
            SCREEN_LABELS[activeScreen]
          )}
        </span>
      </text>
      <text>
        <span fg="#6b7280">
          {accountCount} accts · {deployCount} deploys
        </span>
      </text>
    </box>
  );
}
