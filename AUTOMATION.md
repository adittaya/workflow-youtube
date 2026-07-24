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

## Architecture Overview

```
vplink.in/KEY
    │
    ▼
┌─────────────┐
│  Initial     │  navigate to vplink.in/KEY
│  Redirect    │  Wait for JS redirect to article page (up to 30s)
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Article     │  detect_template() → TP / CE / LINK1S / getlink / unknown
│  Page        │  fingerprint_page() → behavioral detection (future-proof)
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Handler     │  handle_tp() / handle_ce() / handle_link1s() / handle_generic()
│  (wait+click)│  Waits for button → clicks → navigates to learn_more.php
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Redirect    │  learn_more.php → new article page
│  Chain       │  Repeats until get-link page (up to 10 steps)
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Destination │  Extract from parent <a> href of #get-link button
│  URL         │  No clicking, no new tabs, just read the href
└─────────────┘
```

---

## Template System

VPLink uses 4 templates that cycle across articles. The automation detects which template is active and handles it accordingly.

### Template A — Landing (TP)
- **Elements:** `tp-wait1`, `tp-time`, `tp-generate`, `tp-snp2`
- **Behavior:** Timer counts down → Continue button appears → Click → learn_more.php
- **Handler:** `handle_tp()` — waits for `tp-snp2` to become visible, navigates via its parent `<a>` href

### Template B — Step (CE)
- **Elements:** `stick` (step indicator), `btn6` (Verify), `btn7` (Continue), `ce-wait1`, `ce-time`
- **Behavior:** Verify button → Continue button → learn_more.php
- **Handler:** `handle_ce()` — waits for countdown, clicks btn6, waits for btn7, navigates

### Template C — Countdown (LINK1S)
- **Elements:** `startCountdownBtn`, `link1s-wait1`, `link1s-time`, `cross-snp2`
- **Behavior:** Click verify → countdown → Continue → learn_more.php
- **Handler:** `handle_link1s()` — clicks startCountdownBtn, waits for cross-snp2

### Template D — Destination (getlink)
- **Elements:** `get-link` (button), parent `<a href>` = destination URL
- **Behavior:** Timer → get-link appears → parent `<a>` href IS the destination
- **Handler:** `do_get_link()` — reads parent `<a>` href directly (fast path), falls back to new-tab follow

### Unknown Templates
- **Detection:** `fingerprint_page()` — behavioral fingerprinting
- **Behavior:** Detects page type by WHAT it does, not element IDs
- **Handler:** `handle_generic(fp)` — uses `isRealButton()` JS helper to find real buttons

---

## Detection System

### Template Detection (`detect_template()`)
Checks for specific element IDs to determine which template is active:
- `tp-time` / `tp-wait1` → TP template
- `ce-time` / `ce-wait1` → CE template
- `link1s-wait1` / `startCountdownBtn` → LINK1S template
- `get-link` → Destination page
- Otherwise → `unknown`

### Behavioral Fingerprinting (`fingerprint_page()`)
When template detection fails, behavioral fingerprinting kicks in:
- Detects countdown elements by `[id*="time"], [class*="timer"]`
- Detects buttons by text content and visibility
- Detects overlays, popup blockers, get-link elements
- Returns a dict with: `has_countdown`, `has_verify_btn`, `has_continue_btn`, `has_getlink`, `page_type`

**Why this is future-proof:** If VPLink renames element IDs, template detection fails, but behavioral fingerprinting still works because it detects WHAT the page DOES, not what the elements are CALLED.

### Helper Functions
- `has_countdown_template()` — checks for any article template elements (TP/CE/LINK1S/getlink)
- `is_article_page(url)` — True if page has template elements, not vplink.in, not destination
- `is_intermediate_page(url)` — True if URL contains `learn_more.php`
- `is_destination(url)` — True if not article/intermediate/vplink, has valid hostname, AND funnel progress > 0
- `is_ad_domain(url)` — checks against 14 known ad domains (googleadservices, doubleclick, propellerads, etc.)
- `looks_like_article_url(url)` — detects article pages by URL structure heuristics (any domain)
- `get_step_info()` — extracts step progress text from `#stick` element
- `get_countdown()` — reads countdown timer value from any template element
- `get_raw_html(max_len)` — gets raw HTML source from page, works even when JS doesn't execute
- `detect_js_health()` — comprehensive JS health check (height, body_len, element_count, vplink_elements, verdict)
- `find_learn_more_in_html()` — finds learn_more.php links in raw HTML and navigates to first one
- `extract_redirect_from_html(html)` — extracts redirect target URL from raw HTML scripts/meta refresh

