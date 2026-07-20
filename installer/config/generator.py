import json
import os
import uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from installer.platforms import detect_platform, PlatformInfo
from installer.logging.logger import get_logger

log = get_logger("config.generator")

def generate_default_config(platform_info: Optional[PlatformInfo] = None) -> dict:
    """Generate the default installer configuration."""
    if platform_info is None:
        platform_info = detect_platform()

    return {
        "version": "3.0.0",
        "installation_id": str(uuid.uuid4()),
        "install_timestamp": datetime.now(timezone.utc).isoformat(),
        "platform": {
            "system": platform_info.name,
            "distribution": platform_info.distribution,
            "version": platform_info.version,
            "arch": platform_info.arch,
        },
        "settings": {
            "proxy_enabled": True,
            "proxy_tier": "premium",
            "youtube_traffic": True,
            "mobile_profile": True,
            "views": 100,
        },
        "credentials": {
            "supabase_url": "",
            "supabase_key": "",
            "supabase_secret": "",
        },
        "paths": {
            "config_dir": platform_info.config_dir,
            "data_dir": platform_info.data_dir,
            "cache_dir": platform_info.cache_dir,
        },
    }

def write_default_config(config_dir: Optional[str] = None) -> str:
    """Write default config to disk. Returns path to config file."""
    if config_dir is None:
        config_dir = str(Path.home() / ".config" / "vplink3")

    config_path = Path(config_dir) / "installer.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)

    config = generate_default_config()
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    log.info(f"Default config written to {config_path}")
    return str(config_path)
