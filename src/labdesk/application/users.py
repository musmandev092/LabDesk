"""User account mutations (no Qt).

Create / enable-disable / reset-password run through here so the privileged
``manage_users`` capability is enforced + audited at the data boundary, not only by
the settings widget's button state (defence-in-depth; see roles.require). The view
keeps the dialogs, validation, and showing the one-time reset credential.
"""

from __future__ import annotations

import secrets

from .. import db
from ..db import sqlite3
from ..roles import require, role_label


def create_user(
    con: sqlite3.Connection,
    *,
    username: str,
    full_name: str,
    password: str,
    role: str,
    actor_username: str,
    actor_role: str,
) -> None:
    """Create a staff account (must change password on first login) + audit. The
    caller validates the username/password and checks for duplicates first."""
    require(actor_role, "manage_users")
    h, salt = db.hash_password(password)
    con.execute(
        "INSERT INTO users(username,full_name,pass_hash,salt,role,must_change_password) "
        "VALUES (?,?,?,?,?,1)",
        (username, full_name, h, salt, role),
    )
    con.commit()
    db.log_audit(
        con, actor_username, "user_created", f"{username} ({role_label(role)})"
    )


def set_user_active(
    con: sqlite3.Connection, *, user_id: int, actor_username: str, actor_role: str
) -> bool:
    """Toggle a user's active flag + audit. Returns the new active state. The caller
    is responsible for refusing to disable one's own account."""
    require(actor_role, "manage_users")
    row = con.execute(
        "SELECT username, active FROM users WHERE id=?", (user_id,)
    ).fetchone()
    con.execute("UPDATE users SET active = 1 - active WHERE id=?", (user_id,))
    con.commit()
    now_active = 0 if (row and row["active"]) else 1
    db.log_audit(
        con,
        actor_username,
        "user_enabled" if now_active else "user_disabled",
        (row["username"] if row else str(user_id)),
    )
    return bool(now_active)


def reset_user_password(
    con: sqlite3.Connection, *, user_id: int, actor_username: str, actor_role: str
) -> tuple[str, str]:
    """Reset a user's password to a fresh single-use credential (forcing a change on
    next login and clearing any lockout) + audit. Returns ``(username, temp_password)``
    so the view can display the one-time credential."""
    require(actor_role, "manage_users")
    uname = con.execute("SELECT username FROM users WHERE id=?", (user_id,)).fetchone()[
        0
    ]
    temp = "Temp-" + secrets.token_hex(4)  # 32-bit single-use, e.g. Temp-9af3c1d2
    h, salt = db.hash_password(temp)
    con.execute(
        "UPDATE users SET pass_hash=?, salt=?, must_change_password=1, "
        "failed_attempts=0, locked_until=NULL WHERE id=?",
        (h, salt, user_id),
    )
    con.commit()
    db.log_audit(con, actor_username, "password_reset", uname)
    return uname, temp
