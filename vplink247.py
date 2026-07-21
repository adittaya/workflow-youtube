#!/usr/bin/env python3
"""
vplink247 — VPLink 24/7 Automation Deployer & Manager
One-command management: accounts, deployment, testing, and monitoring.
"""

import os, sys, json, time, random, string, shutil, tempfile, subprocess, base64, urllib.request, urllib.error, argparse
from pathlib import Path

# ── ANSI helpers ──────────────────────────────────────────
C = "\033[36m"; G = "\033[32m"; Y = "\033[33m"; R = "\033[31m"
B = "\033[1m"; M = "\033[35m"; N = "\033[0m"; D = "\033[2m"

_STDIN_TTY = sys.stdin.isatty()
VERSION = "1.0.0"
CONFIG_DIR = Path.home() / ".vplink247"
ACCOUNTS_FILE = CONFIG_DIR / "accounts.json"
DEPLOYMENTS_FILE = CONFIG_DIR / "deployments.json"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
TEMPLATE_REPO = "adittaya/workflow-vplink"
GITHUB_API = "https://api.github.com"


# ── TUI toolkit (self-contained, no external deps) ───────

def _say(text):       print(f"  {text}")
def _ok(text):        print(f"  {G}✓{N} {text}")
def _warn(text):      print(f"  {Y}{text}{N}")
def _fail(text):      print(f"  {R}{text}{N}")
def _dim(text):       print(f"  {D}{text}{N}")
def _prompt(text):    return input(f"  {C}?{N} {B}{text}{N} ").strip()

_hline = f"  {C}────────────────────────────────────────────{N}"
_dash  = f"  {D}{'─'*44}{N}"

def _header(text):
    pad = max(2, 44 - len(text))
    print()
    print(f"  {C}╭{'─'*44}╮{N}")
    print(f"  {C}│{N}   {B}{text}{N}{' ' * (pad - 3)}  {C}│{N}")
    print(f"  {C}╰{'─'*44}╯{N}")
    print()

def _choose(opts):
    for i, o in enumerate(opts, 1):
        print(f"    {C}{i:>2}{N}) {o}")
    print()
    while True:
        raw = input(f"  {B}Select{N} [1-{len(opts)}, 0=back] {C}»{N} ").strip()
        if raw == "0": return -1
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(opts): return idx
        print(f"  {Y}Enter a number 1-{len(opts)} or 0 to go back.{N}")

def _confirm(text):
    raw = input(f"  {C}?{N} {text} {D}(y/N){N} ").strip().lower()
    return raw == "y"

def _pause():
    try:
        input(f"\n  {D}Press Enter to continue...{N}")
    except (EOFError, KeyboardInterrupt):
        pass

def _input_secret(prompt):
    import getpass
    return getpass.getpass(f"  {C}?{N} {B}{prompt}{N} ").strip()


# ── JSON helpers ─────────────────────────────────────────

def _load_json(path):
    if path.exists():
        with open(path) as f: return json.load(f)
    return {}

def _save_json(path, data):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f: json.dump(data, f, indent=2)

def load_accounts():    return _load_json(ACCOUNTS_FILE)
def save_accounts(d):   _save_json(ACCOUNTS_FILE, d)
def load_deployments(): return _load_json(DEPLOYMENTS_FILE)
def save_deployments(d): _save_json(DEPLOYMENTS_FILE, d)
def get_setting(k):     return _load_json(SETTINGS_FILE).get(k)
def set_setting(k, v):  s = _load_json(SETTINGS_FILE); s[k] = v; _save_json(SETTINGS_FILE, s)


# ── GitHub API ────────────────────────────────────────────

def _api(token, method, path, data=None):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "vplink247/1.0",
    }
    body = json.dumps(data).encode() if data is not None else None
    if data is not None: headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{GITHUB_API}{path}", data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode() if e.fp else ""
        raise SystemExit(f"  {R}GitHub API error {e.code}:{N} {detail}")
    except urllib.error.URLError as e:
        raise SystemExit(f"  {R}Network error:{N} {e.reason}")

def _encrypt_secret(public_key_content, secret_value):
    import nacl.bindings
    from base64 import b64decode, b64encode
    pk = b64decode(public_key_content)
    encrypted = nacl.bindings.crypto_box_seal(secret_value.encode(), pk)
    return b64encode(encrypted).decode()

