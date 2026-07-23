# VPLink Automation System — Guide

> A production-grade, future-proof automation engine for VPLink-type link protector funnels.
> Built to handle ANY variation — domains change, headings change, templates shuffle, but the system stays.

---

## Core Principle

**Follow the page, don't fight it.**

The page's own JavaScript is the authority. When we inject cookies to speed up timers, force-call JS functions, or manipulate DOM elements before the page is ready, things break. The simplest approach is the most reliable:

1. Load the page
2. Wait for elements to appear
3. Interact with them
4. Navigate to the next step

No tricks. No fighting. Just patience.

---

## Architecture Overview

```
vplink.in/KEY
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
│  Chain       │  Repeats until get-link page
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
- **Handler:** `handle_tp()` — waits for `tp-snp2` to become visible, clicks it

### Template B — Step (CE)
- **Elements:** `stick` (step indicator), `btn6` (Verify), `btn7` (Continue), `ce-wait1`, `ce-time`
- **Behavior:** Verify button → Continue button → learn_more.php
- **Handler:** `handle_ce()` — waits for countdown, clicks btn6, waits for btn7, clicks

### Template C — Countdown (LINK1S)
- **Elements:** `startCountdownBtn`, `link1s-wait1`, `link1s-time`, `cross-snp2`
- **Behavior:** Click verify → countdown → Continue → learn_more.php
- **Handler:** `handle_link1s()` — clicks startCountdownBtn, waits for cross-snp2

### Template D — Destination (getlink)
- **Elements:** `get-link` (button), parent `<a href>` = destination URL
- **Behavior:** Timer → get-link appears → parent `<a>` href IS the destination
- **Handler:** `do_get_link()` — reads parent `<a>` href directly

### Unknown Templates
- **Detection:** `fingerprint_page()` — behavioral fingerprinting
- **Behavior:** Detects page type by WHAT it does, not element IDs
- **Handler:** `handle_generic()` — uses `isRealButton()` JS helper to find real buttons

---

## Detection System

### Template Detection (`detect_template()`)
Checks for specific element IDs to determine which template is active:
- `tp-time` / `tp-wait1` → TP template
- `ce-time` / `ce-wait1` → CE template
- `link1s-wait1` / `startCountdownBtn` → LINK1S template
- `get-link` → Destination page

### Behavioral Fingerprinting (`fingerprint_page()`)
When template detection fails, behavioral fingerprinting kicks in:
- Detects countdown elements by `[id*="time"], [class*="timer"]`
- Detects buttons by text content and visibility
- Detects overlays, popup blockers, get-link elements
- Returns a dict with: `has_countdown`, `has_verify_btn`, `has_continue_btn`, `has_getlink`, `page_type`

**Why this is future-proof:** If VPLink renames element IDs, template detection fails, but behavioral fingerprinting still works because it detects WHAT the page DOES, not what the elements are CALLED.

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
- Every 500ms: captures countdown value, button visibility, overlays, step info
- Python polls JS event queue every 100ms
- Methods: `wait_for_event()`, `wait_for_url_change()`, `wait_for_countdown_zero()`, `wait_for_nav_button()`

**Why this is better than polling:**
- Reacts instantly to page changes
- No wasted CPU cycles on empty polls
- Captures network activity that DOM polling misses
- Detects redirects and navigation in real-time

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

### 10-Minute Hard Timeout
- `AUTOMATION_HARD_TIMEOUT = 600s` from browser start to destination
- Excludes proxy-getting time
- Prevents infinite loops

---

## Anti-Detection

### Human-Like Behavior
- `human_delay(min, max)` — random delays between actions
- `human_read(seconds)` — simulates reading time
- `human_scroll()` — random scroll patterns
- `human_mouse_move(selector)` — mouse movement before clicks
- `human_click(selector)` — click with random offset

### Browser Stealth
- Custom user agent (Chrome 127)
- Window size randomization (412x915, 414x896, etc.)
- Hardware concurrency spoofing (4-16 cores)
- Memory spoofing (4-16GB)
- Device pixel ratio randomization
- Language/locale/timezone randomization

### Ad Overlay Handling
- `close_ad_overlay()` — closes `block-cont-1` and `gcont` overlays
- `handle_popup()` — detects and handles popup blocker dialogs
- `handle_goog_rewarded()` — waits for Google rewarded ads to complete
- `check_ad_hijack()` — detects when ads redirect away from article

---

## Key Functions Reference

| Function | Purpose |
|----------|---------|
| `detect_template()` | Identifies active template (TP/CE/LINK1S/getlink/unknown) |
| `fingerprint_page()` | Behavioral fingerprinting for unknown templates |
| `handle_tp()` | Waits for tp-snp2, clicks, navigates |
| `handle_ce()` | Waits for countdown, clicks btn6→btn7 |
| `handle_link1s()` | Clicks startCountdownBtn, waits for cross-snp2 |
| `handle_generic(fp)` | Generic handler using behavioral fingerprint |
| `do_get_link()` | Extracts destination from parent `<a>` href |
| `get_countdown()` | Reads countdown timer value |
| `get_step_info()` | Extracts step progress from `#stick` |
| `navigate_learn_more()` | Finds and navigates to learn_more.php |
| `close_ad_overlay()` | Closes ad overlays |
| `handle_popup()` | Handles popup blocker dialogs |
| `PageMonitor` | Real-time DOM/network monitoring |

---

## What Makes This System Good

### 1. Domain-Agnostic
- No hardcoded article domains
- Works with any domain VPLink uses
- Handles domain changes automatically

### 2. Future-Proof
- Behavioral fingerprinting survives element ID renames
- Detects page type by behavior, not names
- Works even if VPLink changes their template system

### 3. Adaptive
- Handles any number of steps (2, 3, 4, N)
- Handles any redirect chain length (1, 2, 3, 5 hops)
- Adjusts timeouts based on observed behavior

### 4. Reliable
- Follows the page naturally — no fighting
- Waits for elements to appear before interacting
- Multiple fallback paths for each template

### 5. Observable
- PageMonitor provides real-time visibility
- Detailed logging of every action
- Step progress tracking

### 6. Simple
- 214 lines removed, 78 added in latest refactor
- Each handler does one thing: wait → click → navigate
- No complex cookie injection or JS manipulation

---

## Design Principles

1. **Follow the page** — Don't inject cookies, don't force JS, don't manipulate DOM before the page is ready
2. **Wait for elements** — Don't assume timing, wait for buttons to appear
3. **Detect by behavior** — Don't rely on element IDs, detect what the page DOES
4. **One IP per session** — Test once, use throughout
5. **Fail gracefully** — Multiple fallback paths, never get stuck
6. **Keep it simple** — Complex code breaks, simple code works

---

## File Reference

| File | Purpose |
|------|---------|
| `automation.py` | Main automation engine — all template handlers, PageMonitor, flow logic |
| `proxy_rotator.py` | Proxy pool management — fetch, test, rotate, blacklist |
| `config.py` | Configuration — Supabase, proxy settings |
| `continuous.yml` | GitHub Actions workflow — proxy retry, relay dispatch |
| `vplink247.py` | CLI tool — status, analytics, reports |
| `manager/app.py` | Web dashboard — deploy, monitor, manage |
