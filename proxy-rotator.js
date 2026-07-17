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
  return fetch(url, { ...options, headers });
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

// ── Fast alive check: HTTPS CONNECT to vplink.in only ──
// Returns: { ok: true, latency_ms } or { ok: false }
async function testProxyQuick(proxy, timeoutMs = 5000) {
  const start = Date.now();
  const result = await tryConnectQuick(proxy, 'vplink.in', '/gbd1b', timeoutMs);
  if (result) {
    return { ok: true, latency_ms: Date.now() - start };
  }
  // Fallback: try HTTP absolute-form to vplink.in
  const httpResult = await tryHttpQuick(proxy, 'vplink.in', '/gbd1b', timeoutMs);
  if (httpResult) {
    return { ok: true, latency_ms: Date.now() - start };
  }
  return { ok: false, latency_ms: Date.now() - start };
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

// ── Full test: alive check + speed test via httpbin.org ──
async function testProxyFull(proxy) {
  const start = Date.now();
  const result = { ...proxy, latency_ms: 0, origin: '', speed_kbps: 0 };

  // Quick alive check first
  const quick = await testProxyQuick(proxy, 6000);
  if (!quick.ok) return null;

  result.latency_ms = quick.latency_ms;

  // Test target: try httpbin.org for origin IP, fallback to example.com
  const targets = [
    { host: 'httpbin.org', path: '/ip', json: true },
    { host: 'example.com', path: '/', json: false },
  ];

  for (const target of targets) {
    const origin = await tryConnectFull(proxy, target);
    if (origin) {
      result.origin = origin;
      // Speed test: download 100KB via HTTP proxy
      try {
        const speedStart = Date.now();
        const total = await new Promise((resolve) => {
          const req = http.request({
            hostname: proxy.ip, port: proxy.port,
            path: 'http://speedtest.tele2.net/100KB.zip', method: 'GET',
            headers: { 'Host': 'speedtest.tele2.net' }, timeout: 10000,
          }, (res) => {
            res.on('error', () => resolve(0));
            let t = 0;
            res.on('data', (chunk) => t += chunk.length);
            res.on('end', () => resolve(t));
          });
          req.on('error', () => resolve(0));
          req.on('timeout', () => { req.destroy(); resolve(0); });
          req.end();
        });
        const speedTime = (Date.now() - speedStart) / 1000;
        result.speed_kbps = speedTime > 0 ? Math.round(total / speedTime / 1024) : 0;
      } catch {}
      return result;
    }
  }
  return null;
}

function tryConnectFull(proxy, target) {
  return new Promise((resolve) => {
    const timer = setTimeout(() => { connReq.destroy(); resolve(null); }, 8000);
    const connReq = http.request({
      hostname: proxy.ip, port: proxy.port,
      method: 'CONNECT', path: target.host + ':443',
      timeout: 8000,
    });
    connReq.on('connect', (res, socket) => {
      socket.on('error', () => { clearTimeout(timer); resolve(null); });
      socket.on('timeout', () => { clearTimeout(timer); socket.destroy(); resolve(null); });
      socket.setTimeout(10000);
      const tlsReq = https.request({
        socket, hostname: target.host, path: target.path,
        method: 'GET', headers: { 'Host': target.host },
        timeout: 6000, rejectUnauthorized: false,
      }, (tlsRes) => {
        let data = '';
        tlsRes.on('data', (chunk) => data += chunk);
        tlsRes.on('end', () => {
          clearTimeout(timer);
          if (target.json) {
            try { const json = JSON.parse(data); resolve(json && json.origin ? json.origin : null); }
            catch { resolve(null); }
          } else {
            resolve(tlsRes.statusCode >= 200 && tlsRes.statusCode < 300 ? target.host : null);
          }
        });
      });
      tlsReq.on('error', () => { clearTimeout(timer); resolve(null); });
      tlsReq.on('timeout', () => { clearTimeout(timer); tlsReq.destroy(); resolve(null); });
      tlsReq.end();
    });
    connReq.on('response', (res) => { clearTimeout(timer); res.on('data', () => {}); res.on('end', () => resolve(null)); });
    connReq.on('error', () => { clearTimeout(timer); resolve(null); });
    connReq.on('timeout', () => { clearTimeout(timer); connReq.destroy(); resolve(null); });
    connReq.end();
  });
}

// ── Filter + purge: test all proxies, delete dead from DB ──
async function filterAndClean(tier = 'premium', concurrency = 20, deleteDead = false) {
  console.error('  [Proxy] Fetching proxies from Supabase...');
  const proxies = await fetchProxies(tier);
  console.error(`  [Proxy] Found ${proxies.length} ${tier} proxies`);

  const results = { working: [], dead: [] };
  let completed = 0;

  // Phase 1: Quick alive test (fast — 5s timeout each, 20 parallel)
  console.error('  [Proxy] Phase 1: Quick alive test...');
  for (let i = 0; i < proxies.length; i += concurrency) {
    const batch = proxies.slice(i, i + concurrency);
    const outcomes = await Promise.allSettled(batch.map(async (p) => {
      const quick = await testProxyQuick(p, 5000);
      return quick.ok ? p : null;
    }));
    for (let j = 0; j < batch.length; j++) {
      const alive = outcomes[j].status === 'fulfilled' ? outcomes[j].value : null;
      if (alive) {
        results.working.push({ ...alive, latency_ms: alive.latency_ms || 0 });
      } else {
        results.dead.push(batch[j]);
      }
    }
    completed += batch.length;
    process.stderr.write(`  [Proxy] Alive: ${completed}/${proxies.length} (${results.working.length} alive, ${results.dead.length} dead)\r`);
  }
  process.stderr.write('\n');

  // Delete dead proxies immediately (don't wait for Phase 2)
  if (deleteDead && results.dead.length > 0) {
    console.error(`  [Proxy] Deleting ${results.dead.length} dead proxies from DB...`);
    let deleted = 0;
    for (let i = 0; i < results.dead.length; i += 50) {
      const batch = results.dead.slice(i, i + 50);
      await Promise.allSettled(batch.map(async (p) => {
        if (await deleteProxy(p.ip, p.port)) deleted++;
      }));
      process.stderr.write(`  [Proxy] Deleted ${deleted}/${results.dead.length}\r`);
    }
    process.stderr.write('\n');
    console.error(`  [Proxy] Purged ${deleted} dead proxies`);
  }

  // Phase 2: Speed test alive proxies (optional — for ranking)
  if (results.working.length > 0) {
    console.error('  [Proxy] Phase 2: Speed testing alive proxies...');
    const speedTested = [];
    let speedDone = 0;
    for (let i = 0; i < results.working.length; i += concurrency) {
      const batch = results.working.slice(i, i + concurrency);
      const outcomes = await Promise.allSettled(batch.map(p => testProxyFull(p)));
      for (const o of outcomes) {
        if (o.status === 'fulfilled' && o.value) speedTested.push(o.value);
      }
      speedDone += batch.length;
      process.stderr.write(`  [Proxy] Speed: ${speedDone}/${results.working.length}\r`);
    }
    process.stderr.write('\n');

    const fast = speedTested.filter(p => p.speed_kbps >= 100).length;
    const medium = speedTested.filter(p => p.speed_kbps >= 50 && p.speed_kbps < 100).length;
    const slow = speedTested.filter(p => p.speed_kbps > 0 && p.speed_kbps < 50).length;
    console.error(`  [Proxy] Speed: ${fast} fast, ${medium} medium, ${slow} slow`);
    return speedTested;
  }

  console.error(`  [Proxy] ${results.working.length} working proxies available`);
  return results.working;
}

// ── Quick filter: alive-only test, no speed, no DB delete ──
async function filterQuick(tier = 'premium', concurrency = 30) {
  console.error('  [Proxy] Fetching proxies from Supabase...');
  const proxies = await fetchProxies(tier);
  console.error(`  [Proxy] Found ${proxies.length} ${tier} proxies`);

  const working = [];
  let completed = 0;

  for (let i = 0; i < proxies.length; i += concurrency) {
    const batch = proxies.slice(i, i + concurrency);
    const outcomes = await Promise.allSettled(batch.map(async (p) => {
      const quick = await testProxyQuick(p, 5000);
      return quick.ok ? { ...p, latency_ms: quick.latency_ms } : null;
    }));
    for (const o of outcomes) {
      if (o.status === 'fulfilled' && o.value) working.push(o.value);
    }
    completed += batch.length;
    process.stderr.write(`  [Proxy] Tested ${completed}/${proxies.length} (${working.length} alive)\r`);
  }
  process.stderr.write('\n');
  console.error(`  [Proxy] ${working.length} alive proxies`);
  return working;
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

// ── Main: get a working proxy (with live test + auto-delete dead) ──
async function getProxy(tier = 'premium') {
  // Fetch all proxies from DB
  console.error('  [Proxy] Fetching proxies from Supabase...');
  const allProxies = await fetchProxies(tier);
  console.error(`  [Proxy] Found ${allProxies.length} ${tier} proxies`);
  if (allProxies.length === 0) return null;

  // Random subset of 100 for fast testing (avoids testing all 500)
  const subset = allProxies.sort(() => Math.random() - 0.5).slice(0, 100);
  console.error(`  [Proxy] Testing random subset of ${subset.length}...`);

  const alive = [];
  const dead = [];
  let completed = 0;
  const concurrency = 30;

  for (let i = 0; i < subset.length; i += concurrency) {
    const batch = subset.slice(i, i + concurrency);
    const outcomes = await Promise.allSettled(batch.map(async (p) => {
      const quick = await testProxyQuick(p, 5000);
      return { proxy: p, ok: quick.ok, latency_ms: quick.latency_ms };
    }));
    for (const o of outcomes) {
      if (o.status === 'fulfilled' && o.value.ok) {
        alive.push({ ...o.value.proxy, latency_ms: o.value.latency_ms });
      } else {
        dead.push(batch[outcomes.indexOf(o)] || o.value?.proxy);
      }
    }
    completed += batch.length;
    process.stderr.write(`  [Proxy] Tested ${completed}/${subset.length} (${alive.length} alive, ${dead.length} dead)\r`);
  }
  process.stderr.write('\n');

  // Auto-delete dead proxies from DB
  if (dead.length > 0) {
    let deleted = 0;
    for (let i = 0; i < dead.length; i += 50) {
      const batch = dead.slice(i, i + 50);
      await Promise.allSettled(batch.filter(Boolean).map(async (p) => {
        if (await deleteProxy(p.ip, p.port)) deleted++;
      }));
    }
    console.error(`  [Proxy] Auto-deleted ${deleted} dead proxies from DB`);
  }

  if (alive.length === 0) {
    console.error('  [Proxy] No alive proxies in subset, testing full pool...');
    // Fallback: test remaining proxies
    const remaining = allProxies.filter(p => !subset.some(s => s.ip === p.ip && s.port === p.port));
    for (let i = 0; i < remaining.length; i += concurrency) {
      const batch = remaining.slice(i, i + concurrency);
      const outcomes = await Promise.allSettled(batch.map(async (p) => {
        const quick = await testProxyQuick(p, 5000);
        return quick.ok ? { ...p, latency_ms: quick.latency_ms } : null;
      }));
      for (const o of outcomes) {
        if (o.status === 'fulfilled' && o.value) alive.push(o.value);
      }
      completed += batch.length;
      process.stderr.write(`  [Proxy] Tested ${completed}/${allProxies.length} (${alive.length} alive)\r`);
    }
    process.stderr.write('\n');
  }

  console.error(`  [Proxy] ${alive.length} alive proxies`);
  if (alive.length === 0) return null;

  // Sort by latency (faster first)
  alive.sort((a, b) => (a.latency_ms || 9999) - (b.latency_ms || 9999));

  // Random pick from top 30%
  const topN = Math.max(1, Math.ceil(alive.length * 0.3));
  const shortlist = alive.slice(0, topN);

  const history = config.loadProxyHistory();
  const picked = getRotationIndex(shortlist, history);
  if (!picked) {
    console.error('  [Proxy] All proxies used in last 24h, recycling oldest');
    const fallback = shortlist[Math.floor(Math.random() * Math.min(shortlist.length, 5))];
    console.error(`  [Proxy] Selected: ${fallback.ip}:${fallback.port} (${fallback.latency_ms}ms)`);
    return fallback;
  }

  console.error(`  [Proxy] Selected: ${picked.ip}:${picked.port} (${picked.latency_ms}ms)`);
  return picked;
}

// ── Quick: fetch without live test (DB status only) ──
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

// ── Purge: test all proxies, delete dead from DB ──
async function purgeDead(tier = 'premium') {
  const working = await filterAndClean(tier, 20, true);
  if (working.length > 0) {
    working.sort((a, b) => (b.speed_kbps || 0) - (a.speed_kbps || 0) || (a.latency_ms || 9999) - (b.latency_ms || 9999));
    console.log(`${working[0].ip}:${working[0].port}`);
    console.error(`  [Proxy] Best: ${working[0].ip}:${working[0].port} (${working[0].speed_kbps || '?'} KB/s, ${working[0].latency_ms}ms)`);
  }
  process.exit(working.length > 0 ? 0 : 1);
}

// CLI: node proxy-rotator.js <tier> [--quick|--purge|--test <ip:port>]
// --quick: fetch without live test (use DB status only)
// --purge: test AND delete dead proxies from database
// --test ip:port: test a single proxy
// Outputs: ip:port (on stdout), all status messages go to stderr
if (require.main === module) {
  (async () => {
    const tier = process.argv[2] || 'premium';
    const purge = process.argv.includes('--purge');
    const quick = process.argv.includes('--quick');
    const testIdx = process.argv.indexOf('--test');
    const testTarget = testIdx >= 0 ? process.argv[testIdx + 1] : null;

    if (testTarget) {
      // Test single proxy
      const [ip, port] = testTarget.split(':');
      if (!ip || !port) { console.error('Usage: --test ip:port'); process.exit(1); }
      const proxy = { ip, port: parseInt(port), proto: 'https' };
      console.error(`  [Proxy] Testing ${ip}:${port}...`);
      const quickResult = await testProxyQuick(proxy, 5000);
      console.error(`  [Proxy] Alive: ${quickResult.ok} (${quickResult.latency_ms}ms)`);
      if (quickResult.ok) {
        const full = await testProxyFull(proxy);
        if (full) {
          console.error(`  [Proxy] Full test: origin=${full.origin}, speed=${full.speed_kbps} KB/s`);
          console.log(`${ip}:${port}`);
          process.exit(0);
        }
      }
      console.error(`  [Proxy] ${ip}:${port} is DEAD`);
      process.exit(1);
    } else if (purge) {
      purgeDead(tier);
    } else {
      const fn = quick ? getProxyQuick : getProxy;
      fn(tier).then(p => {
        if (p) console.log(`${p.ip}:${p.port}`);
        process.exit(p ? 0 : 1);
      }).catch(e => { console.error('  [Proxy] Error:', e.message); process.exit(1); });
    }
  })();
}

module.exports = { getProxy, getProxyQuick, filterAndClean, filterQuick, fetchProxies, testProxyQuick, testProxyFull, markDead, deleteProxy };
