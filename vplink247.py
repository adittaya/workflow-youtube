#!/usr/bin/env python3
"""
vplink247 — VPLink 24/7 Automation Deployer & Manager
One-command management: accounts, deployment, testing, and monitoring.
"""

import os, sys, json, time, random, string, shutil, tempfile, subprocess, base64, urllib.request, urllib.error, argparse
from pathlib import Path

_STDIN_TTY = sys.stdin.isatty()

try:
    from installer.interactive import confirm, choose, input_text, header
    _HAS_TUI = True
except ImportError:
    _HAS_TUI = False

VERSION = "1.0.0"
CONFIG_DIR = Path.home() / ".vplink247"
ACCOUNTS_FILE = CONFIG_DIR / "accounts.json"
DEPLOYMENTS_FILE = CONFIG_DIR / "deployments.json"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
TEMPLATE_REPO = "adittaya/workflow-vplink"
GITHUB_API = "https://api.github.com"


def _print_header():
    print(f"\n  {'='*50}")
    print(f"   vplink247 v{VERSION} — VPLink 24/7 Automation Manager")
    print(f"  {'='*50}\n")


def _load_json(path):
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def _save_json(path, data):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def load_accounts():
    return _load_json(ACCOUNTS_FILE)


def save_accounts(data):
    _save_json(ACCOUNTS_FILE, data)


def load_deployments():
    return _load_json(DEPLOYMENTS_FILE)


def save_deployments(data):
    _save_json(DEPLOYMENTS_FILE, data)


def get_setting(key):
    return _load_json(SETTINGS_FILE).get(key)


def set_setting(key, value):
    s = _load_json(SETTINGS_FILE)
    s[key] = value
    _save_json(SETTINGS_FILE, s)


def _api(token, method, path, data=None):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "vplink247/1.0",
    }
    body = json.dumps(data).encode() if data is not None else None
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{GITHUB_API}{path}", data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode() if e.fp else ""
        raise SystemExit(f"  GitHub API error {e.code}: {detail}")
    except urllib.error.URLError as e:
        raise SystemExit(f"  Network error: {e.reason}")


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


###############################################################################
#  ACCOUNT COMMANDS
###############################################################################

def cmd_account_add(args):
    name = args.name or input("  Account name: ").strip()
    token = args.token or input("  GitHub personal access token (classic, full repo scope): ").strip()
    if not name or not token:
        print("  Error: name and token are required")
        return
    accounts = load_accounts()
    accounts[name] = {"token": token, "created_at": time.time()}
    save_accounts(accounts)
    set_setting("active_account", name)
    print(f"  ✓ Account '{name}' added and set as active")


def cmd_account_list(_args):
    accounts = load_accounts()
    active = get_setting("active_account")
    if not accounts:
        print("  No accounts configured. Use 'vplink247 account add'")
        return
    print(f"  {'':3} {'Name':20} {'Active':6} {'Added':20}")
    print(f"  {'':3} {'-'*20} {'-'*6} {'-'*20}")
    for name, info in accounts.items():
        marker = "●" if name == active else "○"
        added = time.strftime("%Y-%m-%d %H:%M", time.localtime(info.get("created_at", 0)))
        print(f"  {marker:3} {name:20} {'YES' if name == active else '':6} {added:20}")


def cmd_account_switch(args):
    accounts = load_accounts()
    if not args.name:
        if not accounts:
            print("  No accounts to switch to.")
            return
        print("  Available accounts:")
        for name in accounts:
            print(f"    {name}")
        args.name = input("  Switch to: ").strip()
    if args.name not in accounts:
        print(f"  Account '{args.name}' not found")
        return
    set_setting("active_account", args.name)
    print(f"  ✓ Switched to '{args.name}'")


def cmd_account_remove(args):
    accounts = load_accounts()
    if args.name not in accounts:
        print(f"  Account '{args.name}' not found")
        return
    confirm = input(f"  Remove account '{args.name}'? (y/N): ").strip().lower()
    if confirm != "y":
        print("  Cancelled")
        return
    del accounts[args.name]
    save_accounts(accounts)
    if get_setting("active_account") == args.name:
        remaining = list(accounts.keys())
        set_setting("active_account", remaining[0] if remaining else None)
    print(f"  ✓ Removed '{args.name}'")