def _set_secret(token, owner, repo, name, value):
    pub = _api(token, "GET", f"/repos/{owner}/{repo}/actions/secrets/public-key")
    encrypted = _encrypt_secret(pub["key"], value)
    _api(token, "PUT", f"/repos/{owner}/{repo}/actions/secrets/{name}",
         {"encrypted_value": encrypted, "key_id": pub["key_id"]})

def _trigger_workflow(token, owner, repo, key):
    _api(token, "POST", f"/repos/{owner}/{repo}/actions/workflows/continuous.yml/dispatches",
         {"ref": "main", "inputs": {"key": key}})

def _get_workflow_id(token, owner, repo):
    wfs = _api(token, "GET", f"/repos/{owner}/{repo}/actions/workflows")
    for wf in wfs.get("workflows", []):
        if wf["path"].endswith("continuous.yml"):
            return wf["id"], wf["state"]
    return None, None

def _set_workflow_state(token, owner, repo, disable=True):
    wid, state = _get_workflow_id(token, owner, repo)
    if not wid: _fail("Workflow continuous.yml not found"); return False
    if disable and state == "disabled_inactivity":
        _ok("Workflow already disabled (inactivity)"); return True
    if disable and state == "disabled_manually":
        _ok("Workflow already disabled"); return True
    if not disable and state == "active":
        _ok("Workflow already active"); return True
    action = "disable" if disable else "enable"
    _api(token, "PUT", f"/repos/{owner}/{repo}/actions/workflows/{wid}/{action}")
    return True


# ── Account commands ─────────────────────────────────────

def _verify_token(token):
    try:
        user = _api(token, "GET", "/user")
        login = user.get("login", "?")
        return True, login
    except SystemExit:
        return False, None

def cmd_login(args):
    _header("🔑 Login with GitHub Token")
    _say("Paste your GitHub personal access token (classic, repo scope).")
    _say("It will be validated before saving.\n")
    token = args.token or _prompt("GitHub token")
    if not token: _fail("Token is required"); return
    ok, login = _verify_token(token)
    if not ok:
        _fail("Token rejected — check it has repo scope and is valid")
        return
    accounts = load_accounts()
    if login in accounts:
        accounts[login]["token"] = token
        accounts[login]["created_at"] = time.time()
        _ok(f"Updated token for existing account '{login}'")
    else:
        accounts[login] = {"token": token, "created_at": time.time()}
        _ok(f"Authenticated as {G}{login}{N}")
    save_accounts(accounts)
    set_setting("active_account", login)
    _ok(f"Account '{login}' set as active")

def cmd_account_add(args):
    name = args.name or _prompt("Account name") or "default"
    token = args.token or _prompt("GitHub token (classic PAT, repo scope)")
    if not name or not token:
        _fail("Name and token are required"); return
    ok, login = _verify_token(token)
    if not ok:
        _fail("Token rejected — check it has repo scope and is valid")
        return
    accounts = load_accounts()
    accounts[name] = {"token": token, "github_user": login, "created_at": time.time()}
    save_accounts(accounts)
    set_setting("active_account", name)
    _ok(f"Account '{name}' added (authenticated as {C}{login}{N}) and set as active")

def cmd_account_list(_args):
    accounts = load_accounts(); active = get_setting("active_account")
    if not accounts: _warn("No accounts. Use 'vplink247 login'"); return
    _say(f"{'':3} {C}{'Name':20}{N} {'Active':6} {'GitHub User':20} {'Created':20}")
    _say(f"{'':3} {D}{'─'*20}{N} {'─'*6} {'─'*20} {'─'*20}")
    for name, info in accounts.items():
        mark = f"{G}●{N}" if name == active else f"{D}○{N}"
        gh = info.get("github_user", "?")
        added = time.strftime("%Y-%m-%d %H:%M", time.localtime(info.get("created_at", 0)))
        _say(f"  {mark:3} {name:20} {f'{G}YES{N}' if name == active else '':6} {gh:20} {added:20}")

def cmd_account_switch(args):
    accounts = load_accounts()
    if not args.name:
        if not accounts: _warn("No accounts."); return
        _say(f"Available: {', '.join(accounts.keys())}")
        args.name = _prompt("Switch to")
    if args.name not in accounts: _fail(f"Account '{args.name}' not found"); return
    set_setting("active_account", args.name)
    _ok(f"Switched to '{args.name}'")

