"""Authentication + brute-force lockout (audit testing gap)."""

from __future__ import annotations

import time


def _make_user(db, con, username="bob", password="s3cret-pass", role="receptionist"):
    h, salt = db.hash_password(password)
    con.execute(
        "INSERT INTO users(username, full_name, pass_hash, salt, role, active, "
        "must_change_password) VALUES (?,?,?,?,?,1,0)",
        (username, username.title(), h, salt, role),
    )
    con.commit()


def test_correct_password_authenticates(db, con):
    _make_user(db, con)
    assert db.verify_user(con, "bob", "s3cret-pass") is not None


def test_wrong_password_rejected(db, con):
    _make_user(db, con)
    assert db.verify_user(con, "bob", "nope") is None


def test_unknown_user_rejected_without_error(db, con):
    # the timing-equaliser path must run without raising
    assert db.verify_user(con, "ghost", "whatever") is None


def test_lockout_after_max_fails(db, con):
    _make_user(db, con)
    for _ in range(db._MAX_FAILS):
        assert db.verify_user(con, "bob", "wrong") is None
    # now locked: even the CORRECT password is refused while the window is open
    assert db.lock_remaining(con, "bob") > 0
    assert db.verify_user(con, "bob", "s3cret-pass") is None


def test_successful_login_resets_failure_counter(db, con):
    _make_user(db, con)
    for _ in range(db._MAX_FAILS - 1):  # one short of lockout
        db.verify_user(con, "bob", "wrong")
    assert db.verify_user(con, "bob", "s3cret-pass") is not None
    row = con.execute(
        "SELECT failed_attempts, locked_until FROM users WHERE username='bob'"
    ).fetchone()
    assert row["failed_attempts"] == 0
    assert row["locked_until"] is None


def test_legacy_sha256_hash_is_upgraded_to_scrypt(db, con):
    import hashlib

    legacy = hashlib.sha256(("salty" + "old-pass").encode()).hexdigest()
    con.execute(
        "INSERT INTO users(username, full_name, pass_hash, salt, role, active) "
        "VALUES ('legacy','Legacy',?,?,'admin',1)",
        (legacy, "salty"),
    )
    con.commit()
    assert db.verify_user(con, "legacy", "old-pass") is not None
    stored = con.execute(
        "SELECT pass_hash FROM users WHERE username='legacy'"
    ).fetchone()[0]
    assert stored.startswith("scrypt$"), "legacy hash should be transparently upgraded"


def test_lock_remaining_handles_corrupt_timestamp(db, con):
    _make_user(db, con)
    con.execute("UPDATE users SET locked_until='not-a-number' WHERE username='bob'")
    con.commit()
    assert db.lock_remaining(con, "bob") == 0  # must not raise on garbage data


def test_correct_password_clears_lock_after_window(db, con):
    """Once the countdown has elapsed, the correct password signs in and resets."""

    _make_user(db, con)
    for _ in range(db._MAX_FAILS):
        db.verify_user(con, "bob", "wrong")
    # fast-forward past the window by back-dating locked_until
    con.execute(
        "UPDATE users SET locked_until=? WHERE username='bob'", (str(time.time() - 1),)
    )
    con.commit()
    assert db.lock_remaining(con, "bob") == 0
    assert db.verify_user(con, "bob", "s3cret-pass") is not None
    row = con.execute(
        "SELECT failed_attempts, locked_until FROM users WHERE username='bob'"
    ).fetchone()
    assert row["failed_attempts"] == 0 and row["locked_until"] is None


def test_far_future_lock_is_self_healing(db, con):
    """A locked_until written under a wrong/ahead clock (days in the future) must
    NOT trap the account: it is ignored so the correct password gets through. A
    real lock is never more than _LOCK_MAX_SECONDS ahead."""

    _make_user(db, con)
    con.execute(
        "UPDATE users SET locked_until=?, failed_attempts=5 WHERE username='bob'",
        (str(time.time() + 30 * 86400),),  # 30 days ahead
    )
    con.commit()
    assert db.lock_remaining(con, "bob") == 0  # implausible -> treated as unlocked
    assert db.verify_user(con, "bob", "s3cret-pass") is not None  # not trapped


def test_real_lock_within_window_still_honoured(db, con):
    """A plausible (<= max) future lock is still enforced — the fix only ignores
    the implausibly-far values, not legitimate lockouts."""

    _make_user(db, con)
    con.execute(
        "UPDATE users SET locked_until=? WHERE username='bob'",
        (str(time.time() + db._LOCK_SECONDS), ),
    )
    con.commit()
    assert db.lock_remaining(con, "bob") > 0
    assert db.verify_user(con, "bob", "s3cret-pass") is None


def test_clear_lockouts_recovery(db, con):
    """`--unlock` recovery clears the lock without touching the password."""
    _make_user(db, con)
    for _ in range(db._MAX_FAILS):
        db.verify_user(con, "bob", "wrong")
    assert db.lock_remaining(con, "bob") > 0
    assert db.clear_lockouts(con, "bob") == 1
    assert db.lock_remaining(con, "bob") == 0
    assert db.verify_user(con, "bob", "s3cret-pass") is not None
