const config = require('./config');
const http = require('http');
const https = require('https');
const { chromium } = require('playwright');
const path = require('path');

const SUPABASE_REST = '/rest/v1';
const TEST_KEY = 'gbd1b';
const TEST_URL = `https://vplink.in/${TEST_KEY}`;

function supabaseFetch(endpoint, options = {}) {
  const cfg = config.load();
  const url = `${cfg.supabase_url}${SUPABASE_REST}${endpoint}`;
  const headers = {
    'apikey': cfg.supabase_secret || cfg.supabase_key,
    'Authorization': `Bearer ${cfg.supabase_secret || cfg.supabase_key}`,
    'Content-Type': 'application/json',
    ...options.headers,
  };
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), 25000);
  return fetch(url, { ...options, headers, signal: ac.signal }).finally(() => clearTimeout(timer));
}

async function fetchProxies(tier = 'premium') {
  const field = tier === 'premium' ? 'vplink_ok' : 'e2_ok';
  const url = `/proxy_results?select=ip,port,proto,country,latency_ms&${field}=eq.true&order=latency_ms.asc&limit=500`;
  const resp = await supabaseFetch(url);
  if (!resp.ok) throw new Error(`Supabase failed: ${resp.status}`);
  return resp.json();
}

async function deleteProxy(ip, port) {
  const url = `/proxy_results?ip=eq.${encodeURIComponent(ip)}&port=eq.${port}`;
  const resp = await supabaseFetch(url, { method: 'DELETE' });
  return resp.ok;
}

async function markDead(ip, port) {
  console.error(`  [Proxy] Proxy ${ip}:${port} failed — blacklisted locally (NOT deleted from DB)`);
  return true;
}

async function batchDeleteDead(dead) {
  if (dead.length === 0) return 0;
  console.error(`  [Proxy] ${dead.length} proxies failed alive test — keeping in DB for retry`);
  return 0;
}

// ══════════════════════════════════════════════════════════════════
//  TCP-level tests (fast, parallel, used in Engine 1)
// ══════════════════════════════════════════════════════════════════

function tryConnectQuick(proxy, host, path, timeoutMs) {
  return new Promise((resolve) => {
    const timer = setTimeout(() => { connReq.destroy(); resolve(false); }, timeoutMs);
    const connReq = http.request({
      hostname: proxy.ip, port: proxy.port,
      method: 'CONNECT', path: host + ':443', timeout: timeoutMs,
    });
    connReq.on('connect', (res, socket) => {
      const sockTimer = setTimeout(() => { socket.destroy(); resolve(false); }, timeoutMs);
      socket.on('error', () => { clearTimeout(sockTimer); resolve(false); });
      socket.on('timeout', () => { clearTimeout(sockTimer); socket.destroy(); resolve(false); });
      socket.setTimeout(timeoutMs);
      const tlsReq = https.request({
        socket, hostname: host, path, method: 'GET',
        headers: { 'Host': host }, timeout: timeoutMs, rejectUnauthorized: false,
      }, (tlsRes) => {
        clearTimeout(sockTimer);
        let data = '';
        tlsRes.on('data', (chunk) => data += chunk);
        tlsRes.on('end', () => resolve(tlsRes.statusCode >= 200 && tlsRes.statusCode < 400));
      });
      tlsReq.on('error', () => { clearTimeout(sockTimer); resolve(false); });
      tlsReq.on('timeout', () => { clearTimeout(sockTimer); tlsReq.destroy(); resolve(false); });
      tlsReq.end();
    });
    connReq.on('error', () => { clearTimeout(timer); resolve(false); });
    connReq.on('timeout', () => { clearTimeout(timer); connReq.destroy(); resolve(false); });
    connReq.on('response', (res) => { clearTimeout(timer); res.on('data', () => {}); res.on('end', () => resolve(false)); });
    connReq.end();
  });
}

