import { Box, Text, useKeyboard } from "@opentui/react";
import { useState } from "react";
import type { AppState } from "../hooks/useAppState";

interface SettingsProps {
  state: AppState;
  onSave: (settings: any) => void;
}

export function Settings({ state, onSave }: SettingsProps) {
  const [supabaseUrl, setSupabaseUrl] = useState(
    state.settings.supabase_url || ""
  );
  const [supabaseKey, setSupabaseKey] = useState(
    state.settings.supabase_key || ""
  );
  const [supabaseSecret, setSupabaseSecret] = useState(
    state.settings.supabase_secret || ""
  );
  const [inputField, setInputField] = useState<string | null>(null);

  useKeyboard((key) => {
    if (key.name === "s") {
      onSave({
        supabase_url: supabaseUrl || undefined,
        supabase_key: supabaseKey || undefined,
        supabase_secret: supabaseSecret || undefined,
        active_account: state.settings.active_account,
      });
    } else if (key.name === "tab") {
      const fields = ["url", "key", "secret"];
      const current = fields.indexOf(inputField || "url");
      setInputField(fields[(current + 1) % fields.length]);
    }
  });

  return (
    <box flexDirection="column" padding={1} gap={1}>
      <text>
        <span fg="#3b82f6" bold>
          Settings
        </span>
      </text>

      <box style={{ borderTop: true, borderColor: "#374151", paddingTop: 1 }}>
        <text>
          <span fg="#6b7280" bold>
            Supabase Configuration
          </span>
        </text>
      </box>

      <box>
        <text>
          <span fg="#6b7280">Project URL: </span>
          <span fg="#ffffff">
            {supabaseUrl || "(not set)"}
          </span>
          {inputField === "url" && <span fg="#3b82f6">_</span>}
        </text>
      </box>

      <box>
        <text>
          <span fg="#6b7280">Anon Key: </span>
          <span fg="#ffffff">
            {supabaseKey ? "●".repeat(8) + "..." : "(not set)"}
          </span>
          {inputField === "key" && <span fg="#3b82f6">_</span>}
        </text>
      </box>

      <box>
        <text>
          <span fg="#6b7280">Service Key: </span>
          <span fg="#ffffff">
            {supabaseSecret ? "●".repeat(8) + "..." : "(not set)"}
          </span>
          {inputField === "secret" && <span fg="#3b82f6">_</span>}
        </text>
      </box>

      <box height={1} />

      <box style={{ borderTop: true, borderColor: "#374151", paddingTop: 1 }}>
        <text>
          <span fg="#6b7280" bold>
            Quick Info
          </span>
        </text>
      </box>

      <box>
        <text>
          <span fg="#6b7280">Active Account: </span>
          <span fg="#22c55e">
            {state.settings.active_account || "none"}
          </span>
        </text>
      </box>

      <box>
        <text>
          <span fg="#6b7280">Data Dir: </span>
          <span fg="#9ca3af">~/.vplink/</span>
        </text>
      </box>

      <box height={1} />
      <text>
        <span fg="#6b7280">[S]</span> save · <span fg="#6b7280">Tab</span>{" "}
        switch field
      </text>
    </box>
  );
}
