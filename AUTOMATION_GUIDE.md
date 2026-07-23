# Web Automation Guide — Build It Right

> A comprehensive guide for building production-grade web automation systems.
> Covers technology choices, architecture, anti-detection, proxies, monitoring, and design principles.
> Works for ANY automation — scraping, testing, monitoring, data collection, link funnels.

---

## Table of Contents

1. [Technology Stack](#technology-stack)
2. [Architecture Patterns](#architecture-patterns)
3. [Browser Automation](#browser-automation)
4. [Proxy Systems](#proxy-systems)
5. [Anti-Detection](#anti-detection)
6. [Error Handling](#error-handling)
7. [Monitoring & Observability](#monitoring--observability)
8. [Scheduling & Orchestration](#scheduling--orchestration)
9. [Design Principles](#design-principles)
10. [Common Pitfalls](#common-pitfalls)

---

## Technology Stack

### Browser Automation — Choose One

| Tool | Language | Best For | Headless | Speed |
|------|----------|----------|----------|-------|
| **Playwright** | Python/JS/TS | Modern web apps, best anti-detect | Yes | Fast |
| **Selenium** | Python/Java/JS | Legacy sites, widest support | Yes | Medium |
| **Puppeteer** | JavaScript | Chrome-only, good for CDP | Yes | Fast |
| **CDP Direct** | Any | Maximum control, custom logic | Yes | Fastest |

**Recommendation:** Playwright for new projects. Selenium if you need legacy support. CDP direct for maximum control.

### Language — Choose One

| Language | Best For | Ecosystem |
|----------|----------|-----------|
| **Python** | Quick prototyping, data processing | Rich libraries, easy to read |
| **JavaScript/TypeScript** | Node.js ecosystem, Playwright native | npm packages, async/await |
| **Go** | High performance, concurrency | Fast execution, small binaries |

**Recommendation:** Python for most automation. TypeScript if using Playwright natively.

### HTTP Clients

| Library | Language | Use Case |
|---------|----------|----------|
| `requests` | Python | Simple HTTP, no async |
| `httpx` | Python | Async HTTP, modern |
| `aiohttp` | Python | High-concurrency async |
| `fetch` / `axios` | JavaScript | Browser or Node.js |
| `got` | Node.js | Retry, timeout, streams |

### Scheduling

| Tool | Best For |
|------|----------|
| **GitHub Actions** | Free tier, cron, CI/CD |
| **Cron** | Simple server scheduling |
| **Celery** | Distributed task queues |
| **Airflow** | Complex workflow orchestration |
| **Temporal** | Durable workflow execution |

**Recommendation:** GitHub Actions for free-tier automation. Cron for simple server tasks.

---

## Architecture Patterns

### Pattern 1: Sequential Pipeline
```
Input → Step 1 → Step 2 → Step 3 → Output
```
- Simple, easy to debug
- Good for: Linear flows (login → navigate → extract)
- Bad for: High throughput, independent steps

### Pattern 2: Worker Pool
```
Input Queue → Worker 1 ─┐
                Worker 2 ─┤→ Output Queue
                Worker 3 ─┘
```
- Parallel execution, shared queue
- Good for: Scraping many pages, processing batches
- Bad for: Stateful workflows, ordered processing

### Pattern 3: State Machine
```
State A ──trigger──→ State B ──trigger──→ State C
   ↑                    │                    │
   └────────────────────┴────────────────────┘
```
- Explicit states and transitions
- Good for: Complex flows with branching, retries
- Bad for: Simple linear tasks

### Pattern 4: Event-Driven
```
Event Source → Event Bus → Handler 1
                         → Handler 2
                         → Handler 3
```
- Reactive, decoupled components
- Good for: Real-time monitoring, complex event processing
- Bad for: Simple sequential tasks

**Recommendation:** State Machine for complex flows. Sequential Pipeline for simple tasks.

---

## Browser Automation

### Core Concepts

**Always prefer the page's own behavior over fighting it.**

```python
# BAD: Fighting the page
driver.execute_script("document.getElementById('btn').click()")
time.sleep(5)

# GOOD: Following the page
WebDriverWait(driver, 30).until(
    EC.element_to_be_clickable((By.ID, "btn"))
).click()
```

### Page Load Strategy

```python
# Wait for DOM ready (fast, may miss dynamic content)
driver.set_page_load_strategy("eager")

# Wait for everything (slow, but complete)
driver.set_page_load_strategy("normal")

# Don't wait at all (fastest, handle manually)
driver.set_page_load_strategy("none")
```

**Recommendation:** Use `eager` by default. Switch to `none` when you need fine-grained control.

### Waiting Strategies

```python
# Element visible
WebDriverWait(driver, 30).until(
    EC.visibility_of_element_located((By.ID, "target"))
)

# Element clickable
WebDriverWait(driver, 30).until(
    EC.element_to_be_clickable((By.ID, "target"))
)

# URL change
WebDriverWait(driver, 30).until(
    lambda d: "expected-url" in d.current_url
)

# JavaScript condition
WebDriverWait(driver, 30).until(
    lambda d: d.execute_script("return document.readyState") == "complete"
)

# Custom condition
WebDriverWait(driver, 30).until(
    lambda d: d.find_element(By.ID, "timer").text == "0"
)
```

**Recommendation:** Always use explicit waits. Never use `time.sleep()` for synchronization.

### MutationObserver (Real-Time Detection)

Instead of polling the DOM, watch for changes:

```javascript
// Inject this into the page
const observer = new MutationObserver((mutations) => {
    mutations.forEach((mutation) => {
        // Fire event when DOM changes
        window.dispatchEvent(new CustomEvent('dom_mutation', {
            detail: {
                type: mutation.type,
                target: mutation.target.tagName,
                added: mutation.addedNodes.length,
                removed: mutation.removedNodes.length
            }
        }));
    });
});

observer.observe(document.documentElement, {
    childList: true,
    attributes: true,
    subtree: true
});
```

**Why this is better:**
- Reacts instantly to changes (no polling delay)
- No wasted CPU cycles
- Captures changes that polling misses
- Works even when elements are added/removed dynamically

### Network Interception

```python
# Playwright
page.route("**/*", lambda route: route.continue_())

# Selenium + CDP
driver.execute_cdp_cmd("Network.enable", {})
driver.execute_cdp_cmd("Network.setRequestInterception", {
    "patterns": [{"urlPattern": "*"}]
})

# CDP Direct
def on_request(params):
    # Inspect/modify requests
    pass
```

**Use cases:**
- Block ads and trackers
- Capture API responses
- Modify headers
- Simulate network conditions

---

## Proxy Systems

### Proxy Types

| Type | anonymity | speed | cost |
|------|-----------|-------|------|
| **Datacenter** | Low | Fast | Cheap |
| **Residential** | High | Medium | Expensive |
| **ISP** | High | Fast | Medium |
| **Mobile** | Highest | Slow | Most expensive |

**Recommendation:** Residential for web automation. Datacenter for testing.

### Proxy Rotation Strategy

```python
class ProxyPool:
    def __init__(self):
        self.proxies = []
        self.blacklist = set()
        self.used = {}
    
    def get_proxy(self):
        """Get one proxy, use for entire session."""
        available = [p for p in self.proxies if p not in self.blacklist]
        if not available:
            self.refresh_pool()
            available = self.proxies
        proxy = random.choice(available)
        self.used[proxy] = time.time()
        return proxy
    
    def mark_dead(self, proxy, reason):
        """Mark proxy as dead, don't use again."""
        self.blacklist.add(proxy)
        self.report_to_db(proxy, reason)
    
    def refresh_pool(self):
        """Fetch new proxies from provider."""
        pass
```

### One IP Per Session

```python
# Test proxy once
proxy = pool.get_proxy()
is_good = test_proxy(proxy)

if is_good:
    # Use same proxy for entire automation run
    run_automation(proxy)
else:
    # Get new proxy, retry
    proxy = pool.get_proxy()
    run_automation(proxy)
```

**Why:** Testing mid-session wastes time and creates inconsistent state.

### Proxy Testing

```python
def test_proxy(proxy, test_url, timeout=10):
    """Test if proxy can reach target."""
    try:
        response = requests.get(
            test_url,
            proxies={"http": proxy, "https": proxy},
            timeout=timeout
        )
        return response.status_code == 200
    except:
        return False
```

**What to test:**
- Can it connect? (TCP test)
- Can it reach the target? (HTTP test)
- Does it complete the flow? (End-to-end test)

### Blacklist Management

```python
# Track why proxies fail
FAIL_REASONS = {
    "tcp_dead": "Connection refused/timeout",
    "first_goto_hang": "Page load timeout",
    "vplink_no_redirect": "Stuck on entry page",
    "timer_stuck": "Countdown never completes",
}

# Blacklist with expiry
def mark_dead(proxy, reason, ttl_hours=24):
    blacklist[proxy] = {
        "reason": reason,
        "expires": time.time() + (ttl_hours * 3600)
    }
```

---

## Anti-Detection

### Browser Fingerprint

```python
stealth_js = """
// Override navigator properties
Object.defineProperty(navigator, 'webdriver', {get: () => false});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3]});

// Override screen properties
Object.defineProperty(screen, 'width', {get: () => 1920});
Object.defineProperty(screen, 'height', {get: () => 1080});

// Override permissions
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications' ?
    Promise.resolve({ state: Notification.permission }) :
    originalQuery(parameters)
);
"""
driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": stealth_js})
```

### Human-Like Behavior

```python
import random

def human_delay(min_ms, max_ms):
    """Random delay between actions."""
    time.sleep(random.uniform(min_ms/1000, max_ms/1000))

def human_type(element, text):
    """Type like a human — random delays between keystrokes."""
    for char in text:
        element.send_keys(char)
        time.sleep(random.uniform(0.05, 0.15))

def human_scroll():
    """Random scroll patterns."""
    scroll_amount = random.randint(100, 500)
    driver.execute_script(f"window.scrollBy(0, {scroll_amount})")
    time.sleep(random.uniform(0.5, 1.5))

def human_mouse_move(element):
    """Move mouse to element before clicking."""
    action = ActionChains(driver)
    action.move_to_element(element)
    action.pause(random.uniform(0.1, 0.3))
    action.click()
    action.perform()
```

### User Agent Rotation

```python
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/127.0.0.0 Safari/537.36",
]

def get_random_ua():
    return random.choice(USER_AGENTS)
```

### Header Spoofing

```python
headers = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}
```

### Timing Randomization

```python
# Never use fixed delays
time.sleep(5)  # BAD — predictable

# Always use randomized delays
time.sleep(random.uniform(3, 7))  # GOOD — unpredictable

# Use distribution-based delays for more natural patterns
import numpy as np
delay = np.random.exponential(scale=2)  # Most delays short, some long
```

---

## Error Handling

### Retry Strategy

```python
import time
from functools import wraps

def retry(max_attempts=3, backoff=2, exceptions=(Exception,)):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    if attempt == max_attempts - 1:
                        raise
                    wait = backoff ** attempt
                    time.sleep(wait)
            return None
        return wrapper
    return decorator

@retry(max_attempts=3, backoff=2, exceptions=(TimeoutException,))
def load_page(driver, url):
    driver.get(url)
```

### Graceful Degradation

```python
def handle_flow():
    try:
        # Try primary approach
        return primary_approach()
    except PrimaryFailed:
        try:
            # Fallback to secondary
            return secondary_approach()
        except SecondaryFailed:
            # Last resort
            return last_resort()
```

### Error Classification

```python
ERROR_TYPES = {
    "transient": ["TimeoutException", "ConnectionError", "429", "503"],
    "permanent": ["404", "403", "ElementNotIntermittentException"],
    "proxy": ["ERR_TUNNEL_CONNECTION_FAILED", "ConnectionRefused"],
    "page": ["StaleElementReferenceException", "NoSuchFrameException"],
}

def classify_error(error):
    error_str = str(error).lower()
    for category, patterns in ERROR_TYPES.items():
        for pattern in patterns:
            if pattern.lower() in error_str:
                return category
    return "unknown"
```

### Circuit Breaker

```python
class CircuitBreaker:
    def __init__(self, failure_threshold=5, recovery_timeout=60):
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.state = "closed"
        self.last_failure_time = None
    
    def call(self, func, *args, **kwargs):
        if self.state == "open":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "half-open"
            else:
                raise CircuitOpenError("Circuit is open")
        
        try:
            result = func(*args, **kwargs)
            if self.state == "half-open":
                self.state = "closed"
                self.failure_count = 0
            return result
        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()
            if self.failure_count >= self.failure_threshold:
                self.state = "open"
            raise
```

---

## Monitoring & Observability

### Structured Logging

```python
import logging
import json

class StructuredLogger:
    def __init__(self, name):
        self.logger = logging.getLogger(name)
    
    def log(self, event, data=None):
        entry = {
            "timestamp": time.time(),
            "event": event,
            "data": data or {}
        }
        self.logger.info(json.dumps(entry))

# Usage
logger = StructuredLogger("automation")
logger.log("proxy_selected", {"ip": "1.2.3.4", "port": 8080})
logger.log("page_loaded", {"url": "https://...", "load_time": 2.3})
logger.log("action_completed", {"action": "click", "selector": "#btn"})
```

### Metrics Collection

```python
class Metrics:
    def __init__(self):
        self.timers = {}
        self.counters = {}
    
    def start_timer(self, name):
        self.timers[name] = time.time()
    
    def end_timer(self, name):
        elapsed = time.time() - self.timers.pop(name, time.time())
        self.record(f"{name}_duration", elapsed)
    
    def increment(self, name, value=1):
        self.counters[name] = self.counters.get(name, 0) + value
    
    def record(self, name, value):
        # Send to Prometheus, Datadog, or local storage
        pass

# Usage
metrics = Metrics()
metrics.start_timer("page_load")
driver.get(url)
metrics.end_timer("page_load")
metrics.increment("pages_scraped")
```

### Health Checks

```python
def health_check():
    return {
        "status": "healthy",
        "proxy_pool": {
            "total": len(pool.proxies),
            "alive": len(pool.proxies) - len(pool.blacklist),
            "blacklisted": len(pool.blacklist)
        },
        "automation": {
            "last_run": last_run_time,
            "success_rate": success_rate,
            "avg_duration": avg_duration
        },
        "system": {
            "memory_usage": get_memory_usage(),
            "cpu_usage": get_cpu_usage()
        }
    }
```

### Alerting

```python
def check_and_alert(metrics):
    if metrics["success_rate"] < 0.5:
        send_alert("Success rate below 50%", severity="high")
    
    if metrics["proxy_pool"]["alive"] < 10:
        send_alert("Low proxy pool", severity="medium")
    
    if metrics["avg_duration"] > 600:
        send_alert("Average duration too high", severity="medium")
```

---

## Scheduling & Orchestration

### GitHub Actions (Free Tier)

```yaml
name: Automation
on:
  schedule:
    - cron: '0 */6 * * *'  # Every 6 hours
  workflow_dispatch:
    inputs:
      target:
        description: 'Target URL'

jobs:
  run:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: python automation.py
        env:
          PROXY: ${{ secrets.PROXY }}
```

### Cron (Simple Server)

```bash
# Run every hour
0 * * * * cd /path/to/project && python automation.py >> /var/log/automation.log 2>&1

# Run every 6 hours with lockfile
0 */6 * * * flock -n /tmp/automation.lock -c 'cd /path/to/project && python automation.py'
```

### Task Queue (Distributed)

```python
from celery import Celery

app = Celery('automation', broker='redis://localhost:6379')

@app.task
def run_automation(target):
    # Automation logic here
    pass

# Schedule
app.conf.beat_schedule = {
    'run-every-6-hours': {
        'task': 'automation.run_automation',
        'schedule': 21600,  # 6 hours
        'args': ('https://target.com',),
    },
}
```

---

## Design Principles

### 1. Follow the Page, Don't Fight It

```python
# BAD: Fighting the page
driver.execute_script("document.getElementById('btn').style.display = 'block'")
driver.execute_script("showNextProcess()")

# GOOD: Following the page
WebDriverWait(driver, 30).until(
    EC.element_to_be_clickable((By.ID, "btn"))
).click()
```

**Why:** The page's JavaScript is the authority. When you fight it, you create race conditions and broken states.

### 2. Wait for Elements, Don't Assume Timing

```python
# BAD: Assuming timing
time.sleep(5)
driver.find_element(By.ID, "btn").click()

# GOOD: Waiting for elements
WebDriverWait(driver, 30).until(
    EC.element_to_be_clickable((By.ID, "btn"))
).click()
```

**Why:** Network speed, server load, and browser performance vary. Fixed delays are unreliable.

### 3. Detect by Behavior, Not Names

```python
# BAD: Relying on element IDs
def detect_page():
    if driver.find_element(By.ID, "tp-time"):
        return "landing"
    if driver.find_element(By.ID, "ce-time"):
        return "step"

# GOOD: Detecting by behavior
def detect_page():
    has_countdown = driver.execute_script("""
        var els = document.querySelectorAll('[id*="time"], [class*="timer"]');
        return els.length > 0;
    """)
    has_continue = driver.execute_script("""
        var btns = document.querySelectorAll('button, a[role="button"]');
        for (var b of btns) {
            if (b.textContent.toLowerCase().includes('continue')) return true;
        }
        return false;
    """)
    if has_countdown and has_continue:
        return "timer_page"
```

**Why:** Element IDs change. Behavior doesn't.

### 4. Fail Gracefully, Never Get Stuck

```python
# BAD: Getting stuck
def handle_page():
    btn = driver.find_element(By.ID, "btn")  # Throws if not found
    btn.click()

# GOOD: Multiple fallback paths
def handle_page():
    try:
        # Try primary: click the button
        btn = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.ID, "btn"))
        )
        btn.click()
        return True
    except TimeoutException:
        # Fallback: find any continue button
        buttons = driver.find_elements(By.XPATH, "//button[contains(text(), 'Continue')]")
        if buttons:
            buttons[0].click()
            return True
        # Last resort: navigate directly
        driver.get("https://example.com/next")
        return True
```

**Why:** Things will fail. Have multiple paths to success.

### 5. One IP Per Session

```python
# BAD: Rotating mid-session
def run():
    for i in range(10):
        proxy = get_new_proxy()  # New proxy each iteration
        driver = create_driver(proxy)
        scrape_page(driver)

# GOOD: One proxy per session
def run():
    proxy = get_proxy()
    driver = create_driver(proxy)
    for i in range(10):
        scrape_page(driver)  # Same proxy throughout
```

**Why:** Mid-session rotation creates inconsistent state and wastes time testing.

### 6. Keep It Simple

```python
# BAD: Complex, hard to debug
def handle_page():
    result = safe_eval("""
        var a = document.getElementById('btn');
        if (a && a.tagName === 'A' && a.href) {
            var b = a.closest('div');
            if (b && b.style.display !== 'none') {
                window.location.href = a.href;
                return a.href;
            }
        }
        return false;
    """)
    if result:
        return True
    # ... 50 more lines

# GOOD: Simple, easy to understand
def handle_page():
    button = driver.find_element(By.ID, "btn")
    link = button.find_element(By.XPATH, "./..")  # Parent <a>
    href = link.get_attribute("href")
    driver.get(href)
    return True
```

**Why:** Complex code breaks in ways you can't predict. Simple code breaks in ways you can fix.

### 7. Log Everything, Debug Fast

```python
# BAD: No logging
def handle_page():
    click_button()
    wait_for_load()
    extract_data()

# GOOD: Structured logging
def handle_page():
    log("handling page", url=driver.current_url)
    
    click_start = time.time()
    click_button()
    log("button clicked", duration=time.time() - click_start)
    
    load_start = time.time()
    wait_for_load()
    log("page loaded", duration=time.time() - load_start)
    
    data = extract_data()
    log("data extracted", rows=len(data))
    
    return data
```

**Why:** When things go wrong (and they will), logs are your only clue.

### 8. Test Your Proxies, Test Your Flow

```python
# BAD: Assuming proxies work
def run():
    proxy = get_proxy()
    driver = create_driver(proxy)
    driver.get("https://target.com")  # May fail silently

# GOOD: Test before using
def run():
    proxy = get_proxy()
    if not test_proxy(proxy):
        proxy = get_proxy()  # Get another one
    
    driver = create_driver(proxy)
    driver.get("https://target.com")
    
    if "error" in driver.current_url:
        mark_proxy_dead(proxy, "page_error")
        return False
    
    return True
```

**Why:** Garbage in, garbage out. Test your inputs.

---

## Common Pitfalls

### 1. Using `time.sleep()` for Synchronization
```python
# BAD
time.sleep(5)
element = driver.find_element(By.ID, "btn")

# GOOD
element = WebDriverWait(driver, 30).until(
    EC.element_to_be_clickable((By.ID, "btn"))
)
```

### 2. Not Handling Stale Elements
```python
# BAD
element = driver.find_element(By.ID, "btn")
# ... page changes ...
element.click()  # StaleElementReferenceException

# GOOD
for _ in range(3):
    try:
        element = driver.find_element(By.ID, "btn")
        element.click()
        break
    except StaleElementReferenceException:
        time.sleep(1)
```

### 3. Ignoring Error Context
```python
# BAD
try:
    do_something()
except Exception as e:
    print(f"Error: {e}")  # No context

# GOOD
try:
    do_something()
except Exception as e:
    log("action_failed", {
        "action": "do_something",
        "error": str(e),
        "url": driver.current_url,
        "screenshot": take_screenshot()
    })
```

### 4. Hardcoding Values
```python
# BAD
TIMEOUT = 30
MAX_RETRIES = 3

# GOOD
TIMEOUT = int(os.environ.get("TIMEOUT", 30))
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", 3))
```

### 5. Not Cleaning Up
```python
# BAD
def run():
    driver = create_driver()
    driver.get(url)
    # driver.quit() never called if exception occurs

# GOOD
def run():
    driver = create_driver()
    try:
        driver.get(url)
        # ... automation logic ...
    finally:
        driver.quit()
```

### 6. Assuming Page Structure is Constant
```python
# BAD: Hardcoded selectors
element = driver.find_element(By.CSS_SELECTOR, "#main > div:nth-child(3) > a")

# GOOD: Flexible selectors
element = driver.find_element(By.XPATH, "//a[contains(@href, 'target')]")
# or
element = driver.find_element(By.CSS_SELECTOR, "a[target-page]")
```

### 7. Not Handling Popups and Alerts
```python
# BAD
driver.find_element(By.ID, "btn").click()  # May trigger popup

# GOOD
try:
    driver.find_element(By.ID, "btn").click()
    # Handle popup if it appears
    WebDriverWait(driver, 5).until(EC.alert_is_present())
    alert = driver.switch_to.alert
    alert.accept()
except NoAlertPresentException:
    pass  # No popup, continue
```

### 8. Blocking the Event Loop
```python
# BAD (in async code)
async def scrape():
    page.goto(url)
    time.sleep(5)  # Blocks entire event loop

# GOOD (in async code)
async def scrape():
    await page.goto(url)
    await page.wait_for_selector("#btn")
```

---

## Quick Start Checklist

- [ ] Choose your stack (Playwright/Selenium + Python/TypeScript)
- [ ] Set up proxy system (one IP per session, test before use)
- [ ] Implement waiting strategy (explicit waits, no sleep)
- [ ] Add anti-detection (stealth JS, human behavior, headers)
- [ ] Set up logging (structured, with context)
- [ ] Add error handling (retries, fallbacks, circuit breaker)
- [ ] Set up monitoring (metrics, health checks, alerts)
- [ ] Schedule execution (GitHub Actions, cron, or task queue)
- [ ] Test the full flow end-to-end
- [ ] Document your automation (what it does, how it works)

---

## Reference Projects

- **Playwright Python:** https://playwright.dev/python/
- **Selenium Python:** https://www.selenium.dev/documentation/
- **Undetected ChromeDriver:** https://github.com/ultrafunkamsterdam/undetected-chromedriver
- **Puppeteer Stealth:** https://github.com/nickthecook/puppeteer-extra-plugin-stealth
- **Scrapy:** https://scrapy.org/ (for large-scale scraping)
