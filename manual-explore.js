#!/usr/bin/env node
// Manual CDP exploration — open browser, navigate step by step, observe everything
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const KEY = process.argv[2] || 'UbpV2D';
const OUT = path.join(__dirname, 'recordings', `manual_${Date.now()}`);
fs.mkdirSync(path.join(OUT, 'dom'), { recursive: true });
fs.mkdirSync(path.join(OUT, 'screenshots'), { recursive: true });

let step = 0;
const snap = async (page, label) => {
  step++;
  const pad = String(step).padStart(3, '0');
  const f = `${pad}_${label}`;
  
  const state = await page.evaluate(() => {
    const getInfo = (sel) => {
      const el = document.querySelector(sel);
      if (!el) return null;
      const s = getComputedStyle(el);
      return {
        display: s.display, visibility: s.visibility, position: s.position,
        zIndex: s.zIndex, text: el.textContent?.substring(0, 80)?.replace(/\s+/g, ' ').trim(),
        href: el.href || null, outerHTML: el.outerHTML?.substring(0, 500),
        disabled: el.disabled, className: el.className
      };
    };
    return {
      url: location.href,
      cookies: document.cookie,
      tp: getInfo('#tp-time'), snp2: getInfo('#tp-snp2'), wait1: getInfo('#tp-wait1'),
      gcont: getInfo('#gcont'), block1: getInfo('#block-cont-1'),
      contBtn: getInfo('#continueBtn'), ggd: getInfo('#ggd-container'),
      getlink: getInfo('#get-link'), gtlink: getInfo('#gt-link'),
      crossSnp2: getInfo('#cross-snp2'), startBtn: getInfo('#startCountdownBtn'),
      ceTime: getInfo('#ce-time'), ceWait: getInfo('#ce-wait1'),
      btn6: getInfo('#btn6'), btn7: getInfo('#btn7'),
      allLinks: Array.from(document.querySelectorAll('a')).map(a => ({
        href: a.href?.substring(0, 120), text: a.textContent?.trim()?.substring(0, 50),
        visible: getComputedStyle(a).display !== 'none' && a.offsetParent !== null
      })).filter(l => l.href?.includes('learn_more') || l.href?.includes('get-link') || 
                      l.href?.includes('gt-link') || l.href?.includes('vplink'))
    };
  });

  fs.writeFileSync(path.join(OUT, 'dom', `${f}.json`), JSON.stringify(state, null, 2));
  await page.screenshot({ path: path.join(OUT, 'screenshots', `${f}.png`) });

  console.log(`\n=== [${pad}] ${label} ===`);
  console.log(`URL: ${state.url?.substring(0, 100)}`);
  if (state.tp) console.log(`  #tp-time: "${state.tp.text}" display=${state.tp.display}`);
  if (state.snp2) console.log(`  #tp-snp2: display=${state.snp2.display} vis=${state.snp2.visibility}`);
  if (state.wait1) console.log(`  #tp-wait1: display=${state.wait1.display}`);
  if (state.gcont) console.log(`  #gcont: display=${state.gcont.display} pos=${state.gcont.position} z=${state.gcont.zIndex}`);
  if (state.block1) console.log(`  #block-cont-1: display=${state.block1.display} pos=${state.block1.position}`);
  if (state.contBtn) console.log(`  #continueBtn: display=${state.contBtn.display}`);
  if (state.crossSnp2) console.log(`  #cross-snp2: display=${state.crossSnp2.display}`);
  if (state.startBtn) console.log(`  #startCountdownBtn: disabled=${state.startBtn.disabled} text="${state.startBtn.text}"`);
  if (state.ceTime) console.log(`  #ce-time: "${state.ceTime.text}" display=${state.ceTime.display}`);
  if (state.getlink) console.log(`  #get-link: display=${state.getlink.display} text="${state.getlink.text}"`);
  if (state.gtlink) console.log(`  #gt-link: display=${state.gtlink.display} href=${state.gtlink.href?.substring(0,80)}`);
  if (state.allLinks?.length) {
    console.log('  LINKS:');
    state.allLinks.forEach(l => console.log(`    [${l.visible?'VIS':'---'}] ${l.text?.substring(0,30)} → ${l.href}`));
  }
  console.log(`  Cookies: ${state.cookies?.substring(0, 150)}`);

  return state;
};

