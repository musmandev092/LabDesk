"""Optional "remember the database password" via the freedesktop Secret Service
(KDE Wallet / GNOME Keyring), talked to directly with jeepney (pure-Python D-Bus).
Every call is guarded/bounded — no bus/wallet/locked just degrades to "unavailable".

Threat model: the saved key is protected by the OS login session + wallet; it
defends a copied DB file and other OS accounts, not someone in the same session."""

from __future__ import annotations

import contextlib

from .paths import db_path

_ATTR_APP = "LabDesk"
_TIMEOUT = 5  # seconds — never let a stuck wallet hang startup


def _attrs() -> dict[str, str]:
    # tie the secret to THIS database file so different installs/data dirs don't clash
    return {"application": _ATTR_APP, "account": str(db_path())}


def _label() -> str:
    return "LabDesk database password"


def _conn():
    """Open a blocking D-Bus session connection, or None if there's no session bus."""
    try:
        from jeepney.io.blocking import open_dbus_connection

        return open_dbus_connection(bus="SESSION")
    except Exception:
        return None


def _open_session(conn):
    """OpenSession('plain') → the session object path used to carry secrets."""
    from jeepney import DBusAddress, new_method_call

    svc = DBusAddress(
        "/org/freedesktop/secrets",
        bus_name="org.freedesktop.secrets",
        interface="org.freedesktop.Secret.Service",
    )
    reply = conn.send_and_get_reply(
        new_method_call(svc, "OpenSession", "sv", ("plain", ("s", ""))),
        timeout=_TIMEOUT,
    )
    return reply.body[1]  # (output_variant, session_object_path)


def available() -> bool:
    """True if a Secret Service is reachable on the session bus (KWallet/GNOME)."""
    conn = _conn()
    if conn is None:
        return False
    try:
        _open_session(conn)
        return True
    except Exception:
        return False
    finally:
        with contextlib.suppress(Exception):
            conn.close()


def store_key(passphrase: str) -> bool:
    """Save the DB passphrase in the wallet (replacing any previous one). Best-effort."""
    conn = _conn()
    if conn is None:
        return False
    try:
        from jeepney import DBusAddress, new_method_call

        session = _open_session(conn)
        coll = DBusAddress(
            "/org/freedesktop/secrets/aliases/default",
            bus_name="org.freedesktop.secrets",
            interface="org.freedesktop.Secret.Collection",
        )
        secret = (session, b"", passphrase.encode("utf-8"), "text/plain")
        props = {
            "org.freedesktop.Secret.Item.Label": ("s", _label()),
            "org.freedesktop.Secret.Item.Attributes": ("a{ss}", _attrs()),
        }
        conn.send_and_get_reply(
            new_method_call(
                coll, "CreateItem", "a{sv}(oayays)b", (props, secret, True)
            ),
            timeout=_TIMEOUT,
        )
        return True
    except Exception:
        return False
    finally:
        with contextlib.suppress(Exception):
            conn.close()


def load_key() -> str | None:
    """Return the saved DB passphrase, or None if none/unavailable/locked."""
    conn = _conn()
    if conn is None:
        return None
    try:
        from jeepney import DBusAddress, new_method_call

        session = _open_session(conn)
        svc = DBusAddress(
            "/org/freedesktop/secrets",
            bus_name="org.freedesktop.secrets",
            interface="org.freedesktop.Secret.Service",
        )
        found = conn.send_and_get_reply(
            new_method_call(svc, "SearchItems", "a{ss}", (_attrs(),)), timeout=_TIMEOUT
        )
        unlocked = found.body[0]  # SearchItems → (unlocked[], locked[])
        if not unlocked:
            return None
        item = unlocked[0]
        item_addr = DBusAddress(
            item,
            bus_name="org.freedesktop.secrets",
            interface="org.freedesktop.Secret.Item",
        )
        got = conn.send_and_get_reply(
            new_method_call(item_addr, "GetSecret", "o", (session,)), timeout=_TIMEOUT
        )
        # secret struct: (session_path, parameters_bytes, value_bytes, content_type)
        value = bytes(got.body[0][2])
        return value.decode("utf-8") or None
    except Exception:
        return None
    finally:
        with contextlib.suppress(Exception):
            conn.close()


def clear_key() -> bool:
    """Forget the saved DB passphrase. Best-effort; True if nothing remains."""
    conn = _conn()
    if conn is None:
        return False
    try:
        from jeepney import DBusAddress, new_method_call

        svc = DBusAddress(
            "/org/freedesktop/secrets",
            bus_name="org.freedesktop.secrets",
            interface="org.freedesktop.Secret.Service",
        )
        found = conn.send_and_get_reply(
            new_method_call(svc, "SearchItems", "a{ss}", (_attrs(),)), timeout=_TIMEOUT
        )
        items = list(found.body[0]) + list(found.body[1])
        for item in items:
            item_addr = DBusAddress(
                item,
                bus_name="org.freedesktop.secrets",
                interface="org.freedesktop.Secret.Item",
            )
            with contextlib.suppress(Exception):
                conn.send_and_get_reply(
                    new_method_call(item_addr, "Delete", "", ()), timeout=_TIMEOUT
                )
        return True
    except Exception:
        return False
    finally:
        with contextlib.suppress(Exception):
            conn.close()
