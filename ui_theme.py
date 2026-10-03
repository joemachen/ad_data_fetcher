"""
UI design tokens for Ads Report Fetcher: colors, fonts and spacing in one place.

Colors are (light, dark) tuples, which CustomTkinter resolves for the current appearance mode,
so both the light and dark themes keep working. Plain Tk widgets (the log text box) can't take
tuples; use resolve() for those and re-apply on theme change.

Button styles are kwargs dicts for CTkButton, e.g. ctk.CTkButton(parent, text="Run", **ui.PRIMARY_BTN).
They only set color keys, so callers can still pass their own font/size/command.
"""

from typing import Dict, Tuple, Union

import customtkinter as ctk

Color = Union[str, Tuple[str, str]]

# --- Palette (light, dark) — zinc neutrals + a single blue accent ---
SURFACE = ("#F4F4F5", "#18181B")  # section backgrounds
CARD = ("#FFFFFF", "#27272A")  # cards / elevated panels
CARD_ACTIVE = ("#EFF6FF", "#1E293B")  # selected platform card
BORDER = ("#D4D4D8", "#3F3F46")
TEXT = ("#18181B", "#F4F4F5")
TEXT_MUTED = ("#71717A", "#A1A1AA")
ACCENT = ("#2563EB", "#3B82F6")
ACCENT_HOVER = ("#1D4ED8", "#2563EB")
SUCCESS = ("#047857", "#6EE7B7")  # muted emerald text
WARNING = ("#B45309", "#FCD34D")  # muted amber text
DANGER = ("#B91C1C", "#FCA5A5")  # muted red text
DANGER_FILL = ("#DC2626", "#B91C1C")
DANGER_FILL_HOVER = ("#B91C1C", "#991B1B")
NEUTRAL_FILL = ("#E4E4E7", "#3F3F46")
NEUTRAL_FILL_HOVER = ("#D4D4D8", "#52525B")
TRACK = ("#E4E4E7", "#27272A")  # progress bar background
SCROLLBAR = ("#D4D4D8", "#3F3F46")
SCROLLBAR_HOVER = ("#A1A1AA", "#52525B")
LOG_BG = ("#FAFAFA", "#18181B")
LOG_FG = ("#27272A", "#E4E4E7")

# --- Button styles ---
PRIMARY_BTN: Dict[str, Color] = {"fg_color": ACCENT, "hover_color": ACCENT_HOVER, "text_color": "#FFFFFF"}
SECONDARY_BTN: Dict[str, Color] = {"fg_color": NEUTRAL_FILL, "hover_color": NEUTRAL_FILL_HOVER, "text_color": TEXT}
# Outlined: transparent with a border — for secondary actions that sit next to a primary one
OUTLINE_BTN: Dict[str, object] = {
    "fg_color": "transparent",
    "hover_color": NEUTRAL_FILL,
    "text_color": TEXT,
    "border_color": BORDER,
    "border_width": 1,
}
# Destructive: muted red text on a transparent button; fills red only on hover
DANGER_BTN: Dict[str, object] = {
    "fg_color": "transparent",
    "hover_color": ("#FEE2E2", "#450A0A"),  # red tint, so the red text stays readable
    "text_color": DANGER,
    "border_color": BORDER,
    "border_width": 1,
}
DANGER_SOLID_BTN: Dict[str, Color] = {
    "fg_color": DANGER_FILL,
    "hover_color": DANGER_FILL_HOVER,
    "text_color": "#FFFFFF",
}
WARNING_BTN: Dict[str, Color] = {"fg_color": ("#D97706", "#B45309"), "hover_color": ("#B45309", "#92400E")}

# --- Typography (Segoe UI ships with Windows; Tk falls back to the default sans elsewhere) ---
FONT_FAMILY = "Segoe UI"
MONO_FAMILY = "Consolas"
SIZE_TITLE = 18
SIZE_SECTION = 14
SIZE_BODY = 12
SIZE_CAPTION = 11


def font(size: int = SIZE_BODY, weight: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(family=FONT_FAMILY, size=size, weight=weight)


def title_font() -> ctk.CTkFont:
    return font(SIZE_TITLE, "bold")


def section_font() -> ctk.CTkFont:
    return font(SIZE_SECTION, "bold")


def caption_font() -> ctk.CTkFont:
    return font(SIZE_CAPTION)


MONO_FONT = (MONO_FAMILY, 10)

# --- Spacing (4/8/12/16 grid) and shape ---
SPACE_XS = 4
SPACE_S = 8
SPACE_M = 12
SPACE_L = 16
RADIUS = 8
RADIUS_SMALL = 6
BUTTON_HEIGHT = 32


def resolve(color: Color) -> str:
    """Pick the light or dark value for plain Tk widgets, which can't take (light, dark) tuples."""
    if isinstance(color, str):
        return color
    return color[1] if ctk.get_appearance_mode() == "Dark" else color[0]