---

## PageMonitor — Real-Time Detection

Instead of polling the DOM every second, PageMonitor uses:

### MutationObserver
- Watches the entire DOM for changes (childList + attributes + subtree)
- Fires `dom_mutation` events on ANY change
- No blind polling — instant reaction to page state changes

### Network Interceptors
- Intercepts `fetch()` and `XMLHttpRequest`
- Captures all network activity (requests, responses, errors)
- Detects when the page is loading new content

### Periodic State Snapshots
- Every 500ms: captures countdown value, button visibility, overlays, step info, get-link href
- Python polls JS event queue every 100ms
- Methods: `wait_for_event()`, `wait_for_url_change()`, `wait_for_countdown_zero()`, `wait_for_nav_button()`

**Why this is better than polling:**
- Reacts instantly to changes
- No wasted CPU cycles on empty polls
- Captures network activity that DOM polling misses
- Detects redirects and navigation in real-time

---

## Raw HTML Fallback — When JS Fails

VPLink JS sometimes fails to execute on article pages (page height=0, no template elements). This happens when proxies strip JS, headless Chrome is detected, or the page requires specific cookies. The raw HTML fallback system handles this case.

### How It Works
1. **Detect**: `detect_js_health()` checks page height, body_len, element count. Returns "broken" when page is empty.
2. **Parse**: `get_raw_html()` gets the page source via `document.documentElement.outerHTML` — works even when JS doesn't execute.
3. **Extract**: `find_learn_more_in_html()` regex-searches HTML for `href="...learn_more.php..."` links.
4. **Navigate**: If found, navigates to the URL via `window.location.href`.
5. **Fallback**: `extract_redirect_from_html()` searches for `window.location = '...'`, meta refresh, and external links.

### Where It's Used
- **`handle_article()`**: After page reload fails (height still < 50), tries raw HTML before giving up
- **`handle_tp()`**: After `tp-snp2` never appears, tries raw HTML for learn_more.php links
- **`handle_ce()`**: After btn7 never appears, tries raw HTML for learn_more.php links
- **`handle_link1s()`**: After cross-snp2 never appears, tries raw HTML for learn_more.php links
- **Intermediate page handler**: After learn_more.php page doesn't redirect, extracts redirect from raw HTML
- **`is_destination()`**: Checks raw HTML for VPLink elements before classifying as destination

### Why This Works
The HTML source is served by the server regardless of whether JS executes. The VPLink template HTML (with `tp-snp2`, `btn6`, `learn_more.php` links) is in the source even if the JS that makes them interactive doesn't run.

---

## Funnel Progress Tracking

The funnel progress system prevents false-positive destination detection on empty article pages.

### How It Works
- `_funnel_progress` counter tracks how many `learn_more.php` redirects we've completed
- `_funnel_progress = 0` → We haven't entered the funnel yet
- `_funnel_progress = N` → We've been through N redirects

