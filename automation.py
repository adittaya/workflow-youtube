#!/usr/bin/env python3
import json
import os
import random
import signal
import sys
import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
import selenium.webdriver.support.expected_conditions as EC

try:
    from proxy_rotator import mark_dead, mark_proxy_used, get_proxy
except ImportError:
    mark_dead = lambda *a, **kw: False
    mark_proxy_used = lambda *a, **kw: False
    get_proxy = None

from profile_generator import generate_profile


def _check_native_binary(path: str) -> bool:
    """Check if path is a runnable binary (ELF binary or shebang script)."""
    try:
        with open(path, "rb") as f:
            header = f.read(4)
            return header in (b"\x7fELF", b"#!/u", b"#!/b", b"#!/s")
    except OSError:
        return False


def _detect_chrome_binary() -> str:
    """Find a working Chrome/Chromium binary. Always returns a string."""
    import shutil

    candidates = [
        "/opt/google/chrome/chrome",
        "/opt/google/chrome/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
    ]

    # 1. Prefer env var
    env_path = os.environ.get("CHROMIUM_PATH", "")
    if env_path:
        candidates.insert(0, env_path)

    # 2. Search PATH via shutil (same as verifier)
    for name in ("google-chrome-stable", "google-chrome", "chromium-browser", "chromium", "google-chrome-beta"):
        which = shutil.which(name)
        if which:
            candidates.insert(0, which)

    # 3. Native ELF binary first
    for p in candidates:
        if _check_native_binary(p):
            return p

    # 4. Fallback: any existing file
    for p in candidates:
        if os.path.exists(p):
            return p

    # 5. Last resort — return a reasonable default that will give a clear error
    return "/usr/bin/chromium-browser"

# ── Globals ──
BASE_DOMAIN = "vplink.in"
KEY = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("VPLINK_KEY", "")
if not KEY:
    print("Usage: python3 automation.py <key_or_url>", file=sys.stderr)
    sys.exit(1)

if KEY.startswith("http"):
    from urllib.parse import urlparse
    parsed = urlparse(KEY)
    BASE_DOMAIN = parsed.hostname or BASE_DOMAIN
    KEY = parsed.path.lstrip("/").split("?")[0].split("#")[0]

if not KEY:
    print("No key extracted from URL", file=sys.stderr)
    sys.exit(1)

START_URL = f"https://{BASE_DOMAIN}/{KEY}"
DEBUG = "--vplink-debug" in sys.argv or os.environ.get("VPLINK_DEBUG") == "1"

driver = None
destination_url = None
start_time = time.time()

PROXY = os.environ.get("VPLINK_PROXY", "")
PROXY_HOST = PROXY.replace("https://", "").replace("http://", "").split(":")[0] if PROXY else ""
PROXY_IP = PROXY_HOST
PROXY_PORT = int(PROXY.split(":")[-1]) if PROXY and ":" in PROXY.split("//")[-1] else 0

proxy_failures = 0
proxy_blocked = False
proxy_punished = False
proxy_restarts = 0
MAX_PROXY_RESTARTS = 3

TRAFFIC_SOURCE = os.environ.get("VPLINK_TRAFFIC_SOURCE", "youtube").lower()
TRAFFIC_REFERRERS = {
    "youtube": "https://www.youtube.com/",
    "google": "https://www.google.com/",
    "facebook": "https://www.facebook.com/",
    "twitter": "https://x.com/",
    "direct": "",
}
TRAFFIC_UTM = {
    "youtube": {"utm_source": "youtube", "utm_medium": "referral", "utm_campaign": "link_in_description"},
    "google": {"utm_source": "google", "utm_medium": "organic", "utm_campaign": "search"},
    "facebook": {"utm_source": "facebook", "utm_medium": "social", "utm_campaign": "post"},
    "twitter": {"utm_source": "twitter", "utm_medium": "social", "utm_campaign": "tweet"},
    "direct": {},
}


def _inject_traffic_source():
    if TRAFFIC_SOURCE not in TRAFFIC_REFERRERS:
        return
    referrer = TRAFFIC_REFERRERS[TRAFFIC_SOURCE]
    if not referrer:
        return
    referrer_js = f"""
    Object.defineProperty(document, 'referrer', {{
        get: function() {{ return '{referrer}'; }}
    }});
    """
    try:
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": referrer_js})
        driver.execute_script(referrer_js)
        log(f"traffic source: {TRAFFIC_SOURCE} referrer={referrer}")
    except Exception:
        pass


def _add_utm_to_url(url):
    if TRAFFIC_SOURCE not in TRAFFIC_UTM or not TRAFFIC_UTM[TRAFFIC_SOURCE]:
        return url
    if not url or not url.startswith("http"):
        return url
    from urllib.parse import urlparse, urlencode, parse_qs, urlunparse
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    utm = TRAFFIC_UTM[TRAFFIC_SOURCE]
    for k, v in utm.items():
        if k not in params:
            params[k] = [v]
    new_query = urlencode({k: v[0] for k, v in params.items()})
    return urlunparse(parsed._replace(query=new_query))


def _revisit_with_referrer(url):
    if TRAFFIC_SOURCE not in TRAFFIC_REFERRERS:
        return
    referrer = TRAFFIC_REFERRERS[TRAFFIC_SOURCE]
    if not referrer or not url:
        return
    try:
        driver.execute_cdp_cmd("Network.enable", {})
        driver.execute_cdp_cmd("Network.setExtraHTTPHeaders", {
            "headers": {"Referer": referrer}
        })
        log(f"re-navigating with referrer: {referrer}")
        driver.get(url)
        ms(3000)
        driver.execute_cdp_cmd("Network.setExtraHTTPHeaders", {
            "headers": {}
        })
        log(f"cleared extra headers after destination visit")
    except Exception as e:
        log(f"referrer revisit failed: {e}")


class AdaptiveTimeout:
    __slots__ = ('name', 'value', 'default', 'min_val', 'max_val', 'safety')

    def __init__(self, name, default, safety=3, min_ratio=0.25, max_ratio=10):
        self.name = name
        self.value = float(default)
        self.default = float(default)
        self.min_val = float(default * min_ratio)
        self.max_val = float(default * max_ratio)
        self.safety = float(safety)

    def get(self):
        return self.value

    def observe(self, elapsed):
        target = max(elapsed * self.safety, self.default)
        target = max(self.min_val, min(self.max_val, target))
        self.value = self.value * 0.7 + target * 0.3

    def timeout_occured(self):
        self.value = min(self.max_val, self.value * 2.0)

    def set_page_load(self, driver):
        driver.set_page_load_timeout(int(self.value * 1.2))

    def reset(self):
        self.value = self.default


adpt_nav = AdaptiveTimeout('nav', 60, safety=2)
adpt_load = AdaptiveTimeout('load', 30, safety=2)
adpt_redirect = AdaptiveTimeout('redirect', 25, safety=3)
adpt_poll = AdaptiveTimeout('poll', 30, safety=3)
adpt_getlink = AdaptiveTimeout('getlink', 50, safety=2)


def log(msg):
    elapsed = time.time() - start_time
    print(f"  [{elapsed:.1f}s] {msg}", file=sys.stderr)


def ms(t):
    time.sleep(t / 1000.0)


def rand(min_val, max_val):
    return random.randint(min_val, max_val)


def safe_url():
    try:
        return driver.current_url
    except Exception:
        return ""


def url_base(u):
    try:
        from urllib.parse import urlparse
        p = urlparse(u)
        return p.scheme + "://" + p.netloc + p.path
    except Exception:
        return (u or "").split("#")[0]


def safe_eval(script, *args):
    try:
        result = driver.execute_script(script, *args)
        return result
    except Exception:
        return None





def report_proxy_failure(reason):
    global proxy_failures, proxy_blocked, proxy_punished
    if not PROXY_IP:
        return
    proxy_failures += 1
    log(f"proxy failure #{proxy_failures}: {reason} ({PROXY_IP}:{PROXY_PORT})")
    if not proxy_punished and PROXY_PORT:
        proxy_punished = True
        try:
            mark_dead(PROXY_IP, PROXY_PORT, reason)
        except Exception:
            pass


def restart_proxy():
    global driver, PROXY, PROXY_HOST, PROXY_IP, PROXY_PORT, proxy_punished, proxy_restarts, start_time
    if proxy_restarts >= MAX_PROXY_RESTARTS:
        log(f"max proxy restarts ({MAX_PROXY_RESTARTS}) reached, giving up")
        return False
    proxy_restarts += 1
    log(f"--- restarting browser with new proxy (attempt {proxy_restarts}/{MAX_PROXY_RESTARTS}) ---")
    try:
        driver.quit()
    except Exception:
        pass
    driver = None
    proxy_punished = False
    new_proxy = None
    try:
        new_proxy = get_proxy()
    except Exception as e:
        log(f"failed to get new proxy: {e}")
    if not new_proxy:
        log("no new proxy available, continuing without proxy")
        PROXY = ""
        PROXY_HOST = ""
        PROXY_IP = ""
        PROXY_PORT = 0
    else:
        PROXY = f"http://{new_proxy['ip']}:{new_proxy['port']}"
        PROXY_HOST = new_proxy["ip"]
        PROXY_IP = new_proxy["ip"]
        PROXY_PORT = int(new_proxy["port"])
        log(f"new proxy: {PROXY_IP}:{PROXY_PORT}")
    start_time = time.time()
    try:
        _create_driver()
    except Exception as e:
        log(f"failed to create browser: {e}")
        return False
    return True


def _signal_handler(sig, frame):
    global driver
    if driver:
        try:
            driver.quit()
        except Exception:
            pass
    sys.exit(130)


signal.signal(signal.SIGINT, _signal_handler)