// Poll every N seconds, return when condition met
const poll = async (page, label, checkFn, maxSec = 60) => {
  console.log(`\n--- POLLING: ${label} (max ${maxSec}s) ---`);
  for (let i = 0; i < maxSec * 2; i++) {
    const state = await page.evaluate(() => {
      const g = (sel) => {
        const el = document.querySelector(sel);
        return el ? { display: getComputedStyle(el).display, text: el.textContent?.substring(0, 40)?.trim() } : null;
      };
      return {
        url: location.href,
        tp: g('#tp-time'), snp2: g('#tp-snp2'), wait1: g('#tp-wait1'),
        gcont: document.querySelector('#gcont') ? getComputedStyle(document.querySelector('#gcont')).display : null,
        contBtn: document.querySelector('#continueBtn') ? getComputedStyle(document.querySelector('#continueBtn')).display : null,
        crossSnp2: g('#cross-snp2'), startBtn: g('#startCountdownBtn'),
      };
    });
    
    const result = checkFn(state);
    if (i % 4 === 0) {
      const vals = [];
      if (state.tp) vals.push(`tp="${state.tp.text}"`);
      if (state.snp2) vals.push(`snp2=${state.snp2.display}`);
      if (state.crossSnp2) vals.push(`cross=${state.crossSnp2.display}`);
      if (state.wait1) vals.push(`wait1=${state.wait1.display}`);
      if (state.gcont) vals.push(`gcont=${state.gcont}`);
      if (state.contBtn) vals.push(`contBtn=${state.contBtn}`);
      console.log(`  [${(i/2).toFixed(0)}s] ${vals.join(' | ')}`);
    }
    if (result) {
      console.log(`  ✓ Condition met at ${(i/2).toFixed(0)}s`);
      return state;
    }
    await new Promise(r => setTimeout(r, 500));
  }
  console.log(`  ✗ Timed out after ${maxSec}s`);
  return null;
};

