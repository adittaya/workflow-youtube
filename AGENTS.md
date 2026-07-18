# VPLink 3.0 — Agent Context

> **MANDATORY: Any AI agent editing this project MUST update this file** with changes made, new decisions, fixes, or known issues. This prevents hallucination across sessions. If you don't update this file, the next agent will have stale context.

## Version History
| Date | Change | Author |
|------|--------|--------|
| 2026-07-05–08 | Initial development, iterative fixes, CI, installer (see git log) | AI |
| 2026-07-16 | **Complete rewrite from live recording**: recorded full flow with network/console/DOM/screenshot capture. Analyzed 3 article templates (TP, CE, LINK1S). Rewrote automation.js with domain-agnostic template detection, human-like behavior (random delays, smooth scrolling, mouse movement), and bot-detection handling. | AI |
| 2026-07-17 | **macOS CI fixes**: Replaced `grep -oP`/`grep -qP` (PCRE) with POSIX-compatible `grep`+`sed`/`awk` in state.sh and config.sh JSON handling. Fixed multi-line sed `\n` replacement (GNU-only) with `awk`. Replaced `:a;N;$!ba` hold-space loop with `awk`. Fixed `bash -c` subshells inheriting `set -e` from CI. Skipped `declare -A` modules on macOS bash 3.2. CI now passes all 5 jobs (shellcheck, Linux, macOS, Termux, smoke). | AI |
| 2026-07-17 | **Critical bug fixes**: Fixed `kill 0` in vplink-desktop.sh (VNC_PID=0 killed entire process group). Fixed cleanup_pids trap recursion loop. Added interactive credential setup (`vplink3.0 config --setup`). Polished run summary box with checkmarks. Fixed `BASH_SOURCE[0]` unbound variable in curl pipe. | AI |
| 2026-07-17 | **#goog_rewarded + stuck-loop fixes**: Fixed `#goog_rewarded` infinite loop (popup click → ad page → kept clicking buttons → loop). `handlePopup` now returns `'rewarded'` state. `waitForCountdown` propagates `'rewarded'` return. `handleArticle` waits 45s for ad redirect. Added `#goog_rewarded` handler in main loop (clears hash). Added stuck-loop detection (3 consecutive same-URL visits → force-navigate, excludes vplink.in + intermediate redirect pages). Fixed CE template: page reloads to same URL after btn7 — handleArticle now returns `true` on button success without requiring base URL change. Added `dumpDOM` helper for debug HTML + screenshots. Max cycles 40→25. E2E test: full funnel completion darkguruji→srtak×3→vplink.in→destination in ~460s. | AI |
| 2026-07-17 | **Proxy filtration + YouTube referral fix**: Added `testProxyBrowser()` — CONNECT tunnel test validates actual page content (>50 bytes) to match Chrome's real browsing behavior. `getProxy()` chains quick→browser tests. Removed broken `extraHTTPHeaders` Referer and `page.route` intercept (both broke vplink.in by applying YouTube Referer to ALL requests including subresources). Replaced with **YouTube-first navigation**: navigate to YouTube page first, browser naturally sets `Referer: https://www.youtube.com/` on next navigation to vplink.in. Updated `profile-generator.js` to output `youtubeReferer` URL instead of `extraHTTPHeaders`. Fixed `vplink3.0.sh` to export `VPLINK_REFERER` env var. | AI |
| 2026-07-17 | **Interactive mode crash fixes**: Fixed `cleanup_pids` calling `vplink-desktop.sh stop` unconditionally on every loop iteration (including first, when nothing is running) — added `DESKTOP_STARTED` flag guard. Added `CLEANING_UP` re-entrancy guard to prevent trap recursion. Fixed `vplink-desktop.sh` `do_stop` running `pkill -x "Xvfb"` 10x redundantly in a loop (now runs once). Expanded lock file cleanup range from 99-108 to 99-199. Fixed `automation.js:889` destination URL overwrite bug (`if (gotDest) destinationUrl = safeURL()` was overwriting correct destination set by `doGetLink()` with vplink.in URL). Added `VPLINK_TRACE` debug env var for run-loop tracing. | AI |
| 2026-07-17 | **Complete rewrite of vplink3.0.sh**: Deleted and rewrote interactive CLI from scratch. Clean architecture: `full_cleanup()` calls `kill_tracked()` + `stop_desktop()`. Desktop lifecycle uses `DESKTOP_PID`/`DESKTOP_DISPLAY` tracking instead of global flags. Re-entrancy via `trap '' SIGINT SIGTERM` during critical sections. EXIT trap added for normal-exit cleanup. Fixed KEY extraction to strip query params/fragments. Proper bash 3.x compat (`${TRACKED_PIDS[@]}` empty-array guard). Manual pkill fallback in `stop_desktop()` when vplink-desktop.sh unavailable. `EXISTING_DISPLAY` variable preserved across unset. Node array for desktop start args. Shellcheck clean (only SC2162 info). | AI |
| 2026-07-17 | **Xvfb removed, headless-only**: Removed interactive display/VNC questions from CLI. Playwright headless + `--use-gl=swiftshader` replaces Xvfb — `page.click()`, `page.mouse.move()`, smooth scrolling all work identically in headless mode. Removed `start_desktop()`, `stop_desktop()`, `DESKTOP_PID`, `DESKTOP_DISPLAY`, `STATE_DIR`, `detect_vnc()`. Display section simplified to `unset DISPLAY` + `export VPLINK_HEADLESS=1`. Signal handler fixed: `trap '' EXIT` → `kill_tracked` → `exec kill -9 $$` for clean exit during child processes. `proxy-rotator.js` fetch timeout added (AbortController 25s). `getCountdown()` fixed: `parseInt("") || 0` returned 0 prematurely causing TP timeouts — now treats NaN as "not ready" (-1). `#goog_rewarded` stuck loop fixed: max 2 retries before force-navigating to vplink.in. | AI |
| 2026-07-17 | **Proxy batch cascade**: Rewrote `getProxy()` — now tests proxies in batches of 100 (quick alive 5s → browser test 12s). If batch 1 fails, cascades to batch 2, 3, etc. (up to 5 batches of 100 from 500 total). Increased shell timeout from 30s to 120s. Removed auto-delete of dead proxies from rotation flow (caused DB writes on every run). Added YouTube video `8A2LHzyevJA` to referrer list. | AI |
| 2026-07-17 | **Proxy visibility + intermediate page fixes**: Removed `2>/dev/null` from proxy engine in shell — proxy progress now visible in real-time. Added `studiiessuniversitiess` and `universitesstudiiess` to intermediate page detection (were being treated as article pages, causing stuck loops). Added `intermediateStuckCount` — force-navigates to vplink.in after 3 unredirecting intermediate pages. Destination redirect wrapper detection (linkedin.com/redir, google.com/url, facebook.com/l.php, t.co) waits 15s for resolution. `hardGoto` wrapper with 30s timeout prevents `page.goto` hanging with broken proxies. `skipMainLoop` flag skips redirect/CF detection when proxy fails during initial goto. `btnState === null` handled same as `missing`. Shell proxy retry timeout 120s. Proxy engine timeout 120s (was 300s). E2E passed: full funnel in ~407s. | AI |
| 2026-07-17 | **Faster stuck detection + E2E optimization**: `#goog_rewarded` ad wait 45s→15s. Hash-only change wait 15s→8s. `MAX_URL_VISITS` 3→2 (detect stuck articles faster). Stuck-loop force-nav now reports `proxyBlocked` + exit(2) immediately (was: force-nav to vplink.in creating infinite loop). Intermediate stuck 3x→2x. Final fallback skipped when `proxyBlocked`. E2E benchmark: 3/4 pass (75%). Failures from `#goog_rewarded` ad not redirecting with certain proxies. Destination URLs confirmed working (apkmirror.com, amazingbaba.com). | AI |