# ── Build stealth JS ──
def _build_stealth_js(profile):
    p = profile
    return f"""
    (function() {{
        var p = {json.dumps(p)};
        Object.defineProperty(navigator, 'webdriver', {{get: function() {{ return undefined; }} }});

        Object.defineProperty(navigator, 'plugins', {{
            get: function() {{
                var plugins = [
                    {{name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format'}},
                    {{name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: ''}},
                    {{name: 'Native Client', filename: 'internal-nacl-plugin', description: ''}}
                ];
                plugins.length = 3;
                plugins.refresh = function() {{}};
                return plugins;
            }}
        }});

        Object.defineProperty(navigator, 'languages', {{get: function() {{ return p.languages; }} }});
        Object.defineProperty(navigator, 'hardwareConcurrency', {{get: function() {{ return p.hardwareConcurrency; }} }});
        Object.defineProperty(navigator, 'deviceMemory', {{get: function() {{ return p.deviceMemory; }} }});
        Object.defineProperty(navigator, 'platform', {{get: function() {{ return p.platform; }} }});

        window.chrome = {{ runtime: {{}}, loadTimes: function() {{}}, csi: function() {{}} }};

        var origPermQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = function(params) {{
            return params.name === 'notifications'
                ? Promise.resolve({{ state: 'denied' }})
                : origPermQuery(params);
        }};

        var getParameterOrig = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(param) {{
            if (param === 37445) return p.webgl.vendor;
            if (param === 37446) return p.webgl.renderer;
            return getParameterOrig.call(this, param);
        }};
        if (typeof WebGL2RenderingContext !== 'undefined') {{
            var getParameter2Orig = WebGL2RenderingContext.prototype.getParameter;
            WebGL2RenderingContext.prototype.getParameter = function(param) {{
                if (param === 37445) return p.webgl.vendor;
                if (param === 37446) return p.webgl.renderer;
                return getParameter2Orig.call(this, param);
            }};
        }}

        var toDataURL = HTMLCanvasElement.prototype.toDataURL;
        HTMLCanvasElement.prototype.toDataURL = function(type) {{
            var ctx = this.getContext('2d');
            if (ctx) {{
                var imageData = ctx.getImageData(0, 0, Math.min(this.width, 16), Math.min(this.height, 16));
                for (var i = 0; i < imageData.data.length; i += 4) {{
                    imageData.data[i] = Math.max(0, Math.min(255, imageData.data[i] + Math.round(p.canvasNoiseSeed * 100)));
                }}
                ctx.putImageData(imageData, 0, 0);
            }}
            return toDataURL.apply(this, arguments);
        }};
        var getImageData = CanvasRenderingContext2D.prototype.getImageData;
        CanvasRenderingContext2D.prototype.getImageData = function() {{
            var imageData = getImageData.apply(this, arguments);
            for (var i = 0; i < imageData.data.length; i += 4) {{
                imageData.data[i] = Math.max(0, Math.min(255, imageData.data[i] + Math.round(p.canvasNoiseSeed * 50)));
            }}
            return imageData;
        }};

        var origGetFloat = AnalyserNode.prototype.getFloatFrequencyData;
        AnalyserNode.prototype.getFloatFrequencyData = function(arr) {{
            origGetFloat.call(this, arr);
            for (var i = 0; i < arr.length; i++) arr[i] += p.audioOffset;
        }};
        var origGetByte = AnalyserNode.prototype.getByteFrequencyData;
        AnalyserNode.prototype.getByteFrequencyData = function(arr) {{
            origGetByte.call(this, arr);
            for (var i = 0; i < arr.length; i++) arr[i] = Math.max(0, Math.min(255, arr[i] + Math.round(p.audioOffset * 1000)));
        }};

        Object.defineProperty(screen, 'width', {{get: function() {{ return p.screen.width; }} }});
        Object.defineProperty(screen, 'height', {{get: function() {{ return p.screen.height; }} }});
        Object.defineProperty(screen, 'availWidth', {{get: function() {{ return p.screen.availWidth; }} }});
        Object.defineProperty(screen, 'availHeight', {{get: function() {{ return p.screen.availHeight; }} }});
        Object.defineProperty(screen, 'colorDepth', {{get: function() {{ return p.screen.colorDepth; }} }});
        Object.defineProperty(screen, 'pixelDepth', {{get: function() {{ return p.screen.colorDepth; }} }});

        if (window.outerWidth === 0) {{
            Object.defineProperty(window, 'outerWidth', {{get: function() {{ return p.screen.availWidth; }} }});
            Object.defineProperty(window, 'outerHeight', {{get: function() {{ return p.screen.availHeight; }} }});
        }}

        if (navigator.connection) {{
            Object.defineProperty(navigator.connection, 'rtt', {{get: function() {{ return Math.round(50 + Math.random() * 100); }} }});
        }}

        Object.defineProperty(navigator, 'maxTouchPoints', {{
            get: function() {{ return p.platform.includes('Mac') ? 0 : Math.round(Math.random()); }}
        }});

        if (navigator.getBattery) {{
            navigator.getBattery = function() {{
                return Promise.resolve({{
                    charging: true, chargingTime: 0, dischargingTime: Infinity,
                    level: 0.5 + Math.random() * 0.5,
                    addEventListener: function() {{}}, removeEventListener: function() {{}}
                }});
            }};
        }}
    }})();
    """


# ══════════════════════════════════════════════════════════════
#  Human-like behavior
# ══════════════════════════════════════════════════════════════

def human_delay(min_ms, max_ms):
    ms(rand(min_ms, max_ms))


def bezier_move(from_x, from_y, to_x, to_y):
    steps = rand(15, 35)
    cp1x = from_x + (to_x - from_x) * 0.3 + (random.random() - 0.5) * 80
    cp1y = from_y + (to_y - from_y) * 0.3 + (random.random() - 0.5) * 80
    cp2x = from_x + (to_x - from_x) * 0.7 + (random.random() - 0.5) * 60
    cp2y = from_y + (to_y - from_y) * 0.7 + (random.random() - 0.5) * 60
    actions = ActionChains(driver)
    for i in range(steps + 1):
        t = i / steps
        t2 = t * t
        t3 = t2 * t
        mt = 1 - t
        mt2 = mt * mt
        mt3 = mt2 * mt
        x = mt3 * from_x + 3 * mt2 * t * cp1x + 3 * mt * t2 * cp2x + t3 * to_x
        y = mt3 * from_y + 3 * mt2 * t * cp1y + 3 * mt * t2 * cp2y + t3 * to_y
        actions.move_by_offset(int(x - from_x), int(y - from_y)) if i > 0 else None
        ms(rand(5, 20))
    try:
        actions.perform()
    except Exception:
        pass


def human_scroll():
    scrolls = rand(1, 3)
    for _ in range(scrolls):
        safe_eval(f"window.scrollBy({{top: {rand(100, 400)}, behavior: 'smooth'}})")
        human_delay(300, 800)


def human_read(duration_sec=45):
    dur = min(duration_sec or 45, 70)
    read_start = time.time()
    start_url = safe_url()
    try:
        max_scroll = safe_eval("document.documentElement.scrollHeight - window.innerHeight") or 0
    except Exception:
        max_scroll = 0
    current_y = 0
    log(f"human read: {dur}s, page height={max_scroll}px")

    if max_scroll < 200:
        log("page height too small, performing quick scroll only")
        for _ in range(3):
            ms(1000)
        return

    try:
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
                break

            vp_w = profile["viewport"]["width"]
            vp_h = profile["viewport"]["height"]
            mx = rand(100, vp_w - 100)
            my = rand(100, vp_h - 100)
            try:
                ActionChains(driver).move_by_offset(mx - vp_w // 2, my - vp_h // 2).perform()
                ActionChains(driver).move_by_offset(-(mx - vp_w // 2), -(my - vp_h // 2)).perform()
            except Exception:
                break

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

            if random.random() < 0.15:
                try:
                    ActionChains(driver).move_by_offset(rand(-30, 30), rand(-20, 20)).perform()
                except Exception:
                    pass
                ms(rand(200, 600))
    except Exception as e:
        log(f"human read error: {str(e)[:60]}")
    log(f"human read done ({int(time.time() - read_start)}s)")


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
        el = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
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


def click_text(txt):
    try:
        el = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.XPATH, f"//*[contains(text(), '{txt}')]"))
        )
        el.click()
        return True
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════
#  Destination / Ad detection
# ══════════════════════════════════════════════════════════════

DEST_PATTERNS = [
    "12indiaplay.com", "vv53243", "casino", "one-vv",
    "apkmirror.com", "play.google.com", "download", ".apk",
    "capecutapk.com", "amazingbaba.com", "ti.com", "1xbet", "whotop.cc",
]

ARTICLE_PATH_PATTERNS = [
    "/studyscholorships/", "/universitiesstudy/", "/studieseducates/",
    "/studiiessuniversitiess/", "/universitesstudiiess/", "/studiessuniversitiess/",
]

INTERMEDIATE_PATTERNS = [
    "learn_more.php", "studieseducates", "studiiessuniversitiess",
    "universitesstudiiess", "studiessuniversitiess"
]

AD_DOMAINS = ["golaso.org", "doubleclick.net", "googlesyndication.com", "googleadservices.com"]


def is_article_page(url):
    if not url or not url.startswith("http"):
        return False
    return any(p in url for p in ARTICLE_PATH_PATTERNS)


def is_intermediate_page(url):
    if not url:
        return False
    return any(x in url for x in INTERMEDIATE_PATTERNS)


def is_destination(url):
    if not url or not url.startswith("http"):
        return False
    if "chrome-error" in url or "about:blank" in url:
        return False
    if any(p in url for p in DEST_PATTERNS):
        return True
    if is_article_page(url) or is_intermediate_page(url):
        return False
    if any(d in url for d in AD_DOMAINS):
        return False
    if "vplink.in" in url:
        return False
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.hostname and "." in parsed.hostname:
        return True
    return False


def is_ad_domain(url):
    if not url or not url.startswith("http"):
        return False
    return any(d in url for d in AD_DOMAINS)


# ══════════════════════════════════════════════════════════════
#  Template detection
# ══════════════════════════════════════════════════════════════

def detect_template():
    result = safe_eval("""
        if (document.getElementById('tp-time') || document.getElementById('tp-wait1')) return 'tp';
        if (document.getElementById('ce-time') || document.getElementById('ce-wait1')) return 'ce';
        if (document.getElementById('link1s-wait1') || document.getElementById('startCountdownBtn')) return 'link1s';
        return 'unknown';
    """)
    return result or "unknown"


