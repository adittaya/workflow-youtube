#!/usr/bin/env node
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const KEY = process.argv[2] || 'UbpV2D';
const OUTDIR = path.join(__dirname, 'recordings', `cdp_${Date.now()}`);

fs.mkdirSync(path.join(OUTDIR, 'dom'), { recursive: true });
fs.mkdirSync(path.join(OUTDIR, 'js'), { recursive: true });
fs.mkdirSync(path.join(OUTDIR, 'screenshots'), { recursive: true });

let stepNum = 0;
async function dumpState(page, label, cdpSession) {
  stepNum++;
  const pad = String(stepNum).padStart(3, '0');
  const fname = `${pad}_${label.replace(/[^a-zA-Z0-9_]/g, '_')}`;

  console.log(`\n[${pad}] === ${label} ===`);

  // Get URL
  const url = page.url();
  console.log(`  URL: ${url}`);

  // Dump full JS state via CDP Runtime.evaluate
  const jsStateResp = await cdpSession.send('Runtime.evaluate', {
    expression: `JSON.stringify({
      url: location.href,
      cookies: document.cookie,
      localStorage: (() => { const o = {}; for(let i=0;i<localStorage.length;i++){const k=localStorage.key(i); o[k]=localStorage.getItem(k);} return o; })(),
      sessionStorage: (() => { const o = {}; for(let i=0;i<sessionStorage.length;i++){const k=sessionStorage.key(i); o[k]=sessionStorage.getItem(k);} return o; })(),
      timerElements: {
        '#tp-time': (() => { const e = document.querySelector('#tp-time'); if(!e) return null; const s=getComputedStyle(e); return {text:e.textContent, display:e.style.display, computedDisplay:s.display, visibility:s.visibility, outerHTML:e.outerHTML.substring(0,500)}; })(),
        '#tp-snp2': (() => { const e = document.querySelector('#tp-snp2'); if(!e) return null; const s=getComputedStyle(e); return {text:e.textContent, display:e.style.display, computedDisplay:s.display, visibility:s.visibility, outerHTML:e.outerHTML.substring(0,500)}; })(),
        '#tp-wait1': (() => { const e = document.querySelector('#tp-wait1'); if(!e) return null; const s=getComputedStyle(e); return {text:e.textContent.substring(0,100), display:e.style.display, computedDisplay:s.display, visibility:s.visibility}; })(),
        '#continueBtn': (() => { const e = document.querySelector('#continueBtn'); if(!e) return null; const s=getComputedStyle(e); return {text:e.textContent, display:e.style.display, computedDisplay:s.display, visibility:s.visibility}; })(),
        '#gcont': (() => { const e = document.querySelector('#gcont'); if(!e) return null; const s=getComputedStyle(e); return {text:e.textContent.substring(0,200), display:e.style.display, computedDisplay:s.display, visibility:s.visibility, position:s.position, zIndex:s.zIndex}; })(),
        '#block-cont-1': (() => { const e = document.querySelector('#block-cont-1'); if(!e) return null; const s=getComputedStyle(e); return {text:e.textContent.substring(0,100), display:e.style.display, computedDisplay:s.display, position:s.position, zIndex:s.zIndex}; })(),
        '#get-link': (() => { const e = document.querySelector('#get-link'); if(!e) return null; const s=getComputedStyle(e); return {text:e.textContent, href:e.href, display:e.style.display, computedDisplay:s.display, className:e.className}; })(),
        '#gt-link': (() => { const e = document.querySelector('#gt-link'); if(!e) return null; const s=getComputedStyle(e); return {text:e.textContent, href:e.href, display:e.style.display, computedDisplay:s.display, className:e.className}; })(),
        '#ce-time': (() => { const e = document.querySelector('#ce-time'); if(!e) return null; const s=getComputedStyle(e); return {text:e.textContent, display:e.style.display, computedDisplay:s.display}; })(),
        '#ce-wait1': (() => { const e = document.querySelector('#ce-wait1'); if(!e) return null; const s=getComputedStyle(e); return {text:e.textContent.substring(0,100), display:e.style.display, computedDisplay:s.display}; })(),
        '#btn6': (() => { const e = document.querySelector('#btn6'); if(!e) return null; const s=getComputedStyle(e); return {text:e.textContent, display:e.style.display, computedDisplay:s.display}; })(),
        '#btn7': (() => { const e = document.querySelector('#btn7'); if(!e) return null; const s=getComputedStyle(e); return {text:e.textContent, href:e.href, display:e.style.display, computedDisplay:s.display, outerHTML:e.outerHTML.substring(0,500)}; })(),
        '#link1s-time': (() => { const e = document.querySelector('#link1s-time'); if(!e) return null; const s=getComputedStyle(e); return {text:e.textContent, display:e.style.display, computedDisplay:s.display}; })(),
        '#startCountdownBtn': (() => { const e = document.querySelector('#startCountdownBtn'); if(!e) return null; const s=getComputedStyle(e); return {text:e.textContent, display:e.style.display, computedDisplay:s.display}; })(),
        '#cross-snp2': (() => { const e = document.querySelector('#cross-snp2'); if(!e) return null; const s=getComputedStyle(e); return {text:e.textContent, display:e.style.display, computedDisplay:s.display}; })(),
      },
      // Check if there's an interval timer running
      timerCheck: (() => {
        const tpTime = document.querySelector('#tp-time');
        if (!tpTime) return {hasTimer: false};
        return {
          hasTimer: true,
          currentText: tpTime.textContent,
          tpTimeDisplay: tpTime.style.display,
          tpSnp2Display: document.querySelector('#tp-snp2')?.style.display,
          tpWait1Display: document.querySelector('#tp-wait1')?.style.display,
        };
      })(),
      // Check all intervals
      intervalCount: (() => {
        let count = 0;
        const origSetInterval = window.setInterval;
        return {note: 'cannot enumerate existing intervals'};
      })(),
    })`,
    returnByValue: true,
    awaitPromise: false,
  });

  const rawVal = jsStateResp?.result?.value;
  if (!rawVal) {
    console.log(`  WARNING: No JS state returned for ${label}`);
    return {};
  }
  const state = JSON.parse(rawVal);
  fs.writeFileSync(path.join(OUTDIR, 'dom', `${fname}_state.json`), JSON.stringify(state, null, 2));

  // Print key fields
  for (const [sel, info] of Object.entries(state.timerElements)) {
    if (info && (sel.includes('tp-') || sel.includes('snp') || sel.includes('wait') || sel.includes('continue') || sel.includes('gcont') || sel.includes('block-cont') || sel.includes('get-link') || sel.includes('gt-link') || sel.includes('ce-') || sel.includes('btn6') || sel.includes('btn7') || sel.includes('link1s') || sel.includes('startCount') || sel.includes('cross-snp'))) {
      const vis = info.computedDisplay !== 'none' ? 'VISIBLE' : 'hidden';
      const txt = (info.text || '').substring(0, 40).replace(/\n/g, ' ');
      console.log(`  ${sel}: [${vis}] display=${info.computedDisplay} text="${txt}"${info.href ? ' href='+info.href.substring(0,80) : ''}${info.zIndex ? ' z='+info.zIndex : ''}`);
    }
  }

  // Dump HTML
  const htmlResult = await cdpSession.send('Runtime.evaluate', {
    expression: `document.documentElement.outerHTML`,
    returnByValue: true,
  });
  const htmlVal = htmlResult?.result?.value || '<empty>';
  fs.writeFileSync(path.join(OUTDIR, 'dom', `${fname}.html`), htmlVal);

  // Screenshot
  await page.screenshot({ path: path.join(OUTDIR, 'screenshots', `${fname}.png`), fullPage: false });

  // Dump inline scripts content (looking for timer logic)
  const scriptsResult = await cdpSession.send('Runtime.evaluate', {
    expression: `JSON.stringify(Array.from(document.querySelectorAll('script:not([src])')).map((s,i)=>({index:i, length:s.textContent.length, snippet: s.textContent.substring(0,200)})).filter(s=>s.length>10))`,
    returnByValue: true,
  });
  const scripts = JSON.parse(scriptsResult?.result?.value || '[]');
  if (scripts.length > 0) {
    fs.writeFileSync(path.join(OUTDIR, 'js', `${fname}_inline_scripts.json`), JSON.stringify(scripts, null, 2));
    console.log(`  [${scripts.length} inline scripts found]`);
    for (const s of scripts) {
      console.log(`    script#${s.index} (${s.length} chars): ${s.snippet.substring(0,100)}...`);
    }
  }

  // Check for the timer JS specifically - search all scripts for tp-time, tp-snp2, setInterval
  const timerJSResult = await cdpSession.send('Runtime.evaluate', {
    expression: `
      // Search for timer-related code in all script elements
      const allScripts = Array.from(document.querySelectorAll('script'));
      const timerScripts = [];
      for (const s of allScripts) {
        const src = s.src || '(inline)';
        const content = s.textContent || '';
        if (content.includes('tp-time') || content.includes('tp_snp2') || content.includes('tp-snp2') || content.includes('tpTime') || content.includes('tp_time') || content.includes('snp2') || content.includes('countdown') || content.includes('setInterval')) {
          timerScripts.push({src, length: content.length, content: content.substring(0, 2000)});
        }
      }
      JSON.stringify(timerScripts);
    `,
    returnByValue: true,
  });
  const timerScripts = JSON.parse(timerJSResult?.result?.value || '[]');
  if (timerScripts.length > 0) {
    console.log(`  [TIMER-RELATED SCRIPTS FOUND: ${timerScripts.length}]`);
    for (const s of timerScripts) {
      console.log(`    ${s.src} (${s.length} chars)`);
      console.log(`    content: ${s.content.substring(0, 500)}`);
    }
    fs.writeFileSync(path.join(OUTDIR, 'js', `${fname}_timer_scripts.json`), JSON.stringify(timerScripts, null, 2));
  }

  return state;
}

