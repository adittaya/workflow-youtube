import { GITHUB_API } from "../utils/storage";

export interface GitHubAccount {
  name: string;
  token: string;
  username?: string;
  repo_count?: number;
}

export interface WorkflowRun {
  id: number;
  name: string;
  status: string;
  conclusion: string | null;
  created_at: string;
  updated_at: string;
  run_number: number;
  html_url: string;
}

export interface DeploymentInfo {
  repo_name: string;
  owner: string;
  key: string;
  status: string;
  repo_url: string;
  last_run: WorkflowRun | null;
  total_runs: number;
  is_public: boolean;
}

export async function ghFetch(
  endpoint: string,
  token: string,
  options?: RequestInit
): Promise<any> {
  const url = endpoint.startsWith("http")
    ? endpoint
    : `${GITHUB_API}${endpoint}`;
  const resp = await fetch(url, {
    ...options,
    headers: {
      Authorization: `token ${token}`,
      Accept: "application/vnd.github.v3+json",
      "User-Agent": "vplink-tui/1.0",
      ...options?.headers,
    },
  });
  if (!resp.ok) {
    throw new Error(`GitHub API ${resp.status}: ${resp.statusText}`);
  }
  return resp.json();
}

export async function validateToken(
  token: string
): Promise<{ username: string; scopes: string[] }> {
  const resp = await fetch(`${GITHUB_API}/user`, {
    headers: {
      Authorization: `token ${token}`,
      Accept: "application/vnd.github.v3+json",
      "User-Agent": "vplink-tui/1.0",
    },
  });
  if (!resp.ok) throw new Error("Invalid token");
  const scopes = (
    resp.headers.get("x-oauth-scopes") || ""
  ).split(",").map((s) => s.trim());
  const data = await resp.json();
  return { username: data.login, scopes };
}

export async function getAccountInfo(
  token: string
): Promise<{ username: string; repo_count: number; repos: any[] }> {
  let allRepos: any[] = [];
  let page = 1;
  while (true) {
    const repos = await ghFetch(
      `/user/repos?per_page=100&page=${page}&type=all`,
      token
    );
    if (!repos || repos.length === 0) break;
    allRepos = allRepos.concat(repos);
    if (repos.length < 100) break;
    page++;
  }
  const username = allRepos[0]?.owner?.login || "unknown";
  return { username, repo_count: allRepos.length, repos: allRepos };
}

export async function discoverDeployments(
  token: string
): Promise<DeploymentInfo[]> {
  const { username, repos } = await getAccountInfo(token);
  const vplinkRepos = repos.filter((r: any) => r.name.startsWith("vplink-"));

  const deployments: DeploymentInfo[] = [];
  for (const repo of vplinkRepos) {
    try {
      const runs = await ghFetch(
        `/repos/${username}/${repo.name}/actions/runs?per_page=5`,
        token
      );
      const workflowRuns: WorkflowRun[] = runs.workflow_runs || [];
      const lastRun = workflowRuns.length > 0 ? workflowRuns[0] : null;
      const status = lastRun
        ? lastRun.conclusion || lastRun.status
        : "no_runs";

      let key = "UbpV2D";
      try {
        const secrets = await ghFetch(
          `/repos/${username}/${repo.name}/actions/variables?per_page=100`,
          token
        );
        const keyVar = (secrets.variables || []).find(
          (v: any) => v.name === "VPLINK_KEY"
        );
        if (keyVar) key = keyVar.value;
      } catch {
        /* no access to secrets */
      }

      deployments.push({
        repo_name: repo.name,
        owner: username,
        key,
        status,
        repo_url: repo.html_url,
        last_run: lastRun,
        total_runs: workflowRuns.length,
        is_public: !repo.private,
      });
    } catch {
      deployments.push({
        repo_name: repo.name,
        owner: username,
        key: "?",
        status: "error",
        repo_url: repo.html_url,
        last_run: null,
        total_runs: 0,
        is_public: !repo.private,
      });
    }
  }
  return deployments;
}

export async function getWorkflowRuns(
  owner: string,
  repo: string,
  token: string,
  perPage: number = 10
): Promise<WorkflowRun[]> {
  const data = await ghFetch(
    `/repos/${owner}/${repo}/actions/runs?per_page=${perPage}`,
    token
  );
  return data.workflow_runs || [];
}

export async function createRepo(
  name: string,
  token: string,
  isPrivate: boolean = true
): Promise<any> {
  return ghFetch("/user/repos", token, {
    method: "POST",
    body: JSON.stringify({
      name,
      private: isPrivate,
      auto_init: true,
      description: "VPLink automation relay",
    }),
  });
}

export async function deleteRepo(
  owner: string,
  name: string,
  token: string
): Promise<void> {
  await ghFetch(`/repos/${owner}/${name}`, token, { method: "DELETE" });
}

export async function dispatchWorkflow(
  owner: string,
  repo: string,
  token: string,
  eventType: string,
  clientPayload?: any
): Promise<void> {
  await ghFetch(`/repos/${owner}/${repo}/dispatches`, token, {
    method: "POST",
    body: JSON.stringify({
      event_type: eventType,
      client_payload: clientPayload || {},
    }),
  });
}

export async function getWorkflowState(
  owner: string,
  repo: string,
  token: string
): Promise<{ id: number; state: string } | null> {
  try {
    const data = await ghFetch(
      `/repos/${owner}/${repo}/actions/workflows`,
      token
    );
    const workflow = (data.workflows || []).find(
      (w: any) =>
        w.path === ".github/workflows/continuous.yml" ||
        w.name === "VPLink Automation"
    );
    if (!workflow) return null;
    return { id: workflow.id, state: workflow.state };
  } catch {
    return null;
  }
}

export async function toggleWorkflow(
  owner: string,
  repo: string,
  token: string,
  workflowId: number,
  enable: boolean
): Promise<void> {
  await ghFetch(
    `/repos/${owner}/${repo}/actions/workflows/${workflowId}/${enable ? "enable" : "disable"}`,
    token,
    { method: "PUT" }
  );
}
