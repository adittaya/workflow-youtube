#!/usr/bin/env python3
"""
VPLink 24/7 Manager — Terminal Edition
Interactive CLI for managing deployments without a web browser.
"""
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "manager.db"
REPO_ROOT = Path(__file__).parent.parent

# ── Colors ──────────────────────────────────────────────
RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
CYAN = "\033[0;36m"
BOLD = "\033[1m"
NC = "\033[0m"
CLEAR = "\033[2J\033[H"


def c(text, color):
    return f"{color}{text}{NC}"


def db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def hash_password(password):
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000)
    return f"{salt}${h.hex()}"


def verify_password(password, stored):
    salt, h_val = stored.split("$", 1)
    return hmac.compare_digest(
        hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000).hex(), h_val
    )


# ── Auth ─────────────────────────────────────────────────

def do_login():
    print(f"\n{c('VPLink 24/7 Manager — Login', CYAN)}")
    print("─" * 40)
    username = input("Username: ").strip()
    password = input("Password: ").strip()
    conn = db()
    user = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    conn.close()
    if user and verify_password(password, user["password_hash"]):
        return user["id"], user["username"]
    print(f"\n{c('Invalid credentials', RED)}")
    return None, None


# ── Display Helpers ──────────────────────────────────────

def show_header(title):
    print(f"\n{c('═' * 50, CYAN)}")
    print(f"  {c(title, BOLD)}")
    print(f"{c('═' * 50, CYAN)}")


def show_menu(options):
    print()
    for key, (label, _) in options.items():
        print(f"  {c(f'{key})', YELLOW)} {label}")
    print()


def pause():
    input(f"\n{c('Press Enter to continue...', CYAN)}")


# ── Status Overview ──────────────────────────────────────

def cmd_status(user_id):
    show_header("Deployment Status Overview")
    conn = db()
    deps = conn.execute(
        "SELECT d.*, ga.name as account_name FROM deployments d "
        "JOIN github_accounts ga ON ga.id = d.github_account_id "
        "WHERE d.user_id=? ORDER BY d.updated_at DESC", (user_id,)).fetchall()
    conn.close()

    if not deps:
        print(f"  {c('No deployments yet.', YELLOW)}")
        pause()
        return

    active = sum(1 for d in deps if d["status"] == "active")
    error = sum(1 for d in deps if d["status"] == "error")
    stopped = sum(1 for d in deps if d["status"] == "stopped")
    total_views = sum(d["total_views"] for d in deps)

    print(f"    {c('Active:', GREEN)} {active}    {c('Error:', RED)} {error}    "
          f"{c('Stopped:', YELLOW)} {stopped}    {c('Total Views:', CYAN)} {total_views}")
    print()
    print(f"  {c(f'{"REPO":<30} {"STATUS":<12} {"VIEWS":<8} {"KEY":<15} {"ACCOUNT":<15}', BOLD)}")
    print(f"  {'─' * 80}")
    for d in deps:
        status_str = d["status"]
        if d["status"] == "active":
            status_str = c(d["status"], GREEN)
        elif d["status"] == "error":
            status_str = c(d["status"], RED)
        elif d["status"] == "stopped":
            status_str = c(d["status"], YELLOW)
        print(f"  {d['repo_name']:<30} {status_str:<12} {d['total_views']:<8} "
              f"{d['vplink_key'][:12]:<15} {d['account_name']:<15} ")
    print()
    print(f"  {c('Detail: use web UI or run: vplink-manager web', CYAN)}")
    pause()


# ── Deploy Single ────────────────────────────────────────

def cmd_deploy_single(user_id):
    show_header("Single Deployment")
    conn = db()
    accounts = conn.execute("SELECT * FROM github_accounts WHERE user_id=?",
                            (user_id,)).fetchall()
    proxies = conn.execute("SELECT * FROM proxy_credentials WHERE user_id=?",
                           (user_id,)).fetchall()
    conn.close()

    if not accounts:
        print(f"  {c('No GitHub accounts. Add one via web UI.', RED)}")
        pause()
        return

    print("  GitHub Accounts:")
    for i, a in enumerate(accounts, 1):
        print(f"    {i}) {a['name']} ({a['username']})")
    try:
        sel = int(input("\n  Select account: ")) - 1
        acct = accounts[sel]
    except Exception:
        print(f"  {c('Invalid selection', RED)}")
        pause()
        return

    key = input("  VPLink key (e.g. UbpV2D): ").strip()
    if not key:
        pause()
        return

    public = input("  Public repo? (y/N): ").strip().lower() == "y"
    is_public = 1 if public else 0

    from app import create_repo_and_deploy, random_repo_name
    repo = random_repo_name()

    conn = db()
    dep_id = conn.execute(
        "INSERT INTO deployments (user_id, github_account_id, repo_name, owner, "
        "vplink_key, is_public, status) VALUES (?,?,?,?,?,?,'deploying')",
        (user_id, acct["id"], repo, acct["username"], key, is_public)
    ).lastrowid
    conn.commit()
    conn.close()

    threading.Thread(target=create_repo_and_deploy, args=(dep_id,), daemon=True).start()
    print(f"\n  {c('Deploying:', GREEN)} {repo}")
    print(f"  {c('Track progress:', CYAN)} vplink-manager web")
    pause()


