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
  const ok = await deleteProxy(ip, port);
  if (ok) console.error(`  [Proxy] Deleted dead ${ip}:${port} from DB`);
  return ok;
}

async function batchDeleteDead(dead) {
  if (dead.length === 0) return 0;
  const outcomes = await Promise.allSettled(dead.map(p => deleteProxy(p.ip, p.port)));
  const deleted = outcomes.filter(o => o.status === 'fulfilled' && o.value).length;
  return deleted;
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
            && !finalUrl.includes('studiiessuniversitiess')
            && !finalUrl.includes('universitesstudiiess')
            && !finalUrl.includes('studiessuniversitiess')
            && !finalUrl.includes('studieseducates')
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
    console.error(`  [Engine 2] Deleting ${bad.length} proxies that failed Playwright validation from DB...`);
    await batchDeleteDead(bad);
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

// CLI: node proxy-rotator.js <tier> [--quick|--test <ip:port>]
if (require.main === module) {
  (async () => {
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

module.exports = { getProxy, getProxyQuick, fetchProxies, testProxyQuick, testProxyBrowser, testProxyPlaywright, markDead, deleteProxy, batchDeleteDead };
