let chromium;
try { ({ chromium } = require('playwright')); }
catch { ({ chromium } = require('playwright-core')); }
const fs = require('fs');
const path = require('path');
let markDead, addProxyBlacklist;
try { ({ markDead } = require('./proxy-rotator')); } catch { markDead = async () => false; }
try { ({ addProxyBlacklist } = require('./config')); } catch { addProxyBlacklist = () => {}; }

let BASE_DOMAIN = 'vplink.in';
let KEY = process.argv[2] || process.env.VPLINK_KEY;
if (!KEY) { console.error('Usage: node automation.js <key_or_url>'); process.exit(1); }
// Support full URLs: https://linkpays.in/GE9Ky → domain=linkpays.in, key=GE9Ky
if (KEY.startsWith('http')) {
  try {
    const u = new URL(KEY);
    BASE_DOMAIN = u.hostname;
    KEY = u.pathname.replace(/^\//, '').split(/[?#]/)[0];
  } catch { /* keep defaults */ }
}
if (!KEY) { console.error('No key extracted from URL'); process.exit(1); }
const START_URL = `https://${BASE_DOMAIN}/${KEY}`;

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

  const DEST_PATTERNS = ['12indiaplay.com', 'vv53243', 'casino', 'one-vv',
    'apkmirror.com', 'play.google.com', 'download', '.apk',
    'capecutapk.com', 'amazingbaba.com',
    'ti.com', '1xbet', 'whotop.cc'];

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
  // DOM analysis revealed:
  // - TP #tp-time starts at 23 (no cookie) or 15 (with adcadg cookie), interval 1900ms, hidden
  // - CE #ce-wait1 starts hidden (display:none), timer only starts after ad click + 10s
  //   CE #ce-time starts at 24 (no cookie) or 15 (with eonudb cookie), interval 1500ms
  // - LINK1S #link1s-time shows "8" initially but timer starts at 15 after clicking
  //   #startCountdownBtn, interval 1500ms. #cross-snp2 appears at timer=-1 (not 0)
  const getCountdown = async () => {
    const result = await safeEval(() => {
      const tpTime = document.getElementById('tp-time');
      if (tpTime) {
        const v = parseInt(tpTime.textContent);
        return isNaN(v) ? -1 : v;
      }
      const ceTime = document.getElementById('ce-time');
      if (ceTime) {
        // CE timer only runs when #ce-wait1 is visible
        const ceWait = document.getElementById('ce-wait1');
        if (ceWait && getComputedStyle(ceWait).display === 'none') return -1; // timer not running yet
        const v = parseInt(ceTime.textContent);
        return isNaN(v) ? -1 : v;
      }
      const link1sTime = document.getElementById('link1s-time');
      if (link1sTime) {
        // LINK1S: timer element exists. Check if button was clicked by looking at its text/state
        const btn = document.getElementById('startCountdownBtn');
        const btnText = btn ? btn.textContent.trim().toLowerCase() : '';
        const btnClicked = btn && (btn.disabled || btnText.includes('counting') || btnText.includes('wait'));
        if (!btnClicked && btn && !btn.disabled) return -1; // not clicked yet
        const v = parseInt(link1sTime.textContent);
        // LINK1S timer counts to -1 (not 0) when cross-snp2 becomes visible
        return isNaN(v) ? -1 : v;
      }
      return -1;
    });
    return result ?? -1;
  };

  // ── Close ad overlay ──
  // DOM analysis confirmed TWO overlay structures:
  // 1. #block-cont-1: dynamically created <div> "X" close button, z-index:10000
  // 2. #gcont: TP template full-screen overlay with .bgcount > svg (X close icon), z-index:99
  const closeAdOverlay = async () => {
    let closed = await safeEval(() => {
      // Try #block-cont-1 first (CE/LINK1S templates)
      const container = document.getElementById('block-cont-1');
      if (container && getComputedStyle(container).display !== 'none') {
        const closeDiv = container.querySelector('div');
        if (closeDiv && closeDiv.textContent.trim() === 'X') {
          const style = getComputedStyle(closeDiv);
          if (style.display !== 'none' && style.visibility !== 'hidden') {
            closeDiv.click();
            return 'block-cont-1';
          }
        }
      }
      return false;
    });

    // Also try #gcont overlay (TP template)
    if (!closed) {
      closed = await safeEval(() => {
        const gcont = document.getElementById('gcont');
        if (!gcont) return false;
        const style = getComputedStyle(gcont);
        if (style.position !== 'fixed') return false; // already dismissed
        // Click the SVG close icon in .bgcount
        const svg = gcont.querySelector('.bgcount svg');
        if (svg) { svg.click(); return 'gcont-svg'; }
        return false;
      });
    }

    if (closed) {
      log(`closed ad overlay: ${closed}`);
      await humanDelay(300, 800);
    }
    return !!closed;
  };

  // ── Handle bot-detection popup ──
  // Recording showed TWO popup structures:
  // 1. #continueBtn (dynamic, appears ~35s on some TP pages, has CSS pulse animation)
  // 2. #gcont overlay (appears on all TP pages, contains #ggd-container with ad instructions)
  const handlePopup = async () => {
    // Check for #continueBtn (dynamic popup)
    const continueBtnVisible = await safeEval(() => {
      const el = document.getElementById('continueBtn');
      if (!el) return false;
      const style = getComputedStyle(el);
      return style.display !== 'none' && style.visibility !== 'hidden'
        && el.getClientRects().length > 0;
    });

    // Check for #gcont overlay (TP template full-screen overlay)
    const gcontVisible = await safeEval(() => {
      const el = document.getElementById('gcont');
      if (!el) return false;
      const style = getComputedStyle(el);
      // #gcont has position:fixed when active, static when dismissed
      return style.position === 'fixed' && style.display !== 'none'
        && el.getClientRects().length > 0;
    });

    if (!continueBtnVisible && !gcontVisible) return false;

    log(`popup detected (continueBtn=${continueBtnVisible}, gcont=${gcontVisible}), clicking...`);
    await humanDelay(500, 1500);

    // Try clicking #continueBtn first (it triggers #goog_rewarded)
    if (continueBtnVisible) {
      try {
        await page.locator('#continueBtn').click({ force: true, timeout: 5000 });
      } catch {
        await humanClick('#continueBtn');
      }
    } else if (gcontVisible) {
      // Click the close/dismiss area of #gcont overlay
      // DOM structure: #gcont > .cls1 > .bgcount > svg (X close icon)
      const gcontClicked = await safeEval(() => {
        const svg = document.querySelector('#gcont .bgcount svg');
        if (svg) { svg.click(); return 'svg-close'; }
        const gcont = document.getElementById('gcont');
        if (gcont) { gcont.click(); return 'gcont-click'; }
        return false;
      });
      if (gcontClicked) log(`clicked gcont overlay: ${gcontClicked}`);
    }

    // Recording showed #goog_rewarded hash takes 2-8s to appear after click
    for (let w = 0; w < 10; w++) {
      await ms(1000);
      if (safeURL().includes('#goog_rewarded')) {
        log('landed on #goog_rewarded, waiting for ad to complete...');
        return 'rewarded';
      }
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
          // Recording showed exact DOM: #google-rewarded-video > button > img (play)
          // and #google-rewarded-video > div...Skip (skip)
          const selectors = [
            '#google-rewarded-video > button > img',
            '#google-rewarded-video > div',
            '#google-rewarded-video .rewardDialogueWrapper button',
            '#google-rewarded-video .videoAdUiSkipButton',
            '.videoAdUiSkipButton',
            '[class*="skip" i]',
            '.reward-overlay button',
            '#skip-button',
            'button[aria-label*="Skip" i]',
            '#google-rewarded-video > button',
          ];
          for (const sel of selectors) {
            const els = document.querySelectorAll(sel);
            for (const el of els) {
              const style = getComputedStyle(el);
              if (style.display !== 'none' && style.visibility !== 'hidden' && el.offsetParent !== null) {
                el.click();
                return true;
              }
            }
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
  // Recording showed: TP timer takes ~44s from 23→0, each "second" = ~1.9s real
  // LINK1S timer takes ~22.5s from 15→-1, each "second" = ~1.5s real
  // Also check for #goog_rewarded URL directly (handlePopup may have missed it)
  const waitForCountdown = async (template, maxWaitSec) => {
    const maxIter = maxWaitSec * 2;
    let lastVal = -2;
    let stuckCount = 0;
    for (let i = 0; i < maxIter; i++) {
      // Check for #goog_rewarded hash directly (recording showed it appears after popup click)
      if (safeURL().includes('#goog_rewarded')) return 'rewarded';

      const remaining = await getCountdown();
      if (remaining === 0) return 'done';
      // LINK1S timer reaches -1 (not 0) when cross-snp2 becomes visible
      if (remaining === -1 && template === 'link1s' && i > 4) return 'done';
      if (remaining === -1 && i > 4) return 'done'; // Timer element gone after initial load = done

      // Stuck timer detection: if countdown stays same value for 5s (10 polls), timer JS is broken
      if (remaining > 0 && remaining === lastVal) {
        stuckCount++;
        if (stuckCount >= 10) {
          log(`countdown stuck at ${remaining}s for 5s — timer JS broken, forcing`);
          return 'stuck';
        }
      } else {
        stuckCount = 0;
        lastVal = remaining;
      }

      // Log countdown value periodically for debugging
      if (i % 10 === 0 && remaining > 0) log(`countdown ${template}: ${remaining}s remaining`);

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
        await page.goto(`https://${BASE_DOMAIN}/${KEY}`, { waitUntil: 'domcontentloaded', timeout: navTimeout }).catch(() => {});
      });
      await humanDelay(2000, 4000);
      return true;
    }
    return false;
  };

  // ── Template A (TP): tp-time countdown → #continueBtn → #goog_rewarded → tp-snp2 ──
  // Recording showed: timer 23→0 over ~44s, popup appears at tp-time=6, tp-snp2 visible at tp-time=1
  const handleTP = async () => {
    log('template: TP (tp-time countdown)');

    // Close ad overlay first (recording showed it on every page)
    await closeAdOverlay();

    // Wait for countdown (up to 50s — recording showed TP timer takes ~44s from 23→0)
    const countdownResult = await waitForCountdown('tp', 50);

    if (countdownResult === 'rewarded') {
      log('popup sent us to #goog_rewarded during countdown');
      await handleGoogRewarded();
      // Clear hash left by ad (e.g. #content) so main loop doesn't treat as hash-only change
      await safeEval(() => {
        if (window.location.hash) history.replaceState(null, '', window.location.pathname + window.location.search);
      });
      await humanDelay(500, 1000);
      // After #goog_rewarded, page's setInterval is often disrupted (stuck at 1).
      // Force-invoke the timer completion logic to make tp-snp2 visible.
      log('force-invoking showNextProcess after rewarded ad...');
      await safeEval(() => {
        // Hide the timer wrapper and show the continue button directly
        const wait1 = document.getElementById('tp-wait1');
        const wait2 = document.getElementById('tp-wait2');
        const snp2 = document.getElementById('tp-snp2');
        if (wait1) wait1.style.display = 'none';
        if (wait2) wait2.style.display = 'none';
        if (snp2) snp2.style.display = 'inline-block';
        // Also try calling the page's own showNextProcess if it exists
        if (typeof showNextProcess === 'function') {
          try { showNextProcess(); } catch {}
        }
      });
      await humanDelay(1000, 2000);
      const clicked = await humanClick('#tp-snp2');
      if (clicked) log('clicked tp-snp2 after rewarded ad');
      return clicked;
    }

    if (countdownResult === 'stuck') {
      log('countdown stuck — forcing button visibility');
      await safeEval(() => {
        const wait1 = document.getElementById('tp-wait1');
        const wait2 = document.getElementById('tp-wait2');
        const snp2 = document.getElementById('tp-snp2');
        if (wait1) wait1.style.display = 'none';
        if (wait2) wait2.style.display = 'none';
        if (snp2) snp2.style.display = 'inline-block';
        if (typeof showNextProcess === 'function') {
          try { showNextProcess(); } catch {}
        }
      });
      await humanDelay(1000, 2000);
    }

    if (countdownResult !== 'done' && countdownResult !== 'stuck') log('TP countdown timeout, trying button anyway');

    // Popup may appear near end of countdown
    const popupResult = await handlePopup();
    if (popupResult === 'rewarded') {
      log('on #goog_rewarded after countdown, waiting for ad...');
      await handleGoogRewarded();
      await safeEval(() => {
        if (window.location.hash) history.replaceState(null, '', window.location.pathname + window.location.search);
      });
      await humanDelay(500, 1000);
      // Force button visibility — timer JS likely disrupted by ad
      await safeEval(() => {
        const wait1 = document.getElementById('tp-wait1');
        const wait2 = document.getElementById('tp-wait2');
        const snp2 = document.getElementById('tp-snp2');
        if (wait1) wait1.style.display = 'none';
        if (wait2) wait2.style.display = 'none';
        if (snp2) snp2.style.display = 'inline-block';
        if (typeof showNextProcess === 'function') {
          try { showNextProcess(); } catch {}
        }
      });
      await humanDelay(1000, 2000);
      const clicked = await humanClick('#tp-snp2');
      return clicked;
    }

    await humanDelay(1000, 2000);

    // Wait for #tp-snp2 to become visible (recording showed it appears at tp-time=1)
    // Don't click hidden elements — humanClick JS fallback clicks hidden elements which don't navigate
    let clicked = false;
    for (let w = 0; w < 15; w++) {
      const visible = await safeEval(() => {
        const el = document.getElementById('tp-snp2');
        if (!el) return false;
        const style = getComputedStyle(el);
        return style.display !== 'none' && style.visibility !== 'hidden'
          && el.getClientRects().length > 0;
      });
      if (visible) {
        clicked = await humanClick('#tp-snp2');
        if (clicked) {
          log('clicked #tp-snp2');
          break;
        }
      }
      await ms(1000);
    }

    if (!clicked) {
      // Fallback: find anchor with learn_more.php href
      const fallback = await safeEval(() => {
        const links = document.querySelectorAll('a');
        for (const a of links) {
          if (a.href && a.href.includes('learn_more.php') && a.offsetParent !== null) {
            a.click();
            return true;
          }
        }
        return false;
      });
      if (fallback) log('clicked learn_more.php fallback link');
    }
    return clicked || false;
  };

  // ── Template B (CE): ce-time countdown → btn6 Verify → btn7 Continue ──
  // DOM analysis revealed:
  // - #ce-wait1 starts hidden (display:none). Timer only starts after:
  //   1. Ad overlay appears (1s after load) in #overcn
  //   2. User clicks/interacts with ad iframe (sets cookie 'eonudb')
  //   3. 10 seconds elapse (localStorage 'iorghupt' timestamp)
  //   4. #ce-wait1 becomes visible, timer starts at 24 (or 15 with existing cookie)
  // - #btn6 "Verify" calls nextbtn() which hides #btn6 and shows #btn7
  // - #btn7 is <a> wrapping <button>, href goes to NEXT article directly (NOT learn_more.php)
  // Flow: click ad area → wait for ce-wait1 → wait for countdown → btn6 → btn7 → next article
  const handleCE = async () => {
    log('template: CE (ce-time countdown)');

    await closeAdOverlay();

    // Step 1: Click on ad area to trigger cookie/localStorage for timer
    log('clicking ad area to trigger CE timer...');
    const adClicked = await safeEval(() => {
      // Click on #overcn (Google Ads container) to trigger iframe focus detection
      const adContainer = document.getElementById('overcn');
      if (adContainer) {
        // Find and click the first ad iframe or link
        const iframe = adContainer.querySelector('iframe');
        if (iframe) { iframe.focus(); iframe.click(); return 'iframe'; }
        const link = adContainer.querySelector('a');
        if (link) { link.click(); return 'link'; }
        adContainer.click();
        return 'container';
      }
      // Fallback: click any ad area
      const gads = document.getElementById('gads');
      if (gads) { gads.click(); return 'gads'; }
      return false;
    });
    if (adClicked) log(`clicked ad area: ${adClicked}`);

    // Step 2: Wait for #ce-wait1 to become visible (timer only starts after ad interaction + 10s)
    log('waiting for ce-wait1 to become visible (ad interaction + 10s delay)...');
    let ceWaitVisible = false;
    for (let w = 0; w < 45; w++) { // up to 45s for ad click + 10s wait + timer start
      ceWaitVisible = await safeEval(() => {
        const el = document.getElementById('ce-wait1');
        if (!el) return false;
        return getComputedStyle(el).display !== 'none';
      });
      if (ceWaitVisible) break;
      // Re-try clicking ad area every 5s if not visible yet
      if (w > 0 && w % 5 === 0) {
        await safeEval(() => {
          const adContainer = document.getElementById('overcn');
          if (adContainer) {
            const iframe = adContainer.querySelector('iframe');
            if (iframe) { iframe.focus(); iframe.click(); return; }
            adContainer.click();
          }
        });
      }
      // Check for ad hijack during wait
      if (await checkAdHijack()) return true;
      await ms(1000);
    }

    if (!ceWaitVisible) {
      log('ce-wait1 never became visible, trying buttons anyway...');
    }

    // Now wait for countdown (up to 60s — CE timer can be 24*1.5s = 36s)
    const countdownResult = await waitForCountdown('ce', 60);
    if (countdownResult === 'rewarded') {
      log('popup sent us to #goog_rewarded during CE countdown');
      await handleGoogRewarded();
      await safeEval(() => {
        if (window.location.hash) history.replaceState(null, '', window.location.pathname + window.location.search);
      });
      await humanDelay(500, 1000);
      // CE buttons may now be visible — check
      const btn7vis = await safeEval(() => {
        const el = document.querySelector('#btn7 > button');
        if (!el) return false;
        return getComputedStyle(el).display !== 'none' && el.offsetParent !== null;
      });
      if (btn7vis) {
        await humanClick('#btn7 > button');
        log('clicked btn7 after rewarded ad');
        return true;
      }
      return true; // Return true so main loop re-evaluates
    }
    if (countdownResult !== 'done') log('CE countdown timeout, trying buttons anyway');

    // Check for ad hijack before clicking
    if (await checkAdHijack()) return true;

    await humanDelay(1000, 2000);

    // Wait for #btn6 to be visible (recording showed it appears when timer reaches 0)
    let btn6Visible = false;
    for (let w = 0; w < 15; w++) {
      btn6Visible = await safeEval(() => {
        const el = document.getElementById('btn6');
        if (!el) return false;
        const style = getComputedStyle(el);
        return style.display !== 'none' && style.visibility !== 'hidden'
          && el.getClientRects().length > 0;
      });
      if (btn6Visible) break;
      // Also check for ad hijack during wait
      if (await checkAdHijack()) return true;
      await ms(1000);
    }

    // Click #btn6 (Verify) first
    if (btn6Visible) {
      await humanClick('#btn6');
      log('clicked btn6 (Verify)');
      // Wait up to 8s — btn6 may navigate OR just hide itself
      const startUrl = safeURL();
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

    // Wait for #btn7 > button to be visible
    for (let w = 0; w < 10; w++) {
      const btn7Visible = await safeEval(() => {
        const el = document.querySelector('#btn7 > button');
        if (!el) return false;
        const style = getComputedStyle(el);
        return style.display !== 'none' && style.visibility !== 'hidden'
          && el.getClientRects().length > 0;
      });
      if (btn7Visible) {
        // DOM analysis confirmed: #btn7 is <a> wrapping <button>, href = next article
        // Click the <a> directly for reliable navigation
        const clicked = await safeEval(() => {
          const a = document.getElementById('btn7');
          if (a && a.tagName === 'A' && a.href) {
            window.location.href = a.href;
            return true;
          }
          const btn = document.querySelector('#btn7 > button');
          if (btn) { btn.click(); return true; }
          return false;
        });
        if (clicked) {
          log('clicked btn7 (Continue) via <a> href');
          return true;
        }
        await humanClick('#btn7 > button');
        log('clicked btn7 (Continue) via button');
        return true;
      }
      await ms(1000);
    }

    // Fallback: click #btn7 directly
    await humanClick('#btn7');
    log('clicked btn7 fallback');
    return true;
  };

  // ── Template C (LINK1S): startCountdownBtn → countdown → cross-snp2 ──
  // DOM analysis revealed:
  // - #startCountdownBtn starts enabled, text "click to verify"
  // - After click: button becomes disabled, text "Counting down..."
  // - #link1s-time shows 8 initially, resets to 15 after click, interval 1500ms
  // - #cross-snp2 appears when timer reaches -1 (NOT 0)
  // - #goog_rewarded appears after clicking startCountdownBtn (ad triggered by button click)
  // - #cross-snp2 click goes to learn_more.php
  const handleLINK1S = async () => {
    log('template: LINK1S (startCountdownBtn)');

    await closeAdOverlay();

    // Click #startCountdownBtn to start the countdown
    let started = await humanClick('#startCountdownBtn');
    if (started) {
      log('clicked startCountdownBtn via Playwright');
      await humanDelay(500, 1000);
    }

    // Also try JS click to ensure event handlers fire
    await safeEval(() => {
      const btn = document.getElementById('startCountdownBtn');
      if (btn && !btn.disabled) btn.click();
    });

    // Check button state
    const btnState = await safeEval(() => {
      const btn = document.getElementById('startCountdownBtn');
      if (!btn) return 'missing';
      return `disabled=${btn.disabled}, text="${btn.textContent.trim()}"`;
    });
    log(`startCountdownBtn state: ${btnState}`);

    await humanDelay(500, 1000);

    // Check for #goog_rewarded immediately after click (recording showed it appears)
    if (safeURL().includes('#goog_rewarded')) {
      log('#goog_rewarded appeared after startCountdownBtn click, handling ad...');
      await handleGoogRewarded();
      await safeEval(() => {
        if (window.location.hash) history.replaceState(null, '', window.location.pathname + window.location.search);
      });
      await humanDelay(500, 1000);
    }

    // Directly wait for #cross-snp2 to become visible (up to 60s)
    // The timer counts from 15 at 1.5s intervals = 22.5s + ad handling time
    // #cross-snp2 appears when timer reaches -1 (NOT 0)
    // Skip the fragile getCountdown → waitForCountdown chain
    log('waiting for #cross-snp2 to appear...');
    let clicked = false;
    for (let w = 0; w < 60; w++) {
      // Also check for #goog_rewarded during wait (ad may appear mid-countdown)
      if (w % 5 === 0) {
        if (safeURL().includes('#goog_rewarded')) {
          log('#goog_rewarded during LINK1S wait, handling...');
          await handleGoogRewarded();
          await safeEval(() => {
            if (window.location.hash) history.replaceState(null, '', window.location.pathname + window.location.search);
          });
          await humanDelay(500, 1000);
        }
        if (await checkAdHijack()) return true;
        await closeAdOverlay();
      }

      const visible = await safeEval(() => {
        const el = document.getElementById('cross-snp2');
        if (!el) return false;
        const style = getComputedStyle(el);
        return style.display !== 'none' && style.visibility !== 'hidden'
          && el.getClientRects().length > 0;
      });
      if (visible) {
        // DOM confirmed: #cross-snp2 is inside <a> with learn_more.php href
        // Click the <a> directly for reliable navigation
        const navDone = await safeEval(() => {
          const a = document.querySelector('#cross-snp2');
          if (!a) return false;
          // Find the parent <a> tag
          let el = a;
          while (el && el.tagName !== 'A') el = el.parentElement;
          if (el && el.href && el.href.includes('learn_more.php')) {
            window.location.href = el.href;
            return true;
          }
          // Fallback: click the button itself
          a.click();
          return true;
        });
        if (navDone) {
          log('clicked #cross-snp2');
          clicked = true;
          break;
        }
      }

      // Periodic countdown log for debugging
      if (w % 10 === 0) {
        const cd = await getCountdown();
        log(`[LINK1S wait ${w}s] cross-snp2 not visible, countdown=${cd}`);
      }
      await ms(1000);
    }

    if (!clicked) {
      // Fallback: find anchor with learn_more.php href
      const fallback = await safeEval(() => {
        const links = document.querySelectorAll('a');
        for (const a of links) {
          if (a.href && a.href.includes('learn_more.php') && a.offsetParent !== null) {
            a.click();
            return true;
          }
        }
        return false;
      });
      if (fallback) log('clicked learn_more.php fallback link');
    }
    return clicked || false;
  };

  // ── Unknown template: try all known buttons ──
  const handleUnknown = async () => {
    log('template: UNKNOWN — trying all known buttons');
    await humanDelay(3000, 5000);

    const buttons = [
      '#tp-snp2', '#cross-snp2', '#btn6',
      '#btn7 > button', '#btn7',
      '#continueBtn', '#gcont',
      '#gt-link',
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
    let template = await detectTemplate();
    log(`detected template: ${template}`);

    // Retry template detection after delay — AMP pages may need more time to initialize
    if (template === 'unknown') {
      for (let retry = 0; retry < 3; retry++) {
        await humanDelay(3000, 5000);
        await closeAdOverlay();
        template = await detectTemplate();
        if (template !== 'unknown') {
          log(`retry detected template: ${template} (attempt ${retry + 1})`);
          break;
        }
      }
    }

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
      return false;
    }

    return false;
  };

  // ── Get Link handler ──
  // DOM analysis revealed:
  // - #get-link is a placeholder <a> with class="disabled", text="Please wait..."
  // - #gt-link is the REAL destination button with actual href (e.g., apkmirror.com)
  // - After countdown, POST to /links/go → #get-link hides, #gt-link shows
  // - #gt-link href is the real destination URL
  // - wistfulseverely.com is a tracking wrapper that opens first, then redirects
  const doGetLink = async () => {
    try {
      for (const p of context.pages()) {
        if (p !== page) { try { await p.close(); } catch {} }
      }

      const btn = await page.waitForSelector('#get-link', { timeout: 40000 }).catch(() => null);
      if (!btn) return false;

      // Capture href from BOTH #get-link and #gt-link BEFORE clicking
      const linkHrefs = await safeEval(() => {
        const getLink = document.getElementById('get-link');
        const gtLink = document.getElementById('gt-link');
        return {
          getLinkHref: getLink ? getLink.href : '',
          gtLinkHref: gtLink ? gtLink.href : '',
        };
      });
      const linkHref = (linkHrefs.gtLinkHref || linkHrefs.getLinkHref || '').replace(/javascript:void\(0\)/, '');
      if (linkHref && linkHref.startsWith('http')) {
        log(`captured href before click: gt-link=${!!linkHrefs.gtLinkHref}, get-link=${!!linkHrefs.getLinkHref}`);
      }

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
              || popupUrl.includes('wistfulseverely.com') || popupUrl.includes('one-vv');
            if (isRedirect) {
              log(`redirect wrapper detected (${popupUrl.substring(0,50)}), waiting for final URL...`);
              for (let r = 0; r < 45; r++) {
                await ms(1000);
                try {
                  const newUrl = newTab.url();
                  if (newUrl && !newUrl.includes('about:blank')) {
                    popupUrl = newUrl;
                    // Keep waiting if still on tracking domain
                    if (!popupUrl.includes('wistfulseverely.com') && !popupUrl.includes('one-vv')
                      && !popupUrl.includes('linkedin.com/redir') && !popupUrl.includes('google.com/url')) break;
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
          // Don't declare stability on tracking wrapper domains
          const isTracker = mUrl.includes('wistfulseverely.com') || mUrl.includes('one-vv');
          if (stableCount >= 3 && isDestination(mUrl) && !isTracker) {
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

      // Fallback: use href captured before clicking (prefer #gt-link over #get-link)
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
  const navTimeout = process.env.VPLINK_PROXY ? 75000 : 45000;
  let skipMainLoop = false;

  // YouTube referral: navigate to YouTube first so browser naturally sets Referer
  // OLD approach (page.route header injection) broke vplink.in JS redirects.
  // Always use YouTube-first navigation — works with and without proxy.
  const REFERER = process.env.VPLINK_REFERER || '';
  if (REFERER) {
    log(`navigating to YouTube first for referral: ${REFERER.substring(0, 60)}`);
    try {
      await page.goto(REFERER, { waitUntil: 'domcontentloaded', timeout: PROXY ? 20000 : 30000 });
      await humanDelay(2000, 4000);
      log('YouTube loaded, now navigating to vplink.in (browser will set Referer)');
    } catch (e) {
      log(`YouTube navigation failed: ${e.message}, continuing without referral`);
    }
  }

  log(`navigating to vplink.in/${KEY}`);
  await debugShot('01-start');

  const hardGotoTimeout = PROXY ? 60000 : 30000;
  const hardGoto = async (url, opts) => {
    const gotoPromise = page.goto(url, opts);
    const abortPromise = new Promise((_, reject) => {
      setTimeout(() => reject(new Error('hard-timeout')), hardGotoTimeout);
    });
    return Promise.race([gotoPromise, abortPromise]);
  };

  try {
    await hardGoto(`https://${BASE_DOMAIN}/${KEY}`, { waitUntil: 'domcontentloaded', timeout: navTimeout });
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
        await hardGoto(`https://${BASE_DOMAIN}/${KEY}`, { waitUntil: 'domcontentloaded', timeout: navTimeout });
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
      || url.includes('studiiessuniversitiess') || url.includes('universitesstudiiess')
      || url.includes('studiessuniversitiess');
    if (!url.includes('vplink.in') && !isIntermediate) {
      urlVisits[urlKey] = (urlVisits[urlKey] || 0) + 1;
      if (urlVisits[urlKey] >= MAX_URL_VISITS) {
        // If we already tried force-navigating away from this article and came back, give up
        if (lastStuckArticle === urlKey) {
          log(`STUCK LOOP: same article visited ${urlVisits[urlKey]} times after force-nav, exiting`);
          if (PROXY) await reportProxyFailure('article-stuck-loop');
          proxyBlocked = true;
          break;
        }
        lastStuckArticle = urlKey;
        log(`STUCK: same article visited ${urlVisits[urlKey]} times, force-navigating`);
        lastBase = '';
        await page.goto(`https://${BASE_DOMAIN}/${KEY}`, { waitUntil: 'domcontentloaded', timeout: navTimeout }).catch(() => {});
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
        // Clear hash so main loop doesn't keep treating as hash-only change
        await safeEval(() => {
          if (window.location.hash) history.replaceState(null, '', window.location.pathname + window.location.search);
        });
        await humanDelay(500, 1000);
        // Wait for any running countdown to finish before clicking
        const remaining = await getCountdown();
        if (remaining > 0) {
          log(`timer still at ${remaining}, waiting for countdown...`);
          await waitForCountdown('tp', 30);
          await humanDelay(500, 1000);
        }
        // Try all known template buttons
        const clicked = await humanClick('#tp-snp2') || await humanClick('#cross-snp2')
          || await humanClick('#btn7 > button') || await humanClick('#btn7')
          || await humanClick('#gt-link');
        if (clicked) log('clicked button after #goog_rewarded ad');
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
        await page.goto(`https://${BASE_DOMAIN}/${KEY}`, { waitUntil: 'domcontentloaded', timeout: navTimeout }).catch(() => {});
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
        const gtLink = document.getElementById('gt-link');
        if (!el && !gtLink) return 'missing';
        // #gt-link is the real destination button (appears after POST)
        if (gtLink && getComputedStyle(gtLink).display !== 'none') return 'ready';
        if (el && el.classList.contains('disabled')) return 'disabled';
        if (el && el.offsetParent === null) return 'hidden';
        return 'ready';
      });
      log(`get-link state: ${btnState}`);

      if (btnState === 'ready') {
        if (await doGetLink()) break;
        log('get-link failed, reloading vplink.in');
        for (const p of context.pages()) { if (p !== page) { try { await p.close(); } catch {} } }
        await page.goto(`https://${BASE_DOMAIN}/${KEY}`, { waitUntil: 'domcontentloaded', timeout: navTimeout }).catch(() => {});
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
      await page.goto(`https://${BASE_DOMAIN}/${KEY}`, { waitUntil: 'domcontentloaded', timeout: navTimeout }).catch(() => {});
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
        await page.goto(`https://${BASE_DOMAIN}/${KEY}`, { waitUntil: 'domcontentloaded', timeout: navTimeout }).catch(() => {});
        await humanDelay(3000, 5000);
        continue;
      }
      const rewardedOk = await handleGoogRewarded();
      if (rewardedOk) {
        // Clear hash left by ad
        await safeEval(() => {
          if (window.location.hash) history.replaceState(null, '', window.location.pathname + window.location.search);
        });
        await humanDelay(500, 1000);
        // Wait for any countdown to finish before clicking buttons
        const remaining = await getCountdown();
        if (remaining > 0) {
          log(`timer at ${remaining} after rewarded ad, waiting...`);
          await waitForCountdown(null, remaining + 10);
          await humanDelay(500, 1000);
        }
        const clicked = await humanClick('#tp-snp2') || await humanClick('#cross-snp2')
          || await humanClick('#btn7 > button') || await humanClick('#btn7')
          || await humanClick('#gt-link');
        if (clicked) log('clicked button after #goog_rewarded');
      }
      lastBase = urlBase(safeURL());
      continue;
    }

    // ── Intermediate redirect pages ──
    if (url.includes('learn_more.php') || url.includes('studieseducates')
      || url.includes('studiiessuniversitiess') || url.includes('universitesstudiiess')
      || url.includes('studiessuniversitiess')) {
      log('intermediate redirect page, waiting for auto-redirect...');
      const intermediateBase = urlBase(url);
      let redirected = false;
      const intermediateWait = PROXY ? 30 : 15;
      for (let w = 0; w < intermediateWait; w++) {
        await ms(1000);
        const cur = safeURL();
        const curBase = urlBase(cur);
        if (curBase !== intermediateBase && !cur.includes('learn_more.php') && !cur.includes('studieseducates')
            && !cur.includes('studiiessuniversitiess') && !cur.includes('universitesstudiiess')
            && !cur.includes('studiessuniversitiess')) {
          log(`redirected to: ${cur.substring(0, 100)}`);
          await humanDelay(500, 1500);
          redirected = true;
          break;
        }
        // After 10s, try to extract redirect URL from page JS/DOM
        if (w === 10 && !redirected) {
          const extractedUrl = await safeEval(() => {
            // Check meta refresh
            const meta = document.querySelector('meta[http-equiv="refresh"]');
            if (meta) {
              const m = meta.content.match(/url=(.+)/i);
              if (m) return m[1].trim();
            }
            // Check for window.location in inline scripts
            const scripts = document.querySelectorAll('script:not([src])');
            for (const s of scripts) {
              const t = s.textContent || '';
              const locMatch = t.match(/window\.location(?:\.href)?\s*=\s*['"]([^'"]+)['"]/);
              if (locMatch) return locMatch[1];
              const replaceMatch = t.match(/window\.location\.replace\s*\(\s*['"]([^'"]+)['"]\s*\)/);
              if (replaceMatch) return replaceMatch[1];
            }
            // Check for hidden links with redirect URLs
            const links = document.querySelectorAll('a[href]');
            for (const a of links) {
              if (a.href && !a.href.includes('javascript:') && a.href !== window.location.href) {
                return a.href;
              }
            }
            return null;
          });
          if (extractedUrl && extractedUrl !== url && !extractedUrl.includes('studiiessuniversitiess')) {
            log(`extracted redirect URL: ${extractedUrl.substring(0, 100)}`);
            await page.goto(extractedUrl, { waitUntil: 'domcontentloaded', timeout: navTimeout }).catch(() => {});
            await humanDelay(1000, 2000);
            redirected = true;
            break;
          }
        }
        if (w === 15 && PROXY) {
          log('intermediate still stuck after 15s, reloading...');
          await page.reload({ waitUntil: 'domcontentloaded', timeout: 20000 }).catch(() => {});
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
      await page.goto(`https://${BASE_DOMAIN}/${KEY}`, { waitUntil: 'domcontentloaded', timeout: navTimeout }).catch(() => {});
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
        await page.goto(`https://${BASE_DOMAIN}/${KEY}`, { waitUntil: 'domcontentloaded', timeout: navTimeout }).catch(() => {});
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
