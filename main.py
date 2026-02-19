"""
Ads Report Fetcher - GUI Entry Point
Main window for the desktop application (Multi-Platform).
"""

import customtkinter as ctk
import logging
import os
import queue
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from dateutil.relativedelta import relativedelta
from typing import Optional, Tuple, List, Dict
import tkinter as tk
import tkinter.filedialog as filedialog
import tkinter.scrolledtext as scrolledtext
import tkinter.messagebox as messagebox
try:
    from tkcalendar import Calendar
except ImportError:
    Calendar = None  # optional: fallback to dropdowns if not installed
import json
import urllib.error
import urllib.parse
import urllib.request
import yaml
from api_fetcher import AdsApiFetcher
from meta_fetcher import MetaAdsFetcher, MetaTokenExpiredError
from microsoft_fetcher import MicrosoftAdsFetcher
from reddit_fetcher import RedditAdsFetcher
from processor import ReportProcessor
from constants import PIPELINE_FETCH_WAIT_SECONDS, DIALOG_WAIT_SECONDS

# Directory containing main.py; config and credentials live here so paths don't depend on CWD
_APP_DIR = Path(__file__).resolve().parent
__version__ = "1.0.0"

# Uniform width for all platform ID/account input fields (combobox)
ID_FIELD_WIDTH = 400

# Meta Ads API only supports data for the last 37 months (Error 3018 for older data)
META_RETENTION_MONTHS = 37


def _parse_id_from_favorite_display(display: str) -> str:
    """Extract ID from combobox display string 'Name (ID)' or return as-is if no parens."""
    if not display or not isinstance(display, str):
        return (display or "").strip()
    s = display.strip()
    if " (" in s and s.endswith(")"):
        return s[s.rindex(" (") + 2:-1].strip()
    return s


def _mask_id_for_log(id_str: str, tail: int = 4) -> str:
    """Return a safe string for logging (e.g. ...1234). Never log full IDs or tokens."""
    if not id_str or not isinstance(id_str, str):
        return "***"
    s = id_str.strip()
    if len(s) <= tail:
        return "***"
    return "..." + s[-tail:]


