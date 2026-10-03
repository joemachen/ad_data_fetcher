"""
DateEntry with a drop-down that doesn't close when you click its own month/year arrows.

tkcalendar 1.5's DateEntry hides the drop-down whenever the calendar loses keyboard focus, unless
some focus/grab state happens to be set at that instant. On Windows, clicking the ◂ ▸ month/year
buttons inside the pop-up sometimes lands in the "hide" branch, so the arrows randomly either
change the month or close the calendar. Here the pop-up only closes when the pointer is outside it.

Dates are also capped at today when the drop-down opens: ad platforms have no data for the future,
and a far-future start date was easy to hit with the old range.
"""

from datetime import date
from typing import Tuple

try:
    from tkcalendar import DateEntry as _TkDateEntry
except ImportError:  # tkcalendar is optional; main.py falls back to month/year dropdowns
    _TkDateEntry = None


def point_in_rect(point: Tuple[int, int], rect: Tuple[int, int, int, int]) -> bool:
    """True if (x, y) lies inside (left, top, width, height), edges included."""
    x, y = point
    left, top, width, height = rect
    return left <= x <= left + width and top <= y <= top + height


if _TkDateEntry is not None:

    class DateEntry(_TkDateEntry):
        def _pointer_over_dropdown(self) -> bool:
            top = self._top_cal
            if not top.winfo_ismapped():
                return False
            rect = (top.winfo_rootx(), top.winfo_rooty(), top.winfo_width(), top.winfo_height())
            return point_in_rect(top.winfo_pointerxy(), rect)

        def _on_focus_out_cal(self, event) -> None:
            # A click on the drop-down's own arrow buttons can move focus away from the calendar;
            # keep it open and take focus back so the next real outside click still closes it.
            if self._pointer_over_dropdown():
                self.after_idle(self._refocus_calendar)
                return
            super()._on_focus_out_cal(event)

        def _refocus_calendar(self) -> None:
            if self._top_cal.winfo_ismapped():
                self._calendar.focus_force()

        def drop_down(self) -> None:
            # Re-cap at today on every open, so a window left open overnight still allows today.
            if not self._calendar.winfo_ismapped():
                self._calendar.configure(maxdate=date.today())
            super().drop_down()

else:
    DateEntry = None  # type: ignore[assignment,misc]

__all__ = ["DateEntry", "point_in_rect"]
