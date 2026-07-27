import json
import urllib.request
import urllib.parse
import config

PROVIDERS = {
    "vplink": {"name": "VPLink", "url": "https://vplink.in/api"},
    "cleanuri": {"name": "CleanURI", "url": "https://cleanuri.com/api/v1/shorten"},
    "tinyurl": {"name": "TinyURL", "url": "https://tinyurl.com/api-create.php"},
    "generic": {"name": "Generic", "url": ""},
}


def shorten_url(url, api_key=None, api_url=None, provider=None):
    cfg = config.load()
    tui_settings = {}
    try:
        tui_settings = config.load_tui_settings()
    except Exception:
        pass

    prov = provider or tui_settings.get("shortener_provider", "") or cfg.get("shortener_provider", "")
    key = api_key or tui_settings.get("shortener_api_key", "") or cfg.get("shortener_api_key", "") or _env("SHORTENER_API_KEY")
    api = api_url or tui_settings.get("shortener_api_url", "") or cfg.get("shortener_api_url", "") or _env("SHORTENER_API_URL")

    if prov == "vplink":
        vplink_key = key or _env("VPLINK_API_KEY")
        if not vplink_key:
            config.log("VPLink API key not configured")
            return url
        return _vplink(url, vplink_key)

    if prov == "cleanuri":
        return _cleanuri(url)

    if prov == "tinyurl":
        return _tinyurl(url)

    if prov == "generic":
        if not key or not api:
            config.log("generic shortener not configured — missing api key or url")
            return url
        return _generic_short(url, api, key)

    if not key or not api:
        config.log("shortener not configured — using original URL")
        return url

    if "cleanuri" in api.lower():
        return _cleanuri(url)
    if "tinyurl" in api.lower():
        return _tinyurl(url)
    if "vplink" in api.lower():
        return _vplink(url, key)
    return _generic_short(url, api, key)


def _vplink(url, api_key):
    params = urllib.parse.urlencode({"api": api_key, "url": url, "format": "json"})
    full_url = f"https://vplink.in/api?{params}"
    req = urllib.request.Request(full_url)
    req.add_header("User-Agent", "YT-Mirror/1.0")
    with urllib.request.urlopen(req, timeout=10) as resp:
        result = json.loads(resp.read())
        if result.get("status") == "success":
            short = result.get("shortenedUrl", "")
            if short:
                config.log(f"shortened: {url[:50]} -> {short}")
                return short
        else:
            msg = result.get("message", "unknown error")
            config.log(f"VPLink error: {msg}")
    return url


def _cleanuri(url):
    data = json.dumps({"url": url}).encode("utf-8")
    req = urllib.request.Request(
        "https://cleanuri.com/api/v1/shorten",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        result = json.loads(resp.read())
        short = result.get("result_url") or result.get("result")
        if short:
            config.log(f"shortened: {url[:50]} -> {short}")
            return short
    return url


def _tinyurl(url):
    full_url = f"https://tinyurl.com/api-create.php?url={urllib.parse.quote(url, safe='')}"
    req = urllib.request.Request(full_url)
    with urllib.request.urlopen(req, timeout=10) as resp:
        short = resp.read().decode().strip()
        if short.startswith("http"):
            config.log(f"shortened: {url[:50]} -> {short}")
            return short
    return url


def _generic_short(url, api_url, api_key):
    params = urllib.parse.urlencode({"url": url, "key": api_key})
    full_url = f"{api_url}?{params}"
    req = urllib.request.Request(full_url)
    with urllib.request.urlopen(req, timeout=10) as resp:
        result = json.loads(resp.read())
        short = (result.get("short_url") or result.get("shortened") or
                 result.get("shortUrl") or result.get("result_url") or result.get("link"))
        if short:
            config.log(f"shortened: {url[:50]} -> {short}")
            return short
    return url


def _env(key):
    import os
    return os.environ.get(key, "")


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python3 shortener.py <url> [provider]")
        sys.exit(1)
    prov = sys.argv[2] if len(sys.argv) > 2 else None
    result = shorten_url(sys.argv[1], provider=prov)
    print(result)