def cmd_account_remove(args):
    accounts = load_accounts()
    if args.name not in accounts: _fail(f"Account '{args.name}' not found"); return
    if not _confirm(f"Remove account '{args.name}'?"): _say("Cancelled"); return
    del accounts[args.name]; save_accounts(accounts)
    if get_setting("active_account") == args.name:
        remaining = list(accounts.keys())
        set_setting("active_account", remaining[0] if remaining else None)
    _ok(f"Removed '{args.name}'")


# ── Deploy commands ─────────────────────────────────────

def cmd_deploy(args):
    accounts = load_accounts(); active = get_setting("active_account")
    if not active or active not in accounts: _fail("No active account. Add one first: vplink247 account add"); return
    token = accounts[active]["token"]
    repo_name = args.name or ""
    if not repo_name:
        auto = _prompt("Repo name (enter for random)")
        repo_name = auto or "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
    key = args.key or _prompt("VPLink key to automate") or "UbpV2D"
    _hline
    _header("Supabase Configuration")
    supabase_url = args.supabase_url or _prompt("Supabase URL")
    supabase_key = args.supabase_key or _prompt("Supabase anon/public key")
    supabase_secret = args.supabase_secret or _input_secret("Supabase service/secret key")
    _hline
    _say(f"Deploying to {C}{active}/{repo_name}{N} ...")
    print()
    # 1. Create repo
    _say(f"  {C}▸{N} Creating repository ...")
    repo = _api(token, "POST", "/user/repos", {
        "name": repo_name, "private": False, "auto_init": True,
        "description": "VPLink 24/7 Automation — endless relay chain"
    })
    clone_url = repo["clone_url"]
    _ok(f"Created {repo['html_url']}")
    # 2. Push template
    _say(f"  {C}▸{N} Pushing automation code ...")
    with tempfile.TemporaryDirectory(prefix="vplink247-") as tmpdir:
        tgt = Path(tmpdir) / repo_name
        subprocess.run(["git", "clone", "--depth=1", f"https://github.com/{TEMPLATE_REPO}.git", str(tgt)],
                       capture_output=True, check=True)
        subprocess.run(["rm", "-rf", str(tgt / ".git")], capture_output=True)
        subprocess.run(["git", "init", "-b", "main"], cwd=str(tgt), capture_output=True, check=True)
        subprocess.run(["git", "add", "-A"], cwd=str(tgt), capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "initial deploy by vplink247"],
                       cwd=str(tgt), capture_output=True, check=True)
        authed = clone_url.replace("https://", f"https://{token}@")
        subprocess.run(["git", "remote", "add", "origin", authed], cwd=str(tgt), capture_output=True, check=True)
        subprocess.run(["git", "push", "-u", "origin", "main", "--force"],
                       cwd=str(tgt), capture_output=True, timeout=120)
    # 3. Secrets
    _say(f"  {C}▸{N} Configuring GitHub Secrets ...")
    for sn, sv in [("SUPABASE_URL", supabase_url), ("SUPABASE_KEY", supabase_key),
                   ("SUPABASE_SECRET", supabase_secret), ("GH_PAT", token)]:
        _set_secret(token, active, repo_name, sn, sv)
    _ok("Secrets set (SUPABASE_URL, KEY, SECRET, GH_PAT)")
    # 4. Save
    deps = load_deployments()
    deps[repo_name] = {"account": active, "key": key, "repo_url": repo["html_url"], "created_at": time.time()}
    save_deployments(deps)
    # 5. Trigger
    _say(f"  {C}▸{N} Triggering first run ...")
    _trigger_workflow(token, active, repo_name, key)
    _ok("Workflow dispatched")
    print()
    print(f"  {G}╭{'─'*46}╮{N}")
    print(f"  {G}│{N}  {B}✓ DEPLOYED SUCCESSFULLY{N}{' ' * 24} {G}│{N}")
    print(f"  {G}├{'─'*46}┤{N}")
    print(f"  {G}│{N}  Repo:  {C}{repo['html_url']:<39}{N} {G}│{N}")
    print(f"  {G}│{N}  Name:  {C}{repo_name:<39}{N} {G}│{N}")
    print(f"  {G}│{N}  Key:   {C}{key:<39}{N} {G}│{N}")
    print(f"  {G}╰{'─'*46}╯{N}")
    print(f"\n  Run {C}vplink247 test {repo_name}{N} to verify it works.\n")

