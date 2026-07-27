#!/usr/bin/env python3
"""One-shot OAuth — starts tunnel, gives URL, captures code, exchanges for tokens."""
import http.server, urllib.parse, json, sys, os, hashlib, base64, secrets, subprocess, re, time, threading

CLIENT_ID = os.environ.get("YT_CLIENT_ID", "YOUR_CLIENT_ID_HERE")
CLIENT_SECRET = os.environ.get("YT_CLIENT_SECRET", "YOUR_CLIENT_SECRET_HERE")
SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.force-ssl https://www.googleapis.com/auth/youtube"
REDIRECT_PORT = 8085

# PKCE
code_verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
code_challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).rstrip(b"=").decode()
state = secrets.token_hex(16)

# Start cloudflared tunnel
print("[1/4] Starting tunnel...", flush=True)
proc = subprocess.Popen(
    ["cloudflared", "tunnel", "--url", f"http://localhost:{REDIRECT_PORT}"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
)
tunnel_url = None
start = time.time()
while time.time() - start < 20:
    line = proc.stdout.readline()
    if not line:
        break
    m = re.search(r"(https://[a-z0-9-]+\.trycloudflare\.com)", line)
    if m:
        tunnel_url = m.group(1)
        break

if not tunnel_url:
    print("ERROR: tunnel failed")
    proc.kill()
    sys.exit(1)

print(f"  Tunnel: {tunnel_url}", flush=True)

# Build auth URL
params = {
    "client_id": CLIENT_ID,
    "redirect_uri": tunnel_url,
    "response_type": "code",
    "scope": SCOPES,
    "access_type": "offline",
    "prompt": "consent",
    "state": state,
    "code_challenge": code_challenge,
    "code_challenge_method": "S256",
}
auth_url = "https://accounts.google.com/o/oauth2/auth?" + urllib.parse.urlencode(params)

print(f"\n[2/4] Open this URL in your browser:\n")
print(auth_url)
print(f"\n[3/4] Waiting for Google callback...\n", flush=True)

# Start local server
RESULT = {"code": None}

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        code = params.get("code", [None])[0]
        if code:
            RESULT["code"] = code
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body><h2>Done! Close this tab.</h2></body></html>")
        else:
            self.send_response(400)
            self.end_headers()
    def log_message(self, format, *args):
        pass

server = http.server.HTTPServer(("127.0.0.1", REDIRECT_PORT), Handler)
server.timeout = 300
server.handle_request()
server.server_close()

if not RESULT["code"]:
    print("ERROR: no code received")
    proc.kill()
    sys.exit(1)

print(f"  Got code!", flush=True)

# Exchange code for tokens
print("[4/4] Exchanging code for tokens...", flush=True)
token_data = urllib.parse.urlencode({
    "code": RESULT["code"],
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "redirect_uri": tunnel_url,
    "grant_type": "authorization_code",
    "code_verifier": code_verifier,
}).encode()

req = urllib.request.Request("https://oauth2.googleapis.com/token", data=token_data, method="POST")
req.add_header("Content-Type", "application/x-www-form-urlencoded")
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        tokens = json.loads(resp.read())
        refresh_token = tokens.get("refresh_token", "")
        if refresh_token:
            print(f"\n{'='*60}")
            print(f"  SUCCESS! Your refresh token:")
            print(f"{'='*60}")
            print(f"  YT_REFRESH_TOKEN={refresh_token}")
            print(f"{'='*60}")
            # Save to config
            import config
            config.save({"yt_client_id": CLIENT_ID, "yt_client_secret": CLIENT_SECRET, "yt_refresh_token": refresh_token})
            print(f"\n  Saved to ~/.yt-mirror/config.json")
        else:
            print("  No refresh token returned — try again with prompt=consent")
except Exception as e:
    print(f"  Token exchange failed: {e}")

proc.kill()