// Try to find and invoke the timer callback directly
async function investigateTimer(page, cdpSession) {
  console.log('\n=== INVESTIGATING TIMER MECHANISM ===');

  const result = await cdpSession.send('Runtime.evaluate', {
    expression: `
      // Try to understand how the countdown works
      const findings = {};

      // 1. Check if tp-time has event listeners
      const tpTime = document.querySelector('#tp-time');
      findings.tpTimeExists = !!tpTime;
      if (tpTime) {
        findings.tpTimeValue = parseInt(tpTime.textContent);
        findings.tpTimeDisplay = tpTime.style.display;
      }

      // 2. Try to find setInterval callbacks by patching
      // Check if there's a global timer variable
      const globalVars = [];
      for (const key of Object.keys(window)) {
        if (key.toLowerCase().includes('timer') || key.toLowerCase().includes('count') || key.toLowerCase().includes('interval')) {
          globalVars.push({key, type: typeof window[key], value: String(window[key]).substring(0,100)});
        }
      }
      findings.globalVars = globalVars;

      // 3. Try to find the countdown function by checking all properties of window
      const countdownRelated = [];
      for (const key of Object.getOwnPropertyNames(window)) {
        try {
          const val = window[key];
          if (typeof val === 'function') {
            const src = val.toString();
            if (src.includes('tp-time') || src.includes('snp2') || src.includes('tpTime') || src.includes('countdown')) {
              countdownRelated.push({key, snippet: src.substring(0, 500)});
            }
          }
        } catch(e) {}
      }
      findings.countdownFunctions = countdownRelated;

      // 4. Check jQuery data if present
      if (window.jQuery) {
        try {
          findings.jqueryPresent = true;
          const tpTimeEl = jQuery('#tp-time');
          findings.jqueryTpTime = tpTimeEl.length > 0 ? {
            text: tpTimeEl.text(),
            css: tpTimeEl.css(['display', 'visibility']),
            data: tpTimeEl.data()
          } : null;
        } catch(e) {
          findings.jqueryError = e.message;
        }
      }

      // 5. Try to intercept setInterval to capture the timer callback
      // Monkey-patch to log the next few interval callbacks
      findings.originalSetInterval = typeof window.__orig_setInterval !== 'undefined';

      JSON.stringify(findings);
    `,
    returnByValue: true,
  });

  const findings = JSON.parse(result.result.value);
  console.log(JSON.stringify(findings, null, 2));
  return findings;
}

