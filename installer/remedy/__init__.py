"""
Remedy — self-healing module for the VPLink 24/7 automation runtime.

Detects broken or missing runtime dependencies and auto-installs them
using the installer framework. Designed to be called both from within
``automation.py`` (on failure) and as a standalone CLI.
"""
import importlib
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from installer import logging as log
from installer.core.platform import detect
from installer.platforms import get_platform
from installer.packages import register_packages, is_installed
from installer.interactive import Spinner


RUNTIME_PIP_PACKAGES = {
    "selenium": "selenium",
    "flask": "flask",
    "pynacl": "pynacl",
    "requests": "requests",
    "webdriver-manager": "webdriver-manager",
}


RUNTIME_SYSTEM_TOOLS = {
    "git": "git",
    "curl": "curl",
    "wget": "wget",
}

CHROME_CANDIDATES = [
    "google-chrome-stable", "google-chrome", "google-chrome-beta",
    "chromium-browser", "chromium",
]


def _check_pip_package(name: str) -> tuple[bool, str]:
    """Check if a pip package is installed."""
    try:
        importlib.import_module(name.replace("-", "_"))
        return True, ""
    except ImportError:
        pass
    
    result = subprocess.run(
        [sys.executable, "-m", "pip", "show", name],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode == 0:
        for line in result.stdout.splitlines():
            if line.lower().startswith("version:"):
                return True, line.split(":", 1)[1].strip()
    return False, ""


def _install_pip_package(name: str) -> bool:
    """Install a pip package."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", name],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            log.success(f"Installed pip package: {name}")
            return True
        log.error(f"pip install {name}: {result.stderr[:200]}")
        return False
    except subprocess.TimeoutExpired:
        log.error(f"pip install {name} timed out")
        return False


def _check_chrome() -> tuple[bool, str]:
    """Find a working Chrome/Chromium binary."""
    env_path = Path(os.environ.get("CHROMIUM_PATH", ""))
    if env_path.is_file():
        return True, str(env_path)

    for name in CHROME_CANDIDATES:
        path = shutil.which(name)
        if path:
            return True, path

    extra = [
        "/opt/google/chrome/chrome",
        "/opt/google/chrome/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
    ]
    for path in extra:
        if Path(path).is_file():
            return True, path

    return False, ""


def _check_chromedriver() -> tuple[bool, str]:
    """Check ChromeDriver availability."""
    path = shutil.which("chromedriver")
    if path:
        return True, path

    try:
        result = subprocess.run(
            [sys.executable, "-c",
             "from webdriver_manager.chrome import ChromeDriverManager; "
             "print(ChromeDriverManager().install())"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return True, result.stdout.strip()
    except Exception:
        pass

    return False, ""


# ── Public API ─────────────────────────────────────────────────────

def check_python_deps() -> dict[str, dict]:
    """Check all runtime pip packages. Returns {name: {ok, version}}."""
    results = {}
    for name, pkg in RUNTIME_PIP_PACKAGES.items():
        ok, ver = _check_pip_package(pkg)
        results[name] = {"ok": ok, "version": ver or "", "package": pkg}
    return results


def check_system_deps() -> dict[str, dict]:
    """Check system tool dependencies."""
    register_packages()
    results = {}
    for name, pkg in RUNTIME_SYSTEM_TOOLS.items():
        ok, ver = is_installed(pkg)
        results[name] = {"ok": ok, "version": ver, "package": pkg}
    return results


def check_browser() -> dict:
    """Check browser + driver availability."""
    chrome_ok, chrome_path = _check_chrome()
    driver_ok, driver_path = _check_chromedriver()
    return {
        "chrome": {"ok": chrome_ok, "path": chrome_path},
        "chromedriver": {"ok": driver_ok, "path": driver_path},
    }


def check_all() -> dict:
    """Run all checks and return a combined report."""
    return {
        "python": check_python_deps(),
        "system": check_system_deps(),
        "browser": check_browser(),
    }


def remedy_python() -> list[str]:
    """Install all missing Python packages. Returns list of installed names."""
    log.header("Remedy: Python Packages")
    installed = []
    for name, pkg in RUNTIME_PIP_PACKAGES.items():
        ok, ver = _check_pip_package(pkg)
        if ok:
            log.success(f"{name}: {ver or 'present'}")
        else:
            with Spinner(f"Installing {name}..."):
                if _install_pip_package(pkg):
                    installed.append(name)
    return installed


def remedy_system() -> list[str]:
    """Install missing system tools. Returns list of installed names."""
    log.header("Remedy: System Tools")
    info = detect()
    platform = get_platform(info)
    register_packages()
    installed = []
    for name, pkg in RUNTIME_SYSTEM_TOOLS.items():
        ok, ver = is_installed(pkg)
        if ok:
            log.success(f"{name}: {ver or 'present'}")
        else:
            with Spinner(f"Installing {name}..."):
                result = platform.install_package(pkg)
            if result.success:
                log.success(f"{name}: {result.version or 'installed'}")
                installed.append(name)
            else:
                log.error(f"{name}: {result.error or 'failed'}")
    return installed


def remedy_browser() -> bool:
    """Attempt to fix browser/driver installation."""
    log.header("Remedy: Browser")
    chrome_ok, chrome_path = _check_chrome()
    driver_ok, driver_path = _check_chromedriver()

    fixed = False
    if chrome_ok:
        log.success(f"Chrome: {chrome_path}")
    else:
        log.warn("Chrome not found — install manually or set CHROMIUM_PATH")
        log.info("Try:  installer install")
        return False

    if driver_ok:
        log.success(f"ChromeDriver: {driver_path}")
    else:
        with Spinner("Installing ChromeDriver via webdriver-manager..."):
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "install", "--quiet", "webdriver-manager"],
                    capture_output=True, text=True, timeout=60,
                )
                if result.returncode == 0:
                    _ok, d_path = _check_chromedriver()
                    if _ok:
                        log.success(f"ChromeDriver: {d_path}")
                        fixed = True
                else:
                    log.error(f"ChromeDriver install: {result.stderr[:200]}")
            except subprocess.TimeoutExpired:
                log.error("ChromeDriver install timed out")
        if not fixed:
            return False

    return fixed


def remedy_all() -> dict:
    """Run all remedies. Returns summary of what was fixed."""
    log.header("VPLink 24/7 — Remedy")
    info = detect()
    log.info(f"Platform: {info.os_name}/{info.distribution}")
    print()

    py_fixed = remedy_python()
    sys_fixed = remedy_system()
    br_fixed = remedy_browser()

    print()
    log.header("Remedy Complete")
    total = len(py_fixed) + len(sys_fixed) + (1 if br_fixed else 0)
    if total:
        log.success(f"Fixed {total} issues")
    else:
        log.success("Everything looks good!")
    return {
        "python_fixed": py_fixed,
        "system_fixed": sys_fixed,
        "browser_fixed": br_fixed,
    }


# ── CLI ──────────────────────────────────────────────────────────────

def cli():
    """CLI entry point: python3 -m installer.remedy [check|fix]"""
    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help"):
        print("Usage: python3 -m installer.remedy <command>")
        print()
        print("Commands:")
        print("  check      Check runtime dependencies")
        print("  fix        Auto-install missing dependencies")
        print("  python     Check/fix only Python packages")
        print("  system     Check/fix only system tools")
        print("  browser    Check/fix only browser & driver")
        return

    log.init(str(Path.home() / ".config" / "vplink" / "logs"))

    cmd = args[0]
    if cmd == "check":
        report = check_all()
        print_report(report)
    elif cmd == "fix":
        remedy_all()
    elif cmd == "python":
        py = check_python_deps()
        missing = [n for n, r in py.items() if not r["ok"]]
        if missing:
            log.info(f"Missing: {', '.join(missing)}")
            remedy_python()
        else:
            log.success("All Python packages present")
    elif cmd == "system":
        sys_ = check_system_deps()
        missing = [n for n, r in sys_.items() if not r["ok"]]
        if missing:
            log.info(f"Missing: {', '.join(missing)}")
            remedy_system()
        else:
            log.success("All system tools present")
    elif cmd == "browser":
        remedy_browser()
    else:
        log.error(f"Unknown command: {cmd}")


def print_report(report: dict):
    log.header("Remedy Check Report")
    for category, items in report.items():
        print(f"  [{category}]")
        for name, info in items.items():
            ok = info.get("ok", False)
            ver = info.get("version", "") or info.get("path", "")
            status = f"✓ {ver}" if ok else "✗ missing"
            print(f"    {status:25} {name}")
        print()


if __name__ == "__main__":
    cli()