# ── Bulk Deploy ──────────────────────────────────────────

def cmd_deploy_bulk(user_id):
    show_header("Bulk Deployment")
    conn = db()
    accounts = conn.execute("SELECT * FROM github_accounts WHERE user_id=?",
                            (user_id,)).fetchall()
    conn.close()

    if not accounts:
        print(f"  {c('No GitHub accounts.', RED)}")
        pause()
        return

    print("  GitHub Accounts:")
    for i, a in enumerate(accounts, 1):
        print(f"    {i}) {a['name']} ({a['username']})")
    try:
        sel = int(input("\n  Select account: ")) - 1
        acct = accounts[sel]
    except Exception:
        print(f"  {c('Invalid', RED)}")
        pause()
        return

    key = input("  VPLink key: ").strip()
    try:
        count = int(input("  Number of repos to create: ").strip())
        if count < 1 or count > 50:
            raise ValueError
    except Exception:
        print(f"  {c('Enter a number between 1-50', RED)}")
        pause()
        return

    public = input("  Public repos? (y/N): ").strip().lower() == "y"
    is_public = 1 if public else 0
    naming = input("  Auto-generate names? (Y/n): ").strip().lower()
    repo_names = None
    if naming == "n":
        print(f"  Enter {count} repo name(s), one per line:")
        names = []
        for _ in range(count):
            names.append(input("    ").strip())
        repo_names = names

    from app import create_n_repos
    results = create_n_repos(count, acct["id"], key, is_public, repo_names)
    print(f"\n  {c(f'{len(results)} deployment(s) created:', GREEN)}")
    for dep_id, rname in results:
        print(f"    - {rname}")
    print(f"\n  {c('Track: vplink-manager web', CYAN)}")
    pause()


# ── List Accounts ────────────────────────────────────────

def cmd_accounts(user_id):
    show_header("GitHub Accounts")
    conn = db()
    accounts = conn.execute("SELECT * FROM github_accounts WHERE user_id=?",
                            (user_id,)).fetchall()
    dep_counts = {}
    for a in accounts:
        cnt = conn.execute("SELECT COUNT(*) as c FROM deployments WHERE github_account_id=?",
                           (a["id"],)).fetchone()["c"]
        dep_counts[a["id"]] = cnt
    conn.close()

    if not accounts:
        print(f"  {c('No accounts. Add one via web UI.', YELLOW)}")
        pause()
        return

    for a in accounts:
        print(f"  {c(a['name'], BOLD)} — {a['username']} ({a['email'] or 'no email'})")
        print(f"    Deployments: {dep_counts.get(a['id'], 0)}  |  Added: {a['created_at']}")
        print()
    pause()


# ── Scan Account ─────────────────────────────────────────

def cmd_scan(user_id):
    show_header("Scan GitHub Account for Existing VPLink Repos")
    conn = db()
    accounts = conn.execute("SELECT * FROM github_accounts WHERE user_id=?",
                            (user_id,)).fetchall()
    conn.close()

    if not accounts:
        print(f"  {c('No accounts.', RED)}")
        pause()
        return

    print("  Select account to scan:")
    for i, a in enumerate(accounts, 1):
        print(f"    {i}) {a['name']} ({a['username']})")
    try:
        sel = int(input("\n  Select: ")) - 1
        acct = accounts[sel]
    except Exception:
        print(f"  {c('Invalid', RED)}")
        pause()
        return

    import requests

    print(f"\n  {c('Scanning repos for', YELLOW)} {acct['username']} ...")
    try:
        all_repos = []
        page = 1
        while True:
            resp = requests.get(
                f"https://api.github.com/user/repos?per_page=100&page={page}&type=all",
                headers={"Authorization": f"Bearer {acct['token']}",
                         "Accept": "application/vnd.github+json"})
            if resp.status_code >= 400:
                raise RuntimeError(resp.text[:200])
            data = resp.json()
            if not data:
                break
            all_repos.extend(data)
            if len(data) < 100:
                break
            page += 1

        conn = db()
        existing = {r["repo_name"] for r in conn.execute(
            "SELECT repo_name FROM deployments WHERE github_account_id=?",
            (acct["id"],)).fetchall()}
        found = 0
        for r in all_repos:
            name = r["name"]
            if name.startswith("vplink-") and name not in existing:
                conn.execute(
                    "INSERT INTO deployments (user_id, github_account_id, repo_name, owner, "
                    "vplink_key, status, repo_url, is_public) VALUES (?,?,?,?,?,'imported',?,?)",
                    (user_id, acct["id"], name, acct["username"], name,
                     r["html_url"], 0 if r["private"] else 1))
                found += 1
        conn.commit()
        conn.close()
        print(f"\n  {c(f'Found {found} new vplink repo(s)!', GREEN)}")
    except Exception as e:
        print(f"\n  {c(f'Scan failed: {e}', RED)}")
    pause()


