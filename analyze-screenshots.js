#!/usr/bin/env node
// Analyze all 154 recording screenshots using NVIDIA NIM VLM API
// Uses multiple models in parallel for comprehensive DOM/UI analysis

const fs = require('fs');
const path = require('path');

const API_KEY = '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';
const API_URL = 'https://integrate.api.nvidia.com/v1/chat/completions';

// Models to use (different perspectives)
const MODELS = [
  'meta/llama-3.2-11b-vision-instruct',
  'nvidia/nemotron-nano-12b-v2-vl',
  'nvidia/llama-3.1-nemotron-nano-vl-8b-v1'
];

const SCREENSHOTS_DIR = path.join(__dirname, 'recordings/recording_2026-07-18T15-20-49-123Z/screenshots');
const OUTPUT_DIR = path.join(__dirname, 'recordings/analysis');

const PROMPT = `You are analyzing a screenshot of an automated browser navigating through vplink.in URL shortener funnel.

Analyze this screenshot in detail and respond in JSON format with these fields:

{
  "pageNumber": <screenshot number from filename>,
  "pageType": "vplink.in" | "article_page" | "goog_rewarded_ad" | "learn_more_redirect" | "intermediate_page" | "destination_page" | "chrome_error" | "unknown",
  "domain": "<domain in URL bar>",
  "urlFragment": "<hash fragment if visible, e.g. #goog_rewarded>",
  
  "timerElement": {
    "present": true/false,
    "id": "<timer element ID, e.g. tp-time, ce-time, link1s-wait1>",
    "value": "<current countdown value shown>",
    "templateType": "TP" | "CE" | "LINK1S" | "none"
  },
  
  "visibleButtons": [
    {
      "id": "<element ID>",
      "text": "<button text>",
      "visible": true/false,
      "position": "<approximate position on page>"
    }
  ],
  
  "adOverlay": {
    "present": true/false,
    "selector": "<CSS selector for close button if visible>"
  },
  
  "continueBtnPopup": {
    "present": true/false,
    "text": "<button text>",
    "position": "<where on page>"
  },
  
  "googRewardedAd": {
    "present": true/false,
    "hasVideo": true/false,
    "skipButtonVisible": true/false,
    "skipButtonText": "<text of skip button if visible>"
  },
  
  "pageContent": "<brief description of what the page shows>",
  "interactiveElements": ["<list of all clickable/interactive elements visible>"],
  "domNotes": "<any notable DOM observations - element visibility, overlays, hidden elements>"
}

Be precise about element IDs, visibility states, and CSS display properties. If you cannot determine something, use null.`;

// Read and base64 encode an image
function encodeImage(filePath) {
  const buffer = fs.readFileSync(filePath);
  return buffer.toString('base64');
}

