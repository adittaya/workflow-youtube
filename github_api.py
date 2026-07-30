import json
import io
import os
import re
import time
import subprocess
import urllib.request
import urllib.error
import zipfile

GITHUB_API = "https://api.github.com"
GH_TIMEOUT = 30
GIT_TIMEOUT = 60
API_PER_PAGE = 100
API_MAX_PAGES = 3
WORKFLOW_NAME = "youtube.yml"
REPO_PREFIX = "workflow-"


def gh(endpoint, token, method="GET", body=None):
    url = endpoint if endpoint.startswith("http") else f"{GITHUB_API}{endpoint}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("User-Agent", "yt-mirror-tui/1.0")
    if body:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=GH_TIMEOUT) as resp:
            raw = resp.read()
            scopes = resp.headers.get("X-OAuth-Scopes", "")
            if not raw:
                return {"ok": True, "status": resp.status, "_scopes": scopes}
            result = json.loads(raw)
            if isinstance(result, dict):
                result["_scopes"] = scopes
            return result
    except urllib.error.HTTPError as e:
        return {"error": True, "status": e.code, "message": e.read().decode(errors="replace")}


def gh_user(token):
    return gh("/user", token)


def get_repo(owner, repo, token):
    return gh(f"/repos/{owner}/{repo}", token)


def create_repo(token, name, description="YouTube Mirror Bot"):
    return gh("/user/repos", token, "POST", {
        "name": name,
        "private": False,
        "auto_init": True,
        "description": description,
    })


def delete_repo(owner, repo, token):
    return gh(f"/repos/{owner}/{repo}", token, "DELETE")


def paginate_repos(token, filter_prefix=None):
    all_repos = []
    for page in range(1, API_MAX_PAGES + 1):
        repos = gh(f"/user/repos?per_page={API_PER_PAGE}&page={page}&type=all", token)
        if isinstance(repos, dict) and repos.get("error"):
            if repos.get("status") == 403:
                return {"_rate_limited": True}
            break
        if not repos:
            break
        all_repos.extend(repos)
        if len(repos) < API_PER_PAGE:
            break
    if filter_prefix:
        return [r for r in all_repos if r["name"].startswith(filter_prefix)]
    return all_repos


def get_mirror_repos(token):
    return paginate_repos(token, filter_prefix=REPO_PREFIX)


def get_workflows(owner, repo, token):
    data = gh(f"/repos/{owner}/{repo}/actions/workflows", token)
    if isinstance(data, dict) and data.get("error"):
        return []
    return data.get("workflows", [])


def get_mirror_workflow(owner, repo, token):
    workflows = get_workflows(owner, repo, token)
    for w in workflows:
        path = w.get("path", "")
        if WORKFLOW_NAME in path:
            return w
    return workflows[0] if workflows else None


def enable_workflow(owner, repo, workflow_id, token):
    return gh(f"/repos/{owner}/{repo}/actions/workflows/{workflow_id}/enable", token, "PUT")


def dispatch_workflow(owner, repo, workflow_id, token, ref="main", inputs=None):
    body = {"ref": ref}
    if inputs:
        body["inputs"] = inputs
    return gh(f"/repos/{owner}/{repo}/actions/workflows/{workflow_id}/dispatches", token, "POST", body)


def get_runs(owner, repo, token, per=10, status=None):
    query = f"?per_page={per}"
    if status:
        query += f"&status={status}"
    data = gh(f"/repos/{owner}/{repo}/actions/runs{query}", token)
    if isinstance(data, dict) and data.get("error"):
        return []
    return data.get("workflow_runs", [])


def cancel_run(owner, repo, run_id, token):
    return gh(f"/repos/{owner}/{repo}/actions/runs/{run_id}/cancel", token, "POST")


def cancel_active_runs(owner, repo, token):
    cancelled = 0
    for run in get_runs(owner, repo, token, per=20, status="in_progress"):
        cancel_run(owner, repo, run["id"], token)
        cancelled += 1
    for run in get_runs(owner, repo, token, per=20, status="queued"):
        cancel_run(owner, repo, run["id"], token)
        cancelled += 1
    return cancelled


