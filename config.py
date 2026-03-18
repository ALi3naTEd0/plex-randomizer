"""
Config handler for Plex Randomizer
Saves and loads configuration from local storage
"""

import json
import os
from pathlib import Path
from typing import Dict, Optional

CONFIG_FILE = "plex_config.json"


def _get_config_path() -> Path:
    """Return a persistent per-user config path across desktop and mobile."""
    # On Linux and Android, this usually resolves to writable app/user storage.
    xdg_config_home = os.getenv("XDG_CONFIG_HOME")
    if xdg_config_home:
        base_dir = Path(xdg_config_home)
    else:
        base_dir = Path.home() / ".config"

    return base_dir / "plex-randomizer" / CONFIG_FILE


def _get_legacy_config_path() -> Path:
    """Previous path used by older versions (current working directory)."""
    return Path(CONFIG_FILE)

def get_config() -> Optional[Dict]:
    """Load configuration from file"""
    config_path = _get_config_path()
    legacy_path = _get_legacy_config_path()

    if config_path.exists():
        try:
            with config_path.open('r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading config from {config_path}: {e}")
            return None

    # Backward compatibility: read old config location if present.
    if legacy_path.exists():
        try:
            with legacy_path.open('r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading legacy config from {legacy_path}: {e}")
            return None

    return None

def save_config(url: str, token: str, section_id: str) -> bool:
    """Save configuration to file"""
    try:
        config_path = _get_config_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)

        config = {
            'url': url,
            'token': token,
            'section_id': section_id
        }
        with config_path.open('w', encoding='utf-8') as f:
            json.dump(config, f, indent=4)
        return True
    except Exception as e:
        print(f"Error saving config: {e}")
        return False

def delete_config() -> bool:
    """Delete configuration file"""
    try:
        config_path = _get_config_path()
        legacy_path = _get_legacy_config_path()

        if config_path.exists():
            config_path.unlink()
        if legacy_path.exists():
            legacy_path.unlink()
        return True
    except Exception as e:
        print(f"Error deleting config: {e}")
        return False
