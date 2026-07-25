# VPLink Automation System — Guide

> A production-grade, future-proof automation engine for VPLink-type link protector funnels.
> Built to handle ANY variation — domains change, headings change, templates shuffle, but the system stays.

---

## Core Principle

**Follow the page, don't fight it.**

The page's own JavaScript is the authority. When we force-call JS functions or manipulate DOM elements before the page is ready, things break. The simplest approach is the most reliable:

1. Load the page
2. Wait for elements to appear
3. Interact with them
4. Navigate to the next step

No tricks. No cookie injection. No fighting. Just patience.

---

## Our Stack

| Component | Choice | Why |
|-----------|--------|-----|
| Browser | Selenium + ChromeDriver | Widest support, CDP access via `execute_cdp_cmd` |
| Language | Python 3.12 | Rich libraries, easy to read, fast prototyping |
| Scheduling | GitHub Actions | Free tier, `repository_dispatch` for relay loop |
| Proxy | Supabase + custom rotator | Datacenter proxies, pagination, blacklist, used-tracking |
| Monitoring | Structured `log()` calls | Every action timestamped with elapsed time |
| Stealth | `profile_generator.py` | 12+ fingerprint spoofing properties |

### Page Load Strategy

We use `driver.set_page_load_strategy("none")` — the fastest option. Selenium returns control immediately without waiting for all resources (images, iframes, ads). We handle waits manually via `WebDriverWait` and PageMonitor's `wait_for_event()`. This matters when pages have heavy ad scripts that stall the load event.

### Proxy Type

We use **datacenter proxies** (not residential). They're cheaper and faster but更容易被目标站点检测到. Our stealth system (`profile_generator.py`) compensates for datacenter IP detection by spoofing 12+ browser fingerprint properties (viewport, hardware concurrency, WebGL, canvas, audio, battery, screen, permissions).

---

## Architecture Overview

**Pattern: State Machine** — The main loop is a state machine where each URL determines the current state and which handler fires.

```
vplink.in/KEY
    |
    v
+---------------+
|  Initial      |  navigate to vplink.in/KEY
|  Redirect     |  Wait for JS redirect to article page (up to 30s, 5 attempts)
+-------+-------+
        |
        v
+---------------+
|  Article      |  detect_template() -> TP / CE / LINK1S / getlink / unknown
|  Page         |  fingerprint_page() -> behavioral detection (future-proof)
|               |  CSS shell detection -> fast-fail when proxy blocks content
|               |  Force-render -> reveal hidden elements when DOM is suppressed
+-------+-------+
        |
        v
+---------------+
|  Handler      |  handle_tp() / handle_ce() / handle_link1s() / handle_generic()
|  (wait+click) |  Waits for button -> clicks -> navigates to learn_more.php
|               |  Ad overlay dismissed BEFORE interaction (CDP-exact order)
+-------+-------+
        |
        v
+---------------+
|  Redirect     |  learn_more.php -> new article page
|  Chain        |  Repeats until get-link page (up to 10 steps)
|               |  Guard pages followed via raw HTML extraction
+-------+-------+
        |
        v
+---------------+
|  Destination  |  Extract from parent <a> href of #get-link button
|  URL          |  2-click pattern (CDP-verified), adaptive wait
+---------------+
```

---

## Template System

VPLink uses 4 templates that cycle across articles. Template sequence observed via CDP: Landing -> TP -> TP -> CE -> LINK1S -> get-link -> DESTINATION.

### Template A — Landing (TP)
- **Elements:** `tp-wait1`, `tp-time`, `tp-generate`, `tp-snp2`
- **Behavior:** Timer counts down (15s or 24s) -> Continue button appears -> Click -> learn_more.php
- **Handler:** `handle_tp()` — closes ads first, waits up to 35s for `tp-snp2`, tries parent `<a>` href fast-path, falls back to `navigate_learn_more()`, then JS click, then raw HTML fallback

