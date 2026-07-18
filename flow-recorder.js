const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const KEY = process.argv[2] || 'UbpV2D';
const RECORDING_DIR = path.join(__dirname, 'recordings', 'recording_' + new Date().toISOString().replace(/[:.]/g, '-'));
const SCREENSHOTS_DIR = path.join(RECORDING_DIR, 'screenshots');
const SNAPSHOTS_DIR = path.join(RECORDING_DIR, 'snapshots');
const NETWORK_LOG = path.join(RECORDING_DIR, 'network.jsonl');
const CONSOLE_LOG = path.join(RECORDING_DIR, 'console.jsonl');
const EVENTS_LOG = path.join(RECORDING_DIR, 'events.jsonl');
const SUMMARY_LOG = path.join(RECORDING_DIR, 'summary.json');

fs.mkdirSync(SCREENSHOTS_DIR, { recursive: true });
fs.mkdirSync(SNAPSHOTS_DIR, { recursive: true });

const startTime = Date.now();
let frameCount = 0;
const events = [];
const networkEvents = [];
const consoleEvents = [];

function log(tag, msg) {
  const ts = ((Date.now() - startTime) / 1000).toFixed(1);
  const line = `[${ts}s] [${tag}] ${msg}`;
  console.log(line);
  fs.appendFileSync(EVENTS_LOG, JSON.stringify({ ts: Date.now() - startTime, tag, msg }) + '\n');
}

async function screenshot(page, label) {
  frameCount++;
  const prefix = String(frameCount).padStart(4, '0');
  try {
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, `${prefix}_${label}.png`), fullPage: false });
  } catch {}
}

async function saveDOM(page, label) {
  try {
    const html = await page.content();
    const prefix = String(frameCount).padStart(4, '0');
    fs.writeFileSync(path.join(SNAPSHOTS_DIR, `${prefix}_${label}.html`));
  } catch {}
}

async function dumpButtonStates(page) {
  try {
    const states = await page.evaluate(() => {
      const selectors = [
        '#tp-snp2', '#cross-snp2', '#btn6', '#btn7', '#btn7 > button',
        '#continueBtn', '#tp-generate a', '#ce-generate a',
        '#get-link', '#link1s-wait1', '#adOverlay button',
        '#main > div:nth-child(4) > center > center > a'
      ];
      const result = {};
      for (const sel of selectors) {
        try {
          const el = document.querySelector(sel);
          if (el) {
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            result[sel] = {
              exists: true,
              visible: rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden',
              text: (el.textContent || '').trim().substring(0, 60),
              href: el.href || '',
              disabled: el.classList.contains('disabled') || el.disabled,
              opacity: style.opacity,
              display: style.display,
              offsetParent: el.offsetParent !== null,
            };
          } else {
            result[sel] = { exists: false };
          }
        } catch { result[sel] = { error: true }; }
      }
      // Also check for countdown/timer elements
      const timers = document.querySelectorAll('[id*="wait"], [id*="time"], [class*="timer"], [class*="countdown"]');
      result._timers = Array.from(timers).map(t => ({
        id: t.id, class: t.className?.substring?.(0, 50) || '',
        text: (t.textContent || '').trim().substring(0, 40),
        visible: t.offsetParent !== null || getComputedStyle(t).display !== 'none',
      }));
      // Check for popup overlays
      const popups = document.querySelectorAll('[class*="overlay"], [class*="popup"], [class*="modal"], [id*="continueBtn"]');
      result._popups = Array.from(popups).map(p => ({
        id: p.id, class: p.className?.substring?.(0, 50) || '',
        visible: getComputedStyle(p).display !== 'none' && getComputedStyle(p).visibility !== 'hidden',
        position: getComputedStyle(p).position,
      }));
      return result;
    });
    log('BUTTONS', JSON.stringify(states));
    return states;
  } catch (e) {
    log('BUTTONS', 'ERROR: ' + e.message);
    return null;
  }
}