def get_countdown():
    result = safe_eval("""
        var tpTime = document.getElementById('tp-time');
        if (tpTime) {{
            var v = parseInt(tpTime.textContent);
            return isNaN(v) ? -1 : v;
        }}
        var ceTime = document.getElementById('ce-time');
        if (ceTime) {{
            var ceWait = document.getElementById('ce-wait1');
            if (ceWait && getComputedStyle(ceWait).display === 'none') return -1;
            var v = parseInt(ceTime.textContent);
            return isNaN(v) ? -1 : v;
        }}
        var link1sTime = document.getElementById('link1s-time');
        if (link1sTime) {{
            var btn = document.getElementById('startCountdownBtn');
            var btnText = btn ? btn.textContent.trim().toLowerCase() : '';
            var btnClicked = btn && (btn.disabled || btnText.indexOf('counting') >= 0 || btnText.indexOf('wait') >= 0);
            if (!btnClicked && btn && !btn.disabled) return -1;
            var v = parseInt(link1sTime.textContent);
            return isNaN(v) ? -1 : v;
        }}
        return -1;
    """)
    return result if result is not None else -1


def close_ad_overlay():
    closed = safe_eval("""
        var container = document.getElementById('block-cont-1');
        if (container && getComputedStyle(container).display !== 'none') {{
            var closeDiv = container.querySelector('div');
            if (closeDiv && closeDiv.textContent.trim() === 'X') {{
                var style = getComputedStyle(closeDiv);
                if (style.display !== 'none' && style.visibility !== 'hidden') {{
                    closeDiv.click();
                    return 'block-cont-1';
                }}
            }}
        }}
        return false;
    """)
    if not closed:
        closed = safe_eval("""
            var gcont = document.getElementById('gcont');
            if (!gcont) return false;
            var style = getComputedStyle(gcont);
            if (style.position !== 'fixed') return false;
            var svg = gcont.querySelector('.bgcount svg');
            if (svg) {{ svg.click(); return 'gcont-svg'; }}
            return false;
        """)
    if closed:
        log(f"closed ad overlay: {closed}")
        human_delay(300, 800)
    return bool(closed)


def handle_popup():
    continue_btn_visible = safe_eval("""
        var el = document.getElementById('continueBtn');
        if (!el) return false;
        var style = getComputedStyle(el);
        return style.display !== 'none' && style.visibility !== 'hidden' && el.getClientRects().length > 0;
    """)
    gcont_visible = safe_eval("""
        var el = document.getElementById('gcont');
        if (!el) return false;
        var style = getComputedStyle(el);
        return style.position === 'fixed' && style.display !== 'none' && el.getClientRects().length > 0;
    """)
    if not continue_btn_visible and not gcont_visible:
        return False

    log(f"popup detected (continueBtn={continue_btn_visible}, gcont={gcont_visible}), clicking...")
    human_delay(500, 1500)

    if continue_btn_visible:
        try:
            el = driver.find_element(By.ID, "continueBtn")
            driver.execute_script("arguments[0].click();", el)
        except Exception:
            human_click("#continueBtn")
    elif gcont_visible:
        gcont_clicked = safe_eval("""
            var svg = document.querySelector('#gcont .bgcount svg');
            if (svg) {{ svg.click(); return 'svg-close'; }}
            var gcont = document.getElementById('gcont');
            if (gcont) {{ gcont.click(); return 'gcont-click'; }}
            return false;
        """)
        if gcont_clicked:
            log(f"clicked gcont overlay: {gcont_clicked}")

    for _ in range(10):
        ms(1000)
        if "#goog_rewarded" in safe_url():
            log("landed on #goog_rewarded, waiting for ad to complete...")
            return "rewarded"
    return True


def handle_goog_rewarded():
    log("handling #goog_rewarded ad...")
    for w in range(90):
        ms(1000)
        cur = safe_url()
        if "#goog_rewarded" not in cur and not is_ad_domain(cur):
            log(f"ad completed, redirected to: {cur[:100]}")
            return True
        if w % 3 == 0:
            skipped = safe_eval("""
                var selectors = [
                    '#google-rewarded-video > button > img',
                    '#google-rewarded-video > div',
                    '#google-rewarded-video .rewardDialogueWrapper button',
                    '#google-rewarded-video .videoAdUiSkipButton',
                    '.videoAdUiSkipButton',
                    '[class*="skip" i]',
                    '.reward-overlay button',
                    '#skip-button',
                    'button[aria-label*="Skip" i]',
                    '#google-rewarded-video > button'
                ];
                for (var s = 0; s < selectors.length; s++) {{
                    var els = document.querySelectorAll(selectors[s]);
                    for (var i = 0; i < els.length; i++) {{
                        var style = getComputedStyle(els[i]);
                        if (style.display !== 'none' && style.visibility !== 'hidden' && els[i].offsetParent !== null) {{
                            els[i].click();
                            return true;
                        }}
                    }}
                }}
                return false;
            """)
            if skipped:
                log("clicked skip/close button on ad")
        if w % 5 == 0:
            remaining = get_countdown()
            if remaining == 0 or remaining == -1:
                log("countdown finished while on #goog_rewarded, clearing hash")
                safe_eval("history.replaceState(null, '', window.location.pathname + window.location.search);")
                human_delay(500, 1000)
                if "#goog_rewarded" not in safe_url():
                    log("hash cleared, no longer on #goog_rewarded")
                    return True
    log("#goog_rewarded ad did not complete in 90s")
    safe_eval("if (window.location.hash) history.replaceState(null, '', window.location.pathname + window.location.search);")
    human_delay(1000, 2000)
    return "#goog_rewarded" not in safe_url()


def wait_for_countdown(template, max_wait_sec=50):
    max_iter = max_wait_sec * 2
    last_val = -2
    stuck_count = 0
    for i in range(max_iter):
        if "#goog_rewarded" in safe_url():
            return "rewarded"
        remaining = get_countdown()
        if remaining == 0:
            return "done"
        if template == "tp" and remaining == 1:
            return "done"
        if remaining == -1 and template == "link1s" and i > 4:
            return "done"
        if remaining == -1 and i > 4:
            return "done"
        if remaining > 0 and remaining == last_val:
            stuck_count += 1
            if stuck_count >= 5:
                log(f"countdown stuck at {remaining}s for 2.5s — timer JS broken, forcing")
                return "stuck"
        else:
            stuck_count = 0
            last_val = remaining
        if i % 10 == 0 and remaining > 0:
            log(f"countdown {template}: {remaining}s remaining")
        if template != "tp" and i % 4 == 0:
            close_ad_overlay()
            popup_result = handle_popup()
            if popup_result == "rewarded":
                return "rewarded"
        if i % 10 == 0:
            human_scroll()
        ms(500)
    return False


def check_ad_hijack():
    url = safe_url()
    if is_ad_domain(url) and "vplink.in" not in url:
        log(f"AD HIJACK detected: {url[:80]}, navigating back...")
        try:
            driver.back()
            time.sleep(2)
        except Exception:
            last_base = ""
            try:
                driver.get(f"https://{BASE_DOMAIN}/{KEY}")
            except Exception:
                pass
        human_delay(2000, 4000)
        return True
    return False


def navigate_learn_more():
    nav_result = safe_eval("""
        var snp2 = document.getElementById('tp-snp2');
        var a = snp2 ? snp2.closest('a') : null;
        if (a && a.href && a.href.indexOf('learn_more.php') >= 0) {{
            window.location.href = a.href;
            return a.href;
        }}
        var links = document.querySelectorAll('a');
        for (var i = 0; i < links.length; i++) {{
            if (links[i].href && links[i].href.indexOf('learn_more.php') >= 0) {{
                window.location.href = links[i].href;
                return links[i].href;
            }}
        }}
        return false;
    """)
    if nav_result:
        log(f"navigated to learn_more.php: {nav_result}")
        return True
    return False


# ══════════════════════════════════════════════════════════════
#  Template handlers
# ══════════════════════════════════════════════════════════════

def handle_tp():
    log("template: TP (tp-time countdown)")
    safe_eval("""
        var container = document.getElementById('block-cont-1');
        if (container && getComputedStyle(container).display !== 'none') {{
            var closeDiv = container.querySelector('div');
            if (closeDiv && closeDiv.textContent.trim() === 'X') closeDiv.click();
        }}
    """)
    countdown_result = wait_for_countdown("tp", 50)
    if countdown_result == "rewarded":
        log("popup sent us to #goog_rewarded during countdown")
        handle_goog_rewarded()
        safe_eval("if (window.location.hash) history.replaceState(null, '', window.location.pathname + window.location.search);")
        human_delay(500, 1000)
        log("force-invoking showNextProcess after rewarded ad...")
        safe_eval("""
            var wait1 = document.getElementById('tp-wait1');
            var wait2 = document.getElementById('tp-wait2');
            var snp2 = document.getElementById('tp-snp2');
            if (wait1) wait1.style.display = 'none';
            if (wait2) wait2.style.display = 'none';
            if (snp2) snp2.style.display = 'inline-block';
            if (typeof showNextProcess === 'function') {{ try {{ showNextProcess(); }} catch(e) {{}} }}
        """)
        human_delay(1000, 2000)
        nav_ok = navigate_learn_more()
        if nav_ok:
            log("navigated via learn_more.php after rewarded ad")
        return nav_ok

    if countdown_result == "stuck":
        log("countdown stuck — forcing button visibility")
        safe_eval("""
            var wait1 = document.getElementById('tp-wait1');
            var wait2 = document.getElementById('tp-wait2');
            var snp2 = document.getElementById('tp-snp2');
            if (wait1) wait1.style.display = 'none';
            if (wait2) wait2.style.display = 'none';
            if (snp2) snp2.style.display = 'inline-block';
            if (typeof showNextProcess === 'function') {{ try {{ showNextProcess(); }} catch(e) {{}} }}
        """)
        human_delay(1000, 2000)

    if countdown_result not in ("done", "stuck"):
        log("TP countdown timeout, trying button anyway")

    safe_eval("""
        var gcont = document.getElementById('gcont');
        if (gcont) gcont.style.display = 'none';
        var btn = document.getElementById('continueBtn');
        if (btn) {{
            var overlay = btn.closest('div[style*="position: fixed"]') || btn.parentElement;
            if (overlay) overlay.style.display = 'none';
        }}
        var block = document.getElementById('block-cont-1');
        if (block) block.style.display = 'none';
        var snp2 = document.getElementById('tp-snp2');
        var wait1 = document.getElementById('tp-wait1');
        if (snp2 && getComputedStyle(snp2).display === 'none') {{
            if (wait1) wait1.style.display = 'none';
            snp2.style.display = 'block';
        }}
    """)

    if "#goog_rewarded" in safe_url():
        log("on #goog_rewarded after countdown, waiting for ad...")
        handle_goog_rewarded()
        safe_eval("""
            if (window.location.hash) history.replaceState(null, '', window.location.pathname + window.location.search);
            var wait1 = document.getElementById('tp-wait1');
            var snp2 = document.getElementById('tp-snp2');
            if (wait1) wait1.style.display = 'none';
            if (snp2) snp2.style.display = 'block';
        """)
        human_delay(500, 1000)
        return navigate_learn_more()

    human_delay(1000, 2000)
    return navigate_learn_more()