// Call NVIDIA VLM API
async function analyzeWithModel(imageBase64, filename, model) {
  const body = {
    model,
    messages: [{
      role: 'user',
      content: [
        { type: 'text', text: PROMPT },
        {
          type: 'image_url',
          image_url: { url: `data:image/png;base64,${imageBase64}` }
        }
      ]
    }],
    max_tokens: 1024,
    temperature: 0.1
  };

  try {
    const resp = await fetch(API_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${API_KEY}`
      },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(60000)
    });

    if (!resp.ok) {
      const errText = await resp.text();
      return { error: `HTTP ${resp.status}: ${errText.substring(0, 200)}`, model };
    }

    const data = await resp.json();
    const content = data.choices?.[0]?.message?.content || '';
    
    // Try to parse JSON from response
    let parsed = null;
    try {
      // Extract JSON from response (may be wrapped in markdown)
      const jsonMatch = content.match(/\{[\s\S]*\}/);
      if (jsonMatch) {
        parsed = JSON.parse(jsonMatch[0]);
      }
    } catch (e) {
      parsed = { rawText: content };
    }

    return { model, result: parsed, rawText: content };
  } catch (err) {
    return { error: err.message, model };
  }
}

// Process a single screenshot with all models in parallel
async function analyzeScreenshot(filename, filePath) {
  const imageBase64 = encodeImage(filePath);
  const num = parseInt(filename.replace(/\D/g, ''));

  console.error(`  [${num}] Analyzing with ${MODELS.length} models...`);
  
  const results = await Promise.all(
    MODELS.map(model => analyzeWithModel(imageBase64, filename, model))
  );

  return {
    screenshot: filename,
    number: num,
    analyses: results
  };
}

// Process screenshots in batches
async function processBatch(screenshots, batchSize) {
  const results = [];
  for (let i = 0; i < screenshots.length; i += batchSize) {
    const batch = screenshots.slice(i, i + batchSize);
    console.error(`\nProcessing batch ${Math.floor(i/batchSize)+1}/${Math.ceil(screenshots.length/batchSize)} (${batch.length} screenshots)...`);
    
    const batchResults = await Promise.all(
      batch.map(({ name, path: filePath }) => analyzeScreenshot(name, filePath))
    );
    results.push(...batchResults);
    
    // Brief pause between batches to respect rate limits
    if (i + batchSize < screenshots.length) {
      console.error('  Pausing 2s between batches...');
      await new Promise(r => setTimeout(r, 2000));
    }
  }
  return results;
}

async function main() {
  // Create output directory
  fs.mkdirSync(OUTPUT_DIR, { recursive: true });

  // Get all screenshots sorted
  const files = fs.readdirSync(SCREENSHOTS_DIR)
    .filter(f => f.endsWith('.png'))
    .sort()
    .map(name => ({ name, path: path.join(SCREENSHOTS_DIR, name) }));

  console.error(`Found ${files.length} screenshots to analyze`);
  console.error(`Using models: ${MODELS.join(', ')}`);
  console.error(`Total API calls: ${files.length * MODELS.length}\n`);

  const startTime = Date.now();
  const results = await processBatch(files, 5); // 5 screenshots in parallel
  const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
  
  console.error(`\nAnalysis complete in ${elapsed}s`);

  // Save raw results
  fs.writeFileSync(
    path.join(OUTPUT_DIR, 'raw-analyses.json'),
    JSON.stringify(results, null, 2)
  );

  // Generate summary by page type
  const summary = {
    total: results.length,
    byType: {},
    timeline: [],
    keyFindings: {
      timerElements: new Set(),
      buttonIds: new Set(),
      adDomains: new Set(),
      overlaySelectors: new Set()
    }
  };

  for (const r of results) {
    // Use first non-error result
    const best = r.analyses.find(a => a.result && !a.error) || r.analyses[0];
    const analysis = best?.result || {};

    const pageType = analysis.pageType || 'unknown';
    summary.byType[pageType] = (summary.byType[pageType] || 0) + 1;

    summary.timeline.push({
      screenshot: r.number,
      pageType,
      domain: analysis.domain,
      timer: analysis.timerElement?.id || null,
      timerValue: analysis.timerElement?.value || null,
      templateType: analysis.timerElement?.templateType || null,
      buttons: (analysis.visibleButtons || []).map(b => b.id).filter(Boolean),
      hasPopup: analysis.continueBtnPopup?.present || false,
      hasAdOverlay: analysis.adOverlay?.present || false,
      hasGoogRewarded: analysis.googRewardedAd?.present || false
    });

    if (analysis.timerElement?.id) summary.keyFindings.timerElements.add(analysis.timerElement.id);
    (analysis.visibleButtons || []).forEach(b => { if (b.id) summary.keyFindings.buttonIds.add(b.id); });
    if (analysis.adOverlay?.selector) summary.keyFindings.overlaySelectors.add(analysis.adOverlay.selector);
  }

  // Convert sets to arrays for JSON
  summary.keyFindings.timerElements = [...summary.keyFindings.timerElements];
  summary.keyFindings.buttonIds = [...summary.keyFindings.buttonIds];
  summary.keyFindings.overlaySelectors = [...summary.keyFindings.overlaySelectors];

  fs.writeFileSync(
    path.join(OUTPUT_DIR, 'summary.json'),
    JSON.stringify(summary, null, 2)
  );

  // Print summary
  console.log('\n=== ANALYSIS SUMMARY ===');
  console.log(`Total screenshots: ${summary.total}`);
  console.log(`Page types found:`);
  Object.entries(summary.byType).sort((a,b) => b[1]-a[1]).forEach(([type, count]) => {
    console.log(`  ${type}: ${count}`);
  });
  console.log(`\nKey DOM elements discovered:`);
  console.log(`  Timer IDs: ${summary.keyFindings.timerElements.join(', ')}`);
  console.log(`  Button IDs: ${summary.keyFindings.buttonIds.join(', ')}`);
  console.log(`  Overlay selectors: ${summary.keyFindings.overlaySelectors.join(', ')}`);
  
  console.log('\n=== TIMELINE ===');
  summary.timeline.forEach(t => {
    const parts = [`[${String(t.screenshot).padStart(3)}] ${t.pageType}`];
    if (t.domain) parts.push(t.domain);
    if (t.timer) parts.push(`timer:${t.timer}=${t.timerValue}`);
    if (t.templateType) parts.push(`tmpl:${t.templateType}`);
    if (t.buttons.length) parts.push(`btns:[${t.buttons.join(',')}]`);
    if (t.hasPopup) parts.push('POPUP');
    if (t.hasAdOverlay) parts.push('OVERLAY');
    if (t.hasGoogRewarded) parts.push('GOOG_REWARDED');
    console.log(parts.join(' | '));
  });
}

main().catch(err => {
  console.error('Fatal error:', err);
  process.exit(1);
});