### Template B — Step (CE)
- **Elements:** `stick` (step indicator), `btn6` (Verify), `btn7` (Continue), `ce-wait1`, `ce-time`
- **Behavior:** Verify button -> Continue button -> learn_more.php
- **Handler:** `handle_ce()` — closes ads, waits for countdown, clicks btn6, waits for btn7, clicks btn7, navigates. Raw HTML fallback if btn7 never appears.

### Template C — Countdown (LINK1S)
- **Elements:** `startCountdownBtn`, `link1s-wait1`, `link1s-time`, `cross-snp2`, `#post-2500 > div`
- **Behavior:** Click verify -> countdown -> Continue -> learn_more.php
- **Handler:** `handle_link1s()` — clicks startCountdownBtn, clicks `#post-2500 > div` (CDP step 300), waits up to 60s for cross-snp2. Raw HTML fallback if cross-snp2 never appears.

### Template D — Destination (getlink)
- **Elements:** `get-link` (button), `gt-link`, parent `<a href>` = destination URL
- **Behavior:** Timer -> get-link appears -> parent `<a>` href IS the destination
- **Handler:** `do_get_link()` — fast path reads parent `<a>` href directly. Falls back to 2-click pattern (CDP-verified: first click activates, second navigates). Up to 5 click attempts with adaptive wait.

### Unknown Templates
- **Detection:** `fingerprint_page()` — behavioral fingerprinting
- **Behavior:** Detects page type by WHAT it does, not element IDs
- **Handler:** `handle_generic(fp)` — uses `isRealButton()` JS helper to find real buttons

---

## Detection System

### Template Detection (`detect_template()`)
Checks for specific element IDs to determine which template is active:
- `tp-time` / `tp-wait1` -> TP template
- `ce-time` / `ce-wait1` -> CE template
- `link1s-wait1` / `startCountdownBtn` -> LINK1S template
- `get-link` -> Destination page
- Otherwise -> `unknown`

### Behavioral Fingerprinting (`fingerprint_page()`)
When template detection fails, behavioral fingerprinting kicks in:
- Detects countdown elements by `[id*="time"], [class*="timer"]`
- Detects buttons by text content and visibility
- Detects overlays, popup blockers, get-link elements
- Returns a dict with: `has_countdown`, `has_verify_btn`, `has_continue_btn`, `has_getlink`, `has_learn_more`, `page_type`

**Why this is future-proof:** If VPLink renames element IDs, template detection fails, but behavioral fingerprinting still works because it detects WHAT the page DOES, not what the elements are CALLED.

### CSS Shell Detection
When a proxy IP is blocked by the target domain, the server returns a CSS shell: the page has height (>500px) but the body text is empty (<100 chars). The automation detects this in `handle_article()` and fast-fails without wasting 20s on a reload that will never work.

### Force-Render
When the page has content (body_len > 200) but height = 0 (elements hidden), the automation removes `display:none`, `visibility:hidden`, and `opacity:0` from all elements EXCEPT ad overlays (`#block-cont-1`, `#gcont`, `#goog_rewarded`). This reveals VPLink elements that the page tried to suppress.

### Helper Functions
- `has_countdown_template()` — checks for any article template elements (TP/CE/LINK1S/getlink)
- `is_article_page(url)` — True if page has template elements, not vplink.in, not destination
- `is_intermediate_page(url)` — True if URL contains `learn_more.php`
- `is_destination(url)` — True if not article/intermediate/vplink, valid hostname, no article signals, no VPLink HTML in source, AND funnel progress > 0
- `is_ad_domain(url)` — checks against 14 known ad domains
- `looks_like_article_url(url)` — detects article pages by URL structure heuristics (any domain)
- `get_step_info()` — extracts step progress text from `#stick` element
- `get_countdown()` — reads countdown timer value from any template element
- `get_raw_html(max_len)` — gets raw HTML source from page, works even when JS doesn't execute
- `detect_js_health()` — comprehensive JS health check (height, body_len, vplink_elements, verdict)
- `find_learn_more_in_html()` — finds learn_more.php links in raw HTML and navigates to first one
- `extract_redirect_from_html(html)` — extracts redirect target URL from raw HTML scripts/meta refresh

