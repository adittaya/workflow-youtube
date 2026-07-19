const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const URL_ARG = process.argv[2] || 'https://vplink.in/gbd1b';
const RECORDING_DIR = path.join(__dirname, 'recordings', 'recording_' + new Date().toISOString().replace(/[:.]/g, '-'));
const SCREENSHOTS_DIR = path.join(RECORDING_DIR, 'screenshots');
const SNAPSHOTS_DIR = path.join(RECORDING_DIR, 'snapshots');
const SCRIPTS_DIR = path.join(RECORDING_DIR, 'scripts');
const NETWORK_LOG = path.join(RECORDING_DIR, 'network.jsonl');
const CONSOLE_LOG = path.join(RECORDING_DIR, 'console.jsonl');
const EVENTS_LOG = path.join(RECORDING_DIR, 'events.jsonl');
const SUMMARY_LOG = path.join(RECORDING_DIR, 'summary.json');

for (const d of [SCREENSHOTS_DIR, SNAPSHOTS_DIR, SCRIPTS_DIR]) fs.mkdirSync(d, { recursive: true });

const startTime = Date.now();
let frameCount = 0;
const events = [];

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

async function saveFullDOM(page, label) {
  try {
    const html = await page.content();
    const prefix = String(frameCount).padStart(4, '0');
    fs.writeFileSync(path.join(SNAPSHOTS_DIR, `${prefix}_${label}.html`), html);
  } catch {}
}

async function extractAllScripts(page) {
  try {
    const scripts = await page.evaluate(() => {
      const result = [];
      // Inline scripts
      document.querySelectorAll('script:not([src])').forEach((s, i) => {
        const text = s.textContent.trim();
        if (text.length > 5) {
          result.push({ type: 'inline', index: i, code: text.substring(0, 5000), length: text.length });
        }
      });
      // External scripts
      document.querySelectorAll('script[src]').forEach((s, i) => {
        result.push({ type: 'external', index: i, src: s.src, async: s.async, defer: s.defer });
      });
      return result;
    });
    const prefix = String(frameCount).padStart(4, '0');
    fs.writeFileSync(path.join(SCRIPTS_DIR, `${prefix}_scripts.json`), JSON.stringify(scripts, null, 2));
    log('SCRIPTS', `Found ${scripts.filter(s=>s.type==='inline').length} inline, ${scripts.filter(s=>s.type==='external').length} external scripts`);
  } catch {}
}

async function extractClickableElements(page) {
  try {
    const elements = await page.evaluate(() => {
      const result = [];
      // All clickable: buttons, anchors, onclick elements, inputs
      const sel = 'button, a[href], [onclick], input[type="submit"], input[type="button"], [role="button"], [class*="btn"], [class*="button"]';
      document.querySelectorAll(sel).forEach(el => {
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        const info = {
          tag: el.tagName.toLowerCase(),
          id: el.id || '',
          className: (typeof el.className === 'string') ? el.className.substring(0, 200) : '',
          text: (el.textContent || '').trim().substring(0, 100),
          href: el.href || el.getAttribute('href') || '',
          onclick: el.getAttribute('onclick') || '',
          display: style.display,
          visibility: style.visibility,
          opacity: style.opacity,
          disabled: el.disabled || el.classList.contains('disabled'),
          visible: rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden',
          rect: { x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height) },
          outerHTML: el.outerHTML.substring(0, 500),
        };
        result.push(info);
      });
      return result;
    });
    const prefix = String(frameCount).padStart(4, '0');
    fs.writeFileSync(path.join(SCRIPTS_DIR, `${prefix}_clickables.json`), JSON.stringify(elements, null, 2));
    log('CLICKABLES', `Found ${elements.length} clickable elements`);
  } catch {}
}

async function extractTimerState(page) {
  try {
    const state = await page.evaluate(() => {
      const result = {};
      // Find all timer/countdown/wait elements
      const allEls = document.querySelectorAll('[id*="time"], [id*="wait"], [id*="timer"], [id*="count"], [id*="snp"], [id*="btn"], [id*="link"], [id*="verify"], [id*="unlock"], [id*="generate"], [id*="continue"]');
      allEls.forEach(el => {
        const style = window.getComputedStyle(el);
        result[el.id || el.tagName + '_' + Math.random().toString(36).slice(2,6)] = {
          tag: el.tagName.toLowerCase(),
          id: el.id,
          className: (typeof el.className === 'string') ? el.className.substring(0, 100) : '',
          text: (el.textContent || '').trim().substring(0, 80),
          display: style.display,
          visibility: style.visibility,
          disabled: el.disabled || false,
          href: el.href || '',
          outerHTML: el.outerHTML.substring(0, 400),
        };
      });
      // Cookies
      result._cookies = document.cookie.substring(0, 500);
      // localStorage
      try {
        const ls = {};
        for (let i = 0; i < localStorage.length; i++) {
          const k = localStorage.key(i);
          ls[k] = localStorage.getItem(k)?.substring(0, 200);
        }
        result._localStorage = ls;
      } catch {}
      return result;
    });
    const prefix = String(frameCount).padStart(4, '0');
    fs.writeFileSync(path.join(SCRIPTS_DIR, `${prefix}_domstate.json`), JSON.stringify(state, null, 2));
  } catch {}
}

