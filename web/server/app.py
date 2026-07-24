import http.server
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
import ssl
import zipfile
import io
import time
import shutil
from pathlib import Path

PORT = int(os.environ.get("VPLINK_WEB_PORT", "5180"))
DATA_DIR = os.environ.get("VPLINK_HOME", os.path.expanduser("~/.vplink247"))
DIST_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "client", "dist")
GITHUB_API = "https://api.github.com"

MIME_TYPES = {
    ".html": "text/html",
    ".js": "application/javascript",
    ".css": "text/css",
    ".json": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
}

def data_path(name):
    return os.path.join(DATA_DIR, name)

def load_json(name):
    p = data_path(name)
    if not os.path.exists(p):
        return {}
    with open(p) as f:
        return json.load(f)

def save_json(name, data):
    os.makedirs(DATA_DIR, exist_ok=True)
    p = data_path(name)
    with open(p, "w") as f:
        json.dump(data, f, indent=2)

def gh_request(endpoint, token, method="GET", body=None):
    url = endpoint if endpoint.startswith("http") else f"{GITHUB_API}{endpoint}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("User-Agent", "vplink-web/3.0")
    if body:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            if not raw:
                return {"ok": True, "status": resp.status}
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        body_text = e.read().decode(errors="replace")
        return {"error": True, "status": e.code, "message": body_text}

def paginate_repos(token):
    all_repos = []
    page = 1
    while page <= 5:
        try:
            repos = gh_request(f"/user/repos?per_page=100&page={page}&type=all", token)
            if isinstance(repos, dict) and repos.get("error"):
                break
            if not repos:
                break
            all_repos.extend(repos)
            if len(repos) < 100:
                break
        except:
            break
        page += 1
    return all_repos


class APIHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length))

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = dict(urllib.parse.parse_qsl(parsed.query))

        if path == "/api/health":
            return self.send_json({"ok": True, "version": "3.0"})

        if path == "/api/accounts":
            return self.send_json(load_json("accounts.json"))

        if path == "/api/settings":
            return self.send_json(load_json("settings.json"))

        if path == "/api/deployments":
            return self.send_json(load_json("deployments.json"))

        if path == "/api/github/validate":
            token = qs.get("token", "")
            if not token:
                return self.send_json({"error": "token required"}, 400)
            data = gh_request("/user", token)
            if isinstance(data, dict) and data.get("login"):
                scopes_hdr = ""
                req = urllib.request.Request(f"{GITHUB_API}/user")
                req.add_header("Authorization", f"token {token}")
                req.add_header("Accept", "application/vnd.github.v3+json")
                req.add_header("User-Agent", "vplink-web/3.0")
                try:
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        scopes_hdr = resp.headers.get("X-OAuth-Scopes", "")
                except:
                    pass
                return self.send_json({
                    "username": data["login"],
                    "scopes": [s.strip() for s in scopes_hdr.split(",") if s.strip()],
                })
            return self.send_json({"error": "Invalid token"}, 401)

        if path == "/api/github/repos":
            token = qs.get("token", "")
            if not token:
                return self.send_json({"error": "token required"}, 400)
            repos = paginate_repos(token)
            return self.send_json([{
                "name": r["name"],
                "full_name": r["full_name"],
                "html_url": r["html_url"],
                "private": r["private"],
                "owner": r["owner"]["login"],
                "created_at": r["created_at"],
            } for r in repos if r["name"].startswith("vplink-")])

        if path == "/api/github/discover":
            token = qs.get("token", "")
            if not token:
                return self.send_json({"error": "token required"}, 400)
            repos = paginate_repos(token)
            vplink = [r for r in repos if r["name"].startswith("vplink-")]
            owner = vplink[0]["owner"]["login"] if vplink else "unknown"
            deployments = []
            for repo in vplink:
                dep = {
                    "repo_name": repo["name"],
                    "owner": owner,
                    "key": "?",
                    "status": "unknown",
                    "repo_url": repo["html_url"],
                    "last_run": None,
                    "total_runs": 0,
                    "is_public": not repo["private"],
                }
                try:
                    runs = gh_request(f"/repos/{owner}/{repo['name']}/actions/runs?per_page=5", token)
                    if isinstance(runs, dict) and not runs.get("error"):
                        wr = runs.get("workflow_runs", [])
                        if wr:
                            dep["last_run"] = {
                                "id": wr[0]["id"],
                                "name": wr[0]["name"],
                                "status": wr[0]["status"],
                                "conclusion": wr[0].get("conclusion"),
                                "created_at": wr[0]["created_at"],
                                "html_url": wr[0]["html_url"],
                            }
                            dep["status"] = wr[0].get("conclusion") or wr[0]["status"]
                            dep["total_runs"] = len(wr)
                except:
                    pass
                try:
                    vdata = gh_request(f"/repos/{owner}/{repo['name']}/actions/variables?per_page=100", token)
                    if isinstance(vdata, dict) and not vdata.get("error"):
                        for v in vdata.get("variables", []):
                            if v["name"] == "VPLINK_KEY":
                                dep["key"] = v["value"]
                except:
                    pass
                deployments.append(dep)
            return self.send_json(deployments)

        if path == "/api/github/workflow":
            token = qs.get("token", "")
            owner = qs.get("owner", "")
            repo = qs.get("repo", "")
            if not all([token, owner, repo]):
                return self.send_json({"error": "missing params"}, 400)
            data = gh_request(f"/repos/{owner}/{repo}/actions/workflows", token)
            if isinstance(data, dict) and data.get("error"):
                return self.send_json({"error": data.get("message", "API error")})
            wf = None
            for w in data.get("workflows", []):
                if "continuous" in w.get("path", "") or "vplink" in w.get("name", "").lower():
                    wf = w
                    break
            if not wf and data.get("workflows"):
                wf = data["workflows"][0]
            if wf:
                return self.send_json({"id": wf["id"], "state": wf["state"], "name": wf["name"]})
            return self.send_json({"error": "no workflow found"})

        if path == "/api/github/runs":
            token = qs.get("token", "")
            owner = qs.get("owner", "")
            repo = qs.get("repo", "")
            per = qs.get("per_page", "10")
            if not all([token, owner, repo]):
                return self.send_json({"error": "missing params"}, 400)
            data = gh_request(f"/repos/{owner}/{repo}/actions/runs?per_page={per}", token)
            if isinstance(data, dict) and data.get("error"):
                return self.send_json([])
            return self.send_json(data.get("workflow_runs", []))

        if path == "/api/github/log":
            token = qs.get("token", "")
            run_id = qs.get("run_id", "")
            owner = qs.get("owner", "")
            repo = qs.get("repo", "")
            if not all([token, run_id, owner, repo]):
                return self.send_json({"error": "missing params"}, 400)
            url = f"/repos/{owner}/{repo}/actions/runs/{run_id}/logs"
            req = urllib.request.Request(f"{GITHUB_API}{url}")
            req.add_header("Authorization", f"token {token}")
            req.add_header("Accept", "application/vnd.github.v3+json")
            req.add_header("User-Agent", "vplink-web/3.0")
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = resp.read()
                    zf = zipfile.ZipFile(io.BytesIO(data))
                    logs = {}
                    for name in zf.namelist():
                        if name.endswith(".txt"):
                            logs[name] = zf.read(name).decode(errors="replace")
                    dest = ""
                    for name, content in logs.items():
                        for line in content.split("\n"):
                            if "DESTINATION URL:" in line or "Destination:" in line:
                                dest = line.split(":", 1)[-1].strip()
                    return self.send_json({"logs": list(logs.keys()), "destination": dest})
            except Exception as e:
                return self.send_json({"error": str(e)})

        if path == "/api/github/log/download":
            token = qs.get("token", "")
            run_id = qs.get("run_id", "")
            owner = qs.get("owner", "")
            repo = qs.get("repo", "")
            if not all([token, run_id, owner, repo]):
                return self.send_json({"error": "missing params"}, 400)
            url = f"/repos/{owner}/{repo}/actions/runs/{run_id}/logs"
            req = urllib.request.Request(f"{GITHUB_API}{url}")
            req.add_header("Authorization", f"token {token}")
            req.add_header("Accept", "application/vnd.github.v3+json")
            req.add_header("User-Agent", "vplink-web/3.0")
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = resp.read()
                    zf = zipfile.ZipFile(io.BytesIO(data))
                    full_log = ""
                    for name in sorted(zf.namelist()):
                        if name.endswith(".txt"):
                            full_log += f"\n{'='*60}\n{name}\n{'='*60}\n"
                            full_log += zf.read(name).decode(errors="replace")
                    return self.send_json({"log": full_log})
            except Exception as e:
                return self.send_json({"error": str(e)})

        # ── Static file serving from dist/ ──
        if not path.startswith("/api/"):
            # Default to index.html for SPA routing
            if path == "/" or path == "":
                path = "/index.html"
            file_path = os.path.join(DIST_DIR, path.lstrip("/"))
            if os.path.isfile(file_path):
                ext = os.path.splitext(file_path)[1]
                mime = MIME_TYPES.get(ext, "application/octet-stream")
                with open(file_path, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Cache-Control", "no-cache" if ext == ".html" else "public, max-age=31536000")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(content)
                return
            # SPA fallback: serve index.html for any non-file route
            index_path = os.path.join(DIST_DIR, "index.html")
            if os.path.isfile(index_path):
                with open(index_path, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return

        self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        body = self.read_body()

        if path == "/api/accounts":
            name = body.get("name", "").strip()
            token = body.get("token", "").strip()
            if not name or not token:
                return self.send_json({"error": "name and token required"}, 400)
            req = urllib.request.Request(f"{GITHUB_API}/user")
            req.add_header("Authorization", f"token {token}")
            req.add_header("Accept", "application/vnd.github.v3+json")
            req.add_header("User-Agent", "vplink-web/3.0")
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read())
                    scopes = resp.headers.get("X-OAuth-Scopes", "")
            except:
                return self.send_json({"error": "Invalid token"}, 401)
            accounts = load_json("accounts.json")
            accounts[name] = {"name": name, "token": token, "username": data.get("login", "")}
            save_json("accounts.json", accounts)
            return self.send_json({
                "ok": True,
                "username": data.get("login"),
                "scopes": [s.strip() for s in scopes.split(",") if s.strip()],
            })

        if path == "/api/accounts/active":
            name = body.get("name", "")
            accounts = load_json("accounts.json")
            if name and name not in accounts:
                return self.send_json({"error": "account not found"}, 404)
            settings = load_json("settings.json")
            settings["active_account"] = name if name else None
            save_json("settings.json", settings)
            return self.send_json({"ok": True})

        if path == "/api/accounts/remove":
            name = body.get("name", "")
            accounts = load_json("accounts.json")
            if name in accounts:
                del accounts[name]
                save_json("accounts.json", accounts)
            settings = load_json("settings.json")
            if settings.get("active_account") == name:
                settings["active_account"] = None
                save_json("settings.json", settings)
            return self.send_json({"ok": True})

        if path == "/api/settings":
            save_json("settings.json", body)
            return self.send_json({"ok": True})

        if path == "/api/deploy":
            repo_name = body.get("name", "").strip()
            key = body.get("key", "").strip()
            if not key:
                return self.send_json({"error": "VPLINK_KEY required"}, 400)
            settings = load_json("settings.json")
            accounts = load_json("accounts.json")
            active_name = settings.get("active_account")
            if not active_name or active_name not in accounts:
                return self.send_json({"error": "No active account"}, 400)
            acct = accounts[active_name]
            token = acct["token"]
            owner = acct.get("username", acct["name"])
            full_name = repo_name if repo_name.startswith("vplink-") else f"vplink-{repo_name}" if repo_name else f"vplink-{int(time.time()).to_bytes(4,'big').hex()}"
            try:
                create_resp = gh_request("/user/repos", token, "POST", {
                    "name": full_name,
                    "private": True,
                    "auto_init": True,
                    "description": "VPLink automation relay",
                })
                if isinstance(create_resp, dict) and create_resp.get("error"):
                    return self.send_json({"error": f"Create repo failed: {create_resp.get('message', '')}"})

                template_dir = os.path.join(DATA_DIR, "template")
                if not os.path.exists(template_dir):
                    subprocess.run([
                        "git", "clone", "--depth", "1",
                        "https://github.com/adittaya/workflow-vplink.git", template_dir
                    ], capture_output=True, timeout=120)

                repo_dir = os.path.join(DATA_DIR, "repos", full_name)
                os.makedirs(os.path.dirname(repo_dir), exist_ok=True)
                shutil.rmtree(repo_dir, ignore_errors=True)
                def ignore_git(dir, files):
                    return [".git"] if ".git" in files else []
                shutil.copytree(template_dir, repo_dir, ignore=ignore_git)

                secrets = {"VPLINK_KEY": key}
                for k in ["SUPABASE_URL", "SUPABASE_KEY", "SUPABASE_SECRET"]:
                    v = settings.get(k.lower(), "")
                    if v:
                        secrets[k] = v

                try:
                    env = os.environ.copy()
                    env["GIT_ASKPASS"] = "echo"
                    token_url = f"https://{token}@github.com/{owner}/{full_name}.git"
                    subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, capture_output=True, timeout=30)
                    subprocess.run(["git", "remote", "add", "origin", token_url], cwd=repo_dir, capture_output=True, timeout=30)
                    subprocess.run(["git", "add", "-A"], cwd=repo_dir, capture_output=True, timeout=30)
                    subprocess.run(["git", "commit", "-m", "init: vplink automation relay"], cwd=repo_dir, capture_output=True, timeout=30)
                    subprocess.run(["git", "push", "--force", "origin", "main"], cwd=repo_dir, capture_output=True, timeout=60, env=env)
                except Exception:
                    pass

                wf_data = gh_request(f"/repos/{owner}/{full_name}/actions/workflows", token)
                if isinstance(wf_data, dict) and not wf_data.get("error"):
                    for w in wf_data.get("workflows", []):
                        if "continuous" in w.get("path", ""):
                            gh_request(f"/repos/{owner}/{full_name}/actions/workflows/{w['id']}/enable", token, "PUT")
                            gh_request(f"/repos/{owner}/{full_name}/actions/workflows/{w['id']}/dispatches", token, "POST", {"ref": "main", "inputs": {"key": key}})
                            break

                dep = {
                    "name": full_name,
                    "key": key,
                    "account": active_name,
                    "repo_url": f"https://github.com/{owner}/{full_name}",
                    "status": "deployed",
                    "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
                deps = load_json("deployments.json")
                deps[full_name] = dep
                save_json("deployments.json", deps)
                return self.send_json(dep)
            except Exception as e:
                return self.send_json({"error": f"Deploy failed: {str(e)}"})

        if path == "/api/deploy/remove":
            name = body.get("name", "")
            deps = load_json("deployments.json")
            dep = deps.get(name)
            if dep:
                accounts = load_json("accounts.json")
                acct = accounts.get(dep.get("account", ""))
                if acct:
                    owner = acct.get("username", acct["name"])
                    gh_request(f"/repos/{owner}/{name}", acct["token"], "DELETE")
                del deps[name]
                save_json("deployments.json", deps)
            return self.send_json({"ok": True})

        if path == "/api/deploy/nuke":
            deps = load_json("deployments.json")
            accounts = load_json("accounts.json")
            deleted = 0
            errors = []
            for name, dep in list(deps.items()):
                acct = accounts.get(dep.get("account", ""))
                if acct:
                    owner = acct.get("username", acct["name"])
                    try:
                        gh_request(f"/repos/{owner}/{name}", acct["token"], "DELETE")
                        deleted += 1
                    except Exception as e:
                        errors.append(f"{name}: {e}")
            save_json("deployments.json", {})
            return self.send_json({"deleted": deleted, "errors": errors})

        if path == "/api/sync":
            accounts = load_json("accounts.json")
            existing = load_json("deployments.json")
            new_repos = []
            updated_repos = []
            for name, acct in accounts.items():
                try:
                    repos = paginate_repos(acct["token"])
                    vplink = [r for r in repos if r["name"].startswith("vplink-")]
                    owner = vplink[0]["owner"]["login"] if vplink else acct.get("username", name)
                    acct["username"] = owner
                    for repo in vplink:
                        rn = repo["name"]
                        try:
                            runs = gh_request(f"/repos/{owner}/{rn}/actions/runs?per_page=5", acct["token"])
                            last = runs.get("workflow_runs", [])[0] if isinstance(runs, dict) and runs.get("workflow_runs") else None
                            status = (last.get("conclusion") or last.get("status", "unknown")) if last else "no_runs"
                        except:
                            status = "unknown"
                            last = None
                        if rn in existing:
                            existing[rn]["status"] = status
                            existing[rn]["account"] = name
                            updated_repos.append(rn)
                        else:
                            existing[rn] = {
                                "name": rn,
                                "key": "?",
                                "account": name,
                                "repo_url": repo["html_url"],
                                "status": status,
                                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                            }
                            new_repos.append(rn)
                except:
                    continue
            save_json("accounts.json", accounts)
            save_json("deployments.json", existing)
            return self.send_json({"new": new_repos, "updated": updated_repos, "total": len(existing)})

        self.send_json({"error": "not found"}, 404)

    def do_PUT(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        body = self.read_body()

        if path == "/api/accounts/switch":
            name = body.get("name", "")
            accounts = load_json("accounts.json")
            if name in accounts:
                settings = load_json("settings.json")
                settings["active_account"] = name
                save_json("settings.json", settings)
                return self.send_json({"ok": True})
            return self.send_json({"error": "not found"}, 404)

        self.send_json({"error": "not found"}, 404)

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = dict(urllib.parse.parse_qsl(parsed.query))

        # Try reading body for DELETE requests too (browsers/fetch sometimes send body)
        body = {}
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length > 0:
                body = json.loads(self.rfile.read(length))
        except:
            pass

        if path == "/api/accounts":
            name = qs.get("name") or body.get("name", "")
            accounts = load_json("accounts.json")
            if name in accounts:
                del accounts[name]
                save_json("accounts.json", accounts)
            settings = load_json("settings.json")
            if settings.get("active_account") == name:
                settings["active_account"] = None
                save_json("settings.json", settings)
            return self.send_json({"ok": True})

        self.send_json({"error": "not found"}, 404)


if __name__ == "__main__":
    os.makedirs(DATA_DIR, exist_ok=True)
    for f in ["accounts.json", "deployments.json", "settings.json"]:
        p = data_path(f)
        if not os.path.exists(p):
            with open(p, "w") as fh:
                fh.write("{}")
    print(f"VPLink Web API starting on http://localhost:{PORT}")
    server = http.server.HTTPServer(("0.0.0.0", PORT), APIHandler)
    server.serve_forever()
