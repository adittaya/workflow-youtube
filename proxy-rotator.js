const config = require('./config');
const http = require('http');
const https = require('https');

const SUPABASE_REST = '/rest/v1';

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
  if (!resp.ok) {
    throw new Error(`Supabase query failed: ${resp.status} ${await resp.text().catch(() => '')}`);
  }
  return resp.json();
}

async function deleteProxy(ip, port) {
  const url = `/proxy_results?ip=eq.${encodeURIComponent(ip)}&port=eq.${port}`;
  const resp = await supabaseFetch(url, { method: 'DELETE' });
  return resp.ok;
}

async function markDead(ip, port) {
  const ok = await deleteProxy(ip, port);
  if (ok) console.error(`  [Proxy] Deleted dead proxy ${ip}:${port} from DB`);
  return ok;
}

// ── Quick alive check: HTTPS CONNECT to vplink.in ──
async function testProxyQuick(proxy, timeoutMs = 5000) {
  const start = Date.now();
  const result = await tryConnectQuick(proxy, 'vplink.in', '/gbd1b', timeoutMs);
  if (result) return { ok: true, latency_ms: Date.now() - start };
  const httpResult = await tryHttpQuick(proxy, 'vplink.in', '/gbd1b', timeoutMs);
  if (httpResult) return { ok: true, latency_ms: Date.now() - start };
  return { ok: false, latency_ms: Date.now() - start };
}

// ── Browser-level test: fetch actual page through proxy like Chrome ──
async function testProxyBrowser(proxy, timeoutMs = 12000) {
  const start = Date.now();
  const httpsOk = await tryBrowserConnect(proxy, 'vplink.in', '/gbd1b', timeoutMs);
  if (httpsOk) return { ok: true, latency_ms: Date.now() - start, protocol: 'https' };
  const httpOk = await tryBrowserPage(proxy, 'http', 'vplink.in', '/gbd1b', timeoutMs);
  if (httpOk) return { ok: true, latency_ms: Date.now() - start, protocol: 'http' };
  return { ok: false, latency_ms: Date.now() - start };
}

function tryBrowserPage(proxy, scheme, host, path, timeoutMs) {
  return new Promise((resolve) => {
    const url = scheme + '://' + host + path;
    let resolved = false;
    const timer = setTimeout(() => { if (!resolved) { resolved = true; req.destroy(); resolve(false); } }, timeoutMs);
    const req = http.request({
      hostname: proxy.ip, port: parseInt(proxy.port),
      path: url, method: 'GET',
      headers: {
        'Host': host,
        'User-Agent': 'Mozilla/5.0 (Linux; Android 15; Pixel 9 Pro) AppleWebKit/537.36 Chrome/127.0 Mobile Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml',
        'Accept-Language': 'en-US,en;q=0.9',
      },
      timeout: timeoutMs,
    }, (res) => {
      let data = '';
      res.on('data', (chunk) => {
        data += chunk;
        if (data.length > 500 && !resolved) { resolved = true; clearTimeout(timer); res.destroy(); resolve(true); }
      });
      res.on('end', () => { if (!resolved) { resolved = true; clearTimeout(timer); resolve(data.length > 100); } });
    });
    req.on('error', () => { if (!resolved) { resolved = true; clearTimeout(timer); resolve(false); } });
    req.on('timeout', () => { if (!resolved) { resolved = true; clearTimeout(timer); req.destroy(); resolve(false); } });
    req.end();
  });
}

function tryBrowserConnect(proxy, host, path, timeoutMs) {
  return new Promise((resolve) => {
    let resolved = false;
    const fail = () => { if (!resolved) { resolved = true; clearTimeout(timer); resolve(false); } };
    const timer = setTimeout(fail, timeoutMs);
    const connReq = http.request({
      hostname: proxy.ip, port: parseInt(proxy.port),
      method: 'CONNECT', path: host + ':443',
      timeout: timeoutMs,
    });
    connReq.on('connect', (res, socket) => {
      if (resolved) { socket.destroy(); return; }
      socket.setTimeout(timeoutMs);
      socket.on('error', () => fail());
      socket.on('timeout', () => { socket.destroy(); fail(); });
      const tlsReq = https.request({
        socket, hostname: host, path, method: 'GET',
        headers: { 'Host': host }, timeout: timeoutMs, rejectUnauthorized: false,
      }, (tlsRes) => {
        let data = '';
        tlsRes.on('data', (chunk) => { data += chunk; });
        tlsRes.on('end', () => { if (!resolved) { resolved = true; clearTimeout(timer); socket.destroy(); resolve(data.length > 50); } });
      });
      tlsReq.on('error', () => fail());
      tlsReq.on('timeout', () => { tlsReq.destroy(); fail(); });
      tlsReq.end();
    });
    connReq.on('error', () => fail());
    connReq.on('timeout', () => { connReq.destroy(); fail(); });
    connReq.on('response', (res) => { res.on('data', () => {}); res.on('end', () => fail()); });
    connReq.end();
  });
}