---

## PageMonitor — Real-Time Detection

Instead of polling the DOM every second, PageMonitor uses:

### MutationObserver
- Watches the entire DOM for changes (childList + attributes + subtree)
- Fires `dom_mutation` events on ANY change

### Network Interceptors
- Intercepts `fetch()` and `XMLHttpRequest`
- Captures all network activity (requests, responses, errors)

### Periodic State Snapshots
- Every 500ms: captures countdown value, button visibility, overlays, step info, get-link href
- Python polls JS event queue every 100ms
- Methods: `wait_for_event()`, `wait_for_url_change()`, `wait_for_countdown_zero()`, `wait_for_nav_button()`

---

## Raw HTML Fallback — When JS Fails

VPLink JS sometimes fails to execute on article pages (page height=0, no template elements). The raw HTML fallback system handles this case.

### How It Works
1. **Detect**: `detect_js_health()` checks page height, body_len, element count.
2. **Parse**: `get_raw_html()` gets the page source via `document.documentElement.outerHTML`.
3. **Extract**: `find_learn_more_in_html()` regex-searches HTML for `href="...learn_more.php..."` links.
4. **Navigate**: If found, navigates to the URL via `window.location.href`.
5. **Fallback**: `extract_redirect_from_html()` searches for `window.location = '...'`, meta refresh, and external links.

### Where It's Used
- **`handle_article()`**: CSS shell -> raw HTML. Empty page -> force-render -> raw HTML -> reload -> raw HTML.
- **`handle_tp()`**: After `tp-snp2` never appears
- **`handle_ce()`**: After btn7 never appears
- **`handle_link1s()`**: After cross-snp2 never appears
- **Intermediate page handler**: After learn_more.php page doesn't redirect
- **`is_destination()`**: Checks raw HTML for VPLink elements before classifying as destination
- **Guard page handler**: When mid-flow and page has no VPLink elements

---

## Guard Page Flow Continuation

Some pages in the VPLink funnel have no VPLink elements — "guard pages" between article pages. The automation follows the flow instead of breaking the chain.

### How It Works
1. **Detection**: After all-false fingerprint wait loop, if `_funnel_progress > 0` (mid-flow), the page is a guard page.
2. **Raw HTML scan**: `find_learn_more_in_html()` searches for `learn_more.php` links in HTML source.
3. **Follow**: If found, navigates to the link — keeps the funnel chain intact.
4. **Redirect extraction**: `extract_redirect_from_html()` tries scripts, meta refresh, external links.
5. **Exhausted handler**: Before force-navigating to vplink.in, checks raw HTML for learn_more.php when mid-flow.

### Why This Is Critical
VPLink's redirect chain sometimes passes through pages that don't contain VPLink template elements. Force-navigating back to vplink.in breaks the chain and wastes time re-entering the funnel from scratch.

---

## Funnel Progress Tracking

The funnel progress system prevents false-positive destination detection on empty article pages.

- `_funnel_progress` counter tracks how many `learn_more.php` redirects we've completed
- `_funnel_progress = 0` -> We haven't entered the funnel yet
- `_funnel_progress = N` -> We've been through N redirects
- Initialized to 0 at start of each proxy attempt
- Incremented when `is_intermediate_page(url)` is True
- Synced to `learn_more_count` after each `handle_article()` success
- `is_destination()` returns False if `_funnel_progress == 0`
- Guard page handler only activates when `_funnel_progress > 0`

---

## Proxy System

### One IP Per Session
- Test proxy once before starting
- Use that IP for ALL browser work
- No mid-session rotation — keeps the session clean
- Workflow-level retry handles bad proxies (3 attempts + 1 no-proxy fallback)

### Workflow Retry Logic
```
Attempt 1: Get proxy -> Run automation (15min timeout)
  If ran < 120s -> proxy blocked -> rotate -> Attempt 2
  If ran >= 120s -> proxy worked -> done
Attempt 2: New proxy -> Run automation
Attempt 3: New proxy -> Run automation
Attempt 4 (no-proxy): Run WITHOUT proxy (local tests show automation works fine direct)
```

