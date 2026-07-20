import http.client
import http.server
import os
import socket
import ssl
import sys
import time
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

import requests as req_lib

import config

SUPABASE_REST = "/rest/v1"
TEST_KEY = "gbd1b"
TEST_URL = f"https://vplink.in/{TEST_KEY}"


def supabase_fetch(endpoint, method="GET", timeout=25):
    cfg = config.load()
    url = f"{cfg['supabase_url']}{SUPABASE_REST}{endpoint}"
    headers = {
        "apikey": cfg.get("supabase_secret") or cfg.get("supabase_key", ""),
        "Authorization": f"Bearer {cfg.get('supabase_secret') or cfg.get('supabase_key', '')}",
        "Content-Type": "application/json",
    }
    try:
        resp = req_lib.request(method, url, headers=headers, timeout=timeout)
        return resp
    except Exception as e:
        raise RuntimeError(f"Supabase request failed: {e}")


def fetch_proxies(tier="premium"):
    field = "vplink_ok" if tier == "premium" else "e2_ok"
    endpoint = f"/proxy_results?select=ip,port,proto,country,latency_ms&{field}=eq.true&order=latency_ms.asc&limit=500"
    resp = supabase_fetch(endpoint)
    if not resp.ok:
        raise RuntimeError(f"Supabase failed: {resp.status_code}")
    return resp.json()


def delete_proxy(ip, port):
    endpoint = f"/proxy_results?ip=eq.{req_lib.utils.quote(str(ip), safe='')}&port=eq.{port}"
    resp = supabase_fetch(endpoint, method="DELETE")
    return resp.ok


def mark_dead(ip, port):
    ok = delete_proxy(ip, port)
    if ok:
        print(f"  [Proxy] Deleted dead {ip}:{port} from DB", file=sys.stderr)
    return ok


def batch_delete_dead(dead_list):
    if not dead_list:
        return 0
    deleted = 0
    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = {pool.submit(delete_proxy, p["ip"], p["port"]): p for p in dead_list}
        for f in as_completed(futures):
            try:
                if f.result():
                    deleted += 1
            except Exception:
                pass
    return deleted


# ══════════════════════════════════════════════════════════════
#  TCP-level tests (fast, parallel, Engine 1)
# ══════════════════════════════════════════════════════════════

def _try_connect_quick(proxy, host, path, timeout_ms):
    start = time.time()
    try:
        conn = http.client.HTTPConnection(proxy["ip"], int(proxy["port"]), timeout=timeout_ms / 1000)
        conn.set_tunnel(host, 443)
        conn.request("GET", path, headers={"Host": host})
        res = conn.getresponse()
        data = res.read(2048)
        conn.close()
        elapsed = int((time.time() - start) * 1000)
        if 200 <= res.status < 400:
            return {"ok": True, "latency_ms": elapsed}
    except Exception:
        pass
    return {"ok": False, "latency_ms": int((time.time() - start) * 1000)}


def test_proxy_quick(proxy, timeout_ms=3000):
    r = _try_connect_quick(proxy, "vplink.in", f"/{TEST_KEY}", timeout_ms)
    if r["ok"]:
        return r
    start = time.time()
    try:
        proxies_dict = {
            "http": f"http://{proxy['ip']}:{proxy['port']}",
            "https": f"http://{proxy['ip']}:{proxy['port']}",
        }
        resp = req_lib.get(TEST_URL, proxies=proxies_dict, timeout=timeout_ms / 1000)
        elapsed = int((time.time() - start) * 1000)
        if resp.ok:
            return {"ok": True, "latency_ms": elapsed}
    except Exception:
        pass
    return {"ok": False, "latency_ms": int((time.time() - start) * 1000)}


# ══════════════════════════════════════════════════════════════
#  Engine 2: Selenium browser validation
# ══════════════════════════════════════════════════════════════