def get_run_logs(owner, repo, run_id, token):
    url = f"/repos/{owner}/{repo}/actions/runs/{run_id}/logs"
    req = urllib.request.Request(f"{GITHUB_API}{url}")
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("User-Agent", "yt-mirror-tui/1.0")
    try:
        with urllib.request.urlopen(req, timeout=GH_TIMEOUT) as resp:
            zf = zipfile.ZipFile(io.BytesIO(resp.read()))
            logs = {}
            for name in sorted(zf.namelist()):
                if name.endswith(".txt"):
                    logs[name] = zf.read(name).decode(errors="replace")
            return logs
    except Exception:
        return {}


def get_public_key(owner, repo, token):
    return gh(f"/repos/{owner}/{repo}/actions/secrets/public-key", token)


def encrypt_secret(public_key_b64, plaintext):
    if not isinstance(plaintext, str):
        plaintext = str(plaintext)
    raw = __import__("base64").b64decode(public_key_b64)
    try:
        import nacl.public
        recipient = nacl.public.PublicKey(raw)
        sealed = nacl.public.SealedBox(recipient)
        encrypted = sealed.encrypt(plaintext.encode("utf-8"))
        return __import__("base64").b64encode(encrypted).decode("utf-8")
    except ImportError:
        pass
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
        pub = serialization.load_der_public_key(raw)
        encrypted = pub.encrypt(
            plaintext.encode("utf-8"),
            asym_padding.OAEP(
                mgf=asym_padding.MGF1(algorithm=hashes.SHA1()),
                algorithm=hashes.SHA1(),
                label=None,
            ),
        )
        return __import__("base64").b64encode(encrypted).decode("utf-8")
    except Exception:
        return None


def set_secret(owner, repo, token, secret_name, secret_value):
    key_data = get_public_key(owner, repo, token)
    if isinstance(key_data, dict) and key_data.get("error"):
        return False, f"Failed to get public key: {key_data.get('message', '')}"
    pub_key = key_data.get("key", "")
    key_id = key_data.get("key_id", "")
    if not pub_key or not key_id:
        return False, "No public key returned"
    encrypted = encrypt_secret(pub_key, secret_value)
    if not encrypted:
        return False, "Encryption failed (install cryptography or pynacl)"
    result = gh(f"/repos/{owner}/{repo}/actions/secrets/{secret_name}", token, "PUT", {
        "encrypted_value": encrypted,
        "key_id": key_id,
    })
    if isinstance(result, dict) and result.get("error"):
        return False, f"Failed to set secret: {result.get('message', '')}"
    return True, None


def set_all_secrets(owner, repo, token, secrets_dict):
    errors = []
    for name, value in secrets_dict.items():
        if not value:
            continue
        ok, err = set_secret(owner, repo, token, name, value)
        if not ok:
            errors.append(f"{name}: {err}")
    return errors


def git_push(local_dir, remote_url, branch="main"):
    env = os.environ.copy()
    env["GIT_ASKPASS"] = "echo"
    env["GIT_AUTHOR_EMAIL"] = "yt-mirror@deploy"
    env["GIT_AUTHOR_NAME"] = "YT Mirror Deploy"
    env["GIT_COMMITTER_EMAIL"] = "yt-mirror@deploy"
    env["GIT_COMMITTER_NAME"] = "YT Mirror Deploy"

    ts = time.strftime("%Y%m%d%H%M%S")
    commands = [
        ["git", "config", "user.email", "yt-mirror@deploy"],
        ["git", "config", "user.name", "YT Mirror Deploy"],
        ["git", "remote", "remove", "origin"],
        ["git", "remote", "add", "origin", remote_url],
        ["git", "add", "-A"],
        ["git", "commit", "--allow-empty", "-m", f"deploy: youtube mirror bot@{ts}"],
        ["git", "push", "--force", "origin", branch],
    ]
    for cmd in commands:
        r = subprocess.run(cmd, cwd=local_dir, capture_output=True, timeout=GIT_TIMEOUT, env=env)
        if r.returncode != 0:
            err = (r.stderr or r.stdout).decode(errors="replace").strip()
            err = err.replace(remote_url.split("//")[-1], "***")
            if cmd[1] == "commit" and "nothing to commit" in err:
                continue
            return False, f"Git {cmd[1]} failed: {err}"
    return True, None
