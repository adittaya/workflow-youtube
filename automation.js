let chromium;
try { ({ chromium } = require('playwright')); }
catch { ({ chromium } = require('playwright-core')); }
const fs = require('fs');
const path = require('path');
let markDead, addProxyBlacklist;
try { ({ markDead } = require('./proxy-rotator')); } catch { markDead = async () => false; }
try { ({ addProxyBlacklist } = require('./config')); } catch { addProxyBlacklist = () => {}; }
const { generateProfile } = require('./profile-generator');

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
  // ── Generate human profile (UA, viewport, locale, fingerprints) ──
  const profile = generateProfile(false, true);
  log(`profile: ${profile.viewport.width}x${profile.viewport.height} ${profile.locale} ${profile.timezone} hw=${profile.hardwareConcurrency} mem=${profile.deviceMemory}`);

  const stealthArgs = ['--no-sandbox', '--disable-gpu', '--disable-blink-features=AutomationControlled',
    '--disable-dev-shm-usage', '--disable-accelerated-2d-canvas', '--disable-setuid-sandbox',
    '--disable-automation', '--use-gl=swiftshader',
    '--disable-features=IsolateOrigins,site-per-process'];
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

  // ── Persistent context for cookie/localStorage retention between views ──
  const storageDir = path.join(process.env.HOME || '/tmp', '.vplink3.0', 'storage');
  const storageFile = path.join(storageDir, 'state.json');
  if (!fs.existsSync(storageDir)) fs.mkdirSync(storageDir, { recursive: true });

  const ctxOpts = {
    viewport: process.env.VPLINK_VIEWPORT_WIDTH ? {
      width: parseInt(process.env.VPLINK_VIEWPORT_WIDTH) || profile.viewport.width,
      height: parseInt(process.env.VPLINK_VIEWPORT_HEIGHT) || profile.viewport.height,
    } : profile.viewport,
    locale: profile.locale,
    timezoneId: profile.timezone,
    userAgent: process.env.VPLINK_USER_AGENT || profile.userAgent,
    extraHTTPHeaders: { 'Accept-Language': profile.languages.join(',') + ';q=0.9' },
  };

  // Load saved storage state (cookies, localStorage) if available
  if (fs.existsSync(storageFile)) {
    try { ctxOpts.storageState = JSON.parse(fs.readFileSync(storageFile, 'utf8')); } catch {}
  }

  context = await browser.newContext(ctxOpts);
  page = await context.newPage();
  page.setDefaultNavigationTimeout(90000);

  // Save storage state periodically (every 30s) for cookie persistence
  const saveStorage = async () => {
    try {
      const state = await context.storageState();
      fs.writeFileSync(storageFile, JSON.stringify(state), 'utf8');
    } catch {}
  };
  setInterval(saveStorage, 30000);

  let debugPage = page;
  const debugShot = async (label) => {
    if (!DEBUG) return;
    const dir = path.join(__dirname, 'screenshots');
    try { fs.mkdirSync(dir, { recursive: true }); } catch {}
    try { await debugPage.screenshot({ path: path.join(dir, `${label}.png`), fullPage: false }); } catch {}
  };

  // ── Tier 1: Enhanced Stealth Fingerprint Patching ──
  const p = profile;
  await page.addInitScript((p) => {
    // 1. webdriver
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

    // 2. plugins (match UA platform)
    Object.defineProperty(navigator, 'plugins', {
      get: () => {
        const plugins = [
          { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
          { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
          { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' },
        ];
        plugins.length = 3;
        plugins.refresh = () => {};
        return plugins;
      }
    });

    // 3. languages (from profile)
    Object.defineProperty(navigator, 'languages', { get: () => p.languages });

    // 4. hardwareConcurrency
    Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => p.hardwareConcurrency });

    // 5. deviceMemory
    Object.defineProperty(navigator, 'deviceMemory', { get: () => p.deviceMemory });

    // 6. platform
    Object.defineProperty(navigator, 'platform', { get: () => p.platform });

    // 7. chrome runtime
    window.chrome = { runtime: {}, loadTimes: () => {}, csi: () => {} };

    // 8. permissions query
    const origPermQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (p) => p.name === 'notifications'
      ? Promise.resolve({ state: 'denied' })
      : origPermQuery(p);

    // 9. WebGL fingerprint spoofing
    const getParameterOrig = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(param) {
      // UNMASKED_VENDOR_WEBGL
      if (param === 37445) return p.webgl.vendor;
      // UNMASKED_RENDERER_WEBGL
      if (param === 37446) return p.webgl.renderer;
      return getParameterOrig.call(this, param);
    };
    if (typeof WebGL2RenderingContext !== 'undefined') {
      const getParameter2Orig = WebGL2RenderingContext.prototype.getParameter;
      WebGL2RenderingContext.prototype.getParameter = function(param) {
        if (param === 37445) return p.webgl.vendor;
        if (param === 37446) return p.webgl.renderer;
        return getParameter2Orig.call(this, param);
      };
    }

    // 10. Canvas fingerprint noise
    const toDataURL = HTMLCanvasElement.prototype.toDataURL;
    HTMLCanvasElement.prototype.toDataURL = function(type) {
      const ctx = this.getContext('2d');
      if (ctx) {
        const imageData = ctx.getImageData(0, 0, Math.min(this.width, 16), Math.min(this.height, 16));
        for (let i = 0; i < imageData.data.length; i += 4) {
          imageData.data[i] = Math.max(0, Math.min(255, imageData.data[i] + Math.round(p.canvasNoiseSeed * 100)));
        }
        ctx.putImageData(imageData, 0, 0);
      }
      return toDataURL.apply(this, arguments);
    };
    const getImageData = CanvasRenderingContext2D.prototype.getImageData;
    CanvasRenderingContext2D.prototype.getImageData = function() {
      const imageData = getImageData.apply(this, arguments);
      for (let i = 0; i < imageData.data.length; i += 4) {
        imageData.data[i] = Math.max(0, Math.min(255, imageData.data[i] + Math.round(p.canvasNoiseSeed * 50)));
      }
      return imageData;
    };

    // 11. AudioContext fingerprint noise
    const origGetFloat = AnalyserNode.prototype.getFloatFrequencyData;
    AnalyserNode.prototype.getFloatFrequencyData = function(arr) {
      origGetFloat.call(this, arr);
      for (let i = 0; i < arr.length; i++) arr[i] += p.audioOffset;
    };
    const origGetByte = AnalyserNode.prototype.getByteFrequencyData;
    AnalyserNode.prototype.getByteFrequencyData = function(arr) {
      origGetByte.call(this, arr);
      for (let i = 0; i < arr.length; i++) arr[i] = Math.max(0, Math.min(255, arr[i] + Math.round(p.audioOffset * 1000)));
    };

    // 12. Screen properties (match viewport + realistic offsets)
    Object.defineProperty(screen, 'width', { get: () => p.screen.width });
    Object.defineProperty(screen, 'height', { get: () => p.screen.height });
    Object.defineProperty(screen, 'availWidth', { get: () => p.screen.availWidth });
    Object.defineProperty(screen, 'availHeight', { get: () => p.screen.availHeight });
    Object.defineProperty(screen, 'colorDepth', { get: () => p.screen.colorDepth });
    Object.defineProperty(screen, 'pixelDepth', { get: () => p.screen.colorDepth });

    // 13. Outer dimensions (browser chrome)
    if (window.outerWidth === 0) {
      Object.defineProperty(window, 'outerWidth', { get: () => p.screen.availWidth });
      Object.defineProperty(window, 'outerHeight', { get: () => p.screen.availHeight });
    }

    // 14. Connection API
    if (navigator.connection) {
      Object.defineProperty(navigator.connection, 'rtt', { get: () => Math.round(50 + Math.random() * 100) });
    }

    // 15. Touch support detection
    Object.defineProperty(navigator, 'maxTouchPoints', {
      get: () => p.platform.includes('Mac') ? 0 : Math.round(Math.random())
    });

    // 16. Notification permission (already handled above)

    // 17. Battery API (return fake)
    if (navigator.getBattery) {
      navigator.getBattery = () => Promise.resolve({
        charging: true, chargingTime: 0, dischargingTime: Infinity,
        level: 0.5 + Math.random() * 0.5,
        addEventListener: () => {}, removeEventListener: () => {},
      });
    }
  }, p);

  page.on('framenavigated', frame => {
    if (frame === page.mainFrame()) log(`nav: ${frame.url().substring(0, 120)}`);
  });

  // ── Tier 1+3: Enhanced Human-Like Behavior ──
  const humanDelay = (min, max) => ms(rand(min, max));

  // Bezier curve mouse movement (realistic arc, not linear)
  const bezierMove = async (fromX, fromY, toX, toY) => {
    const steps = rand(15, 35);
    const cp1x = fromX + (toX - fromX) * 0.3 + (Math.random() - 0.5) * 80;
    const cp1y = fromY + (toY - fromY) * 0.3 + (Math.random() - 0.5) * 80;
    const cp2x = fromX + (toX - fromX) * 0.7 + (Math.random() - 0.5) * 60;
    const cp2y = fromY + (toY - fromY) * 0.7 + (Math.random() - 0.5) * 60;
    for (let i = 0; i <= steps; i++) {
      const t = i / steps;
      const t2 = t * t, t3 = t2 * t;
      const mt = 1 - t, mt2 = mt * mt, mt3 = mt2 * mt;
      const x = mt3 * fromX + 3 * mt2 * t * cp1x + 3 * mt * t2 * cp2x + t3 * toX;
      const y = mt3 * fromY + 3 * mt2 * t * cp1y + 3 * mt * t2 * cp2y + t3 * toY;
      await page.mouse.move(x, y);
      await ms(rand(5, 20));
    }
  };

  const humanScroll = async () => {
    const scrolls = rand(1, 3);
    for (let i = 0; i < scrolls; i++) {
      await safeEval(y => window.scrollBy({ top: y, behavior: 'smooth' }), rand(100, 400));
      await humanDelay(300, 800);
    }
  };

  // ── Deep reading simulation: scroll + mouse wander for 35-65s ──
  // CPM sites require 35s+ viewability for a view to count.
  // Uses Playwright direct API (page.mouse.wheel) instead of safeEval for speed.
  const humanRead = async (durationSec) => {
    const dur = Math.min(durationSec || 45, 70);
    const startTime = Date.now();
    const startUrl = safeURL();
    let maxScroll = 0;
    try {
      maxScroll = await page.evaluate(() => document.documentElement.scrollHeight - window.innerHeight).catch(() => 0);
    } catch {}
    let currentY = 0;
    log(`human read: ${dur}s, page height=${maxScroll}px`);

    try {
      // 12-20 scroll iterations (each ~2-3.5s including pause)
      const iterations = rand(12, 20);
      for (let i = 0; i < iterations; i++) {
        if (Date.now() - startTime >= dur * 1000) break;
        if (safeURL() !== startUrl) { log('human read: page navigated, stopping'); break; }

        // Scroll via Playwright direct API (no safeEval overhead)
        const scrollAmt = Math.random() < 0.2 ? -rand(50, 200) : rand(200, 600);
        currentY = Math.max(0, Math.min(maxScroll || 5000, currentY + scrollAmt));
        try { await page.mouse.wheel(0, scrollAmt); } catch { break; }

        // Mouse wander (direct API, no safeEval)
        const vpW = p.viewport.width, vpH = p.viewport.height;
        const mx = rand(100, vpW - 100), my = rand(100, vpH - 100);
        try { await page.mouse.move(mx, my, { steps: rand(5, 15) }); } catch { break; }

        // Mouseover events via quick evaluate (batch, no DOM query)
        if (Math.random() < 0.2) {
          try {
            await page.evaluate(() => {
              const el = document.elementFromPoint(
                Math.random() * window.innerWidth,
                Math.random() * window.innerHeight
              );
              if (el) el.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
            });
          } catch {}
        }

        // Reading pause (3-7s simulating real reading)
        const pause = rand(3000, 7000);
        await ms(pause);

        // Occasional scroll-back (15%)
        if (Math.random() < 0.15) {
          try { await page.mouse.wheel(0, -rand(100, 300)); } catch {}
          await ms(rand(1000, 2500));
        }

        // Occasional mouse jitter (idle behavior)
        if (Math.random() < 0.15) {
          try { await page.mouse.move(mx + rand(-30, 30), my + rand(-20, 20), { steps: rand(3, 8) }); } catch {}
          await ms(rand(200, 600));
        }
      }
    } catch (e) {
      log(`human read error: ${e.message?.substring(0, 60)}`);
    }
    log(`human read done (${Math.round((Date.now() - startTime) / 1000)}s)`);
  };

  const humanMouseMove = async (sel) => {
    try {
      const box = await page.locator(sel).first().boundingBox();
      if (box) {
        const x = box.x + box.width * (0.3 + Math.random() * 0.4);
        const y = box.y + box.height * (0.3 + Math.random() * 0.4);
        // Bezier curve instead of linear steps
        const fromX = rand(100, p.viewport.width - 100);
        const fromY = rand(100, p.viewport.height - 100);
        await bezierMove(fromX, fromY, x, y);
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
  // TP timer: count starts at 24 (no adcadg cookie) or 15 (with cookie), interval 1900ms.
  // When count<=0: shows #tp-snp2, hides #tp-wait1. tp-time innerHTML never shows 0.
  // CRITICAL: Do NOT click overlays during TP countdown — clicking #gcont SVG causes ad
  // iframe to gain focus → page's monitor detects IFRAME active element → schedules
  // clearInterval(counter) after 15s → KILLS the timer → tp-snp2 never shows.
  // LINK1S timer: takes ~22.5s from 15→-1, each "second" = ~1.5s real
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

      // Stuck timer detection: if countdown stays same value for 2.5s (5 polls at 500ms), timer JS is broken
      if (remaining > 0 && remaining === lastVal) {
        stuckCount++;
        if (stuckCount >= 5) {
          log(`countdown stuck at ${remaining}s for 2.5s — timer JS broken, forcing`);
          return 'stuck';
        }
      } else {
        stuckCount = 0;
        lastVal = remaining;
      }

      // Log countdown value periodically for debugging
      if (i % 10 === 0 && remaining > 0) log(`countdown ${template}: ${remaining}s remaining`);

      // TP: NEVER touch overlays during countdown — the page's iframe-focus monitor
      // kills the timer if any iframe gains focus. Just wait for the timer to finish.
      // Non-TP templates: close overlays periodically (they don't have this monitor issue).
      if (template !== 'tp' && i % 4 === 0) {
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

  // ── Navigate to learn_more.php (DO NOT click #tp-snp2 — its onclick blocks navigation) ──
  // DOM revealed: #tp-snp2 is at y=22000+ (off-screen), parent <a> has onclick that calls
  // e.preventDefault() + window.open("","_blank"). So clicking NEVER navigates.
  const navigateLearnMore = async () => {
    const navResult = await safeEval(() => {
      const snp2 = document.getElementById('tp-snp2');
      const a = snp2?.closest('a');
      if (a && a.href && a.href.includes('learn_more.php')) {
        window.location.href = a.href;
        return a.href;
      }
      const links = document.querySelectorAll('a');
      for (const link of links) {
        if (link.href && link.href.includes('learn_more.php')) {
          window.location.href = link.href;
          return link.href;
        }
      }
      return false;
    });
    if (navResult) {
      log(`navigated to learn_more.php: ${navResult}`);
      return true;
    }
    return false;
  };

  // ── Template A (TP): tp-time countdown → tp-snp2 → learn_more.php ──
  // DOM analysis confirmed: timer is a simple setInterval that counts down.
  // CRITICAL: Do NOT click #gcont overlay SVG — it causes iframe focus → kills timer.
  // Just close #block-cont-1 (safe) and wait for timer to finish naturally.
  const handleTP = async () => {
    log('template: TP (tp-time countdown)');

    // Close ONLY #block-cont-1 ad overlay (safe — no iframe focus trigger).
    // Do NOT close #gcont — clicking its SVG triggers iframe-focus monitor that kills timer.
    await safeEval(() => {
      const container = document.getElementById('block-cont-1');
      if (container && getComputedStyle(container).display !== 'none') {
        const closeDiv = container.querySelector('div');
        if (closeDiv && closeDiv.textContent.trim() === 'X') {
          closeDiv.click();
          return 'block-cont-1';
        }
      }
      return false;
    });

    // Wait for countdown (up to 50s — timer takes 24*1.9s=45.6s without cookie, 15*1.9s=28.5s with)
    // waitForCountdown will NOT touch overlays during TP countdown (safe mode).
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
      const navOk = await navigateLearnMore();
      if (navOk) log('navigated via learn_more.php after rewarded ad');
      return navOk;
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

    // After countdown: dismiss any blocking overlays via JS (NOT clicks — clicks trigger iframe monitor)
    // and force-show tp-snp2 if the timer didn't show it already.
    await safeEval(() => {
      // Dismiss #gcont overlay safely (set display:none, don't click)
      const gcont = document.getElementById('gcont');
      if (gcont) gcont.style.display = 'none';
      // Dismiss #continueBtn overlay safely
      const btn = document.getElementById('continueBtn');
      if (btn) {
        const overlay = btn.closest('div[style*="position: fixed"]') || btn.parentElement;
        if (overlay) overlay.style.display = 'none';
      }
      // Dismiss #block-cont-1 overlay safely
      const block = document.getElementById('block-cont-1');
      if (block) block.style.display = 'none';
      // Force-show tp-snp2 if timer didn't already
      const snp2 = document.getElementById('tp-snp2');
      const wait1 = document.getElementById('tp-wait1');
      if (snp2 && getComputedStyle(snp2).display === 'none') {
        if (wait1) wait1.style.display = 'none';
        snp2.style.display = 'block';
      }
    });

    // Check for #goog_rewarded after overlay dismissal
    if (safeURL().includes('#goog_rewarded')) {
      log('on #goog_rewarded after countdown, waiting for ad...');
      await handleGoogRewarded();
      await safeEval(() => {
        if (window.location.hash) history.replaceState(null, '', window.location.pathname + window.location.search);
        const wait1 = document.getElementById('tp-wait1');
        const snp2 = document.getElementById('tp-snp2');
        if (wait1) wait1.style.display = 'none';
        if (snp2) snp2.style.display = 'block';
      });
      await humanDelay(500, 1000);
      const navOk2 = await navigateLearnMore();
      return navOk2;
    }

    await humanDelay(1000, 2000);

    return await navigateLearnMore();
    return false;
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
  // ── Template C (LINK1S): startCountdownBtn → cross-snp2 → learn_more.php ──
  // DOM confirmed: timer counts from 15 at 1.5s intervals = 22.5s total.
  // #cross-snp2 appears when count=-1. Click goes to learn_more.php.
  // Same iframe-focus monitor issue as TP — do NOT click overlays during countdown.
  const handleLINK1S = async () => {
    log('template: LINK1S (startCountdownBtn)');

    // Close ONLY #block-cont-1 (safe). Do NOT click #gcont SVG.
    await safeEval(() => {
      const container = document.getElementById('block-cont-1');
      if (container && getComputedStyle(container).display !== 'none') {
        const closeDiv = container.querySelector('div');
        if (closeDiv && closeDiv.textContent.trim() === 'X') closeDiv.click();
      }
    });

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
        // Do NOT call closeAdOverlay() here — clicking #gcont SVG triggers iframe monitor
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

    // Force-show cross-snp2 if timer reached -1 but button didn't appear
    if (!clicked) {
      log('cross-snp2 not visible, forcing button visibility...');
      await safeEval(() => {
        const gcont = document.getElementById('gcont');
        if (gcont) gcont.style.display = 'none';
        const block = document.getElementById('block-cont-1');
        if (block) block.style.display = 'none';
        const snp2 = document.getElementById('cross-snp2');
        if (snp2) snp2.style.display = 'block';
        const a = snp2?.closest('a');
        if (a) a.style.display = 'block';
      });
      await humanDelay(1000, 2000);
      const navDone = await safeEval(() => {
        const el = document.getElementById('cross-snp2');
        if (!el) return false;
        const a = el.closest('a');
        if (a && a.href && a.href.includes('learn_more.php')) {
          window.location.href = a.href;
          return true;
        }
        el.click();
        return true;
      });
      if (navDone) { log('clicked #cross-snp2 after force-show'); clicked = true; }
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

    // Fallback: try clicking any learn_more.php link on the page
    const learnMore = await safeEval(() => {
      const links = document.querySelectorAll('a[href*="learn_more.php"]');
      for (const a of links) {
        if (a.offsetParent !== null) {
          window.location.href = a.href;
          return a.href;
        }
      }
      return null;
    });
    if (learnMore) {
      log(`clicked learn_more.php link: ${learnMore.substring(0, 80)}`);
      await humanDelay(1000, 2000);
      return true;
    }

    return false;
  };

  // ── Article page handler (domain-agnostic) ──
  const handleArticle = async () => {
    log('article page');
    await debugShot('article-start');
    const startUrl = safeURL();

    // Detect homepage (no article slug) — funnel chain exhausted, go back to vplink.in
    const urlPath = new URL(startUrl).pathname;
    if (urlPath === '/' || urlPath === '') {
      log('landed on homepage (no article slug) — funnel exhausted, navigating to vplink.in');
      return false;
    }

    // Initial settle — wait for page to fully load before reading
    await humanDelay(2000, 4000);
    try { await page.waitForLoadState('domcontentloaded', { timeout: 10000 }); } catch {}
    await humanScroll();
    await closeAdOverlay();

    // Detect template FIRST — if timer is already at 1/-1, skip reading and go straight to button
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

    // If timer is already at 1 or -1 (finished during page load), skip reading
    const countdown = await getCountdown();
    const timerDone = countdown <= 1 && countdown !== -2;
    if (timerDone) {
      log(`timer already at ${countdown} (finished), skipping read`);
    } else {
      // Read while timer counts down — 35-65s for real viewability signals
      const readSecs = countdown > 0 ? Math.max(countdown + 5, 35) : rand(35, 55);
      await humanRead(Math.min(readSecs, 65));
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
      if (newTab) log(`new tab opened: ${newTab.url()}`);

      // Step 1: Check if initial popup URL has base64-encoded destination
      // vplink.in tracking pages encode the real URL as base64 in params like eduuniversty=
      if (newTab) {
        try {
          const tabUrl = newTab.url();
          const u = new URL(tabUrl);
          for (const [, val] of u.searchParams) {
            try {
              const decoded = Buffer.from(val, 'base64').toString('utf8');
              if (decoded.startsWith('http')) {
                log(`decoded destination from base64 param: ${decoded}`);
                destinationUrl = decoded;
                await newTab.close().catch(() => {});
                return true;
              }
            } catch {}
          }
        } catch {}
      }

      const clickTime = Date.now();
      let stableUrl = '', stableCount = 0;

      // Poll for destination URL — track full redirect chain
      for (let i = 0; i < 60; i++) {
        await ms(1000);
        let popupUrl = '';

        if (newTab) {
          try {
            await newTab.waitForLoadState('networkidle', { timeout: 3000 }).catch(() => {});
            popupUrl = newTab.url();
          } catch { newTab = null; }
          if (popupUrl && !popupUrl.includes('about:blank') && !popupUrl.includes('chrome-error')) {
            if (i < 15 || i % 5 === 0) log(`[get-link ${i}s] popup: ${popupUrl.substring(0, 100)}`);
            // If URL is a redirect wrapper, wait for it to resolve
            const isRedirect = popupUrl.includes('linkedin.com/redir') || popupUrl.includes('google.com/url')
              || popupUrl.includes('facebook.com/l.php') || popupUrl.includes('t.co/')
              || popupUrl.includes('wistfulseverely.com') || popupUrl.includes('one-vv')
              || popupUrl.includes('amazingbaba.com') || popupUrl.includes('lnkd.in');
            if (isRedirect) {
              log(`redirect/tracking URL detected (${popupUrl.substring(0,60)}), waiting for final...`);
              let redirectDone = false;
              for (let r = 0; r < 60; r++) {
                await ms(1000);
                try {
                  const newUrl = newTab.url();
                  if (newUrl && !newUrl.includes('about:blank')) {
                    if (newUrl !== popupUrl) log(`[redirect ${r}s] ${newUrl.substring(0, 100)}`);
                    popupUrl = newUrl;
                    // Keep waiting if still on tracking/redirect domain
                    if (!popupUrl.includes('wistfulseverely.com') && !popupUrl.includes('one-vv')
                      && !popupUrl.includes('linkedin.com/redir') && !popupUrl.includes('google.com/url')
                      && !popupUrl.includes('facebook.com/l.php') && !popupUrl.includes('t.co/')
                      && !popupUrl.includes('amazingbaba.com') && !popupUrl.includes('lnkd.in')) {
                      redirectDone = true;
                      break;
                    }
                  }
                } catch { break; }
              }
              if (redirectDone) {
                destinationUrl = popupUrl;
                log(`destination (popup): ${popupUrl.substring(0,100)}`);
                const elapsed = Date.now() - clickTime;
                const wait = Math.max(0, 25000 - elapsed);
                if (wait > 500) { log(`tracking wait: ${wait}ms`); await ms(wait); }
                return true;
              }
              // Redirect loop exhausted — give up on popup
              break;
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
        // Try all known template buttons (use navigateLearnMore for TP instead of click)
        const clicked = await navigateLearnMore() || await humanClick('#cross-snp2')
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
        const clicked = await navigateLearnMore() || await humanClick('#cross-snp2')
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
      const intermediateWait = PROXY ? 20 : 15;
      let sameUrlReloads = 0; // detect self-reload loops

      // Capture navigation events to catch redirects that happen between poll intervals
      let capturedNavUrl = null;
      const navListener = (frame) => {
        if (frame === page.mainFrame()) {
          const navUrl = frame.url();
          if (navUrl && !navUrl.includes('studiiessuniversitiess') && !navUrl.includes('universitesstudiiess')
              && !navUrl.includes('studiessuniversitiess') && !navUrl.includes('studieseducates')
              && !navUrl.includes('learn_more.php') && !navUrl.includes('vplink.in')
              && !navUrl.startsWith('about:') && !navUrl.startsWith('chrome-')) {
            capturedNavUrl = navUrl;
          }
        }
      };
      page.on('framenavigated', navListener);

      for (let w = 0; w < intermediateWait; w++) {
        await ms(1000);

        // Check captured navigation first
        if (capturedNavUrl) {
          log(`captured nav redirect: ${capturedNavUrl.substring(0, 100)}`);
          await page.goto(capturedNavUrl, { waitUntil: 'domcontentloaded', timeout: navTimeout }).catch(() => {});
          await humanDelay(500, 1500);
          redirected = true;
          break;
        }

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

        // Detect self-reload: page reloads to same intermediate URL every ~5s
        // If still on same URL after 5s intervals, count as reload
        if (w > 0 && w % 5 === 0) {
          sameUrlReloads++;
          if (sameUrlReloads >= 2) {
            log(`intermediate self-reload detected (${sameUrlReloads}x), proxy can't execute JS redirect`);
            break;
          }
        }

        // After 8s, try to extract redirect URL from page source
        if (w === 8 && !redirected) {
          const extractedUrl = await safeEval(() => {
            const html = document.documentElement.outerHTML || '';
            // Pattern 1: window.location.href = '/path'
            let m = html.match(/window\.location(?:\.href)?\s*=\s*['"](\/[^'"]+)['"]/);
            if (m && !m[1].includes('studiiessuniversitiess') && !m[1].includes('learn_more')) return m[1];
            // Pattern 2: window.location.replace('/path')
            m = html.match(/window\.location\.replace\s*\(\s*['"](\/[^'"]+)['"]\s*\)/);
            if (m && !m[1].includes('studiiessuniversitiess') && !m[1].includes('learn_more')) return m[1];
            // Pattern 3: meta refresh
            const meta = document.querySelector('meta[http-equiv="refresh"]');
            if (meta) {
              const urlMatch = meta.content.match(/url=(.+)/i);
              if (urlMatch) return urlMatch[1].trim();
            }
            // Pattern 4: any non-study article link
            const links = document.querySelectorAll('a[href]');
            for (const a of links) {
              const href = a.href;
              if (href && !href.includes('javascript:') && !href.includes('studiiessuniversitiess')
                  && !href.includes('universitesstudiiess') && !href.includes('learn_more')
                  && !href.includes('vplink.in') && !href.includes(window.location.host + '/studyscholorships/studiiessuniversitiess')
                  && !href.includes(window.location.host + '/universitiesstudy/universitesstudiiess')
                  && href.startsWith('http')) {
                return href;
              }
            }
            return null;
          });
          if (extractedUrl) {
            log(`extracted redirect URL: ${extractedUrl.substring(0, 100)}`);
            const fullUrl = extractedUrl.startsWith('http') ? extractedUrl : `https://${new URL(url).hostname}${extractedUrl}`;
            await page.goto(fullUrl, { waitUntil: 'domcontentloaded', timeout: navTimeout }).catch(() => {});
            await humanDelay(1000, 2000);
            redirected = true;
            break;
          }
        }

        // After 12s, try to evaluate pending location changes
        if (w === 12 && !redirected) {
          const forcedUrl = await safeEval(() => {
            // Check if there's a pending setTimeout for redirect
            const scripts = document.querySelectorAll('script:not([src])');
            for (const s of scripts) {
              const t = s.textContent || '';
              const timerMatch = t.match(/setTimeout\s*\(\s*(?:function\s*\(\)\s*\{?\s*)?window\.location(?:\.href)?\s*=\s*['"]([^'"]+)['"]/);
              if (timerMatch && !timerMatch[1].includes('studiiessuniversitiess')) return timerMatch[1];
            }
            return null;
          });
          if (forcedUrl) {
            log(`forced redirect URL: ${forcedUrl.substring(0, 100)}`);
            const fullUrl = forcedUrl.startsWith('http') ? forcedUrl : `https://${new URL(url).hostname}${forcedUrl}`;
            await page.goto(fullUrl, { waitUntil: 'domcontentloaded', timeout: navTimeout }).catch(() => {});
            await humanDelay(1000, 2000);
            redirected = true;
            break;
          }
        }
      }
      page.removeListener('framenavigated', navListener);

      if (!redirected) {
        intermediateStuckCount++;
        log(`intermediate page not redirecting (stuck #${intermediateStuckCount})`);
        if (intermediateStuckCount >= 2) {
          log('intermediate stuck 2x — proxy cannot execute JS redirect, blacklisting');
          if (PROXY) await reportProxyFailure('intermediate-stuck');
          proxyBlocked = true;
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
    if (navigated) {
      // Inter-article delay: CPM platforms reward natural browsing gaps (8-22s)
      const interDelay = rand(8000, 22000);
      log(`inter-article delay: ${Math.round(interDelay / 1000)}s`);
      await ms(interDelay);
      continue;
    }
    // handleArticle returned false — page exhausted or homepage
    log('exhausted, force-navigating to vplink.in');
    lastBase = '';
    await page.goto(`https://${BASE_DOMAIN}/${KEY}`, { waitUntil: 'domcontentloaded', timeout: navTimeout }).catch(() => {});
    await humanDelay(2000, 4000);
    for (let i = 0; i < 15; i++) {
      await ms(1000);
      if (!safeURL().includes('vplink.in')) break;
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