// Patch setInterval to capture timer callbacks
async function patchIntervalCapture(page, cdpSession) {
  console.log('\n=== PATCHING setInterval TO CAPTURE CALLBACKS ===');

  await cdpSession.send('Runtime.evaluate', {
    expression: `
      // Capture the original
      window.__captured_intervals = [];
      window.__orig_setInterval = window.setInterval;
      window.setInterval = function(fn, delay) {
        const fnStr = typeof fn === 'function' ? fn.toString() : String(fn);
        window.__captured_intervals.push({
          fnSnippet: fnStr.substring(0, 500),
          delay: delay,
          time: Date.now(),
          stack: new Error().stack
        });
        return window.__orig_setInterval(fn, delay);
      };
      console.log('[CDP] setInterval patched to capture callbacks');
    `,
    returnByValue: true,
  });
}

// After a delay, check what intervals were captured
async function checkCapturedIntervals(page, cdpSession) {
  const result = await cdpSession.send('Runtime.evaluate', {
    expression: `JSON.stringify(window.__captured_intervals || [])`,
    returnByValue: true,
  });
  const intervals = JSON.parse(result.result.value);
  console.log(`\n=== CAPTURED ${intervals.length} setInterval CALLS ===`);
  for (const iv of intervals) {
    console.log(`  delay=${iv.delay}ms fn=${iv.fnSnippet.substring(0,200)}`);
  }
  return intervals;
}

