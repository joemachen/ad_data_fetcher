"""
Central source of truth for the application directory.

When running as a PyInstaller --onedir bundle, __file__ resolves to the
_internal/ subdirectory, not the directory containing the executable.
This module always returns the directory containing the executable so that
user-editable config files (*.yaml, config.json, *.json) can be found
alongside the .exe in both source and bundled modes.

Usage in any module:
    from _app_dir import APP_DIR as _APP_DIR
"""

import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    # Running as a compiled PyInstaller executable.
    # sys.executable is the path to the .exe; its parent is where the
    # user places their YAML credentials and config files.
    APP_DIR: Path = Path(sys.executable).resolve().parent
else:
    # Running from source — same directory as this file.
    APP_DIR = Path(__file__).resolve().parent