def handle_ce():
    log("template: CE (ce-time countdown)")
    close_ad_overlay()
    log("injecting eonudb cookie + iorghupt localStorage to trigger CE timer...")
    domain = safe_eval("return window.location.hostname;")
    if domain:
        try:
            driver.execute_cdp_cmd("Network.setCookie", {
                "name": "eonudb",
                "value": "1",
                "domain": "." + domain,
                "path": "/",
                "secure": True,
                "httpOnly": False,
                "maxAge": 86400,
            })
        except Exception:
            try:
                driver.add_cookie({"name": "eonudb", "value": "1", "path": "/"})
            except Exception:
                pass
    safe_eval("localStorage.setItem('iorghupt', (Date.now() - 15000).toString());")

    log("reloading page to let JS detect cookie...")
    try:
        driver.execute_script("window.location.reload();")
    except Exception:
        pass
    time.sleep(2)
    close_ad_overlay()

    log("waiting for ce-wait1 to become visible (after reload with cookie)...")
    ce_wait_visible = False
    for w in range(45):
        ce_wait_visible = safe_eval("""
            var el = document.getElementById('ce-wait1');
            if (!el) return false;
            return getComputedStyle(el).display !== 'none';
        """)
        if ce_wait_visible:
            log(f"ce-wait1 visible after {w+1}s")
            break
        if w > 0 and w % 5 == 0:
            safe_eval("""
                var adContainer = document.getElementById('overcn');
                if (adContainer) {
                    var iframe = adContainer.querySelector('iframe');
                    if (iframe) { iframe.focus(); iframe.click(); }
                    else adContainer.click();
                }
            """)
        if check_ad_hijack():
            return True
        ms(1000)

    if not ce_wait_visible:
        log("ce-wait1 never became visible, trying buttons anyway...")

    countdown_result = wait_for_countdown("ce", 60)
    if countdown_result == "rewarded":
        log("popup sent us to #goog_rewarded during CE countdown")
        handle_goog_rewarded()
        safe_eval("if (window.location.hash) history.replaceState(null, '', window.location.pathname + window.location.search);")
        human_delay(500, 1000)
        btn7_vis = safe_eval("""
            var el = document.querySelector('#btn7 > button');
            if (!el) return false;
            return getComputedStyle(el).display !== 'none' && el.offsetParent !== null;
        """)
        if btn7_vis:
            human_click("#btn7 > button")
            log("clicked btn7 after rewarded ad")
            return True
        return True
    if countdown_result != "done":
        log("CE countdown timeout, trying buttons anyway")

    if check_ad_hijack():
        return True

    human_delay(1000, 2000)

    btn6_visible = False
    for w in range(15):
        btn6_visible = safe_eval("""
            var el = document.getElementById('btn6');
            if (!el) return false;
            var style = getComputedStyle(el);
            return style.display !== 'none' && style.visibility !== 'hidden' && el.getClientRects().length > 0;
        """)
        if btn6_visible:
            break
        if check_ad_hijack():
            return True
        ms(1000)

    if btn6_visible:
        human_click("#btn6")
        log("clicked btn6 (Verify)")
        start_url = safe_url()
        for w in range(8):
            ms(1000)
            if safe_url() != start_url:
                log("btn6 triggered navigation")
                return True
            btn7_vis = safe_eval("""
                var el = document.querySelector('#btn7 > button');
                if (!el) return false;
                var style = getComputedStyle(el);
                return style.display !== 'none' && style.visibility !== 'hidden' && el.getClientRects().length > 0;
            """)
            if btn7_vis:
                break

    for w in range(10):
        btn7_vis = safe_eval("""
            var el = document.querySelector('#btn7 > button');
            if (!el) return false;
            var style = getComputedStyle(el);
            return style.display !== 'none' && style.visibility !== 'hidden' && el.getClientRects().length > 0;
        """)
        if btn7_vis:
            clicked = safe_eval("""
                var a = document.getElementById('btn7');
                if (a && a.tagName === 'A' && a.href) {{
                    window._ce_btn7_clicked = true;
                    window.location.href = a.href;
                    return true;
                }}
                var btn = document.querySelector('#btn7 > button');
                if (btn) {{ btn.click(); window._ce_btn7_clicked = true; return true; }}
                return false;
            """)
            if clicked:
                log("clicked btn7 (Continue) via <a> href")
                safe_eval("window._ce_btn7_clicked = true;")
                return True
            human_click("#btn7 > button")
            log("clicked btn7 (Continue) via button")
            safe_eval("window._ce_btn7_clicked = true;")
            return True
        ms(1000)

    human_click("#btn7")
    log("clicked btn7 fallback")
    safe_eval("window._ce_btn7_clicked = true;")
    return True


def handle_link1s():
    log("template: LINK1S (startCountdownBtn)")
    safe_eval("""
        var container = document.getElementById('block-cont-1');
        if (container && getComputedStyle(container).display !== 'none') {{
            var closeDiv = container.querySelector('div');
            if (closeDiv && closeDiv.textContent.trim() === 'X') closeDiv.click();
        }}
    """)
    started = human_click("#startCountdownBtn")
    if started:
        log("clicked startCountdownBtn")
        human_delay(500, 1000)

    safe_eval("""
        var btn = document.getElementById('startCountdownBtn');
        if (btn && !btn.disabled) btn.click();
    """)

    btn_state = safe_eval("""
        var btn = document.getElementById('startCountdownBtn');
        if (!btn) return 'missing';
        return 'disabled=' + btn.disabled + ', text="' + btn.textContent.trim() + '"';
    """)
    log(f"startCountdownBtn state: {btn_state}")

    human_delay(500, 1000)

    if "#goog_rewarded" in safe_url():
        log("#goog_rewarded appeared after startCountdownBtn click, handling ad...")
        handle_goog_rewarded()
        safe_eval("if (window.location.hash) history.replaceState(null, '', window.location.pathname + window.location.search);")
        human_delay(500, 1000)

    log("waiting for #cross-snp2 to appear...")
    clicked = False
    for w in range(60):
        if w % 5 == 0:
            if "#goog_rewarded" in safe_url():
                log("#goog_rewarded during LINK1S wait, handling...")
                handle_goog_rewarded()
                safe_eval("if (window.location.hash) history.replaceState(null, '', window.location.pathname + window.location.search);")
                human_delay(500, 1000)
            if check_ad_hijack():
                return True

        visible = safe_eval("""
            var el = document.getElementById('cross-snp2');
            if (!el) return false;
            var style = getComputedStyle(el);
            return style.display !== 'none' && style.visibility !== 'hidden' && el.getClientRects().length > 0;
        """)
        if visible:
            a_href = safe_eval("""
                var a = document.querySelector('#cross-snp2');
                if (!a) return '';
                var el = a;
                while (el && el.tagName !== 'A') el = el.parentElement;
                if (el && el.href && el.href.indexOf('learn_more.php') >= 0) {{
                    window.location.href = el.href;
                    return el.href;
                }}
                a.click();
                return '';
            """)
            if a_href:
                log(f"navigated via cross-snp2 href: {a_href[:80]}")
            else:
                log("clicked #cross-snp2")
            clicked = True
            break

        if w % 10 == 0:
            cd = get_countdown()
            log(f"[LINK1S wait {w}s] cross-snp2 not visible, countdown={cd}")
        ms(1000)

    if not clicked:
        log("cross-snp2 not visible, forcing button visibility...")
        safe_eval("""
            var gcont = document.getElementById('gcont');
            if (gcont) gcont.style.display = 'none';
            var block = document.getElementById('block-cont-1');
            if (block) block.style.display = 'none';
            var snp2 = document.getElementById('cross-snp2');
            if (snp2) snp2.style.display = 'block';
            var a = snp2 ? snp2.closest('a') : null;
            if (a) a.style.display = 'block';
        """)
        human_delay(1000, 2000)
        nav_done = safe_eval("""
            var el = document.getElementById('cross-snp2');
            if (!el) return false;
            var a = el.closest('a');
            if (a && a.href && a.href.indexOf('learn_more.php') >= 0) {{
                window.location.href = a.href;
                return true;
            }}
            el.click();
            return true;
        """)
        if nav_done:
            log("clicked #cross-snp2 after force-show")
            clicked = True

    if not clicked:
        fallback = safe_eval("""
            var links = document.querySelectorAll('a');
            for (var i = 0; i < links.length; i++) {{
                var a = links[i];
                if (a.href && a.href.indexOf('learn_more.php') >= 0 && a.offsetParent !== null) {{
                    a.click();
                    return true;
                }}
            }}
            return false;
        """)
        if fallback:
            log("clicked learn_more.php fallback link")

    return clicked or False


