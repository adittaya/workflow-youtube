# VPLink 3.0 — Agent Context

> **MANDATORY: Any AI agent editing this project MUST update this file** with changes made, new decisions, fixes, or known issues. This prevents hallucination across sessions. If you don't update this file, the next agent will have stale context.

## Version History
| Date | Change | Author |
|------|--------|--------|
| 2026-07-05–08 | Initial development, iterative fixes, CI, installer (see git log) | AI |
| 2026-07-16 | **Complete rewrite from live recording**: recorded full flow with network/console/DOM/screenshot capture. Analyzed 3 article templates (TP, CE, LINK1S). Rewrote automation.js with domain-agnostic template detection, human-like behavior (random delays, smooth scrolling, mouse movement), and bot-detection handling. | AI |

## Overview
Automated vplink.in URL funnel: navigate auto-redirects, handle article pages (any domain), click "Get Link" on vplink.in, and capture the final destination URL.

**Key design principle: Article domains change weekly. The automation detects page types by DOM structure (timer IDs, button IDs), NOT by domain name.**

## Files
| File | Purpose |
|------|---------|
| `automation.js` | **Main script** — Playwright automation with domain-agnostic template detection and human-like behavior |
| `config.js` | Config management — load/save `~/.vplink3.0/config.json`, CLI get/set |
| `proxy-rotator.js` | Proxy rotation — fetches from Supabase, tests, deletes dead IPs, 24h no-repeat |
| `profile-generator.js` | Profile generator — random mobile/desktop UAs, viewports, YouTube referer |
| `vplink3.0.sh` | Interactive CLI — questionnaire, PID tracking, VNC detection |
| `vplink-desktop.sh` | Virtual desktop manager — Xvfb + x11vnc lifecycle |
| `install.sh` | Production installer — 20+ environments, deps, Node.js, Playwright, credentials |
| `flow-recorder.js` | **Dev tool** — records full browser session (network, console, DOM, screenshots) for analysis |
| `package.json` | Deps: `playwright` + `playwright-core` |

## Article Page Templates (Domain-Agnostic)

**Detected by DOM structure, not by domain name.** Domains change weekly — the flow stays the same.

### Template A: TP (tp-time countdown)
- **Timer**: `#tp-time` (hidden, 15-23s countdown), `#tp-wait1` wrapper
- **Popup**: `#continueBtn` "CONTINUE ➜" appears ~6s before timer ends (bot-detection)
- **Button**: `#tp-snp2` "Continue" (appears when timer ends, `display: block`)
- **Flow**: Wait for popup → click popup (force) → wait for `#tp-snp2` → click → `learn_more.php` redirect → next article
- **Domains observed**: jobskiki.in, bcsakhi.in

### Template B: CE (ce-time countdown)
- **Timer**: `#ce-time` (visible, 20s countdown), `#ce-wait1` wrapper
- **Buttons**: `#btn6` "Verify" → `#btn7 > button` "Continue"
- **Flow**: Wait for timer → click `#btn6` (hides itself) → wait for `#btn7` → click `#btn7 > button` → direct navigation
- **Domains observed**: bcsakhi.in (life-insurance articles)

### Template C: LINK1S (startCountdownBtn)
- **Timer**: `#link1s-wait1` (8s, PAUSED until click)
- **Start button**: `#startCountdownBtn` "click to verify" → must click to START countdown
- **After click**: timer resets to 14s, counts to 0/-1
- **Result button**: `#cross-snp2` "Continue" (appears when timer ends)
- **Flow**: Click `#startCountdownBtn` → wait for countdown (14s) → click `#cross-snp2` → `learn_more.php` redirect → back to vplink.in
- **Domains observed**: bcsakhi.in (cloud-architect articles)

### Unknown Template Fallback
If no template detected, tries all known buttons in priority order + text-based "Continue"/"Verify" search.

## Full Flow (Recorded 2026-07-16)

```
vplink.in/{KEY}
  → (JS redirect) article-domain.com/intermediate/?param={KEY}&uiso={random}
  → (auto-redirect) article-domain.com/article-slug/
  → [Template A] click popup → click #tp-snp2 → learn_more.php → redirect
  → [Template B] click #btn6 → click #btn7 > button → direct nav
  → [Template C] click #startCountdownBtn → wait → click #cross-snp2 → learn_more.php → redirect
  → (back to vplink.in)
  → #get-link: 7s countdown → "Getting link..." → POST /links/go → href becomes destination
  → click #get-link → new tab opens with destination URL
```

