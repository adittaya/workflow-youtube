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

async function testProxyQuick(proxy, timeoutMs = 5000) {
  const start = Date.now();
  const r = await tryConnectQuick(proxy, 'vplink.in', '/gbd1b', timeoutMs);
  if (r) return { ok: true, latency_ms: Date.now() - start };
  const h = await tryHttpQuick(proxy, 'vplink.in', '/gbd1b', timeoutMs);
  if (h) return { ok: true, latency_ms: Date.now() - start };
  return { ok: false, latency_ms: Date.now() - start };
}

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
      headers: { 'Host': host, 'User-Agent': 'Mozilla/5.0 (Linux; Android 15; Pixel 9 Pro) AppleWebKit/537.36 Chrome/127.0 Mobile Safari/537.36', 'Accept': 'text/html' },
      timeout: timeoutMs,
    }, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; if (data.length > 500 && !resolved) { resolved = true; clearTimeout(timer); res.destroy(); resolve(true); } });
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
      method: 'CONNECT', path: host + ':443', timeout: timeoutMs,
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
// Engine 1 (Clean): Quick alive test batch-by-batch, delete dead from DB
// Engine 2 (Speed): Browser test + speed test alive, pick fastest
// Returns FIRST working proxy found — does not test all 500.
// ══════════════════════════════════════════════════════════════════
async function getProxy(tier = 'premium') {
  const CONCURRENCY = 50;
  const BATCH_SIZE = 100;

  console.error('  [Engine 1] Fetching proxies from Supabase...');
  const allProxies = await fetchProxies(tier);
  console.error(`  [Engine 1] Found ${allProxies.length} ${tier} proxies in DB`);
  if (allProxies.length === 0) return null;

  const history = config.loadProxyHistory();
  const shuffled = allProxies.sort(() => Math.random() - 0.5);

  // Process in batches of 100 — stop as soon as we find a working proxy
  for (let bStart = 0; bStart < shuffled.length; bStart += BATCH_SIZE) {
    const batch = shuffled.slice(bStart, bStart + BATCH_SIZE);
    const batchNum = Math.floor(bStart / BATCH_SIZE) + 1;
    const totalBatches = Math.ceil(shuffled.length / BATCH_SIZE);

    // ── Engine 1: Quick alive test this batch ──
    console.error(`  [Engine 1] Batch ${batchNum}/${totalBatches}: alive test (${batch.length} proxies)...`);
    const alive = [];
    const dead = [];
    let completed = 0;
    for (let i = 0; i < batch.length; i += CONCURRENCY) {
      const chunk = batch.slice(i, i + CONCURRENCY);
      const outcomes = await Promise.allSettled(chunk.map(async (p) => {
        const q = await testProxyQuick(p, 5000);
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

    // Delete dead from DB
    if (dead.length > 0) {
      let deleted = 0;
      for (let i = 0; i < dead.length; i += 50) {
        const dBatch = dead.slice(i, i + 50);
        await Promise.allSettled(dBatch.map(async (p) => { if (await deleteProxy(p.ip, p.port)) deleted++; }));
      }
      console.error(`  [Engine 1] Batch ${batchNum}: deleted ${deleted} dead from DB`);
    }

    if (alive.length === 0) {
      console.error(`  [Engine 1] Batch ${batchNum}: no alive proxies, trying next...`);
      continue;
    }

    // ── Engine 2: Browser test + speed test alive proxies ──
    console.error(`  [Engine 1] Batch ${batchNum}: ${alive.length} alive → browser test...`);
    const browserAlive = [];
    const browserDead = [];
    completed = 0;
    for (let i = 0; i < alive.length; i += CONCURRENCY) {
      const chunk = alive.slice(i, i + CONCURRENCY);
      const outcomes = await Promise.allSettled(chunk.map(async (p) => {
        const b = await testProxyBrowser(p, 12000);
        return b.ok ? { ...p, latency_ms: b.latency_ms, protocol: b.protocol } : null;
      }));
      for (let j = 0; j < outcomes.length; j++) {
        const o = outcomes[j];
        if (o.status === 'fulfilled' && o.value) browserAlive.push(o.value);
        else browserDead.push(batch[j]);
      }
      completed += chunk.length;
      process.stderr.write(`  [Engine 1] Browser: ${completed}/${alive.length} (${browserAlive.length} ok)\r`);
    }
    process.stderr.write('\n');

    // Delete browser-failed from DB
    if (browserDead.length > 0) {
      let deleted = 0;
      for (let i = 0; i < browserDead.length; i += 50) {
        const dBatch = browserDead.slice(i, i + 50);
        await Promise.allSettled(dBatch.map(async (p) => { if (await deleteProxy(p.ip, p.port)) deleted++; }));
      }
      console.error(`  [Engine 1] Batch ${batchNum}: deleted ${deleted} more dead (browser failed)`);
    }

    if (browserAlive.length === 0) {
      console.error(`  [Engine 1] Batch ${batchNum}: all alive failed browser test, trying next...`);
      continue;
    }

    // ── Engine 2: Speed test ──
    console.error(`  [Engine 2] Speed testing ${browserAlive.length} proxies...`);
    const speedResults = [];
    completed = 0;
    for (let i = 0; i < browserAlive.length; i += CONCURRENCY) {
      const chunk = browserAlive.slice(i, i + CONCURRENCY);
      const outcomes = await Promise.allSettled(chunk.map(async (p) => {
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
      completed += chunk.length;
      process.stderr.write(`  [Engine 2] Speed: ${completed}/${browserAlive.length}\r`);
    }
    process.stderr.write('\n');

    speedResults.sort((a, b) => (b.speed_kbps || 0) - (a.speed_kbps || 0) || (a.latency_ms || 9999) - (b.latency_ms || 9999));

    const fast = speedResults.filter(p => p.speed_kbps >= 100).length;
    const medium = speedResults.filter(p => p.speed_kbps >= 50 && p.speed_kbps < 100).length;
    console.error(`  [Engine 2] ${fast} fast, ${medium} medium`);

    // Pick from top 30% with rotation
    const topN = Math.max(1, Math.ceil(speedResults.length * 0.3));
    const shortlist = speedResults.slice(0, topN);
    const picked = getRotationIndex(shortlist, history);
    if (!picked) {
      const fallback = shortlist[0];
      console.error(`  [Engine 2] Selected: ${fallback.ip}:${fallback.port} (${fallback.speed_kbps}KB/s)`);
      return fallback;
    }
    console.error(`  [Engine 2] Selected: ${picked.ip}:${picked.port} (${picked.speed_kbps}KB/s)`);
    return picked;
  }

  console.error('  [Engine] Exhausted all batches — no working proxy');
  return null;
}

async function getProxyQuick(tier = 'premium') {
  const proxies = await fetchProxies(tier);
  if (proxies.length === 0) return null;
  const history = config.loadProxyHistory();
  const picked = getRotationIndex(proxies, history);
  return picked || proxies[Math.floor(Math.random() * proxies.length)];
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
      const qr = await testProxyQuick(proxy, 5000);
      console.error(`  [Proxy] Quick: ${qr.ok} (${qr.latency_ms}ms)`);
      if (qr.ok) {
        const br = await testProxyBrowser(proxy, 12000);
        console.error(`  [Proxy] Browser: ${br.ok} (${br.latency_ms}ms)`);
        if (br.ok) { console.log(`${ip}:${port}`); process.exit(0); }
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

module.exports = { getProxy, getProxyQuick, fetchProxies, testProxyQuick, testProxyBrowser, markDead, deleteProxy };
