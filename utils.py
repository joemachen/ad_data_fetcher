"""
Shared utility functions for Ads Report Fetcher.
"""


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
