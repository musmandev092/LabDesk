"""Auto screen-fit scaling (QT_SCALE_FACTOR) for small displays."""

from __future__ import annotations

import pytest

from labdesk.app import _fit_scale


@pytest.mark.parametrize(
    "w,h,expected",
    [
        (1366, 740, 0.85),  # 1366x768 laptop minus the desktop bar — the reported case
        (1366, 768, 0.85),  # 768 / 860 = 0.893 -> 0.85 (confirmed good on that laptop)
        (1366, 731, 0.85),  # same laptop with a taller desktop bar -> still 0.85
        (1280, 720, 0.80),  # 720 / 860 = 0.837 -> 0.80
        (1280, 693, 0.80),  # 720p minus a taskbar
        (1024, 600, 0.70),  # tiny netbook — clamped at the 0.70 floor
        (800, 600, 0.70),  # very small — floor
    ],
)
def test_small_screens_get_scaled(w, h, expected):
    assert _fit_scale(w, h) == pytest.approx(expected)


@pytest.mark.parametrize(
    "w,h",
    [
        (1920, 1080),  # full HD
        (1920, 1053),  # full HD minus a bar
        (1600, 900),  # 900 / 820 > 1 and 1600 wide — fits
        (2560, 1440),  # QHD
        (3840, 2160),  # 4K (native)
        (1920, 1080),  # 4K @ 200% reports 1920x1080 logical — also fits
    ],
)
def test_large_screens_not_scaled(w, h):
    assert _fit_scale(w, h) is None


def test_degenerate_sizes_are_safe():
    assert _fit_scale(0, 0) is None
    assert _fit_scale(-1, 500) is None