function tryHttpQuick(proxy, host, path, timeoutMs) {
  return new Promise((resolve) => {
    const req = http.request({
      hostname: proxy.ip, port: proxy.port,
      path: 'http://' + host + path, method: 'GET',
      headers: { 'Host': host }, timeout: timeoutMs,
    }, (res) => {
      let data = '';
      res.on('data', (chunk) => data += chunk);
      res.on('end', () => resolve(res.statusCode >= 200 && res.statusCode < 400));
    });
    req.on('error', () => resolve(false));
    req.on('timeout', () => { req.destroy(); resolve(false); });
    req.end();
  });
}

async function testProxyQuick(proxy, timeoutMs = 3000) {
  const start = Date.now();
  const r = await tryConnectQuick(proxy, 'vplink.in', '/gbd1b', timeoutMs);
  if (r) return { ok: true, latency_ms: Date.now() - start };
  const h = await tryHttpQuick(proxy, 'vplink.in', '/gbd1b', timeoutMs);
  if (h) return { ok: true, latency_ms: Date.now() - start };
  return { ok: false, latency_ms: Date.now() - start };
}

// ══════════════════════════════════════════════════════════════════
//  Engine 2: Playwright browser validation
//  Tests proxy with REAL Chromium — catches what Node.js CONNECT can't.
// ══════════════════════════════════════════════════════════════════

let _browserPath = null;
function getBrowserPath() {
  if (_browserPath) return _browserPath;
  try {
    const execPath = chromium.executablePath();
    _browserPath = execPath;
    return execPath;
  } catch {
    return null;
  }
}

async function testProxyPlaywright(proxy, timeoutMs = 30000) {
  const proxyUrl = `http://${proxy.ip}:${proxy.port}`;
  const start = Date.now();
  let browser = null;
  try {
    browser = await chromium.launch({
      headless: true,
      args: [
        `--proxy-server=${proxyUrl}`,
        '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage',
        '--disable-blink-features=AutomationControlled',
        '--use-gl=swiftshader',
      ],
    });
    const ctx = await browser.newContext({
      viewport: { width: 1280, height: 720 },
      userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
    });
    const page = await ctx.newPage();

    let finalUrl = '';
    let passedVplink = false;
    let passedIntermediate = false;
    try {
      await page.goto(TEST_URL, { waitUntil: 'domcontentloaded', timeout: timeoutMs });

      for (let i = 0; i < 25; i++) {
        await page.waitForTimeout(1000);
        finalUrl = page.url();

        if (finalUrl.includes('chrome-error') || finalUrl.includes('about:blank')) break;

        if (!passedVplink && !finalUrl.includes('vplink.in')) {
          passedVplink = true;
        }

        if (passedVplink && !finalUrl.includes('vplink.in')
            && !finalUrl.includes('learn_more.php')
            && finalUrl.includes('/')) {
          passedIntermediate = true;
          break;
        }
      }
    } catch {
      finalUrl = 'chrome-error';
    }

    const isGood = finalUrl && !finalUrl.includes('chrome-error') && !finalUrl.includes('about:blank')
      && passedVplink && passedIntermediate;
    const totalMs = Date.now() - start;

    await browser.close().catch(() => {});
    browser = null;

    return { ok: isGood, latency_ms: totalMs, finalUrl };
  } catch (e) {
    if (browser) await browser.close().catch(() => {});
    return { ok: false, latency_ms: Date.now() - start, error: e.message };
  }
}

async function testProxyBatchPlaywright(proxies, timeoutMs = 30000, concurrency = 5) {
  const results = [];
  for (let i = 0; i < proxies.length; i += concurrency) {
    const chunk = proxies.slice(i, i + concurrency);
    const outcomes = await Promise.allSettled(chunk.map(p => testProxyPlaywright(p, timeoutMs)));
    for (let j = 0; j < outcomes.length; j++) {
      const o = outcomes[j];
      if (o.status === 'fulfilled') {
        results.push({ ...chunk[j], ...o.value });
      } else {
        results.push({ ...chunk[j], ok: false, latency_ms: 99999 });
      }
    }
    process.stderr.write(`  [Engine 2] Playwright: ${Math.min(i + concurrency, proxies.length)}/${proxies.length} tested\r`);
  }
  process.stderr.write('\n');
  return results;
}