###############################################################################
#  DEPLOY COMMANDS
###############################################################################

def cmd_deploy(args):
    accounts = load_accounts()
    active = get_setting("active_account")
    if not active or active not in accounts:
        print("  No active account. Add one first: vplink247 account add")
        return
    token = accounts[active]["token"]

    repo_name = args.name or ""
    if not repo_name:
        auto = input("  Repo name (enter for random 10-char): ").strip()
        repo_name = auto or "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
    key = args.key or input("  VPLink key to automate (e.g. UbpV2D): ").strip() or "UbpV2D"

    print("\n  — Supabase Configuration —")
    supabase_url = args.supabase_url or input("  Supabase URL: ").strip()
    supabase_key = args.supabase_key or input("  Supabase anon/public key: ").strip()
    supabase_secret = args.supabase_secret or input("  Supabase service/secret key: ").strip()

    print(f"\n  Deploying to '{active}/{repo_name}'...")

    # 1. Create repo
    print(f"  [{'>'}] Creating repository...")
    repo = _api(token, "POST", "/user/repos", {
        "name": repo_name, "private": False, "auto_init": True,
        "description": "VPLink 24/7 Automation — endless relay chain"
    })
    clone_url = repo["clone_url"]
    print(f"  [✓] Created: {repo['html_url']}")

    # 2. Clone template and push
    print(f"  [{'>'}] Pushing automation code...")
    with tempfile.TemporaryDirectory(prefix="vplink247-") as tmpdir:
        tgt = Path(tmpdir) / repo_name
        subprocess.run(
            ["git", "clone", "--depth=1", f"https://github.com/{TEMPLATE_REPO}.git", str(tgt)],
            capture_output=True, check=True
        )
        subprocess.run(["rm", "-rf", str(tgt / ".git")], capture_output=True)
        subprocess.run(["git", "init", "-b", "main"], cwd=str(tgt), capture_output=True, check=True)
        subprocess.run(["git", "add", "-A"], cwd=str(tgt), capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "initial deploy by vplink247"],
            cwd=str(tgt), capture_output=True, check=True,
        )
        authed = clone_url.replace("https://", f"https://{token}@")
        subprocess.run(
            ["git", "remote", "add", "origin", authed],
            cwd=str(tgt), capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "push", "-u", "origin", "main", "--force"],
            cwd=str(tgt), capture_output=True, timeout=120,
        )

    # 3. Set secrets
    print(f"  [{'>'}] Configuring GitHub Secrets...")
    for sn, sv in [("SUPABASE_URL", supabase_url), ("SUPABASE_KEY", supabase_key),
                   ("SUPABASE_SECRET", supabase_secret), ("GH_PAT", token)]:
        _set_secret(token, active, repo_name, sn, sv)
    print(f"  [✓] Secrets set (SUPABASE_URL, SUPABASE_KEY, SUPABASE_SECRET, GH_PAT)")

    # 4. Save deployment
    deps = load_deployments()
    deps[repo_name] = {
        "account": active, "key": key,
        "repo_url": repo["html_url"],
        "created_at": time.time(),
    }
    save_deployments(deps)

    # 5. Trigger
    print(f"  [{'>'}] Triggering first run...")
    _trigger_workflow(token, active, repo_name, key)
    print(f"  [✓] Workflow dispatched")

    print(f"\n  ╔══════════════════════════════════════════════╗")
    print(f"  ║  ✓ DEPLOYED SUCCESSFULLY                    ║")
    print(f"  ╠══════════════════════════════════════════════╣")
    print(f"  ║  Repo:  {repo['html_url']:<43}║")
    print(f"  ║  Name:  {repo_name:<43}║")
    print(f"  ║  Key:   {key:<43}║")
    print(f"  ╚══════════════════════════════════════════════╝")
    print(f"\n  Run 'vplink247 test {repo_name}' to verify it works.\n")


def cmd_deploy_list(_args):
    deps = load_deployments()
    if not deps:
        print("  No deployments. Use 'vplink247 deploy'")
        return
    print(f"  {'Name':25} {'Account':20} {'Key':15} {'Created':20}")
    print(f"  {'-'*25} {'-'*20} {'-'*15} {'-'*20}")
    for name, info in sorted(deps.items()):
        created = time.strftime("%Y-%m-%d %H:%M", time.localtime(info.get("created_at", 0)))
        print(f"  {name:25} {info.get('account','?'):20} {info.get('key','?'):15} {created:20}")


