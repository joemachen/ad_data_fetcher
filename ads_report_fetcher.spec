# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for Ads Report Fetcher.
# Build with:  pyinstaller ads_report_fetcher.spec
# Output:      dist/AdsReportFetcher/   (one-dir bundle; zip for distribution)
#
# Users must place their *.yaml credential files in the same folder as
# AdsReportFetcher.exe before running the application.
#
from PyInstaller.utils.hooks import collect_data_files, collect_all

block_cipher = None

# --------------------------------------------------------------------------- #
# Data files: packages that ship non-Python assets PyInstaller won't auto-find
# --------------------------------------------------------------------------- #
datas = []
datas += collect_data_files("customtkinter")   # JSON themes, images
datas += collect_data_files("babel")           # locale data (used by tkcalendar)
datas += collect_data_files("tkcalendar")
datas += collect_data_files("bingads")         # WSDL service descriptions
datas += collect_data_files("google.ads")      # proto/resource files
datas += collect_data_files("facebook_business")

# mappings.json must be findable next to the exe at runtime (via _app_dir.py);
# include the source copy so PyInstaller stages it into the bundle root.
# Users can override it by placing their own mappings.json next to the exe.
import os
_root = os.path.dirname(os.path.abspath(SPEC))
_mappings = os.path.join(_root, "mappings.json")
if os.path.exists(_mappings):
    datas += [(_mappings, ".")]

# --------------------------------------------------------------------------- #
# Hidden imports: modules PyInstaller's static analysis misses
# --------------------------------------------------------------------------- #
hiddenimports = [
    # tkinter
    "tkinter",
    "tkinter.filedialog",
    "tkinter.messagebox",
    "tkinter.scrolledtext",
    "tkcalendar",
    # Google Ads SDK — uses dynamic proto loading
    "google.ads.googleads",
    "google.ads.googleads.client",
    "google.auth",
    "google.auth.transport.requests",
    "google_auth_oauthlib.flow",
    # Meta / Facebook Business SDK
    "facebook_business",
    "facebook_business.api",
    "facebook_business.adobjects.adaccount",
    "facebook_business.adobjects.adsinsights",
    "facebook_business.exceptions",
    # Microsoft Bing Ads SDK
    "bingads",
    "bingads.authorization",
    "bingads.v13.reporting.reporting_service_manager",
    "bingads.v13.reporting.reporting_download_parameters",
    # Other
    "yaml",
    "dateutil",
    "dateutil.relativedelta",
    "pandas",
    "babel",
    "babel.numbers",
]

# --------------------------------------------------------------------------- #
# Analysis
# --------------------------------------------------------------------------- #
a = Analysis(
    ["main.py"],
    pathex=[_root],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Dev / test dependencies — not needed at runtime
        "pytest",
        "unittest",
        "setuptools",
        "pip",
        # Setup scripts — users run these from source, not from the bundle
        "setup_auth",
        "setup_meta_auth",
        "setup_ms_auth",
        "setup_reddit_auth",
        "setup_tiktok_auth",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AdsReportFetcher",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,           # GUI app — no terminal window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon="assets/icon.ico",  # Uncomment and add icon.ico to enable a custom icon
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="AdsReportFetcher",
)