// ══════════════════════════════════════════════════════════════════
//  Main getProxy: Engine 1 (TCP alive) → Engine 2 (Playwright validate)
// ══════════════════════════════════════════════════════════════════

function getRotationIndex(proxies, history) {
  const now = Date.now();
  const cutoff = now - 24 * 60 * 60 * 1000;
  const recent = new Set(
    history.used.filter(e => e.timestamp > cutoff).map(e => `${e.ip}:${e.port}`)
  );
  const available = proxies.filter(p => !recent.has(`${p.ip}:${p.port}`));
  if (available.length === 0) return null;
  const picked = available[Math.floor(Math.random() * available.length)];
  history.used.push({ ip: picked.ip, port: picked.port, timestamp: now });
  history.used = history.used.filter(e => e.timestamp > cutoff);
  config.saveProxyHistory(history);
  return picked;
}

async function getProxy(tier = 'premium') {
  const CONCURRENCY = 50;
  const BATCH_SIZE = 200;
  const ENGINE2_MAX = 30;

  console.error('  [Engine 1] Fetching proxies from Supabase...');
  const allProxies = await fetchProxies(tier);
  console.error(`  [Engine 1] Found ${allProxies.length} ${tier} proxies in DB`);
  if (allProxies.length === 0) return null;

  const blacklist = config.loadProxyBlacklist();
  const proxies = blacklist.length > 0
    ? allProxies.filter(p => !blacklist.includes(`${p.ip}:${p.port}`))
    : allProxies;
  if (blacklist.length > 0) console.error(`  [Engine 1] Blacklist: ${blacklist.length} excluded, ${proxies.length} remaining`);
  if (proxies.length === 0) return null;

  const history = config.loadProxyHistory();
  const shuffled = proxies.sort(() => Math.random() - 0.5);

  let allAlive = [];

  for (let bStart = 0; bStart < shuffled.length; bStart += BATCH_SIZE) {
    const batch = shuffled.slice(bStart, bStart + BATCH_SIZE);
    const batchNum = Math.floor(bStart / BATCH_SIZE) + 1;
    const totalBatches = Math.ceil(shuffled.length / BATCH_SIZE);

    console.error(`  [Engine 1] Batch ${batchNum}/${totalBatches}: TCP alive test (${batch.length} proxies, 3s timeout)...`);
    const alive = [];
    const dead = [];
    let completed = 0;
    for (let i = 0; i < batch.length; i += CONCURRENCY) {
      const chunk = batch.slice(i, i + CONCURRENCY);
      const outcomes = await Promise.allSettled(chunk.map(async (p) => {
        const q = await testProxyQuick(p, 3000);
        return q.ok ? { ...p, latency_ms: q.latency_ms } : null;
      }));
      for (let j = 0; j < outcomes.length; j++) {
        const o = outcomes[j];
        if (o.status === 'fulfilled' && o.value) alive.push(o.value);
        else dead.push(batch[j]);
      }
      completed += chunk.length;
      process.stderr.write(`  [Engine 1] Alive: ${completed}/${batch.length} (${alive.length} ok, ${dead.length} dead)\r`);
    }
    process.stderr.write('\n');

    allAlive.push(...alive);

    if (allAlive.length >= ENGINE2_MAX) {
      console.error(`  [Engine 1] ${allAlive.length} alive proxies found (cap ${ENGINE2_MAX}), moving to Engine 2...`);
      break;
    }

    if (alive.length >= 10) {
      console.error(`  [Engine 1] Batch ${batchNum}: ${alive.length} alive, enough for Engine 2...`);
      break;
    }
  }

  if (allAlive.length === 0) {
    console.error('  [Engine 1] No alive proxies found in any batch');
    return null;
  }

  allAlive.sort((a, b) => (a.latency_ms || 9999) - (b.latency_ms || 9999));
  const candidates = allAlive.slice(0, ENGINE2_MAX);

  console.error(`  [Engine 2] Playwright validation: testing ${candidates.length} proxies with real Chromium browser...`);
  const pwResults = await testProxyBatchPlaywright(candidates, 30000, 5);

  const good = pwResults.filter(p => p.ok);
  const bad = pwResults.filter(p => !p.ok);
  if (bad.length > 0) {
    console.error(`  [Engine 2] Blacklisting ${bad.length} proxies that failed Playwright validation (local only — not deleting from DB)`);
    // Only blacklist locally — don't delete from DB. Playwright validation failure
    // is not proof the proxy is dead (network conditions vary per run).
    // DB deletion only happens via reportProxyFailure() for real runtime failures.
    const config = require('./config');
    for (const p of bad) {
      if (p.ip && p.port) config.addProxyBlacklist(p.ip, p.port);
    }
  }
  if (good.length === 0) {
    console.error('  [Engine 2] All proxies failed Playwright validation');
    return null;
  }

  good.sort((a, b) => (a.latency_ms || 9999) - (b.latency_ms || 9999));

  const fast = good.filter(p => p.latency_ms < 15000).length;
  const medium = good.filter(p => p.latency_ms >= 15000 && p.latency_ms < 25000).length;
  console.error(`  [Engine 2] ${good.length} passed (${fast} fast, ${medium} medium)`);

  const topN = Math.max(1, Math.ceil(good.length * 0.3));
  const shortlist = good.slice(0, topN);
  const picked = getRotationIndex(shortlist, history);
  if (picked) {
    console.error(`  [Engine 2] Selected: ${picked.ip}:${picked.port} (${picked.latency_ms}ms via Playwright)`);
    return picked;
  }
  const fallback = shortlist[0];
  console.error(`  [Engine 2] Selected (fallback): ${fallback.ip}:${fallback.port} (${fallback.latency_ms}ms via Playwright)`);
  return fallback;
}

