#!/usr/bin/env python3
"""VPLink Interactive TUI — account, deployment, sync, status, logs, settings."""

import json, os, subprocess, sys, time, urllib.request, urllib.error, zipfile, io
from pathlib import Path

# ─── Config ───────────────────────────────────────────────────────────────────

DATA_DIR = Path(os.environ.get("VPLINK_HOME", os.path.expanduser("~/.vplink247")))
GITHUB_API = "https://api.github.com"
TEMPLATE_REPO = "adittaya/workflow-vplink"
DEPLOY_TIMEOUT = 120

# ─── ANSI Colors ──────────────────────────────────────────────────────────────

C_RESET  = "\033[0m"
C_BOLD   = "\033[1m"
C_DIM    = "\033[2m"
C_RED    = "\033[31m"
C_GREEN  = "\033[32m"
C_YELLOW = "\033[33m"
C_BLUE   = "\033[34m"
C_CYAN   = "\033[36m"
C_WHITE  = "\033[37m"
C_GRAY   = "\033[90m"
C_BRGREEN = "\033[92m"
C_BRCYAN  = "\033[96m"
C_BRYELLOW = "\033[93m"
C_BRRED  = "\033[91m"
C_BOLDWHITE = "\033[1;37m"

# ─── Data Layer ───────────────────────────────────────────────────────────────

def _data_path(name):
    return DATA_DIR / name

def load_json(name):
    p = _data_path(name)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}

def save_json(name, data):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _data_path(name).write_text(json.dumps(data, indent=2))

# ─── GitHub API ───────────────────────────────────────────────────────────────

def gh(endpoint, token, method="GET", body=None):
    url = endpoint if endpoint.startswith("http") else f"{GITHUB_API}{endpoint}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("User-Agent", "vplink-tui/3.0")
    if body:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            scopes = resp.headers.get("X-OAuth-Scopes", "")
            if not raw:
                return {"ok": True, "status": resp.status, "_scopes": scopes}
            result = json.loads(raw)
            result["_scopes"] = scopes
            return result
    except urllib.error.HTTPError as e:
        return {"error": True, "status": e.code, "message": e.read().decode(errors="replace")}

def gh_user(token):
    return gh("/user", token)

def paginate_repos(token):
    all_repos = []
    for page in range(1, 6):
        repos = gh(f"/user/repos?per_page=100&page={page}&type=all", token)
        if isinstance(repos, dict) and repos.get("error"):
            break
        if not repos:
            break
        all_repos.extend(repos)
        if len(repos) < 100:
            break
    return all_repos

def get_vplink_repos(token):
    repos = paginate_repos(token)
    return [r for r in repos if r["name"].startswith("vplink-")]

def get_workflow(owner, repo, token):
    data = gh(f"/repos/{owner}/{repo}/actions/workflows", token)
    if isinstance(data, dict) and data.get("error"):
        return None
    for w in data.get("workflows", []):
        if "continuous" in w.get("path", "") or "vplink" in w.get("name", "").lower():
            return w
    return data.get("workflows", [None])[0] if data.get("workflows") else None

def get_runs(owner, repo, token, per=5):
    data = gh(f"/repos/{owner}/{repo}/actions/runs?per_page={per}", token)
    if isinstance(data, dict) and data.get("error"):
        return []
    return data.get("workflow_runs", [])

def extract_destination(token, owner, repo, run_id):
    url = f"/repos/{owner}/{repo}/actions/runs/{run_id}/logs"
    req = urllib.request.Request(f"{GITHUB_API}{url}")
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("User-Agent", "vplink-tui/3.0")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            zf = zipfile.ZipFile(io.BytesIO(resp.read()))
            found_dest_line = False
            for name in zf.namelist():
                if not name.endswith(".txt"):
                    continue
                for line in zf.read(name).decode(errors="replace").split("\n"):
                    s = line.strip()
                    if "DESTINATION URL:" in s or "Destination:" in s:
                        val = s.split(":", 1)[-1].strip()
                        if val.startswith("http"):
                            return val
                        found_dest_line = True
                    elif found_dest_line and s.startswith("http"):
                        return s
                    else:
                        found_dest_line = False
    except Exception:
        pass
    return ""