async function main() {
  log('INIT', `Recording to ${RECORDING_DIR}`);
  log('INIT', `Target: ${URL_ARG}`);

  const browser = await chromium.launch({
    headless: false,
    args: [
      '--no-sandbox',
      '--disable-gpu',
      '--disable-blink-features=AutomationControlled',
      '--disable-dev-shm-usage',
      '--window-size=1280,720',
    ],
  });

  const context = await browser.newContext({
    viewport: { width: 1280, height: 720 },
    userAgent: 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
    locale: 'en-US',
  });

  await context.addInitScript(() => {
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
    window.chrome = { runtime: {} };
  });

  const page = await context.newPage();

  // Click recorder
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
        parts.unshift(s);
        cur = cur.parentElement;
      }
      return parts.join(' > ');
    }
    document.addEventListener('click', (e) => {
      const el = e.target;
      try { window.__rec({ type: 'click', tagName: (el.tagName||'').toLowerCase(), id: el.id||'', className: (el.className&&typeof el.className==='string')?el.className.substring(0,100):'', selector: getSel(el), text: (el.textContent||'').trim().substring(0,80), href: el.href||el.parentElement?.href||'', trusted: e.isTrusted }); } catch {}
    }, true);
  });

  // Network
  page.on('request', req => {
    const entry = {
      ts: Date.now() - startTime, type: 'request', method: req.method(),
      url: req.url().substring(0, 300), resourceType: req.resourceType(),
    };
    if (req.method() === 'POST' && req.postData()) entry.postData = req.postData().substring(0, 1000);
    fs.appendFileSync(NETWORK_LOG, JSON.stringify(entry) + '\n');
  });

  page.on('response', async resp => {
    const entry = {
      ts: Date.now() - startTime, type: 'response', status: resp.status(),
      url: resp.url().substring(0, 300), resourceType: resp.request().resourceType(),
    };
    const u = resp.url();
    if (resp.request().resourceType() === 'document' || u.includes('vplink') || u.includes('linkpays') || u.includes('get-link')) {
      try { entry.bodySnippet = (await resp.text()).substring(0, 2000); } catch {}
    }
    fs.appendFileSync(NETWORK_LOG, JSON.stringify(entry) + '\n');
    if (resp.request().resourceType() === 'document') {
      const loc = resp.headers()['location'] || '';
      log('NET_RESP', `${resp.status()} DOC ${u.substring(0, 120)}${loc ? ' → ' + loc.substring(0, 100) : ''}`);
    }
  });

  // Console
  page.on('console', msg => {
    fs.appendFileSync(CONSOLE_LOG, JSON.stringify({ ts: Date.now() - startTime, type: msg.type(), text: msg.text().substring(0, 500) }) + '\n');
  });

  // Navigation
  page.on('framenavigated', frame => {
    if (frame === page.mainFrame()) log('NAV', frame.url().substring(0, 150));
  });

  // New tabs
  context.on('page', async newPage => {
    log('NEW_TAB', newPage.url().substring(0, 150));
    newPage.on('framenavigated', frame => {
      if (frame === newPage.mainFrame()) log('TAB_NAV', frame.url().substring(0, 150));
    });
  });

  // Navigate
  const startUrl = URL_ARG.startsWith('http') ? URL_ARG : `https://vplink.in/${URL_ARG}`;
  log('NAVIGATE', `Going to ${startUrl}`);
  try {
    await page.goto(startUrl, { waitUntil: 'domcontentloaded', timeout: 60000 });
  } catch (e) {
    log('NAVIGATE', 'ERROR: ' + e.message);
  }
  await screenshot(page, 'initial');
  await saveFullDOM(page, 'initial');
  await extractAllScripts(page);
  await extractClickableElements(page);
  await extractTimerState(page);
  log('PAGE', `Landed on: ${page.url()}`);

  // Deep DOM dump on every URL change + every 5s
  let lastURL = page.url();
  let domDumpCount = 0;

  const domDump = async () => {
    await saveFullDOM(page, 'domdump');
    await extractAllScripts(page);
    await extractClickableElements(page);
    await extractTimerState(page);
    domDumpCount++;
  };

  // Periodic full DOM dump every 5s
  const domInterval = setInterval(domDump, 5000);

  // Screenshot every 3s
  const ssInterval = setInterval(async () => {
    await screenshot(page, 'tick');
  }, 3000);

  // URL change detection + full dump
  const urlCheck = setInterval(async () => {
    const cur = page.url();
    if (cur !== lastURL) {
      log('URL_CHANGE', `${lastURL.substring(0, 100)} → ${cur.substring(0, 100)}`);
      lastURL = cur;
      frameCount++;
      await screenshot(page, 'urlchange');
      await domDump();
    }
  }, 500);

  log('READY', '=== Browser is open. Do the flow manually. ===');
  log('READY', 'Navigate through all pages. Press Ctrl+C when done.');

  process.on('SIGINT', async () => {
    log('SHUTDOWN', 'Saving final state...');
    clearInterval(domInterval);
    clearInterval(ssInterval);
    clearInterval(urlCheck);

    await screenshot(page, 'final');
    await saveFullDOM(page, 'final');
    await extractAllScripts(page);
    await extractClickableElements(page);
    await extractTimerState(page);

    const summary = {
      url: URL_ARG, recordingDir: RECORDING_DIR,
      duration: Date.now() - startTime, totalScreenshots: frameCount,
      totalEvents: events.length, finalURL: page.url(),
      events: events,
    };
    fs.writeFileSync(SUMMARY_LOG, JSON.stringify(summary, null, 2));
    log('SHUTDOWN', `Done: ${frameCount} screenshots, ${events.length} clicks, ${domDumpCount} DOM dumps`);
    log('SHUTDOWN', `Files: ${RECORDING_DIR}`);

    await browser.close();
    process.exit(0);
  });

  await new Promise(() => {});
}

main().catch(err => {
  console.error('\n[FATAL]', err.message);
  process.exit(1);
});
