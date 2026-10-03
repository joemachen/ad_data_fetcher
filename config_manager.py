"""
ConfigManager: handles all JSON file I/O for config.json and per-platform *_favorites.json.
Extracted from main.py to keep file I/O concerns separate from GUI logic.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

CONFIG_DEFAULTS: Dict[str, Any] = {
    "default_google_favorite": "ML",
    "default_meta_favorite": "ML",
    "default_ms_favorite": None,
    "default_tiktok_favorite": None,
    "default_reddit_favorite": None,
    "default_pinterest_favorite": None,
    "theme_mode": "dark",
    "default_download_folder": "raw_reports",
    "default_output_folder": "processed_reports",
    "raw_reports_dir": "raw_reports",
    "processed_reports_dir": "processed_reports",
    "merged_reports_dir": "merged_reports",
    "ready_reports_dir": "ready_reports",
}

# Maps platform key -> favorites filename
PLATFORM_FAVORITES_FILES: Dict[str, str] = {
    "google":    "customer_favorites.json",
    "meta":      "meta_favorites.json",
    "ms":        "ms_favorites.json",
    "tiktok":    "tiktok_favorites.json",
    "reddit":    "reddit_favorites.json",
    "pinterest": "pinterest_favorites.json",
}


class ConfigManager:
    """Owns all JSON file I/O for config.json, and per-platform *_favorites.json files."""

    def __init__(self, app_dir: Path) -> None:
        self.app_dir = app_dir
        self.settings_file = app_dir / "config.json"
        self.logger = logging.getLogger(__name__)
        self.corrupted_msg: Optional[str] = None

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def load_settings(self) -> Dict[str, Any]:
        """Load config.json; returns merged dict over defaults. Sets self.corrupted_msg on error."""
        defaults = CONFIG_DEFAULTS.copy()
        try:
            if self.settings_file.exists():
                with open(self.settings_file, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                merged = defaults.copy()
                if isinstance(loaded, dict):
                    merged.update(loaded)
                return merged
            return defaults
        except json.JSONDecodeError as e:
            try:
                self.logger.error("config.json is corrupted (invalid JSON): %s", e, exc_info=True)
            except Exception:
                print(f"config.json is corrupted: {e}")
            self.corrupted_msg = "config.json was corrupted; using defaults. Backup or delete and restart."
            return defaults
        except OSError as e:
            try:
                self.logger.error("Error reading config.json: %s", e, exc_info=True)
            except Exception:
                print(f"Error reading config.json: {e}")
            self.corrupted_msg = "Could not read config.json; using defaults."
            return defaults

    def save_settings(self, settings: Dict[str, Any]) -> None:
        """Write settings dict to config.json with restrictive permissions."""
        try:
            with open(self.settings_file, "w", encoding="utf-8") as f:
                json.dump(settings, f, indent=2, ensure_ascii=False)
            self._restrict_permissions(self.settings_file)
            self.logger.info("Settings saved successfully")
        except Exception as e:
            self.logger.error("Error saving settings: %s", e, exc_info=True)

    # ------------------------------------------------------------------
    # Favorites
    # ------------------------------------------------------------------

    def load_favorites(self, platform_key: str) -> List[Dict[str, Any]]:
        """Load favorites list for the given platform key. Returns [] on missing or corrupt file."""
        filename = PLATFORM_FAVORITES_FILES[platform_key]
        path = self.app_dir / filename
        try:
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            return []
        except json.JSONDecodeError as e:
            self.logger.error("%s is corrupted (invalid JSON): %s", filename, e, exc_info=True)
            return []
        except OSError as e:
            self.logger.error("Error reading %s: %s", filename, e, exc_info=True)
            return []

    def save_favorites(self, platform_key: str, favorites: List[Dict[str, Any]]) -> None:
        """Write favorites list for the given platform key."""
        filename = PLATFORM_FAVORITES_FILES[platform_key]
        path = self.app_dir / filename
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(favorites, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.logger.error("Error saving %s: %s", filename, e, exc_info=True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _restrict_permissions(self, path: Path) -> None:
        """Restrict file to owner-only read/write (0o600). Best-effort; silent on Windows."""
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
