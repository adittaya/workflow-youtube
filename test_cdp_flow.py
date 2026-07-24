#!/usr/bin/env python3
"""
VPLink Automation — CDP-Exact Flow Script
==========================================
Replicates the EXACT sequence from the vplink111.json CDP recording:
  vplink.in/ekor0 → darkguruji(TP) → learn_more → darkguruji(TP)
  → learn_more → srtak(CE) → article → srtak(LINK1S) → learn_more(500)
  → recovery → getlink → liteapks.com

CDP Flow Reference (543 steps, 22 clicks, 259 scroll keys):
  Step  3: Click "click here" → darkguruji.com article
  Step  4: Close #block-cont-1 overlay
  Step  5: Click #continueBtn ("CONTINUE ➜")
  Step  6: Click #gcont (Google ad)
  Step  7: Close iframe #close-button (SafeFrame)
  Step  8: Close iframe #close-ad-button ("CLOSE")
  Steps 9-80: 36 PageDown scrolls
  Step 81: Click #tp-snp2 → learn_more.php
  Step 82: Close #block-cont-1
  Step 85: Click #continueBtn
  Steps 86-145: scroll keys
  Step 146: Click #tp-snp2 → learn_more.php → srtak.com
  Step 179: Close #block-cont-1
  Step 192: Click #btn6 ("Verify")
  Steps 193-278: scroll keys
  Step 279: Click #btn7 > button ("Continue") → new article
  Step 280: Close #block-cont-1
  Step 291: Click #startCountdownBtn ("click to verify")
  Step 300: Click #post-2500 > div
  Steps 301-354: scroll keys
  Step 355: Click #cross-snp2 → learn_more.php [500 ERROR]
  Steps 356-441: scroll keys (recovery)
  Step 442: Click body (dismiss popup)
  Step 445: Click body → navigate
  Steps 446-527: scroll keys
  Step 528: Click body > div.container > div
  Steps 541-542: Click #get-link TWICE → liteapks.com

Usage:
  python3 test_cdp_flow.py <key>
  VPLINK_PROXY=ip:port python3 test_cdp_flow.py <key>
  VPLINK_DEBUG=1 python3 test_cdp_flow.py <key>
"""

import json
import os
import random
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
import selenium.webdriver.support.expected_conditions as EC

try:
    from profile_generator import generate_profile
except ImportError:
    generate_profile = None

# ── Config ──
KEY = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("VPLINK_KEY", "")
if not KEY:
    print("Usage: python3 test_cdp_flow.py <key>", file=sys.stderr)
    sys.exit(1)

if KEY.startswith("http"):
    parsed = urlparse(KEY)
    KEY = parsed.path.lstrip("/").split("?")[0].split("#")[0]

BASE_DOMAIN = "vplink.in"
START_URL = f"https://{BASE_DOMAIN}/{KEY}"
PROXY = os.environ.get("VPLINK_PROXY", "")
DEBUG = "--vplink-debug" in sys.argv or os.environ.get("VPLINK_DEBUG") == "1"
AUTOMATION_HARD_TIMEOUT = 600

driver = None
destination_url = None
profile = None


# ══════════════════════════════════════════════════════════════
#  Utilities
# ══════════════════════════════════════════════════════════════

def log(msg):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def ms(t):
    time.sleep(t / 1000.0)


def rand(a, b):
    return random.randint(a, b)


def safe_url():
    try:
        return driver.current_url
    except Exception:
        return ""


def safe_eval(script, *args):
    try:
        return driver.execute_script(script, *args)
    except Exception:
        return None


def debug_shot(label):
    if not DEBUG:
        return
    d = Path(__file__).parent / "screenshots"
    d.mkdir(exist_ok=True)
    try:
        driver.save_screenshot(str(d / f"{label}.png"))
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════
#  Human Behavior Simulation
# ══════════════════════════════════════════════════════════════

def human_delay(min_ms, max_ms):
    ms(rand(min_ms, max_ms))


def bezier_move(from_x, from_y, to_x, to_y):
    steps = rand(15, 35)
    cp1x = from_x + (to_x - from_x) * 0.3 + (random.random() - 0.5) * 80
    cp1y = from_y + (to_y - from_y) * 0.3 + (random.random() - 0.5) * 80
    cp2x = from_x + (to_x - from_x) * 0.7 + (random.random() - 0.5) * 60
    cp2y = from_y + (to_y - from_y) * 0.7 + (random.random() - 0.5) * 60
    prev_x, prev_y = from_x, from_y
    try:
        for i in range(1, steps + 1):
            t = i / steps
            t2 = t * t
            t3 = t2 * t
            mt = 1 - t
            mt2 = mt * mt
            mt3 = mt2 * mt
            x = mt3 * from_x + 3 * mt2 * t * cp1x + 3 * mt * t2 * cp2x + t3 * to_x
            y = mt3 * from_y + 3 * mt2 * t * cp1y + 3 * mt * t2 * cp2y + t3 * to_y
            dx, dy = int(x - prev_x), int(y - prev_y)
            if dx or dy:
                ActionChains(driver).move_by_offset(dx, dy).perform()
            prev_x, prev_y = x, y
            ms(rand(5, 20))
    except Exception:
        pass


