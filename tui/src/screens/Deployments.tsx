import { Box, Text, useKeyboard } from "@opentui/react";
import { useState, useCallback } from "react";
import type { AppState } from "../hooks/useAppState";
import { formatStatus } from "../services/deploy";

interface DeploymentsProps {
  state: AppState;
  onDeploy: (name: string | null, key: string) => void;
  onRemove: (name: string) => void;
  onNukeAll: () => void;
}

export function Deployments({
  state,
  onDeploy,
  onRemove,
  onNukeAll,
}: DeploymentsProps) {
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [showConfirm, setShowConfirm] = useState(false);
  const [showDeployForm, setShowDeployForm] = useState(false);
  const [deployName, setDeployName] = useState("");
  const [deployKey, setDeployKey] = useState("UbpV2D");
  const [inputField, setInputField] = useState<"name" | "key" | null>(null);

  const deployList = Object.values(state.deployments);

  useKeyboard((key) => {
    if (showDeployForm) {
      if (key.name === "escape") {
        setShowDeployForm(false);
        setInputField(null);
      } else if (key.name === "tab") {
        setInputField(inputField === "name" ? "key" : "name");
      } else if (key.name === "return") {
        if (deployName || deployKey) {
          onDeploy(deployName || null, deployKey || "UbpV2D");
          setShowDeployForm(false);
          setDeployName("");
          setDeployKey("UbpV2D");
          setInputField(null);
        }
      }
      return;
    }

    if (showConfirm) {
      if (key.name === "y" || key.name === "Y") {
        onNukeAll();
        setShowConfirm(false);
      } else {
        setShowConfirm(false);
      }
      return;
    }

    if (key.name === "up" || key.name === "k") {
      setSelectedIndex((i) => Math.max(0, i - 1));
    } else if (key.name === "down" || key.name === "j") {
      setSelectedIndex((i) => Math.min(deployList.length - 1, i + 1));
    } else if (key.name === "d") {
      setShowDeployForm(true);
      setInputField("name");
    } else if (key.name === "x" && deployList[selectedIndex]) {
      onRemove(deployList[selectedIndex].name);
    } else if (key.name === "n") {
      setShowConfirm(true);
    }
  });

  if (showDeployForm) {
    return (
      <box flexDirection="column" padding={1} gap={1}>
        <text>
          <span fg="#3b82f6" bold>
            Deploy New
          </span>
        </text>
        <box>
          <text>
            <span fg="#6b7280">Repo name (empty = random): </span>
            <span fg="#ffffff">{deployName}</span>
            {inputField === "name" && <span fg="#3b82f6">_</span>}
          </text>
        </box>
        <box>
          <text>
            <span fg="#6b7280">VPLink key: </span>
            <span fg="#ffffff">{deployKey}</span>
            {inputField === "key" && <span fg="#3b82f6">_</span>}
          </text>
        </box>
        <box height={1} />
        <text>
          <span fg="#6b7280">Tab</span> switch field · <span fg="#6b7280">
            Enter
          </span>{" "}
          deploy · <span fg="#6b7280">Esc</span> cancel
        </text>
      </box>
    );
  }

  if (showConfirm) {
    return (
      <box flexDirection="column" padding={1} gap={1}>
        <text>
          <span fg="#ef4444" bold>
            ⚠ Nuke ALL
          </span>
        </text>
        <text>
          <span fg="#ffffff">
            Delete ALL {deployList.length} repos and records?
          </span>
        </text>
        <text>
          <span fg="#ef4444">This cannot be undone!</span>
        </text>
        <box height={1} />
        <text>
          <span fg="#6b7280">
            Press [Y] to confirm, any other key to cancel
          </span>
        </text>
      </box>
    );
  }

  return (
    <box flexDirection="column" padding={1} gap={1}>
      <text>
        <span fg="#3b82f6" bold>
          Deployments ({deployList.length})
        </span>
      </text>

      <box
        flexDirection="row"
        gap={2}
        style={{ borderBottom: true, borderColor: "#374151", paddingBottom: 1 }}
      >
        <text>
          <span fg="#6b7280">[D]</span> deploy new
        </text>
        <text>
          <span fg="#6b7280">[X]</span> remove selected
        </text>
        <text>
          <span fg="#6b7280">[N]</span> nuke all
        </text>
      </box>

      {deployList.length === 0 ? (
        <text>
          <span fg="#6b7280">No deployments. Press [D] to deploy.</span>
        </text>
      ) : (
        deployList.map((dep, i) => {
          const s = formatStatus(dep.status);
          const isSelected = i === selectedIndex;
          return (
            <box key={dep.name} flexDirection="row" gap={1}>
              <text>
                <span fg={isSelected ? "#3b82f6" : "#6b7280"}>
                  {isSelected ? "▶" : " "}
                </span>
              </text>
              <text width="35%">
                <span fg={isSelected ? "#ffffff" : "#d1d5db"} bold={isSelected}>
                  {dep.name}
                </span>
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