### Where It's Updated
- Initialized to 0 at start of each proxy attempt
- Incremented when `is_intermediate_page(url)` is True (we're on learn_more.php)
- Synced to `learn_more_count` after each `handle_article()` success

### Where It's Checked
- **`is_destination()`**: Returns False if `_funnel_progress == 0` — nothing can be a destination until we've been through the funnel
- **Final stats**: Logged for debugging

### Why This Is Critical
Without this guard, empty article pages (where VPLink JS didn't execute) get classified as destinations because they have valid hostnames. The funnel progress guard ensures we only accept a destination AFTER we've actually navigated through the VPLink funnel.

---

## Proxy System

### One IP Per Session
- Test proxy once before starting
- Use that IP for ALL browser work
- No mid-session rotation — keeps the session clean
- Workflow-level retry handles bad proxies (3 attempts)

### Domain-Agnostic Testing
- Proxy test: "Can this IP get through vplink.in to any article page?"
- Checks: passed vplink.in + not on learn_more.php = works
- No hardcoded article domains — works for any domain, any heading, any future change

### Workflow Retry Logic
```
Attempt 1: Get proxy → Run automation (10min timeout)
  If ran < 120s → proxy blocked → rotate → Attempt 2
  If ran >= 120s → proxy worked → done
Attempt 2: New proxy → Run automation
Attempt 3: New proxy → Run automation
```

---

## Flow Handling

### Adaptive Step Count
- Step count is variable (2, 3, 4, N steps)
- `max_url_visits = 10` — handles up to 10 steps
- Step progress tracked via `#stick` element: "You are currently on step X/N"

### Adaptive Redirect Chains
- Redirect chains are variable (1, 2, 3, 5 hops)
- Up to 5 redirect attempts before giving up
- Checks `has_countdown_template()` to detect article pages in chain
- Thread-based URL polling catches redirects that main loop misses
- Regex extraction from page HTML as fallback for broken JS redirects

### Adaptive Timeouts
- `adpt_nav` — initial navigation timeout (default 40s)
- `adpt_load` — page load timeout (default 30s)
- `adpt_redirect` — redirect wait timeout (default 25s, hard max 30s)
- `adpt_poll` — polling timeout (default 30s)
- `adpt_getlink` — get-link page timeout (default 40s)
- All timeouts adapt based on observed behavior (fast/slow connections)

### 10-Minute Hard Timeout
- `AUTOMATION_HARD_TIMEOUT = 600s` from browser start to destination
- Excludes proxy-getting time
- Prevents infinite loops

---

## Anti-Detection

### Human-Like Behavior
- `human_delay(min_ms, max_ms)` — random delays between actions
- `human_read(seconds)` — simulates reading with scroll, mouse movement, random pauses
- `human_scroll()` — random scroll patterns (1-3 scrolls, random distances)
- `human_mouse_move(selector)` — bezier curve mouse movement to element
- `human_click(selector)` — click with random offset, falls back to JS click
- `bezier_move(x1, y1, x2, y2)` — gradual mouse movement along bezier curve (15-35 steps, 5-20ms per step)

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

### Ad Overlay Handling
- `close_ad_overlay()` — closes `block-cont-1` and `gcont` overlays
- `handle_popup()` — detects and handles popup blocker dialogs
- `handle_goog_rewarded()` — waits for Google rewarded ads to complete (up to 90s)
- `check_ad_hijack()` — detects when ads redirect away from article (checks 14 ad domains)

---

## Key Functions Reference

| Function | Purpose |
|----------|---------|
| `detect_template()` | Identifies active template (TP/CE/LINK1S/getlink/unknown) |
| `fingerprint_page()` | Behavioral fingerprinting for unknown templates |
| `handle_tp()` | Waits for tp-snp2, navigates via parent `<a>` href + raw HTML fallback |
| `handle_ce()` | Waits for countdown, clicks btn6→btn7 + raw HTML fallback |
| `handle_link1s()` | Clicks startCountdownBtn, waits for cross-snp2 + raw HTML fallback |
| `handle_generic(fp)` | Generic handler using behavioral fingerprint + isRealButton |
| `handle_unknown()` | Last resort: tries all known buttons by ID then by text |
| `do_get_link()` | Fast path: extracts destination from parent `<a>` href |
| `handle_article()` | Main article handler: detects template, dispatches to handler + raw HTML fallback |
| `get_countdown()` | Reads countdown timer value from any template |
| `get_step_info()` | Extracts step progress from `#stick` |
| `navigate_learn_more()` | Finds and navigates to learn_more.php |
| `find_learn_more_in_html()` | Finds learn_more.php links in raw HTML source (JS fallback) |
| `extract_redirect_from_html(html)` | Extracts redirect target from raw HTML scripts/meta refresh |
| `get_raw_html(max_len)` | Gets raw HTML source from page (works when JS broken) |
| `detect_js_health()` | Comprehensive JS health check (height, body_len, verdict) |
| `looks_like_article_url(url)` | Detects article pages by URL structure heuristics (any domain) |
| `close_ad_overlay()` | Closes ad overlays |
| `handle_popup()` | Handles popup blocker dialogs |
| `check_ad_hijack()` | Detects ad domain redirects, navigates back |
| `is_ad_domain(url)` | Checks URL against 14 known ad domains |
| `is_destination(url)` | Checks if URL is a valid destination (requires funnel progress > 0) |
| `is_article_page(url)` | Checks if URL has article template elements |
| `wait_for_countdown(template, max_wait)` | Waits for countdown to reach 0 |
| `bezier_move(x1, y1, x2, y2)` | Gradual mouse movement along bezier curve |
| `human_read(seconds)` | Simulates reading with scroll + mouse movement |
| `PageMonitor` | Real-time DOM/network monitoring |

---

## What Makes This System Good

### 1. Domain-Agnostic
- No hardcoded article domains
- Works with any domain VPLink uses
- Handles domain changes automatically via URL structure heuristics

### 2. Future-Proof
- Behavioral fingerprinting survives element ID renames
- Detects page type by behavior, not names
- Works even if VPLink changes their template system

### 3. Adaptive
- Handles any number of steps (2, 3, 4, N)
- Handles any redirect chain length (1, 2, 3, 5 hops)
- Adjusts timeouts based on observed behavior
- Thread-based redirect polling catches redirects main loop misses

### 4. Reliable
- Follows the page naturally — no fighting
- Waits for elements to appear before interacting
- Multiple fallback paths for each template
- Fast path destination extraction (parent `<a>` href)
- Raw HTML fallback when VPLink JS doesn't execute

### 5. Observable
- PageMonitor provides real-time visibility
- Detailed logging of every action with elapsed time
- Step progress tracking
- Destination URL printed at end
- JS health detection (healthy/degraded/broken)

### 6. Clean
- Each handler does one thing: wait → click → navigate
- No cookie injection or JS manipulation
- Ad hijack detection with 14 known ad domains
- Consistent return values (strings, not booleans)

### 7. Resilient
- Funnel progress guard prevents false-positive destination detection
- Raw HTML parsing when DOM is empty (JS broken)
- Multiple retry paths: DOM → raw HTML → reload → proxy blacklist
- Works even when proxies strip JavaScript

---

## Design Principles

1. **Follow the page** — Don't inject cookies, don't force JS, don't manipulate DOM before the page is ready
2. **Wait for elements** — Don't assume timing, wait for buttons to appear
3. **Detect by behavior** — Don't rely on element IDs, detect what the page DOES
4. **One IP per session** — Test once, use throughout
5. **Fail gracefully** — Multiple fallback paths, never get stuck
6. **Keep it simple** — Complex code breaks, simple code works
7. **Funnel progress guard** — Don't classify any page as destination until we've completed at least one funnel step (learn_more.php redirect). Prevents false-positive destination detection on empty article pages.
8. **Raw HTML fallback** — When VPLink JS doesn't execute (page height=0, no template elements), parse the raw HTML source for learn_more.php links and redirect targets. The HTML is served by the server regardless of JS execution.
9. **Domain-agnostic** — Never hardcode article domains. VPLink changes domains weekly. Use URL structure heuristics and funnel progress tracking instead.

---

## File Reference

| File | Purpose |
|------|---------|
| `automation.py` | Main automation engine — all template handlers, PageMonitor, flow logic |
| `proxy_rotator.py` | Proxy pool management — fetch, test, rotate, blacklist |
| `profile_generator.py` | Browser profile generation — viewport, UA, stealth properties |
| `config.py` | Configuration — Supabase, proxy settings |
| `continuous.yml` | GitHub Actions workflow — proxy retry, relay dispatch, destination capture |
| `tui/` | React TUI — deploy, monitor, manage (OpenTUI + Bun) |
| `manager/app.py` | Web dashboard — deploy, monitor, manage |