// ══════════════════════════════════════════════════════════════════
//  getProxyQuick: lightweight — still tests alive, but skips Playwright
// ══════════════════════════════════════════════════════════════════

async function getProxyQuick(tier = 'premium') {
  const proxies = await fetchProxies(tier);
  if (proxies.length === 0) return null;

  const blacklist = config.loadProxyBlacklist();
  const filtered = blacklist.length > 0
    ? proxies.filter(p => !blacklist.includes(`${p.ip}:${p.port}`))
    : proxies;
  if (filtered.length === 0) return null;

  const shuffled = filtered.sort(() => Math.random() - 0.5);
  const candidates = shuffled.slice(0, 50);

  const alive = [];
  for (let i = 0; i < candidates.length; i += 25) {
    const chunk = candidates.slice(i, i + 25);
    const outcomes = await Promise.allSettled(chunk.map(async (p) => {
      const q = await testProxyQuick(p, 3000);
      return q.ok ? { ...p, latency_ms: q.latency_ms } : null;
    }));
    for (const o of outcomes) {
      if (o.status === 'fulfilled' && o.value) alive.push(o.value);
    }
    if (alive.length >= 5) break;
  }

  if (alive.length === 0) return null;
  alive.sort((a, b) => (a.latency_ms || 9999) - (b.latency_ms || 9999));

  const history = config.loadProxyHistory();
  const picked = getRotationIndex(alive.slice(0, 10), history);
  return picked || alive[0];
}

// ══════════════════════════════════════════════════════════════════
//  Legacy exports (kept for backward compatibility)
// ══════════════════════════════════════════════════════════════════

async function testProxyBrowser(proxy, timeoutMs = 12000) {
  const result = await testProxyPlaywright(proxy, timeoutMs);
  return { ok: result.ok, latency_ms: result.latency_ms, protocol: 'playwright' };
}

// ══════════════════════════════════════════════════════════════════
//  Proxy IP Verification — confirm browser traffic routes through proxy
// ══════════════════════════════════════════════════════════════════

async function getPublicIP(timeoutMs = 10000) {
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), timeoutMs);
  try {
    const res = await fetch('https://api.ipify.org?format=json', { signal: ac.signal });
    const data = await res.json();
    return data.ip;
  } catch {
    try {
      const res = await fetch('https://ifconfig.me/ip', { signal: ac.signal });
      return (await res.text()).trim();
    } catch {
      return null;
    }
  } finally {
    clearTimeout(timer);
  }
}