def handle_unknown():
    log("template: UNKNOWN — trying all known buttons")
    human_delay(3000, 5000)

    buttons = [
        "#tp-snp2", "#cross-snp2", "#btn6",
        "#btn7 > button", "#btn7",
        "#continueBtn", "#gcont",
        "#gt-link",
        "#main > div:nth-child(4) > center > center > a",
    ]
    for sel in buttons:
        close_ad_overlay()
        handle_popup()
        visible = safe_eval(f"""
            var el = document.querySelector({json.dumps(sel)});
            if (!el) return false;
            var style = getComputedStyle(el);
            return style.display !== 'none' && style.visibility !== 'hidden' && el.getClientRects().length > 0;
        """)
        if visible:
            log(f"clicking {sel}")
            human_click(sel)
            human_delay(1000, 2000)
            start_url = safe_url()
            for _ in range(15):
                ms(1000)
                if safe_url() != start_url:
                    return True

    for txt in ["Continue", "Verify", "Get Link"]:
        if click_text(txt):
            human_delay(1000, 2000)
            return True

    learn_more = safe_eval("""
        var links = document.querySelectorAll('a[href*="learn_more.php"]');
        for (var i = 0; i < links.length; i++) {{
            if (links[i].offsetParent !== null) {{
                window.location.href = links[i].href;
                return links[i].href;
            }}
        }}
        return null;
    """)
    if learn_more:
        log(f"clicked learn_more.php link: {learn_more[:80]}")
        human_delay(1000, 2000)
        return True

    return False


def handle_article():
    log("article page")
    debug_shot("article-start")
    start_url = safe_url()

    from urllib.parse import urlparse
    url_path = urlparse(start_url).path
    if url_path == "/" or url_path == "":
        log("landed on homepage (no article slug) — funnel exhausted, navigating to vplink.in")
        return False

    human_delay(2000, 4000)
    try:
        WebDriverWait(driver, 10).until(lambda d: d.execute_script("return document.readyState") != "loading")
    except Exception:
        pass
    human_scroll()
    close_ad_overlay()

    template = detect_template()
    log(f"detected template: {template}")

    if template == "unknown":
        for retry in range(3):
            human_delay(3000, 5000)
            close_ad_overlay()
            template = detect_template()
            if template != "unknown":
                log(f"retry detected template: {template} (attempt {retry + 1})")
                break

    if template == "unknown":
        debug_shot(f"unknown-{int(time.time())}")

    countdown = get_countdown()
    timer_done = countdown <= 1 and countdown != -2
    if timer_done:
        log(f"timer already at {countdown} (finished), skipping read")
    else:
        read_secs = max(countdown + 5, 35) if countdown > 0 else rand(35, 55)
        human_read(min(read_secs, 65))

    navigated = False
    ce_btn7_clicked = False
    if template == "tp":
        navigated = handle_tp()
    elif template == "ce":
        navigated = handle_ce()
        ce_btn7_clicked = safe_eval("return window._ce_btn7_clicked === true;") or False
    elif template == "link1s":
        navigated = handle_link1s()
    else:
        navigated = handle_unknown()

    if navigated:
        wait_start = safe_url()
        if wait_start != start_url and url_base(wait_start) != url_base(start_url):
            log(f"navigated to: {wait_start[:100]}")
            return True
        for _ in range(int(adpt_poll.get())):
            ms(1000)
            cur = safe_url()
            if cur != wait_start or (ce_btn7_clicked and url_base(cur) == url_base(wait_start)):
                if cur != wait_start:
                    log(f"navigated to: {cur[:100]}")
                return True
            if is_ad_domain(cur):
                log(f"ad hijack during nav wait: {cur[:80]}")
                try:
                    driver.back()
                    time.sleep(2)
                except Exception:
                    pass
                human_delay(2000, 4000)
                return True
            if any(x in cur for x in ["learn_more.php", "studiiess", "studieseducates"]):
                log(f"on intermediate page: {cur[:80]}")
                return True
        if ce_btn7_clicked:
            log("btn7 clicked (CE same-URL reload), considering navigated")
            return True
        extracted = safe_eval("""
            var a = document.querySelector('a[href*="learn_more.php"]');
            if (a && a.href) { window.location.href = a.href; return a.href; }
            var meta = document.querySelector('meta[http-equiv="refresh"]');
            if (meta) {
                var m = meta.content.match(/url=(.+)/i);
                if (m) return m[1];
            }
            return null;
        """)
        if extracted and "learn_more.php" in str(extracted):
            log(f"re-trying learn_more.php nav: {extracted[:80]}")
            return True
        log("buttons clicked but no URL change detected, continuing")
        return False

    return False