### Proxy Failure Detection
- `report_proxy_failure(reason)` logs failure and marks proxy for blacklist
- CSS shell detection -> `content-blocked`
- Reload failure -> `reload-failed`
- Intermediate page stuck 3x -> `intermediate-stuck`
- Chrome error -> `chrome-error`
- vplink.in get-link missing after 5 arrivals -> `vplink-get-link-missing`

---

## Flow Handling

### Adaptive Step Count
- Step count is variable (2, 3, 4, N steps)
- `max_url_visits = 10` — handles up to 10 steps
- Step progress tracked via `#stick` element: "You are currently on step X/N"

### Adaptive Redirect Chains
- Redirect chains are variable (1, 2, 3, 5 hops)
- Up to 5 redirect attempts before giving up
- Thread-based URL polling catches redirects that main loop misses
- Regex extraction from page HTML as fallback for broken JS redirects

### Adaptive Timeouts
- `adpt_nav` — initial navigation timeout (default 40s)
- `adpt_load` — page load timeout (default 30s)
- `adpt_redirect` — redirect wait timeout (default 25s, hard max 30s)
- `adpt_poll` — polling timeout (default 30s)
- `adpt_getlink` — get-link page timeout (default 40s)

### 15-Minute Hard Timeout
- `AUTOMATION_HARD_TIMEOUT = 900s` from browser start to destination
- Step `timeout-minutes: 15` in CI workflow
- Bash `timeout 880` per attempt

### Dead URL Tracking
- `dead_urls` set tracks URLs that failed
- When same URL fails again -> force-navigate away immediately
- `exhausted_cycles` increments on dead URL bounce
- Breaks after 5 consecutive exhausted cycles

---

## Anti-Detection

### Human-Like Behavior
- `human_delay(min_ms, max_ms)` — random delays between actions
- `human_read(seconds)` — simulates reading with keyboard scrolling (PageDown/ArrowDown events), random pauses. No mouse movement (CDP-verified: 0 mouse movements across 315 steps).
- `human_scroll()` — random scroll patterns (1-3 scrolls, random distances)
- `human_click(selector)` — click with random offset, falls back to JS click. No mouse movement before click (CDP-verified).

### Browser Stealth (via profile_generator)
- Custom user agent (Chrome mobile)
- Mobile device emulation (randomized viewport)
- Hardware concurrency spoofing (4-16 cores)
- Memory spoofing (4-16GB)
- Device pixel ratio randomization
- WebGL vendor/renderer spoofing
- Canvas fingerprint noise injection
- Audio context noise injection
- Battery API spoofing
- Screen properties spoofing
- Permission API override (notifications = denied)

### Timing Randomization
- All delays use `random.uniform(min, max)` — never fixed delays
- `human_delay(2000, 4000)` = random between 2-4 seconds
- Inter-article delays: `rand(8000, 22000)` = 8-22 seconds (wide range)
- Scroll speeds: randomized keypress intervals
- Click offsets: random pixel offsets within button bounds

### Ad Overlay Handling
CDP-exact dismissal order (ads dismissed BEFORE scrolling, not after):
1. `#block-cont-1` — remove element
2. SafeFrame iframes — close buttons (`#close-button > div`, `#close-ad-button`)
3. `#gcont` — remove element
- `handle_popup()` — detects and handles popup blocker dialogs
- `handle_goog_rewarded()` — waits for Google rewarded ads to complete (up to 90s)
- `check_ad_hijack()` — detects when ads redirect away from article (checks 14 ad domains)
- Force-render SKIPS overlay elements when removing display:none

---

## 24/7 Relay System

The relay system creates an infinite loop: each workflow run dispatches the next run via `repository_dispatch`.

### How It Works
1. Workflow run completes (success, failure, or timeout)
2. Relay step fires (condition: `if: always()`)
3. `curl -X POST` to `https://api.github.com/repos/{RELAY_TARGET_REPO}/dispatches`
4. New workflow run starts -> back to step 1