def cmd_deploy_list(_args):
    deps = load_deployments()
    if not deps: _warn("No deployments."); return
    _say(f"  {C}{'Name':25} {'Account':20} {'Key':15} {'Created':20}{N}")
    _say(f"  {D}{'─'*25} {'─'*20} {'─'*15} {'─'*20}{N}")
    for name, info in sorted(deps.items()):
        created = time.strftime("%Y-%m-%d %H:%M", time.localtime(info.get("created_at", 0)))
        _say(f"  {name:25} {info.get('account','?'):20} {info.get('key','?'):15} {created:20}")

def cmd_deploy_remove(args):
    deps = load_deployments()
    if args.name not in deps: _fail(f"Deployment '{args.name}' not found"); return
    info = deps[args.name]
    accounts = load_accounts()
    token = accounts.get(info["account"], {}).get("token")
    if token and _confirm(f"Also delete the GitHub repo '{info['account']}/{args.name}'?"):
        _api(token, "DELETE", f"/repos/{info['account']}/{args.name}")
        _ok("Repo deleted")
    del deps[args.name]; save_deployments(deps)
    _ok(f"Deployment '{args.name}' removed")


# ── Stop / Start ─────────────────────────────────────────

def _get_deployment_info(name):
    deps = load_deployments()
    if name not in deps: _fail(f"Deployment '{name}' not found"); return None
    info = deps[name]
    accounts = load_accounts()
    token = accounts.get(info["account"], {}).get("token")
    if not token: _fail(f"Account '{info['account']}' not found"); return None
    return info["account"], name, token, info.get("key", "?")

def cmd_stop(args):
    r = _get_deployment_info(args.name)
    if not r: return
    owner, repo, token, key = r
    _say(f"Stopping {C}{owner}/{repo}{N} ...")
    if _set_workflow_state(token, owner, repo, disable=True):
        _ok(f"Automation stopped for '{args.name}'")

def cmd_start(args):
    r = _get_deployment_info(args.name)
    if not r: return
    owner, repo, token, key = r
    _say(f"Starting {C}{owner}/{repo}{N} ...")
    if _set_workflow_state(token, owner, repo, disable=False):
        _ok(f"Automation started for '{args.name}'")

# ── Test / Status ────────────────────────────────────────

def cmd_test(args):
    deps = load_deployments()
    if args.name not in deps:
        _fail(f"Deployment '{args.name}' not found")
        _say(f"Available: {', '.join(sorted(deps.keys()))}"); return
    info = deps[args.name]
    accounts = load_accounts()
    token = accounts.get(info["account"], {}).get("token")
    if not token: _fail(f"Account '{info['account']}' not found"); return
    owner, repo_name = info["account"], args.name
    _hline
    _say(f"Testing: {C}{owner}/{repo_name}{N}  |  Key: {C}{info['key']}{N}")
    _say(f"{C}▸{N} Dispatching workflow ...")
    _trigger_workflow(token, owner, repo_name, info["key"])
    _say(f"{C}▸{N} Waiting for run to start ...")
    run_id = None
    for _ in range(12):
        time.sleep(5)
        runs = _api(token, "GET", f"/repos/{owner}/{repo_name}/actions/runs?per_page=1&status=queued")
        all_runs = runs.get("workflow_runs", [])
        if all_runs: run_id = all_runs[0]["id"]; break
    if not run_id:
        for _ in range(12):
            time.sleep(5)
            runs = _api(token, "GET", f"/repos/{owner}/{repo_name}/actions/runs?per_page=1")
            all_runs = runs.get("workflow_runs", [])
            if all_runs and all_runs[0]["status"] != "completed":
                run_id = all_runs[0]["id"]; break
    if not run_id:
        _fail("Could not detect a running workflow. Check:")
        _say(f"  https://github.com/{owner}/{repo_name}/actions"); return
    _ok(f"Run started #{run_id}")
    _say(f"{C}▸{N} Monitoring (every 15s) ...")
    last_status = ""
    for _ in range(40):
        time.sleep(15)
        run = _api(token, "GET", f"/repos/{owner}/{repo_name}/actions/runs/{run_id}")
        status = run.get("status", "?"); conclusion = run.get("conclusion")
        line = f"status: {status}" + (f", conclusion: {conclusion}" if conclusion else "")
        if line != last_status:
            _say(f"  {C}▸{N} {line}")
            last_status = line
        if status == "completed":
            passed = conclusion == "success"
            if passed:
                print(f"\n  {G}╭{'─'*46}╮{N}")
                print(f"  {G}│{N}  {B}✓ AUTOMATION TEST PASSED{N}{' ' * 22} {G}│{N}")
                print(f"  {G}│{N}  Check the log at the URL below{' ' * 16} {G}│{N}")
                print(f"  {G}╰{'─'*46}╯{N}")
            else:
                print(f"\n  {R}╭{'─'*46}╮{N}")
                print(f"  {R}│{N}  {B}✗ AUTOMATION TEST FAILED{N}{' ' * 22} {R}│{N}")
                print(f"  {R}│{N}  Conclusion: {conclusion:<32} {R}│{N}")
                print(f"  {R}╰{'─'*46}╯{N}")
            print(f"\n      {run.get('html_url', '')}\n"); return
    _warn("Timed out. Check manually:")
    _say(f"  https://github.com/{owner}/{repo_name}/actions\n")