def get_run_logs(token, owner, repo, run_id):
    url = f"/repos/{owner}/{repo}/actions/runs/{run_id}/logs"
    req = urllib.request.Request(f"{GITHUB_API}{url}")
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("User-Agent", "vplink-tui/3.0")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            zf = zipfile.ZipFile(io.BytesIO(resp.read()))
            logs = {}
            for name in sorted(zf.namelist()):
                if name.endswith(".txt"):
                    logs[name] = zf.read(name).decode(errors="replace")
            return logs
    except Exception:
        return {}

# ─── Deploy / Remove ──────────────────────────────────────────────────────────

def deploy_new(repo_name, key, token, username, settings):
    full_name = repo_name if repo_name.startswith("vplink-") else f"vplink-{repo_name}"
    print(f"  Creating repo {full_name}...")
    create_resp = gh("/user/repos", token, "POST", {
        "name": full_name, "private": True, "auto_init": True,
        "description": "VPLink automation relay",
    })
    if isinstance(create_resp, dict) and create_resp.get("error"):
        return None, f"Create repo failed: {create_resp.get('message', '')}"

    template_dir = str(DATA_DIR / "template")
    if not Path(template_dir).exists():
        print(f"  Cloning template repo...")
        r = subprocess.run(
            ["git", "clone", "--depth", "1", f"https://github.com/{TEMPLATE_REPO}.git", template_dir],
            capture_output=True, timeout=DEPLOY_TIMEOUT,
        )
        if r.returncode != 0:
            return None, f"Clone template failed: {r.stderr.decode(errors='replace')}"

    repo_dir = str(DATA_DIR / "repos" / full_name)
    Path(repo_dir).parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["rm", "-rf", repo_dir], capture_output=True)

    def ignore_git(d, files):
        return [".git"] if ".git" in files else []

    import shutil
    shutil.copytree(template_dir, repo_dir, ignore=ignore_git)

    env = os.environ.copy()
    env["GIT_ASKPASS"] = "echo"
    token_url = f"https://{token}@github.com/{username}/{full_name}.git"

    for cmd in [
        ["git", "init", "-b", "main"],
        ["git", "remote", "add", "origin", token_url],
        ["git", "add", "-A"],
        ["git", "commit", "-m", "init: vplink automation relay"],
        ["git", "push", "--force", "origin", "main"],
    ]:
        r = subprocess.run(cmd, cwd=repo_dir, capture_output=True, timeout=60, env=env)
        if r.returncode != 0 and cmd[1] != "push":
            pass

    print("  Setting secrets...")
    secrets = {"VPLINK_KEY": key, "RELAY_TARGET_REPO": f"{username}/{full_name}"}
    for k in ["SUPABASE_URL", "SUPABASE_KEY", "SUPABASE_SECRET"]:
        v = settings.get(k.lower(), "")
        if v:
            secrets[k] = v
    for sname, sval in secrets.items():
        gh(f"/repos/{username}/{full_name}/actions/secrets/{sname}", token, "PUT", {
            "encrypted_value": "", "key_id": "",
        })

    print("  Enabling workflow...")
    wf = get_workflow(username, full_name, token)
    if wf:
        gh(f"/repos/{username}/{full_name}/actions/workflows/{wf['id']}/enable", token, "PUT")
        print("  Dispatching workflow...")
        gh(f"/repos/{username}/{full_name}/actions/workflows/{wf['id']}/dispatches", token, "POST",
           {"ref": "main", "inputs": {"key": key}})

    dep = {
        "name": full_name, "key": key, "account": username,
        "repo_url": f"https://github.com/{username}/{full_name}",
        "status": "deployed", "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    deps = load_json("deployments.json")
    deps[full_name] = dep
    save_json("deployments.json", deps)
    return dep, None

def remove_deployment(name):
    deps = load_json("deployments.json")
    dep = deps.get(name)
    if not dep:
        return False, "Deployment not found"
    accounts = load_json("accounts.json")
    acct = accounts.get(dep.get("account", ""))
    if acct:
        owner = acct.get("username", dep.get("account", ""))
        gh(f"/repos/{owner}/{name}", acct["token"], "DELETE")
    del deps[name]
    save_json("deployments.json", deps)
    return True, None

def nuke_deployments():
    deps = load_json("deployments.json")
    accounts = load_json("accounts.json")
    deleted = 0
    for name, dep in list(deps.items()):
        acct = accounts.get(dep.get("account", ""))
        if acct:
            owner = acct.get("username", dep.get("account", ""))
            gh(f"/repos/{owner}/{name}", acct["token"], "DELETE")
            deleted += 1
    save_json("deployments.json", {})
    return deleted

# ─── UI Helpers ───────────────────────────────────────────────────────────────

def clear():
    subprocess.run(["clear"] if os.name != "nt" else ["cls"], capture_output=True)

def banner():
    print(f"""
{C_CYAN}{C_BOLD}╔══════════════════════════════════════════════════════════╗
║                V P L I N K   C O N T R O L              ║
╚══════════════════════════════════════════════════════════╝{C_RESET}""")

def status_line():
    accounts = load_json("accounts.json")
    settings = load_json("settings.json")
    active = settings.get("active_account")
    deps = load_json("deployments.json")
    n_acct = len(accounts)
    n_dep = len(deps)
    if active and active in accounts:
        user = accounts[active].get("username", active)
        print(f"  {C_DIM}Account:{C_RESET} {C_GREEN}{user}{C_RESET}  "
              f"{C_DIM}Accounts:{C_RESET} {n_acct}  "
              f"{C_DIM}Deployments:{C_RESET} {n_dep}")
    elif n_acct == 0:
        print(f"  {C_YELLOW}No accounts configured{C_RESET}")
    else:
        print(f"  {C_DIM}Active:{C_RESET} {C_YELLOW}none{C_RESET}  "
              f"{C_DIM}Accounts:{C_RESET} {n_acct}  "
              f"{C_DIM}Deployments:{C_RESET} {n_dep}")

def divider():
    print(f"  {C_DIM}{'─' * 56}{C_RESET}")

def prompt(msg, default=None):
    suffix = f" [{default}]" if default else ""
    val = input(f"  {C_CYAN}▸{C_RESET} {msg}{suffix}: ").strip()
    return val if val else (default or "")

def confirm(msg):
    val = input(f"  {C_YELLOW}?{C_RESET} {msg} (y/N): ").strip().lower()
    return val in ("y", "yes")

def success(msg):
    print(f"  {C_GREEN}✓ {msg}{C_RESET}")

def error(msg):
    print(f"  {C_RED}✗ {msg}{C_RESET}")

def info(msg):
    print(f"  {C_BLUE}ℹ {msg}{C_RESET}")

def warn(msg):
    print(f"  {C_YELLOW}⚠ {msg}{C_RESET}")

def loading(msg):
    print(f"  {C_DIM}⏳ {msg}...{C_RESET}")

def get_active_token():
    accounts = load_json("accounts.json")
    settings = load_json("settings.json")
    active = settings.get("active_account")
    if active and active in accounts:
        return accounts[active]["token"], active
    return None, None

# ─── Screen: Accounts ─────────────────────────────────────────────────────────

def screen_accounts():
    while True:
        clear()
        banner()
        print(f"\n  {C_BOLDWHITE}ACCOUNTS{C_RESET}")
        divider()
        accounts = load_json("accounts.json")
        settings = load_json("settings.json")
        active = settings.get("active_account")
        accts = list(accounts.values())
        if not accts:
            print(f"\n  {C_DIM}No accounts configured yet.{C_RESET}")
            print(f"  {C_DIM}Add a GitHub account to get started.{C_RESET}\n")
        else:
            for i, a in enumerate(accts, 1):
                is_active = a["name"] == active
                marker = f"{C_GREEN}●{C_RESET}" if is_active else f"{C_DIM}○{C_RESET}"
                user = a.get("username", "?")
                tok = a["token"]
                print(f"  {marker} {C_BOLD}{a['name']}{C_RESET} "
                      f"{C_DIM}@{user}  {tok[:8]}...{tok[-4:]}{C_RESET}")
            print()
        print(f"  {C_BOLD}[1]{C_RESET} Add account")
        print(f"  {C_BOLD}[2]{C_RESET} Remove account")
        if accts:
            print(f"  {C_BOLD}[3]{C_RESET} Switch active")
        print(f"  {C_BOLD}[0]{C_RESET} Back\n")

        choice = prompt("Choice")
        if choice == "0":
            return
        elif choice == "1":
            name = prompt("Account name (e.g. main)")
            if not name:
                continue
            token = prompt("GitHub Personal Access Token")
            if not token:
                continue
            if name in accounts:
                error("Account name already exists")
                continue
            loading("Validating token")
            user_data = gh_user(token)
            if isinstance(user_data, dict) and user_data.get("login"):
                username = user_data["login"]
                scopes = user_data.get("_scopes", "")
                scope_list = [s.strip() for s in scopes.split(",") if s.strip()]
                accounts[name] = {"name": name, "token": token, "username": username}
                save_json("accounts.json", accounts)
                if not active:
                    settings["active_account"] = name
                    save_json("settings.json", settings)
                success(f"Added @{username}")
                if not any("repo" in s for s in scope_list):
                    warn("Token missing 'repo' scope")
                if not any("workflow" in s for s in scope_list):
                    warn("Token missing 'workflow' scope")
            else:
                error("Invalid token")
        elif choice == "2" and accts:
            name = prompt("Account name to remove")
            if name and name in accounts:
                if confirm(f"Remove '{name}'?"):
                    del accounts[name]
                    save_json("accounts.json", accounts)
                    if active == name:
                        settings["active_account"] = None
                        save_json("settings.json", settings)
                    success(f"Removed '{name}'")
            elif name:
                error("Account not found")
        elif choice == "3" and accts:
            name = prompt("Account name to activate")
            if name and name in accounts:
                settings["active_account"] = name
                save_json("settings.json", settings)
                success(f"Activated '{name}'")
            elif name:
                error("Account not found")

# ─── Screen: Deploy ───────────────────────────────────────────────────────────

def screen_deploy():
    clear()
    banner()
    print(f"\n  {C_BOLDWHITE}DEPLOY NEW INSTANCE{C_RESET}")
    divider()

    token, _ = get_active_token()
    if not token:
        error("No active account. Go to Accounts first.")
        input(f"\n  Press Enter to continue...")
        return

    repo_name = prompt("Repo name (will create vplink-{name})")
    if not repo_name:
        return
    key = prompt("VPLINK_KEY")
    if not key:
        error("VPLINK_KEY is required")
        input(f"\n  Press Enter to continue...")
        return

    accounts = load_json("accounts.json")
    settings = load_json("settings.json")
    active = settings.get("active_account")
    username = accounts[active].get("username", active)

    if not confirm(f"Deploy vplink-{repo_name if not repo_name.startswith('vplink-') else repo_name} "
                   f"as @{username}?"):
        return

    loading("Deploying (this may take a minute)")
    dep, err = deploy_new(repo_name, key, token, username, settings)
    if err:
        error(err)
    else:
        success(f"Deployed: {dep['name']}")
        print(f"  {C_DIM}Repo: {dep['repo_url']}{C_RESET}")
    input(f"\n  Press Enter to continue...")

# ─── Screen: Remove ───────────────────────────────────────────────────────────

def screen_remove():
    while True:
        clear()
        banner()
        print(f"\n  {C_BOLDWHITE}REMOVE DEPLOYMENT{C_RESET}")
        divider()
        deps = load_json("deployments.json")
        dep_list = list(deps.values())
        if not dep_list:
            print(f"\n  {C_DIM}No deployments to remove.{C_RESET}\n")
            input(f"  Press Enter to continue...")
            return
        for i, d in enumerate(dep_list, 1):
            status_color = C_GREEN if d["status"] == "success" else C_YELLOW if d["status"] == "deployed" else C_RED
            print(f"  {C_BOLD}{i}.{C_RESET} {d['name']}  "
                  f"{status_color}{d['status']}{C_RESET}  "
                  f"{C_DIM}{d.get('account', '?')}{C_RESET}")
        print(f"\n  {C_BOLD}[N]{C_RESET} Remove deployment N")
        print(f"  {C_BOLD}[a]{C_RESET} Nuke ALL deployments")
        print(f"  {C_BOLD}[0]{C_RESET} Back\n")

        choice = prompt("Choice")
        if choice == "0":
            return
        elif choice == "a":
            if confirm(f"DELETE ALL {len(dep_list)} DEPLOYMENTS? This removes GitHub repos too!"):
                loading("Nuking all deployments")
                deleted = nuke_deployments()
                success(f"Nuked {deleted} deployments")
                input(f"\n  Press Enter to continue...")
                return
        elif choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(dep_list):
                d = dep_list[idx]
                if confirm(f"Remove '{d['name']}'? (deletes GitHub repo)"):
                    loading(f"Removing {d['name']}")
                    ok, err = remove_deployment(d["name"])
                    if ok:
                        success(f"Removed {d['name']}")
                    else:
                        error(err)
                    input(f"\n  Press Enter to continue...")

# ─── Screen: Status ───────────────────────────────────────────────────────────

def screen_status():
    clear()
    banner()
    print(f"\n  {C_BOLDWHITE}DEPLOYMENT STATUS{C_RESET}")
    divider()

    token, _ = get_active_token()
    if not token:
        error("No active account")
        input(f"\n  Press Enter to continue...")
        return

    loading("Fetching deployments from GitHub")
    repos = get_vplink_repos(token)
    if not repos:
        print(f"\n  {C_DIM}No vplink-* repos found on this account.{C_RESET}")
        input(f"\n  Press Enter to continue...")
        return

    cache = load_json("status_cache.json")
    print()
    for repo in repos:
        rn = repo["name"]
        owner = repo["owner"]["login"]
        c = cache.get(rn, {})
        dest = c.get("destination", "")
        consec_fails = c.get("consecutive_fails", 0)
        total_ok = c.get("total_successes", 0)

        runs = get_runs(owner, rn, token, per=1)
        if runs:
            latest = runs[0]
            status = latest.get("conclusion") or latest["status"]
            created = latest.get("created_at", "")[:16].replace("T", " ")
        else:
            status = "no_runs"
            created = "never"

        sc = C_GREEN if status == "success" else C_RED if status == "failure" else C_YELLOW
        print(f"  {C_BOLD}{rn}{C_RESET}")
        print(f"    {C_DIM}Status:{C_RESET} {sc}{status}{C_RESET}  "
              f"{C_DIM}Last:{C_RESET} {created}  "
              f"{C_DIM}OK:{C_RESET} {total_ok}  "
              f"{C_DIM}Fails:{C_RESET} {consec_fails}")
        if dest:
            print(f"    {C_DIM}Destination:{C_RESET} {C_BRGREEN}{dest}{C_RESET}")
        print()

    input(f"  Press Enter to continue...")

# ─── Screen: Logs ─────────────────────────────────────────────────────────────

def screen_logs():
    clear()
    banner()
    print(f"\n  {C_BOLDWHITE}VIEW WORKFLOW LOGS{C_RESET}")
    divider()

    token, _ = get_active_token()
    if not token:
        error("No active account")
        input(f"\n  Press Enter to continue...")
        return

    repos = get_vplink_repos(token)
    if not repos:
        print(f"\n  {C_DIM}No vplink-* repos found.{C_RESET}")
        input(f"\n  Press Enter to continue...")
        return

    print()
    for i, repo in enumerate(repos, 1):
        print(f"  {C_BOLD}{i}.{C_RESET} {repo['name']}")
    print(f"\n  {C_BOLD}[0]{C_RESET} Back\n")

    choice = prompt("Select repo")
    if not choice or choice == "0" or not choice.isdigit():
        return

    idx = int(choice) - 1
    if idx < 0 or idx >= len(repos):
        return

    repo = repos[idx]
    owner = repo["owner"]["login"]
    rn = repo["name"]

    runs = get_runs(owner, rn, token, per=5)
    if not runs:
        print(f"\n  {C_DIM}No workflow runs found.{C_RESET}")
        input(f"\n  Press Enter to continue...")
        return

    print()
    for i, run in enumerate(runs, 1):
        sc = C_GREEN if run.get("conclusion") == "success" else C_RED if run.get("conclusion") == "failure" else C_YELLOW
        created = run.get("created_at", "")[:16].replace("T", " ")
        print(f"  {C_BOLD}{i}.{C_RESET} Run #{run['number']}  "
              f"{sc}{run.get('conclusion', run['status'])}{C_RESET}  {created}")
    print(f"\n  {C_BOLD}[0]{C_RESET} Back\n")

    choice2 = prompt("Select run")
    if not choice2 or choice2 == "0" or not choice2.isdigit():
        return

    idx2 = int(choice2) - 1
    if idx2 < 0 or idx2 >= len(runs):
        return

    run = runs[idx2]
    loading("Fetching logs")
    logs = get_run_logs(token, owner, rn, run["id"])
    if not logs:
        print(f"\n  {C_DIM}No logs available.{C_RESET}")
        input(f"\n  Press Enter to continue...")
        return

    dest = extract_destination(token, owner, rn, run["id"])
    if dest:
        success(f"Destination: {dest}")

    for name, content in logs.items():
        print(f"\n  {C_CYAN}{'─' * 56}{C_RESET}")
        print(f"  {C_BOLD}{name}{C_RESET}")
        print(f"  {C_CYAN}{'─' * 56}{C_RESET}")
        lines = content.split("\n")
        for line in lines[-50:]:
            print(f"  {C_DIM}{line}{C_RESET}")
        if len(lines) > 50:
            print(f"  {C_DIM}... ({len(lines) - 50} lines hidden){C_RESET}")

    input(f"\n  Press Enter to continue...")

# ─── Screen: Sync ─────────────────────────────────────────────────────────────

def screen_sync():
    clear()
    banner()
    print(f"\n  {C_BOLDWHITE}SYNC FROM GITHUB{C_RESET}")
    divider()

    accounts = load_json("accounts.json")
    if not accounts:
        error("No accounts configured")
        input(f"\n  Press Enter to continue...")
        return

    existing = load_json("deployments.json")
    new_repos = []
    updated_repos = []

    for name, acct in accounts.items():
        loading(f"Scanning @{acct.get('username', name)}")
        try:
            repos = paginate_repos(acct["token"])
            vplink = [r for r in repos if r["name"].startswith("vplink-")]
            owner = vplink[0]["owner"]["login"] if vplink else acct.get("username", name)
            acct["username"] = owner
            for repo in vplink:
                rn = repo["name"]
                try:
                    runs = get_runs(owner, rn, acct["token"], per=1)
                    last = runs[0] if runs else None
                    status = (last.get("conclusion") or last.get("status", "unknown")) if last else "no_runs"
                except Exception:
                    status = "unknown"
                if rn in existing:
                    existing[rn]["status"] = status
                    existing[rn]["account"] = name
                    updated_repos.append(rn)
                else:
                    existing[rn] = {
                        "name": rn, "key": "?", "account": name,
                        "repo_url": repo["html_url"], "status": status,
                        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    }
                    new_repos.append(rn)
        except Exception:
            continue

    save_json("accounts.json", accounts)
    save_json("deployments.json", existing)

    print(f"\n  {C_GREEN}Sync complete{C_RESET}")
    print(f"  {C_DIM}New:{C_RESET} {len(new_repos)}  "
          f"{C_DIM}Updated:{C_RESET} {len(updated_repos)}  "
          f"{C_DIM}Total:{C_RESET} {len(existing)}")
    if new_repos:
        print(f"  {C_DIM}New repos:{C_RESET} {', '.join(new_repos)}")
    input(f"\n  Press Enter to continue...")

# ─── Screen: Settings ─────────────────────────────────────────────────────────

def screen_settings():
    while True:
        clear()
        banner()
        print(f"\n  {C_BOLDWHITE}SETTINGS{C_RESET}")
        divider()
        settings = load_json("settings.json")
        su = settings.get("supabase_url", "")
        sk = settings.get("supabase_key", "")
        ss = settings.get("supabase_secret", "")

        print(f"  {C_DIM}Supabase URL:{C_RESET}   {su or f'{C_YELLOW}not set{C_RESET}'}")
        print(f"  {C_DIM}Supabase Key:{C_RESET}   {sk[:20]}{'...' if len(sk) > 20 else '' if sk else ''}")
        print(f"  {C_DIM}Supabase Secret:{C_RESET} {ss[:20]}{'...' if len(ss) > 20 else '' if ss else ''}")
        print()
        print(f"  {C_BOLD}[1]{C_RESET} Set Supabase URL")
        print(f"  {C_BOLD}[2]{C_RESET} Set Supabase Key")
        print(f"  {C_BOLD}[3]{C_RESET} Set Supabase Secret")
        print(f"  {C_BOLD}[4]{C_RESET} Clear all settings")
        print(f"  {C_BOLD}[0]{C_RESET} Back\n")

        choice = prompt("Choice")
        if choice == "0":
            return
        elif choice == "1":
            val = prompt("Supabase URL", settings.get("supabase_url"))
            settings["supabase_url"] = val
            save_json("settings.json", settings)
            success("Saved")
        elif choice == "2":
            val = prompt("Supabase Key", settings.get("supabase_key"))
            settings["supabase_key"] = val
            save_json("settings.json", settings)
            success("Saved")
        elif choice == "3":
            val = prompt("Supabase Secret", settings.get("supabase_secret"))
            settings["supabase_secret"] = val
            save_json("settings.json", settings)
            success("Saved")
        elif choice == "4":
            if confirm("Clear all settings?"):
                save_json("settings.json", {})
                success("Settings cleared")

# ─── Main Menu ────────────────────────────────────────────────────────────────

def main_menu():
    while True:
        clear()
        banner()
        status_line()
        print()
        print(f"  {C_BOLD}[1]{C_RESET} Accounts")
        print(f"  {C_BOLD}[2]{C_RESET} Deploy new instance")
        print(f"  {C_BOLD}[3]{C_RESET} Remove deployment")
        print(f"  {C_BOLD}[4]{C_RESET} Sync from GitHub")
        print(f"  {C_BOLD}[5]{C_RESET} View status")
        print(f"  {C_BOLD}[6]{C_RESET} View logs")
        print(f"  {C_BOLD}[7]{C_RESET} Settings")
        print(f"  {C_BOLD}[0]{C_RESET} Quit\n")

        choice = prompt("Choice")
        if choice == "0" or choice.lower() == "q":
            print(f"\n  {C_DIM}Bye!{C_RESET}\n")
            break
        elif choice == "1":
            screen_accounts()
        elif choice == "2":
            screen_deploy()
        elif choice == "3":
            screen_remove()
        elif choice == "4":
            screen_sync()
        elif choice == "5":
            screen_status()
        elif choice == "6":
            screen_logs()
        elif choice == "7":
            screen_settings()

# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for f in ["accounts.json", "deployments.json", "settings.json"]:
        p = DATA_DIR / f
        if not p.exists():
            p.write_text("{}")
    try:
        main_menu()
    except (KeyboardInterrupt, EOFError):
        print(f"\n\n  {C_DIM}Bye!{C_RESET}\n")
        sys.exit(0)
