#!/usr/bin/env python3
"""
github_sync.py — GitHub as real-time database.

Scans GitHub repos matching vplink-* pattern, reads workflow runs,
and returns live deployment data. Both vplink247.py and manager/app.py
use this as the source of truth.

The GitHub repos ARE the database:
  - Repo exists         → deployment exists
  - Workflow runs       → deployment status + destinations
  - Repo secrets        → configuration
  - Repo description    → metadata
"""

import json
import re
import sys
import time
import requests

GITHUB_API = "https://api.github.com"


def _headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "vplink-sync/1.0",
    }


def _gh_get(token, path, params=None):
    url = f"{GITHUB_API}{path}"
    resp = requests.get(url, headers=_headers(token), params=params, timeout=15)
    if resp.status_code == 403:
        return None
    if resp.status_code >= 400:
        return None
    return resp.json() if resp.text else []


def scan_repos(token):
    """Scan all repos on the account. Returns list of repo dicts."""
    all_repos = []
    page = 1
    while True:
        data = _gh_get(token, "/user/repos", {"per_page": 100, "page": page, "type": "all"})
        if not data or not isinstance(data, list):
            break
        all_repos.extend(data)
        if len(data) < 100:
            break
        page += 1
    return all_repos


def discover_deployments(token):
    """
    Scan GitHub for all vplink-* repos and return live deployment data.
    Each deployment dict contains:
      - repo_name, owner, repo_url, is_public
      - status (from latest workflow run)
      - last_run_at, conclusion
      - vplink_key (from workflow default or description)
      - destinations (captured URLs from latest run)
      - workflow_state (active/disabled)
    """
    all_repos = scan_repos(token)
    deployments = []

    for repo in all_repos:
        name = repo.get("name", "")
        if not name.startswith("vplink-"):
            continue

        owner = repo.get("owner", {}).get("login", "")
        dep = {
            "repo_name": name,
            "owner": owner,
            "repo_url": repo.get("html_url", ""),
            "is_public": not repo.get("private", True),
            "description": repo.get("description", "") or "",
            "status": "unknown",
            "last_run_at": None,
            "conclusion": None,
            "vplink_key": "",
            "destinations": [],
            "workflow_state": "unknown",
            "runs": [],
        }

        dep["vplink_key"] = _extract_key_from_description(dep["description"])

        runs_data = _get_workflow_runs(token, owner, name)
        if runs_data:
            dep["runs"] = runs_data[:5]
            latest = runs_data[0]
            dep["status"] = latest.get("status", "unknown")
            dep["conclusion"] = latest.get("conclusion")
            dep["last_run_at"] = latest.get("created_at")

            if latest.get("status") == "completed":
                destinations = _extract_destinations_from_run(token, owner, name, latest["id"])
                dep["destinations"] = destinations
                if destinations:
                    dep["status"] = "completed"

        wf_state = _get_workflow_state(token, owner, name)
        dep["workflow_state"] = wf_state or "unknown"

        deployments.append(dep)

    return deployments


def _extract_key_from_description(desc):
    """Try to extract vplink key from repo description."""
    if not desc:
        return ""
    match = re.search(r'key[:\s]+(\w+)', desc, re.IGNORECASE)
    if match:
        return match.group(1)
    return ""


def _get_workflow_runs(token, owner, repo, per_page=5):
    """Get recent workflow runs for continuous.yml."""
    data = _gh_get(token, f"/repos/{owner}/{repo}/actions/runs",
                   {"per_page": per_page, "branch": "main"})
    if not data or not isinstance(data, dict):
        return []
    runs = []
    for run in data.get("workflow_runs", []):
        path = run.get("path", "")
        if "continuous.yml" in path or path.endswith(".yml"):
            runs.append({
                "id": run["id"],
                "status": run.get("status", ""),
                "conclusion": run.get("conclusion"),
                "created_at": run.get("created_at", ""),
                "updated_at": run.get("updated_at", ""),
                "html_url": run.get("html_url", ""),
                "event": run.get("event", ""),
            })
    return runs


def _extract_destinations_from_run(token, owner, repo, run_id):
    """Extract DESTINATION URLs from workflow run logs."""
    try:
        resp = requests.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/actions/runs/{run_id}/logs",
            headers=_headers(token),
            timeout=15
        )
        if not resp.ok:
            return []
        destinations = []
        for line in resp.text.split("\n"):
            if "DESTINATION URL:" in line or "DESTINATION_URL:" in line:
                parts = line.split()
                for p in parts:
                    if p.startswith("http") and len(p) > 10:
                        if p not in destinations:
                            destinations.append(p)
                        break
    except Exception:
        return []
    return destinations


def _get_workflow_state(token, owner, repo):
    """Get workflow enabled/disabled state."""
    data = _gh_get(token, f"/repos/{owner}/{repo}/actions/workflows")
    if not data or not isinstance(data, dict):
        return None
    for wf in data.get("workflows", []):
        if wf.get("path", "").endswith("continuous.yml"):
            return wf.get("state", "unknown")
    return None


def get_account_info(token):
    """Get account username and scopes from token."""
    resp = requests.get(f"{GITHUB_API}/user", headers=_headers(token), timeout=10)
    if not resp.ok:
        return None
    user = resp.json()
    scopes = resp.headers.get("X-OAuth-Scopes", "")
    return {
        "username": user.get("login", ""),
        "email": user.get("email", ""),
        "name": user.get("name", ""),
        "scopes": scopes,
    }


def get_deployment_detail(token, owner, repo):
    """Get full detail for a single deployment repo."""
    data = _gh_get(token, f"/repos/{owner}/{repo}")
    if not data or not isinstance(data, dict):
        return None
    if not repo.startswith("vplink-"):
        return None

    dep = {
        "repo_name": repo,
        "owner": owner,
        "repo_url": data.get("html_url", ""),
        "is_public": not data.get("private", True),
        "description": data.get("description", "") or "",
        "status": "unknown",
        "last_run_at": None,
        "conclusion": None,
        "vplink_key": _extract_key_from_description(data.get("description", "") or ""),
        "destinations": [],
        "workflow_state": "unknown",
        "runs": [],
    }

    runs_data = _get_workflow_runs(token, owner, repo)
    if runs_data:
        dep["runs"] = runs_data[:5]
        latest = runs_data[0]
        dep["status"] = latest.get("status", "unknown")
        dep["conclusion"] = latest.get("conclusion")
        dep["last_run_at"] = latest.get("created_at")
        if latest.get("status") == "completed":
            dep["destinations"] = _extract_destinations_from_run(
                token, owner, repo, latest["id"])

    dep["workflow_state"] = _get_workflow_state(token, owner, repo) or "unknown"
    return dep


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 github_sync.py <token>", file=sys.stderr)
        sys.exit(1)

    token = sys.argv[1]
    deployments = discover_deployments(token)
    print(json.dumps(deployments, indent=2))