# ── Credentials ──────────────────────────────────────────

def cmd_credentials(user_id):
    show_header("Stored Credentials")
    conn = db()
    creds = conn.execute("SELECT id, name, cred_type, created_at FROM credentials WHERE user_id=?",
                         (user_id,)).fetchall()
    conn.close()

    if not creds:
        print(f"  {c('No credentials stored.', YELLOW)}")
        pause()
        return

    for c in creds:
        print(f"  {c(c['name'], BOLD)} [{c['cred_type']}] — {c['created_at']}")
        print(f"    Reveal: {c('use web UI', CYAN)}")
        print()
    pause()


# ── Change Password ──────────────────────────────────────

def cmd_password(user_id):
    show_header("Change Password")
    conn = db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not user:
        conn.close()
        return

    current = input("Current password: ").strip()
    if not verify_password(current, user["password_hash"]):
        print(f"  {c('Incorrect password', RED)}")
        conn.close()
        pause()
        return

    new1 = input("New password: ").strip()
    new2 = input("Confirm: ").strip()
    if new1 != new2 or len(new1) < 4:
        print(f"  {c('Passwords do not match or too short', RED)}")
        conn.close()
        pause()
        return

    conn.execute("UPDATE users SET password_hash=? WHERE id=?",
                 (hash_password(new1), user_id))
    conn.commit()
    conn.close()
    print(f"  {c('Password updated!', GREEN)}")
    pause()


# ── Open Web ─────────────────────────────────────────────

def cmd_web():
    print(f"\n  {c('Starting web interface...', GREEN)}")
    print(f"  {c('Run: vplink-manager web', CYAN)}")
    print(f"  {c('Or open http://localhost:8888', CYAN)}")
    pause()


# ── Update ───────────────────────────────────────────────

def cmd_update():
    show_header("Update VPLink Manager")
    print(f"  {c('Pulling latest code...', YELLOW)}")
    result = subprocess.run(["git", "pull"], cwd=str(REPO_ROOT),
                            capture_output=True, text=True)
    print(f"  {result.stdout}")
    if result.returncode != 0:
        print(f"  {c(result.stderr, RED)}")
    print(f"\n  {c('Restart needed: vplink-manager restart', CYAN)}")
    pause()


# ── Interactive Loop ─────────────────────────────────────

def main_loop():
    user_id, username = do_login()
    if not user_id:
        sys.exit(1)

    while True:
        print(CLEAR, end="")
        print(f"{c('╔══════════════════════════════════════════════════╗', CYAN)}")
        print(f"{c('║         VPLink 24/7 Manager — Terminal          ║', CYAN)}")
        print(f"{c('╠══════════════════════════════════════════════════╣', CYAN)}")
        print(f"{c('║', CYAN)}  Logged in: {c(username, BOLD)}                      {c('║', CYAN)}")
        print(f"{c('╠══════════════════════════════════════════════════╣', CYAN)}")

        menu = {
            "1": ("Status Overview — all deployments", lambda: cmd_status(user_id)),
            "2": ("Deploy Single automation", lambda: cmd_deploy_single(user_id)),
            "3": ("Bulk Deploy — create multiple repos", lambda: cmd_deploy_bulk(user_id)),
            "4": ("List GitHub Accounts", lambda: cmd_accounts(user_id)),
            "5": ("Scan Account for existing repos", lambda: cmd_scan(user_id)),
            "6": ("View Stored Credentials", lambda: cmd_credentials(user_id)),
            "7": ("Change Password", lambda: cmd_password(user_id)),
            "8": ("Update Code (git pull)", cmd_update),
            "9": ("Open Web Interface (browser)", cmd_web),
            "0": ("Exit", None),
        }

        for k, (label, _) in menu.items():
            print(f"{c('║', CYAN)}  {c(f'{k})', YELLOW)} {label:<42} {c('║', CYAN)}")

        print(f"{c('╚══════════════════════════════════════════════════╝', CYAN)}")
        choice = input(f"\n  {c('Choice:', GREEN)} ").strip()

        if choice == "0":
            print(f"\n  {c('Goodbye!', GREEN)}")
            break
        elif choice in menu:
            menu[choice][1]()
        else:
            print(f"\n  {c('Invalid choice', RED)}")
            time.sleep(1)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Direct commands
        cmd = sys.argv[1]
        user_id, username = do_login()
        if not user_id:
            sys.exit(1)
        commands = {
            "status": cmd_status,
            "accounts": cmd_accounts,
            "scan": cmd_scan,
            "credentials": cmd_credentials,
            "passwd": cmd_password,
            "update": cmd_update,
        }
        if cmd in commands:
            commands[cmd](user_id)
        else:
            print(f"Unknown command: {cmd}")
            sys.exit(1)
    else:
        main_loop()
