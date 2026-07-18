const fs = require('fs');
const path = require('path');
const os = require('os');

const CONFIG_DIR = path.join(os.homedir(), '.vplink3.0');
const CONFIG_PATH = path.join(CONFIG_DIR, 'config.json');
const PROXY_HISTORY_PATH = path.join(CONFIG_DIR, 'proxy_history.json');
const PROXY_BLACKLIST_PATH = path.join(CONFIG_DIR, 'proxy_blacklist.json');

const DEFAULTS = {
  supabase_url: '',
  supabase_key: '',
  supabase_secret: '',
  proxy_enabled: false,
  proxy_tier: 'premium',
  youtube_traffic: false,
  mobile_profile: false,
  random_urls: [],
  vnc_port: 5900,
  views: 1,
};

function ensureDir() {
  if (!fs.existsSync(CONFIG_DIR)) {
    fs.mkdirSync(CONFIG_DIR, { recursive: true, mode: 0o700 });
  }
  // Config files may contain credentials. Tighten an existing directory too.
  try { fs.chmodSync(CONFIG_DIR, 0o700); } catch {}
}

function writeJsonSecurely(filePath, value) {
  ensureDir();
  const tempPath = `${filePath}.${process.pid}.${Date.now()}.tmp`;
  try {
    fs.writeFileSync(tempPath, JSON.stringify(value, null, 2), { encoding: 'utf8', mode: 0o600 });
    fs.renameSync(tempPath, filePath);
    try { fs.chmodSync(filePath, 0o600); } catch {}
  } catch (error) {
    try { fs.unlinkSync(tempPath); } catch {}
    throw error;
  }
}

function load() {
  ensureDir();
  try {
    const raw = fs.readFileSync(CONFIG_PATH, 'utf8');
    return { ...DEFAULTS, ...JSON.parse(raw) };
  } catch {
    return { ...DEFAULTS };
  }
}

function save(config) {
  const existing = load();
  const merged = { ...existing, ...config };
  writeJsonSecurely(CONFIG_PATH, merged);
  return merged;
}

function loadProxyHistory() {
  try {
    const raw = fs.readFileSync(PROXY_HISTORY_PATH, 'utf8');
    return JSON.parse(raw);
  } catch {
    return { used: [] };
  }
}

function saveProxyHistory(history) {
  writeJsonSecurely(PROXY_HISTORY_PATH, history);
}

function loadProxyBlacklist() {
  try {
    if (fs.existsSync(PROXY_BLACKLIST_PATH)) {
      return JSON.parse(fs.readFileSync(PROXY_BLACKLIST_PATH, 'utf8'));
    }
  } catch {}
  return [];
}

function saveProxyBlacklist(list) {
  writeJsonSecurely(PROXY_BLACKLIST_PATH, list);
}

function addProxyBlacklist(ip, port) {
  const list = loadProxyBlacklist();
  const key = `${ip}:${port}`;
  if (!list.includes(key)) {
    list.push(key);
    saveProxyBlacklist(list);
  }
}

function clearProxyBlacklist() {
  saveProxyBlacklist([]);
}

function isConfigured() {
  const cfg = load();
  return !!(cfg.supabase_url && cfg.supabase_key && cfg.supabase_secret);
}

// CLI mode: node config.js --get <key> or --set <key> <value> or --setup
if (require.main === module) {
  const args = process.argv.slice(2);
  if (args[0] === '--get') {
    const cfg = load();
    console.log(cfg[args[1]] !== undefined ? cfg[args[1]] : '');
  } else if (args[0] === '--set') {
    const key = args[1];
    let val = args.slice(2).join(' ');
    if (val === 'true') val = true;
    else if (val === 'false') val = false;
    else if (!isNaN(val) && val !== '') val = Number(val);
    save({ [key]: val });
  } else if (args[0] === '--check') {
    console.log(isConfigured() ? 'configured' : 'unconfigured');
  } else if (args[0] === '--setup') {
    interactiveSetup();
  } else if (args.length === 0) {
    const cfg = load();
    if (process.stdin.isTTY) {
      interactiveMenu(cfg);
    } else {
      console.log(JSON.stringify(cfg, null, 2));
    }
  }
}