def cmd_deploy_remove(args):
    deps = load_deployments()
    if args.name not in deps:
        print(f"  Deployment '{args.name}' not found")
        return
    info = deps[args.name]
    accounts = load_accounts()
    token = accounts.get(info["account"], {}).get("token")
    if token:
        confirm = input(f"  Also delete the GitHub repo '{info['account']}/{args.name}'? (y/N): ").strip().lower()
        if confirm == "y":
            _api(token, "DELETE", f"/repos/{info['account']}/{args.name}")
            print(f"  [✓] Repo deleted")
    del deps[args.name]
    save_deployments(deps)
    print(f"  [✓] Deployment '{args.name}' removed from local tracking")


###############################################################################
#  TEST / STATUS COMMANDS
###############################################################################

def cmd_test(args):
    deps = load_deployments()
    if args.name not in deps:
        print(f"  Deployment '{args.name}' not found")
        print("  Available:", ", ".join(sorted(deps.keys())))
        return
    info = deps[args.name]
    accounts = load_accounts()
    token = accounts.get(info["account"], {}).get("token")
    if not token:
        print(f"  Account '{info['account']}' not found (credentials missing)")
        return
    owner = info["account"]
    repo_name = args.name

    print(f"\n  Testing: {owner}/{repo_name}")
    print(f"  Key: {info['key']}")

    # Trigger
    print(f"  [{'>'}] Dispatching workflow...")
    _trigger_workflow(token, owner, repo_name, info["key"])

    # Poll
    print(f"  [{'>'}] Waiting for run to start...")
    run_id = None
    for _ in range(12):
        time.sleep(5)
        runs = _api(token, "GET", f"/repos/{owner}/{repo_name}/actions/runs?per_page=1&status=queued")
        all_runs = runs.get("workflow_runs", [])
        if all_runs:
            run_id = all_runs[0]["id"]
            break

    if not run_id:
        for _ in range(12):
            time.sleep(5)
            runs = _api(token, "GET", f"/repos/{owner}/{repo_name}/actions/runs?per_page=1")
            all_runs = runs.get("workflow_runs", [])
            if all_runs and all_runs[0]["status"] != "completed":
                run_id = all_runs[0]["id"]
                break

    if not run_id:
        print("  [✗] Could not detect a running workflow. Check manually:")
        print(f"      https://github.com/{owner}/{repo_name}/actions")
        return

    print(f"  [✓] Run started: #{run_id}")
    print(f"  [{'>'}] Monitoring (polling every 15s)...")

    last_status = ""
    for _ in range(40):
        time.sleep(15)
        run = _api(token, "GET", f"/repos/{owner}/{repo_name}/actions/runs/{run_id}")
        status = run.get("status", "?")
        conclusion = run.get("conclusion")
        line = f"    status: {status}"
        if conclusion:
            line += f", conclusion: {conclusion}"
        if line != last_status:
            print(f"  [{'>'}] {line}")
            last_status = line
        if status == "completed":
            passed = conclusion == "success"
            if passed:
                print(f"\n  ╔══════════════════════════════════════════════╗")
                print(f"  ║  ✓ AUTOMATION TEST PASSED                    ║")
                print(f"  ╠══════════════════════════════════════════════╣")
                print(f"  ║  Check the full log at the URL below        ║")
                print(f"  ╚══════════════════════════════════════════════╝")
            else:
                print(f"\n  ╔══════════════════════════════════════════════╗")
                print(f"  ║  ✗ AUTOMATION TEST FAILED                    ║")
                print(f"  ╠══════════════════════════════════════════════╣")
                print(f"  ║  Conclusion: {conclusion:<37}║")
                print(f"  ╚══════════════════════════════════════════════╝")
            print(f"\n      {run.get('html_url', '')}\n")
            return

    print(f"\n  [!] Timed out waiting. Check manually:")
    print(f"      https://github.com/{owner}/{repo_name}/actions\n")


