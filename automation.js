let chromium;
try { ({ chromium } = require('playwright')); }
catch { ({ chromium } = require('playwright-core')); }
const fs = require('fs');
const path = require('path');
let markDead;
try { ({ markDead } = require('./proxy-rotator')); } catch { markDead = async () => false; }

const KEY = process.argv[2] || process.env.VPLINK_KEY;
if (!KEY) { console.error('Usage: node automation.js <vplink_key>'); process.exit(1); }

const DEBUG = process.argv.includes('--vplink-debug') || process.env.VPLINK_DEBUG === '1';
let browser, context, page;
let destinationUrl = null;
let startTime = Date.now();

const log = msg => console.log(`  [${((Date.now()-startTime)/1000).toFixed(1)}s] ${msg}`);
const ms = t => new Promise(r => setTimeout(r, t));
const rand = (min, max) => Math.floor(Math.random() * (max - min + 1)) + min;
const safeURL = () => { try { return page.url(); } catch { return ''; } };
const urlBase = u => { try { const x = new URL(u); return x.origin + x.pathname; } catch { return (u || '').split('#')[0]; } };
const safeEval = (fn, ...a) => { try { return page.evaluate(fn, ...a).catch(() => null); } catch { return null; } };

let proxyFailures = 0;
const PROXY = process.env.VPLINK_PROXY || '';
const PROXY_HOST = PROXY.replace(/^https?:\/\//, '').replace(/:\d+$/, '');

const reportProxyFailure = async (reason) => {
  if (!PROXY_HOST) return;
  proxyFailures++;
  log(`proxy failure #${proxyFailures}: ${reason} (${PROXY_HOST})`);
  if (proxyFailures >= 2) {
    log(`proxy ${PROXY_HOST} failed ${proxyFailures}x, deleting from DB`);
    const [ip, port] = PROXY_HOST.split(':');
    if (ip && port) await markDead(ip, parseInt(port));
  }
  if (proxyFailures >= 3) {
    log(`proxy ${PROXY_HOST} failed ${proxyFailures}x, aborting (too many failures)`);
  }
};

process.on('SIGINT', async () => {
  if (browser) await browser.close().catch(() => {});
  process.exit(130);
});

(async () => {
  const stealthArgs = ['--no-sandbox', '--disable-gpu', '--disable-blink-features=AutomationControlled',
    '--disable-dev-shm-usage', '--disable-accelerated-2d-canvas', '--disable-setuid-sandbox',
    '--disable-automation', '--use-gl=swiftshader'];
  const launchOpts = {};
  const isTermux = process.env.VPLINK_TERMUX === '1';
  const headless = isTermux || process.env.VPLINK_HEADLESS === '1';
  launchOpts.headless = headless;
  if (isTermux) {
    launchOpts.executablePath = process.env.CHROMIUM_PATH || '/data/data/com.termux/files/usr/bin/chromium-browser';
  } else if (process.env.CHROMIUM_PATH) {
    launchOpts.executablePath = process.env.CHROMIUM_PATH;
  }
  launchOpts.args = [...stealthArgs];
  if (process.env.VPLINK_PROXY) launchOpts.args.push(`--proxy-server=${process.env.VPLINK_PROXY}`);
  if (process.env.VPLINK_EXTRA_ARGS) launchOpts.args.push(...process.env.VPLINK_EXTRA_ARGS.split(' '));

  browser = await chromium.launch(launchOpts);
  const ctxOpts = { viewport: { width: 1280, height: 720 }, locale: 'en-US' };
  if (process.env.VPLINK_USER_AGENT) ctxOpts.userAgent = process.env.VPLINK_USER_AGENT;
  if (process.env.VPLINK_VIEWPORT_WIDTH || process.env.VPLINK_VIEWPORT_HEIGHT) {
    ctxOpts.viewport = {
      width: parseInt(process.env.VPLINK_VIEWPORT_WIDTH) || 1280,
      height: parseInt(process.env.VPLINK_VIEWPORT_HEIGHT) || 720,
    };
  }
  context = await browser.newContext(ctxOpts);
  page = await context.newPage();
  page.setDefaultNavigationTimeout(90000);

  let debugPage = page;
  const debugShot = async (label) => {
    if (!DEBUG) return;
    const dir = path.join(__dirname, 'screenshots');
    try { fs.mkdirSync(dir, { recursive: true }); } catch {}
    try { await debugPage.screenshot({ path: path.join(dir, `${label}.png`), fullPage: false }); } catch {}
  };

  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
    window.chrome = { runtime: {} };
    const orig = window.navigator.permissions.query;
    window.navigator.permissions.query = p => p.name === 'notifications' ? Promise.resolve({ state: 'denied' }) : orig(p);
  });

  page.on('framenavigated', frame => {
    if (frame === page.mainFrame()) log(`nav: ${frame.url().substring(0, 120)}`);
  });

  // ── Human-like helpers ──
  const humanDelay = (min, max) => ms(rand(min, max));

  const humanScroll = async () => {
    const scrolls = rand(1, 3);
    for (let i = 0; i < scrolls; i++) {
      await safeEval(y => window.scrollBy({ top: y, behavior: 'smooth' }), rand(100, 400));
      await humanDelay(300, 800);
    }
  };

  const humanMouseMove = async (sel) => {
    try {
      const box = await page.locator(sel).first().boundingBox();
      if (box) {
        const x = box.x + box.width * (0.3 + Math.random() * 0.4);
        const y = box.y + box.height * (0.3 + Math.random() * 0.4);
        await page.mouse.move(x, y, { steps: rand(5, 15) });
        await humanDelay(100, 300);
      }
    } catch {}
  };

  const humanClick = async (sel) => {
    await humanMouseMove(sel);
    await humanDelay(200, 500);
    try { await page.click(sel, { timeout: 5000 }); return true; }
    catch {
      try {
        return await page.evaluate(s => {
          const el = document.querySelector(s);
          if (!el) return false;
          el.scrollIntoView({ block: 'center', behavior: 'smooth' });
          el.click();
          return true;
        }, sel);
      } catch { return false; }
    }
  };

  const clickText = async txt => {
    try { await page.locator(`text=${txt}`).first().click({ timeout: 5000 }); return true; }
    catch { return false; }
  };

  const DEST_PATTERNS = ['12indiaplay.com', 'vv53243', 'casino', 'one-',
    'apkmirror.com', 'play.google.com', 'download', '.apk', 'one-vv',
    'capecutapk.com', 'amazingbaba.com'];

  const isDestination = url => {
    if (!url || !url.startsWith('http')) return false;
    if (url.includes('chrome-error') || url.includes('about:blank')) return false;
    for (const p of DEST_PATTERNS) {
      if (url.includes(p)) return true;
    }
    return false;
  };

  // ── Template detection ──
  // Returns: 'tp' | 'ce' | 'link1s' | 'unknown'
  const detectTemplate = async () => {
    const result = await safeEval(() => {
      if (document.getElementById('tp-time') || document.getElementById('tp-wait1')) return 'tp';
      if (document.getElementById('ce-time') || document.getElementById('ce-wait1')) return 'ce';
      if (document.getElementById('link1s-wait1') || document.getElementById('startCountdownBtn')) return 'link1s';
      return 'unknown';
    });
    return result || 'unknown';
  };

  // ── Get countdown seconds remaining ──
  // Returns: positive number = seconds left, 0 = done, -1 = element not found
  // IMPORTANT: parseInt on empty/non-numeric text returns NaN → treat as "timer not ready yet" (-1)
  const getCountdown = async () => {
    const result = await safeEval(() => {
      const tpTime = document.getElementById('tp-time');
      if (tpTime) {
        const v = parseInt(tpTime.textContent);
        return isNaN(v) ? -1 : v;
      }
      const ceTime = document.getElementById('ce-time');
      if (ceTime) {
        const v = parseInt(ceTime.textContent);
        return isNaN(v) ? -1 : v;
      }
      const link1sTime = document.getElementById('link1s-time');
      if (link1sTime) {
        const v = parseInt(link1sTime.textContent);
        return isNaN(v) ? -1 : v;
      }
      return -1;
    });
    return result ?? -1;
  };

  // ── Handle bot-detection popup (#continueBtn) ──
  // Returns 'popup' if popup was clicked, 'rewarded' if we landed on #goog_rewarded, false otherwise
  const handlePopup = async () => {
    const popupVisible = await safeEval(() => {
      const el = document.getElementById('continueBtn');
      if (!el) return false;
      const style = getComputedStyle(el);
      return style.display !== 'none' && style.visibility !== 'hidden'
        && el.getClientRects().length > 0;
    });
    if (!popupVisible) return false;

    log('popup detected, clicking...');
    await humanDelay(500, 1500);
    // Popup has CSS pulse animation — force click to bypass stability wait
    try {
      await page.locator('#continueBtn').click({ force: true, timeout: 5000 });
    } catch {
      await humanClick('#continueBtn');
    }
    await humanDelay(1000, 2000);

    // Check if we landed on #goog_rewarded (Google Ads reward page)
    if (safeURL().includes('#goog_rewarded')) {
      log('landed on #goog_rewarded, waiting for ad to complete...');
      return 'rewarded';
    }
    return true;
  };

  // ── Wait for countdown to finish ──
  const waitForCountdown = async (template, maxWaitSec) => {
    const maxIter = maxWaitSec * 2; // check every 500ms
    for (let i = 0; i < maxIter; i++) {
      const remaining = await getCountdown();
      if (remaining === 0) return 'done';       // timer reached 0
      // remaining === -1 means element not found or timer not ready yet — keep waiting

      // Handle popup that may appear during countdown
      if (i % 4 === 0) {
        const popupResult = await handlePopup();
        if (popupResult === 'rewarded') return 'rewarded';
      }

      // Occasional scroll to look natural
      if (i % 10 === 0) await humanScroll();

      await ms(500);
    }
    return false;
  };

  // ── Template A (TP): tp-time countdown → tp-snp2 ──
  const handleTP = async () => {
    log('template: TP (tp-time countdown)');

    // Wait for countdown (up to 30s — timer starts at ~23, popup appears at ~6s remaining)
    const countdownResult = await waitForCountdown('tp', 30);

    // If popup landed us on #goog_rewarded during countdown, return immediately
    if (countdownResult === 'rewarded') {
      log('popup sent us to #goog_rewarded during countdown');
      return 'rewarded';
    }

    if (countdownResult !== 'done') log('TP countdown timeout, trying button anyway');

    // Popup may appear near end of countdown (after countdown finishes)
    const popupResult = await handlePopup();
    if (popupResult === 'rewarded') {
      log('on #goog_rewarded after countdown, waiting for ad redirect...');
      return 'rewarded';
    }

    await humanDelay(500, 1500);

    // Click #tp-snp2 when visible
    const clicked = await humanClick('#tp-snp2');
    if (!clicked) {
      // Fallback: find anchor with learn_more.php href
      const altClicked = await safeEval(() => {
        const links = document.querySelectorAll('a');
        for (const a of links) {
          if (a.href && a.href.includes('learn_more.php') && a.offsetParent !== null) {
            a.click();
            return true;
          }
        }
        return false;
      });
      if (!altClicked) {
        // Last resort: text click
        await clickText('Continue');
      }
    }
    return true;
  };

  // ── Template B (CE): ce-time countdown → btn6 Verify → btn7 Continue ──
  const handleCE = async () => {
    log('template: CE (ce-time countdown)');

    // Wait for countdown (up to 30s — timer starts at ~20)
    const countdownResult = await waitForCountdown('ce', 30);
    if (countdownResult === 'rewarded') {
      log('popup sent us to #goog_rewarded during CE countdown');
      return 'rewarded';
    }
    if (countdownResult !== 'done') log('CE countdown timeout, trying buttons anyway');

    await humanDelay(500, 1500);

    // Click #btn6 (Verify) first — may trigger navigation OR just hide itself
    const startUrl = safeURL();
    const btn6Clicked = await humanClick('#btn6');
    if (btn6Clicked) {
      log('clicked btn6 (Verify)');
      // Wait up to 8s — btn6 may navigate OR just hide itself
      for (let w = 0; w < 8; w++) {
        await ms(1000);
        if (safeURL() !== startUrl) {
          log('btn6 triggered navigation');
          return true;
        }
        // Check if btn7 became visible (btn6 just hid itself)
        const btn7Visible = await safeEval(() => {
          const el = document.querySelector('#btn7 > button');
          if (!el) return false;
          const style = getComputedStyle(el);
          return style.display !== 'none' && style.visibility !== 'hidden'
            && el.getClientRects().length > 0;
        });
        if (btn7Visible) break;
      }
    }

    // Click #btn7 > button (Continue)
    const btn7Clicked = await humanClick('#btn7 > button');
    if (!btn7Clicked) {
      // Fallback: click #btn7 directly
      await humanClick('#btn7');
    }
    log('clicked btn7 (Continue)');
    return true;
  };

  // ── Template C (LINK1S): startCountdownBtn → countdown → cross-snp2 ──
  const handleLINK1S = async () => {
    log('template: LINK1S (startCountdownBtn)');

    // Click #startCountdownBtn to start the countdown
    const started = await humanClick('#startCountdownBtn');
    if (started) {
      log('clicked startCountdownBtn, waiting for countdown...');
      await humanDelay(500, 1000);
    }

    // Wait for countdown (up to 25s — timer resets to 14s after click)
    const countdownResult = await waitForCountdown('link1s', 25);

    if (countdownResult === 'rewarded') {
      log('popup sent us to #goog_rewarded during LINK1S countdown');
      return 'rewarded';
    }

    if (countdownResult !== 'done') log('LINK1S countdown timeout, trying button anyway');

    await humanDelay(500, 1500);

    // Click #cross-snp2 when visible
    const clicked = await humanClick('#cross-snp2');
    if (!clicked) {
      // Fallback: find anchor with learn_more.php href
      await safeEval(() => {
        const links = document.querySelectorAll('a');
        for (const a of links) {
          if (a.href && a.href.includes('learn_more.php') && a.offsetParent !== null) {
            a.click();
            return true;
          }
        }
        return false;
      });
    }
    return true;
  };

  // ── Unknown template: try all known buttons ──
  const handleUnknown = async () => {
    log('template: UNKNOWN — trying all known buttons');
    await humanDelay(3000, 5000);

    // Try each button in priority order
    const buttons = [
      '#tp-snp2', '#cross-snp2', '#btn6',
      '#btn7 > button', '#btn7',
      '#continueBtn',
      '#main > div:nth-child(4) > center > center > a',
    ];

    for (const sel of buttons) {
      await handlePopup();
      const visible = await safeEval(s => {
        const el = document.querySelector(s);
        if (!el) return false;
        const style = getComputedStyle(el);
        return style.display !== 'none' && style.visibility !== 'hidden'
          && el.getClientRects().length > 0;
      }, sel);

      if (visible) {
        log(`clicking ${sel}`);
        await humanClick(sel);
        await humanDelay(1000, 2000);

        // Wait for navigation
        const startUrl = safeURL();
        for (let w = 0; w < 15; w++) {
          await ms(1000);
          if (safeURL() !== startUrl) return true;
        }
      }
    }

    // Text-based fallback
    for (const txt of ['Continue', 'Verify', 'Get Link']) {
      if (await clickText(txt)) {
        await humanDelay(1000, 2000);
        return true;
      }
    }

    return false;
  };

  // ── Article page handler (domain-agnostic) ──
  const handleArticle = async () => {
    log('article page');
    await debugShot('article-start');
    const startUrl = safeURL();

    // Initial settle — let page load and JS initialize
    await humanDelay(2000, 4000);
    await humanScroll();

    // Detect template by DOM structure (NOT by domain)
    const template = await detectTemplate();
    log(`detected template: ${template}`);

    // Debug: dump DOM + screenshot when template is unknown
    if (template === 'unknown') {
      await dumpDOM(`unknown-${Date.now()}`);
    }

    let navigated = false;

    switch (template) {
      case 'tp':
        navigated = await handleTP();
        break;
      case 'ce':
        navigated = await handleCE();
        break;
      case 'link1s':
        navigated = await handleLINK1S();
        break;
      default:
        navigated = await handleUnknown();
        break;
    }

    // Special case: TP popup sent us to #goog_rewarded (Google Ads reward page)
    // Don't click anything — wait for the ad to complete and auto-redirect
    if (navigated === 'rewarded') {
      log('waiting for #goog_rewarded ad to complete...');
      const rewardedBase = urlBase(safeURL());
      for (let w = 0; w < 45; w++) {
        await ms(1000);
        const cur = safeURL();
        const curBase = urlBase(cur);
        if (!cur.includes('#goog_rewarded') && curBase !== rewardedBase) {
          log(`ad completed, redirected to: ${cur.substring(0, 100)}`);
          return true;
        }
      }
      log('#goog_rewarded ad did not redirect in 45s');
      // Try clearing the hash fragment
      await safeEval(() => {
        if (window.location.hash) {
          history.replaceState(null, '', window.location.pathname + window.location.search);
        }
      });
      await humanDelay(1000, 2000);
      return false;
    }

    // Wait for navigation after button click
    if (navigated) {
      const startUrl = safeURL();
      const startBase = urlBase(startUrl);
      for (let w = 0; w < 20; w++) {
        await ms(1000);
        const cur = safeURL();
        const curBase = urlBase(cur);
        if (cur !== startUrl && curBase !== startBase) {
          log(`navigated to: ${cur.substring(0, 100)}`);
          return true;
        }
      }
      // Check if URL changed at all (even same domain — page may have reloaded)
      const finalUrl = safeURL();
      if (finalUrl !== startUrl) {
        log(`page changed: ${finalUrl.substring(0, 100)}`);
        return true;
      }
      // Buttons were clicked but page stayed the same — let main loop re-evaluate
      log('buttons clicked but no URL change detected, continuing');
      return true;
    }

    return false;
  };

  // ── Get Link handler ──
  const doGetLink = async () => {
    try {
      // Close leftover popups
      for (const p of context.pages()) {
        if (p !== page) { try { await p.close(); } catch {} }
      }

      const btn = await page.waitForSelector('#get-link', { timeout: 40000 }).catch(() => null);
      if (!btn) return false;

      // Capture href before clicking
      const linkHref = await btn.evaluate(el => el.href).catch(() => '');

      // Wait for countdown completion (disabled class removal)
      const t0 = Date.now();
      try {
        await page.waitForFunction(() => {
          const el = document.getElementById('get-link');
          return el && !el.classList.contains('disabled');
        }, { timeout: 35000 });
      } catch {}
      const countdownElapsed = Date.now() - t0;
      if (countdownElapsed > 500) log(`get-link countdown: ${countdownElapsed}ms`);

      // Human-like delay before clicking
      await humanDelay(800, 2000);
      await humanMouseMove('#get-link');
      await humanDelay(300, 700);

      log('clicking Get Link');
      const newTabPromise = context.waitForEvent('page', { timeout: 20000 }).catch(() => null);
      await humanClick('#get-link');
      let newTab = await newTabPromise;

      const clickTime = Date.now();
      let stableUrl = '', stableCount = 0;

      // Poll for destination URL
      for (let i = 0; i < 60; i++) {
        await ms(1000);
        let popupUrl = '';

        if (newTab) {
          try {
            await newTab.waitForLoadState('networkidle', { timeout: 3000 }).catch(() => {});
            popupUrl = newTab.url();
          } catch { newTab = null; }
          if (popupUrl && !popupUrl.includes('about:blank') && !popupUrl.includes('chrome-error')) {
            destinationUrl = popupUrl;
            log(`destination (popup): ${popupUrl.substring(0,100)}`);
            const elapsed = Date.now() - clickTime;
            const wait = Math.max(0, 25000 - elapsed);
            if (wait > 500) { log(`tracking wait: ${wait}ms`); await ms(wait); }
            return true;
          }
        }

        const mUrl = safeURL();
        if (!mUrl || mUrl.includes('about:blank') || mUrl.includes('chrome-error')) continue;

        if (mUrl === stableUrl) {
          stableCount++;
          if (stableCount >= 3 && isDestination(mUrl)) {
            destinationUrl = mUrl;
            log(`destination (stable): ${mUrl.substring(0,100)}`);
            const elapsed = Date.now() - clickTime;
            const wait = Math.max(0, 25000 - elapsed);
            if (wait > 500) { log(`tracking wait: ${wait}ms`); await ms(wait); }
            return true;
          }
        } else {
          stableUrl = mUrl;
          stableCount = 1;
        }
      }

      if (linkHref && linkHref.startsWith('http')) {
        destinationUrl = linkHref;
        log(`destination (href): ${linkHref.substring(0,100)}`);
        const elapsed = Date.now() - clickTime;
        const wait = Math.max(0, 25000 - elapsed);
        if (wait > 500) { log(`tracking wait: ${wait}ms`); await ms(wait); }
        return true;
      }
    } catch {}
    return false;
  };

  // ── Main flow ──
  log('='.repeat(50));
  log(`starting funnel for KEY=${KEY}`);
  if (DEBUG) log('debug mode active');
  const navTimeout = process.env.VPLINK_PROXY ? 90000 : 45000;

  // YouTube referral: navigate to YouTube first so browser naturally sets Referer
  const REFERER = process.env.VPLINK_REFERER || '';
  if (REFERER) {
    log(`navigating to YouTube first for referral: ${REFERER.substring(0, 60)}`);
    try {
      await page.goto(REFERER, { waitUntil: 'domcontentloaded', timeout: 30000 });
      await humanDelay(2000, 4000);
      log('YouTube loaded, now navigating to vplink.in (browser will set Referer)');
    } catch (e) {
      log(`YouTube navigation failed: ${e.message}, continuing without referral`);
    }
  }

  log(`navigating to vplink.in/${KEY}`);
  await debugShot('01-start');
  try {
    await page.goto(`https://vplink.in/${KEY}`, { waitUntil: 'domcontentloaded', timeout: navTimeout });
  } catch (e) {
    log(`first goto failed: ${e.message}, retrying...`);
    if (PROXY && (e.message.includes('ERR_TUNNEL') || e.message.includes('ERR_PROXY') || e.message.includes('ERR_CONNECTION'))) {
      await reportProxyFailure('first-goto-tunnel-error');
    }
    await ms(2000);
    try {
      await page.goto(`https://vplink.in/${KEY}`, { waitUntil: 'domcontentloaded', timeout: navTimeout });
    } catch (e2) {
      log(`second goto failed: ${e2.message}`);
      if (PROXY && (e2.message.includes('ERR_TUNNEL') || e2.message.includes('ERR_PROXY') || e2.message.includes('ERR_CONNECTION'))) {
        await reportProxyFailure('second-goto-tunnel-error');
      }
    }
  }
  await humanDelay(2000, 4000);
  await debugShot('02-after-nav');

  // Wait for auto-redirect (vplink.in JS redirects to article page)
  log('waiting for auto-redirect...');
  for (let i = 0; i < 30; i++) {
    await ms(1000);
    if (!safeURL().includes('vplink.in')) break;
  }
  await debugShot('03-after-redirect');

  // Handle Cloudflare challenge if still on vplink.in
  for (let attempt = 0; attempt < 3; attempt++) {
    const url = safeURL();
    if (!url.includes('vplink.in') || url.includes('cdn-cgi')) break;

    const hasGl = await safeEval(() => !!document.getElementById('get-link'));
    if (hasGl) { log('page loaded (get-link visible)'); break; }

    const isCf = await safeEval(() => {
      const html = (document.documentElement?.innerHTML || '').substring(0, 2000);
      return html.includes('cf-browser-verification') || html.includes('challenge-form')
        || html.includes('cf-challenge') || html.includes('_cf_chl_opt');
    });

    if (isCf) log('Cloudflare challenge detected');
    log(`waiting for page content (attempt ${attempt + 1})...`);

    let loaded = false;
    for (let i = 0; i < 40; i++) {
      await ms(1000);
      if (!safeURL().includes('vplink.in')) { loaded = true; break; }
      if (await safeEval(() => !!document.getElementById('get-link'))) { loaded = true; break; }
    }
    if (loaded) break;

    if (isCf) {
      log('Cloudflare not resolved, reloading...');
      await page.reload({ waitUntil: 'domcontentloaded', timeout: navTimeout }).catch(() => {});
      await humanDelay(3000, 5000);
    } else break;
  }

  // ── DOM dump helper (debug) ──
  const dumpDOM = async (label) => {
    if (!DEBUG) return;
    const dir = path.join(__dirname, 'screenshots');
    try { fs.mkdirSync(dir, { recursive: true }); } catch {}
    try {
      const html = await page.content();
      fs.writeFileSync(path.join(dir, `${label}.html`), html);
    } catch {}
    await debugShot(label);
  };

  // ── Main loop ──
  let vplinkArrivals = 0;
  let lastBase = '';
  let googRewardRetries = 0;
  const MAX_GOOG_REWARD_RETRIES = 2;
  const urlVisits = {}; // Track how many times each URL is visited
  const MAX_URL_VISITS = 3; // Abort if same URL seen this many times

  for (let cycle = 0; cycle < 25 && !destinationUrl; cycle++) {
    const url = safeURL();
    if (!url) { await ms(2000); continue; }
    const base = urlBase(url);

    // Track URL visit count for stuck-loop detection
    // Skip vplink.in (needs multiple cycles for countdown)
    // Skip intermediate/routing pages (learn_more.php, studieseducates, intermediates)
    const urlKey = url.split('#')[0]; // Normalize without hash
    const isIntermediate = url.includes('learn_more.php') || url.includes('studieseducates')
      || url.includes('studiiessuniversitiess') || url.includes('universitesstudiiess')
      || url.includes('studyscholorships');
    if (!url.includes('vplink.in') && !isIntermediate) {
      urlVisits[urlKey] = (urlVisits[urlKey] || 0) + 1;
      if (urlVisits[urlKey] >= MAX_URL_VISITS) {
        log(`STUCK: same article visited ${urlVisits[urlKey]} times, force-navigating to vplink.in`);
        await dumpDOM(`stuck-${cycle + 1}`);
        lastBase = '';
        urlVisits[urlKey] = 0;
        await page.goto(`https://vplink.in/${KEY}`, { waitUntil: 'domcontentloaded', timeout: navTimeout }).catch(() => {});
        await humanDelay(3000, 5000);
        continue;
      }
    }

    // Skip hash-only changes (e.g. #goog_rewarded on same article page)
    if (base === lastBase && url.includes('#')) {
      log(`[cycle ${cycle + 1}] hash-only change (${url.split('#')[1]}), waiting for real navigation...`);
      await humanDelay(3000, 5000);
      // Wait for real navigation away from this page
      for (let w = 0; w < 15; w++) {
        await ms(1000);
        const cur = safeURL();
        if (urlBase(cur) !== base) {
          log(`navigated away: ${cur.substring(0, 100)}`);
          break;
        }
      }
      // If still on same hash after waiting, force-navigate
      if (urlBase(safeURL()) === base) {
        log('still stuck on same page after hash wait, force-navigating');
        lastBase = '';
        await page.goto(`https://vplink.in/${KEY}`, { waitUntil: 'domcontentloaded', timeout: navTimeout }).catch(() => {});
        await humanDelay(3000, 5000);
      }
      continue;
    }

    lastBase = base;
    googRewardRetries = 0;
    log(`[cycle ${cycle + 1}] ${url.substring(0, 110)}`);
    await debugShot(`cycle-${cycle + 1}`);

    if (isDestination(url)) { destinationUrl = url; log('on destination URL already!'); break; }

    // ── vplink.in page ──
    if (url.includes('vplink.in') && !url.includes('cdn-cgi')) {
      vplinkArrivals++;
      const btnState = await safeEval(() => {
        const el = document.getElementById('get-link');
        if (!el) return 'missing';
        if (el.classList.contains('disabled')) return 'disabled';
        if (el.offsetParent === null) return 'hidden';
        return 'ready';
      });
      log(`get-link state: ${btnState}`);

      if (btnState === 'ready') {
        if (await doGetLink()) break;
        log('get-link failed, reloading vplink.in');
        for (const p of context.pages()) { if (p !== page) { try { await p.close(); } catch {} } }
        await page.goto(`https://vplink.in/${KEY}`, { waitUntil: 'domcontentloaded', timeout: navTimeout }).catch(() => {});
        await humanDelay(3000, 5000);
        for (let i = 0; i < 15; i++) {
          await ms(1000);
          if (!safeURL().includes('vplink.in')) break;
        }
        continue;
      }

      if (btnState === 'missing') {
        if (vplinkArrivals >= 3) {
          log('get-link missing for 3+ cycles, reloading');
          await page.goto(`https://vplink.in/${KEY}`, { waitUntil: 'domcontentloaded', timeout: navTimeout }).catch(() => {});
          await humanDelay(3000, 5000);
        } else {
          await ms(2000);
        }
        continue;
      }

      // disabled/hidden (countdown still running)
      await humanDelay(1500, 3000);
      continue;
    }

    // ── Chrome error recovery ──
    if (url.startsWith('chrome-error://')) {
      log('chrome-error, force to vplink.in');
      if (PROXY) await reportProxyFailure('chrome-error');
      await page.goto(`https://vplink.in/${KEY}`, { waitUntil: 'domcontentloaded', timeout: navTimeout }).catch(() => {});
      await humanDelay(3000, 5000);
      continue;
    }

    // ── Google Ads reward page (#goog_rewarded) — ad didn't redirect ──
    if (url.includes('#goog_rewarded')) {
      googRewardRetries++;
      log('#goog_rewarded detected in main loop, ad did not redirect');
      await dumpDOM('goog-rewarded');
      if (googRewardRetries > MAX_GOOG_REWARD_RETRIES) {
        log(`#goog_rewarded stuck after ${googRewardRetries} retries, force-navigating to vplink.in`);
        googRewardRetries = 0;
        lastBase = '';
        await page.goto(`https://vplink.in/${KEY}`, { waitUntil: 'domcontentloaded', timeout: navTimeout }).catch(() => {});
        await humanDelay(3000, 5000);
        continue;
      }
      // Try reloading the article without the hash fragment
      const cleanUrl = url.split('#')[0];
      log(`reloading without hash: ${cleanUrl.substring(0, 80)}`);
      lastBase = '';
      await page.goto(cleanUrl, { waitUntil: 'domcontentloaded', timeout: navTimeout }).catch(() => {});
      await humanDelay(3000, 5000);
      // If we're back on the same article (without hash), treat it fresh
      if (!safeURL().includes('#goog_rewarded')) {
        log('reloaded article without hash, treating as fresh page');
      }
      continue;
    }

    // ── Article / unknown page ──
    log(`article/unknown: ${url.substring(0,80)}`);

    // Skip intermediate redirect pages (learn_more.php, studieseducates)
    if (url.includes('learn_more.php') || url.includes('studieseducates')) {
      log('intermediate redirect page, waiting for auto-redirect...');
      const intermediateBase = urlBase(url);
      for (let w = 0; w < 15; w++) {
        await ms(1000);
        const cur = safeURL();
        const curBase = urlBase(cur);
        if (curBase !== intermediateBase && !cur.includes('learn_more.php') && !cur.includes('studieseducates')) {
          log(`redirected to: ${cur.substring(0, 100)}`);
          await humanDelay(500, 1500); // Let page stabilize
          break;
        }
      }
      // Re-check URL after wait — page may have redirected again
      lastBase = urlBase(safeURL());
      continue;
    }

    const navigated = await handleArticle();
    if (!navigated) {
      log('exhausted, force-navigating to vplink.in');
      lastBase = '';
      await page.goto(`https://vplink.in/${KEY}`, { waitUntil: 'domcontentloaded', timeout: navTimeout }).catch(() => {});
      await humanDelay(2000, 4000);
      for (let i = 0; i < 15; i++) {
        await ms(1000);
        if (!safeURL().includes('vplink.in')) break;
      }
    }
  }

  // ── Final fallback ──
  if (!destinationUrl) {
    log('running final fallback...');
    let gotDest = false;

    if (safeURL().includes('vplink.in')) {
      gotDest = await doGetLink();
    }

    if (!gotDest) {
      const vplinkHref = await safeEval(() => {
        const links = document.querySelectorAll('a[href*="vplink.in"]');
        for (const a of links) {
          if (a.href && !a.href.includes('cdn-cgi')) return a.href;
        }
        return null;
      });
      if (vplinkHref) {
        log('found vplink link on page');
        await page.goto(vplinkHref, { waitUntil: 'domcontentloaded', timeout: navTimeout }).catch(() => {});
        await humanDelay(3000, 5000);
        if (safeURL().includes('vplink.in')) gotDest = await doGetLink();
      }
    }

    if (!gotDest) {
      for (let a = 0; a < 3; a++) {
        log(`direct attempt ${a + 1}`);
        await page.goto(`https://vplink.in/${KEY}`, { waitUntil: 'domcontentloaded', timeout: navTimeout }).catch(() => {});
        for (let w = 0; w < 15; w++) {
          await ms(500);
          const cur = safeURL();
          if (cur.includes('vplink.in')) {
            const hasGl = await safeEval(() => !!document.getElementById('get-link'));
            if (hasGl && await doGetLink()) { gotDest = true; break; }
          } else break;
        }
        if (gotDest) break;
      }
    }

    if (gotDest && !destinationUrl) destinationUrl = safeURL();
  }

  console.log('\n═════════════════════════════════════════');
  console.log('  ' + (destinationUrl ? 'DESTINATION URL:' : 'NO DESTINATION'));
  if (destinationUrl) console.log('  ' + destinationUrl);
  if (destinationUrl) fs.writeFileSync(path.join(__dirname, 'destination_url.txt'), destinationUrl);
  await ms(2000);
  await browser.close().catch(() => {});
})();
