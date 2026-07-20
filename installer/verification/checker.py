from dataclasses import dataclass, field
from typing import Optional
from installer.core.executor import check_command, run_command, get_command_path
from installer.logging.logger import get_logger
from installer.packages.definitions import PackageDef, PACKAGES

log = get_logger("verification")

@dataclass
class CheckResult:
    package: str
    display_name: str
    installed: bool
    version: Optional[str] = None
    path: Optional[str] = None
    error: Optional[str] = None

class Verifier:
    def check_package(self, pkg: PackageDef) -> CheckResult:
        path = None
        version = None
        installed = False

        if pkg.binary_check:
            path = get_command_path(pkg.binary_check)
            if path:
                installed = True
                if pkg.version_flag:
                    result = run_command([pkg.binary_check, pkg.version_flag], capture=True, timeout=10)
                    if result.success:
                        version = result.stdout.strip().split("\n")[0]

        # Fallback: on apt systems, accept Google Chrome as equivalent to Chromium Browser
        if not installed and pkg.name == "chromium-browser":
            for alt in ("google-chrome-stable", "google-chrome", "google-chrome-beta"):
                alt_path = get_command_path(alt)
                if alt_path:
                    path = alt_path
                    installed = True
                    result = run_command([alt, "--version"], capture=True, timeout=10)
                    if result.success:
                        version = result.stdout.strip().split("\n")[0]
                    break

        return CheckResult(
            package=pkg.name,
            display_name=pkg.display_name,
            installed=installed,
            version=version,
            path=path,
        )

    def check_all(self) -> list[CheckResult]:
        return [self.check_package(pkg) for pkg in PACKAGES]

    def check_category(self, category: str) -> list[CheckResult]:
        from installer.packages.definitions import get_packages_by_category
        return [self.check_package(pkg) for pkg in get_packages_by_category(category)]

    def summary(self, results: list[CheckResult]) -> dict:
        installed = sum(1 for r in results if r.installed)
        missing = sum(1 for r in results if not r.installed)
        return {
            "total": len(results),
            "installed": installed,
            "missing": missing,
            "all_ok": missing == 0,
        }

    def print_report(self, results: list[CheckResult]):
        from installer.interactive.ui import colored, Color, heading

        heading("Verification Report")

        for r in results:
            status_icon = colored("✓", Color.GREEN) if r.installed else colored("✗", Color.RED)
            name = colored(r.display_name, Color.BOLD)
            version_str = f" v{r.version}" if r.version else ""
            path_str = colored(f" ({r.path})", Color.DIM) if r.path else ""
            print(f"  {status_icon} {name}{version_str}{path_str}")

        summary = self.summary(results)
        print()
        if summary["all_ok"]:
            print(colored(f"  All {summary['total']} packages installed ✓", Color.GREEN))
        else:
            print(colored(f"  {summary['installed']}/{summary['total']} installed", Color.YELLOW))
            print(colored(f"  {summary['missing']} package(s) missing", Color.RED))
