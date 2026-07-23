import { Box, Text, useKeyboard } from "@opentui/react";
import { useState } from "react";
import type { AppState } from "../hooks/useAppState";
import { formatStatus } from "../services/deploy";
import { formatTimestamp } from "../utils/storage";

interface SyncProps {
  state: AppState;
  onSync: () => void;
}

export function Sync({ state, onSync }: SyncProps) {
  const deployList = Object.values(state.deployments);

  useKeyboard((key) => {
    if (key.name === "r" && !state.syncing) {
      onSync();
    }
  });

  return (
    <box flexDirection="column" padding={1} gap={1}>
      <text>
        <span fg="#3b82f6" bold>
          GitHub Sync
        </span>
      </text>

      <box
        flexDirection="row"
        gap={2}
        style={{ borderBottom: true, borderColor: "#374151", paddingBottom: 1 }}
      >
        <text>
          <span fg="#6b7280">[R]</span> sync now
        </text>
        {state.lastSync && (
          <text>
            <span fg="#6b7280">
              Last: {formatTimestamp(state.lastSync)}
            </span>
          </text>
        )}
      </box>

      {state.syncing && (
        <box>
          <text>
            <span fg="#eab308">⟳ Syncing from GitHub...</span>
          </text>
        </box>
      )}

      {state.message && state.messageType && (
        <box>
          <text>
            <span
              fg={
                state.messageType === "success"
                  ? "#22c55e"
                  : state.messageType === "error"
                    ? "#ef4444"
                    : "#3b82f6"
              }
            >
              {state.messageType === "success" ? "✓" : state.messageType === "error" ? "✗" : "ℹ"}{" "}
              {state.message}
            </span>
          </text>
        </box>
      )}

      <box style={{ borderTop: true, borderColor: "#374151", paddingTop: 1 }}>
        <text>
          <span fg="#6b7280" bold>
            Repos as Database
          </span>
        </text>
      </box>

      <text>
        <span fg="#9ca3af">
          GitHub repos ARE the database. Any environment can sync — TUI or web
          UI.
        </span>
      </text>

      <box height={1} />

      <box style={{ borderTop: true, borderColor: "#374151", paddingTop: 1 }}>
        <text>
          <span fg="#6b7280" bold>
            All Deployments ({deployList.length})
          </span>
        </text>
      </box>

      {deployList.length === 0 ? (
        <text>
          <span fg="#6b7280">No deployments found. Press [R] to sync.</span>
        </text>
      ) : (
        deployList.map((dep) => {
          const s = formatStatus(dep.status);
          return (
            <box key={dep.name} flexDirection="row" gap={2}>
              <text>
                <span fg={s.color}>●</span>
              </text>
              <text width="35%">
                <span fg="#ffffff">{dep.name}</span>
              </text>
              <text width="15%">
                <span fg="#6b7280">{dep.account}</span>
              </text>
              <text width="10%">
                <span fg="#6b7280">{dep.key}</span>
              </text>
              <text width="15%">
                <span fg="#6b7280">
                  {formatTimestamp(dep.created_at)}
                </span>
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