def cmd_status(args):
    _print_header()
    accounts = load_accounts()
    active = get_setting("active_account")
    deps = load_deployments()

    print(f"  Active account: {active or 'none'}")
    print(f"  Accounts: {len(accounts)}")
    print(f"  Deployments: {len(deps)}\n")

    if not deps:
        print("  No deployments. Use 'vplink247 deploy'")
        return

    for name, info in sorted(deps.items()):
        accounts_data = load_accounts()
        token = accounts_data.get(info["account"], {}).get("token")
        status_str = "?"
        if token:
            try:
                runs = _api(token, "GET", f"/repos/{info['account']}/{name}/actions/runs?per_page=1")
                for r in runs.get("workflow_runs", []):
                    s = r.get("conclusion") or r.get("status", "?")
                    status_str = s
            except Exception:
                status_str = "err"
        print(f"  {name:25} {info.get('account','?'):20} {status_str:15}")
        print(f"  {'':25} {info.get('repo_url',''):45}")
        print()


###############################################################################
#  MENU / TUI
###############################################################################

def _print_summary():
    accounts = load_accounts()
    active = get_setting("active_account")
    deps = load_deployments()
    print(f"  Accounts:    {len(accounts)} ({active or 'none'} active)")
    print(f"  Deployments: {len(deps)}")
    if deps and active:
        tok = accounts.get(active, {}).get("token")
        if tok:
            n = sum(1 for d in deps.values() if d.get("account") == active)
            print(f"  Yours:       {n}")
    print()

def _menu_accounts():
    while True:
        accounts = load_accounts()
        active = get_setting("active_account")
        header("Account Management")
        print(f"  Active: {active or 'none'}  |  Total: {len(accounts)}\n")
        if accounts:
            print(f"  {'':3} {'Name':20} {'Active':6}")
            print(f"  {'':3} {'-'*20} {'-'*6}")
            for name in accounts:
                marker = "●" if name == active else "○"
                print(f"  {marker:3} {name:20} {'YES' if name == active else ''}")
        print()
        opts = ["List account details", "Add new account", "Switch account",
                "Remove account"]
        if not _HAS_TUI:
            opts.append("Back")
            choice = input("  Choice [0-4]: ").strip()
            if choice == "0": return
            choice = int(choice) - 1 if choice.isdigit() else -1
            if choice < 0 or choice >= len(opts): continue
        else:
            choice = choose("Options", opts)
            if choice == -1: return
        if choice == 0:
            cmd_account_list(None)
            input("\n  Press Enter to continue...")
        elif choice == 1:
            name = input("    Account name: ").strip() or "default"
            token = input("    GitHub personal access token (repo scope): ").strip()
            cmd_account_add(argparse.Namespace(name=name, token=token))
            input("\n  Press Enter to continue...")
        elif choice == 2:
            if not accounts:
                print("  No accounts to switch to.\n")
                continue
            print("  Available:", ", ".join(accounts.keys()))
            name = input("  Switch to: ").strip()
            cmd_account_switch(argparse.Namespace(name=name))
        elif choice == 3:
            if not accounts:
                print("  No accounts to remove.\n")
                continue
            name = input("  Account to remove: ").strip()
            cmd_account_remove(argparse.Namespace(name=name))

def _menu_deployments():
    while True:
        deps = load_deployments()
        header("Deployment Management")
        print(f"  Total deployments: {len(deps)}\n")
        if deps:
            print(f"  {'Name':25} {'Account':20} {'Key':15}")
            print(f"  {'-'*25} {'-'*20} {'-'*15}")
            for name, info in sorted(deps.items()):
                print(f"  {name:25} {info.get('account','?'):20} {info.get('key','?'):15}")
        print()
        opts = ["List deployments", "Deploy new relay", "Test deployment",
                "Remove deployment", "Quick deploy (wizard)"]
        if not _HAS_TUI:
            opts.append("Back")
            choice = input("  Choice [0-4]: ").strip()
            if choice == "0": return
            choice = int(choice) - 1 if choice.isdigit() else -1
            if choice < 0 or choice >= len(opts): continue
        else:
            choice = choose("Options", opts)
            if choice == -1: return
        if choice == 0:
            cmd_deploy_list(None)
            input("\n  Press Enter to continue...")
        elif choice == 1:
            cmd_deploy(argparse.Namespace(
                name=None, key=None,
                supabase_url=None, supabase_key=None, supabase_secret=None,
            ))
        elif choice == 2:
            if not deps:
                print("  No deployments yet.\n")
                continue
            name = input("  Deployment name to test: ").strip()
            cmd_test(argparse.Namespace(name=name))
        elif choice == 3:
            if not deps:
                print("  No deployments to remove.\n")
                continue
            name = input("  Deployment name to remove: ").strip()
            cmd_deploy_remove(argparse.Namespace(name=name))
        elif choice == 4:
            accounts = load_accounts()
            if not accounts:
                print("  No accounts. Add one first.\n")
                continue
            name = input("  Repo name (enter for random): ").strip()
            key = input("  VPLink key (e.g. UbpV2D): ").strip() or "UbpV2D"
            cmd_deploy(argparse.Namespace(
                name=name, key=key,
                supabase_url=None, supabase_key=None, supabase_secret=None,
            ))

