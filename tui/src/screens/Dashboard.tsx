import { Box, Text } from "@opentui/react";
import type { AppState } from "../hooks/useAppState";
import { formatStatus, type LocalDeployment } from "../services/deploy";
import { formatTimestamp } from "../utils/storage";

interface DashboardProps {
  state: AppState;
}

export function Dashboard({ state }: DashboardProps) {
  const { accounts, deployments, settings, lastSync } = state;
  const accountList = Object.values(accounts);
  const deployList = Object.values(deployments);

  const statusCounts = {
    success: 0,
    error: 0,
    in_progress: 0,
    deployed: 0,
    stopped: 0,
    imported: 0,
    other: 0,
  };
  for (const dep of deployList) {
    const s = formatStatus(dep.status);
    if (s.label in statusCounts) {
      (statusCounts as any)[s.label]++;
    } else {
      statusCounts.other++;
    }
  }

  return (
    <box flexDirection="column" padding={1} gap={1}>
      <text>
        <span fg="#3b82f6" bold>
          Dashboard
        </span>
      </text>

      <box
        flexDirection="row"
        gap={2}
        style={{ borderBottom: true, borderColor: "#374151", paddingBottom: 1 }}
      >
        <box flexDirection="column" width="25%">
          <text>
            <span fg="#6b7280">Accounts</span>
          </text>
          <text>
            <span fg="#ffffff" bold>
              {accountList.length}
            </span>
          </text>
        </box>
        <box flexDirection="column" width="25%">
          <text>
            <span fg="#6b7280">Deployments</span>
          </text>
          <text>
            <span fg="#ffffff" bold>
              {deployList.length}
            </span>
          </text>
        </box>
        <box flexDirection="column" width="25%">
          <text>
            <span fg="#6b7280">Active</span>
          </text>
          <text>
            <span fg="#22c55e" bold>
              {statusCounts.success + statusCounts.deployed}
            </span>
          </text>
        </box>
        <box flexDirection="column" width="25%">
          <text>
            <span fg="#6b7280">Errors</span>
          </text>
          <text>
            <span fg="#ef4444" bold>
              {statusCounts.error}
            </span>
          </text>
        </box>
      </box>

      {settings.active_account && (
        <box>
          <text>
            <span fg="#6b7280">Active: </span>
            <span fg="#22c55e">{settings.active_account}</span>
          </text>
        </box>
      )}

      {lastSync && (
        <box>
          <text>
            <span fg="#6b7280">Last sync: </span>
            <span fg="#9ca3af">{formatTimestamp(lastSync)}</span>
          </text>
        </box>
      )}

      <box style={{ borderTop: true, borderColor: "#374151", paddingTop: 1 }}>
        <text>
          <span fg="#6b7280" bold>
            Recent Deployments
          </span>
        </text>
      </box>

      {deployList.length === 0 ? (
        <text>
          <span fg="#6b7280">
            No deployments yet. Press [6] to sync from GitHub or [2] to deploy.
          </span>
        </text>
      ) : (
        deployList.slice(0, 10).map((dep) => {
          const s = formatStatus(dep.status);
          return (
            <box key={dep.name} flexDirection="row" gap={2}>
              <text>
                <span fg={s.color}>●</span>
              </text>
              <text width="40%">
                <span fg="#ffffff">{dep.name}</span>
              </text>
              <text width="15%">
                <span fg="#6b7280">{dep.account}</span>
              </text>
              <text width="10%">
                <span fg="#6b7280">{dep.key}</span>
              </text>
              <text>
                <span fg={s.color}>{s.label}</span>
              </text>
            </box>
          );
        })
      )}
    </box>
  );
}