async function main() {
  log('INIT', `Recording to ${RECORDING_DIR}`);
  log('INIT', `Target: https://vplink.in/${KEY}`);

  const browser = await chromium.launch({
    headless: false,
    args: [
      '--no-sandbox',
      '--disable-gpu',
      '--disable-blink-features=AutomationControlled',
      '--disable-dev-shm-usage',
      '--window-size=1280,720',
      '--disable-features=TranslateUI',
      '--disable-extensions',
    ],
  });

  const context = await browser.newContext({
    viewport: { width: 1280, height: 720 },
    userAgent: 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
    locale: 'en-US',
    bypassCSP: false,
  });

  // Stealth
  await context.addInitScript(() => {
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
    window.chrome = { runtime: {} };
    try {
      navigator.permissions.query = (params) =>
        Promise.resolve({ state: params.name === 'notifications' ? 'denied' : 'prompt' });
    } catch {}
  });

  const page = await context.newPage();

  // ── Click recorder via init script ──
  await page.exposeFunction('__rec', (data) => {
    data.ts = Date.now() - startTime;
    data.url = page.url().substring(0, 200);
    events.push(data);
    log('CLICK', JSON.stringify({
      tag: data.tagName, id: data.id, text: (data.text || '').substring(0, 50),
      sel: (data.selector || '').substring(0, 80), trusted: data.trusted, href: (data.href || '').substring(0, 100),
    }));
  });

  await page.addInitScript(() => {
    function getSel(el) {
      if (!el || el === document) return '';
      if (el.id) return '#' + CSS.escape(el.id);
      if (el === document.body) return 'body';
      const parts = [];
      let cur = el;
      while (cur && cur !== document.body && cur !== document.documentElement) {
        let s = cur.tagName.toLowerCase();
        if (cur.id) { parts.unshift('#' + CSS.escape(cur.id)); break; }
        if (cur.className && typeof cur.className === 'string') {
          const cls = cur.className.trim().split(/\s+/).filter(Boolean).slice(0, 3).join('.');
          if (cls) s += '.' + cls;
        }
        const par = cur.parentElement;
        if (par) {
          const sibs = Array.from(par.children).filter(c => c.tagName === cur.tagName);
          if (sibs.length > 1) s += `:nth-child(${Array.from(par.children).indexOf(cur) + 1})`;
        }
        parts.unshift(s);
        cur = cur.parentElement;
      }
      return parts.join(' > ');
    }
    document.addEventListener('click', (e) => {
      const el = e.target;
      try { window.__rec({ type: 'click', tagName: (el.tagName||'').toLowerCase(), id: el.id||'', className: (el.className&&typeof el.className==='string')?el.className.substring(0,100):'', selector: getSel(el), text: (el.textContent||'').trim().substring(0,80), href: el.href||el.parentElement?.href||'', coords: {x:e.clientX,y:e.clientY}, trusted: e.isTrusted }); } catch {}
    }, true);
  });

  // ── Network logging ──
  page.on('request', req => {
    const entry = {
      ts: Date.now() - startTime,
      type: 'request',
      method: req.method(),
      url: req.url().substring(0, 300),
      resourceType: req.resourceType(),
      headers: req.headers(),
    };
    if (req.method() === 'POST' && req.postData()) {
      entry.postData = req.postData().substring(0, 500);
    }
    networkEvents.push(entry);
    fs.appendFileSync(NETWORK_LOG, JSON.stringify(entry) + '\n');
    // Log interesting requests
    const u = req.url();
    if (u.includes('vplink') || u.includes('wistfulseverely') || u.includes('facebook') || u.includes('adscool') || u.includes('get-link') || req.resourceType() === 'document' || req.resourceType() === 'xhr' || req.resourceType() === 'fetch') {
      log('NET_REQ', `${req.method()} ${req.resourceType()} ${u.substring(0, 120)}`);
    }
  });

  page.on('response', async resp => {
    const entry = {
      ts: Date.now() - startTime,
      type: 'response',
      status: resp.status(),
      url: resp.url().substring(0, 300),
      headers: resp.headers(),
      resourceType: resp.request().resourceType(),
    };
    // Capture redirect chain
    if (resp.request().redirectedFrom()) {
      entry.redirectedFrom = resp.request().redirectedFrom().url().substring(0, 200);
    }
    // Try to get response body for interesting requests
    const u = resp.url();
    if (u.includes('vplink') || u.includes('wistfulseverely') || u.includes('get-link') || resp.request().resourceType() === 'document') {
      try {
        const body = await resp.text();
        entry.bodySnippet = body.substring(0, 1000);
      } catch {}
    }
    networkEvents.push(entry);
    fs.appendFileSync(NETWORK_LOG, JSON.stringify(entry) + '\n');
    if (u.includes('vplink') || u.includes('wistfulseverely') || u.includes('facebook') || u.includes('adscool') || resp.request().resourceType() === 'document') {
      const loc = resp.headers()['location'] || '';
      log('NET_RESP', `${resp.status()} ${resp.request().resourceType()} ${u.substring(0, 120)}${loc ? ' → ' + loc.substring(0, 100) : ''}`);
    }
  });

  // ── Console ──
  page.on('console', msg => {
    const entry = { ts: Date.now() - startTime, type: msg.type(), text: msg.text().substring(0, 500) };
    consoleEvents.push(entry);
    fs.appendFileSync(CONSOLE_LOG, JSON.stringify(entry) + '\n');
    if (['error', 'warning'].includes(msg.type()) || msg.text().includes('vplink') || msg.text().includes('redirect') || msg.text().includes('click') || msg.text().includes('timer')) {
      log('CONSOLE', `[${msg.type()}] ${msg.text().substring(0, 150)}`);
    }
  });

  // ── Navigation ──
  page.on('framenavigated', frame => {
    if (frame === page.mainFrame()) {
      log('NAV', frame.url().substring(0, 150));
    }
  });

  // ── Popups / new tabs ──
  context.on('page', async newPage => {
    log('NEW_TAB', newPage.url().substring(0, 150));
    // Monitor new tab
    newPage.on('request', req => {
      const u = req.url();
      if (u.includes('vplink') || u.includes('wistfulseverely') || req.resourceType() === 'document') {
        log('TAB_REQ', `${req.method()} ${req.resourceType()} ${u.substring(0, 120)}`);
      }
    });
    newPage.on('response', async resp => {
      const u = resp.url();
      if (u.includes('vplink') || u.includes('wistfulseverely') || resp.request().resourceType() === 'document') {
        const loc = resp.headers()['location'] || '';
        log('TAB_RESP', `${resp.status()} ${u.substring(0, 120)}${loc ? ' → ' + loc.substring(0, 100) : ''}`);
      }
    });
    newPage.on('framenavigated', frame => {
      if (frame === newPage.mainFrame()) {
        log('TAB_NAV', frame.url().substring(0, 150));
      }
    });
  });

  page.on('popup', popup => {
    log('POPUP', popup.url().substring(0, 150));
  });

  // ── Navigate ──
  log('NAVIGATE', `Going to https://vplink.in/${KEY}`);
  try {
    await page.goto(`https://vplink.in/${KEY}`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  } catch (e) {
    log('NAVIGATE', 'ERROR: ' + e.message);
  }
  await screenshot(page, 'initial');
  log('PAGE', `Landed on: ${page.url()}`);

  // ── Button state poller every 2s ──
  const btnInterval = setInterval(async () => {
    await dumpButtonStates(page);
  }, 2000);

  // ── Screenshot every 3s ──
  const ssInterval = setInterval(async () => {
    await screenshot(page, 'tick');
  }, 3000);

  // ── Periodic DOM snapshot on URL change ──
  let lastURL = page.url();
  const urlCheck = setInterval(async () => {
    const cur = page.url();
    if (cur !== lastURL) {
      log('URL_CHANGE', `${lastURL.substring(0, 100)} → ${cur.substring(0, 100)}`);
      lastURL = cur;
      await screenshot(page, 'urlchange');
      try {
        const html = await page.content();
        const prefix = String(frameCount).padStart(4, '0');
        fs.writeFileSync(path.join(SNAPSHOTS_DIR, `${prefix}_urlchange.html`), html);
      } catch {}
    }
  }, 500);

  log('READY', '=== Browser is open. Do the flow manually. ===');
  log('READY', 'Press Ctrl+C in this terminal when done to save summary.');

  // ── Wait for SIGINT ──
  process.on('SIGINT', async () => {
    log('SHUTDOWN', 'Saving final state...');
    clearInterval(btnInterval);
    clearInterval(ssInterval);
    clearInterval(urlCheck);

    await screenshot(page, 'final');
    await dumpButtonStates(page);

    // Final DOM
    try {
      const html = await page.content();
      fs.writeFileSync(path.join(SNAPSHOTS_DIR, 'final.html'), html);
    } catch {}

    // Save summary
    const summary = {
      key: KEY,
      recordingDir: RECORDING_DIR,
      duration: Date.now() - startTime,
      totalEvents: events.length,
      totalNetworkRequests: networkEvents.length,
      totalConsoleMessages: consoleEvents.length,
      totalScreenshots: frameCount,
      finalURL: page.url(),
      events: events,
    };
    fs.writeFileSync(SUMMARY_LOG, JSON.stringify(summary, null, 2));

    log('SHUTDOWN', `Summary saved to ${SUMMARY_LOG}`);
    log('SHUTDOWN', `Screenshots: ${SCREENSHOTS_DIR}`);
    log('SHUTDOWN', `Network log: ${NETWORK_LOG}`);
    log('SHUTDOWN', `Console log: ${CONSOLE_LOG}`);
    log('SHUTDOWN', `Total: ${events.length} events, ${networkEvents.length} network, ${consoleEvents.length} console, ${frameCount} screenshots`);

    await browser.close();
    process.exit(0);
  });

  // Keep alive
  await new Promise(() => {});
}

main().catch(err => {
  console.error('\n[FATAL]', err.message);
  process.exit(1);
});
