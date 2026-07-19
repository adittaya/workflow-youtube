const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const KEY = process.argv[2] || 'UbpV2D';
const DIR = path.join(__dirname, 'recordings', 'discovery_' + Date.now());
const SHOTS = path.join(DIR, 'screenshots');
const DOMS = path.join(DIR, 'dom');
const mkd = (d) => { try { fs.mkdirSync(d, { recursive: true }); } catch {} };
mkd(DIR); mkd(SHOTS); mkd(DOMS);

let stepNum = 0;
const log = (msg) => console.error(`[${((Date.now()-t0)/1000).toFixed(1)}s] ${msg}`);
const t0 = Date.now();
const ms = (t) => new Promise(r => setTimeout(r, t));
const safeGoto = async (page, url) => {
  try { await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 }); } catch {}
  await ms(3000);
  try { await page.waitForLoadState('domcontentloaded', { timeout: 5000 }); } catch {}
  await ms(1000);
};

async function dumpDOM(page, label) {
  stepNum++;
  const prefix = String(stepNum).padStart(3, '0');
  log(`DUMP: ${label}`);
  
  // Wait for page to be stable
  try { await page.waitForLoadState('domcontentloaded', { timeout: 8000 }); } catch {}
  await ms(1000);
  
  // Full HTML
  const html = await page.content();
  fs.writeFileSync(path.join(DOMS, `${prefix}_${label.replace(/[^a-z0-9]/gi, '_')}.html`), html);
  
  // Screenshot
  try { await page.screenshot({ path: path.join(SHOTS, `${prefix}_${label.replace(/[^a-z0-9]/gi, '_')}.png`), fullPage: false }); } catch {}
  
  // Key DOM state
  const state = await page.evaluate(() => {
    const result = {};
    
    // All elements with IDs containing timer/wait/btn/link/snp/continue/block/gcont/goog
    const allEls = document.querySelectorAll('[id]');
    const interesting = [];
    for (const el of allEls) {
      const id = el.id;
      if (!id) continue;
      const style = window.getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      interesting.push({
        id,
        tag: el.tagName,
        display: style.display,
        visibility: style.visibility,
        position: style.position,
        opacity: style.opacity,
        disabled: el.disabled || false,
        className: (typeof el.className === 'string') ? el.className.substring(0, 150) : '',
        text: (el.textContent || '').trim().substring(0, 100),
        href: el.href || '',
        onclick: el.getAttribute('onclick') || '',
        outerHTML: el.outerHTML.substring(0, 500),
        visible: rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden',
        rect: { x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height) },
      });
    }
    result.interestingElements = interesting;
    
    // Cookies
    result.cookies = document.cookie;
    
    // localStorage
    try {
      const ls = {};
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        ls[k] = localStorage.getItem(k)?.substring(0, 300);
      }
      result.localStorage = ls;
    } catch {}
    
    // All links
    const links = [];
    document.querySelectorAll('a[href]').forEach(a => {
      const rect = a.getBoundingClientRect();
      links.push({
        href: a.href.substring(0, 200),
        text: (a.textContent || '').trim().substring(0, 80),
        visible: rect.width > 0 && rect.height > 0,
        outerHTML: a.outerHTML.substring(0, 300),
      });
    });
    result.links = links;
    
    // All scripts (inline)
    const scripts = [];
    document.querySelectorAll('script:not([src])').forEach((s, i) => {
      const text = s.textContent.trim();
      if (text.length > 5 && text.length < 5000) {
        scripts.push({ index: i, code: text.substring(0, 2000), length: text.length });
      }
    });
    result.inlineScripts = scripts;
    
    // Timer elements specifically
    const timers = {};
    for (const sel of ['#tp-time', '#tp-wait1', '#tp-wait2', '#tp-snp2',
      '#ce-time', '#ce-wait1', '#btn6', '#btn7',
      '#link1s-wait1', '#link1s-time', '#startCountdownBtn', '#cross-snp2',
      '#get-link', '#gt-link', '#continueBtn', '#gcont', '#block-cont-1',
      '#goog_rewarded', '#google-rewarded-video', '#overcn', '#gads', '#main']) {
      const el = document.querySelector(sel);
      if (el) {
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        timers[sel] = {
          display: style.display,
          visibility: style.visibility,
          position: style.position,
          opacity: style.opacity,
          disabled: el.disabled || false,
          text: (el.textContent || '').trim().substring(0, 100),
          href: el.href || '',
          outerHTML: el.outerHTML.substring(0, 800),
          visible: rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden',
          classList: Array.from(el.classList),
        };
      } else {
        timers[sel] = null;
      }
    }
    result.timerElements = timers;
    
    return result;
  });
  
  fs.writeFileSync(path.join(DOMS, `${prefix}_${label.replace(/[^a-z0-9]/gi, '_')}_state.json`), JSON.stringify(state, null, 2));
  return state;
}

