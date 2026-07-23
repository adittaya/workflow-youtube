#!/usr/bin/env bun
import { createCliRenderer } from "@opentui/core";
import { createRoot } from "@opentui/react";
import { App } from "./components/App";

const args = process.argv.slice(2);

if (args.includes("--help") || args.includes("-h")) {
  console.log(`
VPLink TUI Manager v3.0

Usage:
  vplink-tui                  Launch interactive TUI
  vplink-tui --help           Show this help
  vplink-tui --version        Show version

Navigation (in TUI):
  [1] Dashboard       Overview of all accounts and deployments
  [2] Deployments     Deploy, remove, nuke deployments
  [3] Accounts        Add, switch, remove GitHub accounts
  [4] Analytics       View analytics and status breakdown
  [5] Settings        Configure Supabase and other settings
  [6] Sync            Sync deployments from GitHub (real-time)

Keys:
  ESC                 Quit
  ↑/↓ or j/k          Navigate lists
  Tab                 Switch input fields
  Enter               Confirm action

Description:
  React-powered terminal UI for managing VPLink automation deployments.
  Uses OpenTUI (React for terminals, powered by Bun + Zig).
  
  GitHub repos ARE the database — any environment can sync.
  No local database dependency.
`);
  process.exit(0);
}

if (args.includes("--version") || args.includes("-v")) {
  console.log("vplink-tui v3.0.0");
  process.exit(0);
}

const renderer = await createCliRenderer({
  exitOnCtrlC: true,
});

createRoot(renderer).render(<App />);
