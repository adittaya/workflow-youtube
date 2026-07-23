import { Box, Text } from "@opentui/react";
import type { AppState } from "../hooks/useAppState";
import { formatStatus } from "../services/deploy";
import { formatTimestamp } from "../utils/storage";

interface AnalyticsProps {
  state: AppState;
}

export function Analytics({ state }: AnalyticsProps) {
  const deployList = Object.values(state.deployments);
  const accountList = Object.values(state.accounts);

  const totalRuns = deployList.reduce((sum, d) => {
    return sum;
  }, 0);

  const statusBreakdown: Record<string, number> = {};
  for (const dep of deployList) {
    const s = formatStatus(dep.status);
    statusBreakdown[s.label] = (statusBreakdown[s.label] || 0) + 1;
  }

  return (
    <box flexDirection="column" padding={1} gap={1}>
      <text>
        <span fg="#3b82f6" bold>
          Analytics
        </span>
      </text>

      <box
        flexDirection="row"
        gap={3}
        style={{ borderBottom: true, borderColor: "#374151", paddingBottom: 1 }}
      >
        <box flexDirection="column" width="33%">
          <text>
            <span fg="#6b7280">Total Accounts</span>
          </text>
          <text>
            <span fg="#ffffff" bold>
              {accountList.length}
            </span>
          </text>
        </box>
        <box flexDirection="column" width="33%">
          <text>
            <span fg="#6b7280">Total Deployments</span>
          </text>
          <text>
            <span fg="#ffffff" bold>
              {deployList.length}
            </span>
          </text>
        </box>
        <box flexDirection="column" width="33%">
          <text>
            <span fg="#6b7280">Success Rate</span>
          </text>
          <text>
            <span fg="#22c55e" bold>
              {deployList.length > 0
                ? `${Math.round(
                    ((statusBreakdown["success"] || 0) +
                      (statusBreakdown["deployed"] || 0)) /
                      deployList.length *
                      100
                  )}%`
                : "N/A"}
            </span>
          </text>
        </box>
      </box>

      <box style={{ borderTop: true, borderColor: "#374151", paddingTop: 1 }}>
        <text>
          <span fg="#6b7280" bold>
            Status Breakdown
          </span>
        </text>
      </box>

      {Object.entries(statusBreakdown).length === 0 ? (
        <text>
          <span fg="#6b7280">No data yet.</span>
        </text>
      ) : (
        Object.entries(statusBreakdown).map(([status, count]) => {
          const s = formatStatus(status);
          const pct = Math.round((count / deployList.length) * 100);
          const barWidth = Math.round(pct / 2);
          return (
            <box key={status} flexDirection="row" gap={1}>
              <text width="20%">
                <span fg={s.color}>{status}</span>
              </text>
              <text width="6">
                <span fg="#ffffff">{count}</span>
              </text>
              <text>
                <span fg={s.color}>{"█".repeat(barWidth)}</span>
                <span fg="#374151">{"░".repeat(50 - barWidth)}</span>
              </text>
              <text width="5">
                <span fg="#6b7280">{pct}%</span>
              </text>
            </box>
          );
        })
      )}

      <box style={{ borderTop: true, borderColor: "#374151", paddingTop: 1 }}>
        <text>
          <span fg="#6b7280" bold>
            Per Account
          </span>
        </text>
      </box>

      {accountList.map((acct) => {
        const acctDeps = deployList.filter((d) => d.account === acct.name);
        return (
          <box key={acct.name} flexDirection="row" gap={2}>
            <text width="30%">
              <span fg="#ffffff">{acct.name}</span>
            </text>
            <text width="20%">
              <span fg="#6b7280">@{acct.username || "?"}</span>
            </text>
            <text>
              <span fg="#6b7280">{acctDeps.length} deployments</span>
            </text>
          </box>
        );
      })}
    </box>
  );
}
