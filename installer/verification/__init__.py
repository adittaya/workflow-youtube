"""
Verification and diagnostics module.
"""
from installer.core.platform import PlatformInfo
from installer.packages import is_installed, check_version, register_packages
from installer import logging as log


VERIFICATION_CHECKS: list[dict] = []


def register_check(name: str, package: str, min_version: str = "", critical: bool = False):
    VERIFICATION_CHECKS.append({
        "name": name, "package": package,
        "min_version": min_version, "critical": critical,
    })


def verify_single(name: str) -> dict:
    """Verify a single dependency. Returns {name, installed, version, ok, critical}."""
    check = next((c for c in VERIFICATION_CHECKS if c["name"] == name), None)
    if not check:
        pkg = check.get("package", name)
        installed, version = is_installed(pkg)
        return {"name": name, "installed": installed, "version": version,
                "ok": installed, "critical": False}

    installed, version, min_ok = check_version(check["package"], check.get("min_version"))
    return {
        "name": check["name"],
        "installed": installed,
        "version": version,
        "ok": installed and min_ok,
        "critical": check.get("critical", False),
    }


def verify_all() -> list[dict]:
    """Verify all registered dependencies."""
    register_packages()
    register_standard_checks()
    return [verify_single(c["name"]) for c in VERIFICATION_CHECKS]


def register_standard_checks():
    if not VERIFICATION_CHECKS:
        register_check("Git", "git", "2.0")
        register_check("Python3", "python3", "3.8")
        register_check("Node.js", "node", "16.0")
        register_check("npm", "npm")
        register_check("Java", "java", "11.0")
        register_check("Docker", "docker")
        register_check("Curl", "curl")
        register_check("Wget", "wget")
        register_check("Chrome", "google-chrome")
        register_check("VS Code", "code")
        register_check("Flask", "flask")
        register_check("Selenium", "selenium")


def doctor(info: PlatformInfo) -> dict:
    """Run diagnostics and return system health report."""
    register_packages()
    register_standard_checks()

    checks = verify_all()

    result = {
        "platform": {
            "os": info.os_name,
            "distribution": info.distribution,
            "arch": info.arch,
            "shell": info.shell,
            "package_manager": info.package_manager,
            "is_root": info.is_root,
            "is_wsl": info.is_wsl,
            "is_docker": info.is_docker,
        },
        "checks": checks,
        "summary": {
            "total": len(checks),
            "passed": sum(1 for c in checks if c["ok"]),
            "failed": sum(1 for c in checks if not c["ok"]),
            "critical_failed": sum(1 for c in checks if not c["ok"] and c["critical"]),
        },
    }
    return result


def print_doctor_report(report: dict):
    """Print the doctor report in a readable format."""
    p = report["platform"]
    log.header("System Information")
    log.info(f"OS: {p['os']} ({p.get('distribution', '')})")
    log.info(f"Architecture: {p['arch']}")
    log.info(f"Shell: {p['shell']}")
    log.info(f"Package Manager: {p['package_manager']}")

    if p.get("is_wsl"):
        log.info("WSL: Yes")
    if p.get("is_docker"):
        log.info("Docker: Yes (inside container)")

    log.header("Dependency Verification")
    for c in report["checks"]:
        if c["ok"]:
            log.success(f"{c['name']}: {c['version']}")
        else:
            log.error(f"{c['name']}: NOT FOUND")
            if c.get("critical"):
                log.warn(f"  → {c['name']} is CRITICAL — installation may fail")

    s = report["summary"]
    log.divider()
    log.info(f"Total: {s['total']} | Passed: {s['passed']} | Failed: {s['failed']}")
    if s["critical_failed"]:
        log.warn(f"Critical missing: {s['critical_failed']}")
