"""Authorization policy + the require() choke point (audit High H-1)."""

from __future__ import annotations

import pytest

from labdesk import roles


def test_level_hierarchy():
    assert (
        roles.level("admin") > roles.level("technician") > roles.level("receptionist")
    )
    assert roles.level("nonexistent") == 0


def test_can_capabilities():
    assert roles.can("admin", "manage_users") is True
    assert roles.can("receptionist", "manage_users") is False
    assert roles.can("receptionist", "receive_payment") is True
    assert roles.can("technician", "void_receipt") is False  # void needs level 4
    assert roles.can("admin", "void_receipt") is True


def test_unknown_capability_denied_by_default():
    assert roles.can("admin", "totally-made-up") is False


def test_require_raises_for_insufficient_role():
    with pytest.raises(PermissionError):
        roles.require("receptionist", "manage_users")


def test_require_passes_for_sufficient_role():
    roles.require("admin", "edit_settings")  # must not raise
