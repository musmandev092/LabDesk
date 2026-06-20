"""Wave 5 — keyvault degrades safely when no Secret Service is present.

db/keyvault.py stores the DB passphrase in the desktop wallet (KWallet/GNOME via
the Secret Service over D-Bus). The security-critical contract is that with NO
wallet reachable (headless/CI, or a locked session) it NEVER raises and NEVER
leaks — it just reports unavailable. These tests pin that fail-safe behavior; the
happy D-Bus path needs a live secret service and isn't exercised here.
"""

from __future__ import annotations

from labdesk.db import keyvault


def _raise(*_a, **_k):
    raise RuntimeError("no secret service")


def test_available_returns_bool_without_raising():
    assert isinstance(keyvault.available(), bool)


def test_label_and_attrs_are_well_formed():
    assert isinstance(keyvault._label(), str)
    attrs = keyvault._attrs()
    assert isinstance(attrs, dict)
    assert all(isinstance(k, str) and isinstance(v, str) for k, v in attrs.items())


def test_all_ops_degrade_when_no_bus(monkeypatch):
    # _conn() returns None when there's no session bus → every op fails safe.
    monkeypatch.setattr(keyvault, "_conn", lambda: None)
    assert keyvault.available() is False
    assert keyvault.store_key("secret") is False
    assert keyvault.load_key() is None
    assert keyvault.clear_key() is False


def test_available_false_when_session_cannot_open(monkeypatch):
    class _FakeConn:
        def close(self):
            pass

    monkeypatch.setattr(keyvault, "_conn", lambda: _FakeConn())
    monkeypatch.setattr(keyvault, "_open_session", _raise)
    assert keyvault.available() is False


def test_ops_fail_safe_when_session_cannot_open(monkeypatch):
    class _FakeConn:
        def close(self):
            pass

        def send_and_get_reply(self, *_a, **_k):
            raise RuntimeError("denied")

    monkeypatch.setattr(keyvault, "_conn", lambda: _FakeConn())
    monkeypatch.setattr(keyvault, "_open_session", _raise)
    assert keyvault.store_key("p") is False
    assert keyvault.load_key() is None
    assert keyvault.clear_key() is False