def do_get_link():
    global destination_url
    try:
        handles = driver.window_handles
        main_handle = driver.current_window_handle
        for h in handles:
            if h != main_handle:
                try:
                    driver.switch_to.window(h)
                    driver.close()
                except Exception:
                    pass
        driver.switch_to.window(main_handle)

        try:
            WebDriverWait(driver, int(adpt_getlink.get())).until(
                lambda d: d.execute_script("return document.getElementById('get-link') !== null")
            )
        except Exception:
            return False

        link_hrefs = safe_eval("""
            var getLink = document.getElementById('get-link');
            var gtLink = document.getElementById('gt-link');
            var allScripts = Array.from(document.querySelectorAll('script')).map(function(s){return s.textContent||s.src||''}).join('\\n');
            var allData = '';
            document.querySelectorAll('[data-href],[data-url],[data-dest],[data-link],[data-target]').forEach(function(el){
                allData += (el.getAttribute('data-href')||'') + ' ' + (el.getAttribute('data-url')||'') + ' ' + (el.getAttribute('data-dest')||'') + ' ' + (el.getAttribute('data-link')||'') + ' ' + (el.getAttribute('data-target')||'') + ' ';
            });
            var allHrefs = Array.from(document.querySelectorAll('a[href]')).map(function(a){return a.href}).filter(function(h){return h.indexOf('http')===0}).join('\\n');
            return {{
                getLinkHref: getLink ? getLink.href : '',
                gtLinkHref: gtLink ? gtLink.href : '',
                scripts: allScripts.substring(0, 5000),
                data: allData.trim(),
                hrefs: allHrefs.substring(0, 3000)
            }};
        """) or {}
        link_href = (link_hrefs.get("gtLinkHref") or link_hrefs.get("getLinkHref") or "").replace("javascript:void(0)", "")
        if link_href and link_href.startswith("http"):
            log(f"captured href before click: gt-link={bool(link_hrefs.get('gtLinkHref'))}, get-link={bool(link_hrefs.get('getLinkHref'))}")
        pre_scan_dest = None
        import re as _re
        for scan_field in ["scripts", "hrefs", "data"]:
            scan_text = link_hrefs.get(scan_field, "")
            if not scan_text:
                continue
            for m in _re.finditer(r'https?://[^\s"\'<>]+', scan_text):
                u = m.group(0).rstrip('.,;:)"\'')
                if any(x in u for x in ["lnkd.in", "linkedin.com", "google.com", "gstatic.com", "cloudflare", "facebook.com", "twitter.com", "cloudflareinsights"]):
                    continue
                if is_destination(u):
                    pre_scan_dest = u
                    break
            if pre_scan_dest:
                break
        if pre_scan_dest:
            log(f"destination found in page scan: {pre_scan_dest[:100]}")
            destination_url = pre_scan_dest
            return True

        t0 = time.time()
        try:
            WebDriverWait(driver, int(adpt_poll.get())).until(
                lambda d: d.execute_script("""
                    var el = document.getElementById('get-link');
                    return el && !el.classList.contains('disabled');
                """)
            )
        except Exception:
            pass
        countdown_elapsed = int((time.time() - t0) * 1000)
        if countdown_elapsed > 500:
            log(f"get-link countdown: {countdown_elapsed}ms")

        human_delay(800, 2000)
        human_mouse_move("#get-link")
        human_delay(300, 700)

        log("clicking Get Link")
        pre_handles = set(driver.window_handles)

        captured_redirects = []
        try:
            def _on_response(event):
                try:
                    url = event.get("params", {}).get("response", {}).get("url", "")
                    loc = ""
                    for h in event.get("params", {}).get("response", {}).get("headers", {}):
                        if h.lower() == "location":
                            loc = event["params"]["response"]["headers"][h]
                            break
                    if url and ("linkedin.com" in url or "lnkd.in" in url):
                        captured_redirects.append({"url": url, "location": loc})
                        if loc:
                            log(f"[network] {url[:60]} -> {loc[:80]}")
                except Exception:
                    pass
            try:
                driver.add_cdp_listener("Network.responseReceived", _on_response)
            except Exception:
                pass
        except Exception:
            pass

        human_click("#get-link")

        new_tab = None
        for _ in range(20):
            ms(1000)
            cur_handles = set(driver.window_handles)
            diff = cur_handles - pre_handles
            if diff:
                new_tab = diff.pop()
                break

        if new_tab:
            driver.switch_to.window(new_tab)
            ms(5000)
            try:
                tab_url = driver.current_url
                from urllib.parse import urlparse, parse_qs
                u = urlparse(tab_url)
                for val in parse_qs(u.query).values():
                    if val:
                        import base64
                        try:
                            decoded = base64.b64decode(val[0]).decode("utf-8", errors="ignore")
                            if decoded.startswith("http"):
                                log(f"decoded destination from base64 param: {decoded}")
                                destination_url = decoded
                                driver.close()
                                driver.switch_to.window(driver.window_handles[0])
                                return True
                        except Exception:
                            pass
            except Exception:
                pass

        tracking_wait = int(adpt_getlink.get() * 500)
        click_time = time.time()
        stable_url = ""
        stable_count = 0

        max_dest_wait = int(adpt_getlink.get() * 1.5)
        for i in range(max_dest_wait):
            ms(1000)
            popup_url = ""
            if new_tab:
                try:
                    driver.switch_to.window(new_tab)
                    time.sleep(0.5)
                    popup_url = driver.current_url
                except Exception:
                    new_tab = None
                if popup_url and "about:blank" not in popup_url and "chrome-error" not in popup_url:
                    if i < 15 or i % 5 == 0:
                        log(f"[get-link {i}s] popup: {popup_url[:100]}")
                    if is_destination(popup_url):
                        destination_url = popup_url
                        log(f"destination (popup match): {popup_url[:100]}")
                        try:
                            driver.close()
                            driver.switch_to.window(driver.window_handles[0])
                        except Exception:
                            pass
                        return True
                    is_redirect = any(x in popup_url for x in [
                        "linkedin.com/redir", "google.com/url", "facebook.com/l.php", "t.co/",
                        "wistfulseverely.com", "one-vv", "lnkd.in"
                    ])
                    if is_redirect:
                        log(f"redirect/tracking URL detected ({popup_url[:60]}), waiting for final...")
                        redirect_done = False
                        lnkd_stuck_count = 0
                        for r in range(int(adpt_getlink.get())):
                            ms(1000)
                            try:
                                new_url = driver.current_url
                                if new_url and "about:blank" not in new_url:
                                    if new_url != popup_url:
                                        log(f"[redirect {r}s] {new_url[:100]}")
                                    popup_url = new_url
                                    if not any(x in popup_url for x in [
                                        "wistfulseverely.com", "one-vv", "linkedin.com/redir",
                                        "google.com/url", "facebook.com/l.php", "t.co/", "lnkd.in"
                                    ]):
                                        redirect_done = True
                                        break
                                    if "lnkd.in" in popup_url or "linkedin.com" in popup_url:
                                        lnkd_stuck_count += 1
                                        if lnkd_stuck_count >= 5 and r >= 5:
                                            log(f"stuck on {popup_url[:40]} for {r}s, trying HTTP resolve...")
                                            try:
                                                import urllib.request as _urllib_req
                                                for _att in range(2):
                                                    try:
                                                        req = _urllib_req.Request(popup_url, headers={
                                                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
                                                        })
                                                        resp = _urllib_req.urlopen(req, timeout=15)
                                                        final_url = resp.geturl()
                                                        if final_url and final_url != popup_url and "lnkd.in" not in final_url and "linkedin.com" not in final_url:
                                                            log(f"resolved via early HTTP: {final_url[:100]}")
                                                            destination_url = final_url
                                                            try:
                                                                driver.close()
                                                                driver.switch_to.window(driver.window_handles[0])
                                                            except Exception:
                                                                pass
                                                            return True
                                                        break
                                                    except Exception:
                                                        if _att < 1:
                                                            ms(2000)
                                            except Exception:
                                                pass
                                            break
                            except Exception:
                                break
                        if redirect_done:
                            destination_url = popup_url
                            log(f"destination (popup): {popup_url[:100]}")
                            elapsed_ms = (time.time() - click_time) * 1000
                            wait = max(0, tracking_wait - elapsed_ms) / 1000
                            if wait > 0.5:
                                log(f"tracking wait: {int(wait * 1000)}ms")
                                time.sleep(wait)
                            return True
                        # Redirect loop exhausted but still on a tracking URL
                        # Try to resolve via HTTP redirect (lnkd.in redirects via HTTP 302)
                        try:
                            import urllib.request
                            import re as _re
                            for _attempt in range(3):
                                try:
                                    req = urllib.request.Request(popup_url, headers={
                                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
                                    })
                                    resp = urllib.request.urlopen(req, timeout=15)
                                    final_url = resp.geturl()
                                    if final_url and final_url != popup_url:
                                        if "lnkd.in" not in final_url and "linkedin.com" not in final_url:
                                            log(f"resolved via HTTP redirect: {final_url[:100]}")
                                            destination_url = final_url
                                            try:
                                                driver.close()
                                                driver.switch_to.window(driver.window_handles[0])
                                            except Exception:
                                                pass
                                            return True
                                    body = resp.read(50000).decode("utf-8", errors="ignore")
                                    meta_match = _re.search(r'<meta[^>]+http-equiv=["\']?refresh["\']?[^>]+content=["\']?\d+;\s*url=([^\s"\']+)', body, _re.I)
                                    if meta_match:
                                        meta_url = meta_match.group(1)
                                        if meta_url.startswith("http") and "lnkd.in" not in meta_url and "linkedin.com" not in meta_url:
                                            log(f"extracted from meta refresh: {meta_url[:100]}")
                                            destination_url = meta_url
                                            try:
                                                driver.close()
                                                driver.switch_to.window(driver.window_handles[0])
                                            except Exception:
                                                pass
                                            return True
                                    js_match = _re.search(r'window\.location(?:\.href)?\s*=\s*["\']?(https?://[^"\'>\s]+)', body, _re.I)
                                    if js_match:
                                        js_url = js_match.group(1)
                                        if "lnkd.in" not in js_url and "linkedin.com" not in js_url:
                                            log(f"extracted from JS redirect: {js_url[:100]}")
                                            destination_url = js_url
                                            try:
                                                driver.close()
                                                driver.switch_to.window(driver.window_handles[0])
                                            except Exception:
                                                pass
                                            return True
                                    break
                                except Exception:
                                    if _attempt < 2:
                                        log(f"resolve attempt {_attempt+1} failed, retrying...")
                                        ms(2000)
                        except Exception:
                            pass
                        for cr in reversed(captured_redirects):
                            loc = cr.get("location", "")
                            if loc and loc.startswith("http") and not any(x in loc for x in ["lnkd.in", "linkedin.com", "google.com/recaptcha", "about:blank"]):
                                log(f"destination from network redirect: {loc[:100]}")
                                destination_url = loc
                                try:
                                    driver.close()
                                    driver.switch_to.window(driver.window_handles[0])
                                except Exception:
                                    pass
                                return True
                        log(f"stuck on tracking URL {popup_url[:60]} — giving up on popup")
                        try:
                            driver.close()
                            driver.switch_to.window(driver.window_handles[0])
                        except Exception:
                            pass
                        break

                    # Popup URL is not a redirect — this is the destination
                    destination_url = popup_url
                    log(f"destination (popup): {popup_url[:100]}")
                    elapsed_ms = (time.time() - click_time) * 1000
                    wait = max(0, tracking_wait - elapsed_ms) / 1000
                    if wait > 0.5:
                        log(f"tracking wait: {int(wait * 1000)}ms")
                        time.sleep(wait)
                    return True

            try:
                driver.switch_to.window(driver.window_handles[0])
            except Exception:
                pass
            m_url = safe_url()
            if not m_url or "about:blank" in m_url or "chrome-error" in m_url:
                continue
            if m_url == stable_url:
                stable_count += 1
                is_tracker = "wistfulseverely.com" in m_url or "one-vv" in m_url
                if stable_count >= 3 and is_destination(m_url) and not is_tracker:
                    destination_url = m_url
                    log(f"destination (stable): {m_url[:100]}")
                    elapsed_ms = (time.time() - click_time) * 1000
                    wait = max(0, tracking_wait - elapsed_ms) / 1000
                    if wait > 0.5:
                        log(f"tracking wait: {int(wait * 1000)}ms")
                        time.sleep(wait)
                    return True
            else:
                stable_url = m_url
                stable_count = 1

        if link_href and link_href.startswith("http"):
            destination_url = link_href
            log(f"destination (href): {link_href[:100]}")
            elapsed_ms = (time.time() - click_time) * 1000
            wait = max(0, tracking_wait - elapsed_ms) / 1000
            if wait > 0.5:
                log(f"tracking wait: {int(wait * 1000)}ms")
                time.sleep(wait)
            return True
    except Exception as error:
        log(f"get-link handler failed: {str(error) or 'unknown error'}")
    return False


def _create_driver():
    global driver, profile
    from profile_generator import generate_profile
    profile = generate_profile(mobile=True, youtube=True)
    log(f"profile: {profile['viewport']['width']}x{profile['viewport']['height']} {profile['locale']} {profile['timezone']} hw={profile['hardwareConcurrency']} mem={profile['deviceMemory']} dpr={profile['deviceScaleFactor']}")

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

    is_termux = os.environ.get("VPLINK_TERMUX") == "1"
    headless = is_termux or os.environ.get("VPLINK_HEADLESS") == "1"

    if headless:
        options.add_argument("--headless=new")

    if is_termux:
        chromium_path = os.environ.get("CHROMIUM_PATH", "/data/data/com.termux/files/usr/bin/chromium-browser")
        options.binary_location = chromium_path
    elif os.environ.get("CHROMIUM_PATH"):
        options.binary_location = os.environ["CHROMIUM_PATH"]
    else:
        options.binary_location = _detect_chrome_binary()

    if PROXY:
        options.add_argument(f"--proxy-server={PROXY}")

    extra_args = os.environ.get("VPLINK_EXTRA_ARGS", "")
    if extra_args:
        for arg in extra_args.split():
            options.add_argument(arg)

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
        if os.path.exists(cpath) and _check_native_binary(cpath):
            try:
                service = Service(executable_path=cpath)
                driver = webdriver.Chrome(service=service, options=options)
                break
            except Exception:
                continue
    if driver is None:
        try:
            from webdriver_manager.chrome import ChromeDriverManager
            cm_path = ChromeDriverManager().install()
            service = Service(executable_path=cm_path)
            driver = webdriver.Chrome(service=service, options=options)
        except Exception:
            for cpath in chromedriver_paths:
                if os.path.exists(cpath):
                    try:
                        service = Service(executable_path=cpath)
                        driver = webdriver.Chrome(service=service, options=options)
                        break
                    except Exception:
                        continue

    driver.set_page_load_timeout(90)
    driver.implicitly_wait(0)

    try:
        driver.execute_cdp_cmd("Network.enable", {"maxTotalBufferSize": 1048576})
    except Exception:
        pass

    _inject_traffic_source()

    stealth_js = _build_stealth_js(profile)
    try:
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": stealth_js})
    except Exception:
        pass
    driver.execute_script(stealth_js)


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
#  Main
# ══════════════════════════════════════════════════════════════

