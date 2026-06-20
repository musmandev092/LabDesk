"""GUI tests that drive the REAL Qt pages through pytest-qt (`qtbot`).

These complement the headless self-test by constructing every presentation page
the way the running app does — same widget tree, same signal wiring — and by
driving the reception save path far enough to prove the service's authorization
gate denies an under-privileged role even when the widgets are fully populated.

Runs under the offscreen Qt platform; a missing Qt plugin skips rather than fails.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from labdesk import render, roles
from labdesk.presentation.accounts import AccountsPage
from labdesk.presentation.catalog import CatalogPage
from labdesk.presentation.dashboard import DashboardPage
from labdesk.presentation.receipts import ReceiptsPage
from labdesk.presentation.reception import ReceptionPage
from labdesk.presentation.worklist import WorklistPage

# admin user (level 5): can construct + drive every page
ADMIN = {"id": 1, "username": "adam", "role": "admin"}
# a role that isn't in roles.ROLES at all -> level 0, lacks every capability
NOBODY = {"id": 99, "username": "nobody", "role": "ghost"}

# (label, page class) for the parametrized smoke tests
PAGES = [
    ("dashboard", DashboardPage),
    ("reception", ReceptionPage),
    ("worklist", WorklistPage),
    ("receipts", ReceiptsPage),
    ("catalog", CatalogPage),
    ("accounts", AccountsPage),
]


@pytest.fixture(autouse=True)
def _preload_fonts(qtbot):
    """`qtbot` already created the QApplication; load render fonts once on the GUI
    thread (the pages build text the same way the app does). Skip if Qt can't init."""
    try:
        render.preload()
    except Exception as e:  # pragma: no cover - environment without a Qt platform
        pytest.skip(f"Qt platform unavailable: {e}")


def _mint_test(con):
    """Insert one catalogue test and return its id."""
    tid = con.execute(
        "INSERT INTO tests(name, charges, category) VALUES (?,?,?)",
        ("CBC", 500.0, "Routine"),
    ).lastrowid
    con.commit()
    return tid


@pytest.mark.parametrize("label,cls", PAGES)
def test_page_constructs(qtbot, con, label, cls):
    """Every page builds through the real Qt path without raising."""
    page = cls(con, ADMIN)
    qtbot.addWidget(page)
    assert page is not None
    assert page.con is con


@pytest.mark.parametrize("label,cls", PAGES)
def test_page_on_show_or_refresh(qtbot, con, label, cls):
    """If a page exposes on_show()/refresh(), calling it must not raise on a
    fresh DB."""
    page = cls(con, ADMIN)
    qtbot.addWidget(page)
    called = False
    for method in ("on_show", "refresh"):
        fn = getattr(page, method, None)
        if callable(fn):
            fn()
            called = True
    assert called, f"{label}: expected an on_show()/refresh() to drive"


def test_reception_page_drives_to_save(qtbot, con):
    """Smoke the happy path: populate the reception widgets + cart as a user would
    and call save() — an admin is allowed, so a receipt row must appear."""
    test_id = _mint_test(con)

    page = ReceptionPage(con, ADMIN)
    qtbot.addWidget(page)
    page.name.setText("Driven Patient")
    page.age.setValue(40)
    page.cart.append({"test_id": test_id, "name": "CBC", "charge": 500.0})
    page.paid.setValue(500.0)

    before = con.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]
    page.save(do_print=False)
    after = con.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]
    assert after == before + 1, "an admin's driven save must create one receipt"


def test_reception_save_denied_for_unprivileged_role(qtbot, con):
    """The high-value driven test: a role lacking `create_receipt` (level < 2) is
    denied at the SERVICE boundary even with the widgets fully populated. save()
    catches the PermissionError and surfaces a toast — NO receipt is written."""
    assert not roles.can(NOBODY["role"], "create_receipt")
    test_id = _mint_test(con)

    page = ReceptionPage(con, NOBODY)
    qtbot.addWidget(page)
    page.name.setText("Denied Patient")
    page.age.setValue(33)
    page.cart.append({"test_id": test_id, "name": "CBC", "charge": 500.0})
    page.paid.setValue(500.0)

    before = con.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]
    page.save(do_print=False)  # must not raise — the page swallows PermissionError
    after = con.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]
    assert after == before, "an unprivileged role must NOT create a receipt"


def test_reception_save_requires_name(qtbot, con):
    """Validation gate: no patient name -> no service call -> no receipt."""
    test_id = _mint_test(con)

    page = ReceptionPage(con, ADMIN)
    qtbot.addWidget(page)
    page.cart.append({"test_id": test_id, "name": "CBC", "charge": 500.0})
    page.paid.setValue(500.0)

    before = con.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]
    page.save(do_print=False)
    after = con.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]
    assert after == before, "a blank patient name must abort before any write"


def test_reception_save_requires_cart(qtbot, con):
    """Validation gate: a named patient but an empty cart -> no receipt."""
    page = ReceptionPage(con, ADMIN)
    qtbot.addWidget(page)
    page.name.setText("No Tests Patient")

    before = con.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]
    page.save(do_print=False)
    after = con.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]
    assert after == before, "an empty cart must abort before any write"