function interactiveSetup() {
  const readline = require('readline');
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  const cfg = load();

  console.log('');
  console.log('\x1b[1m╔══════════════════════════════════════════════════════════╗\x1b[0m');
  console.log('\x1b[1m║        VPLink 3.0 — Database Credential Setup          ║\x1b[0m');
  console.log('\x1b[1m╚══════════════════════════════════════════════════════════╝\x1b[0m');
  console.log('');
  console.log('  Credentials are stored in ~/.vplink3.0/config.json');
  console.log('  Press Enter to keep current value (shown in brackets).');
  console.log('');

  const ask = (prompt, current) => {
    return new Promise(resolve => {
      const display = current ? ` [${current.slice(0, 20)}${current.length > 20 ? '...' : ''}]` : ' [empty]';
      rl.question(`  \x1b[1m${prompt}:\x1b[0m${display} `, answer => {
        resolve(answer.trim() || current || '');
      });
    });
  };

  (async () => {
    const supabase_url = await ask('Supabase URL', cfg.supabase_url);
    const supabase_key = await ask('Supabase Publishable Key', cfg.supabase_key);
    const supabase_secret = await ask('Supabase Secret Key', cfg.supabase_secret);
    const proxy_enabled = await ask('Enable proxy? (true/false)', String(cfg.proxy_enabled));
    const proxy_tier = await ask('Proxy tier (free/premium)', cfg.proxy_tier);

    save({
      supabase_url,
      supabase_key,
      supabase_secret,
      proxy_enabled: proxy_enabled === 'true',
      proxy_tier,
    });

    console.log('');
    if (supabase_url && supabase_key && supabase_secret) {
      console.log('  \x1b[32m✓\x1b[0m \x1b[1mCredentials saved successfully!\x1b[0m');
      console.log('  \x1b[32m✓\x1b[0m Proxy: ' + (proxy_enabled === 'true' ? `enabled (${proxy_tier})` : 'disabled'));
    } else {
      console.log('  \x1b[33m⚠\x1b[0m Partial config — proxy features will be limited');
      console.log('  Run \x1b[1mvplink3.0 config\x1b[0m again to update.');
    }
    console.log('');
    rl.close();
  })();
}

function interactiveMenu(cfg) {
  const readline = require('readline');
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });

  const configured = isConfigured();
  const status = configured ? '\x1b[32m✓ Configured\x1b[0m' : '\x1b[33m✗ Not configured\x1b[0m';

  console.log('');
  console.log('\x1b[1m╔══════════════════════════════════════════════════════════╗\x1b[0m');
  console.log('\x1b[1m║           VPLink 3.0 — Configuration                   ║\x1b[0m');
  console.log('\x1b[1m╚══════════════════════════════════════════════════════════╝\x1b[0m');
  console.log('');
  console.log(`  Status: ${status}`);
  if (cfg.supabase_url) {
    console.log(`  Supabase URL: ${cfg.supabase_url.slice(0, 40)}...`);
  }
  console.log(`  Proxy: ${cfg.proxy_enabled ? `enabled (${cfg.proxy_tier})` : 'disabled'}`);
  console.log(`  Views: ${cfg.views}`);
  console.log('');
  console.log('  Commands:');
  console.log('    \x1b[1mvplink3.0 config --setup\x1b[0m   Interactive credential setup');
  console.log('    \x1b[1mvplink3.0 config --set\x1b[0m <k> <v>  Set a value');
  console.log('    \x1b[1mvplink3.0 config --get\x1b[0m <k>     Get a value');
  console.log('    \x1b[1mvplink3.0 config --check\x1b[0m      Check if configured');
  console.log('');
  rl.close();
}

module.exports = { load, save, loadProxyHistory, saveProxyHistory, loadProxyBlacklist, saveProxyBlacklist, addProxyBlacklist, clearProxyBlacklist, isConfigured };