async function verifyProxyIP(proxy) {
  const { chromium } = require('playwright');
  const proxyUrl = `http://${proxy.ip}:${proxy.port}`;
  const BOLD = '\x1b[1m', GREEN = '\x1b[32m', YELLOW = '\x1b[33m',
        CYAN = '\x1b[36m', RED = '\x1b[31m', DIM = '\x1b[2m', NC = '\x1b[0m';
  const check = '\u2713', cross = '\u2717', warn = '\u26a0';

  console.log('');
  console.log(`${BOLD}  Proxy IP Verification${NC}`);
  console.log(`  ${DIM}──────────────────────${NC}`);

  // Step 1: Get real (direct) IP
  console.log(`  ${CYAN}Fetching direct IP (no proxy)...${NC}`);
  const realIP = await getPublicIP();
  if (realIP) {
    console.log(`  ${GREEN}${check}${NC} Direct IP: ${BOLD}${realIP}${NC}`);
  } else {
    console.log(`  ${YELLOW}${warn}${NC} Could not determine direct IP`);
  }

  // Step 2: Launch browser with proxy
  console.log(`  ${CYAN}Launching browser via proxy ${proxy.ip}:${proxy.port}...${NC}`);
  let browser = null;
  try {
    browser = await chromium.launch({
      headless: true,
      args: [
        `--proxy-server=${proxyUrl}`,
        '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage',
        '--disable-blink-features=AutomationControlled', '--use-gl=swiftshader',
      ],
    });
    const ctx = await browser.newContext({
      viewport: { width: 1280, height: 720 },
      userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
    });
    const page = await ctx.newPage();

    // Navigate to IP checker
    console.log(`  ${CYAN}Checking browser IP via api.ipify.org...${NC}`);
    let proxyIP = null;
    try {
      await page.goto('https://api.ipify.org?format=json', { waitUntil: 'domcontentloaded', timeout: 15000 });
      const body = await page.textContent('body');
      const data = JSON.parse(body);
      proxyIP = data.ip;
    } catch {
      // Try fallback
      try {
        await page.goto('https://ifconfig.me/ip', { waitUntil: 'domcontentloaded', timeout: 10000 });
        proxyIP = (await page.textContent('body')).trim();
      } catch {}
    }

    await browser.close();
    browser = null;

    if (!proxyIP) {
      console.log(`  ${RED}${cross}${NC} Could not determine browser IP — proxy may be blocking`);
      return false;
    }

    console.log(`  ${GREEN}${check}${NC} Browser IP: ${BOLD}${proxyIP}${NC}`);
    console.log('');

    // Step 3: Compare
    if (realIP && proxyIP === realIP) {
      console.log(`  ${RED}${cross}${NC} IP match! Proxy ${RED}NOT working${NC} — traffic bypassing proxy`);
      console.log(`  ${DIM}  Browser IP (${proxyIP}) == Direct IP (${realIP})${NC}`);
      return false;
    } else if (realIP && proxyIP !== realIP) {
      console.log(`  ${GREEN}${check}${NC} IP differs! Proxy ${GREEN}WORKING${NC} — traffic routing through proxy`);
      console.log(`  ${DIM}  Direct: ${realIP} → Proxy: ${proxyIP}${NC}`);
      return true;
    } else {
      console.log(`  ${YELLOW}${warn}${NC} Proxy responding but direct IP unknown — cannot verify`);
      return true;
    }
  } catch (e) {
    if (browser) await browser.close().catch(() => {});
    console.log(`  ${RED}${cross}${NC} Browser launch failed: ${e.message}`);
    return false;
  }
}

// ══════════════════════════════════════════════════════════════════
//  Proxy Setup Wizard — question-based CLI for proxy configuration
// ══════════════════════════════════════════════════════════════════