function tryConnectQuick(proxy, host, path, timeoutMs) {
  return new Promise((resolve) => {
    const timer = setTimeout(() => { connReq.destroy(); resolve(false); }, timeoutMs);
    const connReq = http.request({
      hostname: proxy.ip, port: proxy.port,
      method: 'CONNECT', path: host + ':443',
      timeout: timeoutMs,
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
        tlsRes.on('end', () => {
          resolve(tlsRes.statusCode >= 200 && tlsRes.statusCode < 400);
        });
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

// ══════════════════════════════════════════════════════════════════
// ENGINE 1 (Clean): Fetch ALL → alive test → delete dead from DB
// ENGINE 2 (Speed): Speed test alive → pick fastest
// ══════════════════════════════════════════════════════════════════
async function getProxy(tier = 'premium') {
  const CONCURRENCY = 50;

  // ═══ Engine 1: Fetch + Alive test + Delete dead ═══
  console.error('  [Engine 1] Fetching ALL proxies from Supabase...');
  const allProxies = await fetchProxies(tier);
  console.error(`  [Engine 1] Found ${allProxies.length} ${tier} proxies in DB`);
  if (allProxies.length === 0) return null;

  const shuffled = allProxies.sort(() => Math.random() - 0.5);

  console.error(`  [Engine 1] Quick alive test (${CONCURRENCY} parallel)...`);
  const alive = [];
  const dead = [];
  let completed = 0;
  for (let i = 0; i < shuffled.length; i += CONCURRENCY) {
    const batch = shuffled.slice(i, i + CONCURRENCY);
    const outcomes = await Promise.allSettled(batch.map(async (p) => {
      const quick = await testProxyQuick(p, 5000);
      return quick.ok ? { ...p, latency_ms: quick.latency_ms } : null;
    }));
    for (let j = 0; j < outcomes.length; j++) {
      const o = outcomes[j];
      if (o.status === 'fulfilled' && o.value) alive.push(o.value);
      else dead.push(batch[j]);
    }
    completed += batch.length;
    process.stderr.write(`  [Engine 1] Alive: ${completed}/${allProxies.length} (${alive.length} ok, ${dead.length} dead)\r`);
  }
  process.stderr.write('\n');
  console.error(`  [Engine 1] ${alive.length} alive, ${dead.length} dead`);

  if (dead.length > 0) {
    let deleted = 0;
    for (let i = 0; i < dead.length; i += 50) {
      const batch = dead.slice(i, i + 50);
      await Promise.allSettled(batch.map(async (p) => {
        if (await deleteProxy(p.ip, p.port)) deleted++;
      }));
      process.stderr.write(`  [Engine 1] Deleted ${deleted}/${dead.length}\r`);
    }
    process.stderr.write('\n');
    console.error(`  [Engine 1] Purged ${deleted} dead proxies from DB`);
  }

  if (alive.length === 0) {
    console.error('  [Engine 1] No alive proxies found');
    return null;
  }

  console.error(`  [Engine 1] Browser test (${alive.length} alive)...`);
  const browserAlive = [];
  const browserDead = [];
  completed = 0;
  for (let i = 0; i < alive.length; i += CONCURRENCY) {
    const batch = alive.slice(i, i + CONCURRENCY);
    const outcomes = await Promise.allSettled(batch.map(async (p) => {
      const browser = await testProxyBrowser(p, 12000);
      return browser.ok ? { ...p, latency_ms: browser.latency_ms, protocol: browser.protocol } : null;
    }));
    for (let j = 0; j < outcomes.length; j++) {
      const o = outcomes[j];
      if (o.status === 'fulfilled' && o.value) browserAlive.push(o.value);
      else browserDead.push(batch[j]);
    }
    completed += batch.length;
    process.stderr.write(`  [Engine 1] Browser: ${completed}/${alive.length} (${browserAlive.length} ok, ${browserDead.length} dead)\r`);
  }
  process.stderr.write('\n');

  if (browserDead.length > 0) {
    let deleted = 0;
    for (let i = 0; i < browserDead.length; i += 50) {
      const batch = browserDead.slice(i, i + 50);
      await Promise.allSettled(batch.map(async (p) => {
        if (await deleteProxy(p.ip, p.port)) deleted++;
      }));
    }
    console.error(`  [Engine 1] Purged ${deleted} more dead (failed browser test)`);
  }
  console.error(`  [Engine 1] ${browserAlive.length} proxies survived`);

  if (browserAlive.length === 0) {
    console.error('  [Engine 1] All dead');
    return null;
  }

  // ═══ Engine 2: Speed test + Pick fastest ═══
  console.error(`  [Engine 2] Speed testing ${browserAlive.length} proxies (${CONCURRENCY} parallel)...`);
  const speedResults = [];
  completed = 0;
  for (let i = 0; i < browserAlive.length; i += CONCURRENCY) {
    const batch = browserAlive.slice(i, i + CONCURRENCY);
    const outcomes = await Promise.allSettled(batch.map(async (p) => {
      const start = Date.now();
      let speed_kbps = 0;
      try {
        const total = await new Promise((resolve) => {
          const req = http.request({
            hostname: p.ip, port: parseInt(p.port),
            path: 'http://speedtest.tele2.net/100KB.zip', method: 'GET',
            headers: { 'Host': 'speedtest.tele2.net' }, timeout: 8000,
          }, (res) => {
            let t = 0;
            res.on('data', (chunk) => t += chunk.length);
            res.on('end', () => resolve(t));
            res.on('error', () => resolve(0));
          });
          req.on('error', () => resolve(0));
          req.on('timeout', () => { req.destroy(); resolve(0); });
          req.end();
        });
        const elapsed = (Date.now() - start) / 1000;
        speed_kbps = elapsed > 0 ? Math.round(total / elapsed / 1024) : 0;
      } catch {}
      return { ...p, speed_kbps };
    }));
    for (const o of outcomes) {
      if (o.status === 'fulfilled') speedResults.push(o.value);
    }
    completed += batch.length;
    process.stderr.write(`  [Engine 2] Speed: ${completed}/${browserAlive.length}\r`);
  }
  process.stderr.write('\n');

  speedResults.sort((a, b) => (b.speed_kbps || 0) - (a.speed_kbps || 0) || (a.latency_ms || 9999) - (b.latency_ms || 9999));

  const fast = speedResults.filter(p => p.speed_kbps >= 100).length;
  const medium = speedResults.filter(p => p.speed_kbps >= 50 && p.speed_kbps < 100).length;
  const slow = speedResults.filter(p => p.speed_kbps > 0 && p.speed_kbps < 50).length;
  console.error(`  [Engine 2] ${fast} fast, ${medium} medium, ${slow} slow`);

  const topN = Math.max(1, Math.ceil(speedResults.length * 0.3));
  const shortlist = speedResults.slice(0, topN);
  const history = config.loadProxyHistory();
  const picked = getRotationIndex(shortlist, history);
  if (!picked) {
    const fallback = shortlist[0];
    console.error(`  [Engine 2] Selected: ${fallback.ip}:${fallback.port} (${fallback.speed_kbps}KB/s, ${fallback.latency_ms}ms)`);
    return fallback;
  }

  console.error(`  [Engine 2] Selected: ${picked.ip}:${picked.port} (${picked.speed_kbps}KB/s, ${picked.latency_ms}ms)`);
  return picked;
}

// ── Quick: fetch from DB without live test ──
async function getProxyQuick(tier = 'premium') {
  const proxies = await fetchProxies(tier);
  if (proxies.length === 0) return null;

  const history = config.loadProxyHistory();
  const picked = getRotationIndex(proxies, history);
  if (!picked) {
    return proxies[Math.floor(Math.random() * proxies.length)];
  }
  return picked;
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
      const quickResult = await testProxyQuick(proxy, 5000);
      console.error(`  [Proxy] Quick alive: ${quickResult.ok} (${quickResult.latency_ms}ms)`);
      if (quickResult.ok) {
        const browserResult = await testProxyBrowser(proxy, 12000);
        console.error(`  [Proxy] Browser test: ${browserResult.ok} (${browserResult.latency_ms}ms, ${browserResult.protocol || 'none'})`);
        if (browserResult.ok) {
          console.log(`${ip}:${port}`);
          process.exit(0);
        }
      }
      console.error(`  [Proxy] ${ip}:${port} FAILED`);
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

module.exports = { getProxy, getProxyQuick, fetchProxies, testProxyQuick, testProxyBrowser, markDead, deleteProxy };
