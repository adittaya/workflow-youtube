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

## Deployed state (already done for zzxatvwjblfbaqzdxouw)

- Function `post-pending-comments` deployed with **verify_jwt disabled**
  (the `sb_secret_...` key is not a JWT, so JWT verification would reject
  every call). Access is gated by the shared secret env var
  `FUNCTION_POST_SECRET` — callers must send it in the `X-Post-Secret`
  header, else the function answers 403.
- Env vars: `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` are auto-injected
  by the runtime; `FUNCTION_POST_SECRET` was set via `supabase secrets set`.
- The 1-minute schedule is a **pg_cron job** (enabled via
  `create extension if not exists pg_cron;` + `pg_net;` — the project lives
  in ap-southeast-1, so use `aws-0-ap-southeast-1.pooler.supabase.com`):

```sql
create extension if not exists pg_cron;
create extension if not exists pg_net;

select cron.unschedule('post-pending-comments');
select cron.schedule(
  'post-pending-comments',
  '* * * * *',
  format('select net.http_post(url := ''https://zzxatvwjblfbaqzdxouw.supabase.co/functions/v1/post-pending-comments'', headers := ''{"Authorization":"Bearer %s","X-Post-Secret":"%s","Content-Type":"application/json"}''::jsonb, body := ''{}''::jsonb)', 'SB_SECRET_KEY', 'FUNCTION_POST_SECRET')
);
```

(Why not pg_net directly against YouTube? pg_net only sends JSON bodies —
Google's OAuth token refresh requires form-urlencoded, so the token step
must run in the Edge Function.)

## Redeploy (after changing index.ts)

```bash
export SUPABASE_ACCESS_TOKEN=sbp_...            # Dashboard → Account → Access Tokens
npx supabase@latest functions deploy post-pending-comments \
  --project-ref zzxatvwjblfbaqzdxouw --no-verify-jwt
```

The `FUNCTION_POST_SECRET` secret survives redeploys (set once via
`supabase secrets set --project-ref ... --env-file <file>`).

## Test

```bash
# with secret — must return {"posted":0,...} when nothing is due
curl -X POST https://zzxatvwjblfbaqzdxouw.supabase.co/functions/v1/post-pending-comments \
  -H "X-Post-Secret: $FUNCTION_POST_SECRET" -H "Content-Type: application/json" -d '{}'
# without secret — must return 403
```

Verify the cron fires: `select status, return_message from cron.job_run_details
where jobid = <id> order by runid desc limit 3;` and the function's answer in
`net._http_response` (HTTP 200 + `{"posted":0,...}`).

## Failure semantics

- If the database is paused or Supabase is down, the tick silently skips —
  the queue is untouched and the next tick (or the app's own drain on any
  TUI/CLI run, or the GitHub Actions 30-min cron) posts it.
- No retry inside a tick beyond the attempts cap — the queue itself is the
  durable state.