def test_proxy_selenium(proxy, timeout_s=60):
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service

    proxy_url = f"http://{proxy['ip']}:{proxy['port']}"
    start = time.time()
    driver = None
    try:
        options = Options()
        options.add_argument(f"--proxy-server={proxy_url}")
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--use-gl=swiftshader")
        options.add_argument("--window-size=1280,720")
        options.add_argument(
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
        )
        options.binary_location = "/usr/bin/chromium-browser"
        try:
            driver = webdriver.Chrome(options=options)
        except Exception:
            chromedriver_path = "/usr/bin/chromedriver"
            if os.path.exists(chromedriver_path):
                service = Service(executable_path=chromedriver_path)
                driver = webdriver.Chrome(service=service, options=options)
            else:
                from webdriver_manager.chrome import ChromeDriverManager
                service = Service(ChromeDriverManager().install())
                driver = webdriver.Chrome(service=service, options=options)

        driver.set_page_load_timeout(30)

        try:
            driver.get(TEST_URL)
        except Exception:
            pass
        time.sleep(1)

        passed_vplink = False
        passed_intermediate = False
        final_url = ""
        for _ in range(20):
            time.sleep(1)
            final_url = driver.current_url
            if "chrome-error" in final_url or "about:blank" in final_url or final_url.startswith("data:"):
                break
            if not passed_vplink and "vplink.in" not in final_url:
                passed_vplink = True
            if passed_vplink and "vplink.in" not in final_url and "learn_more.php" not in final_url and "studiiessuniversitiess" not in final_url and "universitesstudiiess" not in final_url and "studiessuniversitiess" not in final_url and "studieseducates" not in final_url:
                passed_intermediate = True
                break

        is_good = bool(
            final_url
            and "chrome-error" not in final_url
            and "about:blank" not in final_url
            and not final_url.startswith("data:")
            and passed_vplink
            and passed_intermediate
        )
        total_ms = int((time.time() - start) * 1000)
        driver.quit()
        driver = None
        return {"ok": is_good, "latency_ms": total_ms, "finalUrl": final_url}

    except Exception as e:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
        return {"ok": False, "latency_ms": int((time.time() - start) * 1000), "error": str(e)}


def test_proxy_batch_selenium(proxies, timeout_s=60, concurrency=10):
    results = []
    for i in range(0, len(proxies), concurrency):
        chunk = proxies[i : i + concurrency]
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {pool.submit(test_proxy_selenium, p, timeout_s): p for p in chunk}
            for f in as_completed(futures):
                p = futures[f]
                try:
                    r = f.result(timeout=timeout_s + 10)
                    results.append({**p, **r})
                except Exception:
                    results.append({**p, "ok": False, "latency_ms": 99999, "error": "timeout"})
        done = min(i + concurrency, len(proxies))
        for r in results[-len(chunk):]:
            ok = "OK" if r.get("ok") else "FAIL"
            tag = r.get("finalUrl", "")[:40] or r.get("error", "")[:40] or "?"
            print(f"  [Engine 2] {ok} {r['latency_ms']}ms {r['ip']}:{r['port']}  {tag}", file=sys.stderr)
    return results


# ══════════════════════════════════════════════════════════════
#  Main getProxy: Engine 1 (TCP alive) → Engine 2 (Selenium validate)
# ══════════════════════════════════════════════════════════════

def get_rotation_index(proxies, history):
    now_ms = int(time.time() * 1000)
    cutoff = now_ms - 24 * 60 * 60 * 1000
    recent = {
        e["ip"] + ":" + str(e["port"])
        for e in history.get("used", [])
        if e.get("timestamp", 0) > cutoff
    }
    available = [p for p in proxies if f"{p['ip']}:{p['port']}" not in recent]
    if not available:
        return None
    picked = random.choice(available)
    if "used" not in history:
        history["used"] = []
    history["used"].append({"ip": picked["ip"], "port": picked["port"], "timestamp": now_ms})
    history["used"] = [e for e in history["used"] if e.get("timestamp", 0) > cutoff]
    config.save_proxy_history(history)
    return picked


import random


