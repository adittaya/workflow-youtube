let chromium;
try { ({ chromium } = require('playwright')); }
catch { ({ chromium } = require('playwright-core')); }
const fs = require('fs');
const path = require('path');
let markDead, addProxyBlacklist;
try { ({ markDead } = require('./proxy-rotator')); } catch { markDead = async () => false; }
try { ({ addProxyBlacklist } = require('./config')); } catch { addProxyBlacklist = () => {}; }

const KEY = process.argv[2] || process.env.VPLINK_KEY;
if (!KEY) { console.error('Usage: node automation.js <vplink_key>'); process.exit(1); }

const DEBUG = process.argv.includes('--vplink-debug') || process.env.VPLINK_DEBUG === '1';
let browser, context, page;
let destinationUrl = null;
let startTime = Date.now();

const log = msg => console.error(`  [${((Date.now()-startTime)/1000).toFixed(1)}s] ${msg}`);
const ms = t => new Promise(r => setTimeout(r, t));
const rand = (min, max) => Math.floor(Math.random() * (max - min + 1)) + min;
const safeURL = () => { try { return page.url(); } catch { return ''; } };
const urlBase = u => { try { const x = new URL(u); return x.origin + x.pathname; } catch { return (u || '').split('#')[0]; } };
const safeEval = (fn, ...a) => { try { return page.evaluate(fn, ...a).catch(() => null); } catch { return null; } };