**Observed sequence**: vplink.in → jobskiki.in (TP) → bcsakhi.in (TP) → bcsakhi.in (CE) → bcsakhi.in (LINK1S) → vplink.in → capecutapk.com

## Human-Like Behavior (Anti-Bot)

- **Random delays**: 200-2000ms between actions (varies by action type)
- **Smooth scrolling**: 100-400px scrolls with `behavior: 'smooth'`, 1-3 scrolls per page
- **Mouse movement**: moves to element before clicking (random position within bounding box, 5-15 step curve)
- **Template-aware waiting**: waits for countdown to finish naturally, doesn't bypass timers
- **Popup handling**: checks for `#continueBtn` during countdown, clicks with `force: true` (CSS animation bypass)

## Get Link Handler

1. Wait for `#get-link` element (up to 40s)
2. Wait for `disabled` class removal (countdown ~7s)
3. Human-like delay + mouse move before click
4. Capture `href` before clicking (fallback)
5. Click `#get-link` → new tab opens (popup IS the destination)
6. Poll both main page + popup URL for up to 60s
7. **URL stability check**: 3 consecutive same-URL observations
8. **Destination patterns**: `capecutapk.com`, `amazingbaba.com`, `apkmirror.com`, `play.google.com`, `download`, `.apk`, `casino`, etc.
9. Wait up to 25s total for tracking chain completion

## Env Vars
- `VPLINK_KEY` — key fallback
- `VPLINK_TERMUX=1` — headless mode
- `CHROMIUM_PATH` — custom Chromium binary
- `VPLINK_PROXY` — `--proxy-server` Chrome arg
- `VPLINK_USER_AGENT` — context userAgent
- `VPLINK_VIEWPORT_WIDTH` / `VPLINK_VIEWPORT_HEIGHT` — viewport
- `VPLINK_EXTRA_ARGS` — extra Chrome args (space-separated)
- `VPLINK_DEBUG=1` — screenshots + HTML captures at key steps

## Stealth
- `navigator.webdriver` → `undefined`
- `navigator.plugins` → `[1,2,3,4,5]`
- `navigator.languages` → `['en-US', 'en']`
- `window.chrome` → `{ runtime: {} }`
- `navigator.permissions.query` → denies notifications
- Chrome args: `--disable-blink-features=AutomationControlled`, `--disable-automation`

## Key Decisions
- **Domain-agnostic**: detect template by DOM (timer IDs, button IDs), never by domain name
- **3 templates**: TP (`#tp-time`/`#tp-snp2`), CE (`#ce-time`/`#btn6`/`#btn7`), LINK1S (`#startCountdownBtn`/`#cross-snp2`)
- **Human-like timing**: random delays, smooth scrolling, mouse movement before clicks
- **Trusted clicks only**: `page.click()` first, JS fallback only for non-critical buttons
- **Popup force-click**: `#continueBtn` has CSS pulse animation — `page.locator().click({ force: true })` bypasses stability wait
- **No timer bypass**: wait for countdown to complete naturally (AJAX heartbeats register dashboard views)
- **learn_more.php redirector**: all article pages chain through `learn_more.php` to next article or back to vplink.in
- **Get Link POST**: `POST /links/go` returns `{status: "success", url: "..."}` — the URL is the real destination
- **New tab IS the destination**: popup opened by `#get-link` click contains the destination URL

## CLI Usage
```bash
vplink3.0                          # Interactive
node automation.js <KEY>           # Direct
node flow-recorder.js [KEY]        # Record flow for analysis
```

## Known Issues
- Article page structure may change without notice (weekly domain rotation)
- `#startCountdownBtn` timer resets to 14s after click (not the displayed 8s)
- `#tp-time` countdown is hidden (`display: none`) — must wait for it to reach 0 via JS
- Popup `#continueBtn` appears at indeterminate time (~6s before timer ends)
- Proxy runs may cause new tab to chrome-error — href fallback handles this