def get_proxy(tier="premium"):
    BATCH_SIZE = 200

    print("  [Engine 1] Fetching proxies from Supabase...", file=sys.stderr)
    all_proxies = fetch_proxies(tier)
    print(f"  [Engine 1] Found {len(all_proxies)} {tier} proxies in DB", file=sys.stderr)
    if not all_proxies:
        return None

    blacklist = config.load_proxy_blacklist()
    if blacklist:
        bl_set = set(blacklist)
        proxies = [p for p in all_proxies if f"{p['ip']}:{p['port']}" not in bl_set]
        print(f"  [Engine 1] Blacklist: {len(blacklist)} excluded, {len(proxies)} remaining", file=sys.stderr)
    else:
        proxies = all_proxies
    if not proxies:
        return None

    history = config.load_proxy_history()
    shuffled = proxies[:]
    random.shuffle(shuffled)

    all_alive = []
    for b_start in range(0, len(shuffled), BATCH_SIZE):
        batch = shuffled[b_start : b_start + BATCH_SIZE]
        batch_num = b_start // BATCH_SIZE + 1
        total_batches = (len(shuffled) + BATCH_SIZE - 1) // BATCH_SIZE

        print(
            f"  [Engine 1] Batch {batch_num}/{total_batches}: TCP alive test ({len(batch)} proxies, 3s timeout)...",
            file=sys.stderr,
        )
        alive = []
        dead = []
        with ThreadPoolExecutor(max_workers=50) as pool:
            futures = {}
            for p in batch:
                futures[pool.submit(test_proxy_quick, p, 3000)] = p
            for f in as_completed(futures):
                p = futures[f]
                try:
                    r = f.result()
                    if r["ok"]:
                        alive.append({**p, "latency_ms": r["latency_ms"]})
                    else:
                        dead.append(p)
                except Exception:
                    dead.append(p)
        print(
            f"  [Engine 1] Alive: {len(alive)}/{len(batch)} ({len(alive)} ok, {len(dead)} dead)\r",
            end="",
            file=sys.stderr,
        )
        if dead:
            n = batch_delete_dead(dead)
            print(f"\r  [Engine 1] Deleted {n}/{len(dead)} dead from DB", file=sys.stderr)

        all_alive.extend(alive)
        if len(alive) >= 20:
            print(f"  [Engine 1] Batch {batch_num}: {len(alive)} alive, enough for rotation pool", file=sys.stderr)
            break

    print("", file=sys.stderr)

    if not all_alive:
        print("  [Engine 1] No alive proxies found in any batch", file=sys.stderr)
        return None

    all_alive.sort(key=lambda p: p.get("latency_ms", 9999))
    shortlist = all_alive[:20]

    print(f"  [Engine 1] {len(all_alive)} alive, picking from top {len(shortlist)} fastest", file=sys.stderr)

    picked = get_rotation_index(shortlist, history)
    if picked:
        print(f"  [Engine 1] Selected: {picked['ip']}:{picked['port']} ({picked.get('latency_ms', '?')}ms)", file=sys.stderr)
        return picked
    if shortlist:
        fallback = shortlist[0]
        print(f"  [Engine 1] Selected (fallback): {fallback['ip']}:{fallback['port']} ({fallback.get('latency_ms', '?')}ms)", file=sys.stderr)
        return fallback
    print("  [Engine 1] All alive proxies already used today", file=sys.stderr)
    return None


def get_proxy_quick(tier="premium"):
    proxies = fetch_proxies(tier)
    if not proxies:
        return None

    blacklist = config.load_proxy_blacklist()
    if blacklist:
        bl_set = set(blacklist)
        filtered = [p for p in proxies if f"{p['ip']}:{p['port']}" not in bl_set]
    else:
        filtered = proxies
    if not filtered:
        return None

    random.shuffle(filtered)
    candidates = filtered[:50]

    alive = []
    for i in range(0, len(candidates), 25):
        chunk = candidates[i : i + 25]
        with ThreadPoolExecutor(max_workers=25) as pool:
            futures = {pool.submit(test_proxy_quick, p, 3000): p for p in chunk}
            for f in as_completed(futures):
                try:
                    r = f.result()
                    if r["ok"]:
                        alive.append({**futures[f], "latency_ms": r["latency_ms"]})
                except Exception:
                    pass
        if len(alive) >= 5:
            break

    if not alive:
        return None
    alive.sort(key=lambda p: p.get("latency_ms", 9999))

    history = config.load_proxy_history()
    return get_rotation_index(alive[:10], history) or alive[0]


def get_public_ip(timeout_s=10):
    try:
        r = req_lib.get("https://api.ipify.org?format=json", timeout=timeout_s)
        return r.json().get("ip")
    except Exception:
        try:
            r = req_lib.get("https://ifconfig.me/ip", timeout=timeout_s)
            return r.text.strip()
        except Exception:
            return None