## Overview
Automated vplink.in URL funnel: navigate auto-redirects, handle article pages (any domain), click "Get Link" on vplink.in, and capture the final destination URL.

**Key design principle: Article domains change weekly. The automation detects page types by DOM structure (timer IDs, button IDs), NOT by domain name.**

## Files
| File | Purpose |
|------|---------|
| `automation.js` | **Main script** — Playwright automation with domain-agnostic template detection and human-like behavior |
| `config.js` | Config management — load/save `~/.vplink3.0/config.json`, CLI get/set |
| `proxy-rotator.js` | Proxy rotation — fetches from Supabase, tests, deletes dead IPs, 24h no-repeat |
| `profile-generator.js` | Profile generator — random mobile/desktop UAs, viewports, YouTube referer URL |
| `vplink3.0.sh` | Interactive CLI — questionnaire, PID tracking, VNC detection, desktop lifecycle via DESKTOP_PID tracking |
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
- `VPLINK_REFERER` — YouTube URL to navigate to first (browser sets Referer naturally)
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
- **#goog_rewarded = ad page**: after popup click, if URL contains `#goog_rewarded`, STOP clicking and wait for ad redirect (45s timeout). `handlePopup` returns `'rewarded'` state, propagated through `waitForCountdown` → template handlers → `handleArticle`
- **Stuck-loop detection**: track URL visit counts per URL, force-navigate after 3 visits to same article. Excludes vplink.in (needs multiple cycles for countdown) and intermediate redirect pages (learn_more.php, studieseducates, studiiessuniversitiess, etc.)
- **CE same-URL reload**: CE template btn7 can cause page reload to same URL (with `#/` hash). handleArticle returns `true` on button success regardless of URL change, letting main loop re-evaluate
- **dumpDOM helper**: saves HTML + screenshot to `screenshots/` when `VPLINK_DEBUG=1`
- **YouTube-first navigation**: navigate to YouTube page first, browser naturally sets `Referer: https://www.youtube.com/` on next navigation to vplink.in. No header manipulation needed — `extraHTTPHeaders` Referer broke vplink.in by applying to ALL requests (subresources too). `page.route` intercept also broke it. Natural browser navigation is the only reliable approach.
- **hardGoto wrapper**: 30s hard timeout on `page.goto` prevents Playwright hanging indefinitely with broken proxies. `skipMainLoop` flag skips redirect/CF detection when proxy fails during initial goto.
- **Intermediate page stuck detection**: `intermediateStuckCount` tracks unredirecting intermediate pages (learn_more.php, studiiessuniversitiess, universitesstudiiess). After 3 stuck cycles, force-navigates to vplink.in.
- **Destination redirect wrapper detection**: when popup opens a LinkedIn/Google/Facebook/Twitter redirect URL, waits up to 15s for it to resolve to the actual final URL before capturing.

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
- Headless Chromium requires `--use-gl=swiftshader` on GPU-less servers — without it, `headless_shell` crashes immediately
