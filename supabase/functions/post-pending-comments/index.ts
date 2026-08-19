// post-pending-comments — Supabase Edge Function
//
// Drains the pending-comments queue (settings.pending_comments, same JSON
// list the app uses) and posts each comment whose video has published
// (publish_at <= now) via the YouTube Data API. Runs on any schedule —
// every minute via Supabase Cron (Dashboard → Integrations → Cron →
// Edge Function) or pg_cron + pg_net. Mirrors daily_uploader.py's
// drain_pending_comments: success removes the entry, 403 commentsDisabled
// drops immediately, other 403s retry up to 5 attempts then drop.
//
// Credentials come from the database itself (projects' embedded OAuth
// client + refresh token, falling back to the linked account row), so no
// secrets are needed beyond the auto-injected service role key.

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

function enc(v: unknown): string {
  return encodeURIComponent(String(v ?? ""));
}

async function rest(method: string, path: string, body?: unknown) {
  const res = await fetch(`${SUPABASE_URL}/rest/v1/${path}`, {
    method,
    headers: {
      apikey: SERVICE_KEY,
      Authorization: `Bearer ${SERVICE_KEY}`,
      "Content-Type": "application/json",
      Prefer: "return=representation,resolution=merge-duplicates",
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`rest ${method} ${path}: ${res.status} ${await res.text()}`);
  const text = await res.text();
  return text ? JSON.parse(text) : null;
}

async function getSetting(key: string): Promise<unknown> {
  try {
    const rows = await rest(
      "GET",
      `settings?key=eq.${encodeURIComponent(key)}&select=value&limit=1`,
    );
    return rows?.[0]?.value ?? null;
  } catch {
    return null;
  }
}

async function setSetting(key: string, value: unknown) {
  await rest(
    "POST",
    `settings?on_conflict=key`,
    { key, value, updated_at: new Date().toISOString() },
  );
}

async function refreshAccessToken(
  clientId: string,
  clientSecret: string,
  refreshToken: string,
): Promise<string> {
  const body = new URLSearchParams({
    client_id: clientId,
    client_secret: clientSecret,
    refresh_token: refreshToken,
    grant_type: "refresh_token",
  });
  const res = await fetch("https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  const data = await res.json();
  if (!res.ok || !data.access_token) {
    throw new Error(`token refresh failed: ${res.status} ${JSON.stringify(data).slice(0, 200)}`);
  }
  return data.access_token;
}

async function postComment(
  accessToken: string,
  videoId: string,
  text: string,
): Promise<void> {
  const res = await fetch(
    "https://www.googleapis.com/youtube/v3/commentThreads?part=snippet",
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        snippet: {
          videoId,
          topLevelComment: { snippet: { textOriginal: text } },
        },
      }),
    },
  );
  if (!res.ok) {
    let reason = "";
    try {
      reason = (await res.json())?.error?.errors?.[0]?.reason ?? "";
    } catch {
      /* keep empty */
    }
    throw new CommentError(res.status, reason);
  }
  const data = await res.json();
  // Hold for review when the channel's moderation setting says so
  // (matches the app's immediate-post path). Best effort — never fatal.
  try {
    await fetch(`https://www.googleapis.com/youtube/v3/comments?part=snippet`, {
      method: "PUT",
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        id: data.id,
        snippet: { textOriginal: text, moderationStatus: "heldForReview" },
      }),
    });
  } catch {
    /* ignore */
  }
}

class CommentError extends Error {
  status: number;
  reason: string;
  constructor(status: number, reason: string) {
    super(`comment failed: ${status} ${reason}`);
    this.status = status;
    this.reason = reason;
  }
}

Deno.serve(async (req) => {
  // Deployed with verify_jwt=false (the service key is not a JWT), so gate
  // on a shared secret instead: X-Post-Secret must match FUNCTION_POST_SECRET.
  const expected = Deno.env.get("FUNCTION_POST_SECRET");
  if (expected && req.headers.get("X-Post-Secret") !== expected) {
    return Response.json({ error: "forbidden" }, { status: 403 });
  }
  const posted: string[] = [];
  const dropped: string[] = [];
  const retried: string[] = [];
  const now = Date.now();

  const queue: any[] = Array.isArray((await getSetting("pending_comments")) || [])
    ? (await getSetting("pending_comments") as any[])
    : [];
  if (!Array.isArray(queue) || queue.length === 0) {
    return Response.json({ posted: 0, dropped: 0, retried: 0, waiting: 0 });
  }

  const remaining: any[] = [];

  for (const entry of queue) {
    const due = entry.publish_at
      ? Date.parse(String(entry.publish_at).replace("Z", "+00:00"))
      : NaN;
    if (!Number.isNaN(due) && due > now) {
      remaining.push(entry);
      continue;
    }

    // Resolve credentials: project's embedded OAuth client first, then the
    // linked account row. Deleted project/account → drop the entry.
    let clientId = "";
    let clientSecret = "";
    let refreshToken = "";
    const pid = String(entry.project_id ?? "");
    try {
      if (pid) {
        const proj = await rest("GET", `projects?id=eq.${enc(pid)}&select=*&limit=1`);
        const p = proj?.[0];
        if (p) {
          clientId = p.yt_client_id ?? "";
          clientSecret = p.yt_client_secret ?? "";
          refreshToken = p.yt_refresh_token ?? "";
        }
        if (!refreshToken && p?.account_id) {
          const acct = await rest(
            "GET",
            `accounts?name=eq.${enc(p.account_id)}&select=*&limit=1`,
          );
          const a = acct?.[0];
          if (a) {
            clientId = a.client_id ?? clientId;
            clientSecret = a.client_secret ?? clientSecret;
            refreshToken = a.refresh_token ?? "";
          }
        }
      }
    } catch {
      refreshToken = "";
    }

    if (!clientId || !refreshToken) {
      dropped.push(entry.video_id);
      continue;
    }

    try {
      const token = await refreshAccessToken(clientId, clientSecret, refreshToken);
      await postComment(token, entry.video_id, entry.comment);
      posted.push(entry.video_id);
    } catch (e) {
      if (e instanceof CommentError) {
        if (e.reason === "commentsDisabled") {
          dropped.push(entry.video_id);
          continue;
        }
        if (e.reason === "forbidden" || e.reason === "insufficientPermissions") {
          const attempts = Number(entry.attempts ?? 0) + 1;
          if (attempts >= 5) {
            dropped.push(entry.video_id);
            continue;
          }
          entry.attempts = attempts;
          retried.push(entry.video_id);
          remaining.push(entry);
          continue;
        }
      }
      // Transient (network, 5xx, token refresh) — retry next tick.
      entry.attempts = Number(entry.attempts ?? 0) + 1;
      retried.push(entry.video_id);
      remaining.push(entry);
    }
  }

  await setSetting("pending_comments", remaining);

  return Response.json({
    posted: posted.length,
    dropped: dropped.length,
    retried: retried.length,
    waiting: remaining.length,
    posted_ids: posted,
    dropped_ids: dropped,
  });
});