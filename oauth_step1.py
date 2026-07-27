#!/usr/bin/env python3
"""OAuth via localhost — code appears in browser address bar."""
import urllib.parse, json, hashlib, base64, os, secrets

CLIENT_ID = os.environ.get("YT_CLIENT_ID", "YOUR_CLIENT_ID_HERE")
CLIENT_SECRET = os.environ.get("YT_CLIENT_SECRET", "YOUR_CLIENT_SECRET_HERE")
SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.force-ssl https://www.googleapis.com/auth/youtube"

code_verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
code_challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).rstrip(b"=").decode()

with open("/tmp/oauth_pkce.json", "w") as f:
    json.dump({"verifier": code_verifier}, f)

params = {
    "client_id": CLIENT_ID,
    "redirect_uri": "http://localhost:8085",
    "response_type": "code",
    "scope": SCOPES,
    "access_type": "offline",
    "prompt": "consent",
    "code_challenge": code_challenge,
    "code_challenge_method": "S256",
}

print("Open this URL in your browser:\n")
print("https://accounts.google.com/o/oauth2/auth?" + urllib.parse.urlencode(params))
print("\nAfter approving, the page will show an error — that's NORMAL.")
print("Look at your BROWSER ADDRESS BAR, it will look like:")
print("  http://localhost:8085/?state=...&code=4/0A...XXXXX...")
print("\nCopy the FULL URL from the address bar and paste it here.\n")