(async () => {
  const browser = await chromium.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-gpu', '--use-gl=swiftshader', '--disable-blink-features=AutomationControlled'],
  });
  const ctx = await browser.newContext({
    viewport: { width: 1366, height: 768 },
    userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
  });
  await ctx.addInitScript(() => {
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    window.chrome = { runtime: {} };
  });

  const page = await ctx.newPage();
  console.log(`=== MANUAL CDP EXPLORATION: vplink.in/${KEY} ===\n`);

  try {
    // STEP 1: Navigate to vplink.in
    console.log('\n>>> STEP 1: Navigate to vplink.in');
    await page.goto(`https://vplink.in/${KEY}`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await new Promise(r => setTimeout(r, 3000)); // wait for JS redirect
    await snap(page, 'after_vplink_redirect');

    // STEP 2: Wait for article page
    console.log('\n>>> STEP 2: Wait for article to fully load');
    await page.waitForLoadState('networkidle', { timeout: 20000 }).catch(() => {});
    await new Promise(r => setTimeout(r, 2000));
    const artState = await snap(page, 'article_loaded');
    console.log(`\nTemplate detected: ${
      artState.tp ? 'TP' : artState.ceTime ? 'CE' : artState.crossSnp2 ? 'LINK1S' : 'UNKNOWN'
    }`);

    // STEP 3: Check if #gcont overlay is blocking — what happens when we click it?
    console.log('\n>>> STEP 3: Observe overlay state');
    const overlayInfo = await page.evaluate(() => {
      const gcont = document.querySelector('#gcont');
      const block1 = document.querySelector('#block-cont-1');
      const ggd = document.querySelector('#ggd-container');
      const svg = document.querySelector('#gcont .bgcount svg');
      return {
        gcontZ: gcont ? getComputedStyle(gcont).zIndex : null,
        gcontPos: gcont ? getComputedStyle(gcont).position : null,
        block1Z: block1 ? getComputedStyle(block1).zIndex : null,
        svgExists: !!svg,
        // Check if tp-snp2 is behind the overlay
        snp2Rect: document.querySelector('#tp-snp2')?.getBoundingClientRect(),
        gcontRect: gcont?.getBoundingClientRect(),
      };
    });
    console.log('  Overlay z-indexes:', JSON.stringify(overlayInfo, null, 2));

    // STEP 4: Wait for timer to count down — poll every 2s
    console.log('\n>>> STEP 4: Watch timer countdown');
    const timerDone = await poll(page, 'timer countdown', (s) => {
      // Timer is done when tp-snp2 becomes visible OR tp-time disappears (count reached 0)
      return s.snp2?.display === 'block' || !s.tp;
    }, 60);

    await snap(page, 'after_timer');

    // STEP 5: Now try clicking tp-snp2 — first check what's covering it
    console.log('\n>>> STEP 5: Analyze clickability of #tp-snp2');
    const clickability = await page.evaluate(() => {
      const snp2 = document.querySelector('#tp-snp2');
      if (!snp2) return { exists: false };
      const rect = snp2.getBoundingClientRect();
      const style = getComputedStyle(snp2);
      
      // Check what element is at the center of tp-snp2
      const centerX = rect.x + rect.width / 2;
      const centerY = rect.y + rect.height / 2;
      const topEl = document.elementFromPoint(centerX, centerY);
      
      // Check parent <a>
      const parentA = snp2.closest('a');
      
      return {
        exists: true,
        display: style.display,
        visibility: style.visibility,
        rect: { x: rect.x, y: rect.y, w: rect.width, h: rect.height },
        elementAtCenter: topEl ? { tag: topEl.tagName, id: topEl.id, class: topEl.className?.substring?.(0, 80) } : null,
        parentA: parentA ? { href: parentA.href?.substring(0, 120), display: getComputedStyle(parentA).display } : null,
      };
    });
    console.log('  Clickability:', JSON.stringify(clickability, null, 2));

    // STEP 6: Try clicking via different methods and observe
    console.log('\n>>> STEP 6: Try clicking tp-snp2 via Playwright click');
    try {
      await page.locator('#tp-snp2').click({ timeout: 5000 });
      console.log('  Playwright click succeeded');
    } catch (e) {
      console.log(`  Playwright click failed: ${e.message.substring(0, 100)}`);
    }
    await new Promise(r => setTimeout(r, 3000));
    const afterPwClick = await snap(page, 'after_playwright_click');
    
    // Check if URL changed
    console.log(`  URL after click: ${afterPwClick.url?.substring(0, 100)}`);

    // STEP 7: If no navigation, try clicking the parent <a> directly
    if (afterPwClick.url?.includes('darkguruji') || afterPwClick.url?.includes('srtak')) {
      console.log('\n>>> STEP 7: Try clicking parent <a> of tp-snp2 via JS');
      const navResult = await page.evaluate(() => {
        const snp2 = document.querySelector('#tp-snp2');
        const a = snp2?.closest('a');
        if (a) {
          return { href: a.href, target: a.target, onclick: !!a.onclick };
        }
        return null;
      });
      console.log('  Parent <a>:', JSON.stringify(navResult, null, 2));

      // Try window.location.href
      if (navResult?.href) {
        console.log(`\n>>> STEP 8: Navigate via window.location.href = ${navResult.href}`);
        await page.evaluate((href) => { window.location.href = href; }, navResult.href);
        await new Promise(r => setTimeout(r, 5000));
        await snap(page, 'after_location_navigate');
      }
    }

    // Continue: wait for next article
    console.log('\n>>> STEP 9: Wait for next page');
    await page.waitForLoadState('domcontentloaded', { timeout: 15000 }).catch(() => {});
    await new Promise(r => setTimeout(r, 3000));
    const nextArt = await snap(page, 'next_article');
    console.log(`  URL: ${nextArt.url?.substring(0, 100)}`);
    console.log(`  Template: ${nextArt.tp ? 'TP' : nextArt.ceTime ? 'CE' : nextArt.crossSnp2 ? 'LINK1S' : 'UNKNOWN'}`);

    // If we're on a new article, watch THIS article's timer too
    if (nextArt.tp) {
      console.log('\n>>> STEP 10: Watch article 2 timer — DO NOTHING, just observe');
      const art2Done = await poll(page, 'article 2 timer', (s) => {
        return s.snp2?.display === 'block' || !s.tp;
      }, 60);
      
      await snap(page, 'article2_after_timer');
      
      // Check clickability of snp2 on article 2
      const art2Click = await page.evaluate(() => {
        const snp2 = document.querySelector('#tp-snp2');
        if (!snp2) return { exists: false };
        const rect = snp2.getBoundingClientRect();
        const topEl = document.elementFromPoint(rect.x + rect.width/2, rect.y + rect.height/2);
        const parentA = snp2.closest('a');
        return {
          display: getComputedStyle(snp2).display,
          rect: { x: rect.x, y: rect.y, w: rect.width, h: rect.height },
          elementAtCenter: topEl ? { tag: topEl.tagName, id: topEl.id } : null,
          parentA: parentA ? { href: parentA.href?.substring(0, 120) } : null,
        };
      });
      console.log('  Art2 clickability:', JSON.stringify(art2Click, null, 2));

      // Try clicking
      if (art2Click.parentA?.href) {
        console.log(`\n>>> STEP 11: Navigate art2 via ${art2Click.parentA.href}`);
        await page.evaluate((href) => { window.location.href = href; }, art2Click.parentA.href);
        await new Promise(r => setTimeout(r, 5000));
        await snap(page, 'after_art2_navigate');
      }
    }

  } catch (e) {
    console.error(`ERROR: ${e.message}`);
  } finally {
    await browser.close();
    console.log(`\n=== DONE. Output: ${OUT} ===`);
  }
})();