async function proxySetupWizard() {
  const readline = require('readline');
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  const ask = (q) => new Promise(r => rl.question(q, a => r(a.trim())));
  const askSecret = (q) => new Promise(r => {
    const rl2 = readline.createInterface({ input: process.stdin, output: process.stdout, terminal: true });
    rl2.question(q, a => { rl2.close(); console.log(''); r(a.trim()); });
  });

  const cfg = config.load();
  const GREEN = '\x1b[32m', YELLOW = '\x1b[33m', CYAN = '\x1b[36m', BOLD = '\x1b[1m', DIM = '\x1b[2m', NC = '\x1b[0m';
  const check = '\u2713', cross = '\u2717', warn = '\u26a0';

  console.log('');
  console.log(`${BOLD}╔══════════════════════════════════════════════════════════╗${NC}`);
  console.log(`${BOLD}║         VPLink 3.0 — Proxy Setup Wizard                ║${NC}`);
  console.log(`${BOLD}╚══════════════════════════════════════════════════════════╝${NC}`);
  console.log('');
  console.log(`${DIM}  VPLink uses rotating proxies from a Supabase database.`);
  console.log(`  You need a Supabase project with a proxy_results table.`);
  console.log(`  Press Enter to keep current values (shown in brackets).${NC}`);
  console.log('');

  // ── Step 1: Enable/disable ──
  const currentEnabled = cfg.proxy_enabled ? 'Y' : 'n';
  const ena = await ask(`  Enable proxy rotation? [${currentEnabled}]: `);
  let proxyEnabled = cfg.proxy_enabled;
  if (ena !== '') proxyEnabled = ena !== 'n' && ena !== 'N';

  if (!proxyEnabled) {
    console.log('');
    console.log(`  ${GREEN}${check}${NC} Proxy disabled — running without proxy`);
    config.save({ proxy_enabled: false });
    rl.close();
    return;
  }

  // ── Step 2: Supabase URL ──
  const defaultUrl = cfg.supabase_url || 'https://bytemjjijgwwcrxlgutf.supabase.co';
  const urlDisplay = defaultUrl.length > 40 ? defaultUrl.slice(0, 40) + '...' : defaultUrl;
  const url = await ask(`  Supabase URL [${urlDisplay}]: `);
  const supabaseUrl = url || defaultUrl;

  // ── Step 3: Supabase Anon Key ──
  const keyDisplay = cfg.supabase_key ? cfg.supabase_key.slice(0, 12) + '...' : 'empty';
  const key = await ask(`  Supabase Anon Key [${keyDisplay}]: `);
  const supabaseKey = key || cfg.supabase_key || '';

  // ── Step 4: Supabase Secret Key ──
  const secretDisplay = cfg.supabase_secret ? '(set)' : 'empty';
  const secret = await askSecret(`  Supabase Secret Key [${secretDisplay}]: `);
  const supabaseSecret = secret || cfg.supabase_secret || '';

  // ── Step 5: Tier ──
  const tierDefault = cfg.proxy_tier || 'premium';
  const tier = await ask(`  Proxy tier (free/premium) [${tierDefault}]: `);
  const proxyTier = tier || tierDefault;

  // ── Validate credentials ──
  console.log('');
  console.log(`  ${CYAN}Validating credentials...${NC}`);

  // Temporarily save to test
  config.save({
    supabase_url: supabaseUrl,
    supabase_key: supabaseKey,
    supabase_secret: supabaseSecret,
    proxy_enabled: true,
    proxy_tier: proxyTier,
  });

  let proxies = [];
  try {
    proxies = await fetchProxies(proxyTier);
    console.log(`  ${GREEN}${check}${NC} Connected to Supabase — ${proxies.length} ${proxyTier} proxies found`);
  } catch (e) {
    console.log(`  ${RED}${cross}${NC} Supabase connection failed: ${e.message}`);
    console.log('');
    const retry = await ask(`  Fix credentials now? [Y/n]: `);
    if (retry !== 'n' && retry !== 'N') {
      rl.close();
      return proxySetupWizard(); // retry
    }
    console.log(`  ${YELLOW}${warn}${NC} Saving anyway — proxy will fail at runtime`);
    rl.close();
    return;
  }

  if (proxies.length === 0) {
    console.log(`  ${YELLOW}${warn}${NC} No ${proxyTier} proxies in database — proxy will be unavailable`);
    rl.close();
    return;
  }

  // ── Health check: TCP test 5 random proxies ──
  console.log(`  ${CYAN}Testing proxy pool health...${NC}`);
  const sample = proxies.sort(() => Math.random() - 0.5).slice(0, 5);
  let alive = 0;
  const results = await Promise.allSettled(sample.map(p => testProxyQuick(p, 3000)));
  for (const r of results) {
    if (r.status === 'fulfilled' && r.value.ok) alive++;
  }

  if (alive > 0) {
    console.log(`  ${GREEN}${check}${NC} Pool healthy — ${alive}/${sample.length} test proxies alive`);
  } else {
    console.log(`  ${YELLOW}${warn}${NC} 0/${sample.length} test proxies alive — pool may be depleted`);
    console.log(`  ${DIM}  (This is normal after many runs. Engine 2 Playwright validation will find working ones.)${NC}`);
  }

  // ── Summary ──
  console.log('');
  console.log(`  ${GREEN}${check}${NC} Proxy configured:`);
  console.log(`     URL:    ${supabaseUrl}`);
  console.log(`     Key:    ${supabaseKey ? supabaseKey.slice(0, 12) + '...' : '(empty)'}`);
  console.log(`     Secret: ${supabaseSecret ? '(set)' : '(empty)'}`);
  console.log(`     Tier:   ${proxyTier}`);
  console.log(`     Pool:   ${proxies.length} proxies in DB`);
  console.log('');
  console.log(`  Run ${BOLD}vplink3.0${NC} to start with proxy rotation`);
  console.log(`  Run ${BOLD}vplink3.0 proxy --status${NC} to check pool health`);
  console.log('');

  rl.close();
}