### Why `always()` Is Critical
- GitHub Actions `cancelled` status (from job timeout) is NOT covered by `success() || failure()`
- Only `always()` covers all states: success, failure, cancelled, skipped
- Without `always()`, job timeout breaks the relay loop permanently
- Root cause found: vplink-ttrgg55 had only 1 run ever because `conclusion=cancelled` caused relay to skip

---

## CDP-Verified Flow

Analysis of Chrome DevTools Protocol recording (`vplink111.json`, KEY=ekor0) — 315 steps, 18 clicks, 259 scroll keys:

| Step | Action | CDP Evidence |
|------|--------|-------------|
| 1 | Navigate to vplink.in/ekor0 | JS redirect to darkguruji.com article |
| 2 | Close ad overlays (#block-cont-1, SafeFrame, #gcont) | Steps 4-8: click #close-button > div, #close-ad-button |
| 3 | Read article (keyboard scrolling only) | Steps 9-80: 259 PageDown/ArrowDown keys, 0 mouse movements |
| 4 | Click #tp-snp2 (TP template) | learn_more.php redirect |
| 5 | Read next article, click #tp-snp2 again | Second TP template |
| 6 | Read next article, click #btn6 (CE verify) | Waits for countdown |
| 7 | Click #btn7 (CE continue) | learn_more.php redirect |
| 8 | Click #startCountdownBtn (LINK1S) | Click #post-2500 > div |
| 9 | Wait for countdown, click #cross-snp2 | learn_more.php redirect |
| 10 | Click #get-link (1st click activates) | 2s delay, 2nd click navigates |
| 11 | Capture destination URL from new tab | apkmirror.com |

**Key findings:**
- Pure keyboard scrolling (no mouse movement at all)
- Ad dismissal happens BEFORE reading, not after
- `#get-link` requires 2 clicks (first activates, second navigates)
- Domain changes across flow (darkguruji.com -> srtak.com)
- All transitions via `learn_more.php` JS redirects

---

## Key Functions Reference

| Function | Purpose |
|----------|---------|
| `detect_template()` | Identifies active template (TP/CE/LINK1S/getlink/unknown) |
| `fingerprint_page()` | Behavioral fingerprinting for unknown templates |
| `handle_tp()` | Waits for tp-snp2, navigates via parent `<a>` href + raw HTML fallback |
| `handle_ce()` | Waits for countdown, clicks btn6->btn7 + raw HTML fallback |
| `handle_link1s()` | Clicks startCountdownBtn, #post-2500 > div, waits for cross-snp2 |
| `handle_generic(fp)` | Generic handler using behavioral fingerprint + isRealButton |
| `handle_unknown()` | Last resort: tries all known buttons by ID then by text |
| `do_get_link()` | Fast path: parent `<a>` href. Fallback: 2-click pattern, up to 5 attempts |
| `handle_article()` | Main handler: CSS shell detect, force-render, template dispatch, guard page |
| `get_countdown()` | Reads countdown timer value from any template |
| `get_step_info()` | Extracts step progress from `#stick` |
| `navigate_learn_more()` | Finds and navigates to learn_more.php |
| `find_learn_more_in_html()` | Finds learn_more.php links in raw HTML source |
| `extract_redirect_from_html(html)` | Extracts redirect target from raw HTML scripts/meta refresh |
| `get_raw_html(max_len)` | Gets raw HTML source from page (works when JS broken) |
| `detect_js_health()` | Comprehensive JS health check (height, body_len, verdict) |
| `looks_like_article_url(url)` | Detects article pages by URL structure heuristics |
| `close_ad_overlay()` | Closes ad overlays (CDP-exact order) |
| `handle_popup()` | Handles popup blocker dialogs |
| `check_ad_hijack()` | Detects ad domain redirects, navigates back |
| `is_ad_domain(url)` | Checks URL against 14 known ad domains |
| `is_destination(url)` | Checks if URL is valid destination (requires funnel progress > 0) |
| `is_article_page(url)` | Checks if URL has article template elements |
| `wait_for_countdown(template, max_wait)` | Waits for countdown to reach 0 |
| `human_read(seconds)` | Simulates reading with keyboard scrolling |
| `human_click(selector)` | Click with random offset, JS fallback |
| `PageMonitor` | Real-time DOM/network monitoring |

---

## What Makes This System Good

### 1. Domain-Agnostic
No hardcoded article domains. Works with any domain VPLink uses. Handles domain changes automatically.

### 2. Future-Proof
Behavioral fingerprinting survives element ID renames. Detects page type by behavior, not names.

### 3. Adaptive
Handles any number of steps (2, 3, 4, N). Handles any redirect chain length. Adjusts timeouts based on observed behavior.

### 4. Reliable
Follows the page naturally. Multiple fallback paths for each template. Fast path destination extraction. Raw HTML fallback when VPLink JS doesn't execute. Guard pages followed instead of broken.

### 5. Observable
PageMonitor provides real-time visibility. Detailed logging of every action with elapsed time. Step progress tracking. JS health detection (healthy/degraded/broken).

### 6. Clean
Each handler does one thing: wait -> click -> navigate. No cookie injection or JS manipulation. Ad hijack detection with 14 known ad domains. Consistent return values (strings, not booleans).

### 7. Resilient
Funnel progress guard prevents false-positive destination detection. Raw HTML parsing when DOM is empty. Multiple retry paths: DOM -> raw HTML -> reload -> proxy blacklist. CSS shell detection skips wasted reloads. Guard pages followed via raw HTML. Dead URL tracking prevents infinite loops.

---

## Design Principles

1. **Follow the page** — Don't inject cookies, don't force JS, don't manipulate DOM before the page is ready
2. **Wait for elements** — Don't assume timing, wait for buttons to appear
3. **Detect by behavior** — Don't rely on element IDs, detect what the page DOES
4. **One IP per session** — Test once, use throughout
5. **Fail gracefully** — Multiple fallback paths, never get stuck
6. **Keep it simple** — Complex code breaks, simple code works
7. **Funnel progress guard** — Don't classify any page as destination until we've completed at least one funnel step
8. **Raw HTML fallback** — When VPLink JS doesn't execute, parse the raw HTML source for learn_more.php links and redirect targets
9. **Domain-agnostic** — Never hardcode article domains. Use URL structure heuristics and funnel progress tracking instead.
10. **Guard page flow** — When mid-flow and page has no VPLink elements, follow learn_more.php from raw HTML instead of breaking the chain
11. **CDP-verified behavior** — Ad dismissal before scrolling, keyboard-only scrolling, 2-click get-link, no mouse movement before clicks

---

## Error Handling

### Error Classification

The automation classifies errors into categories to determine the right response:

| Category | Examples | Response |
|----------|----------|----------|
| **Proxy** | `ERR_TUNNEL_CONNECTION_FAILED`, CSS shell, content-blocked | Blacklist proxy, rotate |
| **Transient** | `TimeoutException`, stale element, page not ready | Retry with backoff |
| **Permanent** | `404`, `403`, chrome-error | Skip, force-navigate |
| **Ad** | Ad domain redirect, popup blocker, Google rewarded | Dismiss, continue |
| **Page** | Empty page, broken JS, guard page | Raw HTML fallback |

### Retry Strategy

Each handler has built-in retry with fallback escalation:

```
Template handler retry:
  1. Wait for element (explicit wait, up to 35-60s)
  2. Try parent <a> href fast-path
  3. Try navigate_learn_more()
  4. Try JS click
  5. Try raw HTML extraction
  6. Try force JS redirect to learn_more.php

Main loop retry:
  1. handle_article() -> True -> continue
  2. If failed, wait 8-12s (grace period after learn_more)
  3. Check dead_urls set
  4. Check raw HTML for learn_more.php (guard page)
  5. Force-navigate to vplink.in
  6. After 5 exhausted cycles -> break to final fallback
```

### Circuit Breaker Patterns

- **`exhausted_cycles`**: Increments on dead URL bounces. Breaks after 5 consecutive.
- **`intermediate_stuck_count`**: Increments when learn_more.php doesn't redirect. Blacklists proxy after 3.
- **`vplink_arrivals`**: Counts vplink.in arrivals without article page. Declares proxy blocking after 5.
- **`dead_urls`**: Set of failed URLs. Same URL fails twice -> force-navigate immediately.

---

## Common Pitfalls (and How We Avoid Them)

### 1. Using `time.sleep()` for Synchronization
**BAD:** `time.sleep(5)` then find element.
**GOOD:** Explicit waits via `WebDriverWait` or PageMonitor `wait_for_event()`. Random delays via `human_delay()` only for human-like timing, not synchronization.

### 2. Not Handling Stale Elements
**BAD:** Find element, page changes, click fails with `StaleElementReferenceException`.
**GOOD:** Each handler re-finds elements after waits. `safe_eval()` re-executes JS each time.

### 3. Ignoring Error Context
**BAD:** `except Exception: pass` — loses all diagnostic info.
**GOOD:** Every exception logged with URL, action, elapsed time. `debug_shot()` captures page state.

### 4. Hardcoding Values
**BAD:** `TIMEOUT = 30` everywhere.
**GOOD:** Named constants (`GH_TIMEOUT`, `GIT_TIMEOUT`, `LOG_MAX_LINES`), environment variables (`AUTOMATION_HARD_TIMEOUT`), adaptive timeouts that adjust based on observed behavior.

### 5. Not Cleaning Up
**BAD:** Driver quits only on happy path. Exception leaves Chrome process orphaned.
**GOOD:** `try/finally` in `main()` ensures `driver.quit()`. Signal handler (`_signal_handler`) catches SIGTERM.

### 6. Assuming Page Structure is Constant
**BAD:** Hardcoded CSS selectors `#main > div:nth-child(3) > a`.
**GOOD:** Behavioral detection (`fingerprint_page()`). Multiple selector strategies per template. Raw HTML fallback when DOM is empty.

### 7. Rotating Proxies Mid-Session
**BAD:** New proxy every request. Creates inconsistent state.
**GOOD:** One IP per session. Test once, use throughout. Workflow-level retry handles bad proxies.

### 8. Fighting the Page
**BAD:** `driver.execute_script("document.getElementById('btn').click()")` before page is ready.
**GOOD:** Wait for elements to appear naturally. Follow `learn_more.php` redirects instead of navigating manually. Let VPLink JS execute before interacting.

---

## Quick Start Checklist

- [x] Choose stack (Selenium + Python + ChromeDriver)
- [x] Set up proxy system (one IP per session, Supabase pool, blacklist)
- [x] Implement waiting strategy (explicit waits + PageMonitor MutationObserver)
- [x] Add anti-detection (stealth JS, human behavior, keyboard-only scrolling)
- [x] Set up logging (timestamped `log()` with elapsed time + debug shots)
- [x] Add error handling (retry, fallback escalation, circuit breakers)
- [x] Set up monitoring (funnel stats, JS health detection, proxy failure reporting)
- [x] Schedule execution (GitHub Actions + relay dispatch `if: always()`)
- [x] Test full flow end-to-end (CDP recording verified: 315 steps, 18 clicks)
- [x] Document automation (AUTOMATION.md + AGENTS.md)

---

## File Reference

| File | Purpose |
|------|---------|
| `automation.py` | Main automation engine (~3505 lines) — all template handlers, PageMonitor, flow logic |
| `proxy_rotator.py` | Proxy pool management — fetch, test, rotate, blacklist |
| `profile_generator.py` | Browser profile generation — viewport, UA, stealth properties |
| `config.py` | Configuration — Supabase, proxy settings |
| `continuous.yml` | GitHub Actions workflow — proxy retry, relay dispatch, destination capture |
| `tui.py` | Interactive Python TUI — deploy, monitor, manage (zero dependencies) |
