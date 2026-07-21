#!/usr/bin/env python3
import hashlib
import hmac
import json
import os
import random
import secrets
import sqlite3
import string
import subprocess
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from flask import (
    Flask, abort, jsonify, redirect, render_template, request, session, url_for,
)

DB_PATH = Path(__file__).parent / "manager.db"
TEMPLATE_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"
REPO_ROOT = Path(__file__).parent.parent

app = Flask(__name__, template_folder=str(TEMPLATE_DIR), static_folder=str(STATIC_DIR))
app.secret_key = os.environ.get("MANAGER_SECRET") or secrets.token_hex(32)


def get_db():
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    return db


def init_db():
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS github_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            token TEXT NOT NULL,
            username TEXT NOT NULL,
            email TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS proxy_credentials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            proxies TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS deployments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            github_account_id INTEGER NOT NULL,
            proxy_credential_id INTEGER,
            repo_name TEXT NOT NULL,
            repo_url TEXT NOT NULL,
            owner TEXT NOT NULL,
            vplink_key TEXT NOT NULL,
            status TEXT DEFAULT 'deploying',
            last_run_at TIMESTAMP,
            total_views INTEGER DEFAULT 0,
            total_destinations INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (github_account_id) REFERENCES github_accounts(id) ON DELETE CASCADE,
            FOREIGN KEY (proxy_credential_id) REFERENCES proxy_credentials(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS deployment_urls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            deployment_id INTEGER NOT NULL,
            url TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (deployment_id) REFERENCES deployments(id) ON DELETE CASCADE
        );
    """)
    db.commit()
    if not db.execute("SELECT id FROM users WHERE username='admin'").fetchone():
        db.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)",
                   ("admin", hash_password("admin")))
        db.commit()


def hash_password(password):
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000)
    return f"{salt}${h.hex()}"


def verify_password(password, stored):
    salt, h = stored.split("$", 1)
    return hmac.compare_digest(
        hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000).hex(),
        h
    )


def login_required(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*a, **kw):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*a, **kw)
    return wrapper


def gh_headers(token):
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}


def gh_api(method, url, token, **kw):
    resp = requests.request(method, url, headers=gh_headers(token), **kw)
    if resp.status_code >= 400:
        raise RuntimeError(f"GitHub API {resp.status_code}: {resp.text[:200]}")
    return resp.json() if resp.text else {}


def random_repo_name():
    adjs = ["bold", "quick", "swift", "calm", "eager", "fancy", "grand", "happy",
            "jolly", "keen", "lucky", "nice", "proud", "rapid", "sharp", "smart",
            "brave", "crisp", "fresh", "prime", "vivid", "agile", "brisk", "agile"]
    nouns = ["fox", "wolf", "bear", "deer", "hawk", "lion", "seal", "crow",
             "dove", "frog", "hare", "kite", "lark", "mole", "newt", "owl",
             "pike", "rail", "swan", "tern", "wren", "bass", "crab", "koi"]
    return f"vplink-{random.choice(adjs)}-{random.choice(nouns)}-{random.randint(100,999)}"


def random_password():
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=24))


def create_repo_and_deploy(deployment_id):
    db = get_db()
    dep = db.execute("SELECT * FROM deployments WHERE id=?", (deployment_id,)).fetchone()
    if not dep:
        return
    acct = db.execute("SELECT * FROM github_accounts WHERE id=?", (dep["github_account_id"],)).fetchone()
    if not acct or not acct["token"]:
        db.execute("UPDATE deployments SET status='error', updated_at=CURRENT_TIMESTAMP WHERE id=?", (deployment_id,))
        db.commit()
        return

    token = acct["token"]
    repo = dep["repo_name"]
    owner = acct["username"]
    key = dep["vplink_key"]

    try:
        gh_api("POST", "https://api.github.com/user/repos", token, json={
            "name": repo, "private": True, "auto_init": False,
            "description": f"VPLink automation deployment {repo}",
        })
    except RuntimeError as e:
        db.execute("UPDATE deployments SET status='error', updated_at=CURRENT_TIMESTAMP WHERE id=?", (deployment_id,))
        db.commit()
        return

    tmpdir = tempfile.mkdtemp(prefix="vplink_deploy_")
    try:
        repo_url = f"https://x-access-token:{token}@github.com/{owner}/{repo}.git"
        subprocess.run(["git", "clone", repo_url, tmpdir], capture_output=True, text=True, timeout=60)

        for fname in ["automation.py", "proxy_rotator.py", "config.py",
                       "profile_generator.py", "requirements.txt"]:
            src = REPO_ROOT / fname
            if src.exists():
                subprocess.run(["cp", str(src), tmpdir], check=True)

        gh_dir = Path(tmpdir) / ".github" / "workflows"
        gh_dir.mkdir(parents=True, exist_ok=True)
        wf_src = REPO_ROOT / ".github" / "workflows" / "continuous.yml"
        if wf_src.exists():
            subprocess.run(["cp", str(wf_src), str(gh_dir / "continuous.yml")], check=True)

        subprocess.run(["git", "add", "-A"], cwd=tmpdir, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "Initial deployment"], cwd=tmpdir,
                       capture_output=True, check=False)
        subprocess.run(["git", "push", "-u", "origin", "main"], cwd=tmpdir,
                       capture_output=True, check=True)

        secrets_map = {
            "SUPABASE_URL": os.environ.get("SUPABASE_URL", ""),
            "SUPABASE_KEY": os.environ.get("SUPABASE_KEY", ""),
            "SUPABASE_SECRET": os.environ.get("SUPABASE_SECRET", ""),
            "GH_PAT": token,
        }
        for sname, sval in secrets_map.items():
            if sval:
                set_repo_secret(owner, repo, sname, sval, token)

        # Trigger workflow
        gh_api("POST", f"https://api.github.com/repos/{owner}/{repo}/actions/workflows/continuous.yml/dispatches",
               token, json={"ref": "main", "inputs": {"key": key}})

        db.execute(
            "UPDATE deployments SET status='active', repo_url=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (f"https://github.com/{owner}/{repo}", deployment_id))
        db.commit()
    except Exception as e:
        db.execute("UPDATE deployments SET status='error', updated_at=CURRENT_TIMESTAMP WHERE id=?", (deployment_id,))
        db.commit()
    finally:
        subprocess.run(["rm", "-rf", tmpdir], capture_output=True)


def set_repo_secret(owner, repo, name, value, token):
    from base64 import b64encode
    import nacl.bindings
    import nacl.encoding

    pub_key_data = gh_api(
        "GET", f"https://api.github.com/repos/{owner}/{repo}/actions/secrets/public-key", token)
    pub_key = pub_key_data["key"]
    key_id = pub_key_data["key_id"]

    pub_key_bytes = nacl.encoding.Base64Encoder.decode(pub_key.encode())
    encrypted = nacl.bindings.crypto_box_seal(value.encode(), pub_key_bytes)
    encrypted_value = b64encode(encrypted).decode()

    gh_api("PUT", f"https://api.github.com/repos/{owner}/{repo}/actions/secrets/{name}",
           token, json={"encrypted_value": encrypted_value, "key_id": key_id})


def fetch_deployment_status(dep, token):
    try:
        runs = gh_api("GET",
                      f"https://api.github.com/repos/{dep['owner']}/{dep['repo_name']}/actions/runs?per_page=5",
                      token)
        workflow_runs = runs.get("workflow_runs", [])
        run_data = []
        total_views = 0
        total_dests = 0
        for run in workflow_runs:
            r = {
                "id": run["id"],
                "status": run["status"],
                "conclusion": run["conclusion"],
                "created_at": run["created_at"],
                "updated_at": run["updated_at"],
                "html_url": run["html_url"],
                "destinations": [],
            }
            if run["status"] == "completed":
                try:
                    logs_url = f"https://api.github.com/repos/{dep['owner']}/{dep['repo_name']}/actions/runs/{run['id']}/logs"
                    log_resp = requests.get(logs_url, headers=gh_headers(token))
                    if log_resp.ok:
                        text = log_resp.text
                        dests = []
                        for line in text.split("\n"):
                            if "DESTINATION URL:" in line or "DESTINATION_URL:" in line:
                                parts = line.split()
                                for p in parts:
                                    if p.startswith("http") and len(p) > 10:
                                        if p not in dests:
                                            dests.append(p)
                                        break
                        r["destinations"] = dests
                        total_dests += len(dests)
                        total_views += len(dests)
                except Exception:
                    pass
            run_data.append(r)

        db = get_db()
        db.execute("UPDATE deployments SET total_views=?, total_destinations=?, "
                   "last_run_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                   (total_views, total_dests, dep["id"]))
        db.commit()

        return {"runs": run_data, "total_views": total_views, "total_destinations": total_dests}
    except Exception:
        return {"runs": [], "total_views": 0, "total_destinations": 0}


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if user and verify_password(password, user["password_hash"]):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            return redirect(url_for("dashboard"))
        return render_template("manager/login.html", error="Invalid credentials")
    return render_template("manager/login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def dashboard():
    db = get_db()
    deps = db.execute(
        "SELECT d.*, ga.name as account_name FROM deployments d "
        "JOIN github_accounts ga ON ga.id = d.github_account_id "
        "WHERE d.user_id=? ORDER BY d.updated_at DESC",
        (session["user_id"],)).fetchall()
    return render_template("manager/dashboard.html", deployments=deps)


@app.route("/status")
@login_required
def status_json():
    db = get_db()
    deps = db.execute(
        "SELECT d.*, ga.name as account_name, ga.token, ga.username as owner "
        "FROM deployments d JOIN github_accounts ga ON ga.id = d.github_account_id "
        "WHERE d.user_id=?",
        (session["user_id"],)).fetchall()
    results = []
    for dep in deps:
        status = fetch_deployment_status(dep, dep["token"])
        results.append({
            "id": dep["id"],
            "repo_name": dep["repo_name"],
            "vplink_key": dep["vplink_key"],
            "status": dep["status"],
            "total_views": status["total_views"],
            "total_destinations": status["total_destinations"],
            "runs": status["runs"],
        })
    return jsonify(results)


@app.route("/deploy/new", methods=["GET", "POST"])
@login_required
def deploy_new():
    db = get_db()
    if request.method == "POST":
        account_id = request.form.get("github_account_id")
        proxy_id = request.form.get("proxy_credential_id") or None
        vplink_key = request.form.get("vplink_key", "").strip()
        urls_raw = request.form.get("urls", "").strip()

        if not account_id or not vplink_key:
            return render_template("manager/deploy_new.html",
                                   error="GitHub account and VPLINK key are required")

        acct = db.execute("SELECT * FROM github_accounts WHERE id=? AND user_id=?",
                          (account_id, session["user_id"])).fetchone()
        if not acct:
            return render_template("manager/deploy_new.html", error="Invalid account")

        repo = random_repo_name()
        dep_id = db.execute(
            "INSERT INTO deployments (user_id, github_account_id, proxy_credential_id, "
            "repo_name, owner, vplink_key, status) VALUES (?,?,?,?,?,?,'deploying')",
            (session["user_id"], account_id, proxy_id, repo, acct["username"], vplink_key)
        ).lastrowid

        if urls_raw:
            for u in urls_raw.split("\n"):
                u = u.strip()
                if u:
                    db.execute("INSERT INTO deployment_urls (deployment_id, url) VALUES (?,?)",
                               (dep_id, u))
        db.commit()

        import threading
        threading.Thread(target=create_repo_and_deploy, args=(dep_id,), daemon=True).start()

        return redirect(url_for("deploy_detail", dep_id=dep_id))

    accounts = db.execute("SELECT * FROM github_accounts WHERE user_id=?",
                          (session["user_id"],)).fetchall()
    proxies = db.execute("SELECT * FROM proxy_credentials WHERE user_id=?",
                         (session["user_id"],)).fetchall()
    return render_template("manager/deploy_new.html", accounts=accounts, proxies=proxies)


@app.route("/deploy/<int:dep_id>")
@login_required
def deploy_detail(dep_id):
    db = get_db()
    dep = db.execute(
        "SELECT d.*, ga.name as account_name, ga.token, ga.username as owner "
        "FROM deployments d JOIN github_accounts ga ON ga.id = d.github_account_id "
        "WHERE d.id=? AND d.user_id=?",
        (dep_id, session["user_id"])).fetchone()
    if not dep:
        abort(404)
    status = fetch_deployment_status(dep, dep["token"])
    urls = db.execute("SELECT * FROM deployment_urls WHERE deployment_id=?", (dep_id,)).fetchall()
    return render_template("manager/deploy_detail.html", dep=dep, status=status, urls=urls)


@app.route("/deploy/<int:dep_id>/stop", methods=["POST"])
@login_required
def deploy_stop(dep_id):
    db = get_db()
    dep = db.execute(
        "SELECT d.*, ga.token, ga.username as owner "
        "FROM deployments d JOIN github_accounts ga ON ga.id = d.github_account_id "
        "WHERE d.id=? AND d.user_id=?", (dep_id, session["user_id"])).fetchone()
    if not dep:
        abort(404)
    try:
        gh_api("PUT",
               f"https://api.github.com/repos/{dep['owner']}/{dep['repo_name']}/actions/workflows/continuous.yml/disable",
               dep["token"])
    except Exception:
        pass
    db.execute("UPDATE deployments SET status='stopped', updated_at=CURRENT_TIMESTAMP WHERE id=?",
               (dep_id,))
    db.commit()
    return redirect(url_for("deploy_detail", dep_id=dep_id))


@app.route("/deploy/<int:dep_id>/restart", methods=["POST"])
@login_required
def deploy_restart(dep_id):
    db = get_db()
    dep = db.execute(
        "SELECT d.*, ga.token, ga.username as owner "
        "FROM deployments d JOIN github_accounts ga ON ga.id = d.github_account_id "
        "WHERE d.id=? AND d.user_id=?", (dep_id, session["user_id"])).fetchone()
    if not dep:
        abort(404)
    try:
        gh_api("PUT",
               f"https://api.github.com/repos/{dep['owner']}/{dep['repo_name']}/actions/workflows/continuous.yml/enable",
               dep["token"])
        gh_api("POST",
               f"https://api.github.com/repos/{dep['owner']}/{dep['repo_name']}/actions/workflows/continuous.yml/dispatches",
               dep["token"], json={"ref": "main", "inputs": {"key": dep["vplink_key"]}})
    except Exception:
        pass
    db.execute("UPDATE deployments SET status='active', updated_at=CURRENT_TIMESTAMP WHERE id=?",
               (dep_id,))
    db.commit()
    return redirect(url_for("deploy_detail", dep_id=dep_id))


@app.route("/deploy/<int:dep_id>/delete", methods=["POST"])
@login_required
def deploy_delete(dep_id):
    db = get_db()
    dep = db.execute(
        "SELECT d.*, ga.token, ga.username as owner "
        "FROM deployments d JOIN github_accounts ga ON ga.id = d.github_account_id "
        "WHERE d.id=? AND d.user_id=?", (dep_id, session["user_id"])).fetchone()
    if not dep:
        abort(404)
    try:
        gh_api("DELETE",
               f"https://api.github.com/repos/{dep['owner']}/{dep['repo_name']}",
               dep["token"])
    except Exception:
        pass
    db.execute("DELETE FROM deployments WHERE id=?", (dep_id,))
    db.commit()
    return redirect(url_for("dashboard"))


@app.route("/accounts")
@login_required
def accounts():
    db = get_db()
    accts = db.execute("SELECT * FROM github_accounts WHERE user_id=?",
                       (session["user_id"],)).fetchall()
    return render_template("manager/accounts.html", accounts=accts)


@app.route("/accounts/new", methods=["POST"])
@login_required
def accounts_new():
    name = request.form.get("name", "").strip()
    token = request.form.get("token", "").strip()
    if not name or not token:
        return redirect(url_for("accounts"))
    try:
        user_data = gh_api("GET", "https://api.github.com/user", token)
        username = user_data["login"]
        email = user_data.get("email", "")
    except Exception:
        return redirect(url_for("accounts", error="Invalid token"))
    db = get_db()
    db.execute("INSERT INTO github_accounts (user_id, name, token, username, email) VALUES (?,?,?,?,?)",
               (session["user_id"], name, token, username, email))
    db.commit()
    return redirect(url_for("accounts"))


@app.route("/accounts/<int:aid>/delete", methods=["POST"])
@login_required
def accounts_delete(aid):
    db = get_db()
    db.execute("DELETE FROM github_accounts WHERE id=? AND user_id=?", (aid, session["user_id"]))
    db.commit()
    return redirect(url_for("accounts"))


@app.route("/proxies")
@login_required
def proxies():
    db = get_db()
    proxies = db.execute("SELECT * FROM proxy_credentials WHERE user_id=?",
                         (session["user_id"],)).fetchall()
    return render_template("manager/proxies.html", proxies=proxies)


@app.route("/proxies/new", methods=["POST"])
@login_required
def proxies_new():
    name = request.form.get("name", "").strip()
    proxy_list = request.form.get("proxies", "").strip()
    if not name or not proxy_list:
        return redirect(url_for("proxies"))
    # Validate proxy format
    lines = [l.strip() for l in proxy_list.split("\n") if l.strip()]
    db = get_db()
    db.execute("INSERT INTO proxy_credentials (user_id, name, proxies) VALUES (?,?,?)",
               (session["user_id"], name, json.dumps(lines)))
    db.commit()
    return redirect(url_for("proxies"))


@app.route("/proxies/<int:pid>/delete", methods=["POST"])
@login_required
def proxies_delete(pid):
    db = get_db()
    db.execute("DELETE FROM proxy_credentials WHERE id=? AND user_id=?",
               (pid, session["user_id"]))
    db.commit()
    return redirect(url_for("proxies"))


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    db = get_db()
    if request.method == "POST":
        current = request.form.get("current_password", "")
        new_pass = request.form.get("new_password", "")
        user = db.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
        if not verify_password(current, user["password_hash"]):
            return render_template("manager/settings.html", error="Current password incorrect")
        if new_pass:
            db.execute("UPDATE users SET password_hash=? WHERE id=?",
                       (hash_password(new_pass), session["user_id"]))
            db.commit()
            return render_template("manager/settings.html", message="Password updated")
    return render_template("manager/settings.html")


@app.route("/api/refresh/<int:dep_id>")
@login_required
def api_refresh(dep_id):
    db = get_db()
    dep = db.execute(
        "SELECT d.*, ga.token, ga.username as owner "
        "FROM deployments d JOIN github_accounts ga ON ga.id = d.github_account_id "
        "WHERE d.id=? AND d.user_id=?", (dep_id, session["user_id"])).fetchone()
    if not dep:
        return jsonify({"error": "not found"}), 404
    status = fetch_deployment_status(dep, dep["token"])
    return jsonify(status)


def main():
    init_db()
    port = int(os.environ.get("MANAGER_PORT", 8888))
    host = os.environ.get("MANAGER_HOST", "0.0.0.0")
    print(f"VPLink Manager starting on http://{host}:{port}")
    print(f"Default login: admin / admin")
    app.run(host=host, port=port, debug=True)


if __name__ == "__main__":
    main()
