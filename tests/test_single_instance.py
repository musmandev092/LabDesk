"""Single-instance lock + activation socket: a second launch is refused and can
ping the running primary to raise its window (replaces the old silent exit)."""

from __future__ import annotations

import pytest


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    return tmp_path


def test_no_instance_ping_fails(runtime):
    from labdesk import app

    assert app._ping_running_instance() is False  # nothing listening yet


def test_primary_acquires_second_is_refused_and_can_ping(runtime):
    from labdesk import app

    lock, srv = app._acquire_single_instance()
    assert lock is not None and srv is not None
    try:
        # a second acquire in the same user/runtime is refused (flock held)
        lock2, srv2 = app._acquire_single_instance()
        assert lock2 is None and srv2 is None
        # a second launch can reach the listening primary to ask it to raise
        assert app._ping_running_instance() is True
    finally:
        srv.close()
        lock.close()


def test_lock_releases_after_close(runtime):
    from labdesk import app

    lock, srv = app._acquire_single_instance()
    srv.close()
    lock.close()  # releases the flock
    # a fresh acquire now succeeds (primary slot is free again)
    lock2, srv2 = app._acquire_single_instance()
    try:
        assert lock2 is not None
    finally:
        if srv2:
            srv2.close()
        lock2.close()