def cmd_wizard(args):
    if not _STDIN_TTY:
        print("  [!] Interactive menu requires a terminal.\n")
        return
    try:
        menu_main()
    except (SystemExit, KeyboardInterrupt):
        pass

def menu_main():
    if not _STDIN_TTY:
        print("  [!] Interactive menu requires a terminal.\n")
        return
    _print_header()
    while True:
        _print_summary()
        opts = [
            "Account Management",
            "Deployment Management",
            "Status & Monitoring",
            "Help / All Commands",
        ]
        if not _HAS_TUI:
            print("  1) Account Management")
            print("  2) Deployment Management")
            print("  3) Status & Monitoring")
            print("  4) Help / All Commands")
            print("  0) Exit\n")
            choice = input("  Choice: ").strip()
            if choice == "0":
                print("\n  Bye.\n")
                break
            choice = int(choice) - 1 if choice.isdigit() else -1
            if choice < 0 or choice >= len(opts):
                continue
        else:
            choice = choose("Main Menu", opts)
            if choice == -1:
                print("\n  Bye.\n")
                break
        if choice == 0:
            _menu_accounts()
        elif choice == 1:
            _menu_deployments()
        elif choice == 2:
            cmd_status(None)
            input("\n  Press Enter to continue...")
        elif choice == 3:
            print("""
  Available commands:
    vplink247 setup              This interactive menu
    vplink247 account add        Add a GitHub account
    vplink247 account list       List all accounts
    vplink247 account switch     Switch active account
    vplink247 account remove     Remove an account
    vplink247 deploy new/create  Deploy automation relay
    vplink247 deploy list        List deployments
    vplink247 deploy remove      Remove a deployment
    vplink247 test <name>        Test a deployment
    vplink247 status             Show overall status

  Flags:
    vplink247 account add default --token ghp_xxxxx
    vplink247 deploy new --name my-relay --key UbpV2D
      --supabase-url <url> --supabase-key <key> --supabase-secret <secret>
""")
            input("  Press Enter to continue...")


###############################################################################
#  MAIN
###############################################################################

def main():
    parser = argparse.ArgumentParser(
        prog="vplink247",
        description="VPLink 24/7 Automation Deployer & Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  vplink247 setup                    Interactive setup wizard
  vplink247 account add              Add a GitHub account
  vplink247 account list             List all accounts
  vplink247 account switch <name>    Switch active account
  vplink247 deploy                   Deploy automation
  vplink247 deploy list              List deployments
  vplink247 test <name>              Test a deployment
  vplink247 status                   Show overall status
        """
    )

    sub = parser.add_subparsers(dest="command")

    # setup / menu
    p = sub.add_parser("setup", aliases=["menu"], help="Interactive management menu")
    p.set_defaults(func=cmd_wizard)

    # account group
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

    # deploy group
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

    # test
    p = sub.add_parser("test", help="Test a deployment")
    p.add_argument("name", help="Deployment name")
    p.set_defaults(func=cmd_test)

    # status
    p = sub.add_parser("status", help="Show overall status")
    p.set_defaults(func=cmd_status)

    args = parser.parse_args()

    if not args.command:
        cmd_wizard(args)
        return

    # deploy with no subcommand → interactive deploy
    if args.command == "deploy" and not getattr(args, "subcmd", None):
        args.func = cmd_deploy

    try:
        args.func(args)
    except SystemExit:
        raise
    except KeyboardInterrupt:
        print("\n  Interrupted.\n")
    except Exception as e:
        print(f"\n  [!] Error: {e}\n", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