def verify_proxy_ip(proxy):
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    BOLD = "\033[1m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    CYAN = "\033[36m"
    RED = "\033[31m"
    DIM = "\033[2m"
    NC = "\033[0m"
    check = "\u2713"
    cross = "\u2717"
    warn = "\u26a0"

    print("")
    print(f"{BOLD}  Proxy IP Verification{NC}")
    print(f"  {DIM}{'─' * 22}{NC}")

    print(f"  {CYAN}Fetching direct IP (no proxy)...{NC}")
    real_ip = get_public_ip()
    if real_ip:
        print(f"  {GREEN}{check}{NC} Direct IP: {BOLD}{real_ip}{NC}")
    else:
        print(f"  {YELLOW}{warn}{NC} Could not determine direct IP")

    proxy_url = f"http://{proxy['ip']}:{proxy['port']}"
    print(f"  {CYAN}Launching browser via proxy {proxy['ip']}:{proxy['port']}...{NC}")
    driver = None
    try:
        options = Options()
        options.add_argument(f"--proxy-server={proxy_url}")
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--use-gl=swiftshader")
        options.add_argument("--window-size=1280,720")
        options.binary_location = "/usr/bin/chromium-browser"

        try:
            driver = webdriver.Chrome(options=options)
        except Exception:
            chromedriver_path = "/usr/bin/chromedriver"
            if os.path.exists(chromedriver_path):
                service = Service(executable_path=chromedriver_path)
                driver = webdriver.Chrome(service=service, options=options)
            else:
                from webdriver_manager.chrome import ChromeDriverManager
                service = Service(ChromeDriverManager().install())
                driver = webdriver.Chrome(service=service, options=options)

        driver.set_page_load_timeout(15)
        driver.implicitly_wait(10)

        print(f"  {CYAN}Checking browser IP via api.ipify.org...{NC}")
        proxy_ip = None
        try:
            driver.get("https://api.ipify.org?format=json")
            body = driver.find_element("tag name", "body").text
            proxy_ip = json.loads(body).get("ip")
        except Exception:
            try:
                driver.get("https://ifconfig.me/ip")
                proxy_ip = driver.find_element("tag name", "body").text.strip()
            except Exception:
                pass

        driver.quit()
        driver = None

        if not proxy_ip:
            print(f"  {RED}{cross}{NC} Could not determine browser IP — proxy may be blocking")
            return False

        print(f"  {GREEN}{check}{NC} Browser IP: {BOLD}{proxy_ip}{NC}")
        print("")

        if real_ip and proxy_ip == real_ip:
            print(f"  {RED}{cross}{NC} IP match! Proxy {RED}NOT working{NC} — traffic bypassing proxy")
            print(f"  {DIM}  Browser IP ({proxy_ip}) == Direct IP ({real_ip}){NC}")
            return False
        elif real_ip and proxy_ip != real_ip:
            print(f"  {GREEN}{check}{NC} IP differs! Proxy {GREEN}WORKING{NC} — traffic routing through proxy")
            print(f"  {DIM}  Direct: {real_ip} → Proxy: {proxy_ip}{NC}")
            return True
        else:
            print(f"  {YELLOW}{warn}{NC} Proxy responding but direct IP unknown — cannot verify")
            return True
    except Exception as e:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
        print(f"  {RED}{cross}{NC} Browser launch failed: {e}")
        return False


if __name__ == "__main__":
    import argparse

    if "--setup" in sys.argv:
        if not sys.stdin.isatty():
            print("No interactive terminal. Set env vars:", file=sys.stderr)
            print("  SUPABASE_URL=https://... SUPABASE_KEY=... SUPABASE_SECRET=...", file=sys.stderr)
            sys.exit(1)

        BOLD = "\033[1m"; GREEN = "\033[32m"; YELLOW = "\033[33m"
        CYAN = "\033[36m"; RED = "\033[31m"; DIM = "\033[2m"; NC = "\033[0m"
        check = "\u2713"; cross = "\u2717"; warn = "\u26a0"

        cfg = config.load()

        print(f"\n{BOLD}Proxy Setup Wizard{NC}")
        print(f"{DIM}{'─' * 50}{NC}\n")

        # 1. Enable/disable
        current_enabled = cfg.get("proxy_enabled", False)
        default = "y" if current_enabled else "n"
        ans = input(f"Enable proxy rotation? (y/N) [{default}]: ").strip().lower()
        ans = ans or default
        if ans not in ("y", "yes"):
            config.save({"proxy_enabled": False})
            print(f"  {YELLOW}{warn}{NC} Proxy disabled. Re-run {BOLD}vplink3.0 proxy --setup{NC} to enable.\n")
            sys.exit(0)

        # 2. Supabase URL
        default_url = "https://bytemjjijgwwcrxlgutf.supabase.co"
        current_url = cfg.get("supabase_url") or default_url
        ans = input(f"Supabase URL [{current_url}]: ").strip()
        sb_url = ans or current_url

        # 3. Supabase Anon Key
        current_key = cfg.get("supabase_key", "")
        key_hint = current_key[:12] + "..." if len(current_key) > 12 else "(not set)"
        ans = input(f"Supabase Anon/Publishable Key [{key_hint}]: ").strip()
        sb_key = ans or current_key

        # 4. Supabase Secret
        current_secret = cfg.get("supabase_secret", "")
        sec_hint = current_secret[:12] + "..." if len(current_secret) > 12 else "(not set)"
        ans = input(f"Supabase Secret/Service Key [{sec_hint}]: ").strip()
        sb_secret = ans or current_secret

        if not sb_key or not sb_secret:
            print(f"  {YELLOW}{warn}{NC} Key or secret missing — saving with proxy disabled.")
            config.save({"supabase_url": sb_url, "supabase_key": sb_key, "supabase_secret": sb_secret, "proxy_enabled": False})
            sys.exit(1)

        # 5. Proxy tier
        current_tier = cfg.get("proxy_tier", "premium")
        ans = input(f"Proxy tier? (normal/premium) [{current_tier}]: ").strip().lower()
        tier = ans or current_tier
        if tier not in ("normal", "premium"):
            print(f"  Invalid tier '{tier}', using 'premium'")
            tier = "premium"

        # 6. Save credentials
        config.save({
            "supabase_url": sb_url,
            "supabase_key": sb_key,
            "supabase_secret": sb_secret,
            "proxy_enabled": True,
            "proxy_tier": tier,
        })
        print(f"  {GREEN}{check}{NC} Credentials saved to ~/.vplink3.0/config.json\n")

        # 7. Validate
        print(f"  Validating credentials...", end=" ", flush=True)
        try:
            proxies = fetch_proxies(tier)
            print(f"{GREEN}{check}{NC}")
            print(f"  {GREEN}{check}{NC} {len(proxies)} {tier} proxies in Supabase")
        except Exception as e:
            print(f"{RED}{cross}{NC}")
            print(f"  {RED}{cross}{NC} Validation failed: {e}")
            print(f"  {YELLOW}{warn}{NC} Credentials saved but may be invalid. Check and re-run: {BOLD}vplink3.0 proxy --setup{NC}")
            sys.exit(1)

        # 8. Pool health check
        ans = input(f"\n  Run pool health check (test 5 random proxies)? (Y/n): ").strip().lower()
        if ans not in ("n", "no"):
            print(f"\n  Testing random proxies...")
            sample = proxies[:]
            random.shuffle(sample)
            sample = sample[:5]
            alive = 0
            with ThreadPoolExecutor(max_workers=5) as pool:
                futures = {pool.submit(test_proxy_quick, p, 3000): p for p in sample}
                for f in as_completed(futures):
                    p = futures[f]
                    try:
                        r = f.result()
                        if r.get("ok"):
                            alive += 1
                            print(f"    {GREEN}{check}{NC} {p['ip']}:{p['port']} ({r.get('latency_ms', '?')}ms)")
                        else:
                            print(f"    {RED}{cross}{NC} {p['ip']}:{p['port']} (dead)")
                    except Exception as e:
                        print(f"    {RED}{cross}{NC} {p['ip']}:{p['port']} (error: {e})")
            print(f"\n  {alive}/{len(sample)} proxies alive")

        print(f"\n{GREEN}{BOLD}Setup complete.{NC} Run {BOLD}vplink3.0{NC} to start.\n")
        sys.exit(0)

    if "--status" in sys.argv:
        cfg = config.load()
        GREEN = "\033[32m"
        YELLOW = "\033[33m"
        CYAN = "\033[36m"
        RED = "\033[31m"
        BOLD = "\033[1m"
        DIM = "\033[2m"
        NC = "\033[0m"
        check = "\u2713"
        cross = "\u2717"
        warn = "\u26a0"

        print("")
        print(f"{BOLD}  Proxy Status{NC}")
        print(f"  {DIM}{'─' * 11}{NC}")
        print(f"  Enabled: {GREEN if cfg.get('proxy_enabled') else YELLOW}{'yes' if cfg.get('proxy_enabled') else 'no'}{NC}")
        print(f"  Tier:    {cfg.get('proxy_tier', 'premium')}")
        print(f"  URL:     {cfg.get('supabase_url', '')[:40] + '...' if cfg.get('supabase_url') else '(not set)'}")
        print(f"  Key:     {'set' if cfg.get('supabase_key') else '(not set)'}")
        print(f"  Secret:  {'set' if cfg.get('supabase_secret') else '(not set)'}")
        bl = config.load_proxy_blacklist()
        print(f"  Blacklist: {len(bl)} entries")
        print("")
        if not cfg.get("proxy_enabled"):
            print(f"  {YELLOW}{warn}{NC} Proxy disabled. Run {BOLD}vplink3.0 proxy --setup{NC} to enable")
            sys.exit(0)
        if not (cfg.get("supabase_url") and cfg.get("supabase_key") and cfg.get("supabase_secret")):
            print(f"  {RED}{cross}{NC} Credentials incomplete. Run {BOLD}vplink3.0 proxy --setup{NC}")
            sys.exit(1)
        try:
            proxies = fetch_proxies(cfg.get("proxy_tier", "premium"))
        except Exception as e:
            print(f"  {RED}{cross}{NC} Fetch failed: {e}")
            sys.exit(1)
        print(f"  {GREEN}{check}{NC} {len(proxies)} proxies in DB")
        if not proxies:
            print(f"  {YELLOW}{warn}{NC} Empty pool")
            sys.exit(0)
        sample = proxies[:]
        random.shuffle(sample)
        sample = sample[:5]
        alive = 0
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = {pool.submit(test_proxy_quick, p, 3000): p for p in sample}
            for f in as_completed(futures):
                p = futures[f]
                try:
                    r = f.result()
                    if r["ok"]:
                        alive += 1
                        print(f"    {GREEN}{check}{NC} {p['ip']}:{p['port']} ({r['latency_ms']}ms)")
                    else:
                        print(f"    {RED}{cross}{NC} {p['ip']}:{p['port']} FAIL")
                except Exception:
                    print(f"    {RED}{cross}{NC} {p['ip']}:{p['port']} FAIL")
        print(f"  {GREEN if alive else YELLOW}{check if alive else warn}{NC} {alive}/{len(sample)} alive")
        print("")
        sys.exit(0)

    if "--test" in sys.argv:
        idx = sys.argv.index("--test")
        target = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else None
        if not target or ":" not in target:
            print("Usage: --test ip:port", file=sys.stderr)
            sys.exit(1)
        ip, port = target.split(":", 1)
        proxy = {"ip": ip, "port": int(port), "proto": "https"}
        print(f"  [Proxy] Testing {ip}:{port}...", file=sys.stderr)
        qr = test_proxy_quick(proxy, 3000)
        print(f"  [Proxy] TCP: {'PASS' if qr['ok'] else 'FAIL'} ({qr['latency_ms']}ms)", file=sys.stderr)
        if qr["ok"]:
            pr = test_proxy_selenium(proxy, 30)
            print(f"  [Proxy] Selenium: {'PASS' if pr['ok'] else 'FAIL'} ({pr['latency_ms']}ms)", file=sys.stderr)
            if pr["ok"]:
                print(f"{ip}:{port}")
                sys.exit(0)
        sys.exit(1)

    if "--verify-ip" in sys.argv:
        cfg = config.load()
        if not cfg.get("proxy_enabled") or not cfg.get("supabase_key") or not cfg.get("supabase_secret"):
            print("  Proxy not configured. Run: vplink3.0 proxy --setup", file=sys.stderr)
            sys.exit(1)
        print("  [Proxy] Getting proxy from pool...", file=sys.stderr)
        proxy = get_proxy(cfg.get("proxy_tier", "premium"))
        if not proxy:
            print("  [Proxy] No proxy available", file=sys.stderr)
            sys.exit(1)
        print(f"  [Proxy] Got: {proxy['ip']}:{proxy['port']}", file=sys.stderr)
        ok = verify_proxy_ip(proxy)
        sys.exit(0 if ok else 1)

    if "--quick" in sys.argv:
        tier = "premium"
        for a in sys.argv[1:]:
            if not a.startswith("-"):
                tier = a
                break
        p = get_proxy_quick(tier)
        if p:
            print(f"{p['ip']}:{p['port']}")
            sys.exit(0)
        sys.exit(1)

    tier = "premium"
    for a in sys.argv[1:]:
        if not a.startswith("-"):
            tier = a
            break
    try:
        p = get_proxy(tier)
        if p:
            print(f"{p['ip']}:{p['port']}")
            sys.exit(0)
        sys.exit(1)
    except Exception as e:
        print(f"  [Proxy] Error: {e}", file=sys.stderr)
        sys.exit(1)