def human_mouse_move(selector):
    try:
        el = driver.find_element(By.CSS_SELECTOR, selector)
        loc = el.location
        sz = el.size
        vp = profile["viewport"]
        x = loc["x"] + sz["width"] * (0.3 + random.random() * 0.4)
        y = loc["y"] + sz["height"] * (0.3 + random.random() * 0.4)
        from_x = rand(100, vp["width"] - 100)
        from_y = rand(100, vp["height"] - 100)
        bezier_move(from_x, from_y, int(x), int(y))
        human_delay(100, 300)
    except Exception:
        pass


def human_click(selector):
    human_mouse_move(selector)
    human_delay(200, 500)
    try:
        el = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
        )
        el.click()
        return True
    except Exception:
        try:
            return safe_eval(f"""
                var el = document.querySelector({json.dumps(selector)});
                if (!el) return false;
                el.scrollIntoView({{block: 'center', behavior: 'smooth'}});
                el.click();
                return true;
            """)
        except Exception:
            return False


def human_read(duration_sec=45, known_height=0):
    """CDP-exact scrolling: mix of PageDown and ArrowDown with occasional ArrowUp."""
    dur = min(duration_sec or 45, 70)
    read_start = time.time()
    start_url = safe_url()

    try:
        max_scroll = safe_eval("document.documentElement.scrollHeight - window.innerHeight") or 0
    except Exception:
        max_scroll = 0
    if max_scroll < 200 and known_height > 200:
        max_scroll = known_height
    log(f"human read: {dur}s, page height={max_scroll}px")

    if max_scroll < 200:
        log("page too small, quick scroll only")
        for _ in range(3):
            ms(1000)
        return

    try:
        current_y = 0
        iterations = rand(12, 20)
        for i in range(iterations):
            if time.time() - read_start >= dur:
                break
            if safe_url() != start_url:
                log("human read: page navigated, stopping")
                break

            scroll_amt = -rand(50, 200) if random.random() < 0.2 else rand(200, 600)
            current_y = max(0, min(max_scroll or 5000, current_y + scroll_amt))
            try:
                safe_eval(f"window.scrollBy(0, {scroll_amt})")
            except Exception:
                ms(rand(1000, 3000))
                continue

            vp_w = profile["viewport"]["width"]
            vp_h = profile["viewport"]["height"]
            mx = rand(100, vp_w - 100)
            my = rand(100, vp_h - 100)
            try:
                ActionChains(driver).move_by_offset(mx - vp_w // 2, my - vp_h // 2).pause(random.uniform(0.1, 0.3)).move_by_offset(-(mx - vp_w // 2), -(my - vp_h // 2)).perform()
            except Exception:
                ms(rand(1000, 3000))
                continue

            if random.random() < 0.2:
                safe_eval("""
                    var el = document.elementFromPoint(Math.random() * window.innerWidth, Math.random() * window.innerHeight);
                    if (el) el.dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
                """)

            pause = rand(3000, 7000)
            ms(pause)

            if random.random() < 0.15:
                try:
                    safe_eval(f"window.scrollBy(0, -{rand(100, 300)})")
                except Exception:
                    pass
                ms(rand(1000, 2500))
    except Exception:
        log(f"human_read exception: {sys.exc_info()[1]}")


def human_pagedown(count=36):
    """CDP-exact: straight PageDown key presses like the real user."""
    log(f"PageDown x{count}")
    for i in range(count):
        try:
            ActionChains(driver).send_keys(Keys.PAGE_DOWN).perform()
        except Exception:
            try:
                safe_eval("window.scrollBy(0, window.innerHeight)")
            except Exception:
                pass
        ms(rand(400, 900))


def human_scroll_mixed(page_downs=30, arrow_downs=10, arrow_ups=3):
    """CDP-exact: mixed scroll pattern like real user (Phase 4 had this mix)."""
    total = page_downs + arrow_downs + arrow_ups
    log(f"mixed scroll: {page_downs} PageDown, {arrow_downs} ArrowDown, {arrow_ups} ArrowUp")
    keys = (
        [("PageDown", 1)] * page_downs
        + [("ArrowDown", 1)] * arrow_downs
        + [("ArrowUp", -1)] * arrow_ups
    )
    random.shuffle(keys)
    for key, direction in keys:
        try:
            if key == "PageDown":
                ActionChains(driver).send_keys(Keys.PAGE_DOWN).perform()
            elif key == "ArrowDown":
                ActionChains(driver).send_keys(Keys.ARROW_DOWN).perform()
            elif key == "ArrowUp":
                ActionChains(driver).send_keys(Keys.ARROW_UP).perform()
        except Exception:
            try:
                safe_eval(f"window.scrollBy(0, {direction * 300})")
            except Exception:
                pass
        ms(rand(300, 800))


# ══════════════════════════════════════════════════════════════
#  Ad Handling (CDP-Exact)
# ══════════════════════════════════════════════════════════════

def close_block_cont_1():
    """Close #block-cont-1 overlay (X button) — CDP step 4, 82, 179, 280."""
    closed = safe_eval("""
        var container = document.getElementById('block-cont-1');
        if (container && getComputedStyle(container).display !== 'none') {
            var closeDiv = container.querySelector('div');
            if (closeDiv && closeDiv.textContent.trim() === 'X') {
                var style = getComputedStyle(closeDiv);
                if (style.display !== 'none' && style.visibility !== 'hidden') {
                    closeDiv.click();
                    return 'block-cont-1';
                }
            }
        }
        return false;
    """)
    if closed:
        log(f"closed overlay: {closed}")
        human_delay(300, 800)
    return bool(closed)


def close_continue_btn():
    """Click #continueBtn ("CONTINUE ➜") — CDP step 5, 85."""
    visible = safe_eval("""
        var el = document.getElementById('continueBtn');
        if (!el) return false;
        var style = getComputedStyle(el);
        return style.display !== 'none' && style.visibility !== 'hidden' && el.getClientRects().length > 0;
    """)
    if visible:
        log("clicking #continueBtn")
        try:
            el = driver.find_element(By.ID, "continueBtn")
            driver.execute_script("arguments[0].click();", el)
        except Exception:
            human_click("#continueBtn")
        human_delay(500, 1500)
        return True
    return False


def close_gcont():
    """Close #gcont Google ad overlay — CDP step 6."""
    visible = safe_eval("""
        var el = document.getElementById('gcont');
        if (!el) return false;
        var style = getComputedStyle(el);
        return style.position === 'fixed' && style.display !== 'none' && el.getClientRects().length > 0;
    """)
    if visible:
        log("clicking #gcont overlay")
        gcont_clicked = safe_eval("""
            var svg = document.querySelector('#gcont .bgcount svg');
            if (svg) { svg.click(); return 'svg-close'; }
            var gcont = document.getElementById('gcont');
            if (gcont) { gcont.click(); return 'gcont-click'; }
            return false;
        """)
        if gcont_clicked:
            log(f"closed gcont: {gcont_clicked}")
        human_delay(500, 1000)
        return True
    return False


def close_iframe_ads():
    """Close SafeFrame iframe ads — CDP steps 7-8. NEW: handles iframe close buttons."""
    closed_any = False

    # Try to find and click close buttons inside iframes
    iframes = safe_eval("""
        var iframes = document.querySelectorAll('iframe');
        var results = [];
        for (var i = 0; i < iframes.length; i++) {
            try {
                var doc = iframes[i].contentDocument || iframes[i].contentWindow.document;
                if (!doc) continue;
                var closeBtn = doc.getElementById('close-button') || doc.getElementById('close-ad-button');
                if (closeBtn) {
                    results.push({
                        src: iframes[i].src || '',
                        hasCloseButton: true
                    });
                }
            } catch(e) {
                // cross-origin iframe
                if (iframes[i].src && iframes[i].src.indexOf('safeframe') >= 0) {
                    results.push({
                        src: iframes[i].src || '',
                        safeframe: true
                    });
                }
            }
        }
        return results;
    """)

    if iframes:
        log(f"found {len(iframes)} iframe(s) with potential close buttons")

        # For cross-origin iframes (SafeFrame), we can't access contentDocument
        # but we can try clicking the iframe element itself or using CDP
        for iframe_info in iframes:
            src = iframe_info.get("src", "")
            if "safeframe" in src or "googlesyndication" in src:
                log(f"SafeFrame ad iframe detected: {src[:80]}")
                # Try clicking the iframe element to bring it to focus, then press Escape
                try:
                    iframe_el = driver.find_element(By.CSS_SELECTOR, f'iframe[src*="safeframe"]')
                    driver.execute_script("arguments[0].click();", iframe_el)
                    ms(200)
                    ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                    ms(500)
                    closed_any = True
                    log("pressed Escape on SafeFrame iframe")
                except Exception:
                    pass

        # Also try: click any visible close buttons via JavaScript in main frame
        # Some ad close buttons are actually in the main DOM despite appearing in iframes
        js_close = safe_eval("""
            var closeSelectors = [
                '#close-button > div',
                '#close-ad-button',
                '#close-button',
                '[id*="close"] > div',
                '[id*="close-ad"]'
            ];
            for (var s = 0; s < closeSelectors.length; s++) {
                var els = document.querySelectorAll(closeSelectors[s]);
                for (var i = 0; i < els.length; i++) {
                    var style = getComputedStyle(els[i]);
                    if (style.display !== 'none' && style.visibility !== 'hidden' && els[i].offsetParent !== null) {
                        els[i].click();
                        return closeSelectors[s];
                    }
                }
            }
            return false;
        """)
        if js_close:
            log(f"closed ad via JS: {js_close}")
            closed_any = True
            human_delay(300, 800)

    return closed_any


def dismiss_popups():
    """Click body to dismiss any remaining popups — CDP steps 442, 445."""
    safe_eval("document.body.click();")
    ms(500)


def close_all_ads():
    """CDP-exact ad dismissal sequence: block-cont-1 → continueBtn → gcont → iframes."""
    close_block_cont_1()
    close_continue_btn()
    close_gcont()
    close_iframe_ads()


def get_countdown():
    """Get remaining countdown value from page."""
    return safe_eval("""
        var el = document.getElementById('tp-time') || document.getElementById('ce-time')
            || document.getElementById('link1s-time');
        if (!el) return -1;
        var txt = el.textContent.trim();
        var m = txt.match(/(\\d+)/);
        return m ? parseInt(m[1]) : -1;
    """) or -1


# ══════════════════════════════════════════════════════════════
#  Template Detection
# ══════════════════════════════════════════════════════════════

def detect_template():
    """Detect which VPLink template is active."""
    return safe_eval("""
        if (document.getElementById('tp-snp2') || document.getElementById('tp-time')) return 'tp';
        if (document.getElementById('btn6') || document.getElementById('btn7')) return 'ce';
        if (document.getElementById('startCountdownBtn') || document.getElementById('cross-snp2')) return 'link1s';
        if (document.getElementById('get-link')) return 'getlink';
        return 'unknown';
    """) or "unknown"


# ══════════════════════════════════════════════════════════════
#  CDP-Exact Flow Phases
# ══════════════════════════════════════════════════════════════

def phase_vplink_guard():
    """CDP Steps 3: Click 'click here' on vplink.in guard page."""
    log("Phase: vplink.in guard page — clicking 'click here'")
    debug_shot("guard-page")

    # CDP Step 3: Click "click here" link
    clicked = safe_eval("""
        var links = document.querySelectorAll('a');
        for (var i = 0; i < links.length; i++) {
            var txt = links[i].textContent.trim().toLowerCase();
            if (txt.indexOf('click here') >= 0 || txt.indexOf('click') >= 0) {
                links[i].click();
                return true;
            }
        }
        return false;
    """)
    if not clicked:
        human_click("a")
    log("clicked 'click here' link")
    human_delay(3000, 6000)


def phase_article(template="tp"):
    """CDP-exact article page handling.
    
    Real user order (every article page):
      1. Close #block-cont-1 overlay
      2. Click #continueBtn ("CONTINUE ➜")
      3. Close #gcont (Google ad)
      4. Close iframe ads
      5. human_read (scroll)
      6. Click template button
    """
    log(f"Phase: article page (template={template})")
    debug_shot(f"article-{template}-start")

    # Steps 4-8: Close all ads BEFORE reading (CDP-exact order)
    close_all_ads()

    # Steps 9-80: human_read scrolling
    if template == "tp":
        human_read(30, known_height=safe_eval("document.documentElement.scrollHeight") or 0)
    elif template == "ce":
        human_read(35, known_height=safe_eval("document.documentElement.scrollHeight") or 0)
    elif template == "link1s":
        human_read(25, known_height=safe_eval("document.documentElement.scrollHeight") or 0)
    else:
        human_read(35, known_height=safe_eval("document.documentElement.scrollHeight") or 0)

    # Step 6: Click template button
    if template == "tp":
        return handle_tp()
    elif template == "ce":
        return handle_ce()
    elif template == "link1s":
        return handle_link1s()
    return False


def handle_tp():
    """CDP Step 81: Click #tp-snp2 → learn_more.php."""
    log("TP: waiting for #tp-snp2")
    for w in range(60):
        visible = safe_eval("""
            var el = document.getElementById('tp-snp2');
            if (!el) return false;
            var style = getComputedStyle(el);
            return style.display !== 'none' && style.visibility !== 'hidden' && el.offsetParent !== null;
        """)
        if visible:
            log(f"tp-snp2 visible after {w}s")

            # Fast path: navigate via parent <a href> (CDP shows it has learn_more.php)
            a_href = safe_eval("""
                var snp2 = document.getElementById('tp-snp2');
                var a = snp2 ? snp2.closest('a') : null;
                if (a && a.href && a.href.indexOf('learn_more.php') >= 0) {
                    window.location.href = a.href;
                    return a.href;
                }
                return '';
            """)
            if a_href:
                log(f"navigated via tp-snp2 href: {a_href[:80]}")
                return True

            # Click tp-snp2 (CDP step 81)
            close_ad_overlay()
            close_continue_btn()
            close_gcont()
            human_click("#tp-snp2")
            log("clicked #tp-snp2")
            human_delay(3000, 6000)

            # Check if navigated
            cur = safe_url()
            if "learn_more" in cur or "vplink.in" not in cur:
                log(f"navigated to: {cur[:80]}")
                return True

            # Fallback: navigate to learn_more.php
            safe_eval("window.location.href = 'learn_more.php';")
            return True

        if w % 10 == 0 and w > 0:
            cd = get_countdown()
            log(f"[TP wait {w}s] tp-snp2 not visible, countdown={cd}")
            close_block_cont_1()
        ms(1000)

    # Fallback
    log("tp-snp2 never appeared, trying learn_more.php")
    safe_eval("window.location.href = 'learn_more.php';")
    return True


def handle_ce():
    """CDP Steps 192, 279: Click #btn6 (Verify) then #btn7 (Continue)."""
    log("CE: waiting for #btn6")
    btn6_visible = False
    for w in range(60):
        btn6_visible = safe_eval("""
            var el = document.getElementById('btn6');
            if (!el) return false;
            var style = getComputedStyle(el);
            return style.display !== 'none' && style.visibility !== 'hidden' && el.getClientRects().length > 0;
        """)
        if btn6_visible:
            break
        if w % 10 == 0 and w > 0:
            close_block_cont_1()
        ms(1000)

    if btn6_visible:
        log("btn6 visible, clicking (Verify)")
        close_ad_overlay()
        human_click("#btn6")
        log("clicked #btn6")
        human_delay(3000, 6000)

    # Wait for btn7 (CDP step 279)
    log("CE: waiting for #btn7")
    for w in range(60):
        btn7_vis = safe_eval("""
            var el = document.querySelector('#btn7 > button');
            if (!el) {
                el = document.getElementById('btn7');
                if (!el) return false;
                var style = getComputedStyle(el);
                return style.display !== 'none' && el.getClientRects().length > 0;
            }
            var style = getComputedStyle(el);
            return style.display !== 'none' && style.visibility !== 'hidden' && el.getClientRects().length > 0;
        """)
        if btn7_vis:
            log(f"btn7 visible after {w}s, clicking (Continue)")
            human_click("#btn7 > button") or human_click("#btn7")
            log("clicked #btn7")
            human_delay(3000, 6000)
            return True
        if w % 10 == 0 and w > 0:
            close_block_cont_1()
        ms(1000)

    log("btn7 never appeared")
    return False


def handle_link1s():
    """CDP Steps 291, 300, 355: startCountdownBtn → post-2500 → cross-snp2."""
    log("LINK1S: clicking #startCountdownBtn")
    close_ad_overlay()

    # CDP Step 291
    human_click("#startCountdownBtn")
    log("clicked #startCountdownBtn")
    human_delay(1000, 2000)

    # CDP Step 300: Click #post-2500 > div (NEW element from CDP recording)
    safe_eval("""
        var el = document.getElementById('post-2500');
        if (el) {
            var div = el.querySelector('div');
            if (div) div.click();
        }
    """)
    log("clicked #post-2500 > div")
    human_delay(500, 1000)

    # Wait for countdown, then click cross-snp2 (CDP step 355)
    log("LINK1S: waiting for #cross-snp2")
    for w in range(60):
        visible = safe_eval("""
            var el = document.getElementById('cross-snp2');
            if (!el) return false;
            var style = getComputedStyle(el);
            return style.display !== 'none' && style.visibility !== 'hidden' && el.getClientRects().length > 0;
        """)
        if visible:
            log(f"cross-snp2 visible after {w}s")

            # Navigate via parent <a href>
            a_href = safe_eval("""
                var a = document.querySelector('#cross-snp2');
                if (!a) return '';
                var el = a;
                while (el && el.tagName !== 'A') el = el.parentElement;
                if (el && el.href && el.href.indexOf('learn_more.php') >= 0) {
                    window.location.href = el.href;
                    return el.href;
                }
                a.click();
                return '';
            """)
            if a_href:
                log(f"navigated via cross-snp2 href: {a_href[:80]}")
            else:
                log("clicked #cross-snp2")
            return True

        if w % 10 == 0:
            cd = get_countdown()
            log(f"[LINK1S wait {w}s] cross-snp2 not visible, countdown={cd}")
        ms(1000)

    # Fallback
    log("cross-snp2 never appeared, trying learn_more.php")
    safe_eval("window.location.href = 'learn_more.php';")
    return True


def handle_getlink():
    """CDP Steps 541-542: Click #get-link TWICE (real user double-clicks)."""
    log("GETLINK: handling #get-link")
    debug_shot("getlink-start")

    # Wait for get-link to appear
    for w in range(30):
        has_gl = safe_eval("return !!document.getElementById('get-link');")
        if has_gl:
            break
        ms(1000)

    if not has_gl:
        log("get-link never appeared")
        return False

    # Wait for countdown to finish
    log("waiting for get-link countdown...")
    for w in range(50):
        ready = safe_eval("""
            var el = document.getElementById('get-link');
            if (!el) return false;
            var gt = document.getElementById('gt-link');
            if (gt && gt.href && gt.href.indexOf('http') === 0) return true;
            if (el && !el.classList.contains('disabled')) {
                var h = el.href || '';
                if (h.indexOf('http') === 0 && h.indexOf('void') < 0) return true;
            }
            return false;
        """)
        if ready:
            log(f"get-link ready after {w}s")
            break
        ms(1000)

    ms(500)

    # Fast path: extract from parent <a> href
    fast_dest = safe_eval("""
        var btn = document.getElementById('get-link');
        if (!btn) return '';
        var el = btn;
        while (el && el.tagName !== 'A') el = el.parentElement;
        if (el && el.href && el.href.indexOf('http') === 0 && el.href.indexOf('void') < 0) {
            return el.href;
        }
        return '';
    """) or ""
    if fast_dest:
        log(f"destination (parent <a> href): {fast_dest[:120]}")
        return True

    # CDP Steps 541-542: Click #get-link (real user clicks TWICE)
    human_delay(800, 2000)
    human_mouse_move("#get-link")
    human_delay(300, 700)

    log("clicking #get-link (1st click)")
    human_click("#get-link")
    ms(2000)

    # Check for new tab
    pre_handles = set(driver.window_handles)
    for _ in range(15):
        ms(1000)
        cur_handles = set(driver.window_handles)
        diff = cur_handles - pre_handles
        if diff:
            new_tab = diff.pop()
            log("new tab opened from 1st click")
            driver.switch_to.window(new_tab)
            ms(3000)
            final_url = safe_url()
            if final_url and "about:blank" not in final_url:
                log(f"destination (new tab): {final_url[:120]}")
                try:
                    driver.close()
                    driver.switch_to.window(driver.window_handles[0])
                except Exception:
                    pass
                return True
            try:
                driver.close()
                driver.switch_to.window(driver.window_handles[0])
            except Exception:
                pass
            break

    # CDP Step 542: Second click (real user clicks twice)
    log("clicking #get-link (2nd click)")
    human_click("#get-link")
    ms(2000)

    # Check for new tab again
    pre_handles = set(driver.window_handles)
    for _ in range(15):
        ms(1000)
        cur_handles = set(driver.window_handles)
        diff = cur_handles - pre_handles
        if diff:
            new_tab = diff.pop()
            log("new tab opened from 2nd click")
            driver.switch_to.window(new_tab)
            ms(3000)
            final_url = safe_url()
            if final_url and "about:blank" not in final_url:
                log(f"destination (new tab): {final_url[:120]}")
                try:
                    driver.close()
                    driver.switch_to.window(driver.window_handles[0])
                except Exception:
                    pass
                return True
            try:
                driver.close()
                driver.switch_to.window(driver.window_handles[0])
            except Exception:
                pass
            break

    # Fallbacks
    get_link_href = safe_eval("""
        var el = document.getElementById('get-link');
        return el ? el.href : '';
    """) or ""
    if get_link_href.startswith("http") and "void" not in get_link_href:
        log(f"destination (get-link href): {get_link_href[:100]}")
        return True

    gt_href = safe_eval("var gt = document.getElementById('gt-link'); return gt ? gt.href : '';") or ""
    if gt_href.startswith("http"):
        log(f"destination (gt-link href): {gt_href[:100]}")
        return True

    log("get-link: no destination found")
    return False


def close_ad_overlay():
    """Close #block-cont-1 overlay."""
    return close_block_cont_1()


# ══════════════════════════════════════════════════════════════
#  Chrome Driver Setup
# ══════════════════════════════════════════════════════════════

def create_driver():
    global driver, profile

    if generate_profile:
        profile = generate_profile(mobile=True, youtube=True)
    else:
        profile = {
            "viewport": {"width": 390, "height": 844},
            "locale": "en-US",
            "timezone": "America/New_York",
            "hardwareConcurrency": 8,
            "deviceMemory": 8,
            "deviceScaleFactor": 3,
            "userAgent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
        }

    log(f"profile: {profile['viewport']['width']}x{profile['viewport']['height']} {profile.get('locale', 'en-US')}")

    options = Options()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-accelerated-2d-canvas")
    options.add_argument("--disable-setuid-sandbox")
    options.add_argument("--disable-automation")
    options.add_argument("--use-gl=swiftshader")
    options.add_argument("--disable-features=IsolateOrigins,site-per-process")
    options.add_argument("--window-size=390,844")

    headless = os.environ.get("VPLINK_HEADLESS") == "1"
    if headless:
        options.add_argument("--headless=new")

    # Detect Chrome binary
    import shutil
    chrome_paths = [
        "/opt/google/chrome/chrome",
        "/opt/google/chrome/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
    ]
    env_path = os.environ.get("CHROMIUM_PATH", "")
    if env_path:
        chrome_paths.insert(0, env_path)
    for name in ("google-chrome-stable", "google-chrome", "chromium-browser", "chromium"):
        which = shutil.which(name)
        if which:
            chrome_paths.insert(0, which)
    for p in chrome_paths:
        if os.path.exists(p):
            options.binary_location = p
            break

    if PROXY:
        options.add_argument(f"--proxy-server={PROXY}")

    vp = profile["viewport"]
    mobile_emu = {
        "deviceMetrics": {
            "width": vp["width"],
            "height": vp["height"],
            "deviceScaleFactor": profile.get("deviceScaleFactor", 1),
            "mobile": True,
        },
        "userAgent": profile["userAgent"],
    }
    options.add_experimental_option("mobileEmulation", mobile_emu)
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument(f"--user-agent={profile['userAgent']}")

    chromedriver_paths = [
        "/usr/bin/chromedriver",
        "/snap/bin/chromium.chromedriver",
        "/usr/lib/chromium-browser/chromedriver",
        "/usr/lib/chromium/chromedriver",
        "/usr/local/bin/chromedriver",
    ]
    driver = None
    for cpath in chromedriver_paths:
        if os.path.exists(cpath):
            try:
                service = Service(executable_path=cpath)
                driver = webdriver.Chrome(service=service, options=options)
                break
            except Exception:
                continue
    if driver is None:
        driver = webdriver.Chrome(options=options)

    driver.set_page_load_timeout(30)
    driver.implicitly_wait(0)

    # Stealth
    stealth_js = f"""
    Object.defineProperty(navigator, 'webdriver', {{get: () => undefined}});
    Object.defineProperty(navigator, 'languages', {{get: () => ['{profile.get("locale", "en-US")}']}});
    Object.defineProperty(navigator, 'plugins', {{get: () => [1, 2, 3, 4, 5]}});
    window.chrome = {{runtime: {{}}}};
    """
    try:
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": stealth_js})
    except Exception:
        pass
    driver.execute_script(stealth_js)

    log("driver created")


# ══════════════════════════════════════════════════════════════
#  Main Flow — CDP-Exact Sequence
# ══════════════════════════════════════════════════════════════

def main():
    global destination_url

    from selenium.webdriver.common.keys import Keys
    global Keys
    Keys = Keys

    create_driver()
    start_time = time.time()

    log("=" * 50)
    log(f"CDP-Exact flow test for KEY={KEY}")
    log(f"URL: {START_URL}")
    log("=" * 50)

    # Navigate to vplink.in/ekor0
    log(f"navigating to {START_URL}")
    try:
        driver.get(START_URL)
    except Exception as e:
        log(f"navigation failed: {e}")
        # Try once more
        time.sleep(2)
        try:
            driver.get(START_URL)
        except Exception:
            log("second navigation also failed")
            driver.quit()
            return

    human_delay(3000, 6000)
    log(f"landed on: {safe_url()[:100]}")
    debug_shot("01-vplink")

    # Wait for vplink.in redirect to article domain
    log("waiting for redirect from vplink.in...")
    for i in range(30):
        ms(1000)
        cur = safe_url()
        if "vplink.in" not in cur:
            log(f"redirected to: {cur[:100]}")
            break
    human_delay(2000, 4000)

    # If still on vplink.in, try clicking "click here"
    if "vplink.in" in safe_url():
        log("still on vplink.in, trying to click 'click here'")
        phase_vplink_guard()
        human_delay(3000, 6000)
        for i in range(15):
            ms(1000)
            if "vplink.in" not in safe_url():
                log(f"redirected to: {safe_url()[:100]}")
                break

    debug_shot("02-article")

    # ── Main Flow Loop ──
    # CDP recording shows: TP → TP → CE → LINK1S → getlink
    # We detect template dynamically and handle each page
    for cycle in range(20):
        elapsed = time.time() - start_time
        if elapsed >= AUTOMATION_HARD_TIMEOUT:
            log(f"HARD TIMEOUT: {elapsed:.0f}s")
            break

        cur_url = safe_url()
        log(f"[cycle {cycle+1}] {cur_url[:100]}")

        # Check if we're on vplink.in (guard page)
        if "vplink.in" in cur_url:
            has_gl = safe_eval("return !!document.getElementById('get-link');")
            if has_gl:
                log("on vplink.in with get-link — destination page")
                if handle_getlink():
                    destination_url = cur_url
                    break
            else:
                log("on vplink.in guard page, clicking 'click here'")
                phase_vplink_guard()
                human_delay(3000, 6000)
            continue

        # Check if destination page
        is_dest = safe_eval("""
            var gl = document.getElementById('get-link');
            if (gl) return 'getlink';
            return false;
        """)
        if is_dest == "getlink":
            log("destination page detected (get-link)")
            if handle_getlink():
                destination_url = safe_url()
                break
            continue

        # Detect template
        template = detect_template()
        log(f"detected template: {template}")

        if template == "unknown":
            # Wait for template to load
            log("template unknown, waiting for VPLink elements...")
            for w in range(15):
                ms(1000)
                template = detect_template()
                if template != "unknown":
                    log(f"template appeared after {w+1}s: {template}")
                    break

        if template == "unknown":
            # Check for error page or empty page
            body_len = safe_eval("return (document.body?.innerHTML || '').length") or 0
            page_title = safe_eval("return document.title") or ""
            log(f"still unknown: body_len={body_len}, title={page_title[:60]}")

            if "500" in page_title or "error" in page_title.lower():
                log("error page detected, trying to recover...")
                dismiss_popups()
                human_read(20)
                # Try navigating to learn_more.php
                safe_eval("window.location.href = 'learn_more.php';")
                human_delay(3000, 5000)
                continue

            if body_len < 100:
                log("empty page, reloading...")
                try:
                    driver.refresh()
                except Exception:
                    pass
                human_delay(3000, 5000)
                continue

            # Try clicking common buttons
            clicked = (
                human_click("#tp-snp2") or
                human_click("#btn6") or
                human_click("#startCountdownBtn") or
                human_click("#get-link") or
                human_click("a[href*='learn_more']")
            )
            if clicked:
                human_delay(3000, 5000)
                continue

            log("no action possible, navigating to vplink.in")
            try:
                driver.get(START_URL)
            except Exception:
                pass
            human_delay(3000, 5000)
            continue

        # Handle the template
        navigated = phase_article(template)

        if navigated:
            log(f"navigated from {template} page")
            human_delay(3000, 6000)

            # Check if we landed on learn_more.php (intermediate page)
            cur = safe_url()
            if "learn_more" in cur:
                log(f"on intermediate page: {cur[:80]}")
                # Wait for redirect
                for w in range(40):
                    ms(1000)
                    new_cur = safe_url()
                    if new_cur != cur and "learn_more" not in new_cur:
                        log(f"intermediate redirected to: {new_cur[:80]}")
                        break
                human_delay(2000, 4000)
            continue

        # Template handling failed
        log(f"template {template} handling failed")
        exhausted_urls = safe_eval("return document.body?.innerHTML?.length || 0") or 0
        if exhausted_urls < 100:
            log("empty page after failure, navigating to vplink.in")
            try:
                driver.get(START_URL)
            except Exception:
                pass
            human_delay(3000, 5000)
        else:
            # Try to find learn_more.php link
            lm = safe_eval("""
                var links = document.querySelectorAll('a');
                for (var i = 0; i < links.length; i++) {
                    if (links[i].href && links[i].href.indexOf('learn_more.php') >= 0) {
                        return links[i].href;
                    }
                }
                return null;
            """)
            if lm:
                log(f"found learn_more.php link: {lm[:80]}")
                try:
                    driver.get(lm)
                except Exception:
                    pass
                human_delay(3000, 5000)
            else:
                log("no learn_more.php found, navigating to vplink.in")
                try:
                    driver.get(START_URL)
                except Exception:
                    pass
                human_delay(3000, 5000)

    # ── Final Result ──
    elapsed = time.time() - start_time
    print("\n" + "=" * 50)
    if destination_url:
        print(f"  DESTINATION URL:")
        print(f"  {destination_url}")
        (Path(__file__).parent / "destination_url.txt").write_text(destination_url, "utf-8")
    else:
        print("  NO DESTINATION")
    print(f"  Elapsed: {elapsed:.0f}s / {AUTOMATION_HARD_TIMEOUT}s")
    print("=" * 50)

    ms(2000)
    try:
        driver.quit()
    except Exception:
        pass
    sys.exit(0 if destination_url else 3)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Fatal error: {error}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
        sys.exit(1)