async function proxyStatus() {
  const cfg = config.load();
  const GREEN = '\x1b[32m', YELLOW = '\x1b[33m', CYAN = '\x1b[36m', RED = '\x1b[31m', BOLD = '\x1b[1m', DIM = '\x1b[2m', NC = '\x1b[0m';
  const check = '\u2713', cross = '\u2717', warn = '\u26a0';

  console.log('');
  console.log(`${BOLD}  Proxy Status${NC}`);
  console.log(`  ${DIM}─────────────${NC}`);
  console.log(`  Enabled: ${cfg.proxy_enabled ? `${GREEN}yes${NC}` : `${YELLOW}no${NC}`}`);
  console.log(`  Tier:    ${cfg.proxy_tier || 'premium'}`);
  console.log(`  URL:     ${cfg.supabase_url ? cfg.supabase_url.slice(0, 40) + '...' : '(not set)'}`);
  console.log(`  Key:     ${cfg.supabase_key ? 'set' : '(not set)'}`);
  console.log(`  Secret:  ${cfg.supabase_secret ? 'set' : '(not set)'}`);

  const bl = config.loadProxyBlacklist();
  console.log(`  Blacklist: ${bl.length} entries`);
  console.log('');

  if (!cfg.proxy_enabled) {
    console.log(`  ${YELLOW}${warn}${NC} Proxy disabled. Run ${BOLD}vplink3.0 proxy --setup${NC} to enable`);
    return;
  }
  if (!cfg.supabase_url || !cfg.supabase_key || !cfg.supabase_secret) {
    console.log(`  ${RED}${cross}${NC} Credentials incomplete. Run ${BOLD}vplink3.0 proxy --setup${NC}`);
    return;
  }

  console.log(`  ${CYAN}Fetching proxies...${NC}`);
  let proxies;
  try {
    proxies = await fetchProxies(cfg.proxy_tier || 'premium');
  } catch (e) {
    console.log(`  ${RED}${cross}${NC} Fetch failed: ${e.message}`);
    return;
  }
  console.log(`  ${GREEN}${check}${NC} ${proxies.length} proxies in DB`);

  if (proxies.length === 0) {
    console.log(`  ${YELLOW}${warn}${NC} Empty pool — add proxies to Supabase proxy_results table`);
    return;
  }

  console.log(`  ${CYAN}TCP health check (5 random)...${NC}`);
  const sample = proxies.sort(() => Math.random() - 0.5).slice(0, 5);
  let alive = 0;
  const results = await Promise.allSettled(sample.map(p => testProxyQuick(p, 3000)));
  for (let i = 0; i < results.length; i++) {
    const r = results[i];
    const p = sample[i];
    const ok = r.status === 'fulfilled' && r.value.ok;
    if (ok) alive++;
    console.log(`    ${ok ? GREEN + check : RED + cross}${NC} ${p.ip}:${p.port} ${ok ? '(' + r.value.latency_ms + 'ms)' : 'FAIL'}`);
  }
  console.log('');
  console.log(`  ${alive > 0 ? GREEN + check : YELLOW + warn}${NC} ${alive}/${sample.length} alive`);
  console.log('');
}