async function main() {
  console.log(`=== CDP EXPLORATION: vplink.in/${KEY} ===`);
  console.log(`Output: ${OUTDIR}\n`);

  const browser = await chromium.launch({
    headless: true,
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-gpu',
      '--use-gl=swiftshader',
      '--disable-blink-features=AutomationControlled',
    ],
  });

  const context = await browser.newContext({
    userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    viewport: { width: 1366, height: 768 },
  });

  // Stealth
  await context.addInitScript(() => {
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
    window.chrome = { runtime: {} };
  });

  const page = await context.newPage();
  const cdp = await context.newCDPSession(page);

  // Enable domains
  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');
  await cdp.send('Network.enable');
  await cdp.send('DOM.enable');

  // Patch setInterval BEFORE navigation to capture timer setup
  await patchIntervalCapture(page, cdp);

  // Listen for navigations
  cdp.on('Page.frameNavigated', (params) => {
    console.log(`  [NAV] ${params.frame.url?.substring(0, 120)}`);
  });

  // Listen for console
  cdp.on('Runtime.consoleAPICalled', (params) => {
    if (params.type === 'log' || params.type === 'error' || params.type === 'warn') {
      const msg = params.args.map(a => a.value || a.description || '').join(' ');
      if (msg.includes('CDP')) return; // skip our own
      console.log(`  [CONSOLE.${params.type.toUpperCase()}] ${msg.substring(0, 200)}`);
    }
  });

  try {
    // STAGE 1: Navigate to vplink.in
    console.log('\n--- STAGE 1: Navigate to vplink.in ---');
    await page.goto(`https://vplink.in/${KEY}`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    // Wait for JS redirect to fire (vplink.in does immediate JS redirect)
    await new Promise(r => setTimeout(r, 3000));
    await dumpState(page, '01_vplink_in', cdp);

    // STAGE 2: Wait for redirect chain to article
    console.log('\n--- STAGE 2: Wait for redirect to article ---');
    await page.waitForURL(url => !url.includes('vplink.in'), { timeout: 15000 }).catch(() => {});
    await page.waitForLoadState('domcontentloaded', { timeout: 15000 }).catch(() => {});
    await new Promise(r => setTimeout(r, 3000));
    const state2 = await dumpState(page, '02_article_landed', cdp);

    // Check captured intervals after landing
    const intervals = await checkCapturedIntervals(page, cdp);

    // STAGE 3: Investigate timer mechanism
    console.log('\n--- STAGE 3: Investigate timer mechanism ---');
    await investigateTimer(page, cdp);

    // STAGE 4: Wait and poll timer state every 2 seconds
    console.log('\n--- STAGE 4: Poll timer state over time ---');
    for (let i = 0; i < 30; i++) {
      await new Promise(r => setTimeout(r, 2000));
      const pollResult = await cdp.send('Runtime.evaluate', {
        expression: `JSON.stringify({
          tpTime: document.querySelector('#tp-time')?.textContent,
          tpTimeDisplay: document.querySelector('#tp-time')?.style.display,
          tpSnp2Display: document.querySelector('#tp-snp2')?.style.display,
          tpSnp2Computed: getComputedStyle(document.querySelector('#tp-snp2')||document.body).display,
          tpWait1Display: document.querySelector('#tp-wait1')?.style.display,
          url: location.href,
          gcontDisplay: document.querySelector('#gcont')?.style.display,
          continueBtn: !!document.querySelector('#continueBtn'),
        })`,
        returnByValue: true,
      });
      const poll = JSON.parse(pollResult.result.value);
      console.log(`  [${i*2}s] timer=${poll.tpTime} tp-time.display=${poll.tpTimeDisplay} tp-snp2.computed=${poll.tpSnp2Computed} tp-wait1.display=${poll.tpWait1Display} url=${poll.url.substring(0,60)}`);

      // When tp-snp2 becomes visible or timer seems stuck, dump full state
      if (poll.tpSnp2Computed === 'block' || (poll.tpTime === '1' && i > 3)) {
        if (poll.tpSnp2Computed === 'block') {
          console.log('  >>> tp-snp2 IS VISIBLE! Dumping full state...');
          await dumpState(page, `03_snp2_visible_${i*2}s`, cdp);
          break;
        }
        if (poll.tpTime === '1' && i > 5) {
          console.log('  >>> Timer stuck at 1, tp-snp2 still hidden. Investigating...');
          await dumpState(page, `03_timer_stuck_${i*2}s`, cdp);

          // Try to manually trigger the timer callback
          console.log('\n--- ATTEMPTING MANUAL BUTTON SHOW ---');
          const manualShow = await cdp.send('Runtime.evaluate', {
            expression: `
              const results = {};
              // 1. Try directly setting display
              const snp2 = document.querySelector('#tp-snp2');
              const wait1 = document.querySelector('#tp-wait1');
              if (snp2) {
                results.snp2Before = snp2.style.display;
                snp2.style.display = 'block';
                results.snp2After = snp2.style.display;
                results.snp2Computed = getComputedStyle(snp2).display;
              }
              if (wait1) {
                results.wait1Before = wait1.style.display;
                wait1.style.display = 'none';
                results.wait1After = wait1.style.display;
              }

              // 2. Try clicking the parent <a> of tp-snp2
              const parentA = snp2?.closest('a');
              if (parentA) {
                results.parentAHref = parentA.href;
                results.parentATagName = parentA.tagName;
              }

              // 3. Try setting tp-time to 0
              const tpTime = document.querySelector('#tp-time');
              if (tpTime) {
                results.tpTimeBefore = tpTime.textContent;
                tpTime.textContent = '0';
              }

              // 4. Try to find and call the countdown callback directly
              // Look for event listeners on tp-time
              results.allGlobalsWithSnp2 = [];
              for (const key of Object.getOwnPropertyNames(window)) {
                try {
                  const val = window[key];
                  if (typeof val === 'function' && val.toString().includes('snp2')) {
                    results.allGlobalsWithSnp2.push(key);
                  }
                } catch(e) {}
              }

              // 5. Try jQuery click if available
              if (window.jQuery) {
                try {
                  jQuery('#tp-snp2').trigger('click');
                  results.jqueryClickTriggered = true;
                } catch(e) {
                  results.jqueryClickError = e.message;
                }
              }

              // 6. Check for click handlers on the parent <a>
              if (parentA) {
                results.parentAClick = typeof parentA.onclick;
              }

              JSON.stringify(results);
            `,
            returnByValue: true,
          });
          const manual = JSON.parse(manualShow.result.value);
          console.log('  Manual show results:', JSON.stringify(manual, null, 2));

          // Wait a moment and check if clicking worked
          await new Promise(r => setTimeout(r, 3000));
          await dumpState(page, `04_after_manual_show`, cdp);

          // Now try clicking the tp-snp2 button
          console.log('\n--- CLICKING tp-snp2 ---');
          try {
            // Force click via CDP directly
            const snp2Box = await page.locator('#tp-snp2').boundingBox();
            if (snp2Box) {
              console.log(`  tp-snp2 bounding box: ${JSON.stringify(snp2Box)}`);
              await cdp.send('Input.dispatchMouseEvent', {
                type: 'mousePressed',
                x: snp2Box.x + snp2Box.width / 2,
                y: snp2Box.y + snp2Box.height / 2,
                button: 'left',
                clickCount: 1,
              });
              await cdp.send('Input.dispatchMouseEvent', {
                type: 'mouseReleased',
                x: snp2Box.x + snp2Box.width / 2,
                y: snp2Box.y + snp2Box.height / 2,
                button: 'left',
                clickCount: 1,
              });
              console.log('  Clicked tp-snp2 via CDP Input events');
            } else {
              // Force click via JS
              await cdp.send('Runtime.evaluate', {
                expression: `document.querySelector('#tp-snp2')?.click(); document.querySelector('#tp-snp2')?.closest('a')?.click();`,
                returnByValue: true,
              });
              console.log('  Clicked tp-snp2 via JS (no bounding box)');
            }
          } catch(e) {
            console.log(`  Click error: ${e.message}`);
          }

          await new Promise(r => setTimeout(r, 5000));
          await dumpState(page, '05_after_click', cdp);
          break;
        }
      }
    }

    // STAGE 5: Check captured intervals after full flow
    await checkCapturedIntervals(page, cdp);

    // Check for all script srcs that loaded
    console.log('\n--- LOADED EXTERNAL SCRIPTS ---');
    const scriptSrcs = await cdp.send('Runtime.evaluate', {
      expression: `JSON.stringify(Array.from(document.querySelectorAll('script[src]')).map(s=>s.src).filter(s=>!s.includes('google') && !s.includes('clarity') && !s.includes('cloudflare') && !s.includes('doubleclick'))`,
      returnByValue: true,
    });
    console.log(JSON.parse(scriptSrcs.result.value));

    // Deep dive: search ALL loaded JS for timer logic
    console.log('\n--- SEARCHING ALL LOADED JS FOR TIMER LOGIC ---');
    const scriptContents = await cdp.send('Runtime.evaluate', {
      expression: `
        // Fetch all same-origin scripts and search for timer logic
        async function findTimerLogic() {
          const scripts = Array.from(document.querySelectorAll('script[src]'));
          const sameOrigin = scripts.filter(s => s.src.includes(location.hostname));
          const results = [];
          for (const s of sameOrigin) {
            try {
              const resp = await fetch(s.src);
              const text = await resp.text();
              if (text.includes('tp-time') || text.includes('snp2') || text.includes('tpTime') || text.includes('countdown')) {
                results.push({
                  src: s.src,
                  length: text.length,
                  // Find the relevant section
                  timerSection: (() => {
                    const idx = text.indexOf('tp-time');
                    const idx2 = text.indexOf('snp2');
                    const idx3 = text.indexOf('tpTime');
                    const idx4 = text.indexOf('countdown');
                    const minIdx = Math.min(...[idx, idx2, idx3, idx4].filter(i => i >= 0));
                    if (minIdx >= 0) {
                      return text.substring(Math.max(0, minIdx - 200), minIdx + 800);
                    }
                    return text.substring(0, 500);
                  })(),
                });
              }
            } catch(e) {
              results.push({src: s.src, error: e.message});
            }
          }
          return JSON.stringify(results);
        }
        findTimerLogic();
      `,
      returnByValue: true,
      awaitPromise: true,
    });
    const timerLogic = JSON.parse(scriptContents.result.value);
    console.log(JSON.stringify(timerLogic, null, 2));
    fs.writeFileSync(path.join(OUTDIR, 'js', 'timer_logic_from_scripts.json'), JSON.stringify(timerLogic, null, 2));

  } catch(e) {
    console.error(`FATAL: ${e.message}`);
    console.error(e.stack);
  } finally {
    await browser.close();
    console.log(`\n=== DONE. Output: ${OUTDIR} ===`);
  }
}

main().catch(console.error);