def cmd_status(_args):
    accounts = load_accounts(); active = get_setting("active_account")
    deps = load_deployments()
    _header("System Status")
    _say(f"{'Active account:':18} {C}{active or 'none'}{N}")
    _say(f"{'Accounts:':18} {len(accounts)}")
    _say(f"{'Deployments:':18} {len(deps)}")
    print()
    if not deps: _warn("No deployments. Use 'vplink247 deploy'"); return
    for name, info in sorted(deps.items()):
        accounts_data = load_accounts()
        token = accounts_data.get(info["account"], {}).get("token")
        status_str = "?"
        if token:
            try:
                runs = _api(token, "GET", f"/repos/{info['account']}/{name}/actions/runs?per_page=1")
                for r in runs.get("workflow_runs", []):
                    status_str = r.get("conclusion") or r.get("status", "?")
            except Exception:
                status_str = f"{R}err{N}"
        color = G if status_str == "success" else (Y if status_str in ("in_progress","queued","pending") else R)
        print(f"  {color}{'●':3}{N} {B}{name}{N}")
        print(f"      {'Account:':12} {info.get('account','?'):15} {'Key:':6} {info.get('key','?')}")
        print(f"      {'Status:':12} {color}{status_str}{N}")
        print(f"      {'URL:':12} {info.get('repo_url','')}")
        print()


# ── Menu system ──────────────────────────────────────────

def _summary_block():
    accounts = load_accounts(); active = get_setting("active_account")
    deps = load_deployments()
    _hline
    a = f"accounts: {len(accounts)}  ({G}{active}{N} active)" if active else f"accounts: {len(accounts)}  ({R}none active{N})"
    _say(f"{'  📦':4} {a}   |   deployments: {len(deps)}")
    _hline

def _menu_accounts():
    while True:
        accounts = load_accounts(); active = get_setting("active_account")
        _header("👤 Account Management")
        if accounts:
            _say(f"  Active: {G if active else ''}{active or 'none'}{N}")
            _dash
            for name in sorted(accounts.keys()):
                mark  = f"{G}●{N}" if name == active else f"{D}○{N}"
                extra = f"  {G}(active){N}" if name == active else ""
                _say(f"  {mark} {B}{name}{N}{extra}")
            _dash
        else:
            _warn("No accounts configured.")
        print()
        choice = _choose(["📋 List accounts", "🔑 Login with token", "➕ Add account", "🔀 Switch account", "🗑 Remove account"])
        if choice < 0: return
        if choice == 0:
            cmd_account_list(None); _pause()
        elif choice == 1:
            cmd_login(argparse.Namespace(token=None)); _pause()
        elif choice == 2:
            name = _prompt("Account name") or "default"
            token = _prompt("GitHub token (classic PAT, repo scope)")
            cmd_account_add(argparse.Namespace(name=name, token=token)); _pause()
        elif choice == 3:
            if not accounts: _warn("No accounts."); _pause(); continue
            _say(f"Available: {', '.join(accounts.keys())}")
            name = _prompt("Switch to")
            cmd_account_switch(argparse.Namespace(name=name))
        elif choice == 4:
            if not accounts: _warn("No accounts."); _pause(); continue
            name = _prompt("Account to remove")
            cmd_account_remove(argparse.Namespace(name=name))