class AdsReportFetcherApp:
    """Main GUI application class."""
    
    def __init__(self):
        """Initialize the GUI application."""
        # Setup logging first (rotate at 2 MB, keep 3 backups)
        from logging.handlers import RotatingFileHandler
        log_path = _APP_DIR / "app_debug.log"
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %I:%M:%S %p',
            handlers=[RotatingFileHandler(log_path, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8")]
        )
        self.logger = logging.getLogger(__name__)
        
        # Config and favorites under app dir so behavior doesn't depend on CWD
        self.settings_file = _APP_DIR / "config.json"
        self.settings = self._load_settings()
        theme_mode = self.settings.get("theme_mode", "dark")
        ctk.set_appearance_mode(theme_mode)
        ctk.set_default_color_theme("blue")
        
        # Create main window: default size fits header + both rows of platform cards + Live Log (no cutoff)
        self.root = ctk.CTk()
        self.root.title(f"Ads Report Fetcher (Multi-Platform) v{__version__}")
        self.root.geometry("960x1150")
        self.root.resizable(True, True)
        # Min width: 3 cards (~240px each) + padx + scrollbar; min height: both card rows + log
        _min_w = 900
        _min_h = 850
        self.root.minsize(_min_w, _min_h)
        
        # Month names for dropdowns
        self.month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", 
                           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        
        # Variables - default to previous month
        now = datetime.now()
        if now.month == 1:
            # If current month is January, previous month is December of previous year
            prev_month = 12
            prev_year = now.year - 1
        else:
            prev_month = now.month - 1
            prev_year = now.year
        
        self.start_year = ctk.StringVar(value=str(prev_year))
        self.start_month = ctk.StringVar(value=self.month_names[prev_month - 1])
        self.end_year = ctk.StringVar(value=str(prev_year))
        self.end_month = ctk.StringVar(value=self.month_names[prev_month - 1])
        self.customer_id = ctk.StringVar(value="")
        self.meta_account_id = ctk.StringVar(value="act_")
        self.ms_customer_id = ctk.StringVar(value="")
        self.tiktok_account_id = ctk.StringVar(value="")
        self.reddit_account_id = ctk.StringVar(value="")
        self.pinterest_account_id = ctk.StringVar(value="")
        # Display vars for ID comboboxes (show "Name (ID)" or raw ID)
        self.google_id_display = ctk.StringVar(value="")
        self.meta_id_display = ctk.StringVar(value="")
        self.ms_id_display = ctk.StringVar(value="")
        self.tiktok_id_display = ctk.StringVar(value="")
        self.reddit_id_display = ctk.StringVar(value="")
        self.pinterest_id_display = ctk.StringVar(value="")
        self.meta_token_input = ctk.StringVar(value="")
        self.status_text = ctk.StringVar(value="Ready")
        if getattr(self, "_config_corrupted_msg", None):
            self.status_text.set(self._config_corrupted_msg)
        self.is_processing = False
        self.meta_is_processing = False
        self.batch_fetch_active = False
        self.cancel_event = threading.Event()
        self.meta_cancel_event = threading.Event()
        self.google_fetch_complete = threading.Event()
        self.meta_fetch_complete = threading.Event()
        self.ms_fetch_complete = threading.Event()
        self.tiktok_fetch_complete = threading.Event()
        self.reddit_fetch_complete = threading.Event()
        self.pinterest_fetch_complete = threading.Event()
        self.meta_token_updated = threading.Event()
        self.date_range_locked = False
        self.meta_date_range_locked = False
        # Note: output_dir is no longer used - each platform has its own directory
        
        # Favorites (Google Ads)
        self.favorites_file = _APP_DIR / "customer_favorites.json"
        self.favorites: List[Dict[str, str]] = []
        self._load_favorites()
        
        # Meta Ads Favorites
        self.meta_favorites_file = _APP_DIR / "meta_favorites.json"
        self.meta_favorites: List[Dict[str, str]] = []
        self._load_meta_favorites()
        # Microsoft, TikTok, Reddit, Pinterest Favorites
        self.ms_favorites_file = _APP_DIR / "ms_favorites.json"
        self.ms_favorites: List[Dict[str, str]] = []
        self._load_ms_favorites()
        self.tiktok_favorites_file = _APP_DIR / "tiktok_favorites.json"
        self.tiktok_favorites: List[Dict[str, str]] = []
        self._load_tiktok_favorites()
        self.reddit_favorites_file = _APP_DIR / "reddit_favorites.json"
        self.reddit_favorites: List[Dict[str, str]] = []
        self._load_reddit_favorites()
        self.pinterest_favorites_file = _APP_DIR / "pinterest_favorites.json"
        self.pinterest_favorites: List[Dict[str, str]] = []
        self._load_pinterest_favorites()
        
        # Create widgets
        self._create_widgets()
        
        # Thread-safe log queue so worker threads never touch Tk (avoids deadlock)
        self._log_queue = queue.Queue()
        # Start logging handler for GUI
        self._setup_gui_logging()
        
        # Handle window close event to clear log
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)
    
    def _on_closing(self) -> None:
        """Handle window close event - clear log and destroy window."""
        try:
            # Clear the log textbox
            if hasattr(self, 'log_textbox'):
                self.log_textbox.delete("1.0", "end")
        except Exception as e:
            self.logger.error(f"Error clearing log on exit: {e}", exc_info=True)
        finally:
            # Destroy the window
            self.root.destroy()
    
    def _setup_gui_logging(self) -> None:
        """Setup logging to also output to the GUI log box. Handler only enqueues; main thread drains (avoids Tk deadlock from worker threads)."""
        class GUILogHandler(logging.Handler):
            def __init__(self, log_queue):
                super().__init__()
                self.log_queue = log_queue

            def emit(self, record):
                try:
                    msg = self.format(record)
                    self.log_queue.put_nowait(msg)
                except Exception:
                    self.handleError(record)

        gui_handler = GUILogHandler(self._log_queue)
        gui_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %I:%M:%S %p'))
        gui_handler.setLevel(logging.INFO)
        logging.getLogger().addHandler(gui_handler)
        self.root.after(100, self._drain_log_queue)

    def _drain_log_queue(self) -> None:
        """Run on main thread only: drain log queue and append to Live Log. Reschedule to keep draining."""
        try:
            while True:
                msg = self._log_queue.get_nowait()
                self.log_textbox.insert("end", msg + "\n")
                self.log_textbox.see("end")
        except queue.Empty:
            pass
        self.root.after(100, self._drain_log_queue)
    
    def _create_widgets(self) -> None:
        """Create and layout all GUI widgets. Live Log pinned at bottom (grid row 1); content fills rest (grid row 0)."""
        # Content area (will go in grid row 0, weight=1)
        content_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        content_frame.grid(row=0, column=0, sticky="nsew")
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_columnconfigure(0, weight=1)
        content_frame.grid_rowconfigure(3, weight=1)
        content_frame.grid_columnconfigure(0, weight=1)

        # Title
        title_label = ctk.CTkLabel(
            content_frame,
            text="Ads Report Fetcher",
            font=ctk.CTkFont(size=24, weight="bold")
        )
        title_label.grid(row=0, column=0, pady=15)

        # Header: single horizontal bar, 4 buttons, uniform padding
        header_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
        header_frame.grid(row=1, column=0, pady=(0, 10), sticky="ew")
        btn_h, btn_w = 36, 165
        pad = 10
        self.new_fetch_button = ctk.CTkButton(
            header_frame, text="New Fetch", command=self._on_new_fetch_clicked,
            font=ctk.CTkFont(size=13, weight="bold"), height=btn_h, width=btn_w,
            fg_color="green", hover_color="darkgreen", state="disabled"
        )
        self.new_fetch_button.pack(side="left", padx=pad)
        self.run_full_pipeline_button = ctk.CTkButton(
            header_frame, text="Run Fetch", command=self._on_run_all_clicked,
            font=ctk.CTkFont(size=13, weight="bold"), height=btn_h, width=btn_w,
            fg_color="#0066CC", hover_color="#0052A3"
        )
        self.run_full_pipeline_button.pack(side="left", padx=pad)
        self.process_all_data_button = ctk.CTkButton(
            header_frame, text="Process All Data", command=self._on_process_all_data_clicked,
            font=ctk.CTkFont(size=13, weight="bold"), height=btn_h, width=btn_w,
            fg_color="orange", hover_color="darkorange", border_width=2, border_color="#FF8C00", corner_radius=8
        )
        self.process_all_data_button.pack(side="left", padx=pad)
        self.clear_data_button = ctk.CTkButton(
            header_frame, text="☢ Clear All Data ☢", command=self._on_clear_data_clicked,
            font=ctk.CTkFont(size=13, weight="bold"), height=btn_h, width=btn_w,
            fg_color="#8B0000", hover_color="#A00000", border_width=2, border_color="#FF4500", corner_radius=8
        )
        self.clear_data_button.pack(side="left", padx=pad)
        # Data guardrail: show data presence next to Clear All Data
        self.data_status_label = ctk.CTkLabel(
            header_frame, text="✓ No existing data", font=ctk.CTkFont(size=11), text_color="#90EE90"
        )
        self.data_status_label.pack(side="left", padx=(pad, 0))

        # Status message and progress bar directly beneath header (visible during pipeline run)
        header_status_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
        header_status_frame.grid(row=2, column=0, pady=(0, 4), padx=20, sticky="ew")
        content_frame.columnconfigure(0, weight=1)
        # Global status label (token save, errors, etc.) - so messages are visible from any tab
        ctk.CTkLabel(header_status_frame, text="Status:", font=ctk.CTkFont(size=10), text_color="#A0A0A0").pack(side="left", padx=(0, 6))
        self.global_status_label = ctk.CTkLabel(
            header_status_frame, textvariable=self.status_text, font=ctk.CTkFont(size=10), text_color="#C0C0C0"
        )
        self.global_status_label.pack(side="left", padx=0, fill="x", expand=True)
        self.pipeline_status_label = ctk.CTkLabel(
            header_status_frame, text="", font=ctk.CTkFont(size=10), text_color="#A0A0A0"
        )
        self.pipeline_status_label.pack(side="left", padx=(15, 0))
        self.pipeline_progress_frame = ctk.CTkFrame(header_status_frame, fg_color="transparent")
        self.pipeline_progress_bar = ctk.CTkProgressBar(self.pipeline_progress_frame, width=200)
        self.pipeline_progress_bar.pack(side="left", padx=(10, 0))
        self.pipeline_progress_bar.set(0)
        self.pipeline_progress_bar.configure(progress_color="#0066CC", fg_color="#2B2B2B")
        self.pipeline_progress_frame.pack(side="left")
        self.pipeline_progress_frame.pack_forget()

        # Tabview: wide/tall enough so Main tab (control + cards + actions) fits without scroll
        self.tabview = ctk.CTkTabview(content_frame, width=920, height=580)
        self.tabview.grid(row=3, column=0, pady=10, padx=20, sticky="nsew")
        self.main_tab = self.tabview.add("Main")
        self.accounts_tab = self.tabview.add("Accounts")
        self.settings_tab = self.tabview.add("Settings")
        self._create_main_tab()
        self._create_accounts_tab()
        self._create_settings_tab()
        self._update_checklist_statuses()

        # Live Log pinned at bottom (grid row 1, weight=0 so it keeps consistent height)
        log_frame = self._create_shared_log_area()
        log_frame.grid(row=1, column=0, sticky="ew")
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_rowconfigure(1, weight=0)
    
    def _update_checklist_statuses(self) -> None:
        """Update Source Selection checkboxes with readiness (✓ when ready), data label, and button states."""
        # Check readiness per platform (valid ID and date range confirmed)
        is_valid_google, _ = self._validate_inputs()
        google_ready = is_valid_google and self.date_range_locked
        is_valid_meta, _ = self._validate_meta_inputs()
        meta_ready = is_valid_meta and self.meta_date_range_locked
        ms_cid = (self.ms_customer_id.get() or "").strip().replace("-", "").replace(" ", "")
        is_valid_ms = bool(ms_cid and ms_cid.isdigit())
        ms_config_exists = (_APP_DIR / "microsoft-ads.yaml").exists()
        tiktok_config_exists = (_APP_DIR / "tiktok-ads.yaml").exists()
        pinterest_config_exists = (_APP_DIR / "pinterest-ads.yaml").exists()
        ms_ready = is_valid_ms and self.date_range_locked and ms_config_exists
        tiktok_ready = self.date_range_locked and bool((self.tiktok_account_id.get() or "").strip()) and tiktok_config_exists
        reddit_ready = self.date_range_locked and bool((self.reddit_account_id.get() or "").strip())
        pinterest_ready = self.date_range_locked and bool((self.pinterest_account_id.get() or "").strip()) and pinterest_config_exists

        # Update Platform Card status labels: Ready / ID Missing / Date not confirmed / Setup pending
        def _status_text(ready: bool, has_id: bool) -> str:
            if ready:
                return "Ready"
            if not has_id:
                return "ID Missing"
            return "Date not confirmed"
        def _status_color(ready: bool) -> str:
            return "#90EE90" if ready else "gray"
        self.google_card_status_label.configure(text=_status_text(google_ready, is_valid_google), text_color=_status_color(google_ready))
        self.meta_card_status_label.configure(text=_status_text(meta_ready, is_valid_meta), text_color=_status_color(meta_ready))
        # Microsoft: show "Setup pending" when config file missing (admin consent / setup_ms_auth.py)
        if not ms_config_exists:
            self.ms_card_status_label.configure(text="Setup pending", text_color="gray")
        else:
            self.ms_card_status_label.configure(text=_status_text(ms_ready, is_valid_ms), text_color=_status_color(ms_ready))
        # TikTok / Pinterest: show "Setup pending" when config missing
        if not tiktok_config_exists:
            self.tiktok_card_status_label.configure(text="Setup pending" if (self.tiktok_account_id.get() or "").strip() else "ID Missing", text_color="gray")
        else:
            self.tiktok_card_status_label.configure(text=_status_text(tiktok_ready, bool((self.tiktok_account_id.get() or "").strip())), text_color=_status_color(tiktok_ready))
        self.reddit_card_status_label.configure(text=_status_text(reddit_ready, bool((self.reddit_account_id.get() or "").strip())), text_color=_status_color(reddit_ready))
        if not pinterest_config_exists:
            self.pinterest_card_status_label.configure(text="Setup pending" if (self.pinterest_account_id.get() or "").strip() else "ID Missing", text_color="gray")
        else:
            self.pinterest_card_status_label.configure(text=_status_text(pinterest_ready, bool((self.pinterest_account_id.get() or "").strip())), text_color=_status_color(pinterest_ready))

        # Data guardrail: update label next to Clear All Data (top)
        raw_base = Path(self.settings.get("raw_reports_dir", "raw_reports"))
        google_dir = raw_base / "google"
        meta_dir = raw_base / "meta"
        merged_dir = Path(self.settings.get("merged_reports_dir", "merged_reports"))
        ready_dir = Path(self.settings.get("ready_reports_dir", "ready_reports"))
        google_has_data = google_dir.exists() and any(google_dir.glob("*.csv"))
        meta_has_data = meta_dir.exists() and any(meta_dir.glob("*.csv"))
        merged_has_data = merged_dir.exists() and any(merged_dir.glob("*.csv"))
        ready_has_data = ready_dir.exists() and any(ready_dir.glob("*.csv"))
        has_csv_files = google_has_data or meta_has_data or merged_has_data or ready_has_data
        if has_csv_files:
            data_text, data_color = "☐ Data present", "#FF6B6B"
        else:
            data_text, data_color = "✓ No existing data", "#90EE90"
        self.data_status_label.configure(text=data_text, text_color=data_color)

        # Run Fetch: enabled when at least one selected platform ready (data may exist; user can run and overwrite)
        google_selected = self.source_google_var.get()
        meta_selected = self.source_meta_var.get()
        ms_selected = self.source_ms_var.get()
        tiktok_selected = self.source_tiktok_var.get()
        reddit_selected = self.source_reddit_var.get()
        pinterest_selected = self.source_pinterest_var.get()
        any_ready = (
            (google_selected and google_ready)
            or (meta_selected and meta_ready)
            or (ms_selected and ms_ready)
            or (tiktok_selected and tiktok_ready)
            or (reddit_selected and reddit_ready)
            or (pinterest_selected and pinterest_ready)
        )
        all_ready = any_ready
        self.root.after(0, lambda: self.run_full_pipeline_button.configure(
            state="normal" if all_ready else "disabled",
            fg_color="#0066CC" if all_ready else "gray",
            hover_color="#0052A3" if all_ready else "darkgray"
        ))

        # Clear All Data button state
        self.root.after(0, lambda: self.clear_data_button.configure(
            fg_color="#8B0000" if has_csv_files else "gray",
            hover_color="#A00000" if has_csv_files else "darkgray",
            state="normal" if has_csv_files else "disabled"
        ))

        # Process All Data button state (enabled only when there is data to process)
        self.root.after(0, lambda: self.process_all_data_button.configure(
            state="normal" if has_csv_files else "disabled",
            fg_color="orange" if has_csv_files else "gray",
            hover_color="darkorange" if has_csv_files else "darkgray"
        ))


    
    def _create_process_section(self) -> None:
        """Create process section between tabs and log."""
        process_section = ctk.CTkFrame(self.root)
        process_section.pack(pady=10, padx=20, fill="x")
        
        self.process_button = ctk.CTkButton(
            process_section,
            text="Process Downloaded Files",
            command=self._on_process_clicked,
            font=ctk.CTkFont(size=14, weight="bold"),
            height=45,
            fg_color="orange",
            hover_color="darkorange"
        )
        self.process_button.pack(pady=10, padx=20, fill="x")
        
        # Progress frame (initially hidden)
        self.process_progress_frame = ctk.CTkFrame(process_section)
        
        # Outer glow frame for visual appeal
        progress_container = ctk.CTkFrame(self.process_progress_frame)
        progress_container.pack(pady=10, padx=10, fill="x")
        
        # Animated status label
        self.process_status_label = ctk.CTkLabel(
            progress_container,
            text="",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#FFA500"
        )
        self.process_status_label.pack(pady=(10, 5))
        
        # Progress bar
        self.process_progress_bar = ctk.CTkProgressBar(progress_container)
        self.process_progress_bar.pack(pady=10, padx=20, fill="x")
        self.process_progress_bar.set(0)
        self.process_progress_bar.configure(progress_color="#FF6B35", fg_color="#2B2B2B")
        
        # Progress info frame
        progress_info_frame = ctk.CTkFrame(progress_container)
        progress_info_frame.pack(pady=5, padx=20, fill="x")
        
        self.process_progress_percent_label = ctk.CTkLabel(
            progress_info_frame,
            text="0%",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#FFA500"
        )
        self.process_progress_percent_label.pack(side="left", padx=5)
        
        self.process_files_count_label = ctk.CTkLabel(
            progress_info_frame,
            text="",
            font=ctk.CTkFont(size=11),
            text_color="#A0A0A0"
        )
        self.process_files_count_label.pack(side="left", padx=15, expand=True)
        
        self.process_current_file_label = ctk.CTkLabel(
            progress_info_frame,
            text="",
            font=ctk.CTkFont(size=10),
            text_color="#808080"
        )
        self.process_current_file_label.pack(side="right", padx=5)
        
        # Spinner
        self.process_spinner_label = ctk.CTkLabel(
            progress_container,
            text="",
            font=ctk.CTkFont(size=16),
            text_color="#FFA500"
        )
        self.process_spinner_label.pack(pady=(5, 10))
        
        # Initially hide progress frame
        self.process_progress_frame.pack_forget()
    
    def _create_main_tab(self) -> None:
        """Create Main tab: Control Panel (daily date picker), Source Selection, Action Bar."""
        now = datetime.now()
        current_year = datetime.now().year
        year_list = [str(y) for y in range(current_year - 10, current_year + 1)]
        self.main_pull_prior_year_var = ctk.BooleanVar(value=True)

        # --- Control Panel: daily date range ---
        control_frame = ctk.CTkFrame(self.main_tab)
        control_frame.pack(pady=10, padx=20, fill="x")
        ctk.CTkLabel(control_frame, text="Control Panel — Date Range", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=10, pady=(10, 5))
        cal_frame = ctk.CTkFrame(control_frame, fg_color="transparent")
        cal_frame.pack(pady=5, padx=10, fill="x")
        self.main_start_cal = None
        self.main_end_cal = None
        if Calendar is not None:
            start_col = ctk.CTkFrame(cal_frame, fg_color="transparent")
            start_col.pack(side="left", padx=15, pady=5)
            ctk.CTkLabel(start_col, text="Start date", font=ctk.CTkFont(size=11, weight="bold")).pack(anchor="w")
            start_cal_container = tk.Frame(start_col)
            start_cal_container.pack(pady=5)
            self.main_start_cal = Calendar(
                start_cal_container,
                date_pattern="y-mm-dd",
                mindate=datetime(now.year - 2, 1, 1),
                maxdate=datetime(now.year + 1, 12, 31),
                font="Arial 10",
            )
            self.main_start_cal.pack(padx=5, pady=5)
            end_col = ctk.CTkFrame(cal_frame, fg_color="transparent")
            end_col.pack(side="left", padx=15, pady=5)
            ctk.CTkLabel(end_col, text="End date", font=ctk.CTkFont(size=11, weight="bold")).pack(anchor="w")
            end_cal_container = tk.Frame(end_col)
            end_cal_container.pack(pady=5)
            self.main_end_cal = Calendar(
                end_cal_container,
                date_pattern="y-mm-dd",
                mindate=datetime(now.year - 2, 1, 1),
                maxdate=datetime(now.year + 1, 12, 31),
                font="Arial 10",
            )
            self.main_end_cal.pack(padx=5, pady=5)
            self._set_main_dates_default()
        else:
            start_frame = ctk.CTkFrame(cal_frame, fg_color="transparent")
            start_frame.pack(pady=3, fill="x")
            ctk.CTkLabel(start_frame, text="Start:", font=ctk.CTkFont(size=11)).pack(side="left", padx=10)
            self.start_month_menu = ctk.CTkOptionMenu(start_frame, values=self.month_names, variable=self.start_month, width=80, state="normal" if not self.date_range_locked else "disabled")
            self.start_month_menu.pack(side="left", padx=5)
            self.start_year_menu = ctk.CTkOptionMenu(start_frame, values=year_list, variable=self.start_year, width=80, state="normal" if not self.date_range_locked else "disabled")
            self.start_year_menu.pack(side="left", padx=5)
            end_frame = ctk.CTkFrame(cal_frame, fg_color="transparent")
            end_frame.pack(pady=3, fill="x")
            ctk.CTkLabel(end_frame, text="End:  ", font=ctk.CTkFont(size=11)).pack(side="left", padx=10)
            self.end_month_menu = ctk.CTkOptionMenu(end_frame, values=self.month_names, variable=self.end_month, width=80, state="normal" if not self.date_range_locked else "disabled")
            self.end_month_menu.pack(side="left", padx=5)
            self.end_year_menu = ctk.CTkOptionMenu(end_frame, values=year_list, variable=self.end_year, width=80, state="normal" if not self.date_range_locked else "disabled")
            self.end_year_menu.pack(side="left", padx=5)

        date_btn_frame = ctk.CTkFrame(control_frame, fg_color="transparent")
        date_btn_frame.pack(pady=8, padx=10)
        self.confirm_date_btn = ctk.CTkButton(date_btn_frame, text="Confirm Date Range", command=self._confirm_date_range_global, font=ctk.CTkFont(size=11), width=150, height=30)
        self.confirm_date_btn.pack(side="left", padx=5)
        self.unlock_date_btn = ctk.CTkButton(date_btn_frame, text="Unlock", command=self._unlock_date_range_global, font=ctk.CTkFont(size=10), width=80, height=30, fg_color="gray", hover_color="darkgray", state="disabled")
        self.unlock_date_btn.pack(side="left", padx=5)

        prior_year_row = ctk.CTkFrame(control_frame, fg_color="transparent")
        prior_year_row.pack(pady=6, padx=10, fill="x")
        self.main_pull_prior_year_cb = ctk.CTkCheckBox(
            prior_year_row, text="Also pull same range previous year", variable=self.main_pull_prior_year_var,
            font=ctk.CTkFont(size=11)
        )
        self.main_pull_prior_year_cb.pack(side="left", padx=(20, 0))

        # --- Scrollable: 3x2 grid of Platform Cards (expands to fill; scrollbar only when window shrunk)
        # Platform section and scrollbar use different shades to differentiate
        PLATFORM_SECTION_BG = ("#e8e8e8", "#2a2a2a")
        SCROLLBAR_FG = ("#d0d0d0", "#1e1e1e")
        SCROLLBAR_BUTTON = ("#b0b0b0", "#333333")
        SCROLLBAR_BUTTON_HOVER = ("#909090", "#444444")
        self.main_scrollable = ctk.CTkScrollableFrame(
            self.main_tab,
            fg_color=PLATFORM_SECTION_BG,
            corner_radius=8,
            scrollbar_fg_color=SCROLLBAR_FG,
            scrollbar_button_color=SCROLLBAR_BUTTON,
            scrollbar_button_hover_color=SCROLLBAR_BUTTON_HOVER,
        )
        self.main_scrollable.pack(pady=6, padx=20, fill="both", expand=True)

        # Select a card by default only if that platform has at least one favorite account
        self.source_google_var = ctk.BooleanVar(value=bool(self.favorites))
        self.source_meta_var = ctk.BooleanVar(value=bool(self.meta_favorites))
        self.source_ms_var = ctk.BooleanVar(value=bool(self.ms_favorites))
        self.source_tiktok_var = ctk.BooleanVar(value=bool(self.tiktok_favorites))
        self.source_reddit_var = ctk.BooleanVar(value=bool(self.reddit_favorites))
        self.source_pinterest_var = ctk.BooleanVar(value=bool(self.pinterest_favorites))

        CARD_PAD = 10
        CARD_COMBO_WIDTH = 220
        CARD_ACTIVE_BORDER = "#0066CC"
        CARD_DIM_FG = ("#3a3a3a", "#2d2d2d")
        CARD_ACTIVE_FG = ("#4a4a4a", "#3d3d3d")

        cards_grid = ctk.CTkFrame(self.main_scrollable, fg_color="transparent")
        cards_grid.pack(pady=8, padx=8, fill="both", expand=True)
        for c in range(3):
            cards_grid.columnconfigure(c, weight=1, uniform="cards")
        cards_grid.rowconfigure(0, weight=0)
        cards_grid.rowconfigure(1, weight=0)

        def _make_card(parent: ctk.CTkFrame, row: int, col: int, name: str, var: ctk.BooleanVar) -> ctk.CTkFrame:
            card = ctk.CTkFrame(parent, fg_color=CARD_DIM_FG, corner_radius=8, border_width=0)
            card.grid(row=row, column=col, padx=CARD_PAD, pady=CARD_PAD, sticky="nsew")
            cb = ctk.CTkCheckBox(card, text=name, variable=var, font=ctk.CTkFont(size=11, weight="bold"), command=self._on_source_selection_changed)
            cb.pack(anchor="w", padx=10, pady=(10, 6))
            return card

        # Row 0: Google (0,0), Meta (0,1), MS Ads (0,2)
        self.google_card = _make_card(cards_grid, 0, 0, "Google Ads", self.source_google_var)
        google_values = [f"{f['name']} ({f['customer_id']})" for f in self.favorites] if self.favorites else []
        self.customer_id_combobox = ctk.CTkComboBox(self.google_card, variable=self.google_id_display, values=google_values, width=CARD_COMBO_WIDTH, height=28, font=ctk.CTkFont(size=11), state="normal", command=self._on_google_id_combobox_select)
        self.customer_id_combobox.pack(anchor="w", padx=10, pady=(0, 4))
        self.google_card_status_label = ctk.CTkLabel(self.google_card, text="ID Missing", font=ctk.CTkFont(size=10), text_color="gray")
        self.google_card_status_label.pack(anchor="w", padx=10, pady=(0, 10))
        self._set_google_id_display_from_id()
        self.google_id_display.trace_add("write", lambda *a: self._sync_google_id_from_display())

        self.meta_card = _make_card(cards_grid, 0, 1, "Meta Ads", self.source_meta_var)
        meta_values = [f"{f['name']} ({f['account_id']})" for f in self.meta_favorites] if self.meta_favorites else []
        self.meta_account_id_combobox = ctk.CTkComboBox(self.meta_card, variable=self.meta_id_display, values=meta_values, width=CARD_COMBO_WIDTH, height=28, font=ctk.CTkFont(size=11), state="normal", command=self._on_meta_id_combobox_select)
        self.meta_account_id_combobox.pack(anchor="w", padx=10, pady=(0, 4))
        self.meta_card_status_label = ctk.CTkLabel(self.meta_card, text="ID Missing", font=ctk.CTkFont(size=10), text_color="gray")
        self.meta_card_status_label.pack(anchor="w", padx=10, pady=(0, 4))
        self.meta_retention_warning_label = ctk.CTkLabel(
            self.meta_card,
            text="",
            font=ctk.CTkFont(size=10),
            text_color="#FFA500",
            wraplength=280,
            justify="left"
        )
        self.meta_retention_warning_label.pack(anchor="w", padx=10, pady=(0, 4))
        self.meta_retention_warning_label.pack_forget()
        self.meta_token_frame = ctk.CTkFrame(self.meta_card, fg_color="transparent")
        ctk.CTkLabel(self.meta_token_frame, text="Meta Access Token Expired. Enter new token:", font=ctk.CTkFont(size=10, weight="bold"), text_color="#FF6B6B").pack(anchor="w", padx=0, pady=(2, 2))
        token_row = ctk.CTkFrame(self.meta_token_frame, fg_color="transparent")
        token_row.pack(pady=(0, 4), fill="x")
        self.meta_token_entry = ctk.CTkEntry(token_row, textvariable=self.meta_token_input, placeholder_text="Paste new token", width=200, height=28)
        self.meta_token_entry.pack(side="left", padx=(0, 6), fill="x", expand=True)
        self.meta_token_update_btn = ctk.CTkButton(token_row, text="Update Token", command=self._on_meta_token_update_clicked, width=100, height=28, font=ctk.CTkFont(size=10, weight="bold"), fg_color="green", hover_color="darkgreen")
        self.meta_token_update_btn.pack(side="left", padx=0)
        self.meta_token_frame.pack(fill="x", padx=10, pady=(0, 6))
        self.meta_token_frame.pack_forget()
        self._set_meta_id_display_from_id()
        self.meta_id_display.trace_add("write", lambda *a: self._sync_meta_id_from_display())

        self.ms_card = _make_card(cards_grid, 0, 2, "Microsoft Ads", self.source_ms_var)
        ms_values = [f"{f['name']} ({f['customer_id']})" for f in self.ms_favorites] if self.ms_favorites else []
        self.ms_customer_id_combobox = ctk.CTkComboBox(self.ms_card, variable=self.ms_id_display, values=ms_values, width=CARD_COMBO_WIDTH, height=28, font=ctk.CTkFont(size=11), state="normal", command=self._on_ms_id_combobox_select)
        self.ms_customer_id_combobox.pack(anchor="w", padx=10, pady=(0, 4))
        self.ms_card_status_label = ctk.CTkLabel(self.ms_card, text="ID Missing", font=ctk.CTkFont(size=10), text_color="gray")
        self.ms_card_status_label.pack(anchor="w", padx=10, pady=(0, 10))
        self._set_ms_id_display_from_id()
        self.ms_id_display.trace_add("write", lambda *a: self._sync_ms_id_from_display())

        # Row 1: TikTok (1,0), Reddit (1,1), Pinterest (1,2)
        self.tiktok_card = _make_card(cards_grid, 1, 0, "TikTok Ads", self.source_tiktok_var)
        tk_values = [f"{f['name']} ({f['advertiser_id']})" for f in self.tiktok_favorites] if self.tiktok_favorites else []
        self.tiktok_account_id_combobox = ctk.CTkComboBox(self.tiktok_card, variable=self.tiktok_id_display, values=tk_values, width=CARD_COMBO_WIDTH, height=28, font=ctk.CTkFont(size=11), state="normal", command=self._on_tiktok_id_combobox_select)
        self.tiktok_account_id_combobox.pack(anchor="w", padx=10, pady=(0, 4))
        self.tiktok_card_status_label = ctk.CTkLabel(self.tiktok_card, text="ID Missing", font=ctk.CTkFont(size=10), text_color="gray")
        self.tiktok_card_status_label.pack(anchor="w", padx=10, pady=(0, 10))
        self._set_tiktok_id_display_from_id()
        self.tiktok_id_display.trace_add("write", lambda *a: self._sync_tiktok_id_from_display())

        self.reddit_card = _make_card(cards_grid, 1, 1, "Reddit Ads", self.source_reddit_var)
        rd_values = [f"{f['name']} ({f['account_id']})" for f in self.reddit_favorites] if self.reddit_favorites else []
        self.reddit_account_id_combobox = ctk.CTkComboBox(self.reddit_card, variable=self.reddit_id_display, values=rd_values, width=CARD_COMBO_WIDTH, height=28, font=ctk.CTkFont(size=11), state="normal", command=self._on_reddit_id_combobox_select)
        self.reddit_account_id_combobox.pack(anchor="w", padx=10, pady=(0, 4))
        self.reddit_card_status_label = ctk.CTkLabel(self.reddit_card, text="ID Missing", font=ctk.CTkFont(size=10), text_color="gray")
        self.reddit_card_status_label.pack(anchor="w", padx=10, pady=(0, 10))
        self._set_reddit_id_display_from_id()
        self.reddit_id_display.trace_add("write", lambda *a: self._sync_reddit_id_from_display())

        self.pinterest_card = _make_card(cards_grid, 1, 2, "Pinterest Ads", self.source_pinterest_var)
        pt_values = [f"{f['name']} ({f['advertiser_id']})" for f in self.pinterest_favorites] if self.pinterest_favorites else []
        self.pinterest_account_id_combobox = ctk.CTkComboBox(self.pinterest_card, variable=self.pinterest_id_display, values=pt_values, width=CARD_COMBO_WIDTH, height=28, font=ctk.CTkFont(size=11), state="normal", command=self._on_pinterest_id_combobox_select)
        self.pinterest_account_id_combobox.pack(anchor="w", padx=10, pady=(0, 4))
        self.pinterest_card_status_label = ctk.CTkLabel(self.pinterest_card, text="ID Missing", font=ctk.CTkFont(size=10), text_color="gray")
        self.pinterest_card_status_label.pack(anchor="w", padx=10, pady=(0, 10))
        self._set_pinterest_id_display_from_id()
        self.pinterest_id_display.trace_add("write", lambda *a: self._sync_pinterest_id_from_display())

        # Apply default account for every platform so Main tab shows default (e.g. Reddit, MS, TikTok, Pinterest) like Google/Meta
        self._apply_default_accounts_at_startup()
        self._on_source_selection_changed()

        # Invisible progress bars for pipeline (Google/Meta fetch threads update these; pipeline status shows under header)
        self.progress_bar = ctk.CTkProgressBar(ctk.CTkFrame(self.main_tab, fg_color="transparent"))
        self.progress_bar.set(0)
        self.progress_percent_label = ctk.CTkLabel(self.main_tab, text="0%")
        self.eta_label = ctk.CTkLabel(self.main_tab, text="")
        self.completion_time_label = ctk.CTkLabel(self.main_tab, text="")
        self.meta_progress_bar = ctk.CTkProgressBar(ctk.CTkFrame(self.main_tab, fg_color="transparent"))
        self.meta_progress_bar.set(0)
        self.meta_progress_percent_label = ctk.CTkLabel(self.main_tab, text="0%")
        self.meta_eta_label = ctk.CTkLabel(self.main_tab, text="")
        self.meta_completion_time_label = ctk.CTkLabel(self.main_tab, text="")

        self.google_process_progress_frame = ctk.CTkFrame(self.main_tab)
        self.meta_process_progress_frame = ctk.CTkFrame(self.main_tab)
        for pf in [self.google_process_progress_frame, self.meta_process_progress_frame]:
            pc = ctk.CTkFrame(pf, fg_color="transparent")
            pc.pack(pady=10, padx=10, fill="x")
            ctk.CTkLabel(pc, text="", font=ctk.CTkFont(size=13, weight="bold"), text_color="#FFA500").pack(pady=(10, 5))
            pb = ctk.CTkProgressBar(pc)
            pb.pack(pady=10, padx=20, fill="x")
            pb.set(0)
            pb.configure(progress_color="#FF6B35", fg_color="#2B2B2B")
            pi = ctk.CTkFrame(pc, fg_color="transparent")
            pi.pack(pady=5, padx=20, fill="x")
            ctk.CTkLabel(pi, text="0%", font=ctk.CTkFont(size=14, weight="bold"), text_color="#FFA500").pack(side="left", padx=5)
            ctk.CTkLabel(pi, text="", font=ctk.CTkFont(size=11), text_color="#A0A0A0").pack(side="left", padx=15, expand=True)
            ctk.CTkLabel(pi, text="", font=ctk.CTkFont(size=10), text_color="#808080").pack(side="right", padx=5)
            ctk.CTkLabel(pc, text="", font=ctk.CTkFont(size=16), text_color="#FFA500").pack(pady=(5, 10))
            pf.pack_forget()
        self.google_process_status_label = self.google_process_progress_frame.winfo_children()[0].winfo_children()[0]
        self.google_process_progress_bar = self.google_process_progress_frame.winfo_children()[0].winfo_children()[1]
        self.google_process_percent_label = self.google_process_progress_frame.winfo_children()[0].winfo_children()[2].winfo_children()[0]
        self.google_process_files_label = self.google_process_progress_frame.winfo_children()[0].winfo_children()[2].winfo_children()[1]
        self.google_process_current_label = self.google_process_progress_frame.winfo_children()[0].winfo_children()[2].winfo_children()[2]
        self.google_process_spinner_label = self.google_process_progress_frame.winfo_children()[0].winfo_children()[3]
        self.meta_process_status_label = self.meta_process_progress_frame.winfo_children()[0].winfo_children()[0]
        self.meta_process_progress_bar = self.meta_process_progress_frame.winfo_children()[0].winfo_children()[1]
        self.meta_process_percent_label = self.meta_process_progress_frame.winfo_children()[0].winfo_children()[2].winfo_children()[0]
        self.meta_process_files_label = self.meta_process_progress_frame.winfo_children()[0].winfo_children()[2].winfo_children()[1]
        self.meta_process_current_label = self.meta_process_progress_frame.winfo_children()[0].winfo_children()[2].winfo_children()[2]
        self.meta_process_spinner_label = self.meta_process_progress_frame.winfo_children()[0].winfo_children()[3]

    def _create_accounts_tab(self) -> None:
        """Create Accounts tab: Default account settings and Add/Edit/Delete per platform."""
        self.accounts_scrollable = ctk.CTkScrollableFrame(self.accounts_tab, height=450, fg_color="transparent")
        self.accounts_scrollable.pack(pady=6, padx=20, fill="both", expand=True)

        # --- Default Favorites (default account per platform) — aligned grid ---
        default_favorite_frame = ctk.CTkFrame(self.accounts_scrollable)
        default_favorite_frame.pack(pady=10, padx=0, fill="x")
        # Grid: column 0 = label (fixed width), 1 = dropdown, 2 = Add, 3 = Edit, 4 = Delete
        LABEL_WIDTH_PX = 130
        DROPDOWN_WIDTH = 200
        BTN_WIDTH = 70
        PAD_ROW = (5, 5)
        PAD_COL = (8, 8)
        default_favorite_frame.columnconfigure(0, minsize=LABEL_WIDTH_PX)
        default_favorite_frame.columnconfigure(1, minsize=DROPDOWN_WIDTH)
        default_favorite_frame.columnconfigure(2, minsize=BTN_WIDTH)
        default_favorite_frame.columnconfigure(3, minsize=BTN_WIDTH)
        default_favorite_frame.columnconfigure(4, minsize=BTN_WIDTH)

        ctk.CTkLabel(
            default_favorite_frame,
            text="Default account",
            font=ctk.CTkFont(size=12, weight="bold")
        ).grid(row=0, column=0, columnspan=5, sticky="w", padx=10, pady=(10, 8))

        def add_platform_row(row, label_text, values, default_key, set_callback, menu_attr, add_cb, edit_cb, delete_cb):
            ctk.CTkLabel(default_favorite_frame, text=label_text, font=ctk.CTkFont(size=11), anchor="w").grid(row=row, column=0, sticky="w", padx=(10, 0), pady=PAD_ROW)
            menu = ctk.CTkOptionMenu(
                default_favorite_frame,
                values=["None"] + values if values else ["None"],
                command=set_callback,
                width=DROPDOWN_WIDTH,
                font=ctk.CTkFont(size=11)
            )
            default_val = self.settings.get(default_key, "None")
            if default_val not in (values or []):
                default_val = "None"
            menu.set(default_val)
            menu.grid(row=row, column=1, sticky="w", padx=PAD_COL, pady=PAD_ROW)
            setattr(self, menu_attr, menu)
            ctk.CTkButton(default_favorite_frame, text="Add", command=add_cb, width=BTN_WIDTH, font=ctk.CTkFont(size=11)).grid(row=row, column=2, padx=(0, 4), pady=PAD_ROW)
            ctk.CTkButton(default_favorite_frame, text="Edit", command=edit_cb, width=BTN_WIDTH, font=ctk.CTkFont(size=11)).grid(row=row, column=3, padx=4, pady=PAD_ROW)
            ctk.CTkButton(default_favorite_frame, text="Delete", command=delete_cb, width=BTN_WIDTH, font=ctk.CTkFont(size=11), fg_color="red", hover_color="darkred").grid(row=row, column=4, padx=(4, 10), pady=PAD_ROW)

        google_favorite_names = [fav["name"] for fav in self.favorites] if self.favorites else []
        add_platform_row(1, "Google Ads:", google_favorite_names, "default_google_favorite", self._on_google_default_favorite_changed, "settings_google_favorite_menu",
            self._on_settings_add_google_favorite, self._on_settings_edit_google_favorite, self._on_settings_delete_google_favorite)
        default_google = self.settings.get("default_google_favorite", "ML" if "ML" in (google_favorite_names or []) else "None")
        if default_google in (google_favorite_names or []):
            self.settings_google_favorite_menu.set(default_google)
        else:
            self.settings_google_favorite_menu.set("None")

        meta_favorite_names = [fav["name"] for fav in self.meta_favorites] if self.meta_favorites else []
        add_platform_row(2, "Meta Ads:", meta_favorite_names, "default_meta_favorite", self._on_meta_default_favorite_changed, "settings_meta_favorite_menu",
            self._on_settings_add_meta_favorite, self._on_settings_edit_meta_favorite, self._on_settings_delete_meta_favorite)
        default_meta = self.settings.get("default_meta_favorite", "ML" if "ML" in (meta_favorite_names or []) else "None")
        if default_meta in (meta_favorite_names or []):
            self.settings_meta_favorite_menu.set(default_meta)
        else:
            self.settings_meta_favorite_menu.set("None")

        ms_favorite_names = [fav["name"] for fav in self.ms_favorites] if self.ms_favorites else []
        add_platform_row(3, "Microsoft Ads:", ms_favorite_names, "default_ms_favorite", self._on_ms_default_favorite_changed, "settings_ms_favorite_menu",
            self._on_settings_add_ms_favorite, self._on_settings_edit_ms_favorite, self._on_settings_delete_ms_favorite)
        default_ms = self.settings.get("default_ms_favorite", "None")
        if default_ms in (ms_favorite_names or []):
            self.settings_ms_favorite_menu.set(default_ms)
        else:
            self.settings_ms_favorite_menu.set("None")

        tiktok_favorite_names = [fav["name"] for fav in self.tiktok_favorites] if self.tiktok_favorites else []
        add_platform_row(4, "TikTok Ads:", tiktok_favorite_names, "default_tiktok_favorite", self._on_tiktok_default_favorite_changed, "settings_tiktok_favorite_menu",
            self._on_settings_add_tiktok_favorite, self._on_settings_edit_tiktok_favorite, self._on_settings_delete_tiktok_favorite)
        default_tiktok = self.settings.get("default_tiktok_favorite", "None")
        if default_tiktok in (tiktok_favorite_names or []):
            self.settings_tiktok_favorite_menu.set(default_tiktok)
        else:
            self.settings_tiktok_favorite_menu.set("None")

        reddit_favorite_names = [fav["name"] for fav in self.reddit_favorites] if self.reddit_favorites else []
        add_platform_row(5, "Reddit Ads:", reddit_favorite_names, "default_reddit_favorite", self._on_reddit_default_favorite_changed, "settings_reddit_favorite_menu",
            self._on_settings_add_reddit_favorite, self._on_settings_edit_reddit_favorite, self._on_settings_delete_reddit_favorite)
        default_reddit = self.settings.get("default_reddit_favorite", "None")
        if default_reddit in (reddit_favorite_names or []):
            self.settings_reddit_favorite_menu.set(default_reddit)
        else:
            self.settings_reddit_favorite_menu.set("None")

        pinterest_favorite_names = [fav["name"] for fav in self.pinterest_favorites] if self.pinterest_favorites else []
        add_platform_row(6, "Pinterest Ads:", pinterest_favorite_names, "default_pinterest_favorite", self._on_pinterest_default_favorite_changed, "settings_pinterest_favorite_menu",
            self._on_settings_add_pinterest_favorite, self._on_settings_edit_pinterest_favorite, self._on_settings_delete_pinterest_favorite)
        default_pinterest = self.settings.get("default_pinterest_favorite", "None")
        if default_pinterest in (pinterest_favorite_names or []):
            self.settings_pinterest_favorite_menu.set(default_pinterest)
        else:
            self.settings_pinterest_favorite_menu.set("None")

    def _on_source_selection_changed(self) -> None:
        """Update card state: enable/disable dropdown, dim/active card; apply smart default when first checked."""
        CARD_DIM_FG = ("#3a3a3a", "#2d2d2d")
        CARD_ACTIVE_FG = ("#4a4a4a", "#3d3d3d")
        CARD_ACTIVE_BORDER = "#0066CC"
        platform_cards = [
            (self.source_google_var, self.google_card, self.customer_id_combobox, "google"),
            (self.source_meta_var, self.meta_card, self.meta_account_id_combobox, "meta"),
            (self.source_ms_var, self.ms_card, self.ms_customer_id_combobox, "ms"),
            (self.source_tiktok_var, self.tiktok_card, self.tiktok_account_id_combobox, "tiktok"),
            (self.source_reddit_var, self.reddit_card, self.reddit_account_id_combobox, "reddit"),
            (self.source_pinterest_var, self.pinterest_card, self.pinterest_account_id_combobox, "pinterest"),
        ]
        for var, card, combobox, key in platform_cards:
            checked = var.get()
            combobox.configure(state="normal" if checked else "disabled")
            if checked:
                card.configure(fg_color=CARD_ACTIVE_FG, border_width=2, border_color=CARD_ACTIVE_BORDER)
                self._apply_smart_default_for_platform(key)
            else:
                card.configure(fg_color=CARD_DIM_FG, border_width=0, border_color="#3a3a3a")
        self._update_checklist_statuses()

    def _apply_smart_default_for_platform(self, platform_key: str) -> None:
        """When a platform is first shown, fill empty ID from last_*_id or primary favorite."""
        last_key = f"last_{platform_key}_id"
        last_id = self.settings.get(last_key, "").strip()
        if platform_key == "google":
            if not self.customer_id.get().strip() and last_id:
                self.customer_id.set(last_id)
            elif not self.customer_id.get().strip():
                default_fav = self.settings.get("default_google_favorite")
                if default_fav and self.favorites:
                    for f in self.favorites:
                        if f.get("name") == default_fav and f.get("customer_id"):
                            self.customer_id.set(f["customer_id"].strip())
                            break
        elif platform_key == "meta":
            current = self.meta_account_id.get().strip()
            if (not current or current == "act_") and last_id:
                self.meta_account_id.set(last_id)
            elif (not current or current == "act_"):
                default_fav = self.settings.get("default_meta_favorite")
                if default_fav and self.meta_favorites:
                    for f in self.meta_favorites:
                        if f.get("name") == default_fav and f.get("account_id"):
                            self.meta_account_id.set(f["account_id"].strip())
                            break
        elif platform_key == "ms":
            if not self.ms_customer_id.get().strip() and last_id:
                self.ms_customer_id.set(last_id)
            elif not self.ms_customer_id.get().strip():
                default_fav = self.settings.get("default_ms_favorite")
                if default_fav and self.ms_favorites:
                    for f in self.ms_favorites:
                        if f.get("name") == default_fav and f.get("customer_id"):
                            self.ms_customer_id.set(f["customer_id"].strip())
                            break
        elif platform_key == "tiktok":
            if not self.tiktok_account_id.get().strip() and last_id:
                self.tiktok_account_id.set(last_id)
            elif not self.tiktok_account_id.get().strip():
                default_fav = self.settings.get("default_tiktok_favorite")
                if default_fav and self.tiktok_favorites:
                    for f in self.tiktok_favorites:
                        if f.get("name") == default_fav and f.get("advertiser_id"):
                            self.tiktok_account_id.set(f["advertiser_id"].strip())
                            break
        elif platform_key == "reddit":
            if not self.reddit_account_id.get().strip() and last_id:
                self.reddit_account_id.set(last_id)
            elif not self.reddit_account_id.get().strip():
                default_fav = self.settings.get("default_reddit_favorite")
                if default_fav and self.reddit_favorites:
                    for f in self.reddit_favorites:
                        if f.get("name") == default_fav and f.get("account_id"):
                            self.reddit_account_id.set(f["account_id"].strip())
                            break
        elif platform_key == "pinterest":
            if not self.pinterest_account_id.get().strip() and last_id:
                self.pinterest_account_id.set(last_id)
            elif not self.pinterest_account_id.get().strip():
                default_fav = self.settings.get("default_pinterest_favorite")
                if default_fav and self.pinterest_favorites:
                    for f in self.pinterest_favorites:
                        if f.get("name") == default_fav and f.get("advertiser_id"):
                            self.pinterest_account_id.set(f["advertiser_id"].strip())
                            break
        # Sync combobox display to current ID for this platform
        if platform_key == "google":
            self._set_google_id_display_from_id()
        elif platform_key == "meta":
            self._set_meta_id_display_from_id()
        elif platform_key == "ms":
            self._set_ms_id_display_from_id()
        elif platform_key == "tiktok":
            self._set_tiktok_id_display_from_id()
        elif platform_key == "reddit":
            self._set_reddit_id_display_from_id()
        elif platform_key == "pinterest":
            self._set_pinterest_id_display_from_id()

    def _apply_default_accounts_at_startup(self) -> None:
        """Pre-fill each platform's account from default favorite so Main tab shows default for all cards (like Google/Meta)."""
        # Google
        if not self.customer_id.get().strip():
            default_fav = self.settings.get("default_google_favorite")
            if default_fav and self.favorites:
                for f in self.favorites:
                    if f.get("name") == default_fav and f.get("customer_id"):
                        self.customer_id.set(f["customer_id"].strip())
                        break
        # Meta
        current_meta = self.meta_account_id.get().strip()
        if not current_meta or current_meta == "act_":
            default_fav = self.settings.get("default_meta_favorite")
            if default_fav and self.meta_favorites:
                for f in self.meta_favorites:
                    if f.get("name") == default_fav and f.get("account_id"):
                        self.meta_account_id.set(f["account_id"].strip())
                        break
        # Microsoft
        if not self.ms_customer_id.get().strip():
            default_fav = self.settings.get("default_ms_favorite")
            if default_fav and self.ms_favorites:
                for f in self.ms_favorites:
                    if f.get("name") == default_fav and f.get("customer_id"):
                        self.ms_customer_id.set(f["customer_id"].strip())
                        break
        # TikTok
        if not self.tiktok_account_id.get().strip():
            default_fav = self.settings.get("default_tiktok_favorite")
            if default_fav and self.tiktok_favorites:
                for f in self.tiktok_favorites:
                    if f.get("name") == default_fav and f.get("advertiser_id"):
                        self.tiktok_account_id.set(f["advertiser_id"].strip())
                        break
        # Reddit
        if not self.reddit_account_id.get().strip():
            default_fav = self.settings.get("default_reddit_favorite")
            if default_fav and self.reddit_favorites:
                for f in self.reddit_favorites:
                    if f.get("name") == default_fav and f.get("account_id"):
                        self.reddit_account_id.set(f["account_id"].strip())
                        break
        # Pinterest
        if not self.pinterest_account_id.get().strip():
            default_fav = self.settings.get("default_pinterest_favorite")
            if default_fav and self.pinterest_favorites:
                for f in self.pinterest_favorites:
                    if f.get("name") == default_fav and f.get("advertiser_id"):
                        self.pinterest_account_id.set(f["advertiser_id"].strip())
                        break
        # Sync combobox display for all platforms
        self._set_google_id_display_from_id()
        self._set_meta_id_display_from_id()
        self._set_ms_id_display_from_id()
        self._set_tiktok_id_display_from_id()
        self._set_reddit_id_display_from_id()
        self._set_pinterest_id_display_from_id()

    def _set_google_id_display_from_id(self) -> None:
        cid = self.customer_id.get().strip()
        for f in self.favorites:
            if (f.get("customer_id") or "").strip() == cid:
                self.google_id_display.set(f"{f['name']} ({f['customer_id']})")
                return
        self.google_id_display.set(cid if cid else "")

    def _sync_google_id_from_display(self) -> None:
        self.customer_id.set(_parse_id_from_favorite_display(self.google_id_display.get()))

    def _on_google_id_combobox_select(self, choice: str) -> None:
        self.customer_id.set(_parse_id_from_favorite_display(choice))

    def _set_meta_id_display_from_id(self) -> None:
        aid = self.meta_account_id.get().strip()
        for f in self.meta_favorites:
            if (f.get("account_id") or "").strip() == aid:
                self.meta_id_display.set(f"{f['name']} ({f['account_id']})")
                return
        self.meta_id_display.set(aid if aid else "")

    def _sync_meta_id_from_display(self) -> None:
        self.meta_account_id.set(_parse_id_from_favorite_display(self.meta_id_display.get()))

    def _on_meta_id_combobox_select(self, choice: str) -> None:
        self.meta_account_id.set(_parse_id_from_favorite_display(choice))

    def _set_ms_id_display_from_id(self) -> None:
        cid = self.ms_customer_id.get().strip()
        for f in self.ms_favorites:
            if (f.get("customer_id") or "").strip() == cid:
                self.ms_id_display.set(f"{f['name']} ({f['customer_id']})")
                return
        self.ms_id_display.set(cid if cid else "")

    def _sync_ms_id_from_display(self) -> None:
        self.ms_customer_id.set(_parse_id_from_favorite_display(self.ms_id_display.get()))

    def _on_ms_id_combobox_select(self, choice: str) -> None:
        self.ms_customer_id.set(_parse_id_from_favorite_display(choice))

    def _set_tiktok_id_display_from_id(self) -> None:
        tid = self.tiktok_account_id.get().strip()
        for f in self.tiktok_favorites:
            if (f.get("advertiser_id") or "").strip() == tid:
                self.tiktok_id_display.set(f"{f['name']} ({f['advertiser_id']})")
                return
        self.tiktok_id_display.set(tid if tid else "")

    def _sync_tiktok_id_from_display(self) -> None:
        self.tiktok_account_id.set(_parse_id_from_favorite_display(self.tiktok_id_display.get()))

    def _on_tiktok_id_combobox_select(self, choice: str) -> None:
        self.tiktok_account_id.set(_parse_id_from_favorite_display(choice))

    def _set_reddit_id_display_from_id(self) -> None:
        rid = self.reddit_account_id.get().strip()
        for f in self.reddit_favorites:
            if (f.get("account_id") or "").strip() == rid:
                self.reddit_id_display.set(f"{f['name']} ({f['account_id']})")
                return
        self.reddit_id_display.set(rid if rid else "")

    def _sync_reddit_id_from_display(self) -> None:
        self.reddit_account_id.set(_parse_id_from_favorite_display(self.reddit_id_display.get()))

    def _on_reddit_id_combobox_select(self, choice: str) -> None:
        self.reddit_account_id.set(_parse_id_from_favorite_display(choice))

    def _set_pinterest_id_display_from_id(self) -> None:
        pid = self.pinterest_account_id.get().strip()
        for f in self.pinterest_favorites:
            if (f.get("advertiser_id") or "").strip() == pid:
                self.pinterest_id_display.set(f"{f['name']} ({f['advertiser_id']})")
                return
        self.pinterest_id_display.set(pid if pid else "")

    def _sync_pinterest_id_from_display(self) -> None:
        self.pinterest_account_id.set(_parse_id_from_favorite_display(self.pinterest_id_display.get()))

    def _on_pinterest_id_combobox_select(self, choice: str) -> None:
        self.pinterest_account_id.set(_parse_id_from_favorite_display(choice))

    def _create_settings_tab(self) -> None:
        """Create Settings tab with configuration options."""
        self._mappings_data: Dict[str, str] = {}
        self._mappings_file = _APP_DIR / "mappings.json"

        # Theme mode section (pack first so it stays visible at top)
        theme_frame = ctk.CTkFrame(self.settings_tab)
        theme_frame.pack(pady=10, padx=20, fill="x")
        
        theme_label = ctk.CTkLabel(
            theme_frame,
            text="Appearance Mode:",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        theme_label.pack(anchor="w", padx=10, pady=(10, 5))
        
        theme_input_frame = ctk.CTkFrame(theme_frame)
        theme_input_frame.pack(pady=(0, 10), padx=10, fill="x")
        
        self.settings_theme_menu = ctk.CTkOptionMenu(
            theme_input_frame,
            values=["dark", "light"],
            command=self._on_theme_mode_changed,
            width=200,
            font=ctk.CTkFont(size=11)
        )
        current_theme = self.settings.get("theme_mode", "dark")
        self.settings_theme_menu.set(current_theme)
        self.settings_theme_menu.pack(side="left", padx=10)
        
        # Report directories section (used by fetch, process, merge, YoY)
        folder_frame = ctk.CTkFrame(self.settings_tab)
        folder_frame.pack(pady=10, padx=20, fill="x")
        
        folder_label = ctk.CTkLabel(
            folder_frame,
            text="Report directories:",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        folder_label.pack(anchor="w", padx=10, pady=(10, 2))
        ctk.CTkLabel(
            folder_frame,
            text="Paths for raw downloads, processed files, merged CSVs, and YoY ready reports.",
            font=ctk.CTkFont(size=10),
            text_color="gray"
        ).pack(anchor="w", padx=10, pady=(0, 5))
        
        def add_dir_row(parent: ctk.CTkFrame, label: str, setting_key: str, default: str) -> ctk.CTkEntry:
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(pady=4, padx=10, fill="x")
            ctk.CTkLabel(row, text=label + ":", font=ctk.CTkFont(size=11)).pack(side="left", padx=(0, 10))
            entry = ctk.CTkEntry(row, width=300, font=ctk.CTkFont(size=11))
            entry.insert(0, self.settings.get(setting_key, default))
            entry.pack(side="left", padx=5, fill="x", expand=True)
            ctk.CTkButton(row, text="Browse", command=lambda e=entry: self._on_browse_folder(e), width=80, font=ctk.CTkFont(size=11)).pack(side="left", padx=5)
            return entry
        
        self.settings_raw_reports_entry = add_dir_row(folder_frame, "Raw reports", "raw_reports_dir", "raw_reports")
        self.settings_processed_reports_entry = add_dir_row(folder_frame, "Processed reports", "processed_reports_dir", "processed_reports")
        self.settings_merged_reports_entry = add_dir_row(folder_frame, "Merged reports", "merged_reports_dir", "merged_reports")
        self.settings_ready_reports_entry = add_dir_row(folder_frame, "Ready reports (YoY)", "ready_reports_dir", "ready_reports")
        
        # Save settings button
        save_settings_frame = ctk.CTkFrame(self.settings_tab)
        save_settings_frame.pack(pady=20, padx=20, fill="x")
        
        save_settings_btn = ctk.CTkButton(
            save_settings_frame,
            text="Save All Settings",
            command=self._on_save_all_settings,
            font=ctk.CTkFont(size=14, weight="bold"),
            height=40,
            fg_color="green",
            hover_color="darkgreen"
        )
        save_settings_btn.pack(pady=10, padx=20, fill="x")

        # Campaign Rules Manager (pack last with expand so it fills remaining space; scrolls if needed)
        self._create_campaign_rules_section()

    def _create_campaign_rules_section(self) -> None:
        """Build Campaign Rules Manager UI and load mappings.json."""
        rules_frame = ctk.CTkFrame(self.settings_tab)
        rules_frame.pack(pady=10, padx=20, fill="both", expand=True)

        # Sticky header: title, New Rule, Campaign Filter, and Save/Export stay at top; only the list scrolls
        sticky_header = ctk.CTkFrame(rules_frame, fg_color="transparent")
        sticky_header.pack(fill="x", pady=(0, 0))

        ctk.CTkLabel(
            sticky_header, text="Campaign Rules Manager",
            font=ctk.CTkFont(size=12, weight="bold")
        ).pack(anchor="w", padx=10, pady=(10, 2))
        ctk.CTkLabel(
            sticky_header,
            text="Rules map campaign names to funnel stage (Top, Bottom) or DELETE (exclude). Used by Process All Data. Stored in mappings.json.",
            font=ctk.CTkFont(size=10),
            text_color="gray"
        ).pack(anchor="w", padx=10, pady=(0, 2))
        ctk.CTkLabel(
            sticky_header,
            text="Auto-rules (in processor): names containing 'Brand' or 'Branded' → Bottom.",
            font=ctk.CTkFont(size=10),
            text_color="gray"
        ).pack(anchor="w", padx=10, pady=(0, 2))
        ctk.CTkLabel(
            sticky_header,
            text="Partial matches are supported. The system matches these keywords case-insensitively.",
            font=ctk.CTkFont(size=10),
            text_color="gray"
        ).pack(anchor="w", padx=10, pady=(0, 8))
        
        # --- New Rule section ---
        ctk.CTkLabel(
            sticky_header, text="New Rule",
            font=ctk.CTkFont(size=11, weight="bold")
        ).pack(anchor="w", padx=10, pady=(0, 4))
        ctk.CTkLabel(
            sticky_header,
            text="New rule — campaign keyword (e.g., Spring Sale Campaign):",
            font=ctk.CTkFont(size=10),
            text_color="gray"
        ).pack(anchor="w", padx=10, pady=(0, 2))
        add_row = ctk.CTkFrame(sticky_header, fg_color="transparent")
        add_row.pack(pady=(0, 4), padx=10, fill="x")
        self.mappings_add_campaign_var = ctk.StringVar(value="")
        self.mappings_add_campaign_entry = ctk.CTkEntry(
            add_row, textvariable=self.mappings_add_campaign_var,
            placeholder_text="e.g., Spring Sale Campaign or Advantage+", width=260, height=28
        )
        self.mappings_add_campaign_entry.pack(side="left", padx=(0, 8))
        self.mappings_add_stage_var = ctk.StringVar(value="Top")
        self.mappings_add_stage_menu = ctk.CTkOptionMenu(
            add_row, variable=self.mappings_add_stage_var,
            values=["Top", "Bottom", "DELETE"], width=100, height=28
        )
        self.mappings_add_stage_menu.pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            add_row, text="Save new rule", command=self._on_mappings_add,
            width=110, height=28, font=ctk.CTkFont(size=11),
            fg_color="#0066CC", hover_color="#0052A3"
        ).pack(side="left", padx=0)
        
        # --- Campaign Filter section (below New Rule) ---
        ctk.CTkLabel(
            sticky_header, text="Campaign Filter",
            font=ctk.CTkFont(size=11, weight="bold")
        ).pack(anchor="w", padx=10, pady=(10, 4))
        ctk.CTkLabel(
            sticky_header,
            text="Filter by campaign keyword or stage (e.g., Advantage+):",
            font=ctk.CTkFont(size=10),
            text_color="gray"
        ).pack(anchor="w", padx=10, pady=(0, 2))
        filter_row = ctk.CTkFrame(sticky_header, fg_color="transparent")
        filter_row.pack(pady=(0, 4), padx=10, fill="x")
        self.mappings_filter_var = ctk.StringVar(value="")
        self.mappings_filter_entry = ctk.CTkEntry(
            filter_row, textvariable=self.mappings_filter_var,
            placeholder_text="e.g., Advantage+", width=260, height=28
        )
        self.mappings_filter_entry.pack(side="left", padx=(0, 8))
        self.mappings_filter_var.trace_add("write", lambda *a: self._mappings_refresh_list())
        self.mappings_stage_filter_var = ctk.StringVar(value="All Stages")
        self.mappings_stage_filter_menu = ctk.CTkOptionMenu(
            filter_row, variable=self.mappings_stage_filter_var,
            values=["All Stages", "Top", "Bottom", "DELETE"], width=110, height=28
        )
        self.mappings_stage_filter_menu.pack(side="left", padx=(0, 8))
        self.mappings_stage_filter_var.trace_add("write", lambda *a: self._mappings_refresh_list())
        
        # Save + Export buttons (sticky at top; only the rules list scrolls)
        btn_row = ctk.CTkFrame(sticky_header, fg_color="transparent")
        btn_row.pack(pady=(6, 6), padx=10, fill="x")
        save_mappings_btn = ctk.CTkButton(
            btn_row, text="Save New Rule",
            command=self._on_mappings_save,
            width=180, height=32, font=ctk.CTkFont(size=11),
            fg_color="green", hover_color="darkgreen"
        )
        save_mappings_btn.pack(side="left", padx=(0, 10))
        ctk.CTkButton(
            btn_row, text="Export to CSV",
            command=self._on_mappings_export_csv,
            width=120, height=32, font=ctk.CTkFont(size=11),
            fg_color="gray", hover_color="darkgray"
        ).pack(side="left", padx=0)
        
        # Rules list: only this part scrolls; sticky header stays pinned above
        rules_list_container = ctk.CTkFrame(rules_frame, fg_color="transparent")
        rules_list_container.pack(pady=(6, 10), padx=10, fill="both", expand=True)
        self.mappings_rules_scroll = ctk.CTkScrollableFrame(rules_list_container, height=200, fg_color="transparent")
        self.mappings_rules_scroll.pack(fill="both", expand=True)

        def _on_rules_list_container_configure(event) -> None:
            h = max(100, event.height)
            if self.mappings_rules_scroll.winfo_exists() and self.mappings_rules_scroll.cget("height") != h:
                self.mappings_rules_scroll.configure(height=h)

        rules_list_container.bind("<Configure>", _on_rules_list_container_configure)

        self._load_mappings_file()
        self._mappings_refresh_list()
    
    def _load_mappings_file(self) -> None:
        """Load mappings from mappings.json into _mappings_data."""
        try:
            if self._mappings_file.exists():
                with open(self._mappings_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._mappings_data = {str(k): str(v) for k, v in (data or {}).items()}
            else:
                self._mappings_data = {}
        except json.JSONDecodeError as e:
            self.logger.error(f"mappings.json is corrupted (invalid JSON): {e}", exc_info=True)
            self._mappings_data = {}
            self.status_text.set("mappings.json was corrupted; using empty rules. Backup or delete and restart.")
        except OSError as e:
            self.logger.error(f"Error reading mappings.json: {e}", exc_info=True)
            self._mappings_data = {}
    
    def _save_mappings_file(self) -> None:
        """Write _mappings_data to mappings.json."""
        try:
            with open(self._mappings_file, "w", encoding="utf-8") as f:
                json.dump(self._mappings_data, f, indent=2, ensure_ascii=False)
            self.logger.info(f"Saved {len(self._mappings_data)} campaign rules to mappings.json")
            self.status_text.set(f"Saved {len(self._mappings_data)} rules to mappings.json")
        except Exception as e:
            self.logger.error(f"Error saving mappings: {e}", exc_info=True)
            self.status_text.set(f"Error saving mappings: {e}")
    
    def _mappings_refresh_list(self) -> None:
        """Rebuild the rules list UI from _mappings_data, applying text and stage filters. Sorted by campaign name (case-insensitive)."""
        for w in self.mappings_rules_scroll.winfo_children():
            w.destroy()
        filter_text = (self.mappings_filter_var.get() or "").strip().lower()
        stage_filter = (self.mappings_stage_filter_var.get() or "All Stages").strip()
        # Alphabetize by campaign name (case-insensitive)
        items = sorted(self._mappings_data.items(), key=lambda x: x[0].lower())
        shown = 0
        for campaign, stage in items:
            if filter_text and filter_text not in campaign.lower() and filter_text not in (stage or "").lower():
                continue
            if stage_filter != "All Stages" and stage != stage_filter:
                continue
            shown += 1
            # Subtle row bg for tracking; hover darkens slightly
            row_bg = ("#e8e8e8", "#353535")
            row_hover_bg = ("#d8d8d8", "#454545")
            row = ctk.CTkFrame(self.mappings_rules_scroll, fg_color=row_bg, corner_radius=4)
            row.pack(fill="x", pady=2)
            def _hover_on(r, bg=row_bg, hover=row_hover_bg):
                r.configure(fg_color=hover)
            def _hover_off(r, bg=row_bg):
                r.configure(fg_color=bg)
            row.bind("<Enter>", lambda e, r=row: _hover_on(r))
            row.bind("<Leave>", lambda e, r=row: _hover_off(r))
            disp_name = campaign if len(campaign) <= 52 else campaign[:49] + "..."
            ctk.CTkLabel(row, text=disp_name, font=ctk.CTkFont(size=10), anchor="w").pack(side="left", padx=(6, 8), pady=4, fill="x", expand=True)
            ctk.CTkLabel(row, text=stage, font=ctk.CTkFont(size=10), width=60, anchor="w").pack(side="left", padx=(0, 8), pady=4)
            ctk.CTkButton(row, text="Edit", width=50, height=24, font=ctk.CTkFont(size=10), command=lambda c=campaign: self._on_mappings_edit(c)).pack(side="left", padx=2, pady=2)
            ctk.CTkButton(row, text="Delete", width=50, height=24, font=ctk.CTkFont(size=10), fg_color="red", hover_color="darkred", command=lambda c=campaign: self._on_mappings_delete(c)).pack(side="left", padx=2, pady=2)
        if shown == 0:
            no_match = ctk.CTkLabel(
                self.mappings_rules_scroll,
                text="No matching rules found",
                font=ctk.CTkFont(size=11),
                text_color="gray"
            )
            no_match.pack(expand=True, pady=40)
    
    def _on_mappings_add(self) -> None:
        """Add a new rule from the Add row. Case-insensitive: replaces any existing rule with same campaign name."""
        self.root.update_idletasks()
        campaign = self.mappings_add_campaign_var.get().strip()
        if not campaign:
            self.status_text.set("Error: Enter a campaign name")
            return
        stage = self.mappings_add_stage_var.get().strip()
        if stage not in ("Top", "Bottom", "DELETE"):
            stage = "Top"
        # Replace any existing key that matches case-insensitively
        existing = next((k for k in self._mappings_data if k.lower() == campaign.lower()), None)
        if existing is not None:
            del self._mappings_data[existing]
            self.status_text.set("Rule updated (replaced existing). Click Save to write file.")
        else:
            self.status_text.set(f"Added rule: {campaign} → {stage} (click Save to write file)")
        self._mappings_data[campaign] = stage
        self.mappings_add_campaign_var.set("")
        self._mappings_refresh_list()
    
    def _on_mappings_edit(self, campaign: str) -> None:
        """Edit an existing rule via dialog. Uses wait_window so the main thread stays responsive (no blocking with Event)."""
        current_stage = self._mappings_data.get(campaign, "Top")
        result = {"campaign": campaign, "stage": current_stage}
        
        d = ctk.CTkToplevel(self.root)
        d.title("Edit Campaign Rule")
        d.geometry("420x180")
        d.transient(self.root)
        d.grab_set()
        ctk.CTkLabel(d, text="Campaign name:", font=ctk.CTkFont(size=11)).pack(anchor="w", padx=15, pady=(15, 4))
        name_entry = ctk.CTkEntry(d, width=380, height=28)
        name_entry.pack(padx=15, pady=(0, 10), fill="x")
        name_entry.insert(0, campaign)
        ctk.CTkLabel(d, text="Funnel stage:", font=ctk.CTkFont(size=11)).pack(anchor="w", padx=15, pady=(8, 4))
        stage_var = ctk.StringVar(value=current_stage)
        stage_menu = ctk.CTkOptionMenu(d, variable=stage_var, values=["Top", "Bottom", "DELETE"], width=120)
        stage_menu.pack(anchor="w", padx=15, pady=(0, 15))
        
        def on_ok() -> None:
            result["campaign"] = name_entry.get().strip()
            result["stage"] = stage_var.get().strip()
            if result["stage"] not in ("Top", "Bottom", "DELETE"):
                result["stage"] = "Top"
            d.destroy()
        
        def on_cancel() -> None:
            result["campaign"] = ""
            d.destroy()
        
        btn_frame = ctk.CTkFrame(d, fg_color="transparent")
        btn_frame.pack(pady=10, padx=15)
        ctk.CTkButton(btn_frame, text="OK", command=on_ok, width=80).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="Cancel", command=on_cancel, width=80, fg_color="gray").pack(side="left", padx=5)
        
        d.wait_window(d)
        new_campaign = (result.get("campaign") or "").strip()
        new_stage = result.get("stage") or "Top"
        if not new_campaign:
            return
        # Remove any key that matches old or new campaign name case-insensitively (consolidate)
        to_remove = [k for k in self._mappings_data if k.lower() == campaign.lower() or k.lower() == new_campaign.lower()]
        for k in to_remove:
            del self._mappings_data[k]
        self._mappings_data[new_campaign] = new_stage
        self._mappings_refresh_list()
        self.status_text.set(f"Updated rule (click Save to write file)")
    
    def _on_mappings_delete(self, campaign: str) -> None:
        """Remove a rule."""
        if campaign in self._mappings_data:
            del self._mappings_data[campaign]
            self._mappings_refresh_list()
            self.status_text.set(f"Removed rule: {campaign} (click Save to write file)")
    
    def _on_mappings_save(self) -> None:
        """Persist _mappings_data to mappings.json."""
        self._save_mappings_file()
    
    def _on_mappings_export_csv(self) -> None:
        """Export current rules (filtered view) to a CSV file via file dialog. Columns: Campaign Name, Funnel Stage."""
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            title="Export campaign rules to CSV"
        )
        if not path:
            return
        filter_text = (self.mappings_filter_var.get() or "").strip().lower()
        stage_filter = (self.mappings_stage_filter_var.get() or "All Stages").strip()
        items = sorted(self._mappings_data.items(), key=lambda x: x[0].lower())
        rows = []
        for campaign, stage in items:
            if filter_text and filter_text not in campaign.lower() and filter_text not in (stage or "").lower():
                continue
            if stage_filter != "All Stages" and stage != stage_filter:
                continue
            rows.append((campaign, stage))
        try:
            import csv
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["Campaign Name", "Funnel Stage"])
                w.writerows(rows)
            self.status_text.set(f"Exported {len(rows)} rules to {path}")
            self.logger.info(f"Exported {len(rows)} campaign rules to {path}")
        except Exception as e:
            self.logger.error(f"Export CSV error: {e}", exc_info=True)
            self.status_text.set(f"Error exporting: {e}")
    
    def _restrict_file_permissions(self, path: Path) -> None:
        """Restrict file to owner-only read/write (0o600). Best-effort; may no-op on some systems."""
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    def _save_settings(self) -> None:
        """Save settings to config.json file (under app dir)."""
        try:
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=2, ensure_ascii=False)
            self._restrict_file_permissions(self.settings_file)
            self.logger.info("Settings saved successfully")
        except Exception as e:
            self.logger.error(f"Error saving settings: {e}", exc_info=True)
    
    def _on_google_default_favorite_changed(self, choice: str) -> None:
        """Handle Google default favorite change in settings."""
        if choice == "None":
            self.settings["default_google_favorite"] = None
        else:
            self.settings["default_google_favorite"] = choice
        self._save_settings()
        self.logger.info(f"Google Ads default favorite set to: {choice}")
        if choice != "None" and self.favorites:
            for f in self.favorites:
                if f.get("name") == choice and f.get("customer_id"):
                    self.customer_id.set(f["customer_id"].strip())
                    self._set_google_id_display_from_id()
                    break
    
    def _on_meta_default_favorite_changed(self, choice: str) -> None:
        """Handle Meta default favorite change in settings."""
        if choice == "None":
            self.settings["default_meta_favorite"] = None
        else:
            self.settings["default_meta_favorite"] = choice
        self._save_settings()
        self.logger.info(f"Meta Ads default favorite set to: {choice}")
        if choice != "None" and self.meta_favorites:
            for f in self.meta_favorites:
                if f.get("name") == choice and f.get("account_id"):
                    self.meta_account_id.set(f["account_id"].strip())
                    self._set_meta_id_display_from_id()
                    break
    
    def _on_theme_mode_changed(self, choice: str) -> None:
        """Handle theme mode change in settings."""
        self.settings["theme_mode"] = choice
        ctk.set_appearance_mode(choice)
        self._save_settings()
        self.logger.info(f"Theme mode changed to: {choice}")
        self.status_text.set(f"Theme changed to {choice} mode")
    
    def _on_browse_folder(self, entry: ctk.CTkEntry) -> None:
        """Browse for a directory and put its path into the given entry."""
        folder = filedialog.askdirectory(title="Select directory")
        if folder:
            entry.delete(0, "end")
            entry.insert(0, folder)
    
    def _on_save_all_settings(self) -> None:
        """Save all settings including report directories."""
        self.settings["raw_reports_dir"] = self.settings_raw_reports_entry.get().strip() or "raw_reports"
        self.settings["processed_reports_dir"] = self.settings_processed_reports_entry.get().strip() or "processed_reports"
        self.settings["merged_reports_dir"] = self.settings_merged_reports_entry.get().strip() or "merged_reports"
        self.settings["ready_reports_dir"] = self.settings_ready_reports_entry.get().strip() or "ready_reports"
        self._save_settings()
        self.status_text.set("All settings saved successfully")
        self.logger.info("All settings saved")
    
    def _animate_process_spinner(self) -> None:
        """Animate the spinner dots during processing."""
        if not hasattr(self, 'process_spinner_active') or not self.process_spinner_active:
            return
        
        spinner_chars = ["●", "○", "◐", "◑", "◒", "◓"]
        if not hasattr(self, 'process_spinner_index'):
            self.process_spinner_index = 0
        
        self.process_spinner_label.configure(text=spinner_chars[self.process_spinner_index % len(spinner_chars)])
        self.process_spinner_index += 1
        self.root.after(150, self._animate_process_spinner)
    
    def _create_shared_log_area(self) -> ctk.CTkFrame:
        """Create Live Log frame (caller grids it at bottom with sticky=ew). Returns the log frame."""
        log_frame = ctk.CTkFrame(self.root)

        # Header with label and Export button
        log_header_frame = ctk.CTkFrame(log_frame, fg_color="transparent")
        log_header_frame.pack(pady=(6, 2), padx=10, fill="x")
        
        log_label = ctk.CTkLabel(
            log_header_frame,
            text="Live Log:",
            font=ctk.CTkFont(size=11, weight="bold")
        )
        log_label.pack(side="left", padx=10)
        
        self.log_export_button = ctk.CTkButton(
            log_header_frame,
            text="Export to .txt",
            command=self._on_export_log_clicked,
            font=ctk.CTkFont(size=11),
            height=25,
            width=100,
            fg_color="#4CAF50",
            hover_color="#45a049"
        )
        self.log_export_button.pack(side="right", padx=10)
        
        # Increased height (16 lines) for more log visibility after removing checklist
        self.log_textbox = scrolledtext.ScrolledText(
            log_frame,
            height=16,
            wrap="word",
            font=("Consolas", 9),
            bg="#212121",
            fg="#FFFFFF",
            insertbackground="#FFFFFF"
        )
        self.log_textbox.pack(pady=(0, 6), padx=10, fill="x")
        return log_frame

    def _on_export_log_clicked(self) -> None:
        """Export log content to a text file."""
        try:
            log_content = self.log_textbox.get("1.0", "end-1c")
            if not log_content.strip():
                self.status_text.set("Log is empty, nothing to export")
                return
            
            # Ask user for save location
            filename = filedialog.asksaveasfilename(
                defaultextension=".txt",
                filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
                title="Export Log to Text File"
            )
            
            if filename:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(log_content)
                self.status_text.set(f"Log exported to: {filename}")
                self.logger.info(f"Log exported to: {filename}")
        except Exception as e:
            error_msg = f"Error exporting log: {str(e)}"
            self.status_text.set(error_msg)
            self.logger.error(error_msg, exc_info=True)
    
    def _get_main_date_range(self) -> Tuple[datetime, datetime]:
        """Return (start_date, end_date) from Main tab: calendars if available, else month/year dropdowns."""
        if Calendar is not None and self.main_start_cal is not None and self.main_end_cal is not None:
            start_d = self.main_start_cal.get_date()
            end_d = self.main_end_cal.get_date()
            if isinstance(start_d, str):
                start_date = datetime.strptime(start_d, "%Y-%m-%d")
            else:
                start_date = datetime.combine(start_d, datetime.min.time())
            if isinstance(end_d, str):
                end_date = datetime.strptime(end_d, "%Y-%m-%d")
            else:
                end_date = datetime.combine(end_d, datetime.min.time())
            return (start_date, end_date)
        start_year = int(self.start_year.get())
        start_month_num = self._month_name_to_number(self.start_month.get())
        end_year = int(self.end_year.get())
        end_month_num = self._month_name_to_number(self.end_month.get())
        start_date = datetime(start_year, start_month_num, 1)
        if end_month_num == 12:
            end_date = datetime(end_year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = datetime(end_year, end_month_num + 1, 1) - timedelta(days=1)
        return (start_date, end_date)

    def _set_main_dates_default(self) -> None:
        """Set Main tab start/end calendar to default: first of current month through today."""
        if Calendar is None or self.main_start_cal is None or self.main_end_cal is None:
            return
        now = datetime.now()
        start = datetime(now.year, now.month, 1)
        end = now if now.day > 1 else start
        self.main_start_cal.selection_set(start.date())
        self.main_end_cal.selection_set(end.date())

    def _month_name_to_number(self, month_name: str) -> int:
        """Convert month name to number (1-12)."""
        try:
            return self.month_names.index(month_name) + 1
        except ValueError:
            return 1
    
    def _validate_date_only(self) -> Tuple[bool, Optional[str]]:
        """Validate date range only (no account ID)."""
        try:
            start_date, end_date = self._get_main_date_range()
            if start_date > end_date:
                return False, "Start date must be before or equal to end date"
            return True, None
        except (ValueError, TypeError, Exception) as e:
            return False, f"Invalid date values: {e}"
    
    def _confirm_date_range_global(self) -> None:
        """Lock the global date range for all platforms."""
        is_valid, error_msg = self._validate_date_only()
        if not is_valid:
            self.status_text.set(f"Error: {error_msg}")
            return
        self.date_range_locked = True
        self.meta_date_range_locked = True
        if Calendar is not None and self.main_start_cal is not None and self.main_end_cal is not None:
            self.main_pull_prior_year_cb.configure(state="disabled")
            try:
                self.main_start_cal.configure(state="disabled")
            except Exception:
                pass
            try:
                self.main_end_cal.configure(state="disabled")
            except Exception:
                pass
        else:
            self.start_month_menu.configure(state="disabled")
            self.start_year_menu.configure(state="disabled")
            self.end_month_menu.configure(state="disabled")
            self.end_year_menu.configure(state="disabled")
        self.confirm_date_btn.configure(text="Date Range Locked", state="disabled")
        self.unlock_date_btn.configure(state="normal")
        # Meta retention: show warning in Meta card if start date is older than 37 months
        start_date, _ = self._get_main_date_range()
        meta_cutoff = (datetime.now() - relativedelta(months=META_RETENTION_MONTHS)).replace(day=1)
        if start_date < meta_cutoff:
            cutoff_display = meta_cutoff.strftime("%B %Y")
            self.meta_retention_warning_label.configure(
                text=f"Meta only supports data for the last {META_RETENTION_MONTHS} months. Dates prior to {cutoff_display} will be skipped."
            )
            self.meta_retention_warning_label.pack(anchor="w", padx=10, pady=(0, 4))
        else:
            self.meta_retention_warning_label.pack_forget()
        is_valid_google, _ = self._validate_inputs()
        is_valid_meta, _ = self._validate_meta_inputs()
        self.status_text.set("Date range confirmed for all platforms")
        self.logger.info("Date range confirmed (global)")
        self._update_checklist_statuses()
    
    def _unlock_date_range_global(self) -> None:
        """Unlock the global date range for editing."""
        self.date_range_locked = False
        self.meta_date_range_locked = False
        self.meta_retention_warning_label.pack_forget()
        if Calendar is not None and self.main_start_cal is not None and self.main_end_cal is not None:
            self.main_pull_prior_year_cb.configure(state="normal")
            try:
                self.main_start_cal.configure(state="normal")
            except Exception:
                pass
            try:
                self.main_end_cal.configure(state="normal")
            except Exception:
                pass
        else:
            self.start_month_menu.configure(state="normal")
            self.start_year_menu.configure(state="normal")
            self.end_month_menu.configure(state="normal")
            self.end_year_menu.configure(state="normal")
        self.confirm_date_btn.configure(text="Confirm Date Range", state="normal")
        self.unlock_date_btn.configure(state="disabled")
        self.status_text.set("Date range unlocked for editing")
        self.logger.info("Date range unconfirmed (global)")
        self._update_checklist_statuses()
    
    def _confirm_date_range(self) -> None:
        self._confirm_date_range_global()
    
    def _unlock_date_range(self) -> None:
        self._unlock_date_range_global()
    
    def _confirm_meta_date_range(self) -> None:
        self._confirm_date_range_global()
    
    def _unlock_meta_date_range(self) -> None:
        self._unlock_date_range_global()
    
    def _validate_inputs(self) -> Tuple[bool, Optional[str]]:
        """Validate user inputs."""
        customer_id = self.customer_id.get().strip()
        if not customer_id:
            return False, "Please enter a Customer ID"
        
        customer_id_clean = customer_id.replace("-", "")
        if not customer_id_clean.isdigit() or len(customer_id_clean) != 10:
            return False, "Customer ID must be a 10-digit number"
        
        try:
            start_date, end_date = self._get_main_date_range()
            if start_date > end_date:
                return False, "Start date must be before or equal to end date"
            return True, None
        except (ValueError, Exception) as e:
            return False, f"Invalid date values: {e}"

    def _validate_meta_inputs(self) -> Tuple[bool, Optional[str]]:
        """Validate Meta Ads inputs."""
        account_id = self.meta_account_id.get().strip()
        if not account_id or account_id == "act_":
            return False, "Please enter a valid Ad Account ID"
        
        if not account_id.startswith("act_"):
            return False, "Ad Account ID must start with 'act_'"
        
        try:
            start_date, end_date = self._get_main_date_range()
            if start_date > end_date:
                return False, "Start date must be before or equal to end date"
            
            return True, None
            
        except ValueError as e:
            return False, f"Invalid date values: {e}"
    
    def _on_start_clicked(self) -> None:
        """Handle start button click."""
        if self.is_processing:
            self.logger.warning("Already processing, ignoring start request")
            return
        
        if not self.date_range_locked:
            self.status_text.set("Error: Please confirm date range before starting")
            return
        
        is_valid, error_msg = self._validate_inputs()
        if not is_valid:
            self.status_text.set(f"Error: {error_msg}")
            return
        
        self.cancel_event.clear()
        self.is_processing = True
        self.progress_bar.set(0)
        self.status_text.set("Initializing Google Ads fetch...")
        
        thread = threading.Thread(target=self.start_google_fetch_thread, daemon=True)
        thread.start()
    
    def _on_stop_clicked(self) -> None:
        """Handle stop button click."""
        if self.is_processing:
            self.cancel_event.set()
            self.status_text.set("Stopping... Please wait")
            self.logger.info("Stop requested by user")
    
    def _on_clear_data_clicked(self) -> None:
        """Handle clear data button click."""
        self._clear_all_data()
    
    def _on_process_all_data_clicked(self) -> None:
        """Handle Process All Data button click - process and merge all existing data."""
        if self.is_processing or self.meta_is_processing:
            self.status_text.set("Cannot process files while fetching is in progress")
            return
        
        self.process_all_data_button.configure(state="disabled")
        self.status_text.set("Starting full data processing pipeline...")
        self.logger.info("Process All Data: Starting full pipeline (process + merge)")
        
        def process_thread() -> None:
            try:
                def status_callback(message: str):
                    self.root.after(0, lambda msg=message: self.status_text.set(msg))
                    self.logger.info(f"Processing: {message}")
                
                def user_input_callback(campaign_name: str) -> str:
                    """Callback to get user input for campaign classification."""
                    return self._show_funnel_dialog(campaign_name)
                
                raw_dir = self.settings.get("raw_reports_dir", "raw_reports")
                processed_dir = self.settings.get("processed_reports_dir", "processed_reports")
                merged_dir = self.settings.get("merged_reports_dir", "merged_reports")
                ready_dir = self.settings.get("ready_reports_dir", "ready_reports")
                processor = ReportProcessor(
                    input_dir=raw_dir,
                    output_dir=processed_dir,
                    merged_dir=merged_dir,
                    ready_dir=ready_dir,
                    status_callback=status_callback,
                    user_input_callback=user_input_callback
                )
                
                # Process all files
                processor.process_all()
                
                # Merge platform data
                self.logger.info("Process All Data: Merging platform data...")
                self.root.after(0, lambda: self.status_text.set("Merging platform data..."))
                processor.merge_platform_data()
                
                # Build YoY reports (ready_reports/)
                self.logger.info("Process All Data: Building YoY reports...")
                self.root.after(0, lambda: self.status_text.set("Building YoY reports..."))
                processor.build_yoy_reports()
                
                self.logger.info("Process All Data: Complete!")
                self.root.after(0, lambda: self.status_text.set("Processing Complete!"))
                self.root.after(0, lambda: self._update_checklist_statuses())
                
            except Exception as e:
                error_msg = f"Error during processing: {str(e)}"
                self.logger.error(f"Error in Process All Data: {e}", exc_info=True)
                self.root.after(0, lambda: self.status_text.set(error_msg))
            finally:
                self.root.after(0, lambda: self.process_all_data_button.configure(state="normal"))
        
        thread = threading.Thread(target=process_thread, daemon=True)
        thread.start()
    
    def _on_run_all_clicked(self) -> None:
        """Handle Run All button click."""
        if self.is_processing or self.meta_is_processing:
            self.status_text.set("Error: Already processing. Please wait for current operation to complete.")
            return
        
        self.run_all_fetches()
    
    def run_all_fetches(self) -> None:
        """
        Execute batch fetch across all platforms.
        Only downloads platforms that are ready (ID and date range locked).
        Chains: Fetch ready platforms → Process → Merge
        """
        # Update checklist to show current status
        self._update_checklist_statuses()
        
        # Check which platforms are selected and ready (selected + valid ID + date range confirmed)
        is_valid_google, _ = self._validate_inputs()
        is_valid_meta, _ = self._validate_meta_inputs()
        ms_cid = (self.ms_customer_id.get() or "").strip().replace("-", "").replace(" ", "")
        is_valid_ms = bool(ms_cid and ms_cid.isdigit())
        ms_config_exists = (_APP_DIR / "microsoft-ads.yaml").exists()
        tiktok_config_exists = (_APP_DIR / "tiktok-ads.yaml").exists()
        pinterest_config_exists = (_APP_DIR / "pinterest-ads.yaml").exists()
        google_selected = self.source_google_var.get()
        meta_selected = self.source_meta_var.get()
        ms_selected = self.source_ms_var.get()
        google_ready = google_selected and is_valid_google and self.date_range_locked
        meta_ready = meta_selected and is_valid_meta and self.meta_date_range_locked
        tiktok_selected = self.source_tiktok_var.get()
        reddit_selected = self.source_reddit_var.get()
        pinterest_selected = self.source_pinterest_var.get()
        ms_ready = ms_selected and is_valid_ms and self.date_range_locked and ms_config_exists
        tiktok_ready = tiktok_selected and self.date_range_locked and bool((self.tiktok_account_id.get() or "").strip()) and tiktok_config_exists
        reddit_ready = reddit_selected and self.date_range_locked and bool((self.reddit_account_id.get() or "").strip())
        pinterest_ready = pinterest_selected and self.date_range_locked and bool((self.pinterest_account_id.get() or "").strip()) and pinterest_config_exists

        # Check data status (raw platform dirs, merged_reports, ready_reports)
        raw_dir = Path(self.settings.get("raw_reports_dir", "raw_reports"))
        merged_dir = Path(self.settings.get("merged_reports_dir", "merged_reports"))
        ready_dir = Path(self.settings.get("ready_reports_dir", "ready_reports"))
        has_data = False
        if raw_dir.exists():
            for d in raw_dir.iterdir():
                if d.is_dir() and any(d.glob("*.csv")):
                    has_data = True
                    break
        if not has_data and merged_dir.exists() and any(merged_dir.glob("*.csv")):
            has_data = True
        if not has_data and ready_dir.exists() and any(ready_dir.glob("*.csv")):
            has_data = True

        # At least one selected platform must be ready (data may exist; we allow run and overwrite)
        any_platform_ready = google_ready or meta_ready or ms_ready or tiktok_ready or reddit_ready or pinterest_ready
        any_platform_selected = google_selected or meta_selected or ms_selected or tiktok_selected or reddit_selected or pinterest_selected
        all_ready = any_platform_ready

        if not all_ready:
            missing_items = []
            if google_selected and not google_ready:
                missing_items.append("Google Ads (confirm Customer ID and Date Range)")
            if meta_selected and not meta_ready:
                missing_items.append("Meta Ads (confirm Account ID and Date Range)")
            if ms_selected and not ms_ready:
                if is_valid_ms and self.date_range_locked and not ms_config_exists:
                    missing_items.append("Microsoft Ads (run setup_ms_auth.py; config missing)")
                else:
                    missing_items.append("Microsoft Ads (confirm Customer ID and Date Range)")
            if tiktok_selected and not tiktok_ready:
                if (self.tiktok_account_id.get() or "").strip() and not tiktok_config_exists:
                    missing_items.append("TikTok Ads (add tiktok-ads.yaml; see PLATFORM_STATUS.md)")
                else:
                    missing_items.append("TikTok Ads (confirm Advertiser ID and Date Range)")
            if reddit_selected and not reddit_ready:
                missing_items.append("Reddit Ads (confirm Account ID and Date Range)")
            if pinterest_selected and not pinterest_ready:
                if (self.pinterest_account_id.get() or "").strip() and not pinterest_config_exists:
                    missing_items.append("Pinterest Ads (add pinterest-ads.yaml; see PLATFORM_STATUS.md)")
                else:
                    missing_items.append("Pinterest Ads (confirm Advertiser ID and Date Range)")
            if not any_platform_selected:
                missing_items.append("Select at least one platform")

            message = "Cannot run pipeline. Please complete the following:\n\n" + "\n".join(f"• {item}" for item in missing_items)
            messagebox.showwarning("Pipeline Not Ready", message)
            self.status_text.set("Pipeline not ready - see popup for details")
            return

        # When data exists, let user confirm before overwriting (same date-range files get overwritten)
        if has_data:
            result = messagebox.askyesno(
                "Data Already Exists",
                "Data already exists in raw/processed/merged folders. "
                "The new fetch will overwrite files for the same date range(s). "
                "You can use 'Clear All Data' first if you want a clean slate.\n\n"
                "Continue with fetch?",
                icon="question"
            )
            if not result:
                self.status_text.set("Pipeline cancelled")
                return

        self.logger.info("Starting Full Pipeline...")
        self.logger.info(f"Platforms ready: Google={google_ready}, Meta={meta_ready}, MS={ms_ready}, TikTok={tiktok_ready}, Reddit={reddit_ready}, Pinterest={pinterest_ready}")
        self.status_text.set("Starting Full Pipeline...")
        self.batch_fetch_active = True
        self.run_full_pipeline_button.configure(state="disabled")
        
        # Show pipeline progress bar (lives under header status row)
        self.root.after(0, lambda: self.pipeline_progress_frame.pack(side="left"))
        self.root.after(0, lambda: self.pipeline_progress_bar.set(0))
        self.root.after(0, lambda: self.pipeline_status_label.configure(text="Initializing pipeline..."))
        
        # Run batch fetch in a thread
        batch_thread = threading.Thread(target=self._execute_batch_fetch, daemon=True)
        batch_thread.start()
    
    def _execute_batch_fetch(self) -> None:
        """
        Execute the batch fetch sequence.
        Only runs platforms that are selected and ready (valid ID + date range confirmed).
        """
        try:
            is_valid_google, _ = self._validate_inputs()
            is_valid_meta, _ = self._validate_meta_inputs()
            ms_cid = (self.ms_customer_id.get() or "").strip().replace("-", "").replace(" ", "")
            is_valid_ms = bool(ms_cid and ms_cid.isdigit())
            ms_config_exists = (_APP_DIR / "microsoft-ads.yaml").exists()
            tiktok_config_exists = (_APP_DIR / "tiktok-ads.yaml").exists()
            pinterest_config_exists = (_APP_DIR / "pinterest-ads.yaml").exists()
            # Only run platforms that are selected, ready (valid ID + date range), and have config when required
            google_ready = self.source_google_var.get() and is_valid_google and self.date_range_locked
            meta_ready = self.source_meta_var.get() and is_valid_meta and self.meta_date_range_locked
            ms_ready = self.source_ms_var.get() and is_valid_ms and self.date_range_locked and ms_config_exists
            tiktok_ready = self.source_tiktok_var.get() and self.date_range_locked and bool((self.tiktok_account_id.get() or "").strip()) and tiktok_config_exists
            reddit_ready = self.source_reddit_var.get() and self.date_range_locked and bool((self.reddit_account_id.get() or "").strip())
            pinterest_ready = self.source_pinterest_var.get() and self.date_range_locked and bool((self.pinterest_account_id.get() or "").strip()) and pinterest_config_exists

            # Skip platforms with missing config (log so user knows)
            if self.source_ms_var.get() and is_valid_ms and self.date_range_locked and not ms_config_exists:
                self.logger.info("Skipping Microsoft Ads: microsoft-ads.yaml not found. Run setup_ms_auth.py first.")
            if self.source_tiktok_var.get() and (self.tiktok_account_id.get() or "").strip() and not tiktok_config_exists:
                self.logger.info("Skipping TikTok Ads: tiktok-ads.yaml not found. See PLATFORM_STATUS.md.")
            if self.source_pinterest_var.get() and (self.pinterest_account_id.get() or "").strip() and not pinterest_config_exists:
                self.logger.info("Skipping Pinterest Ads: pinterest-ads.yaml not found. See PLATFORM_STATUS.md.")

            # Build fetch sequence only for selected + ready platforms (loop through GUI selection)
            fetch_sequence = []
            if google_ready:
                fetch_sequence.append(("Google Ads", self._run_google_fetch_in_batch))
            if meta_ready:
                fetch_sequence.append(("Meta Ads", self._run_meta_fetch_in_batch))
            if ms_ready:
                fetch_sequence.append(("Microsoft Ads", self._run_ms_fetch_in_batch))
            if tiktok_ready:
                fetch_sequence.append(("TikTok Ads", self._run_tiktok_fetch_in_batch))
            if reddit_ready:
                fetch_sequence.append(("Reddit Ads", self._run_reddit_fetch_in_batch))
            if pinterest_ready:
                fetch_sequence.append(("Pinterest Ads", self._run_pinterest_fetch_in_batch))

            total_steps = len(fetch_sequence) + 1  # +1 for processing
            current_step = 0
            
            self.logger.info(f"Pipeline: Running {len(fetch_sequence)} platform(s) and processing")
            
            # Execute each ready platform
            for platform_name, fetch_func in fetch_sequence:
                if not self.batch_fetch_active:
                    self.logger.warning("Pipeline cancelled")
                    break
                
                current_step += 1
                progress = current_step / total_steps
                self.root.after(0, lambda p=progress, pn=platform_name: (
                    self.pipeline_progress_bar.set(p),
                    self.pipeline_status_label.configure(text=f"Fetching {pn}...")
                ))
                
                self.logger.info(f"Pipeline: Starting {platform_name}...")
                self.root.after(0, lambda pn=platform_name: self.status_text.set(f"Pipeline: Fetching {pn}..."))
                
                # Execute fetch and wait for completion
                fetch_func()
                
                # Wait for this platform to complete
                if platform_name == "Google Ads":
                    self.google_fetch_complete.wait(timeout=PIPELINE_FETCH_WAIT_SECONDS)
                    self.google_fetch_complete.clear()
                elif platform_name == "Meta Ads":
                    self.meta_fetch_complete.wait(timeout=PIPELINE_FETCH_WAIT_SECONDS)
                    self.meta_fetch_complete.clear()
                elif platform_name == "Microsoft Ads":
                    self.ms_fetch_complete.wait(timeout=PIPELINE_FETCH_WAIT_SECONDS)
                    self.ms_fetch_complete.clear()
                elif platform_name == "TikTok Ads":
                    self.tiktok_fetch_complete.wait(timeout=PIPELINE_FETCH_WAIT_SECONDS)
                    self.tiktok_fetch_complete.clear()
                elif platform_name == "Reddit Ads":
                    self.reddit_fetch_complete.wait(timeout=PIPELINE_FETCH_WAIT_SECONDS)
                    self.reddit_fetch_complete.clear()
                elif platform_name == "Pinterest Ads":
                    self.pinterest_fetch_complete.wait(timeout=PIPELINE_FETCH_WAIT_SECONDS)
                    self.pinterest_fetch_complete.clear()

                if not self.batch_fetch_active:
                    break
            
            # Process all files after fetching
            if self.batch_fetch_active:
                current_step += 1
                progress = current_step / total_steps
                self.root.after(0, lambda p=progress: (
                    self.pipeline_progress_bar.set(p),
                    self.pipeline_status_label.configure(text="Processing files...")
                ))
                
                self.logger.info("Pipeline: Starting file processing...")
                self.root.after(0, lambda: self.status_text.set("Pipeline: Processing files..."))
                
                try:
                    def status_callback(message: str):
                        self.root.after(0, lambda msg=message: self.status_text.set(msg))
                        self.logger.info(f"Processing: {message}")
                    
                    def user_input_callback(campaign_name: str) -> str:
                        """Callback to get user input for campaign classification."""
                        return self._show_funnel_dialog(campaign_name)
                    
                    raw_dir = self.settings.get("raw_reports_dir", "raw_reports")
                    processed_dir = self.settings.get("processed_reports_dir", "processed_reports")
                    merged_dir = self.settings.get("merged_reports_dir", "merged_reports")
                    ready_dir = self.settings.get("ready_reports_dir", "ready_reports")
                    processor = ReportProcessor(
                        input_dir=raw_dir,
                        output_dir=processed_dir,
                        merged_dir=merged_dir,
                        ready_dir=ready_dir,
                        status_callback=status_callback,
                        user_input_callback=user_input_callback
                    )
                    
                    # Process all files
                    processor.process_all()
                    
                    # Merge platform data
                    self.logger.info("Pipeline: Merging platform data...")
                    self.root.after(0, lambda: self.status_text.set("Pipeline: Merging data..."))
                    processor.merge_platform_data()
                    
                    # Build YoY reports (ready_reports/)
                    self.logger.info("Pipeline: Building YoY reports...")
                    self.root.after(0, lambda: self.status_text.set("Pipeline: Building YoY reports..."))
                    processor.build_yoy_reports()
                    
                    self.logger.info("Pipeline: Complete!")
                    self.root.after(0, lambda: self.status_text.set("Pipeline Complete!"))
                    self.root.after(0, lambda: (
                        self.pipeline_progress_bar.set(1.0),
                        self.pipeline_status_label.configure(text="Pipeline Complete!")
                    ))
                except Exception as e:
                    error_msg = f"Error during processing: {str(e)}"
                    self.logger.error(f"Error in pipeline processing: {e}", exc_info=True)
                    self.root.after(0, lambda: self.status_text.set(error_msg))
                    self.root.after(0, lambda: self.pipeline_status_label.configure(text="Error during processing"))
            
        except Exception as e:
            error_msg = f"Pipeline Error: {str(e)}"
            self.logger.error(f"Error in pipeline: {e}", exc_info=True)
            self.root.after(0, lambda: self.status_text.set(error_msg))
            self.root.after(0, lambda: self.pipeline_status_label.configure(text="Pipeline Error"))
        finally:
            self.batch_fetch_active = False
            self.root.after(0, lambda: self.run_full_pipeline_button.configure(state="normal"))
            self.root.after(0, self._update_checklist_statuses)
            # Hide progress bar after delay
            self.root.after(3000, lambda: self.pipeline_progress_frame.pack_forget())
    
    def _run_google_fetch_in_batch(self) -> None:
        """Run Google Ads fetch as part of batch operation."""
        self.root.after(0, lambda: self._on_start_clicked())
    
    def _run_meta_fetch_in_batch(self) -> None:
        """Run Meta Ads fetch as part of batch operation.
        Starts the Meta fetch thread directly from the pipeline thread so we don't depend
        on the main thread processing an after(0) callback (which can cause the pipeline to hang).
        """
        if self.meta_is_processing:
            self.meta_fetch_complete.set()
            return
        # Update GUI from main thread, then start fetch thread from this (pipeline) thread
        self.meta_cancel_event.clear()
        self.meta_is_processing = True
        self.root.after(0, lambda: (
            self.meta_progress_bar.set(0),
            self.meta_progress_percent_label.configure(text="0%"),
            self.meta_eta_label.configure(text=""),
            self.meta_completion_time_label.configure(text=""),
            self.status_text.set("Pipeline: Fetching Meta Ads..."),
        ))
        self.logger.info("Meta fetch thread starting (from pipeline)")
        thread = threading.Thread(target=self.start_meta_fetch_thread, daemon=True)
        thread.start()

    def _run_ms_fetch_in_batch(self) -> None:
        """Run Microsoft Ads fetch as part of batch in a background thread."""
        self.logger.info("Pipeline: Microsoft Ads fetch starting")
        self.root.after(0, lambda: self.status_text.set("Pipeline: Fetching Microsoft Ads..."))
        thread = threading.Thread(target=self._run_ms_fetch_thread, daemon=True)
        thread.start()

    def _run_ms_fetch_thread(self) -> None:
        """Run Microsoft Ads fetcher in a background thread; signals ms_fetch_complete when done. Fetches by date range; optionally same range previous year."""
        try:
            start_date, end_date = self._get_main_date_range()
            customer_id = (self.ms_customer_id.get() or "").strip().replace("-", "").replace(" ", "")
            if not customer_id:
                self.root.after(0, lambda: self.status_text.set("Error: Microsoft Ads Customer ID missing"))
                return
            self.logger.info(f"Starting Microsoft Ads fetch for Customer ID: {_mask_id_for_log(customer_id)}")

            def update_status(message: str) -> None:
                self.root.after(0, lambda msg=message: self.status_text.set(msg))

            raw_base = self.settings.get("raw_reports_dir", "raw_reports")
            out_dir = Path(raw_base) / "microsoft"
            fetcher = MicrosoftAdsFetcher(
                customer_id=customer_id,
                output_dir=str(out_dir),
                status_callback=update_status,
                progress_callback=None,
                cancel_flag=None,
            )
            out_dir.mkdir(parents=True, exist_ok=True)
            saved = 0
            # Current range
            df = fetcher.fetch_month_data(start_date, end_date)
            if df is not None and not df.empty:
                fn = f"{start_date.strftime('%Y-%m-%d')}_{end_date.strftime('%Y-%m-%d')}.csv"
                out = out_dir / fn
                df.to_csv(out, index=False)
                self.logger.info(f"Microsoft Ads: saved {out}")
                saved += 1
            else:
                self.logger.info(f"Microsoft Ads: no data for {start_date.date()} to {end_date.date()}")
            # Prior year range (if checkbox)
            if self.main_pull_prior_year_var.get():
                prior_start = start_date - relativedelta(years=1)
                prior_end = end_date - relativedelta(years=1)
                df_prior = fetcher.fetch_month_data(prior_start, prior_end)
                if df_prior is not None and not df_prior.empty:
                    fn_prior = f"{prior_start.strftime('%Y-%m-%d')}_{prior_end.strftime('%Y-%m-%d')}.csv"
                    out_prior = out_dir / fn_prior
                    df_prior.to_csv(out_prior, index=False)
                    self.logger.info(f"Microsoft Ads: saved prior year {out_prior}")
                    saved += 1
                else:
                    self.logger.info(f"Microsoft Ads: no data for prior year {prior_start.date()} to {prior_end.date()}")
            self.root.after(0, lambda: self.status_text.set(
                f"Microsoft Ads fetch complete: {saved} range(s) saved"
            ))
            self.logger.info(f"Microsoft Ads fetch complete: {saved} range(s) saved")
        except Exception as e:
            error_msg = f"Microsoft Ads error: {e}"
            self.logger.error(error_msg, exc_info=True)
            self.root.after(0, lambda: self.status_text.set(error_msg))
        finally:
            self.ms_fetch_complete.set()

    def _run_tiktok_fetch_in_batch(self) -> None:
        """Run TikTok Ads fetch as part of batch. Stub: set completion; wire tiktok_fetcher when ready."""
        self.logger.info("Pipeline: TikTok Ads fetch (stub)")
        self.root.after(0, lambda: self.status_text.set("Pipeline: Fetching TikTok Ads..."))
        self.tiktok_fetch_complete.set()

    def _run_reddit_fetch_in_batch(self) -> None:
        """Run Reddit Ads fetch as part of batch in a background thread."""
        self.logger.info("Pipeline: Reddit Ads fetch starting")
        self.root.after(0, lambda: self.status_text.set("Pipeline: Fetching Reddit Ads..."))
        thread = threading.Thread(target=self._run_reddit_fetch_thread, daemon=True)
        thread.start()

    def _run_reddit_fetch_thread(self) -> None:
        """Run Reddit Ads fetcher in a background thread; signals reddit_fetch_complete when done. Fetches by date range; optionally same range previous year."""
        try:
            start_date, end_date = self._get_main_date_range()
            account_id = (self.reddit_account_id.get() or "").strip()
            if not account_id:
                self.root.after(0, lambda: self.status_text.set("Error: Reddit Account ID missing"))
                return
            self.logger.info(f"Starting Reddit Ads fetch for Account ID: {_mask_id_for_log(account_id)}")

            def update_status(message: str) -> None:
                self.root.after(0, lambda msg=message: self.status_text.set(msg))

            raw_base = self.settings.get("raw_reports_dir", "raw_reports")
            out_dir = Path(raw_base) / "reddit"
            fetcher = RedditAdsFetcher(
                account_id=account_id,
                output_dir=str(out_dir),
                status_callback=update_status,
                progress_callback=None,
                cancel_flag=None,
            )
            out_dir.mkdir(parents=True, exist_ok=True)
            saved = 0
            # Current range
            df = fetcher.fetch_month_data(start_date, end_date)
            if df is not None and not df.empty:
                fn = f"{start_date.strftime('%Y-%m-%d')}_{end_date.strftime('%Y-%m-%d')}.csv"
                out = out_dir / fn
                df.to_csv(out, index=False)
                self.logger.info(f"Reddit Ads: saved {out}")
                saved += 1
            else:
                self.logger.info(f"Reddit Ads: no data for {start_date.date()} to {end_date.date()}")
            # Prior year range (if checkbox)
            if self.main_pull_prior_year_var.get():
                prior_start = start_date - relativedelta(years=1)
                prior_end = end_date - relativedelta(years=1)
                df_prior = fetcher.fetch_month_data(prior_start, prior_end)
                if df_prior is not None and not df_prior.empty:
                    fn_prior = f"{prior_start.strftime('%Y-%m-%d')}_{prior_end.strftime('%Y-%m-%d')}.csv"
                    out_prior = out_dir / fn_prior
                    df_prior.to_csv(out_prior, index=False)
                    self.logger.info(f"Reddit Ads: saved prior year {out_prior}")
                    saved += 1
                else:
                    self.logger.info(f"Reddit Ads: no data for prior year {prior_start.date()} to {prior_end.date()}")
            self.root.after(0, lambda: self.status_text.set(
                f"Reddit Ads fetch complete: {saved} range(s) saved"
            ))
            self.logger.info(f"Reddit Ads fetch complete: {saved} range(s) saved")
        except Exception as e:
            error_msg = f"Reddit Ads error: {e}"
            self.logger.error(error_msg, exc_info=True)
            self.root.after(0, lambda: self.status_text.set(error_msg))
        finally:
            self.reddit_fetch_complete.set()

    def _run_pinterest_fetch_in_batch(self) -> None:
        """Run Pinterest Ads fetch as part of batch. Stub: set completion; wire pinterest_fetcher when ready."""
        self.logger.info("Pipeline: Pinterest Ads fetch (stub)")
        self.root.after(0, lambda: self.status_text.set("Pipeline: Fetching Pinterest Ads..."))
        self.pinterest_fetch_complete.set()

    def _clear_all_data(self) -> None:
        """
        Delete all CSV files from raw_reports, processed_reports, merged_reports, and ready_reports directories.
        Preserves directory structure but removes all .csv files.
        """
        # Show confirmation dialog
        result = messagebox.askyesno(
            "Confirm Clear Data",
            "Are you sure you want to delete ALL raw, processed, merged, and ready report CSV files? This cannot be undone.",
            icon="warning"
        )
        
        if not result:
            return
        
        deleted_count = 0
        
        # Target directories (from settings)
        raw_dir = Path(self.settings.get("raw_reports_dir", "raw_reports"))
        processed_dir = Path(self.settings.get("processed_reports_dir", "processed_reports"))
        merged_dir = Path(self.settings.get("merged_reports_dir", "merged_reports"))
        ready_dir = Path(self.settings.get("ready_reports_dir", "ready_reports"))
        directories = [raw_dir, processed_dir, merged_dir, ready_dir]
        
        for directory in directories:
            if not directory.exists():
                continue
            
            # Walk through all subdirectories
            for csv_file in directory.rglob("*.csv"):
                try:
                    csv_file.unlink()
                    deleted_count += 1
                    self.logger.info(f"Deleted: {csv_file}")
                except Exception as e:
                    self.logger.error(f"Error deleting {csv_file}: {e}")
        
        # Update status
        status_msg = f"Deleted {deleted_count} files from raw, processed, merged, and ready report folders."
        self.status_text.set(status_msg)
        self.logger.info(status_msg)
        
        # Update checklist statuses after clearing
        self._update_checklist_statuses()
        
        # Also log to GUI log box
        if deleted_count > 0:
            self.logger.info(f"Clear Data: Removed {deleted_count} CSV file(s)")
        else:
            self.logger.info("Clear Data: No CSV files found to delete")
    
    def _on_new_fetch_clicked(self) -> None:
        """Handle new fetch button click - resets all tabs."""
        if self.is_processing or self.meta_is_processing:
            self.logger.warning("Cannot reset while processing")
            self.status_text.set("Cannot reset while processing")
            return
        
        # Reset Main tab (date range unlocked)
        self.date_range_locked = False
        if hasattr(self, "start_month_menu") and self.start_month_menu is not None:
            self.start_month_menu.configure(state="normal")
            self.start_year_menu.configure(state="normal")
            self.end_month_menu.configure(state="normal")
            self.end_year_menu.configure(state="normal")
        if hasattr(self, "main_pull_prior_year_cb") and self.main_pull_prior_year_cb is not None:
            self.main_pull_prior_year_cb.configure(state="normal")
        self.confirm_date_btn.configure(text="Confirm Date Range", state="normal")
        self.unlock_date_btn.configure(state="disabled")
        self.progress_bar.set(0)
        self.progress_percent_label.configure(text="0%")
        self.eta_label.configure(text="")
        self.completion_time_label.configure(text="")
        
        # Reset Meta Ads (global date already reset above)
        self.meta_date_range_locked = False
        self.meta_progress_bar.set(0)
        self.meta_progress_percent_label.configure(text="0%")
        self.meta_eta_label.configure(text="")
        self.meta_completion_time_label.configure(text="")
        
        # Reset button state
        self.new_fetch_button.configure(state="disabled")
        self.status_text.set("Ready")
        self.logger.info("Reset all tabs for new fetch")
        self._update_checklist_statuses()
    
    def _on_meta_start_clicked(self) -> None:
        """Handle Meta Ads start button click."""
        if self.meta_is_processing:
            self.logger.warning("Meta Ads already processing, ignoring start request")
            self.meta_fetch_complete.set()
            return

        if not self.meta_date_range_locked:
            msg = "Error: Please confirm Account ID and date range before starting"
            self.logger.warning(msg)
            self.status_text.set(msg)
            self.meta_fetch_complete.set()
            return

        is_valid, error_msg = self._validate_meta_inputs()
        if not is_valid:
            self.logger.warning(f"Meta start aborted: {error_msg}")
            self.status_text.set(f"Error: {error_msg}")
            self.meta_fetch_complete.set()
            return

        self.meta_cancel_event.clear()
        self.meta_is_processing = True
        self.meta_progress_bar.set(0)
        self.meta_progress_percent_label.configure(text="0%")
        self.meta_eta_label.configure(text="")
        self.meta_completion_time_label.configure(text="")
        self.status_text.set("Initializing Meta Ads fetch...")
        self.logger.info("Meta fetch thread starting")

        thread = threading.Thread(target=self.start_meta_fetch_thread, daemon=True)
        thread.start()
    
    def _on_meta_stop_clicked(self) -> None:
        """Handle Meta Ads stop button click."""
        if self.meta_is_processing:
            self.meta_cancel_event.set()
            self.status_text.set("Stopping Meta Ads fetch...")
            self.logger.info("Meta Ads stop requested by user")
    
    def _on_meta_token_update_clicked(self) -> None:
        """Handle Meta token update button click. Saves token in a background thread so the main thread never blocks on file I/O (avoids app freezing)."""
        self.root.update_idletasks()
        new_token = self.meta_token_input.get().strip()
        if not new_token:
            self.status_text.set("Error: Please enter a token")
            return

        # Disable button while checking/saving so user doesn't double-click
        self.meta_token_update_btn.configure(state="disabled")
        self.status_text.set("Checking token...")

        def check_and_save_token_in_background() -> None:
            try:
                valid, check_err, _ = self._check_meta_token_with_api(new_token)
                if not valid:
                    def on_check_failed() -> None:
                        self.meta_token_update_btn.configure(state="normal")
                        self.status_text.set(f"Token invalid: {check_err or 'Unknown error'}")
                    self.root.after(0, on_check_failed)
                    return
                self.root.after(0, lambda: self.status_text.set("Token valid. Saving..."))
                ok, err = self._update_meta_token(new_token)
                def on_done() -> None:
                    self.meta_token_update_btn.configure(state="normal")
                    if not ok:
                        self.status_text.set(f"Error: {err or 'Failed to update token file'}")
                        return
                    self.meta_token_updated.set()
                    self.meta_token_frame.pack_forget()
                    self.meta_token_input.set("")
                    self.status_text.set("Token valid and saved successfully")
                    self.logger.info("Meta token updated from Meta tab input field")
                self.root.after(0, on_done)
            except Exception as e:
                self.logger.error(f"Meta token update error: {e}", exc_info=True)
                def on_fail() -> None:
                    self.meta_token_update_btn.configure(state="normal")
                    self.status_text.set(f"Error: {e}")
                self.root.after(0, on_fail)

        threading.Thread(target=check_and_save_token_in_background, daemon=True).start()
    
    def _on_process_clicked(self) -> None:
        """Handle process button click."""
        if self.is_processing or self.meta_is_processing:
            self.status_text.set("Cannot process files while fetching is in progress")
            return
        
        self.process_button.configure(state="disabled")
        self.status_text.set("Starting file processing...")
        
        # Show progress frame
        self.process_progress_frame.pack(pady=10, padx=20, fill="x")
        
        thread = threading.Thread(target=self.start_processing_thread, daemon=True)
        thread.start()
    
    def start_google_fetch_thread(self) -> None:
        """Run Google Ads fetcher in a background thread. Fetches by date range; optionally same range previous year."""
        try:
            start_date, end_date = self._get_main_date_range()
            customer_id_raw = self.customer_id.get().strip()
            customer_id_clean = customer_id_raw.replace("-", "")

            self.logger.info(f"Starting Google Ads fetch for Customer ID: {_mask_id_for_log(customer_id_clean)}")
            self.logger.info(f"Date range: {start_date} to {end_date}")

            def update_status(message: str) -> None:
                if self.cancel_event.is_set():
                    return
                self.root.after(0, lambda msg=message: self.status_text.set(msg))

            raw_base = self.settings.get("raw_reports_dir", "raw_reports")
            out_dir = Path(raw_base) / "google"
            fetcher = AdsApiFetcher(
                customer_id=customer_id_clean,
                output_dir=str(out_dir),
                status_callback=update_status,
                progress_callback=None,
                cancel_flag=self.cancel_event
            )
            out_dir.mkdir(parents=True, exist_ok=True)
            saved = 0
            # Current range
            df = fetcher.fetch_month_data(start_date, end_date)
            if df is not None and not df.empty:
                fn = f"{start_date.strftime('%Y-%m-%d')}_{end_date.strftime('%Y-%m-%d')}.csv"
                out = out_dir / fn
                df.to_csv(out, index=False)
                self.logger.info(f"Google Ads: saved {out}")
                saved += 1
            else:
                self.logger.info(f"Google Ads: no data for {start_date.date()} to {end_date.date()}")
            # Prior year range (if checkbox)
            if self.main_pull_prior_year_var.get():
                prior_start = start_date - relativedelta(years=1)
                prior_end = end_date - relativedelta(years=1)
                df_prior = fetcher.fetch_month_data(prior_start, prior_end)
                if df_prior is not None and not df_prior.empty:
                    fn_prior = f"{prior_start.strftime('%Y-%m-%d')}_{prior_end.strftime('%Y-%m-%d')}.csv"
                    out_prior = out_dir / fn_prior
                    df_prior.to_csv(out_prior, index=False)
                    self.logger.info(f"Google Ads: saved prior year {out_prior}")
                    saved += 1
                else:
                    self.logger.info(f"Google Ads: no data for prior year {prior_start.date()} to {prior_end.date()}")
            self.root.after(0, lambda: self.status_text.set(
                f"Google Ads fetch complete: {saved} range(s) saved"
            ))
            self.root.after(0, lambda: self.progress_bar.set(1.0))
            self.root.after(0, lambda: self.progress_percent_label.configure(text="100%"))
        except Exception as e:
            error_msg = f"Error: {str(e)}"
            self.logger.error(f"Error in Google Ads fetch: {e}", exc_info=True)
            self.root.after(0, lambda: self.status_text.set(error_msg))
        finally:
            self.is_processing = False
            self.cancel_event.clear()
            self.root.after(0, lambda: self.new_fetch_button.configure(state="normal"))
            self.google_fetch_complete.set()
    
    def start_meta_fetch_thread(self) -> None:
        """Run Meta Ads fetcher in a background thread. Fetches by date range; optionally same range previous year."""
        try:
            start_date, end_date = self._get_main_date_range()
            account_id_raw = self.meta_account_id.get().strip()
            account_id_clean = account_id_raw.replace("-", "").replace(" ", "")

            self.logger.info(f"Starting Meta Ads fetch for Account ID: {_mask_id_for_log(account_id_clean)}")
            self.logger.info(f"Date range: {start_date} to {end_date}")

            def update_status(message: str) -> None:
                if self.meta_cancel_event.is_set():
                    return
                self.root.after(0, lambda msg=message: self.status_text.set(msg))

            raw_base = self.settings.get("raw_reports_dir", "raw_reports")
            out_dir = Path(raw_base) / "meta"
            out_dir.mkdir(parents=True, exist_ok=True)
            saved = 0
            max_retries = 10
            retry_count = 0

            def do_fetch(s_date: datetime, e_date: datetime) -> Optional[object]:
                """Fetch one range; returns DataFrame or None. Raises MetaTokenExpiredError on token expiry."""
                f = MetaAdsFetcher(
                    ad_account_id=account_id_clean,
                    output_dir=str(out_dir),
                    status_callback=update_status,
                    progress_callback=None,
                    cancel_flag=self.meta_cancel_event
                )
                return f.fetch_month_data(s_date, e_date)

            while retry_count < max_retries:
                try:
                    # Current range
                    df = do_fetch(start_date, end_date)
                    if df is not None and not df.empty:
                        fn = f"{start_date.strftime('%Y-%m-%d')}_{end_date.strftime('%Y-%m-%d')}.csv"
                        (out_dir / fn).parent.mkdir(parents=True, exist_ok=True)
                        df.to_csv(out_dir / fn, index=False)
                        self.logger.info(f"Meta Ads: saved {out_dir / fn}")
                        saved += 1
                    else:
                        self.logger.info(f"Meta Ads: no data for {start_date.date()} to {end_date.date()}")
                    # Prior year range (if checkbox)
                    if self.main_pull_prior_year_var.get():
                        prior_start = start_date - relativedelta(years=1)
                        prior_end = end_date - relativedelta(years=1)
                        df_prior = do_fetch(prior_start, prior_end)
                        if df_prior is not None and not df_prior.empty:
                            fn_prior = f"{prior_start.strftime('%Y-%m-%d')}_{prior_end.strftime('%Y-%m-%d')}.csv"
                            df_prior.to_csv(out_dir / fn_prior, index=False)
                            self.logger.info(f"Meta Ads: saved prior year {out_dir / fn_prior}")
                            saved += 1
                        else:
                            self.logger.info(f"Meta Ads: no data for prior year {prior_start.date()} to {prior_end.date()}")
                    break  # Success, exit retry loop

                except MetaTokenExpiredError:
                    retry_count += 1
                    self.logger.warning(f"Meta token expired (attempt {retry_count}/{max_retries})")
                    
                    # Show token input frame in Meta tab
                    self.root.after(0, lambda: self.status_text.set(
                        f"Meta token expired (attempt {retry_count}). Please enter new token in Meta tab..."
                    ))
                    self.root.after(0, lambda: self.meta_token_frame.pack(fill="x", pady=(6, 0)))
                    self.root.after(0, lambda: self.meta_token_entry.focus_set())
                    
                    # Reset and wait for user to update token
                    self.meta_token_updated.clear()
                    self.meta_token_updated.wait(timeout=DIALOG_WAIT_SECONDS)
                    
                    if not self.meta_token_updated.is_set():
                        self.logger.warning("Token update timeout")
                        self.root.after(0, lambda: self.status_text.set(
                            "Meta fetch cancelled: Token update timeout"
                        ))
                        self.root.after(0, lambda: self.meta_token_frame.pack_forget())
                        return
                    
                    # User already saved the token via "Update Token" (which writes to meta-ads.yaml
                    # and then clears the input). Do not read meta_token_input here—it is empty.
                    # Retry by creating a new MetaAdsFetcher; it will load the updated token from meta-ads.yaml.
                    self.logger.info(f"Token updated (attempt {retry_count}), retrying fetch...")
                    self.root.after(0, lambda: self.status_text.set(
                        f"Token updated. Retrying Meta fetch (attempt {retry_count})..."
                    ))
                    # Short delay so the YAML write is visible to the next reader (e.g. on network drives).
                    time.sleep(0.25)
                    continue  # Retry loop; new MetaAdsFetcher() will read meta-ads.yaml
            
            if retry_count >= max_retries:
                self.logger.error(f"Max retries ({max_retries}) reached for token expiration")
                self.root.after(0, lambda: self.status_text.set(
                    f"Error: Failed to update Meta token after {max_retries} attempts"
                ))
                self.root.after(0, lambda: self.meta_token_frame.pack_forget())
                return
            
            self.root.after(0, lambda: self.status_text.set(
                f"Meta Ads fetch complete: {saved} range(s) saved"
            ))
            self.root.after(0, lambda: self.meta_progress_bar.set(1.0))
            self.root.after(0, lambda: self.meta_progress_percent_label.configure(text="100%"))
            self.logger.info(f"Meta Ads fetch complete: {saved} range(s) saved")
            
        except Exception as e:
            error_msg = f"Error: {str(e)}"
            self.logger.error(f"Error in Meta Ads fetch: {e}", exc_info=True)
            self.root.after(0, lambda: self.status_text.set(error_msg))
        finally:
            self.meta_is_processing = False
            self.meta_cancel_event.clear()
            self.root.after(0, lambda: self.new_fetch_button.configure(state="normal"))
            # Signal batch fetch that Meta fetch is complete
            self.meta_fetch_complete.set()
    
    def _on_google_process_clicked(self) -> None:
        """Handle Google process button click - processes only google/ directory."""
        if self.is_processing or self.meta_is_processing:
            self.status_text.set("Cannot process files while fetching is in progress")
            return
        
        raw_base = Path(self.settings.get("raw_reports_dir", "raw_reports"))
        google_dir = raw_base / "google"
        if not google_dir.exists() or not any(google_dir.glob("*.csv")):
            self.status_text.set("No Google Ads files found to process")
            return
        
        self.status_text.set("Starting Google Ads file processing...")
        thread = threading.Thread(target=self.start_google_processing_thread, daemon=True)
        thread.start()
    
    def start_google_processing_thread(self) -> None:
        """Run ReportProcessor for Google Ads files only."""
        try:
            def status_callback(message: str):
                self.root.after(0, lambda msg=message: self.status_text.set(msg))
            
            def user_input_callback(campaign_name: str) -> str:
                return self._show_funnel_dialog(campaign_name)
            
            raw_dir = self.settings.get("raw_reports_dir", "raw_reports")
            processed_dir = self.settings.get("processed_reports_dir", "processed_reports")
            merged_dir = self.settings.get("merged_reports_dir", "merged_reports")
            ready_dir = self.settings.get("ready_reports_dir", "ready_reports")
            processor = ReportProcessor(
                input_dir=raw_dir,
                output_dir=processed_dir,
                merged_dir=merged_dir,
                ready_dir=ready_dir,
                status_callback=status_callback,
                user_input_callback=user_input_callback
            )
            
            # Find all files, then filter to only Google files
            all_files = processor._find_report_files()
            raw_files = [f for f in all_files if f.parent.name == "google"]
            
            if not raw_files:
                self.root.after(0, lambda: self.status_text.set("No Google Ads files found to process."))
                self.logger.info("No Google Ads files found for processing.")
                return
            
            total_files = len(raw_files)
            successful_processes = 0
            
            for i, file_path in enumerate(raw_files):
                self.root.after(0, lambda fp=file_path: self.status_text.set(f"Processing {fp.name}..."))
                processed_path = processor.process_file(file_path)
                if processed_path:
                    successful_processes += 1
                    self.logger.info(f"Successfully processed {file_path.name}")
            
            self.root.after(0, lambda: self.status_text.set(
                f"Google Ads processing complete: {successful_processes}/{total_files} files processed."
            ))
            self.logger.info(f"Google Ads processing finished: {successful_processes}/{total_files} files processed.")
            
        except Exception as e:
            error_msg = f"Error during Google Ads processing: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            self.root.after(0, lambda: self.status_text.set(error_msg))
        finally:
            self.root.after(0, lambda: self._update_checklist_statuses())
    
    def _on_meta_process_clicked(self) -> None:
        """Handle Meta process button click - processes only meta/ directory."""
        if self.is_processing or self.meta_is_processing:
            self.status_text.set("Cannot process files while fetching is in progress")
            return
        
        raw_base = Path(self.settings.get("raw_reports_dir", "raw_reports"))
        meta_dir = raw_base / "meta"
        if not meta_dir.exists() or not any(meta_dir.glob("*.csv")):
            self.status_text.set("No Meta Ads files found to process")
            return
        
        self.status_text.set("Starting Meta Ads file processing...")
        thread = threading.Thread(target=self.start_meta_processing_thread, daemon=True)
        thread.start()
    
    def start_meta_processing_thread(self) -> None:
        """Run ReportProcessor for Meta Ads files only."""
        try:
            def status_callback(message: str):
                self.root.after(0, lambda msg=message: self.status_text.set(msg))
            
            def user_input_callback(campaign_name: str) -> str:
                return self._show_funnel_dialog(campaign_name)
            
            raw_dir = self.settings.get("raw_reports_dir", "raw_reports")
            processed_dir = self.settings.get("processed_reports_dir", "processed_reports")
            merged_dir = self.settings.get("merged_reports_dir", "merged_reports")
            ready_dir = self.settings.get("ready_reports_dir", "ready_reports")
            processor = ReportProcessor(
                input_dir=raw_dir,
                output_dir=processed_dir,
                merged_dir=merged_dir,
                ready_dir=ready_dir,
                status_callback=status_callback,
                user_input_callback=user_input_callback
            )
            
            # Find all files, then filter to only Meta files
            all_files = processor._find_report_files()
            raw_files = [f for f in all_files if f.parent.name == "meta"]
            
            if not raw_files:
                self.root.after(0, lambda: self.status_text.set("No Meta Ads files found to process."))
                self.logger.info("No Meta Ads files found for processing.")
                return
            
            total_files = len(raw_files)
            successful_processes = 0
            
            for i, file_path in enumerate(raw_files):
                self.root.after(0, lambda fp=file_path: self.status_text.set(f"Processing {fp.name}..."))
                processed_path = processor.process_file(file_path)
                if processed_path:
                    successful_processes += 1
                    self.logger.info(f"Successfully processed {file_path.name}")
            
            self.root.after(0, lambda: self.status_text.set(
                f"Meta Ads processing complete: {successful_processes}/{total_files} files processed."
            ))
            self.logger.info(f"Meta Ads processing finished: {successful_processes}/{total_files} files processed.")
            
        except Exception as e:
            error_msg = f"Error during Meta Ads processing: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            self.root.after(0, lambda: self.status_text.set(error_msg))
        finally:
            self.root.after(0, lambda: self._update_checklist_statuses())
    
    def _update_progress(self, completed: int, total: int) -> None:
        """Update progress bar with percentage and ETA (Google Ads)."""
        if total == 0:
            return
        
        progress = completed / total
        self.progress_bar.set(progress)
        self.progress_percent_label.configure(text=f"{int(progress * 100)}%")
        
        if completed > 0 and hasattr(self, 'start_time') and self.start_time:
            elapsed = (datetime.now() - self.start_time).total_seconds()
            avg_time_per_month = elapsed / completed
            remaining_months = total - completed
            eta_seconds = avg_time_per_month * remaining_months
            
            hours = int(eta_seconds // 3600)
            minutes = int((eta_seconds % 3600) // 60)
            seconds = int(eta_seconds % 60)
            
            if hours > 0:
                eta_str = f"ETA: {hours}h {minutes}m {seconds}s"
            else:
                eta_str = f"ETA: {minutes}m {seconds}s"
            
            self.eta_label.configure(text=eta_str)
            
            completion_time = datetime.now() + timedelta(seconds=eta_seconds)
            self.completion_time_label.configure(text=f"Complete: {completion_time.strftime('%I:%M:%S %p')}")
    
    def _update_meta_progress(self, completed: int, total: int) -> None:
        """Update progress bar with percentage and ETA (Meta Ads)."""
        if total == 0:
            return
        
        progress = completed / total
        self.meta_progress_bar.set(progress)
        self.meta_progress_percent_label.configure(text=f"{int(progress * 100)}%")
        
        if completed > 0 and hasattr(self, 'meta_start_time') and self.meta_start_time:
            elapsed = (datetime.now() - self.meta_start_time).total_seconds()
            avg_time_per_month = elapsed / completed
            remaining_months = total - completed
            eta_seconds = avg_time_per_month * remaining_months
            
            hours = int(eta_seconds // 3600)
            minutes = int((eta_seconds % 3600) // 60)
            seconds = int(eta_seconds % 60)
            
            if hours > 0:
                eta_str = f"ETA: {hours}h {minutes}m {seconds}s"
            else:
                eta_str = f"ETA: {minutes}m {seconds}s"
            
            self.meta_eta_label.configure(text=eta_str)
            
            completion_time = datetime.now() + timedelta(seconds=eta_seconds)
            self.meta_completion_time_label.configure(text=f"Complete: {completion_time.strftime('%I:%M:%S %p')}")
    
    def _show_token_input_dialog(self) -> Optional[str]:
        """Show dialog to get new Meta access token from user."""
        result = {"token": None}
        dialog_done = threading.Event()
        
        def show_dialog():
            dialog = ctk.CTkToplevel(self.root)
            dialog.title("Meta Access Token Expired")
            dialog.geometry("600x180")
            dialog.transient(self.root)
            dialog.grab_set()
            dialog.attributes('-topmost', True)
            
            dialog.update_idletasks()
            x = (dialog.winfo_screenwidth() // 2) - (600 // 2)
            y = (dialog.winfo_screenheight() // 2) - (180 // 2)
            dialog.geometry(f"600x180+{x}+{y}")
            
            message_label = ctk.CTkLabel(
                dialog,
                text="Meta Access Token Expired. Please enter a new token:",
                font=ctk.CTkFont(size=12, weight="bold")
            )
            message_label.pack(pady=(20, 10), padx=20)
            
            token_entry = ctk.CTkEntry(
                dialog,
                placeholder_text="Paste your new Meta access token here",
                width=550,
                height=35,
                font=ctk.CTkFont(size=11)
            )
            token_entry.pack(pady=10, padx=20)
            token_entry.focus_set()
            
            button_frame = ctk.CTkFrame(dialog)
            button_frame.pack(pady=10, padx=20)
            
            def on_ok():
                token = token_entry.get().strip()
                if token:
                    result["token"] = token
                dialog_done.set()
                dialog.destroy()
            
            def on_cancel():
                dialog_done.set()
                dialog.destroy()
            
            ok_btn = ctk.CTkButton(
                button_frame,
                text="OK",
                command=on_ok,
                width=120,
                height=35,
                font=ctk.CTkFont(size=12, weight="bold"),
                fg_color="green",
                hover_color="darkgreen"
            )
            ok_btn.pack(side="left", padx=10)
            
            cancel_btn = ctk.CTkButton(
                button_frame,
                text="Cancel",
                command=on_cancel,
                width=120,
                height=35,
                font=ctk.CTkFont(size=12),
                fg_color="gray",
                hover_color="darkgray"
            )
            cancel_btn.pack(side="left", padx=10)
            
            # Bind Enter key to OK
            token_entry.bind('<Return>', lambda e: on_ok())
            dialog.bind('<Escape>', lambda e: on_cancel())
        
        self.root.after(0, show_dialog)
        dialog_done.wait(timeout=DIALOG_WAIT_SECONDS)
        
        return result["token"]

    def _check_meta_token_with_api(self, token: str) -> Tuple[bool, Optional[str], Optional[int]]:
        """Validate Meta access token via Graph API debug_token. Returns (valid, error_message, expires_at)."""
        try:
            yaml_path = _APP_DIR / "meta-ads.yaml"
            if not yaml_path.exists():
                return False, "meta-ads.yaml not found", None
            try:
                with open(yaml_path, "r", encoding="utf-8") as f:
                    config = yaml.safe_load(f) or {}
            except yaml.YAMLError as e:
                self.logger.error(f"meta-ads.yaml is corrupted (invalid YAML): {e}", exc_info=True)
                return False, "meta-ads.yaml is corrupted; backup or delete and re-run setup.", None
            except OSError as e:
                self.logger.error(f"Error reading meta-ads.yaml: {e}", exc_info=True)
                return False, f"Could not read meta-ads.yaml: {e}", None
            app_id = config.get("app_id") or ""
            app_secret = config.get("app_secret") or ""
            if not app_id or not app_secret:
                return False, "meta-ads.yaml missing app_id or app_secret", None
            app_token = f"{app_id}|{app_secret}"
            url = (
                "https://graph.facebook.com/v18.0/debug_token"
                f"?input_token={urllib.parse.quote(token.strip())}"
                f"&access_token={urllib.parse.quote(app_token)}"
            )
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
            info = data.get("data") or {}
            if not info.get("is_valid"):
                return False, "Token invalid or expired", None
            expires_at = info.get("expires_at")
            if expires_at and expires_at != 0:
                exp_str = datetime.utcfromtimestamp(expires_at).strftime("%Y-%m-%d %H:%M UTC")
                self.logger.info(f"Meta token valid until {exp_str}")
            return True, None, expires_at if expires_at else None
        except urllib.error.HTTPError as e:
            body = e.read().decode() if e.fp else ""
            try:
                err = json.loads(body).get("error", {})
                msg = err.get("message", body or str(e))
            except Exception:
                msg = body or str(e)
            return False, f"Token check failed: {msg}", None
        except urllib.error.URLError as e:
            return False, f"Token check failed: {e.reason or str(e)}", None
        except Exception as e:
            self.logger.error(f"Token check error: {e}", exc_info=True)
            return False, str(e), None
    
    def _update_meta_token(self, new_token: str) -> Tuple[bool, Optional[str]]:
        """Update access_token in meta-ads.yaml file. Validates token before saving.
        Returns (True, None) on success, (False, error_message) on failure."""
        try:
            yaml_path = _APP_DIR / "meta-ads.yaml"
            if not yaml_path.exists():
                self.logger.error("meta-ads.yaml not found")
                return False, "meta-ads.yaml not found"

            # Validate: token must be single-line and look like a real token (not pasted prose)
            t = new_token.strip()
            if not t:
                self.logger.error("Token is empty")
                return False, "Token is empty"
            if "\n" in t or "\r" in t:
                self.logger.error("Token must be a single line (no line breaks)")
                return False, "Token must be a single line (no line breaks)"
            if len(t) < 20 or len(t) > 2000:
                self.logger.error("Token length looks wrong (expected 20–2000 characters)")
                return False, "Token length looks wrong (expected 20–2000 characters)"
            if any(x in t for x in ("Goal:", "Requirements:", "Implement ", "Pin the Log")):
                self.logger.error("Token looks like pasted text; enter only the Meta access token")
                return False, "Token looks like pasted text; enter only the Meta access token"

            # Read current config
            try:
                with open(yaml_path, "r", encoding="utf-8") as f:
                    config = yaml.safe_load(f) or {}
            except yaml.YAMLError as e:
                self.logger.error(f"meta-ads.yaml is corrupted (invalid YAML): {e}", exc_info=True)
                return False, "meta-ads.yaml is corrupted; backup or delete and re-run setup_meta_auth.py."
            except OSError as e:
                self.logger.error(f"Error reading meta-ads.yaml: {e}", exc_info=True)
                return False, f"Could not read meta-ads.yaml: {e}"

            # Update token
            config["access_token"] = t

            # Write back (preserve other keys)
            with open(yaml_path, "w", encoding="utf-8") as f:
                yaml.dump(config, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
            self._restrict_file_permissions(Path(yaml_path))

            self.logger.info("Meta access token updated in meta-ads.yaml")
            return True, None

        except Exception as e:
            self.logger.error(f"Error updating meta-ads.yaml: {e}", exc_info=True)
            return False, str(e)
    
    def _show_funnel_dialog(self, campaign_name: str) -> str:
        """Show dialog to ask user for funnel stage classification."""
        result = {"choice": "Top"}
        dialog_done = threading.Event()
        
        def show_dialog():
            dialog = ctk.CTkToplevel(self.root)
            dialog.title("Classify Campaign")
            dialog.geometry("650x200")
            dialog.transient(self.root)
            dialog.grab_set()
            dialog.attributes('-topmost', True)
            
            dialog.update_idletasks()
            x = (dialog.winfo_screenwidth() // 2) - (650 // 2)
            y = (dialog.winfo_screenheight() // 2) - (200 // 2)
            dialog.geometry(f"650x200+{x}+{y}")
            
            name_label = ctk.CTkLabel(
                dialog,
                text="Campaign Name:",
                font=ctk.CTkFont(size=12, weight="bold")
            )
            name_label.pack(pady=(20, 5), padx=20)
            
            campaign_label = ctk.CTkLabel(
                dialog,
                text=campaign_name,
                font=ctk.CTkFont(size=13),
                wraplength=500
            )
            campaign_label.pack(pady=5, padx=20)
            
            question_label = ctk.CTkLabel(
                dialog,
                text="Select Funnel Stage:",
                font=ctk.CTkFont(size=12)
            )
            question_label.pack(pady=(15, 10), padx=20)
            
            button_frame = ctk.CTkFrame(dialog)
            button_frame.pack(pady=10, padx=20)
            
            def choose_top():
                result["choice"] = "Top"
                dialog_done.set()
                dialog.destroy()
            
            def choose_bottom():
                result["choice"] = "Bottom"
                dialog_done.set()
                dialog.destroy()
            
            def choose_skip():
                result["choice"] = "SKIP"
                dialog_done.set()
                dialog.destroy()
            
            def choose_always_ignore():
                result["choice"] = "DELETE"
                dialog_done.set()
                dialog.destroy()
            
            top_btn = ctk.CTkButton(
                button_frame,
                text="Top",
                command=choose_top,
                width=110,
                height=40,
                font=ctk.CTkFont(size=14, weight="bold"),
                fg_color="blue",
                hover_color="darkblue"
            )
            top_btn.pack(side="left", padx=4)
            
            bottom_btn = ctk.CTkButton(
                button_frame,
                text="Bottom",
                command=choose_bottom,
                width=110,
                height=40,
                font=ctk.CTkFont(size=14, weight="bold"),
                fg_color="green",
                hover_color="darkgreen"
            )
            bottom_btn.pack(side="left", padx=4)
            
            skip_btn = ctk.CTkButton(
                button_frame,
                text="Skip (This Report Only)",
                command=choose_skip,
                width=140,
                height=40,
                font=ctk.CTkFont(size=12, weight="bold"),
                fg_color="orange",
                hover_color="darkorange"
            )
            skip_btn.pack(side="left", padx=4)
            
            always_ignore_btn = ctk.CTkButton(
                button_frame,
                text="Always Ignore Campaign",
                command=choose_always_ignore,
                width=150,
                height=40,
                font=ctk.CTkFont(size=12, weight="bold"),
                fg_color="red",
                hover_color="darkred"
            )
            always_ignore_btn.pack(side="left", padx=4)
            
            dialog.focus()
            dialog.wait_window()
        
        self.root.after(0, show_dialog)
        dialog_done.wait(timeout=DIALOG_WAIT_SECONDS)
        
        return result["choice"]
    
    def _load_settings(self) -> Dict:
        """Load settings from config.json file (under app dir)."""
        defaults = {
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
        try:
            if self.settings_file.exists():
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                # Merge with defaults so new keys (e.g. raw_reports_dir) are present when saving
                merged = defaults.copy()
                if isinstance(loaded, dict):
                    merged.update(loaded)
                return merged
            return defaults.copy()
        except json.JSONDecodeError as e:
            try:
                self.logger.error(f"config.json is corrupted (invalid JSON): {e}", exc_info=True)
            except Exception:
                print(f"config.json is corrupted: {e}")
            self._config_corrupted_msg = "config.json was corrupted; using defaults. Backup or delete and restart."
            return defaults.copy()
        except OSError as e:
            try:
                self.logger.error(f"Error reading config.json: {e}", exc_info=True)
            except Exception:
                print(f"Error reading config.json: {e}")
            self._config_corrupted_msg = "Could not read config.json; using defaults."
            return defaults.copy()
    
    def _load_favorites(self) -> None:
        """Load favorites from JSON file."""
        try:
            if self.favorites_file.exists():
                with open(self.favorites_file, 'r', encoding='utf-8') as f:
                    self.favorites = json.load(f)
            else:
                self.favorites = []
        except json.JSONDecodeError as e:
            self.logger.error(f"customer_favorites.json is corrupted (invalid JSON): {e}", exc_info=True)
            self.favorites = []
            if hasattr(self, "status_text"):
                self.status_text.set("customer_favorites.json was corrupted; using empty list. Backup or delete and restart.")
        except OSError as e:
            self.logger.error(f"Error reading customer_favorites.json: {e}", exc_info=True)
            self.favorites = []
    
    def _save_favorites(self) -> None:
        """Save favorites to JSON file."""
        try:
            with open(self.favorites_file, 'w', encoding='utf-8') as f:
                json.dump(self.favorites, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"Error saving favorites: {e}", exc_info=True)
    
    def _update_favorites_menu(self) -> None:
        """Update the Google ID combobox and settings menus."""
        google_values = [f"{f['name']} ({f['customer_id']})" for f in self.favorites] if self.favorites else []
        if hasattr(self, 'customer_id_combobox'):
            self.customer_id_combobox.configure(values=google_values)
            self._set_google_id_display_from_id()
        self._update_settings_google_favorites_menu()
        if hasattr(self, 'settings_google_favorite_menu'):
            google_favorite_names = [fav["name"] for fav in self.favorites] if self.favorites else []
            self.settings_google_favorite_menu.configure(values=["None"] + google_favorite_names if google_favorite_names else ["None"])
    
    def _update_settings_google_favorites_menu(self) -> None:
        """Update the Default account Google favorites dropdown menu."""
        favorite_names = [fav["name"] for fav in self.favorites] if self.favorites else []
        if hasattr(self, 'settings_google_favorite_menu'):
            self.settings_google_favorite_menu.configure(values=["None"] + favorite_names if favorite_names else ["None"])
    
    def _on_favorite_selected(self, choice: str) -> None:
        """Handle favorite selection from dropdown."""
        if choice == "Select a favorite...":
            return
        
        for fav in self.favorites:
            if fav["name"] == choice:
                self.customer_id.set(fav["customer_id"])
                break
    
    def _on_settings_add_google_favorite(self) -> None:
        """Show dialog to add a new Google Ads favorite from Settings."""
        dialog = ctk.CTkToplevel(self.root)
        dialog.title("Add Google Ads Favorite")
        dialog.geometry("450x200")
        dialog.transient(self.root)
        dialog.grab_set()
        
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (450 // 2)
        y = (dialog.winfo_screenheight() // 2) - (200 // 2)
        dialog.geometry(f"450x200+{x}+{y}")
        
        name_var = ctk.StringVar(value="")
        customer_id_var = ctk.StringVar(value="")
        
        name_label = ctk.CTkLabel(dialog, text="Favorite Name:", font=ctk.CTkFont(size=12))
        name_label.pack(pady=(20, 5), padx=20)
        
        name_entry = ctk.CTkEntry(
            dialog,
            textvariable=name_var,
            placeholder_text="Enter a name for this favorite",
            width=410,
            font=ctk.CTkFont(size=12)
        )
        name_entry.pack(pady=5, padx=20)
        name_entry.focus()
        
        customer_id_label = ctk.CTkLabel(dialog, text="Customer ID (10 digits):", font=ctk.CTkFont(size=12))
        customer_id_label.pack(pady=(10, 5), padx=20)
        
        customer_id_entry = ctk.CTkEntry(
            dialog,
            textvariable=customer_id_var,
            placeholder_text="Enter 10-digit Customer ID",
            width=410,
            font=ctk.CTkFont(size=12)
        )
        customer_id_entry.pack(pady=5, padx=20)
        
        def save_favorite() -> None:
            name = name_var.get().strip()
            customer_id = customer_id_var.get().strip()
            customer_id_clean = customer_id.replace("-", "").replace(" ", "")
            
            if not name:
                self.status_text.set("Error: Please enter a name for the favorite")
                dialog.destroy()
                return
            
            if not customer_id_clean or not customer_id_clean.isdigit() or len(customer_id_clean) != 10:
                self.status_text.set("Error: Please enter a valid 10-digit Customer ID")
                dialog.destroy()
                return
            
            if any(fav["name"] == name for fav in self.favorites):
                self.status_text.set(f"Error: A favorite named '{name}' already exists")
                dialog.destroy()
                return
            
            self.favorites.append({
                "name": name,
                "customer_id": customer_id_clean
            })
            self._save_favorites()
            self._update_favorites_menu()
            self.status_text.set(f"Added favorite: {name}")
            self.logger.info(f"Added Google Ads favorite: {name}")
            dialog.destroy()
        
        button_frame = ctk.CTkFrame(dialog)
        button_frame.pack(pady=15, padx=20)
        
        save_btn = ctk.CTkButton(
            button_frame,
            text="Save",
            command=save_favorite,
            width=100,
            font=ctk.CTkFont(size=12)
        )
        save_btn.pack(side="left", padx=10)
        
        cancel_btn = ctk.CTkButton(
            button_frame,
            text="Cancel",
            command=dialog.destroy,
            width=100,
            font=ctk.CTkFont(size=12),
            fg_color="gray",
            hover_color="darkgray"
        )
        cancel_btn.pack(side="left", padx=10)
        
        dialog.bind('<Return>', lambda e: save_favorite())
        name_entry.bind('<Return>', lambda e: customer_id_entry.focus())
        customer_id_entry.bind('<Return>', lambda e: save_favorite())
    
    def _on_settings_edit_google_favorite(self) -> None:
        """Show dialog to edit a Google Ads favorite from Settings."""
        if not hasattr(self, 'settings_google_favorite_menu'):
            return
        current_selection = self.settings_google_favorite_menu.get()
        if not self.favorites or current_selection == "None":
            self.status_text.set("Error: Please select a favorite to edit")
            return
        
        selected_fav = None
        for fav in self.favorites:
            if fav["name"] == current_selection:
                selected_fav = fav
                break
        
        if not selected_fav:
            return
        
        dialog = ctk.CTkToplevel(self.root)
        dialog.title("Edit Google Ads Favorite")
        dialog.geometry("450x200")
        dialog.transient(self.root)
        dialog.grab_set()
        
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (450 // 2)
        y = (dialog.winfo_screenheight() // 2) - (200 // 2)
        dialog.geometry(f"450x200+{x}+{y}")
        
        name_var = ctk.StringVar(value=selected_fav["name"])
        customer_id_var = ctk.StringVar(value=selected_fav["customer_id"])
        
        name_label = ctk.CTkLabel(dialog, text="Favorite Name:", font=ctk.CTkFont(size=12))
        name_label.pack(pady=(20, 5), padx=20)
        
        name_entry = ctk.CTkEntry(
            dialog,
            textvariable=name_var,
            width=410,
            font=ctk.CTkFont(size=12)
        )
        name_entry.pack(pady=5, padx=20)
        name_entry.select_range(0, ctk.END)
        name_entry.focus()
        
        customer_id_label = ctk.CTkLabel(dialog, text="Customer ID (10 digits):", font=ctk.CTkFont(size=12))
        customer_id_label.pack(pady=(10, 5), padx=20)
        
        customer_id_entry = ctk.CTkEntry(
            dialog,
            textvariable=customer_id_var,
            width=410,
            font=ctk.CTkFont(size=12)
        )
        customer_id_entry.pack(pady=5, padx=20)
        
        def save_edit() -> None:
            new_name = name_var.get().strip()
            customer_id = customer_id_var.get().strip()
            customer_id_clean = customer_id.replace("-", "").replace(" ", "")
            
            if not new_name:
                self.status_text.set("Error: Please enter a name for the favorite")
                dialog.destroy()
                return
            
            if not customer_id_clean or not customer_id_clean.isdigit() or len(customer_id_clean) != 10:
                self.status_text.set("Error: Please enter a valid 10-digit Customer ID")
                dialog.destroy()
                return
            
            if any(fav["name"] == new_name and fav != selected_fav for fav in self.favorites):
                self.status_text.set(f"Error: A favorite named '{new_name}' already exists")
                dialog.destroy()
                return
            
            selected_fav["name"] = new_name
            selected_fav["customer_id"] = customer_id_clean
            self._save_favorites()
            self._update_favorites_menu()
            self.settings_google_favorite_menu.set(new_name)
            self.status_text.set(f"Updated favorite: {new_name}")
            self.logger.info(f"Updated Google Ads favorite: {new_name}")
            dialog.destroy()
        
        button_frame = ctk.CTkFrame(dialog)
        button_frame.pack(pady=15, padx=20)
        
        save_btn = ctk.CTkButton(
            button_frame,
            text="Save",
            command=save_edit,
            width=100,
            font=ctk.CTkFont(size=12)
        )
        save_btn.pack(side="left", padx=10)
        
        cancel_btn = ctk.CTkButton(
            button_frame,
            text="Cancel",
            command=dialog.destroy,
            width=100,
            font=ctk.CTkFont(size=12),
            fg_color="gray",
            hover_color="darkgray"
        )
        cancel_btn.pack(side="left", padx=10)
        
        dialog.bind('<Return>', lambda e: save_edit())
        name_entry.bind('<Return>', lambda e: customer_id_entry.focus())
        customer_id_entry.bind('<Return>', lambda e: save_edit())
    
    def _on_settings_delete_google_favorite(self) -> None:
        """Delete the selected Google Ads favorite from Settings."""
        if not hasattr(self, 'settings_google_favorite_menu'):
            return
        current_selection = self.settings_google_favorite_menu.get()
        if not self.favorites or current_selection == "None":
            self.status_text.set("Error: Please select a favorite to delete")
            return
        
        result = messagebox.askyesno(
            "Confirm Delete",
            f"Are you sure you want to delete the favorite '{current_selection}'?",
            icon="warning"
        )
        
        if result:
            self.favorites = [fav for fav in self.favorites if fav["name"] != current_selection]
            self._save_favorites()
            self._update_favorites_menu()
            self.settings_google_favorite_menu.set("None")
            self.status_text.set(f"Deleted favorite: {current_selection}")
            self.logger.info(f"Deleted Google Ads favorite: {current_selection}")
    
    def _load_meta_favorites(self) -> None:
        """Load Meta Ads favorites from JSON file."""
        try:
            if self.meta_favorites_file.exists():
                with open(str(self.meta_favorites_file), 'r', encoding='utf-8') as f:
                    self.meta_favorites = json.load(f)
            else:
                self.meta_favorites = []
        except json.JSONDecodeError as e:
            self.logger.error(f"meta_favorites.json is corrupted (invalid JSON): {e}", exc_info=True)
            self.meta_favorites = []
            if hasattr(self, "status_text"):
                self.status_text.set("meta_favorites.json was corrupted; using empty list. Backup or delete and restart.")
        except OSError as e:
            self.logger.error(f"Error reading meta_favorites.json: {e}", exc_info=True)
            self.meta_favorites = []
    
    def _save_meta_favorites(self) -> None:
        """Save Meta Ads favorites to JSON file."""
        try:
            with open(str(self.meta_favorites_file), 'w', encoding='utf-8') as f:
                json.dump(self.meta_favorites, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"Error saving Meta favorites: {e}", exc_info=True)
    
    def _load_ms_favorites(self) -> None:
        try:
            if self.ms_favorites_file.exists():
                with open(self.ms_favorites_file, 'r', encoding='utf-8') as f:
                    self.ms_favorites = json.load(f)
            else:
                self.ms_favorites = []
        except json.JSONDecodeError as e:
            self.logger.error(f"ms_favorites.json is corrupted (invalid JSON): {e}", exc_info=True)
            self.ms_favorites = []
            if hasattr(self, "status_text"):
                self.status_text.set("ms_favorites.json was corrupted; using empty list. Backup or delete and restart.")
        except OSError as e:
            self.logger.error(f"Error reading ms_favorites.json: {e}", exc_info=True)
            self.ms_favorites = []
    
    def _save_ms_favorites(self) -> None:
        try:
            with open(self.ms_favorites_file, 'w', encoding='utf-8') as f:
                json.dump(self.ms_favorites, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"Error saving MS favorites: {e}", exc_info=True)
    
    def _load_tiktok_favorites(self) -> None:
        try:
            if self.tiktok_favorites_file.exists():
                with open(self.tiktok_favorites_file, 'r', encoding='utf-8') as f:
                    self.tiktok_favorites = json.load(f)
            else:
                self.tiktok_favorites = []
        except json.JSONDecodeError as e:
            self.logger.error(f"tiktok_favorites.json is corrupted (invalid JSON): {e}", exc_info=True)
            self.tiktok_favorites = []
        except OSError as e:
            self.logger.error(f"Error reading tiktok_favorites.json: {e}", exc_info=True)
            self.tiktok_favorites = []
    
    def _save_tiktok_favorites(self) -> None:
        try:
            with open(self.tiktok_favorites_file, 'w', encoding='utf-8') as f:
                json.dump(self.tiktok_favorites, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"Error saving TikTok favorites: {e}", exc_info=True)
    
    def _load_reddit_favorites(self) -> None:
        try:
            if self.reddit_favorites_file.exists():
                with open(self.reddit_favorites_file, 'r', encoding='utf-8') as f:
                    self.reddit_favorites = json.load(f)
            else:
                self.reddit_favorites = []
        except json.JSONDecodeError as e:
            self.logger.error(f"reddit_favorites.json is corrupted (invalid JSON): {e}", exc_info=True)
            self.reddit_favorites = []
        except OSError as e:
            self.logger.error(f"Error reading reddit_favorites.json: {e}", exc_info=True)
            self.reddit_favorites = []
    
    def _save_reddit_favorites(self) -> None:
        try:
            with open(self.reddit_favorites_file, 'w', encoding='utf-8') as f:
                json.dump(self.reddit_favorites, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"Error saving Reddit favorites: {e}", exc_info=True)
    
    def _load_pinterest_favorites(self) -> None:
        try:
            if self.pinterest_favorites_file.exists():
                with open(self.pinterest_favorites_file, 'r', encoding='utf-8') as f:
                    self.pinterest_favorites = json.load(f)
            else:
                self.pinterest_favorites = []
        except json.JSONDecodeError as e:
            self.logger.error(f"pinterest_favorites.json is corrupted (invalid JSON): {e}", exc_info=True)
            self.pinterest_favorites = []
        except OSError as e:
            self.logger.error(f"Error reading pinterest_favorites.json: {e}", exc_info=True)
            self.pinterest_favorites = []
    
    def _save_pinterest_favorites(self) -> None:
        try:
            with open(self.pinterest_favorites_file, 'w', encoding='utf-8') as f:
                json.dump(self.pinterest_favorites, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"Error saving Pinterest favorites: {e}", exc_info=True)
    
    def _update_meta_favorites_menu(self) -> None:
        """Update the Meta ID combobox and settings menus."""
        meta_values = [f"{f['name']} ({f['account_id']})" for f in self.meta_favorites] if self.meta_favorites else []
        if hasattr(self, 'meta_account_id_combobox'):
            self.meta_account_id_combobox.configure(values=meta_values)
            self._set_meta_id_display_from_id()
        self._update_settings_meta_favorites_menu()
        if hasattr(self, 'settings_meta_favorite_menu'):
            meta_favorite_names = [fav["name"] for fav in self.meta_favorites] if self.meta_favorites else []
            self.settings_meta_favorite_menu.configure(values=["None"] + meta_favorite_names if meta_favorite_names else ["None"])
    
    def _update_settings_meta_favorites_menu(self) -> None:
        """Update the Default account Meta favorites dropdown menu."""
        meta_favorite_names = [fav["name"] for fav in self.meta_favorites] if self.meta_favorites else []
        if hasattr(self, 'settings_meta_favorite_menu'):
            self.settings_meta_favorite_menu.configure(values=["None"] + meta_favorite_names if meta_favorite_names else ["None"])
    
    def _update_settings_ms_favorite_menu(self) -> None:
        ms_names = [f["name"] for f in self.ms_favorites] if self.ms_favorites else []
        if hasattr(self, 'settings_ms_favorite_menu'):
            self.settings_ms_favorite_menu.configure(values=["None"] + ms_names if ms_names else ["None"])
    
    def _update_settings_tiktok_favorite_menu(self) -> None:
        tk_names = [f["name"] for f in self.tiktok_favorites] if self.tiktok_favorites else []
        if hasattr(self, 'settings_tiktok_favorite_menu'):
            self.settings_tiktok_favorite_menu.configure(values=["None"] + tk_names if tk_names else ["None"])
    
    def _update_settings_reddit_favorite_menu(self) -> None:
        rd_names = [f["name"] for f in self.reddit_favorites] if self.reddit_favorites else []
        if hasattr(self, 'settings_reddit_favorite_menu'):
            self.settings_reddit_favorite_menu.configure(values=["None"] + rd_names if rd_names else ["None"])
    
    def _update_settings_pinterest_favorite_menu(self) -> None:
        pt_names = [f["name"] for f in self.pinterest_favorites] if self.pinterest_favorites else []
        if hasattr(self, 'settings_pinterest_favorite_menu'):
            self.settings_pinterest_favorite_menu.configure(values=["None"] + pt_names if pt_names else ["None"])
    
    def _update_ms_favorites_combobox(self) -> None:
        ms_values = [f"{f['name']} ({f['customer_id']})" for f in self.ms_favorites] if self.ms_favorites else []
        if hasattr(self, 'ms_customer_id_combobox'):
            self.ms_customer_id_combobox.configure(values=ms_values)
            self._set_ms_id_display_from_id()
        self._update_settings_ms_favorite_menu()
        if hasattr(self, 'settings_ms_favorite_menu'):
            ms_names = [f["name"] for f in self.ms_favorites] if self.ms_favorites else []
            self.settings_ms_favorite_menu.configure(values=["None"] + ms_names if ms_names else ["None"])
    
    def _update_tiktok_favorites_combobox(self) -> None:
        tk_values = [f"{f['name']} ({f['advertiser_id']})" for f in self.tiktok_favorites] if self.tiktok_favorites else []
        if hasattr(self, 'tiktok_account_id_combobox'):
            self.tiktok_account_id_combobox.configure(values=tk_values)
            self._set_tiktok_id_display_from_id()
        self._update_settings_tiktok_favorite_menu()
        if hasattr(self, 'settings_tiktok_favorite_menu'):
            tk_names = [f["name"] for f in self.tiktok_favorites] if self.tiktok_favorites else []
            self.settings_tiktok_favorite_menu.configure(values=["None"] + tk_names if tk_names else ["None"])
    
    def _update_reddit_favorites_combobox(self) -> None:
        rd_values = [f"{f['name']} ({f['account_id']})" for f in self.reddit_favorites] if self.reddit_favorites else []
        if hasattr(self, 'reddit_account_id_combobox'):
            self.reddit_account_id_combobox.configure(values=rd_values)
            self._set_reddit_id_display_from_id()
        self._update_settings_reddit_favorite_menu()
        if hasattr(self, 'settings_reddit_favorite_menu'):
            rd_names = [f["name"] for f in self.reddit_favorites] if self.reddit_favorites else []
            self.settings_reddit_favorite_menu.configure(values=["None"] + rd_names if rd_names else ["None"])
    
    def _update_pinterest_favorites_combobox(self) -> None:
        pt_values = [f"{f['name']} ({f['advertiser_id']})" for f in self.pinterest_favorites] if self.pinterest_favorites else []
        if hasattr(self, 'pinterest_account_id_combobox'):
            self.pinterest_account_id_combobox.configure(values=pt_values)
            self._set_pinterest_id_display_from_id()
        self._update_settings_pinterest_favorite_menu()
        if hasattr(self, 'settings_pinterest_favorite_menu'):
            pt_names = [f["name"] for f in self.pinterest_favorites] if self.pinterest_favorites else []
            self.settings_pinterest_favorite_menu.configure(values=["None"] + pt_names if pt_names else ["None"])
    
    def _on_meta_favorite_selected(self, choice: str) -> None:
        """Handle Meta favorite selection from dropdown."""
        if choice == "Select a favorite...":
            return
        
        for fav in self.meta_favorites:
            if fav["name"] == choice:
                self.meta_account_id.set(fav["account_id"])
                break
    
    def _on_settings_add_meta_favorite(self) -> None:
        """Show dialog to add a new Meta Ads favorite from Settings."""
        dialog = ctk.CTkToplevel(self.root)
        dialog.title("Add Meta Ads Favorite")
        dialog.geometry("450x200")
        dialog.transient(self.root)
        dialog.grab_set()
        
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (450 // 2)
        y = (dialog.winfo_screenheight() // 2) - (200 // 2)
        dialog.geometry(f"450x200+{x}+{y}")
        
        name_var = ctk.StringVar(value="")
        account_id_var = ctk.StringVar(value="")
        
        name_label = ctk.CTkLabel(dialog, text="Favorite Name:", font=ctk.CTkFont(size=12))
        name_label.pack(pady=(20, 5), padx=20)
        
        name_entry = ctk.CTkEntry(
            dialog,
            textvariable=name_var,
            placeholder_text="Enter a name for this favorite",
            width=410,
            font=ctk.CTkFont(size=12)
        )
        name_entry.pack(pady=5, padx=20)
        name_entry.focus()
        
        account_id_label = ctk.CTkLabel(dialog, text="Account ID (e.g., act_12345678):", font=ctk.CTkFont(size=12))
        account_id_label.pack(pady=(10, 5), padx=20)
        
        account_id_entry = ctk.CTkEntry(
            dialog,
            textvariable=account_id_var,
            placeholder_text="Enter Account ID",
            width=410,
            font=ctk.CTkFont(size=12)
        )
        account_id_entry.pack(pady=5, padx=20)
        
        def save_favorite() -> None:
            name = name_var.get().strip()
            account_id = account_id_var.get().strip()
            account_id_clean = account_id.replace("-", "").replace(" ", "")
            
            if not name:
                self.status_text.set("Error: Please enter a name for the favorite")
                dialog.destroy()
                return
            
            # Auto-prepend "act_" if user entered just the number
            if account_id_clean.isdigit():
                account_id_clean = f"act_{account_id_clean}"
            
            if account_id_clean == "act_" or len(account_id_clean) <= 4:
                self.status_text.set("Error: Please enter a valid Ad Account ID (format: act_12345678)")
                dialog.destroy()
                return
            
            if not account_id_clean.startswith("act_"):
                self.status_text.set("Error: Ad Account ID must start with 'act_' or be a valid number")
                dialog.destroy()
                return
            
            # Additional validation: after "act_", should have digits
            account_part = account_id_clean[4:]
            if not account_part.isdigit():
                self.status_text.set("Error: Ad Account ID must be in format: act_12345678 (numbers after 'act_')")
                dialog.destroy()
                return
            
            if any(fav["name"] == name for fav in self.meta_favorites):
                self.status_text.set(f"Error: A favorite named '{name}' already exists")
                dialog.destroy()
                return
            
            self.meta_favorites.append({
                "name": name,
                "account_id": account_id_clean
            })
            self._save_meta_favorites()
            self._update_meta_favorites_menu()
            self.status_text.set(f"Added favorite: {name}")
            self.logger.info(f"Added Meta Ads favorite: {name}")
            dialog.destroy()
        
        button_frame = ctk.CTkFrame(dialog)
        button_frame.pack(pady=15, padx=20)
        
        save_btn = ctk.CTkButton(
            button_frame,
            text="Save",
            command=save_favorite,
            width=100,
            font=ctk.CTkFont(size=12)
        )
        save_btn.pack(side="left", padx=10)
        
        cancel_btn = ctk.CTkButton(
            button_frame,
            text="Cancel",
            command=dialog.destroy,
            width=100,
            font=ctk.CTkFont(size=12),
            fg_color="gray",
            hover_color="darkgray"
        )
        cancel_btn.pack(side="left", padx=10)
        
        dialog.bind('<Return>', lambda e: save_favorite())
        name_entry.bind('<Return>', lambda e: account_id_entry.focus())
        account_id_entry.bind('<Return>', lambda e: save_favorite())
    
    def _on_settings_edit_meta_favorite(self) -> None:
        """Show dialog to edit a Meta Ads favorite from Settings."""
        if not hasattr(self, 'settings_meta_favorite_menu'):
            return
        current_selection = self.settings_meta_favorite_menu.get()
        if not self.meta_favorites or current_selection == "None":
            self.status_text.set("Error: Please select a favorite to edit")
            return
        
        selected_fav = None
        for fav in self.meta_favorites:
            if fav["name"] == current_selection:
                selected_fav = fav
                break
        
        if not selected_fav:
            return
        
        dialog = ctk.CTkToplevel(self.root)
        dialog.title("Edit Meta Ads Favorite")
        dialog.geometry("450x200")
        dialog.transient(self.root)
        dialog.grab_set()
        
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (450 // 2)
        y = (dialog.winfo_screenheight() // 2) - (200 // 2)
        dialog.geometry(f"450x200+{x}+{y}")
        
        name_var = ctk.StringVar(value=selected_fav["name"])
        account_id_var = ctk.StringVar(value=selected_fav["account_id"])
        
        name_label = ctk.CTkLabel(dialog, text="Favorite Name:", font=ctk.CTkFont(size=12))
        name_label.pack(pady=(20, 5), padx=20)
        
        name_entry = ctk.CTkEntry(
            dialog,
            textvariable=name_var,
            width=410,
            font=ctk.CTkFont(size=12)
        )
        name_entry.pack(pady=5, padx=20)
        name_entry.select_range(0, ctk.END)
        name_entry.focus()
        
        account_id_label = ctk.CTkLabel(dialog, text="Account ID (e.g., act_12345678):", font=ctk.CTkFont(size=12))
        account_id_label.pack(pady=(10, 5), padx=20)
        
        account_id_entry = ctk.CTkEntry(
            dialog,
            textvariable=account_id_var,
            width=410,
            font=ctk.CTkFont(size=12)
        )
        account_id_entry.pack(pady=5, padx=20)
        
        def save_edit() -> None:
            new_name = name_var.get().strip()
            account_id = account_id_var.get().strip()
            account_id_clean = account_id.replace("-", "").replace(" ", "")
            
            if not new_name:
                self.status_text.set("Error: Please enter a name for the favorite")
                dialog.destroy()
                return
            
            # Auto-prepend "act_" if user entered just the number
            if account_id_clean.isdigit():
                account_id_clean = f"act_{account_id_clean}"
            
            if account_id_clean == "act_" or len(account_id_clean) <= 4:
                self.status_text.set("Error: Please enter a valid Ad Account ID (format: act_12345678)")
                dialog.destroy()
                return
            
            if not account_id_clean.startswith("act_"):
                self.status_text.set("Error: Ad Account ID must start with 'act_' or be a valid number")
                dialog.destroy()
                return
            
            # Additional validation: after "act_", should have digits
            account_part = account_id_clean[4:]
            if not account_part.isdigit():
                self.status_text.set("Error: Ad Account ID must be in format: act_12345678 (numbers after 'act_')")
                dialog.destroy()
                return
            
            if any(fav["name"] == new_name and fav != selected_fav for fav in self.meta_favorites):
                self.status_text.set(f"Error: A favorite named '{new_name}' already exists")
                dialog.destroy()
                return
            
            selected_fav["name"] = new_name
            selected_fav["account_id"] = account_id_clean
            self._save_meta_favorites()
            self._update_meta_favorites_menu()
            self.settings_meta_favorite_menu.set(new_name)
            self.status_text.set(f"Updated favorite: {new_name}")
            self.logger.info(f"Updated Meta Ads favorite: {new_name}")
            dialog.destroy()
        
        button_frame = ctk.CTkFrame(dialog)
        button_frame.pack(pady=15, padx=20)
        
        save_btn = ctk.CTkButton(
            button_frame,
            text="Save",
            command=save_edit,
            width=100,
            font=ctk.CTkFont(size=12)
        )
        save_btn.pack(side="left", padx=10)
        
        cancel_btn = ctk.CTkButton(
            button_frame,
            text="Cancel",
            command=dialog.destroy,
            width=100,
            font=ctk.CTkFont(size=12),
            fg_color="gray",
            hover_color="darkgray"
        )
        cancel_btn.pack(side="left", padx=10)
        
        dialog.bind('<Return>', lambda e: save_edit())
        name_entry.bind('<Return>', lambda e: account_id_entry.focus())
        account_id_entry.bind('<Return>', lambda e: save_edit())
    
    def _on_settings_delete_meta_favorite(self) -> None:
        """Delete the selected Meta Ads favorite from Settings."""
        if not hasattr(self, 'settings_meta_favorite_menu'):
            return
        current_selection = self.settings_meta_favorite_menu.get()
        if not self.meta_favorites or current_selection == "None":
            self.status_text.set("Error: Please select a favorite to delete")
            return
        
        result = messagebox.askyesno(
            "Confirm Delete",
            f"Are you sure you want to delete the favorite '{current_selection}'?",
            icon="warning"
        )
        
        if result:
            self.meta_favorites = [fav for fav in self.meta_favorites if fav["name"] != current_selection]
            self._save_meta_favorites()
            self._update_meta_favorites_menu()
            self.settings_meta_favorite_menu.set("None")
            self.status_text.set(f"Deleted favorite: {current_selection}")
            self.logger.info(f"Deleted Meta Ads favorite: {current_selection}")
    
    def _on_ms_default_favorite_changed(self, choice: str) -> None:
        self.settings["default_ms_favorite"] = None if choice == "None" else choice
        self._save_settings()
        if choice != "None" and self.ms_favorites:
            for f in self.ms_favorites:
                if f.get("name") == choice and f.get("customer_id"):
                    self.ms_customer_id.set(f["customer_id"].strip())
                    self._set_ms_id_display_from_id()
                    break
    
    def _on_tiktok_default_favorite_changed(self, choice: str) -> None:
        self.settings["default_tiktok_favorite"] = None if choice == "None" else choice
        self._save_settings()
        if choice != "None" and self.tiktok_favorites:
            for f in self.tiktok_favorites:
                if f.get("name") == choice and f.get("advertiser_id"):
                    self.tiktok_account_id.set(f["advertiser_id"].strip())
                    self._set_tiktok_id_display_from_id()
                    break
    
    def _on_reddit_default_favorite_changed(self, choice: str) -> None:
        self.settings["default_reddit_favorite"] = None if choice == "None" else choice
        self._save_settings()
        if choice != "None" and self.reddit_favorites:
            for f in self.reddit_favorites:
                if f.get("name") == choice and f.get("account_id"):
                    self.reddit_account_id.set(f["account_id"].strip())
                    self._set_reddit_id_display_from_id()
                    break
    
    def _on_pinterest_default_favorite_changed(self, choice: str) -> None:
        self.settings["default_pinterest_favorite"] = None if choice == "None" else choice
        self._save_settings()
        if choice != "None" and self.pinterest_favorites:
            for f in self.pinterest_favorites:
                if f.get("name") == choice and f.get("advertiser_id"):
                    self.pinterest_account_id.set(f["advertiser_id"].strip())
                    self._set_pinterest_id_display_from_id()
                    break
    
    def _on_settings_add_ms_favorite(self) -> None:
        dialog = ctk.CTkToplevel(self.root)
        dialog.title("Add Microsoft Ads Favorite")
        dialog.geometry("450x200")
        dialog.transient(self.root)
        dialog.grab_set()
        name_var = ctk.StringVar(value="")
        id_var = ctk.StringVar(value="")
        ctk.CTkLabel(dialog, text="Favorite Name:", font=ctk.CTkFont(size=12)).pack(pady=(20, 5), padx=20)
        ctk.CTkEntry(dialog, textvariable=name_var, placeholder_text="Enter name", width=410, font=ctk.CTkFont(size=12)).pack(pady=5, padx=20)
        ctk.CTkLabel(dialog, text="Customer ID (digits):", font=ctk.CTkFont(size=12)).pack(pady=(10, 5), padx=20)
        ctk.CTkEntry(dialog, textvariable=id_var, placeholder_text="Enter Customer ID", width=410, font=ctk.CTkFont(size=12)).pack(pady=5, padx=20)
        def save():
            name, cid = name_var.get().strip(), id_var.get().strip().replace("-", "").replace(" ", "")
            if not name or not cid or not cid.isdigit():
                self.status_text.set("Error: Name and valid Customer ID required")
                dialog.destroy()
                return
            if any(f["name"] == name for f in self.ms_favorites):
                self.status_text.set(f"Error: A favorite named '{name}' already exists")
                dialog.destroy()
                return
            self.ms_favorites.append({"name": name, "customer_id": cid})
            self._save_ms_favorites()
            self._update_ms_favorites_combobox()
            self.status_text.set(f"Added Microsoft Ads favorite: {name}")
            dialog.destroy()
        btn_f = ctk.CTkFrame(dialog)
        btn_f.pack(pady=15, padx=20)
        ctk.CTkButton(btn_f, text="Save", command=save, width=100, font=ctk.CTkFont(size=12)).pack(side="left", padx=10)
        ctk.CTkButton(btn_f, text="Cancel", command=dialog.destroy, width=100, font=ctk.CTkFont(size=12), fg_color="gray", hover_color="darkgray").pack(side="left", padx=10)
    
    def _on_settings_edit_ms_favorite(self) -> None:
        if not hasattr(self, 'settings_ms_favorite_menu'):
            return
        current = self.settings_ms_favorite_menu.get()
        if current == "None":
            self.status_text.set("Error: Select a favorite to edit")
            return
        selected = next((f for f in self.ms_favorites if f["name"] == current), None)
        if not selected:
            return
        dialog = ctk.CTkToplevel(self.root)
        dialog.title("Edit Microsoft Ads Favorite")
        dialog.geometry("450x180")
        dialog.transient(self.root)
        dialog.grab_set()
        name_var = ctk.StringVar(value=selected["name"])
        ctk.CTkLabel(dialog, text="Favorite Name:", font=ctk.CTkFont(size=12)).pack(pady=(20, 5), padx=20)
        ctk.CTkEntry(dialog, textvariable=name_var, width=410, font=ctk.CTkFont(size=12)).pack(pady=5, padx=20)
        def save_edit():
            new_name = name_var.get().strip()
            if not new_name:
                dialog.destroy()
                return
            if any(f["name"] == new_name and f != selected for f in self.ms_favorites):
                self.status_text.set(f"Error: A favorite named '{new_name}' already exists")
                dialog.destroy()
                return
            selected["name"] = new_name
            self._save_ms_favorites()
            self._update_ms_favorites_combobox()
            self.status_text.set(f"Updated: {new_name}")
            dialog.destroy()
        btn_f = ctk.CTkFrame(dialog)
        btn_f.pack(pady=15, padx=20)
        ctk.CTkButton(btn_f, text="Save", command=save_edit, width=100, font=ctk.CTkFont(size=12)).pack(side="left", padx=10)
        ctk.CTkButton(btn_f, text="Cancel", command=dialog.destroy, width=100, font=ctk.CTkFont(size=12), fg_color="gray", hover_color="darkgray").pack(side="left", padx=10)
    
    def _on_settings_delete_ms_favorite(self) -> None:
        if not hasattr(self, 'settings_ms_favorite_menu'):
            return
        current = self.settings_ms_favorite_menu.get()
        if current == "None":
            self.status_text.set("Error: Select a favorite to delete")
            return
        if messagebox.askyesno("Confirm Delete", f"Delete favorite '{current}'?", icon="warning"):
            self.ms_favorites = [f for f in self.ms_favorites if f["name"] != current]
            self._save_ms_favorites()
            self._update_ms_favorites_combobox()
            self.settings_ms_favorite_menu.set("None")
            self.status_text.set(f"Deleted: {current}")
    
    def _on_settings_add_tiktok_favorite(self) -> None:
        dialog = ctk.CTkToplevel(self.root)
        dialog.title("Add TikTok Ads Favorite")
        dialog.geometry("450x200")
        dialog.transient(self.root)
        dialog.grab_set()
        name_var = ctk.StringVar(value="")
        id_var = ctk.StringVar(value="")
        ctk.CTkLabel(dialog, text="Favorite Name:", font=ctk.CTkFont(size=12)).pack(pady=(20, 5), padx=20)
        ctk.CTkEntry(dialog, textvariable=name_var, placeholder_text="Enter name", width=410, font=ctk.CTkFont(size=12)).pack(pady=5, padx=20)
        ctk.CTkLabel(dialog, text="Advertiser ID:", font=ctk.CTkFont(size=12)).pack(pady=(10, 5), padx=20)
        ctk.CTkEntry(dialog, textvariable=id_var, placeholder_text="Enter Advertiser ID", width=410, font=ctk.CTkFont(size=12)).pack(pady=5, padx=20)
        def save():
            name, aid = name_var.get().strip(), id_var.get().strip()
            if not name or not aid:
                self.status_text.set("Error: Name and Advertiser ID required")
                dialog.destroy()
                return
            if any(f["name"] == name for f in self.tiktok_favorites):
                self.status_text.set(f"Error: A favorite named '{name}' already exists")
                dialog.destroy()
                return
            self.tiktok_favorites.append({"name": name, "advertiser_id": aid})
            self._save_tiktok_favorites()
            self._update_tiktok_favorites_combobox()
            self.status_text.set(f"Added TikTok Ads favorite: {name}")
            dialog.destroy()
        btn_f = ctk.CTkFrame(dialog)
        btn_f.pack(pady=15, padx=20)
        ctk.CTkButton(btn_f, text="Save", command=save, width=100, font=ctk.CTkFont(size=12)).pack(side="left", padx=10)
        ctk.CTkButton(btn_f, text="Cancel", command=dialog.destroy, width=100, font=ctk.CTkFont(size=12), fg_color="gray", hover_color="darkgray").pack(side="left", padx=10)
    
    def _on_settings_edit_tiktok_favorite(self) -> None:
        if not hasattr(self, 'settings_tiktok_favorite_menu'):
            return
        current = self.settings_tiktok_favorite_menu.get()
        if current == "None":
            self.status_text.set("Error: Select a favorite to edit")
            return
        selected = next((f for f in self.tiktok_favorites if f["name"] == current), None)
        if not selected:
            return
        dialog = ctk.CTkToplevel(self.root)
        dialog.title("Edit TikTok Ads Favorite")
        dialog.geometry("450x180")
        dialog.transient(self.root)
        dialog.grab_set()
        name_var = ctk.StringVar(value=selected["name"])
        ctk.CTkLabel(dialog, text="Favorite Name:", font=ctk.CTkFont(size=12)).pack(pady=(20, 5), padx=20)
        ctk.CTkEntry(dialog, textvariable=name_var, width=410, font=ctk.CTkFont(size=12)).pack(pady=5, padx=20)
        def save_edit():
            new_name = name_var.get().strip()
            if not new_name:
                dialog.destroy()
                return
            if any(f["name"] == new_name and f != selected for f in self.tiktok_favorites):
                self.status_text.set(f"Error: A favorite named '{new_name}' already exists")
                dialog.destroy()
                return
            selected["name"] = new_name
            self._save_tiktok_favorites()
            self._update_tiktok_favorites_combobox()
            self.status_text.set(f"Updated: {new_name}")
            dialog.destroy()
        btn_f = ctk.CTkFrame(dialog)
        btn_f.pack(pady=15, padx=20)
        ctk.CTkButton(btn_f, text="Save", command=save_edit, width=100, font=ctk.CTkFont(size=12)).pack(side="left", padx=10)
        ctk.CTkButton(btn_f, text="Cancel", command=dialog.destroy, width=100, font=ctk.CTkFont(size=12), fg_color="gray", hover_color="darkgray").pack(side="left", padx=10)
    
    def _on_settings_delete_tiktok_favorite(self) -> None:
        if not hasattr(self, 'settings_tiktok_favorite_menu'):
            return
        current = self.settings_tiktok_favorite_menu.get()
        if current == "None":
            self.status_text.set("Error: Select a favorite to delete")
            return
        if messagebox.askyesno("Confirm Delete", f"Delete favorite '{current}'?", icon="warning"):
            self.tiktok_favorites = [f for f in self.tiktok_favorites if f["name"] != current]
            self._save_tiktok_favorites()
            self._update_tiktok_favorites_combobox()
            self.settings_tiktok_favorite_menu.set("None")
            self.status_text.set(f"Deleted: {current}")
    
    def _on_settings_add_reddit_favorite(self) -> None:
        dialog = ctk.CTkToplevel(self.root)
        dialog.title("Add Reddit Ads Favorite")
        dialog.geometry("450x280")
        dialog.transient(self.root)
        dialog.grab_set()
        name_var = ctk.StringVar(value="")
        id_var = ctk.StringVar(value="")
        ctk.CTkLabel(dialog, text="Favorite Name:", font=ctk.CTkFont(size=12)).pack(pady=(20, 5), padx=20)
        ctk.CTkEntry(dialog, textvariable=name_var, placeholder_text="Enter name", width=410, font=ctk.CTkFont(size=12)).pack(pady=5, padx=20)
        ctk.CTkLabel(dialog, text="Account ID:", font=ctk.CTkFont(size=12)).pack(pady=(10, 5), padx=20)
        ctk.CTkEntry(dialog, textvariable=id_var, placeholder_text="Enter Account ID", width=410, font=ctk.CTkFont(size=12)).pack(pady=5, padx=20)
        def save():
            name, aid = name_var.get().strip(), id_var.get().strip()
            if not name or not aid:
                self.status_text.set("Error: Name and Account ID required")
                dialog.destroy()
                return
            if any(f["name"] == name for f in self.reddit_favorites):
                self.status_text.set(f"Error: A favorite named '{name}' already exists")
                dialog.destroy()
                return
            self.reddit_favorites.append({"name": name, "account_id": aid})
            self._save_reddit_favorites()
            self._update_reddit_favorites_combobox()
            self._update_settings_reddit_favorite_menu()
            self.status_text.set(f"Added Reddit Ads favorite: {name}")
            dialog.destroy()
        btn_f = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_f.pack(pady=20, padx=20, fill="x")
        ctk.CTkButton(btn_f, text="Save", command=save, width=120, height=36, font=ctk.CTkFont(size=12, weight="bold"), fg_color="green", hover_color="darkgreen").pack(side="left", padx=10)
        ctk.CTkButton(btn_f, text="Cancel", command=dialog.destroy, width=120, height=36, font=ctk.CTkFont(size=12), fg_color="gray", hover_color="darkgray").pack(side="left", padx=10)
        dialog.update_idletasks()
        x = max(0, (dialog.winfo_screenwidth() - 450) // 2)
        y = max(0, (dialog.winfo_screenheight() - 280) // 2)
        dialog.geometry(f"450x280+{x}+{y}")
    
    def _on_settings_edit_reddit_favorite(self) -> None:
        if not hasattr(self, 'settings_reddit_favorite_menu'):
            return
        current = self.settings_reddit_favorite_menu.get()
        if current == "None":
            self.status_text.set("Error: Select a favorite to edit")
            return
        selected = next((f for f in self.reddit_favorites if f["name"] == current), None)
        if not selected:
            return
        dialog = ctk.CTkToplevel(self.root)
        dialog.title("Edit Reddit Ads Favorite")
        dialog.geometry("450x180")
        dialog.transient(self.root)
        dialog.grab_set()
        name_var = ctk.StringVar(value=selected["name"])
        ctk.CTkLabel(dialog, text="Favorite Name:", font=ctk.CTkFont(size=12)).pack(pady=(20, 5), padx=20)
        ctk.CTkEntry(dialog, textvariable=name_var, width=410, font=ctk.CTkFont(size=12)).pack(pady=5, padx=20)
        def save_edit():
            new_name = name_var.get().strip()
            if not new_name:
                dialog.destroy()
                return
            if any(f["name"] == new_name and f != selected for f in self.reddit_favorites):
                self.status_text.set(f"Error: A favorite named '{new_name}' already exists")
                dialog.destroy()
                return
            selected["name"] = new_name
            self._save_reddit_favorites()
            self._update_reddit_favorites_combobox()
            self.status_text.set(f"Updated: {new_name}")
            dialog.destroy()
        btn_f = ctk.CTkFrame(dialog)
        btn_f.pack(pady=15, padx=20)
        ctk.CTkButton(btn_f, text="Save", command=save_edit, width=100, font=ctk.CTkFont(size=12)).pack(side="left", padx=10)
        ctk.CTkButton(btn_f, text="Cancel", command=dialog.destroy, width=100, font=ctk.CTkFont(size=12), fg_color="gray", hover_color="darkgray").pack(side="left", padx=10)
    
    def _on_settings_delete_reddit_favorite(self) -> None:
        if not hasattr(self, 'settings_reddit_favorite_menu'):
            return
        current = self.settings_reddit_favorite_menu.get()
        if current == "None":
            self.status_text.set("Error: Select a favorite to delete")
            return
        if messagebox.askyesno("Confirm Delete", f"Delete favorite '{current}'?", icon="warning"):
            self.reddit_favorites = [f for f in self.reddit_favorites if f["name"] != current]
            self._save_reddit_favorites()
            self._update_reddit_favorites_combobox()
            self.settings_reddit_favorite_menu.set("None")
            self.status_text.set(f"Deleted: {current}")
    
    def _on_settings_add_pinterest_favorite(self) -> None:
        dialog = ctk.CTkToplevel(self.root)
        dialog.title("Add Pinterest Ads Favorite")
        dialog.geometry("450x200")
        dialog.transient(self.root)
        dialog.grab_set()
        name_var = ctk.StringVar(value="")
        id_var = ctk.StringVar(value="")
        ctk.CTkLabel(dialog, text="Favorite Name:", font=ctk.CTkFont(size=12)).pack(pady=(20, 5), padx=20)
        ctk.CTkEntry(dialog, textvariable=name_var, placeholder_text="Enter name", width=410, font=ctk.CTkFont(size=12)).pack(pady=5, padx=20)
        ctk.CTkLabel(dialog, text="Advertiser ID:", font=ctk.CTkFont(size=12)).pack(pady=(10, 5), padx=20)
        ctk.CTkEntry(dialog, textvariable=id_var, placeholder_text="Enter Advertiser ID", width=410, font=ctk.CTkFont(size=12)).pack(pady=5, padx=20)
        def save():
            name, aid = name_var.get().strip(), id_var.get().strip()
            if not name or not aid:
                self.status_text.set("Error: Name and Advertiser ID required")
                dialog.destroy()
                return
            if any(f["name"] == name for f in self.pinterest_favorites):
                self.status_text.set(f"Error: A favorite named '{name}' already exists")
                dialog.destroy()
                return
            self.pinterest_favorites.append({"name": name, "advertiser_id": aid})
            self._save_pinterest_favorites()
            self._update_pinterest_favorites_combobox()
            self.status_text.set(f"Added Pinterest Ads favorite: {name}")
            dialog.destroy()
        btn_f = ctk.CTkFrame(dialog)
        btn_f.pack(pady=15, padx=20)
        ctk.CTkButton(btn_f, text="Save", command=save, width=100, font=ctk.CTkFont(size=12)).pack(side="left", padx=10)
        ctk.CTkButton(btn_f, text="Cancel", command=dialog.destroy, width=100, font=ctk.CTkFont(size=12), fg_color="gray", hover_color="darkgray").pack(side="left", padx=10)
    
    def _on_settings_edit_pinterest_favorite(self) -> None:
        if not hasattr(self, 'settings_pinterest_favorite_menu'):
            return
        current = self.settings_pinterest_favorite_menu.get()
        if current == "None":
            self.status_text.set("Error: Select a favorite to edit")
            return
        selected = next((f for f in self.pinterest_favorites if f["name"] == current), None)
        if not selected:
            return
        dialog = ctk.CTkToplevel(self.root)
        dialog.title("Edit Pinterest Ads Favorite")
        dialog.geometry("450x180")
        dialog.transient(self.root)
        dialog.grab_set()
        name_var = ctk.StringVar(value=selected["name"])
        ctk.CTkLabel(dialog, text="Favorite Name:", font=ctk.CTkFont(size=12)).pack(pady=(20, 5), padx=20)
        ctk.CTkEntry(dialog, textvariable=name_var, width=410, font=ctk.CTkFont(size=12)).pack(pady=5, padx=20)
        def save_edit():
            new_name = name_var.get().strip()
            if not new_name:
                dialog.destroy()
                return
            if any(f["name"] == new_name and f != selected for f in self.pinterest_favorites):
                self.status_text.set(f"Error: A favorite named '{new_name}' already exists")
                dialog.destroy()
                return
            selected["name"] = new_name
            self._save_pinterest_favorites()
            self._update_pinterest_favorites_combobox()
            self.status_text.set(f"Updated: {new_name}")
            dialog.destroy()
        btn_f = ctk.CTkFrame(dialog)
        btn_f.pack(pady=15, padx=20)
        ctk.CTkButton(btn_f, text="Save", command=save_edit, width=100, font=ctk.CTkFont(size=12)).pack(side="left", padx=10)
        ctk.CTkButton(btn_f, text="Cancel", command=dialog.destroy, width=100, font=ctk.CTkFont(size=12), fg_color="gray", hover_color="darkgray").pack(side="left", padx=10)
    
    def _on_settings_delete_pinterest_favorite(self) -> None:
        if not hasattr(self, 'settings_pinterest_favorite_menu'):
            return
        current = self.settings_pinterest_favorite_menu.get()
        if current == "None":
            self.status_text.set("Error: Select a favorite to delete")
            return
        if messagebox.askyesno("Confirm Delete", f"Delete favorite '{current}'?", icon="warning"):
            self.pinterest_favorites = [f for f in self.pinterest_favorites if f["name"] != current]
            self._save_pinterest_favorites()
            self._update_pinterest_favorites_combobox()
            self.settings_pinterest_favorite_menu.set("None")
            self.status_text.set(f"Deleted: {current}")
    
    def run(self) -> None:
        """Start the GUI application."""
        try:
            self.root.mainloop()
        except Exception as e:
            self.logger.error(f"Fatal error in GUI: {e}", exc_info=True)


def main() -> None:
    """Entry point for the application."""
    try:
        app = AdsReportFetcherApp()
        app.run()
    except Exception as e:
        logging.basicConfig(
            level=logging.ERROR,
            format='%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %I:%M:%S %p',
            handlers=[logging.FileHandler('app_debug.log')]
        )
        logger = logging.getLogger(__name__)
        logger.error(f"Fatal error: {e}", exc_info=True)


if __name__ == "__main__":
    main()
