#!/usr/bin/env python3
"""One-shot OAuth — starts local server, gives URL, captures code, exchanges for tokens."""
import http.server, urllib.parse, json, os, hashlib, base64

CLIENT_ID = os.environ.get("YT_CLIENT_ID", "YOUR_CLIENT_ID_HERE")
CLIENT_SECRET = os.environ.get("YT_CLIENT_SECRET", "YOUR_CLIENT_SECRET_HERE")
SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.force-ssl https://www.googleapis.com/auth/youtube"

code_verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
code_challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).rstrip(b"=").decode()

params = {
    "client_id": CLIENT_ID,
    "redirect_uri": "http://127.0.0.1:8085",
    "response_type": "code",
    "scope": SCOPES,
    "access_type": "offline",
    "prompt": "consent",
    "code_challenge": code_challenge,
    "code_challenge_method": "S256",
}
auth_url = "https://accounts.google.com/o/oauth2/auth?" + urllib.parse.urlencode(params)

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

server = http.server.HTTPServer(("0.0.0.0", 8085), Handler)
print("Server running on port 8085", flush=True)
print(f"\nOpen this URL in your browser:\n\n{auth_url}\n", flush=True)
print("Waiting for callback (300s timeout)...\n", flush=True)

server.timeout = 300
server.handle_request()
server.server_close()

if RESULT["code"]:
    token_data = urllib.parse.urlencode({
        "code": RESULT["code"],
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": "http://127.0.0.1:8085",
        "grant_type": "authorization_code",
        "code_verifier": code_verifier,
    }).encode()

    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=token_data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        import urllib.request
        with urllib.request.urlopen(req, timeout=30) as resp:
            tokens = json.loads(resp.read())
            rt = tokens.get("refresh_token", "")
            if rt:
                print(f"\n{'='*50}")
                print(f"  SUCCESS!")
                print(f"  YT_REFRESH_TOKEN={rt}")
                print(f"{'='*50}")
            else:
                print("  No refresh token returned")
    except Exception as e:
        print(f"  Token exchange failed: {e}")
else:
    print("ERROR: no code received")
