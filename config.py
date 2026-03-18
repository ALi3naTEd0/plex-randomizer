"""
Config handler for Plex Randomizer
Saves and loads configuration from local storage
"""

import json
import os
from pathlib import Path
from typing import Dict, Optional

CONFIG_FILE = "plex_config.json"

def get_config() -> Optional[Dict]:
    """Load configuration from file"""
    if not os.path.exists(CONFIG_FILE):
        return None
    
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading config: {e}")
        return None

def save_config(url: str, token: str, section_id: str) -> bool:
    """Save configuration to file"""
    try:
        config = {
            'url': url,
            'token': token,
            'section_id': section_id
        }
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)
        return True
    except Exception as e:
        print(f"Error saving config: {e}")
        return False

def delete_config() -> bool:
    """Delete configuration file"""
    try:
        if os.path.exists(CONFIG_FILE):
            os.remove(CONFIG_FILE)
        return True
    except Exception as e:
        print(f"Error deleting config: {e}")
        return False