(async () => {
  const browser = await chromium.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage',
      '--disable-blink-features=AutomationControlled', '--use-gl=swiftshader'],
  });
  
  const context = await browser.newContext({
    viewport: { width: 1280, height: 720 },
    userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
    locale: 'en-US',
  });
  
  await context.addInitScript(() => {
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
    window.chrome = { runtime: {} };
  });
  
  const page = await context.newPage();
  page.setDefaultNavigationTimeout(60000);
  
  // Log all navigations
  page.on('framenavigated', frame => {
    if (frame === page.mainFrame()) log(`NAV: ${frame.url().substring(0, 150)}`);
  });
  
  // ── STAGE 1: vplink.in ──
  log('=== STAGE 1: vplink.in ===');
  try { await page.goto(`https://vplink.in/${KEY}`, { waitUntil: 'domcontentloaded', timeout: 30000 }); } catch {}
  await ms(5000);
  // Wait until page is stable (no pending navigations)
  for (let i = 0; i < 10; i++) {
    try { await page.waitForLoadState('domcontentloaded', { timeout: 5000 }); break; } catch { await ms(2000); }
  }
  await dumpDOM(page, '01_vplink_in');
  
  // Wait for redirect
  log('Waiting for auto-redirect from vplink.in...');
  for (let i = 0; i < 30; i++) {
    await ms(1000);
    const url = page.url();
    if (!url.includes('vplink.in')) {
      log(`Redirected to: ${url.substring(0, 120)}`);
      break;
    }
  }
  await ms(3000);
  try { await page.waitForLoadState('domcontentloaded', { timeout: 8000 }); } catch {}
  await dumpDOM(page, '02_after_redirect');
  
  // ── STAGE 2: Intermediate page ──
  const url2 = page.url();
  if (url2.includes('studiiessuniversitiess') || url2.includes('studieseducates') || url2.includes('learn_more.php')) {
    log('=== STAGE 2: Intermediate redirect page ===');
    await dumpDOM(page, '03_intermediate');
    // Wait for redirect to article
    for (let i = 0; i < 15; i++) {
      await ms(1000);
      const cur = page.url();
      if (!cur.includes('studiiessuniversitiess') && !cur.includes('studieseducates') && !cur.includes('learn_more.php')) {
        log(`Redirected to article: ${cur.substring(0, 120)}`);
        break;
      }
    }
    await ms(3000);
    try { await page.waitForLoadState('domcontentloaded', { timeout: 8000 }); } catch {}
  }
  
  // ── STAGE 3: Article page (first article) ──
  log('=== STAGE 3: Article page ===');
  const artUrl = page.url();
  log(`Article URL: ${artUrl.substring(0, 120)}`);
  await ms(3000); // let page settle
  await dumpDOM(page, '04_article_start');
  
  // Wait for timer to progress
  log('Waiting 10s for timer to start...');
  await ms(10000);
  await dumpDOM(page, '05_article_10s');
  
  log('Waiting 15s more...');
  await ms(15000);
  await dumpDOM(page, '06_article_25s');
  
  log('Waiting 15s more...');
  await ms(15000);
  await dumpDOM(page, '07_article_40s');
  
  log('Waiting 15s more...');
  await ms(15000);
  await dumpDOM(page, '08_article_55s');
  
  // Try clicking tp-snp2 if visible
  const tpSnp2 = await page.evaluate(() => {
    const el = document.getElementById('tp-snp2');
    if (!el) return null;
    const style = window.getComputedStyle(el);
    return { display: style.display, visible: el.offsetParent !== null, text: el.textContent.trim() };
  });
  log(`#tp-snp2 state: ${JSON.stringify(tpSnp2)}`);
  
  if (tpSnp2 && tpSnp2.display !== 'none') {
    log('Clicking #tp-snp2...');
    try { await page.click('#tp-snp2', { timeout: 5000 }); } catch { await page.evaluate(() => { const el = document.getElementById('tp-snp2'); if (el) el.click(); }); }
    await ms(3000);
    await dumpDOM(page, '09_after_tp_snp2_click');
  } else {
    log('Force-showing tp-snp2 and clicking...');
    await page.evaluate(() => {
      const w1 = document.getElementById('tp-wait1');
      const w2 = document.getElementById('tp-wait2');
      const s2 = document.getElementById('tp-snp2');
      if (w1) w1.style.display = 'none';
      if (w2) w2.style.display = 'none';
      if (s2) { s2.style.display = 'inline-block'; s2.click(); }
      if (typeof showNextProcess === 'function') try { showNextProcess(); } catch {}
    });
    await ms(3000);
    await dumpDOM(page, '09_after_force_click');
  }
  
  // ── STAGE 4: learn_more.php or next article ──
  log('=== STAGE 4: After button click ===');
  log(`Current URL: ${page.url().substring(0, 120)}`);
  
  // Wait for navigation
  for (let i = 0; i < 15; i++) {
    await ms(1000);
    const cur = page.url();
    if (cur !== artUrl) {
      log(`Navigated to: ${cur.substring(0, 120)}`);
      break;
    }
  }
  await ms(3000);
  try { await page.waitForLoadState('domcontentloaded', { timeout: 8000 }); } catch {}
  await dumpDOM(page, '10_after_navigation');
  
  // If on learn_more.php, wait for redirect
  if (page.url().includes('learn_more.php')) {
    log('=== On learn_more.php, waiting for redirect ===');
    for (let i = 0; i < 15; i++) {
      await ms(1000);
      if (!page.url().includes('learn_more.php')) {
        log(`Redirected to: ${page.url().substring(0, 120)}`);
        break;
      }
    }
    await ms(3000);
    await dumpDOM(page, '11_after_learn_more');
  }
  
  // ── STAGE 5: Second article ──
  const art2Url = page.url();
  if (!art2Url.includes('vplink.in')) {
    log('=== STAGE 5: Second article ===');
    log(`Article 2 URL: ${art2Url.substring(0, 120)}`);
    await ms(3000);
    await dumpDOM(page, '12_article2_start');
    
    // Wait for timer
    log('Waiting 10s for article 2 timer...');
    await ms(10000);
    await dumpDOM(page, '13_article2_10s');
    
    log('Waiting 15s more...');
    await ms(15000);
    await dumpDOM(page, '14_article2_25s');
    
    log('Waiting 15s more...');
    await ms(15000);
    await dumpDOM(page, '15_article2_40s');
    
    log('Waiting 15s more...');
    await ms(15000);
    await dumpDOM(page, '16_article2_55s');
    
    // Check tp-snp2 on article 2
    const tpSnp2_2 = await page.evaluate(() => {
      const el = document.getElementById('tp-snp2');
      if (!el) return null;
      const style = window.getComputedStyle(el);
      return { display: style.display, visible: el.offsetParent !== null, text: el.textContent.trim(), outerHTML: el.outerHTML.substring(0, 500) };
    });
    log(`Article 2 #tp-snp2 state: ${JSON.stringify(tpSnp2_2)}`);
    
    // Check gcont state
    const gcontState = await page.evaluate(() => {
      const el = document.getElementById('gcont');
      if (!el) return null;
      const style = window.getComputedStyle(el);
      return { display: style.display, position: style.position, visibility: style.visibility, outerHTML: el.outerHTML.substring(0, 800) };
    });
    log(`Article 2 #gcont state: ${JSON.stringify(gcontState)}`);
    
    // Check continueBtn
    const continueBtnState = await page.evaluate(() => {
      const el = document.getElementById('continueBtn');
      if (!el) return null;
      const style = window.getComputedStyle(el);
      return { display: style.display, visibility: style.visibility, text: el.textContent.trim().substring(0, 50) };
    });
    log(`Article 2 #continueBtn state: ${JSON.stringify(continueBtnState)}`);
  }
  
  log('=== DISCOVERY COMPLETE ===');
  log(`Files saved to: ${DIR}`);
  
  await browser.close();
})().catch(e => { console.error('FATAL:', e.message); process.exit(1); });
