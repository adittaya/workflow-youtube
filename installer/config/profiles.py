import os
import re
from pathlib import Path
from typing import Optional

from installer.logging.logger import get_logger

log = get_logger("config.profiles")

def get_profile_paths(shell: str, home: str) -> list[Path]:
    """Get shell profile paths for the given shell."""
    home_path = Path(home)
    profiles = {
        "bash": [home_path / ".bashrc", home_path / ".bash_profile", home_path / ".profile"],
        "zsh": [home_path / ".zshrc", home_path / ".zprofile", home_path / ".profile"],
        "fish": [home_path / ".config" / "fish" / "config.fish"],
        "powershell": [
            Path(os.environ.get("PROFILE", "")),
            Path(os.environ.get("USERPROFILE", "")) / "Documents" / "PowerShell" / "Microsoft.PowerShell_profile.ps1",
        ],
    }
    return profiles.get(shell, [home_path / ".profile"])

def ensure_marker(profile_path: Path, app_name: str = "vplink3") -> tuple[bool, str]:
    """
    Ensure a section marker exists in the profile.
    Returns (modified, section_header).
    The section uses begin/end markers:
        # >>> vplink3 begin
        ...
        # <<< vplink3 end
    """
    header = f"# >>> {app_name} begin"
    footer = f"# <<< {app_name} end"

    if not profile_path.exists():
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        profile_path.touch()

    content = profile_path.read_text(encoding="utf-8", errors="ignore")

    if header in content:
        return False, header  # Already has section

    # Append section at end
    new_content = content.rstrip() + "\n\n" + header + "\n" + footer + "\n"
    profile_path.write_text(new_content, encoding="utf-8")
    log.info(f"Added section marker to {profile_path}")
    return True, header

def add_env_var(profile_path: Path, key: str, value: str, app_name: str = "vplink3") -> bool:
    """
    Add or update an environment variable in the profile section.
    Uses the marker section to avoid duplicates.
    Returns True if modified.
    """
    header = f"# >>> {app_name} begin"
    footer = f"# <<< {app_name} end"

    if not profile_path.exists():
        return False

    content = profile_path.read_text(encoding="utf-8", errors="ignore")

    # Extract section content
    match = re.search(re.escape(header) + "(.*?)" + re.escape(footer), content, re.DOTALL)
    if not match:
        return False

    section = match.group(1)
    export_line = f'export {key}="{value}"'

    # Update existing or add new
    if re.search(re.escape(key) + r"\s*=", section):
        section = re.sub(
            re.escape(key) + r'\s*=\s*"[^"]*"',
            export_line,
            section,
        )
    else:
        section = section.rstrip() + "\n" + export_line + "\n"

    new_content = content[:match.start()] + section + content[match.end():]
    profile_path.write_text(new_content, encoding="utf-8")
    log.info(f"Updated {key}={value} in {profile_path}")
    return True

def add_path_entry(profile_path: Path, directory: str, app_name: str = "vplink3") -> bool:
    """
    Add a directory to PATH in the profile section.
    Avoids duplicates.
    """
    return add_env_var(profile_path, "PATH", f'$PATH:{directory}', app_name)

def remove_section(profile_path: Path, app_name: str = "vplink3") -> bool:
    """Remove the entire app section from a profile file."""
    header = f"# >>> {app_name} begin"
    footer = f"# <<< {app_name} end"

    if not profile_path.exists():
        return False

    content = profile_path.read_text(encoding="utf-8", errors="ignore")
    pattern = re.escape(header) + ".*?" + re.escape(footer) + r"\s*\n?"
    new_content = re.sub(pattern, "", content, flags=re.DOTALL)

    if new_content != content:
        profile_path.write_text(new_content, encoding="utf-8")
        log.info(f"Removed {app_name} section from {profile_path}")
        return True
    return False
