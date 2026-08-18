# post-pending-comments (Supabase Edge Function)

Posts the app's queued comments (settings.`pending_comments`) as soon as a
scheduled video publishes. Runs every minute entirely inside Supabase — no
machine, no app open, no GitHub. Comment lands within ~1 minute of YouTube
auto-publishing the video.

Same logic as `daily_uploader.drain_pending_comments()`:

- reads the queue from the settings table (shared with the app, both modes)
- refresh token → OAuth access token → `commentThreads.insert`
- success removes the entry; `commentsDisabled` drops immediately;
  other 403s (video still private) retry, capped at 5 attempts; transient
  errors retry next tick

## Deploy (one time, ~2 minutes)

```bash
# 1. install the CLI + log in (opens a browser, authorize with the
#    account that owns the zzxatvwjblfbaqzdxouw project)
npm install -g supabase
supabase login

# 2. from the repo root, link the project and deploy the function
supabase link --project-ref zzxatvwjblfbaqzdxouw
supabase functions deploy post-pending-comments

# 3. test it (must return {"posted":0,...} — the queue is drained but
#    nothing is due right now, so it no-ops)
curl -X POST https://zzxatvwjblfbaqzdxouw.supabase.co/functions/v1/post-pending-comments \
  -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY" \
  -H "Content-Type: application/json" -d '{}'
```

## Schedule it every minute

Dashboard → **Integrations → Cron → Create cron job**:

- Name: `post-pending-comments`
- Schedule: `* * * * *`
- Type: **Supabase Edge Function**
- Function: `post-pending-comments`
- Save.

(Or with plain SQL: `SELECT cron.schedule('post-pending-comments', '* * * * *',
$$SELECT net.http_post(url:='https://zzxatvwjblfbaqzdxouw.supabase.co/functions/v1/post-pending-comments', headers:='{"Authorization":"Bearer <SERVICE_ROLE_KEY>","Content-Type":"application/json"}'::jsonb, body:='{}'::jsonb)$$);`
— the service key is fine here because the function holds no extra secrets.)

## Failure semantics

- If the database is paused or Supabase is down, the tick silently skips —
  the queue is untouched and the next tick (or the app's own drain on any
  TUI/CLI run) posts it.
- No retry inside a tick beyond the attempts cap — the queue itself is the
  durable state.