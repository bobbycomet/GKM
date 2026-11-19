# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Bobby Comet
import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "griffin-kernel-manager"
LEGACY_CONFIG_DIR = Path.home() / ".config" / "xanmod-kernel-manager"   # XKM 3.x and earlier
CONFIG_FILE = CONFIG_DIR / "config.json"
LOG_DIR = CONFIG_DIR / "logs"
DEFAULT_CONFIG = {
    "auto_check_hours": 6,
    "auto_remove_after_install": False,
    "auto_rollback": True,
    "win_size": [1080, 680],
    "dark_mode": True,
}


def migrate_legacy_config():
    """First start after the XKM -> GKM rename: carry the user's settings over.
    Copies only; the old directory is left untouched."""
    try:
        old = LEGACY_CONFIG_DIR / "config.json"
        if old.exists() and not CONFIG_FILE.exists():
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            CONFIG_FILE.write_text(old.read_text(encoding="utf-8"), encoding="utf-8")
    except OSError:
        pass


def load_config():
    migrate_legacy_config()
    try:
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return {**DEFAULT_CONFIG, **json.load(f)}
    except Exception:
        pass
    return DEFAULT_CONFIG.copy()


def save_config(data):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
