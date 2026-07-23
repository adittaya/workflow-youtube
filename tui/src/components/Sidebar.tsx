import { useKeyboard } from "@opentui/react";
import type { Screen } from "../hooks/useAppState";

interface SidebarProps {
  activeScreen: Screen;
  onNavigate: (screen: Screen) => void;
}

const NAV_ITEMS: { key: Screen; label: string; shortcut: string }[] = [
  { key: "dashboard", label: "Dashboard", shortcut: "1" },
  { key: "deployments", label: "Deployments", shortcut: "2" },
  { key: "accounts", label: "Accounts", shortcut: "3" },
  { key: "analytics", label: "Analytics", shortcut: "4" },
  { key: "settings", label: "Settings", shortcut: "5" },
  { key: "sync", label: "Sync", shortcut: "6" },
];

export function Sidebar({ activeScreen, onNavigate }: SidebarProps) {
  useKeyboard((key) => {
    if (key.name === "escape") {
      process.exit(0);
    }
    const item = NAV_ITEMS.find((n) => n.shortcut === key.name);
    if (item) {
      onNavigate(item.key);
    }
  });

  return (
    <box
      flexDirection="column"
      width={20}
      style={{ borderRight: true, borderColor: "#374151", padding: 1 }}
    >
      <text>
        <span fg="#3b82f6" bold>
          Navigation
        </span>
      </text>
      <box height={1} />
      {NAV_ITEMS.map((item) => {
        const isActive = item.key === activeScreen;
        return (
          <box key={item.key} flexDirection="row" gap={1}>
            <text>
              {isActive ? (
                <span fg="#3b82f6" bold>
                  [{item.shortcut}]
                </span>
              ) : (
                <span fg="#6b7280">
                  [{item.shortcut}]
                </span>
              )}
            </text>
            <text>
              {isActive ? (
                <span fg="#ffffff" bold>
                  {item.label}
                </span>
              ) : (
                <span fg="#9ca3af">{item.label}</span>
              )}
            </text>
          </box>
        );
      })}
      <box height={1} />
      <box style={{ borderTop: true, borderColor: "#374151", paddingTop: 1 }}>
        <text>
          <span fg="#6b7280">ESC</span> <span fg="#4b5563">quit</span>
        </text>
      </box>
    </box>
  );
}
