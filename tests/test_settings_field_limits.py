"""Settings text fields are length-capped (setMaxLength) so an over-long value — a
very long lab name especially — can't overflow the printed report/receipt header.
"""

from __future__ import annotations

import pytest

from labdesk.presentation.settings import SettingsPage
from labdesk.presentation.settings_fields import MAX_LENGTHS

_ADMIN = {"id": 1, "username": "adam", "role": "admin"}


def _page(con, qtbot):
    page = SettingsPage(con, _ADMIN)
    qtbot.addWidget(page)
    return page


def test_lab_name_is_capped_at_35(con, qtbot):
    page = _page(con, qtbot)
    assert page.inputs["lab_name"].maxLength() == 35


@pytest.mark.parametrize("key,maxlen", list(MAX_LENGTHS.items()))
def test_each_capped_field_enforces_its_limit(con, qtbot, key, maxlen):
    page = _page(con, qtbot)
    le = page.inputs.get(key)
    if le is None:
        pytest.skip(f"{key} is not shown on the settings page")
    assert le.maxLength() == maxlen
    # the cap actually truncates input
    le.setText("X" * (maxlen + 20))
    assert len(le.text()) == maxlen