// CLI: node proxy-rotator.js <tier> [--quick|--test <ip:port>|--setup|--status|--verify-ip|--verify <ip:port>]
if (require.main === module) {
  (async () => {
    if (process.argv.includes('--setup')) {
      await proxySetupWizard();
      process.exit(0);
    }
    if (process.argv.includes('--status')) {
      await proxyStatus();
      process.exit(0);
    }
    if (process.argv.includes('--verify-ip')) {
      // Get a proxy from pool and verify its IP
      const cfg = config.load();
      if (!cfg.proxy_enabled || !cfg.supabase_key || !cfg.supabase_secret) {
        console.error('  Proxy not configured. Run: vplink3.0 proxy --setup');
        process.exit(1);
      }
      console.error('  [Proxy] Getting proxy from pool...');
      const proxy = await getProxy(cfg.proxy_tier || 'premium');
      if (!proxy) { console.error('  [Proxy] No proxy available'); process.exit(1); }
      console.error(`  [Proxy] Got: ${proxy.ip}:${proxy.port}`);
      const ok = await verifyProxyIP(proxy);
      process.exit(ok ? 0 : 1);
    }
    const verifyIdx = process.argv.indexOf('--verify');
    if (verifyIdx >= 0) {
      const verifyTarget = process.argv[verifyIdx + 1];
      if (verifyTarget) {
        const [ip, port] = verifyTarget.split(':');
        if (!ip || !port) { console.error('Usage: --verify ip:port'); process.exit(1); }
        const ok = await verifyProxyIP({ ip, port: parseInt(port) });
        process.exit(ok ? 0 : 1);
      } else {
        console.error('Usage: --verify ip:port');
        process.exit(1);
      }
    }

    const tier = process.argv[2] || 'premium';
    const quick = process.argv.includes('--quick');
    const testIdx = process.argv.indexOf('--test');
    const testTarget = testIdx >= 0 ? process.argv[testIdx + 1] : null;

    if (testTarget) {
      const [ip, port] = testTarget.split(':');
      if (!ip || !port) { console.error('Usage: --test ip:port'); process.exit(1); }
      const proxy = { ip, port: parseInt(port), proto: 'https' };
      console.error(`  [Proxy] Testing ${ip}:${port}...`);

      console.error('  [Proxy] TCP alive test...');
      const qr = await testProxyQuick(proxy, 3000);
      console.error(`  [Proxy] TCP: ${qr.ok ? 'PASS' : 'FAIL'} (${qr.latency_ms}ms)`);

      if (qr.ok) {
        console.error('  [Proxy] Playwright browser test...');
        const pr = await testProxyPlaywright(proxy, 30000);
        console.error(`  [Proxy] Playwright: ${pr.ok ? 'PASS' : 'FAIL'} (${pr.latency_ms}ms)`);
        if (pr.ok) { console.log(`${ip}:${port}`); process.exit(0); }
      }
      process.exit(1);
    } else {
      const fn = quick ? getProxyQuick : getProxy;
      fn(tier).then(p => {
        if (p) console.log(`${p.ip}:${p.port}`);
        process.exit(p ? 0 : 1);
      }).catch(e => { console.error('  [Proxy] Error:', e.message); process.exit(1); });
    }
  })();
}

module.exports = { getProxy, getProxyQuick, fetchProxies, testProxyQuick, testProxyBrowser, testProxyPlaywright, markDead, deleteProxy, batchDeleteDead, proxySetupWizard, proxyStatus, verifyProxyIP, getPublicIP };
