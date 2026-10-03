"""Tests for date_entry.point_in_rect (decides whether a focus loss came from a click inside the drop-down)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from date_entry import point_in_rect

RECT = (100, 200, 280, 220)  # left, top, width, height of the drop-down


@pytest.mark.parametrize("point", [(100, 200), (240, 310), (380, 420), (105, 205)])
def test_points_inside_including_edges(point):
    assert point_in_rect(point, RECT)


@pytest.mark.parametrize("point", [(99, 250), (381, 250), (200, 199), (200, 421), (0, 0)])
def test_points_outside(point):
    assert not point_in_rect(point, RECT)
