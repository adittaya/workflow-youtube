import { Box, Text, useKeyboard } from "@opentui/react";
import { useState } from "react";
import type { AppState } from "../hooks/useAppState";

interface AccountsProps {
  state: AppState;
  onAddAccount: (name: string, token: string) => void;
  onRemoveAccount: (name: string) => void;
  onSwitchAccount: (name: string) => void;
}

export function Accounts({
  state,
  onAddAccount,
  onRemoveAccount,
  onSwitchAccount,
}: AccountsProps) {
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [showAddForm, setShowAddForm] = useState(false);
  const [formName, setFormName] = useState("");
  const [formToken, setFormToken] = useState("");
  const [inputField, setInputField] = useState<"name" | "token" | null>(null);

  const accountList = Object.values(state.accounts);

  useKeyboard((key) => {
    if (showAddForm) {
      if (key.name === "escape") {
        setShowAddForm(false);
        setInputField(null);
        setFormName("");
        setFormToken("");
      } else if (key.name === "tab") {
        setInputField(inputField === "name" ? "token" : "name");
      } else if (key.name === "return") {
        if (formName && formToken) {
          onAddAccount(formName, formToken);
          setShowAddForm(false);
          setFormName("");
          setFormToken("");
          setInputField(null);
        }
      }
      return;
    }

    if (key.name === "up" || key.name === "k") {
      setSelectedIndex((i) => Math.max(0, i - 1));
    } else if (key.name === "down" || key.name === "j") {
      setSelectedIndex((i) => Math.min(accountList.length - 1, i + 1));
    } else if (key.name === "a") {
      setShowAddForm(true);
      setInputField("name");
    } else if (key.name === "x" && accountList[selectedIndex]) {
      onRemoveAccount(accountList[selectedIndex].name);
    } else if (key.name === "s" && accountList[selectedIndex]) {
      onSwitchAccount(accountList[selectedIndex].name);
    }
  });

  if (showAddForm) {
    return (
      <box flexDirection="column" padding={1} gap={1}>
        <text>
          <span fg="#3b82f6" bold>
            Add Account
          </span>
        </text>
        <box>
          <text>
            <span fg="#6b7280">Account name: </span>
            <span fg="#ffffff">{formName}</span>
            {inputField === "name" && <span fg="#3b82f6">_</span>}
          </text>
        </box>
        <box>
          <text>
            <span fg="#6b7280">GitHub token: </span>
            <span fg="#ffffff">
              {formToken ? formToken.slice(0, 8) + "..." : ""}
            </span>
            {inputField === "token" && <span fg="#3b82f6">_</span>}
          </text>
        </box>
        <box height={1} />
        <text>
          <span fg="#6b7280">Tab</span> switch field · <span fg="#6b7280">
            Enter
          </span>{" "}
          add · <span fg="#6b7280">Esc</span> cancel
        </text>
      </box>
    );
  }

  return (
    <box flexDirection="column" padding={1} gap={1}>
      <text>
        <span fg="#3b82f6" bold>
          Accounts ({accountList.length})
        </span>
      </text>

      <box
        flexDirection="row"
        gap={2}
        style={{ borderBottom: true, borderColor: "#374151", paddingBottom: 1 }}
      >
        <text>
          <span fg="#6b7280">[A]</span> add account
        </text>
        <text>
          <span fg="#6b7280">[S]</span> switch to selected
        </text>
        <text>
          <span fg="#6b7280">[X]</span> remove selected
        </text>
      </box>

      {state.settings.active_account && (
        <box>
          <text>
            <span fg="#6b7280">Active: </span>
            <span fg="#22c55e">{state.settings.active_account}</span>
          </text>
        </box>
      )}

      {accountList.length === 0 ? (
        <text>
          <span fg="#6b7280">
            No accounts configured. Press [A] to add one.
          </span>
        </text>
      ) : (
        accountList.map((acct, i) => {
          const isActive = acct.name === state.settings.active_account;
          const isSelected = i === selectedIndex;
          return (
            <box key={acct.name} flexDirection="row" gap={2}>
              <text>
                <span fg={isSelected ? "#3b82f6" : "#6b7280"}>
                  {isSelected ? "▶" : " "}
                </span>
              </text>
              <text width="30%">
                <span
                  fg={isActive ? "#22c55e" : isSelected ? "#ffffff" : "#d1d5db"}
                  bold={isSelected}
                >
                  {acct.name}
                </span>
              </text>
              <text width="20%">
                <span fg="#6b7280">@{acct.username || "?"}</span>
              </text>
              <text>
                {isActive && (
                  <span fg="#22c55e">● active</span>
                )}
              </text>
            </box>
          );
        })
      )}
    </box>
  );
}