let proxyFailures = 0;
let proxyBlocked = false;
let proxyPunished = false; // Track if we already blacklisted/deleted this proxy
const PROXY = process.env.VPLINK_PROXY || '';
const PROXY_HOST = PROXY.replace(/^https?:\/\//, '').replace(/:\d+$/, '');
// Parse IP and port from full proxy URL for deletion
const PROXY_IP = PROXY.replace(/^https?:\/\//, '').split(':')[0] || '';
const PROXY_PORT = parseInt((PROXY.match(/:(\d+)$/) || [])[1]) || 0;

const reportProxyFailure = async (reason) => {
  if (!PROXY_IP) return;
  proxyFailures++;
  log(`proxy failure #${proxyFailures}: ${reason} (${PROXY_IP}:${PROXY_PORT})`);

  // Blacklist locally + delete from Supabase on first failure
  if (!proxyPunished && PROXY_PORT) {
    proxyPunished = true;
    try { addProxyBlacklist(PROXY_IP, PROXY_PORT); log(`blacklisted ${PROXY_IP}:${PROXY_PORT} locally`); } catch {}
    try { const ok = await markDead(PROXY_IP, PROXY_PORT); if (ok) log(`deleted ${PROXY_IP}:${PROXY_PORT} from Supabase`); } catch {}
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
    'capecutapk.com', 'amazingbaba.com', 'wistfulseverely.com'];

  const isDestination = url => {
    if (!url || !url.startsWith('http')) return false;
    if (url.includes('chrome-error') || url.includes('about:blank')) return false;
    for (const p of DEST_PATTERNS) {
      if (url.includes(p)) return true;
    }
    return false;
  };

  // ── Ad domain detection ──
  // golaso.org hijacks pages via Google Ads. Must detect and navigate back.
  const AD_DOMAINS = ['golaso.org', 'doubleclick.net', 'googlesyndication.com', 'googleadservices.com'];
  const isAdDomain = url => {
    if (!url || !url.startsWith('http')) return false;
    for (const d of AD_DOMAINS) {
      if (url.includes(d)) return true;
    }
    return false;
  };

  // ── Template detection ──
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

  // ── Close ad overlay ──
  // Recording showed #block-cont-1 > div:nth-child(1) "X" button on every article page
  const closeAdOverlay = async () => {
    const closed = await safeEval(() => {
      const el = document.querySelector('#block-cont-1 > div:nth-child(1)');
      if (!el) return false;
      const style = getComputedStyle(el);
      if (style.display === 'none' || style.visibility === 'hidden') return false;
      if (el.getClientRects().length === 0) return false;
      el.click();
      return true;
    });
    if (closed) {
      log('closed ad overlay');
      await humanDelay(300, 800);
    }
    return closed;
  };

  // ── Handle bot-detection popup (#continueBtn) ──
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
    try {
      await page.locator('#continueBtn').click({ force: true, timeout: 5000 });
    } catch {
      await humanClick('#continueBtn');
    }
    await humanDelay(1000, 2000);

    if (safeURL().includes('#goog_rewarded')) {
      log('landed on #goog_rewarded, waiting for ad to complete...');
      return 'rewarded';
    }
    return true;
  };

  // ── Handle #goog_rewarded ad page ──
  // Recording showed: #goog_rewarded hash appears, video ad plays,
  // user clicks skip button on #google-rewarded-video, then ad completes.
  // Timeout 90s — recording showed ads take 30-60s to show skip button.
  const handleGoogRewarded = async () => {
    log('handling #goog_rewarded ad...');

    // Wait up to 90s for the ad to complete and redirect
    for (let w = 0; w < 90; w++) {
      await ms(1000);
      const cur = safeURL();

      // Check if ad redirected us away from #goog_rewarded
      if (!cur.includes('#goog_rewarded') && !isAdDomain(cur)) {
        log(`ad completed, redirected to: ${cur.substring(0, 100)}`);
        return true;
      }

      // Try to click skip button if visible (every 3s)
      if (w % 3 === 0) {
        const skipped = await safeEval(() => {
          // Try Skip button on video ad
          const skipBtns = document.querySelectorAll(
            '#google-rewarded-video .rewardDialogueWrapper button, ' +
            '#google-rewarded-video .videoAdUiSkipButton, ' +
            '.videoAdUiSkipButton, ' +
            '[class*="skip" i], ' +
            '.reward-overlay button, ' +
            '#skip-button, ' +
            'button[aria-label*="Skip" i]'
          );
          for (const btn of skipBtns) {
            const style = getComputedStyle(btn);
            if (style.display !== 'none' && style.visibility !== 'hidden' && btn.offsetParent !== null) {
              btn.click();
              return true;
            }
          }
          // Also try the X close button
          const closeBtn = document.querySelector('#google-rewarded-video > button');
          if (closeBtn && closeBtn.offsetParent !== null) {
            closeBtn.click();
            return true;
          }
          return false;
        });
        if (skipped) log('clicked skip/close button on ad');
      }

      // Check if timer is still counting (LINK1S case — #goog_rewarded appeared but
      // the article timer is still running underneath). If countdown is still active
      // and approaching 0, the ad may just be an overlay.
      if (w % 5 === 0) {
        const remaining = await getCountdown();
        if (remaining === 0 || remaining === -1) {
          // Timer done or gone — ad may have auto-completed
          log('countdown finished while on #goog_rewarded, clearing hash');
          await safeEval(() => {
            history.replaceState(null, '', window.location.pathname + window.location.search);
          });
          await humanDelay(500, 1000);
          if (!safeURL().includes('#goog_rewarded')) {
            log('hash cleared, no longer on #goog_rewarded');
            return true;
          }
        }
      }
    }

    log('#goog_rewarded ad did not complete in 90s');
    // Try clearing the hash fragment as last resort
    await safeEval(() => {
      if (window.location.hash) {
        history.replaceState(null, '', window.location.pathname + window.location.search);
      }
    });
    await humanDelay(1000, 2000);
    return safeURL().includes('#goog_rewarded') ? false : true;
  };

  // ── Wait for countdown to finish ──
  const waitForCountdown = async (template, maxWaitSec) => {
    const maxIter = maxWaitSec * 2;
    for (let i = 0; i < maxIter; i++) {
      const remaining = await getCountdown();
      if (remaining === 0) return 'done';
      if (remaining === -1 && i > 4) return 'done'; // Timer element gone after initial load = done

      // Handle popup that may appear during countdown
      if (i % 4 === 0) {
        await closeAdOverlay();
        const popupResult = await handlePopup();
        if (popupResult === 'rewarded') return 'rewarded';
      }

      if (i % 10 === 0) await humanScroll();
      await ms(500);
    }
    return false;
  };

  // ── Detect ad hijack (golaso.org etc.) and navigate back ──
  const checkAdHijack = async () => {
    const url = safeURL();
    if (isAdDomain(url) && !url.includes('vplink.in')) {
      log(`AD HIJACK detected: ${url.substring(0, 80)}, navigating back...`);
      await page.goBack({ waitUntil: 'domcontentloaded', timeout: 15000 }).catch(async () => {
        // goBack failed, force navigate to vplink.in
        log('goBack failed, force-navigating to vplink.in');
        lastBase = '';
        await page.goto(`https://vplink.in/${KEY}`, { waitUntil: 'domcontentloaded', timeout: navTimeout }).catch(() => {});
      });
      await humanDelay(2000, 4000);
      return true;
    }
    return false;
  };

  // ── Template A (TP): tp-time countdown → #continueBtn → #goog_rewarded → tp-snp2 ──
  const handleTP = async () => {
    log('template: TP (tp-time countdown)');

    // Close ad overlay first (recording showed it on every page)
    await closeAdOverlay();

    // Wait for countdown (up to 40s — timer starts at ~23, popup appears at ~6s remaining)
    const countdownResult = await waitForCountdown('tp', 40);

    if (countdownResult === 'rewarded') {
      log('popup sent us to #goog_rewarded during countdown');
      await handleGoogRewarded();
      // After ad completes, try clicking tp-snp2
      await humanDelay(500, 1500);
      const clicked = await humanClick('#tp-snp2');
      if (clicked) log('clicked tp-snp2 after rewarded ad');
      return true;
    }

    if (countdownResult !== 'done') log('TP countdown timeout, trying button anyway');

    // Popup may appear near end of countdown
    const popupResult = await handlePopup();
    if (popupResult === 'rewarded') {
      log('on #goog_rewarded after countdown, waiting for ad...');
      await handleGoogRewarded();
      await humanDelay(500, 1500);
      await humanClick('#tp-snp2');
      return true;
    }

    await humanDelay(500, 1500);

    // Click #tp-snp2 when visible
    const clicked = await humanClick('#tp-snp2');
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

  // ── Template B (CE): ce-time countdown → btn6 Verify → btn7 Continue ──
  const handleCE = async () => {
    log('template: CE (ce-time countdown)');

    await closeAdOverlay();

    // Wait for countdown (up to 40s — timer starts at ~23)
    const countdownResult = await waitForCountdown('ce', 40);
    if (countdownResult === 'rewarded') {
      log('popup sent us to #goog_rewarded during CE countdown');
      await handleGoogRewarded();
      return true;
    }
    if (countdownResult !== 'done') log('CE countdown timeout, trying buttons anyway');

    await humanDelay(500, 1500);

    // Click #btn6 (Verify) first
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
    if (!btn7Clicked) await humanClick('#btn7');
    log('clicked btn7 (Continue)');
    return true;
  };

  // ── Template C (LINK1S): startCountdownBtn → countdown → cross-snp2 ──
  // Recording showed: click #startCountdownBtn → #goog_rewarded appears immediately →
  // timer continues counting underneath → skip ad → timer reaches 0 → #cross-snp2 appears
  const handleLINK1S = async () => {
    log('template: LINK1S (startCountdownBtn)');

    await closeAdOverlay();

    // Click #startCountdownBtn to start the countdown
    const started = await humanClick('#startCountdownBtn');
    if (started) {
      log('clicked startCountdownBtn, waiting for countdown...');
      await humanDelay(500, 1000);
    }

    // #goog_rewarded may appear immediately after clicking startCountdownBtn
    const curUrl = safeURL();
    if (curUrl.includes('#goog_rewarded')) {
      log('#goog_rewarded appeared after startCountdownBtn click, handling ad...');
      await handleGoogRewarded();
      await humanDelay(500, 1500);
    }

    // Wait for countdown (up to 30s — timer resets to ~14s after click)
    const countdownResult = await waitForCountdown('link1s', 30);

    if (countdownResult === 'rewarded') {
      log('popup sent us to #goog_rewarded during LINK1S countdown');
      await handleGoogRewarded();
      await humanDelay(500, 1500);
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

    const buttons = [
      '#tp-snp2', '#cross-snp2', '#btn6',
      '#btn7 > button', '#btn7',
      '#continueBtn',
      '#main > div:nth-child(4) > center > center > a',
    ];

    for (const sel of buttons) {
      await closeAdOverlay();
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

        const startUrl = safeURL();
        for (let w = 0; w < 15; w++) {
          await ms(1000);
          if (safeURL() !== startUrl) return true;
        }
      }
    }

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

    // Initial settle
    await humanDelay(2000, 4000);
    await humanScroll();
    await closeAdOverlay();

    // Detect template by DOM structure (NOT by domain)
    const template = await detectTemplate();
    log(`detected template: ${template}`);

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

    // Wait for navigation after button click
    if (navigated) {
      const waitStart = safeURL();
      const waitBase = urlBase(waitStart);
      for (let w = 0; w < 20; w++) {
        await ms(1000);
        const cur = safeURL();
        const curBase = urlBase(cur);
        if (cur !== waitStart && curBase !== waitBase) {
          log(`navigated to: ${cur.substring(0, 100)}`);
          return true;
        }
        // Detect ad hijack during navigation wait
        if (isAdDomain(cur)) {
          log(`ad hijack during nav wait: ${cur.substring(0, 80)}`);
          await page.goBack({ waitUntil: 'domcontentloaded', timeout: 15000 }).catch(() => {});
          await humanDelay(2000, 4000);
          return true;
        }
      }
      const finalUrl = safeURL();
      if (finalUrl !== startUrl) {
        log(`page changed: ${finalUrl.substring(0, 100)}`);
        return true;
      }
      log('buttons clicked but no URL change detected, continuing');
      return true;
    }

    return false;
  };

  // ── Get Link handler ──
  // Recording showed: #get-link href already contains destination URL (apkmirror.com/...)
  // Click opens new tab → tracking redirects → final destination
  const doGetLink = async () => {
    try {
      for (const p of context.pages()) {
        if (p !== page) { try { await p.close(); } catch {} }
      }

      const btn = await page.waitForSelector('#get-link', { timeout: 40000 }).catch(() => null);
      if (!btn) return false;

      // Capture href BEFORE clicking — recording showed it already has the destination
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
            // If URL is a redirect wrapper, wait for it to resolve
            const isRedirect = popupUrl.includes('linkedin.com/redir') || popupUrl.includes('google.com/url')
              || popupUrl.includes('facebook.com/l.php') || popupUrl.includes('t.co/')
              || popupUrl.includes('wistfulseverely.com');
            if (isRedirect) {
              log(`redirect wrapper detected, waiting for final URL...`);
              for (let r = 0; r < 20; r++) {
                await ms(1000);
                try {
                  const newUrl = newTab.url();
                  if (newUrl && newUrl !== popupUrl && !newUrl.includes('about:blank')) {
                    popupUrl = newUrl;
                    break;
                  }
                } catch { break; }
              }
            }
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

      // Fallback: use href captured before clicking
      if (linkHref && linkHref.startsWith('http')) {
        destinationUrl = linkHref;
        log(`destination (href): ${linkHref.substring(0,100)}`);
        const elapsed = Date.now() - clickTime;
        const wait = Math.max(0, 25000 - elapsed);
        if (wait > 500) { log(`tracking wait: ${wait}ms`); await ms(wait); }
        return true;
      }
    } catch (error) {
      log(`get-link handler failed: ${error.message || 'unknown error'}`);
    }
    return false;
  };

  // ── Main flow ──
  log('='.repeat(50));
  log(`starting funnel for KEY=${KEY}`);
  if (DEBUG) log('debug mode active');
  const navTimeout = process.env.VPLINK_PROXY ? 45000 : 45000;
  let skipMainLoop = false;

  // YouTube referral: navigate to YouTube first so browser naturally sets Referer
  // OLD approach (page.route header injection) broke vplink.in JS redirects.
  // Always use YouTube-first navigation — works with and without proxy.
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

  const hardGoto = async (url, opts) => {
    const gotoPromise = page.goto(url, opts);
    const abortPromise = new Promise((_, reject) => {
      setTimeout(() => reject(new Error('hard-timeout')), 30000);
    });
    return Promise.race([gotoPromise, abortPromise]);
  };

  try {
    await hardGoto(`https://vplink.in/${KEY}`, { waitUntil: 'domcontentloaded', timeout: navTimeout });
  } catch (e) {
    log(`first goto failed: ${e.message}, retrying...`);
    if (PROXY && !e.message.includes('hard-timeout')) {
      await reportProxyFailure('first-goto-error');
    } else if (PROXY && e.message.includes('hard-timeout')) {
      await reportProxyFailure('first-goto-hang');
      proxyBlocked = true;
      skipMainLoop = true;
    }
    await ms(2000);
    if (!skipMainLoop) {
      try {
        await hardGoto(`https://vplink.in/${KEY}`, { waitUntil: 'domcontentloaded', timeout: navTimeout });
      } catch (e2) {
        log(`second goto failed: ${e2.message}`);
        if (PROXY) await reportProxyFailure('second-goto-error');
        proxyBlocked = true;
        skipMainLoop = true;
      }
    }
  }
  if (!skipMainLoop) await humanDelay(2000, 4000);
  await debugShot('02-after-nav');

  if (!skipMainLoop) {

  // Wait for auto-redirect
  log('waiting for auto-redirect...');
  const redirectWait = PROXY ? 15 : 30;
  for (let i = 0; i < redirectWait; i++) {
    await ms(1000);
    if (!safeURL().includes('vplink.in')) break;
  }
  await debugShot('03-after-redirect');

  // Handle Cloudflare challenge
  for (let attempt = 0; attempt < 2; attempt++) {
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
    const cfWait = PROXY ? 20 : 40;
    for (let i = 0; i < cfWait; i++) {
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

  // Check stuck on vplink.in
  if (safeURL().includes('vplink.in') && !safeURL().includes('cdn-cgi')) {
    const hasGl = await safeEval(() => !!document.getElementById('get-link'));
    if (!hasGl && PROXY) {
      log('stuck on vplink.in — proxy may be blocking JS redirects');
      proxyBlocked = true;
      await reportProxyFailure('vplink-no-redirect');
      skipMainLoop = true;
    }
  }

  } // end if (!skipMainLoop)

  // ── DOM dump helper ──
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
  let intermediateStuckCount = 0;
  let lastBase = '';
  let googRewardRetries = 0;
  let adHijackCount = 0;
  let lastStuckArticle = '';
  const MAX_GOOG_REWARD_RETRIES = 3;
  const MAX_URL_VISITS = 4; // Recording showed 4 articles is normal
  const MAX_AD_HIJACKS = 5; // Allow multiple ad hijacks before giving up
  const urlVisits = {};

  for (let cycle = 0; cycle < 30 && !destinationUrl && !skipMainLoop; cycle++) {
    const url = safeURL();
    if (!url) { await ms(2000); continue; }
    const base = urlBase(url);

    // Check for ad hijack first
    if (await checkAdHijack()) {
      adHijackCount++;
      if (adHijackCount > MAX_AD_HIJACKS) {
        log(`too many ad hijacks (${adHijackCount}), proxy likely injecting ads`);
        if (PROXY) await reportProxyFailure('too-many-ad-hijacks');
        proxyBlocked = true;
        break;
      }
      lastBase = '';
      continue;
    }

    // Track URL visit count for stuck-loop detection
    const urlKey = url.split('#')[0];
    const isIntermediate = url.includes('learn_more.php') || url.includes('studieseducates')
      || url.includes('studiiessuniversitiess') || url.includes('universitesstudiiess');
    if (!url.includes('vplink.in') && !isIntermediate) {
      urlVisits[urlKey] = (urlVisits[urlKey] || 0) + 1;
      if (urlVisits[urlKey] >= MAX_URL_VISITS) {
        lastStuckArticle = urlKey;
        log(`STUCK: same article visited ${urlVisits[urlKey]} times, force-navigating`);
        if (PROXY) await reportProxyFailure('article-stuck-loop');
        lastBase = '';
        await page.goto(`https://vplink.in/${KEY}`, { waitUntil: 'domcontentloaded', timeout: navTimeout }).catch(() => {});
        await humanDelay(3000, 5000);
        continue;
      }
    }

    // Skip hash-only changes (#goog_rewarded etc.)
    if (base === lastBase && url.includes('#')) {
      const hash = url.split('#')[1];
      log(`[cycle ${cycle + 1}] hash-only change (${hash}), waiting...`);

      // Handle #goog_rewarded hash
      if (hash === 'goog_rewarded') {
        await handleGoogRewarded();
        await humanDelay(500, 1500);
        // After ad, try to continue
        const clicked = await humanClick('#tp-snp2') || await humanClick('#cross-snp2');
        if (clicked) log('clicked button after #goog_rewarded ad');
        await humanDelay(1000, 2000);
        lastBase = urlBase(safeURL());
        continue;
      }

      await humanDelay(3000, 5000);
      for (let w = 0; w < 8; w++) {
        await ms(1000);
        const cur = safeURL();
        if (urlBase(cur) !== base) {
          log(`navigated away: ${cur.substring(0, 100)}`);
          break;
        }
      }
      if (urlBase(safeURL()) === base) {
        log('still stuck on same page after hash wait, navigating to vplink.in');
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

      if (btnState === 'missing' || btnState === null) {
        if (vplinkArrivals >= 5) {
          log('stuck on vplink.in with no article page — proxy blocking JS redirects');
          proxyBlocked = true;
          if (PROXY) await reportProxyFailure('vplink-get-link-missing');
          break;
        }
        await ms(2000);
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

    // ── #goog_rewarded in main loop ──
    if (url.includes('#goog_rewarded')) {
      googRewardRetries++;
      log(`#goog_rewarded in main loop (attempt ${googRewardRetries})`);
      if (googRewardRetries > MAX_GOOG_REWARD_RETRIES) {
        log(`#goog_rewarded stuck after ${googRewardRetries} retries, force-navigating`);
        googRewardRetries = 0;
        lastBase = '';
        await page.goto(`https://vplink.in/${KEY}`, { waitUntil: 'domcontentloaded', timeout: navTimeout }).catch(() => {});
        await humanDelay(3000, 5000);
        continue;
      }
      const rewardedOk = await handleGoogRewarded();
      if (rewardedOk) {
        await humanDelay(500, 1500);
        const clicked = await humanClick('#tp-snp2') || await humanClick('#cross-snp2');
        if (clicked) log('clicked button after #goog_rewarded');
      }
      lastBase = urlBase(safeURL());
      continue;
    }

    // ── Intermediate redirect pages ──
    if (url.includes('learn_more.php') || url.includes('studieseducates')
      || url.includes('studiiessuniversitiess') || url.includes('universitesstudiiess')) {
      log('intermediate redirect page, waiting for auto-redirect...');
      const intermediateBase = urlBase(url);
      let redirected = false;
      for (let w = 0; w < 15; w++) {
        await ms(1000);
        const cur = safeURL();
        const curBase = urlBase(cur);
        if (curBase !== intermediateBase && !cur.includes('learn_more.php') && !cur.includes('studieseducates')) {
          log(`redirected to: ${cur.substring(0, 100)}`);
          await humanDelay(500, 1500);
          redirected = true;
          break;
        }
      }
      if (!redirected) {
        intermediateStuckCount++;
        log(`intermediate page not redirecting (stuck #${intermediateStuckCount})`);
        if (intermediateStuckCount >= 3) {
          log('intermediate stuck 3x — forcing');
          if (PROXY) await reportProxyFailure('intermediate-stuck');
          proxyBlocked = true;
          intermediateStuckCount = 0;
          lastBase = '';
          break;
        }
      } else {
        intermediateStuckCount = 0;
      }
      lastBase = urlBase(safeURL());
      continue;
    }

    // ── Article / unknown page ──
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
  if (!destinationUrl && !proxyBlocked) {
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
  process.exit(destinationUrl ? 0 : (proxyBlocked ? 2 : 3));
})().catch(async (error) => {
  console.error(`Fatal automation error: ${error.message || error}`);
  if (browser) await browser.close().catch(() => {});
  process.exit(1);
});