def _menu_deployments():
    while True:
        deps = load_deployments(); active = get_setting("active_account")
        _header("🚀 Deployment Management")
        _say(f"  Deployments: {len(deps)}  |  Active account: {G if active else ''}{active or 'none'}{N}")
        if deps:
            _dash
            for name, info in sorted(deps.items()):
                key = info.get('key', '?')
                print(f"  {C}■{N} {B}{name}{N}  ({C}{key}{N})  →  {D}{info.get('account','?')}{N}")
            _dash
        print()
        choice = _choose(["📋 List deployments", "🚀 Deploy new relay", "🧪 Test deployment",
                          "⏹  Stop automation", "▶️  Start automation",
                          "🗑 Remove deployment", "⚡ Quick deploy (bare-bones)"])
        if choice < 0: return
        if choice == 0:
            cmd_deploy_list(None); _pause()
        elif choice == 1:
            cmd_deploy(argparse.Namespace(name=None, key=None,
                        supabase_url=None, supabase_key=None, supabase_secret=None)); _pause()
        elif choice == 2:
            if not deps: _warn("No deployments yet."); _pause(); continue
            name = _prompt("Deployment name to test")
            cmd_test(argparse.Namespace(name=name))
        elif choice == 3:
            if not deps: _warn("No deployments."); _pause(); continue
            name = _prompt("Deployment to stop")
            cmd_stop(argparse.Namespace(name=name))
        elif choice == 4:
            if not deps: _warn("No deployments."); _pause(); continue
            name = _prompt("Deployment to start")
            cmd_start(argparse.Namespace(name=name))
        elif choice == 5:
            if not deps: _warn("No deployments."); _pause(); continue
            name = _prompt("Deployment name to remove")
            cmd_deploy_remove(argparse.Namespace(name=name))
        elif choice == 6:
            accts = load_accounts()
            if not accts: _warn("No accounts. Add one first."); _pause(); continue
            name = _prompt("Repo name (enter for random)")
            key = _prompt("VPLink key to automate") or "UbpV2D"
            cmd_deploy(argparse.Namespace(name=name or None, key=key,
                        supabase_url=None, supabase_key=None, supabase_secret=None)); _pause()

def cmd_wizard(_args):
    if not _STDIN_TTY:
        _fail("Interactive menu requires a terminal.")
        _say("Use CLI flags instead:")
        _say("  vplink247 account add default --token ghp_xxxxx")
        _say("  vplink247 deploy new --name my-relay --key UbpV2D --supabase-url ...")
        return
    try:
        _run_menu()
    except KeyboardInterrupt:
        print(f"\n  {Y}Bye.{N}\n")
    except SystemExit:
        pass

def _run_menu():
    while True:
        accounts = load_accounts(); active = get_setting("active_account")
        deps = load_deployments()
        print(f"\n  {C}╭{'─'*44}╮{N}")
        print(f"  {C}│{N}   {B}vplink247 v{VERSION}{N}  —  {D}VPLink 24/7 Manager{N}  {C}│{N}")
        print(f"  {C}╰{'─'*44}╯{N}")
        _summary_block()
        print()
        choice = _choose([
            f"👤  Account Management      {D}{len(accounts)} account(s){N}",
            f"🚀  Deployment Management   {D}{len(deps)} deployment(s){N}",
            f"📊  Status & Monitoring     {D}live workflow health{N}",
            f"📖  Help / All Commands     {D}CLI reference{N}",
        ])
        if choice < 0:
            print(f"  {Y}Bye.{N}\n"); break
        if choice == 0:      _menu_accounts()
        elif choice == 1:    _menu_deployments()
        elif choice == 2:    cmd_status(None); _pause()
        elif choice == 3:
            _header("📖 CLI Reference")
            print(f"    {C}vplink247{N}                   Interactive menu (this)")
            print(f"    {C}vplink247 setup{N}             Same as above")
            print(f"    {C}vplink247 account add{N}       Add a GitHub account")
            print(f"    {C}vplink247 account list{N}      List accounts")
            print(f"    {C}vplink247 account switch{N}    Switch active account")
            print(f"    {C}vplink247 login <token>{N}     Login (validates against API)")
            print(f"    {C}vplink247 account list{N}      List accounts")
            print(f"    {C}vplink247 account add{N}       Add account with name + token")
            print(f"    {C}vplink247 account switch{N}    Switch active account")
            print(f"    {C}vplink247 account remove{N}    Remove an account")
            print(f"    {C}vplink247 deploy new{N}        Create a new deployment")
            print(f"    {C}vplink247 deploy list{N}       List deployments")
            print(f"    {C}vplink247 deploy remove{N}     Remove a deployment")
            print(f"    {C}vplink247 test <name>{N}       Test a deployment")
            print(f"    {C}vplink247 stop <name>{N}       Stop (disable) automation")
            print(f"    {C}vplink247 start <name>{N}      Start (enable) automation")
            print(f"    {C}vplink247 status{N}            Show overall status")
            print()
            print(f"  {B}Flags:{N}")
            print(f"    account add default {C}--token ghp_xxxxx{N}")
            print(f"    login {C}ghp_xxxxx{N}")
            print(f"    deploy new {C}--name my-relay --key UbpV2D{N}")
            print(f"      {C}--supabase-url <url> --supabase-key <key>{N}")
            print(f"      {C}--supabase-secret <secret>{N}")
            _pause()