def main():
    global driver, destination_url, start_time, profile, proxy_blocked, PROXY, PROXY_HOST, PROXY_IP, PROXY_PORT

    _create_driver()

    storage_dir = Path.home() / ".vplink3.0" / "storage"
    storage_file = storage_dir / "state.json"
    storage_dir.mkdir(parents=True, exist_ok=True)

    def save_storage():
        try:
            cookies = driver.get_cookies()
            storage_file.write_text(json.dumps({"cookies": cookies}), "utf-8")
        except Exception:
            pass

    import threading
    storage_timer = threading.Timer(30.0, save_storage)
    storage_timer.daemon = True
    storage_timer.start()

    if storage_file.exists():
        try:
            saved = json.loads(storage_file.read_text("utf-8"))
            for cookie in saved.get("cookies", []):
                try:
                    driver.add_cookie(cookie)
                except Exception:
                    pass
        except Exception:
            pass

    log("=" * 50)
    log(f"starting funnel for KEY={KEY}")
    if DEBUG:
        log("debug mode active")

    for proxy_attempt in range(MAX_PROXY_RESTARTS + 1):
      if proxy_attempt > 0:
        log(f"--- proxy restart {proxy_attempt}/{MAX_PROXY_RESTARTS} ---")
        if not restart_proxy():
            break
        skip_main_loop = False
        proxy_blocked = False
      nav_timeout = adpt_nav.get()
      if proxy_attempt == 0:
        skip_main_loop = False

      referer = os.environ.get("VPLINK_REFERER", "")
      if referer:
          log(f"navigating to YouTube first for referral: {referer[:60]}")
          try:
              adpt_load.set_page_load(driver)
              nav_start = time.time()
              driver.get(referer)
              adpt_nav.observe(time.time() - nav_start)
              human_delay(2000, 4000)
              log("YouTube loaded, now navigating to vplink.in (browser will set Referer)")
          except Exception as e:
              log(f"YouTube navigation failed: {e}, continuing without referral")

      log(f"navigating to vplink.in/{KEY}")
      debug_shot("01-start")

      adpt_load.set_page_load(driver)
      nav_start = time.time()
      try:
          driver.get(f"https://{BASE_DOMAIN}/{KEY}")
          adpt_nav.observe(time.time() - nav_start)
      except Exception as e:
          log(f"first goto failed: {e}, retrying...")
          if PROXY and "timeout" in str(e).lower():
              report_proxy_failure("first-goto-hang")
              proxy_blocked = True
              skip_main_loop = True
          elif PROXY:
              report_proxy_failure("first-goto-error")
          time.sleep(2)
          if not skip_main_loop:
              try:
                  adpt_load.set_page_load(driver)
                  nav_start = time.time()
                  driver.get(f"https://{BASE_DOMAIN}/{KEY}")
                  adpt_nav.observe(time.time() - nav_start)
              except Exception as e2:
                  log(f"second goto failed: {e2}")
                  adpt_nav.timeout_occured()
                  if PROXY:
                      report_proxy_failure("second-goto-error")
                  proxy_blocked = True
                  skip_main_loop = True

      if not skip_main_loop:
          human_delay(2000, 4000)
      debug_shot("02-after-nav")

      if not skip_main_loop:
          log("waiting for auto-redirect...")
          redirect_start = time.time()
          redirect_wait = int(adpt_redirect.get())
          for i in range(redirect_wait):
              ms(1000)
              if "vplink.in" not in safe_url():
                  break
          redirect_elapsed = time.time() - redirect_start
          if "vplink.in" not in safe_url():
              adpt_redirect.observe(redirect_elapsed)
          debug_shot("03-after-redirect")

          for attempt in range(2):
              url = safe_url()
              if "vplink.in" not in url or "cdn-cgi" in url:
                  break
              has_gl = safe_eval("return !!document.getElementById('get-link');")
              if has_gl:
                  log("page loaded (get-link visible)")
                  break
              is_cf = safe_eval("""
                  var html = (document.documentElement?.innerHTML || '').substring(0, 2000);
                  return html.indexOf('cf-browser-verification') >= 0 || html.indexOf('challenge-form') >= 0
                      || html.indexOf('cf-challenge') >= 0 || html.indexOf('_cf_chl_opt') >= 0;
              """)
              if is_cf:
                  log("Cloudflare challenge detected")
              log(f"waiting for page content (attempt {attempt + 1})...")
              cf_wait = int(adpt_poll.get())
              loaded = False
              for i in range(cf_wait):
                  ms(1000)
                  if "vplink.in" not in safe_url():
                      loaded = True
                      break
                  if safe_eval("return !!document.getElementById('get-link');"):
                      loaded = True
                      break
              if loaded:
                  break
              if is_cf:
                  log("Cloudflare not resolved, reloading...")
                  try:
                      driver.refresh()
                      time.sleep(4)
                  except Exception:
                      pass
              else:
                  break

          if "vplink.in" in safe_url() and "cdn-cgi" not in safe_url():
              has_gl = safe_eval("return !!document.getElementById('get-link');")
              if not has_gl:
                  log("stuck on vplink.in — proxy may be blocking JS redirects")
                  proxy_blocked = True
                  if PROXY:
                      report_proxy_failure("vplink-no-redirect")
                  skip_main_loop = True

      vplink_arrivals = 0
      intermediate_stuck_count = 0
      last_base = ""
      goog_reward_retries = 0
      ad_hijack_count = 0
      last_stuck_article = ""
      max_goog_reward_retries = 3
      max_url_visits = 4
      max_ad_hijacks = 5
      url_visits = {}
      exhausted_cycles = 0

      for cycle in range(30):
          if destination_url or skip_main_loop:
              break
          url = safe_url()
          if not url:
              ms(2000)
              continue
          base = url_base(url)

          if check_ad_hijack():
              ad_hijack_count += 1
              if ad_hijack_count > max_ad_hijacks:
                  log(f"too many ad hijacks ({ad_hijack_count}), proxy likely injecting ads")
                  if PROXY:
                      report_proxy_failure("too-many-ad-hijacks")
                  proxy_blocked = True
                  break
              last_base = ""
              continue

          url_key = url.split("#")[0]
          is_intermediate = is_intermediate_page(url)
          if "vplink.in" not in url and not is_intermediate:
              url_visits[url_key] = url_visits.get(url_key, 0) + 1
              if url_visits[url_key] >= max_url_visits:
                  if last_stuck_article == url_key:
                      log(f"STUCK LOOP: same article visited {url_visits[url_key]} times after force-nav, exiting")
                      if PROXY:
                          report_proxy_failure("article-stuck-loop")
                      proxy_blocked = True
                      break
                  last_stuck_article = url_key
                  log(f"STUCK: same article visited {url_visits[url_key]} times, force-navigating")
                  last_base = ""
                  try:
                      adpt_load.set_page_load(driver)
                      driver.get(f"https://{BASE_DOMAIN}/{KEY}")
                  except Exception:
                      adpt_load.timeout_occured()
                  human_delay(3000, 5000)
                  continue

          if base == last_base and "#" in url:
              hash_val = url.split("#")[1]
              log(f"[cycle {cycle + 1}] hash-only change ({hash_val}), waiting...")
              if hash_val == "goog_rewarded":
                  handle_goog_rewarded()
                  safe_eval("if (window.location.hash) history.replaceState(null, '', window.location.pathname + window.location.search);")
                  human_delay(500, 1000)
                  remaining = get_countdown()
                  if remaining > 0:
                      log(f"timer still at {remaining}, waiting for countdown...")
                      wait_for_countdown("tp", int(adpt_poll.get()))
                      human_delay(500, 1000)
                  clicked = navigate_learn_more()
                  if not clicked:
                      clicked = human_click("#cross-snp2") or human_click("#btn7 > button") or human_click("#btn7") or human_click("#gt-link")
                  if clicked:
                      log("clicked button after #goog_rewarded ad")
                  last_base = url_base(safe_url())
                  continue
              human_delay(3000, 5000)
              for _ in range(8):
                  ms(1000)
                  cur = safe_url()
                  if url_base(cur) != base:
                      log(f"navigated away: {cur[:100]}")
                      break
              if url_base(safe_url()) == base:
                  log("still stuck on same page after hash wait, navigating to vplink.in")
                  last_base = ""
                  try:
                      adpt_load.set_page_load(driver)
                      driver.get(f"https://{BASE_DOMAIN}/{KEY}")
                  except Exception:
                      adpt_load.timeout_occured()
                  human_delay(3000, 5000)
              continue

          last_base = base
          goog_reward_retries = 0
          log(f"[cycle {cycle + 1}] {url[:110]}")
          debug_shot(f"cycle-{cycle + 1}")

          if is_destination(url):
              destination_url = url
              log("on destination URL already!")
              break

          if "vplink.in" in url and "cdn-cgi" not in url:
              vplink_arrivals += 1
              btn_state = safe_eval("""
                  var el = document.getElementById('get-link');
                  var gtLink = document.getElementById('gt-link');
                  if (!el && !gtLink) return 'missing';
                  if (gtLink && getComputedStyle(gtLink).display !== 'none') return 'ready';
                  if (el && el.classList.contains('disabled')) return 'disabled';
                  if (el && el.offsetParent === null) return 'hidden';
                  return 'ready';
              """)
              log(f"get-link state: {btn_state}")
              if btn_state == "ready":
                  if do_get_link():
                      break
                  log("get-link failed, reloading vplink.in")
                  try:
                      main_handle = driver.current_window_handle
                      for h in driver.window_handles:
                          if h != main_handle:
                              driver.switch_to.window(h)
                              driver.close()
                      driver.switch_to.window(main_handle)
                      adpt_load.set_page_load(driver)
                      driver.get(f"https://{BASE_DOMAIN}/{KEY}")
                  except Exception:
                      adpt_load.timeout_occured()
                  human_delay(3000, 5000)
                  for i in range(15):
                      ms(1000)
                      if "vplink.in" not in safe_url():
                          break
                  continue
              if btn_state in ("missing", None):
                  if vplink_arrivals >= 5:
                      log("stuck on vplink.in with no article page — proxy blocking JS redirects")
                      proxy_blocked = True
                      if PROXY:
                          report_proxy_failure("vplink-get-link-missing")
                      break
                  ms(2000)
                  continue
              human_delay(1500, 3000)
              continue

          if url.startswith("chrome-error://"):
              log("chrome-error, force to vplink.in")
              if PROXY:
                  report_proxy_failure("chrome-error")
              try:
                  adpt_load.set_page_load(driver)
                  driver.get(f"https://{BASE_DOMAIN}/{KEY}")
              except Exception:
                  adpt_load.timeout_occured()
              human_delay(3000, 5000)
              continue

          if "#goog_rewarded" in url:
              goog_reward_retries += 1
              log(f"#goog_rewarded in main loop (attempt {goog_reward_retries})")
              if goog_reward_retries > max_goog_reward_retries:
                  log(f"#goog_rewarded stuck after {goog_reward_retries} retries, force-navigating")
                  goog_reward_retries = 0
                  last_base = ""
                  try:
                      adpt_load.set_page_load(driver)
                      driver.get(f"https://{BASE_DOMAIN}/{KEY}")
                  except Exception:
                      adpt_load.timeout_occured()
                  human_delay(3000, 5000)
                  continue
              rewarded_ok = handle_goog_rewarded()
              if rewarded_ok:
                  safe_eval("if (window.location.hash) history.replaceState(null, '', window.location.pathname + window.location.search);")
                  human_delay(500, 1000)
                  remaining = get_countdown()
                  if remaining > 0:
                      log(f"timer at {remaining} after rewarded ad, waiting...")
                      wait_for_countdown(None, remaining + 10)
                      human_delay(500, 1000)
                  clicked = navigate_learn_more()
                  if not clicked:
                      clicked = human_click("#cross-snp2") or human_click("#btn7 > button") or human_click("#btn7") or human_click("#gt-link")
                  if clicked:
                      log("clicked button after #goog_rewarded")
              last_base = url_base(safe_url())
              continue

          if is_intermediate_page(url):
              log("intermediate redirect page, waiting for auto-redirect...")
              intermediate_base = url_base(url)
              redirected = False
              intermediate_wait = max(int(adpt_redirect.get()), 20)
              same_url_reloads = 0

              _nav_captured = {"url": None}
              _nav_active = [True]
              _nav_last_url = [safe_url()]
              import threading
              def _nav_poll():
                  while _nav_active[0]:
                      try:
                          cur = driver.current_url
                          if cur and cur != _nav_last_url[0]:
                              _nav_last_url[0] = cur
                              if not any(x in cur for x in [
                                  "studiiess", "studieseducates", "learn_more", "vplink.in",
                                  "about:", "chrome-", "cdn-cgi"
                              ]):
                                  _nav_captured["url"] = cur
                      except Exception:
                          pass
                      time.sleep(0.3)
              _nav_thread = threading.Thread(target=_nav_poll, daemon=True)
              _nav_thread.start()

              for w in range(intermediate_wait):
                  ms(1000)
                  if _nav_captured["url"]:
                      log(f"poll captured nav: {_nav_captured['url'][:100]}")
                      try:
                          adpt_load.set_page_load(driver)
                          driver.get(_nav_captured["url"])
                      except Exception:
                          pass
                      human_delay(500, 1500)
                      redirected = True
                      break
                  cur = safe_url()
                  cur_base = url_base(cur)
                  intermediate_skip = is_intermediate_page(cur)
                  if cur_base != intermediate_base and not intermediate_skip:
                      log(f"redirected to: {cur[:100]}")
                      human_delay(500, 1500)
                      redirected = True
                      break
                  if w > 0 and w % 5 == 0:
                      same_url_reloads += 1
                      if same_url_reloads >= 2:
                          log(f"intermediate self-reload detected ({same_url_reloads}x), proxy can't execute JS redirect")
                          break
                  if w == 8 and not redirected:
                      extracted_url = safe_eval("""
                          var html = document.documentElement.outerHTML || '';
                          var m = html.match(/window\\.location(?:\\.href)?\\s*=\\s*['"](\\/[^'"]+)['"]/);
                          if (m && m[1].indexOf('studiiessuniversitiess') < 0 && m[1].indexOf('learn_more') < 0) return m[1];
                          m = html.match(/window\\.location\\.replace\\s*\\(\\s*['"](\\/[^'"]+)['"]\\s*\\)/);
                          if (m && m[1].indexOf('studiiessuniversitiess') < 0 && m[1].indexOf('learn_more') < 0) return m[1];
                          var meta = document.querySelector('meta[http-equiv="refresh"]');
                          if (meta) {{
                              var urlMatch = meta.content.match(/url=(.+)/i);
                              if (urlMatch) return urlMatch[1].trim();
                          }}
                          var links = document.querySelectorAll('a[href]');
                          for (var i = 0; i < links.length; i++) {{
                              var href = links[i].href;
                              if (href && href.indexOf('javascript:') < 0 && href.indexOf('studiiessuniversitiess') < 0
                                  && href.indexOf('universitesstudiiess') < 0 && href.indexOf('learn_more') < 0
                                  && href.indexOf('vplink.in') < 0 && href.startsWith('http')) {{
                                  return href;
                              }}
                          }}
                          return null;
                      """)
                      if extracted_url:
                          log(f"extracted redirect URL: {extracted_url[:100]}")
                          full_url = extracted_url if extracted_url.startswith("http") else f"https://{urlparse(url).hostname}{extracted_url}"
                          try:
                              adpt_load.set_page_load(driver)
                              driver.get(full_url)
                          except Exception:
                              pass
                          human_delay(1000, 2000)
                          redirected = True
                          break
                  if w == 12 and not redirected:
                      forced_url = safe_eval("""
                          var scripts = document.querySelectorAll('script:not([src])');
                          for (var i = 0; i < scripts.length; i++) {{
                              var t = scripts[i].textContent || '';
                              var timerMatch = t.match(/setTimeout\\s*\\(\\s*(?:function\\s*\\(\\)\\s*\\{?\\s*)?window\\.location(?:\\.href)?\\s*=\\s*['"]([^'"]+)['"]/);
                              if (timerMatch && timerMatch[1].indexOf('studiiessuniversitiess') < 0) return timerMatch[1];
                          }}
                          return null;
                      """)
                      if forced_url:
                          log(f"forced redirect URL: {forced_url[:100]}")
                          full_url = forced_url if forced_url.startswith("http") else f"https://{urlparse(url).hostname}{forced_url}"
                          try:
                              adpt_load.set_page_load(driver)
                              driver.get(full_url)
                          except Exception:
                              pass
                          human_delay(1000, 2000)
                          redirected = True
                          break

              _nav_active[0] = False

              if not redirected:
                  intermediate_stuck_count += 1
                  log(f"intermediate page not redirecting (stuck #{intermediate_stuck_count})")
                  if intermediate_stuck_count >= 2:
                      log("intermediate stuck 2x — proxy cannot execute JS redirect, blacklisting")
                      if PROXY:
                          report_proxy_failure("intermediate-stuck")
                      proxy_blocked = True
                      break
              else:
                  intermediate_stuck_count = 0
              last_base = url_base(safe_url())
              continue

          navigated = handle_article()
          if navigated:
              inter_delay = rand(8000, 22000)
              log(f"inter-article delay: {inter_delay // 1000}s")
              ms(inter_delay)
              exhausted_cycles = 0
              continue
          exhausted_cycles += 1
          log(f"exhausted (x{exhausted_cycles}), force-navigating to vplink.in")
          if exhausted_cycles >= 2:
              log("2 consecutive exhausted cycles — breaking to final get-link")
              break
          last_base = ""
          try:
              adpt_load.set_page_load(driver)
              driver.get(f"https://{BASE_DOMAIN}/{KEY}")
          except Exception:
              adpt_load.timeout_occured()
          human_delay(2000, 4000)
          for i in range(int(adpt_poll.get())):
              ms(1000)
              if "vplink.in" not in safe_url():
                  break

      if not destination_url and not proxy_blocked:
          log("running final fallback...")
          got_dest = False
          if "vplink.in" in safe_url():
              got_dest = do_get_link()
          if not got_dest:
              vplink_href = safe_eval("""
                  var links = document.querySelectorAll('a[href*="vplink.in"]');
                  for (var i = 0; i < links.length; i++) {{
                      if (links[i].href && links[i].href.indexOf('cdn-cgi') < 0) return links[i].href;
                  }}
                  return null;
              """)
              if vplink_href:
                  log("found vplink link on page")
                  try:
                      adpt_load.set_page_load(driver)
                      driver.get(vplink_href)
                  except Exception:
                      adpt_load.timeout_occured()
                  human_delay(3000, 5000)
                  if "vplink.in" in safe_url():
                      got_dest = do_get_link()
          if not got_dest:
              for a in range(3):
                  log(f"direct attempt {a + 1}")
                  try:
                      adpt_load.set_page_load(driver)
                      driver.get(f"https://{BASE_DOMAIN}/{KEY}")
                  except Exception:
                      adpt_load.timeout_occured()
                  for w in range(int(adpt_poll.get())):
                      ms(500)
                      cur = safe_url()
                      if "vplink.in" in cur:
                          has_gl = safe_eval("return !!document.getElementById('get-link');")
                          if has_gl and do_get_link():
                              got_dest = True
                              break
                      else:
                          break
                  if got_dest:
                      break
          if got_dest and not destination_url:
              destination_url = safe_url()

      if destination_url or not proxy_blocked:
          break

    print("\n" + "=" * 39)
    print("  " + ("DESTINATION URL:" if destination_url else "NO DESTINATION"))
    if destination_url:
        final_url = _add_utm_to_url(destination_url)
        print("  " + final_url)
        (Path(__file__).parent / "destination_url.txt").write_text(final_url, "utf-8")
        _revisit_with_referrer(final_url)
        if PROXY_IP and PROXY_PORT:
            mark_proxy_used(PROXY_IP, PROXY_PORT)
    ms(2000)
    try:
        driver.quit()
    except Exception:
        pass
    sys.exit(0 if destination_url else (2 if proxy_blocked else 3))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Fatal automation error: {error}", file=sys.stderr)
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
        sys.exit(1)
