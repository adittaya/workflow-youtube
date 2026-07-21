# vplink247

24/7 VPLink automation — deploy, manage, and monitor endless relay chains on GitHub Actions.

## One-line installer

```bash
curl -fsSL https://raw.githubusercontent.com/adittaya/workflow-vplink/main/install-vplink247.sh | bash
```

Installs the `vplink247` global command, then runs setup wizard.

## Commands

```
vplink247 setup              Interactive wizard
vplink247 account add        Add GitHub account
vplink247 account list       List accounts
vplink247 account switch     Switch active account
vplink247 deploy             Deploy automation to a new repo
vplink247 deploy list        List deployments
vplink247 test <name>        Test a deployment
vplink247 status             Overall status
```

## How it works

Each deployed repo runs a GitHub Actions workflow that:
1. Gets a premium proxy from the Supabase pool
2. Runs the vplink.in funnel (TP → CE → destination)
3. On success, triggers the next run via repository_dispatch (endless relay chain)
4. On failure, invalidates the proxy and still continues the chain

Cron fallback every 15 minutes.