# ── Main entry point ─────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="vplink247",
        description="VPLink 24/7 Automation Deployer & Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  vplink247                       Interactive management menu
  vplink247 account add           Add a GitHub account
  vplink247 account list          List all accounts
  vplink247 deploy new            Deploy automation relay
  vplink247 deploy list           List deployments
  vplink247 test <name>           Test a deployment
  vplink247 stop <name>           Stop (disable) automation
  vplink247 start <name>          Start (enable) automation
  vplink247 status                Show overall status
        """
    )
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("setup", aliases=["menu"], help="Interactive management menu")
    p.set_defaults(func=cmd_wizard)

    acct = sub.add_parser("account", help="Manage GitHub accounts")
    acct_sub = acct.add_subparsers(dest="subcmd")
    p = acct_sub.add_parser("add", help="Add a GitHub account")
    p.add_argument("name", nargs="?", help="Account name")
    p.add_argument("--token", help="GitHub personal access token")
    p.set_defaults(func=cmd_account_add)
    p = acct_sub.add_parser("list", help="List accounts")
    p.set_defaults(func=cmd_account_list)
    p = acct_sub.add_parser("switch", help="Switch active account")
    p.add_argument("name", nargs="?", help="Account name")
    p.set_defaults(func=cmd_account_switch)
    p = acct_sub.add_parser("remove", help="Remove an account")
    p.add_argument("name", help="Account name")
    p.set_defaults(func=cmd_account_remove)

    dep = sub.add_parser("deploy", help="Deploy automation")
    dep_sub = dep.add_subparsers(dest="subcmd")
    p = dep_sub.add_parser("new", aliases=["create"], help="Create a new deployment")
    p.add_argument("--name", help="Repository name (default: random)")
    p.add_argument("--key", help="VPLink key to automate")
    p.add_argument("--supabase-url", help="Supabase project URL")
    p.add_argument("--supabase-key", help="Supabase anon key")
    p.add_argument("--supabase-secret", help="Supabase service key")
    p.set_defaults(func=cmd_deploy)
    p = dep_sub.add_parser("list", help="List deployments")
    p.set_defaults(func=cmd_deploy_list)
    p = dep_sub.add_parser("remove", help="Remove a deployment")
    p.add_argument("name", help="Deployment name")
    p.set_defaults(func=cmd_deploy_remove)

    p = sub.add_parser("test", help="Test a deployment")
    p.add_argument("name", help="Deployment name")
    p.set_defaults(func=cmd_test)

    p = sub.add_parser("stop", help="Stop (disable) automation for a deployment")
    p.add_argument("name", help="Deployment name")
    p.set_defaults(func=cmd_stop)

    p = sub.add_parser("start", help="Start (enable) automation for a deployment")
    p.add_argument("name", help="Deployment name")
    p.set_defaults(func=cmd_start)

    p = sub.add_parser("login", help="Login with GitHub token (validates & saves)")
    p.add_argument("token", nargs="?", help="GitHub token")
    p.set_defaults(func=cmd_login)

    p = sub.add_parser("status", help="Show overall status")
    p.set_defaults(func=cmd_status)

    args = parser.parse_args()

    if not args.command:
        cmd_wizard(args)
        return

    if args.command == "deploy" and not getattr(args, "subcmd", None):
        args.func = cmd_deploy

    try:
        args.func(args)
    except SystemExit:
        raise
    except KeyboardInterrupt:
        print(f"\n  {Y}Interrupted.{N}\n")
    except Exception as e:
        print(f"\n  {R}[!] Error:{N} {e}\n", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
