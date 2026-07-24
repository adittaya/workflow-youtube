#!/usr/bin/env python3
"""Lightweight flow recorder — logs URLs, DOM state, click targets. No screenshots."""
import os, sys, time, json
os.environ.setdefault("DISPLAY", ":0")
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

LOG_DIR = "/tmp/vplink_record"
os.makedirs(LOG_DIR, exist_ok=True)
LOG = open(os.path.join(LOG_DIR, "flow.log"), "w")
EVENTS = []

KEY = sys.argv[1] if len(sys.argv) > 1 else "UbpV2D"
URL = f"https://vplink.in/{KEY}"
start = time.time()

def log(msg):
    line = f"[{time.time()-start:.1f}s] {msg}"
    print(line, file=LOG, flush=True)
    print(line, flush=True)

def event(kind, **data):
    EVENTS.append({"t": round(time.time()-start, 1), "kind": kind, **data})

def dom():
    try:
        return driver.execute_script("""
            var r = {url: location.href, title: document.title, els: {}};
            ['get-link','gt-link','tp-time','tp-wait1','ce-time','ce-wait1',
             'link1s-wait1','startCountdownBtn','btn6','btn7','tp-snp2',
             'cross-snp2','block-cont-1','overcn'].forEach(function(id){
                var e = document.getElementById(id);
                if(e){var s=getComputedStyle(e);r.els[id]={tag:e.tagName,
                    href:(e.href||'').substring(0,120),text:(e.textContent||'').substring(0,80),
                    display:s.display,vis:s.visibility,disabled:!!e.disabled,visible:!!e.offsetParent};}
            });
            r.links=[];document.querySelectorAll('a[href]').forEach(function(a,i){
                if(i<25)r.links.push({id:a.id,href:(a.href||'').substring(0,120),text:(a.textContent||'').substring(0,40)});});
            r.iframes=document.querySelectorAll('iframe').length;
            r.bodyLen=(document.body||{}).innerHTML?.length||0;
            return r;
        """)
    except Exception as e:
        return {"error": str(e)}

def state_hash(d):
    """Compact hash of DOM state for change detection."""
    if not d or "error" in d: return ""
    return json.dumps(d.get("els",{}), sort_keys=True)[:200]

# ── Chrome ──
options = Options()
for a in ["--no-sandbox","--disable-gpu","--disable-dev-shm-usage",
          "--disable-blink-features=AutomationControlled","--use-gl=swiftshader","--window-size=390,844"]:
    options.add_argument(a)
options.binary_location = "/usr/bin/chromium-browser"

log("launching chrome...")
service = Service(executable_path="/usr/bin/chromedriver")
driver = webdriver.Chrome(service=service, options=options)
driver.set_page_load_timeout(30)

try:
    log(f"navigating to {URL}")
    driver.get(URL)
    d = dom()
    log(f"LOADED: {d.get('url','?')}")
    event("loaded", url=d.get("url",""), title=d.get("title",""), els=d.get("els",{}))
    log(f"DOM: {json.dumps(d, default=str)[:400]}")

    log("="*60)
    log("RECORDING — do the full flow now")
    log("Press Ctrl+C or close browser when done")
    log("="*60)

    last_url = ""
    last_hash = ""
    count = 0
    while True:
        time.sleep(2)
        count += 1
        try:
            cur = driver.current_url
        except:
            log("browser closed")
            break

        if cur != last_url:
            last_url = cur
            d = dom()
            h = state_hash(d)
            log(f"URL → {cur[:150]}")
            log(f"DOM: {json.dumps(d, default=str)[:500]}")
            event("url", url=cur, els=d.get("els",{}), links=d.get("links",[]))
            last_hash = h
        elif count % 10 == 0:
            d = dom()
            h = state_hash(d)
            if h != last_hash:
                log(f"DOM CHANGED (same URL): {cur[:100]}")
                log(f"DOM: {json.dumps(d, default=str)[:500]}")
                event("dom_change", url=cur, els=d.get("els",{}))
                last_hash = h

except KeyboardInterrupt:
    log("interrupted by user")
except Exception as e:
    log(f"ERROR: {e}")
finally:
    log("RECORDING DONE")
    try:
        final = driver.current_url
        log(f"Final URL: {final}")
        event("final", url=final)
    except: pass

    with open(os.path.join(LOG_DIR, "events.json"), "w") as f:
        json.dump(EVENTS, f, indent=2, default=str)

    LOG.close()
    try: driver.quit()
    except: pass
    print(f"\nSaved: {LOG_DIR}/flow.log + events.json")
