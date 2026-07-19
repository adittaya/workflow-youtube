#!/usr/bin/env node
// Fast analysis: single model, larger batches, saves incrementally

const fs = require('fs');
const path = require('path');

const API_KEY = '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';
const API_URL = 'https://integrate.api.nvidia.com/v1/chat/completions';
const MODEL = 'meta/llama-3.2-11b-vision-instruct';

const SCREENSHOTS_DIR = path.join(__dirname, 'recordings/recording_2026-07-18T15-20-49-123Z/screenshots');
const OUTPUT = path.join(__dirname, 'recordings/analysis/results.jsonl');
const SUMMARY = path.join(__dirname, 'recordings/analysis/summary.json');

const PROMPT = `Analyze this browser screenshot for a vplink.in URL shortener automation. Return ONLY valid JSON (no markdown):
{"n":<screenshot_number>,"type":"vplink.in"|"article_page"|"goog_rewarded_ad"|"learn_more"|"intermediate"|"destination"|"unknown","domain":"<domain>","timer":{"present":<bool>,"id":"<id>","val":"<countdown value>","tmpl":"TP"|"CE"|"LINK1S"|"none"},"buttons":[{"id":"<id>","text":"<text>","vis":<bool>}],"popup":<bool>,"overlay":<bool>,"googAd":<bool>,"notes":"<brief>"}`;

function encodeImage(fp) { return fs.readFileSync(fp).toString('base64'); }

async function analyze(imageBase64, num) {
  try {
    const resp = await fetch(API_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${API_KEY}` },
      body: JSON.stringify({
        model: MODEL,
        messages: [{ role: 'user', content: [
          { type: 'text', text: PROMPT },
          { type: 'image_url', image_url: { url: `data:image/png;base64,${imageBase64}` } }
        ]}],
        max_tokens: 512,
        temperature: 0.05
      }),
      signal: AbortSignal.timeout(30000)
    });
    if (!resp.ok) return { n: num, error: `HTTP ${resp.status}` };
    const data = await resp.json();
    const txt = data.choices?.[0]?.message?.content || '';
    const m = txt.match(/\{[\s\S]*\}/);
    if (m) return JSON.parse(m[0]);
    return { n: num, raw: txt };
  } catch (e) { return { n: num, error: e.message }; }
}

async function main() {
  fs.mkdirSync(path.dirname(OUTPUT), { recursive: true });
  
  // Check for existing progress
  const done = new Set();
  if (fs.existsSync(OUTPUT)) {
    fs.readFileSync(OUTPUT, 'utf8').split('\n').filter(Boolean).forEach(line => {
      try { const r = JSON.parse(line); done.add(r.n); } catch {}
    });
    console.error(`Resuming: ${done.size} already done`);
  }

  const files = fs.readdirSync(SCREENSHOTS_DIR).filter(f => f.endsWith('.png')).sort();
  const pending = files.filter(f => {
    const n = parseInt(f.replace(/\D/g, ''));
    return !done.has(n);
  });

  console.error(`Total: ${files.length}, Pending: ${pending.length}`);

  const out = fs.createWriteStream(OUTPUT, { flags: 'a' });
  let count = done.size;

  // Process in batches of 10
  const BATCH = 10;
  for (let i = 0; i < pending.length; i += BATCH) {
    const batch = pending.slice(i, i + BATCH);
    const results = await Promise.all(batch.map(async (f) => {
      const n = parseInt(f.replace(/\D/g, ''));
      const b64 = encodeImage(path.join(SCREENSHOTS_DIR, f));
      const r = await analyze(b64, n);
      count++;
      if (count % 10 === 0) console.error(`  Progress: ${count}/${files.length}`);
      return r;
    }));
    results.forEach(r => out.write(JSON.stringify(r) + '\n'));
    
    // Tiny pause between batches
    if (i + BATCH < pending.length) await new Promise(r => setTimeout(r, 500));
  }

  out.end();
  console.error(`Done: ${count} screenshots analyzed`);

  // Generate summary
  const lines = fs.readFileSync(OUTPUT, 'utf8').split('\n').filter(Boolean);
  const all = lines.map(l => { try { return JSON.parse(l); } catch { return null; } }).filter(Boolean);
  
  const byType = {};
  const timeline = [];
  const timerIds = new Set();
  const buttonIds = new Set();
  
  all.sort((a, b) => (a.n || 0) - (b.n || 0));
  all.forEach(r => {
    const t = r.type || 'unknown';
    byType[t] = (byType[t] || 0) + 1;
    if (r.timer?.id) timerIds.add(r.timer.id);
    (r.buttons || []).forEach(b => { if (b.id) buttonIds.add(b.id); });
    timeline.push({ n: r.n, type: t, domain: r.domain, timer: r.timer?.id, val: r.timer?.val, 
      tmpl: r.timer?.tmpl, btns: (r.buttons||[]).map(b=>b.id).filter(Boolean).join(','),
      popup: r.popup, overlay: r.overlay, googAd: r.googAd, notes: r.notes });
  });

  const summary = { total: all.length, byType, timerIds: [...timerIds], buttonIds: [...buttonIds], timeline };
  fs.writeFileSync(SUMMARY, JSON.stringify(summary, null, 2));
  
  console.log('\n=== SUMMARY ===');
  console.log(JSON.stringify(byType, null, 2));
  console.log('\nTimer IDs:', [...timerIds].join(', '));
  console.log('Button IDs:', [...buttonIds].join(', '));
  console.log('\n=== TIMELINE ===');
  timeline.forEach(t => {
    const p = [`${String(t.n).padStart(3)} ${t.type}`];
    if (t.domain) p.push(t.domain);
    if (t.timer) p.push(`${t.timer}=${t.val}`);
    if (t.tmpl && t.tmpl !== 'none') p.push(`tmpl:${t.tmpl}`);
    if (t.btns) p.push(`btns:${t.btns}`);
    if (t.popup) p.push('POPUP');
    if (t.overlay) p.push('OVERLAY');
    if (t.googAd) p.push('GOOG_AD');
    if (t.notes) p.push(t.notes);
    console.log(p.join(' | '));
  });
}

main().catch(e => { console.error(e); process.exit(1); });
