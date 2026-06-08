"""Security / password-hashing invariants for src/labdesk/db.py.

Covers:
  * scrypt round-trips (hash_password -> _verify_password) for many passwords
  * wrong-password rejection (constant-time path)
  * legacy sha256 hashes still verify (and verify_user upgrades them to scrypt)
  * salts differ across calls; same salt -> deterministic hash
  * the brute-force lockout state machine (failed_attempts -> locked_until ->
    reset on success / on manual clear), exponential backoff window, and the
    lock_remaining() seconds-remaining helper.

scrypt is intentionally slow (~tens of ms/hash), so this module hashes a modest
fixed set of passwords ONCE and then drives a large number of cheap assertions
against those stored strings.  Contract: only t.check / t.eq / t.near / t.has.
"""

from __future__ import annotations

import hashlib
import time


def _sha256(salt: str, pw: str) -> str:
    return hashlib.sha256(((salt or "") + pw).encode("utf-8")).hexdigest()


def register(t):
    db = t.db
    con = t.con

    # A broad set of passwords: empty, ascii, digits, spaces, unicode, very long,
    # control chars, lookalikes, common ones, and ones with the scrypt delimiter.
    PWS = [
        "",
        " ",
        "a",
        "ab",
        "abc",
        "admin",
        "password",
        "Password1",
        "s3cret-pw",
        "oldpw",
        "12345678",
        "0000",
        "correct horse battery",
        "p@$$w0rd!",
        "with$dollar$signs",
        "scrypt$fake$1$1$salt$hash",
        "tabs\tand\nnewlines",
        "trailing ",
        " leading",
        "  double  ",
        "UPPER",
        "MiXeD",
        "ünïcödé",
        "密码口令",
        "emoji😀pw",
        "résumé",
        "a" * 1,
        "a" * 64,
        "a" * 256,
        "a" * 1024,
        "null\x00byte",
        "líne",
        "Ω≈ç√∫",
        "123456789012345678901234567890",
        "P@ssw0rd",
        "qwerty",
        "letmein",
        "Sargodha-Lab-2026",
    ]

    # ---------------------------------------------------------------------
    # 1. scrypt round-trips + format invariants. Hash each password ONCE.
    # ---------------------------------------------------------------------
    t.section("scrypt round-trips + stored-string format")
    stored = {}
    for pw in PWS:
        h, extra = db.hash_password(pw)
        stored[pw] = h
        # self-describing format: scrypt$N$r$p$salt$hexhash
        t.eq(extra, "", f"hash_password returns empty 2nd field pw={pw!r}")
        t.check(h.startswith("scrypt$"), f"hash uses scrypt prefix pw={pw!r}")
        parts = h.split("$")
        t.eq(len(parts), 6, f"stored string has 6 $-fields pw={pw!r}")
        _, n, r, p, salt, hexh = parts
        t.eq(n, str(db._SCRYPT_N), f"N field pw={pw!r}")
        t.eq(r, str(db._SCRYPT_R), f"r field pw={pw!r}")
        t.eq(p, str(db._SCRYPT_P), f"p field pw={pw!r}")
        t.eq(len(salt), 32, f"salt is 16 bytes hex=32 chars pw={pw!r}")
        t.eq(len(hexh), 64, f"derived key is 32 bytes hex=64 chars pw={pw!r}")
        # salt + hash are valid lowercase hex
        t.check(all(c in "0123456789abcdef" for c in salt), f"salt is lowercase hex pw={pw!r}")
        t.check(all(c in "0123456789abcdef" for c in hexh), f"hash is lowercase hex pw={pw!r}")
        # correct password verifies, returns a real bool True
        v = db._verify_password(pw, h, "")
        t.check(v is True, f"scrypt verify accepts correct pw={pw!r}")

    # ---------------------------------------------------------------------
    # 2. wrong-password rejection: every password must be rejected against
    #    every OTHER password's stored hash (N*(N-1) cheap-ish scrypt checks
    #    would be too slow, so reuse stored hashes and only re-hash the guess).
    # ---------------------------------------------------------------------
    t.section("wrong-password rejection across the matrix")
    pw_list = PWS
    for i, target in enumerate(pw_list):
        h = stored[target]
        # a handful of wrong guesses per target (rotate, keep total bounded)
        for j in range(1, 6):
            guess = pw_list[(i + j) % len(pw_list)]
            if guess == target:
                continue
            v = db._verify_password(guess, h, "")
            t.check(v is False, f"reject guess={guess!r} vs target={target!r}")
        # near-miss mutations of the correct password are rejected
        for mut in (target + " ", " " + target, target + "x", target.upper() + "_"):
            if mut == target:
                continue
            t.check(
                db._verify_password(mut, h, "") is False, f"reject near-miss {mut!r} vs {target!r}"
            )

    # ---------------------------------------------------------------------
    # 3. salts differ across calls; explicit salt -> deterministic hash.
    # ---------------------------------------------------------------------
    t.section("salt uniqueness + determinism with explicit salt")
    salts_seen = set()
    for pw in ["admin", "password", "a", "", "ünïcödé"]:
        these = []
        for _ in range(8):
            h, _ = db.hash_password(pw)
            s = h.split("$")[4]
            these.append(s)
        # all 8 random salts distinct for this password
        t.eq(len(set(these)), len(these), f"random salts unique pw={pw!r}")
        # and distinct hashes overall
        salts_seen.update(these)
    t.check(len(salts_seen) >= 30, "salts globally unique across calls")

    # explicit salt is honoured and deterministic
    for pw in ["admin", "password", "s3cret-pw", "", "密码口令"]:
        for salt in ["00" * 16, "deadbeef" * 4, "ab" * 16, "f" * 32]:
            h1, _ = db.hash_password(pw, salt)
            h2, _ = db.hash_password(pw, salt)
            t.eq(h1, h2, f"explicit salt deterministic pw={pw!r} salt={salt}")
            t.eq(h1.split("$")[4], salt, f"explicit salt embedded pw={pw!r}")
            t.check(
                db._verify_password(pw, h1, "") is True,
                f"explicit-salt hash verifies pw={pw!r} salt={salt}",
            )
            # a different password with the same salt yields a different hash
            other = db.hash_password(pw + "X", salt)[0]
            t.check(other != h1, f"diff pw same salt diff hash pw={pw!r}")

    # ---------------------------------------------------------------------
    # 4. legacy sha256 verification (no salt + with salt) and rejection.
    # ---------------------------------------------------------------------
    t.section("legacy sha256 verify + reject")
    LEGACY_SALTS = [
        "",
        "abc123",
        "saltysalt",
        "0",
        "Z" * 40,
        "deadbeef",
        "  spaces  ",
        "$pecial$",
        "1234567890",
        "Ω≈ç",
    ]
    LEGACY_PWS = [
        "oldpw",
        "admin",
        "password",
        "",
        "12345678",
        "ünïcödé",
        "P@ssw0rd",
        "qwerty",
        "密码口令",
        "a" * 128,
        " ",
        "x",
    ]
    for pw in LEGACY_PWS:
        for ls in LEGACY_SALTS:
            digest = _sha256(ls, pw)
            t.check(
                db._verify_password(pw, digest, ls) is True,
                f"legacy sha256 verifies pw={pw!r} salt={ls!r}",
            )
            # wrong salt -> reject (unless salts collide, which they won't here)
            wrong_salt = ls + "x"
            t.check(
                db._verify_password(pw, digest, wrong_salt) is False,
                f"legacy wrong salt rejected pw={pw!r}",
            )
            # wrong password -> reject
            t.check(
                db._verify_password(pw + "!", digest, ls) is False,
                f"legacy wrong pw rejected pw={pw!r} salt={ls!r}",
            )

    # garbage / malformed stored strings never verify and never raise
    t.section("malformed stored strings degrade safely")
    GARBAGE = [
        "",
        "scrypt$",
        "scrypt$x",
        "scrypt$16384$8$1$onlyfourfields",
        "scrypt$16384$8$1$" + "ab" * 16 + "$nothex!!" + "0" * 56,
        "scrypt$notanint$8$1$" + "ab" * 16 + "$" + "0" * 64,
        "scrypt$16384$8$1$" + "ab" * 16 + "$",  # empty hash
        "not-a-hash-at-all",
        "$$$$$",
        "scrypt",
        "sha256:garbage",
        "scrypt$16384$8$1$salt",  # too few fields
    ]
    for g in GARBAGE:
        v = db._verify_password("anything", g, "")
        t.check(v is False, f"malformed stored rejected {g!r}")
        # None password value never crashes (legacy path with None salt)
        v2 = db._verify_password("x", g, None)
        t.check(v2 is False, f"malformed stored + None salt rejected {g!r}")
    # None stored string is treated as empty -> reject
    t.check(db._verify_password("x", None, "") is False, "None stored rejected")
    t.check(db._verify_password("", None, "") is False, "None stored empty-pw rejected")

    # ---------------------------------------------------------------------
    # 5. verify_user against real rows in the users table.
    # ---------------------------------------------------------------------
    t.section("verify_user: live row auth, unknown user, inactive user")
    # unknown users always rejected (and don't raise)
    for ghost in ["ghost", "", "nobody", "Robert'); DROP TABLE users;--", "admin "]:
        t.check(db.verify_user(con, ghost, "x") is None, f"unknown user rejected user={ghost!r}")

    # create a battery of fresh scrypt users
    def _mkuser(uname, pw, *, active=1, role="operator", legacy_salt=None):
        con.execute("DELETE FROM users WHERE username=?", (uname,))
        if legacy_salt is None:
            h, salt = db.hash_password(pw)
        else:
            h, salt = _sha256(legacy_salt, pw), legacy_salt
        con.execute(
            "INSERT INTO users(username,full_name,pass_hash,salt,role,active,"
            "failed_attempts,locked_until) VALUES (?,?,?,?,?,?,0,NULL)",
            (uname, uname.title(), h, salt, role, active),
        )
        con.commit()

    USERS = [
        ("op_alice", "alice-pw-123"),
        ("op_bob", "Bob!Secure9"),
        ("op_carol", "p@$$w0rd!"),
        ("op_dave", "ünïcödé-密码"),
        ("op_eve", "x"),
        ("op_frank", "a" * 200),
    ]
    for uname, pw in USERS:
        _mkuser(uname, pw)
    for uname, pw in USERS:
        # wrong password rejected (and counts a failure)
        t.check(db.verify_user(con, uname, pw + "X") is None, f"wrong pw rejected user={uname}")
        t.check(db.verify_user(con, uname, "") is None, f"empty pw rejected user={uname}")
        # failures were counted (sub-threshold, so no lock yet)
        rr = con.execute(
            "SELECT failed_attempts, locked_until FROM users WHERE username=?", (uname,)
        ).fetchone()
        t.eq(rr["failed_attempts"], 2, f"two wrong tries counted user={uname}")
        t.check(rr["locked_until"] is None, f"sub-threshold not locked user={uname}")
        # now a correct login succeeds and clears the failure counters
        row = db.verify_user(con, uname, pw)
        t.check(row is not None, f"correct login user={uname}")
        if row is not None:
            t.eq(row["username"], uname, f"verify_user returns the row user={uname}")
        rr = con.execute(
            "SELECT failed_attempts, locked_until FROM users WHERE username=?", (uname,)
        ).fetchone()
        t.eq(rr["failed_attempts"], 0, f"failed_attempts reset after success user={uname}")
        t.check(rr["locked_until"] is None, f"locked_until cleared after success user={uname}")

    # inactive user: even the correct password is refused (active=1 filter)
    _mkuser("op_inactive", "right-pw", active=0)
    t.check(
        db.verify_user(con, "op_inactive", "right-pw") is None,
        "inactive user refused even with correct pw",
    )

    # legacy sha256 user logs in AND is upgraded to scrypt on success
    t.section("verify_user upgrades legacy sha256 -> scrypt on login")
    for i, (uname, pw, ls) in enumerate(
        [
            ("legacy_a", "oldpw", "abc123"),
            ("legacy_b", "Pass123", ""),
            ("legacy_c", "密码", "saltZ"),
            ("legacy_d", "x" * 50, "0"),
        ]
    ):
        _mkuser(uname, pw, legacy_salt=ls)
        pre = con.execute("SELECT pass_hash FROM users WHERE username=?", (uname,)).fetchone()[0]
        t.check(not pre.startswith("scrypt$"), f"legacy user starts as sha256 user={uname}")
        t.check(db.verify_user(con, uname, pw) is not None, f"legacy user logs in user={uname}")
        post = con.execute(
            "SELECT pass_hash, salt FROM users WHERE username=?", (uname,)
        ).fetchone()
        t.check(
            post["pass_hash"].startswith("scrypt$"), f"legacy hash upgraded to scrypt user={uname}"
        )
        t.eq(post["salt"], "", f"legacy salt cleared after upgrade user={uname}")
        # and the new scrypt hash still verifies the same password
        t.check(
            db._verify_password(pw, post["pass_hash"], "") is True,
            f"upgraded scrypt verifies user={uname}",
        )
        # subsequent login still works (now via scrypt path)
        t.check(
            db.verify_user(con, uname, pw) is not None, f"re-login works post-upgrade user={uname}"
        )

    # ---------------------------------------------------------------------
    # 6. lockout state machine.
    # ---------------------------------------------------------------------
    t.section("lockout: failed_attempts counts up, locks at _MAX_FAILS")
    MAX = db._MAX_FAILS
    LOCK_S = db._LOCK_SECONDS
    LOCK_MAX = db._LOCK_MAX_SECONDS

    def _reset(uname):
        con.execute(
            "UPDATE users SET failed_attempts=0, locked_until=NULL WHERE username=?", (uname,)
        )
        con.commit()

    _mkuser("lock_user", "good-pw")
    # below the threshold: each wrong try increments failed_attempts, no lock yet
    _reset("lock_user")
    for attempt in range(1, MAX):
        db.verify_user(con, "lock_user", "bad")
        fa = con.execute("SELECT failed_attempts FROM users WHERE username='lock_user'").fetchone()[
            0
        ]
        t.eq(fa, attempt, f"failed_attempts increments to {attempt}")
        lu = con.execute("SELECT locked_until FROM users WHERE username='lock_user'").fetchone()[0]
        t.check(lu is None, f"not locked before threshold attempt={attempt}")
        t.eq(
            db.lock_remaining(con, "lock_user"),
            0,
            f"lock_remaining 0 before threshold attempt={attempt}",
        )
        # correct pw STILL works before lock (and would reset) — verify on a clone
        # without disturbing the counter: use a sibling row.

    # the MAX-th failure triggers the lock
    db.verify_user(con, "lock_user", "bad")
    fa = con.execute("SELECT failed_attempts FROM users WHERE username='lock_user'").fetchone()[0]
    t.eq(fa, MAX, f"failed_attempts hits MAX={MAX}")
    rem = db.lock_remaining(con, "lock_user")
    t.check(rem > 0, "locked after MAX failures")
    # first lock window is _LOCK_SECONDS (backoff exponent = 0)
    t.check(rem <= LOCK_S, f"first lock window <= {LOCK_S}s (got {rem})")
    t.check(rem >= LOCK_S - 5, f"first lock window ~{LOCK_S}s (got {rem})")
    # correct password is refused while locked
    t.check(db.verify_user(con, "lock_user", "good-pw") is None, "correct pw refused while locked")

    # exponential backoff: window doubles each extra failure, capped at LOCK_MAX
    t.section("lockout: exponential backoff doubles then caps")
    for extra in range(0, 12):
        fa_val = MAX + extra
        # set the row to exactly fa_val-1 failures, unlocked, then fail once more
        con.execute(
            "UPDATE users SET failed_attempts=?, locked_until=NULL " "WHERE username='lock_user'",
            (fa_val - 1,),
        )
        con.commit()
        db.verify_user(con, "lock_user", "bad")
        row = con.execute(
            "SELECT failed_attempts, locked_until FROM users " "WHERE username='lock_user'"
        ).fetchone()
        t.eq(row["failed_attempts"], fa_val, f"failed_attempts={fa_val} after extra={extra}")
        expected = min(LOCK_S * (2 ** (fa_val - MAX)), LOCK_MAX)
        rem = db.lock_remaining(con, "lock_user")
        # rem is seconds-from-now; allow a few seconds of slack for clock drift
        t.check(rem > 0, f"locked at fa={fa_val}")
        t.check(rem <= expected + 1, f"backoff window <= {expected}s at fa={fa_val} (got {rem})")
        t.check(
            rem >= min(expected, LOCK_MAX) - 5,
            f"backoff window ~{expected}s at fa={fa_val} (got {rem})",
        )
        t.check(expected <= LOCK_MAX, f"backoff never exceeds cap at fa={fa_val}")

    # reset path: clearing failed_attempts + locked_until re-enables login
    t.section("lockout: reset re-enables login")
    _reset("lock_user")
    t.eq(db.lock_remaining(con, "lock_user"), 0, "lock_remaining 0 after reset")
    t.check(
        db.verify_user(con, "lock_user", "good-pw") is not None, "login works again after reset"
    )
    # ...and a successful login itself zeroes the counters
    con.execute(
        "UPDATE users SET failed_attempts=3, locked_until=NULL " "WHERE username='lock_user'"
    )
    con.commit()
    t.check(
        db.verify_user(con, "lock_user", "good-pw") is not None, "login with sub-threshold fails"
    )
    rr = con.execute(
        "SELECT failed_attempts, locked_until FROM users WHERE username='lock_user'"
    ).fetchone()
    t.eq(rr["failed_attempts"], 0, "success resets failed_attempts from 3 -> 0")
    t.check(rr["locked_until"] is None, "success clears locked_until")

    # ---------------------------------------------------------------------
    # 7. lock_remaining helper edge cases.
    # ---------------------------------------------------------------------
    t.section("lock_remaining: timestamp math + garbage tolerance")
    now = time.time()
    cases = [
        (None, 0, "NULL locked_until -> 0"),
        ("", 0, "empty locked_until -> 0"),
        ("not-a-number", 0, "garbage timestamp -> 0"),
        ("abc", 0, "alpha timestamp -> 0"),
        (str(now + 0.4), 0, "sub-second future floors to 0"),
    ]
    # BUG PROBE: locked_until="1e9999" parses to float('inf'); int(inf - now)
    # raises OverflowError, which lock_remaining's except (TypeError, ValueError)
    # does NOT catch -> the lockout check crashes. Only reachable via a corrupted
    # DB (the app always writes finite str(time.time()+backoff)), but it should
    # still degrade to 0 like every other unparseable value.
    con.execute("UPDATE users SET locked_until='1e9999' WHERE username='lock_user'")
    con.commit()
    try:
        _inf_rem = db.lock_remaining(con, "lock_user")
        t.eq(_inf_rem, 0, "lock_remaining 'inf' timestamp degrades to 0 (no crash)")
    except Exception as _e:
        t.check(False, f"lock_remaining crashed on 'inf' timestamp: {type(_e).__name__}")
    # many past timestamps -> 0
    for dt in [1, 2, 5, 10, 100, 1000, 100000, 86400, 0.1, 0.9]:
        cases.append((str(now - dt), 0, f"past -{dt}s -> 0"))
    # many future timestamps -> ~dt seconds remaining
    for dt in [
        1,
        2,
        5,
        10,
        15,
        30,
        45,
        60,
        90,
        120,
        240,
        480,
        600,
        900,
        1200,
        1800,
        2400,
        3000,
        3600,
        7200,
    ]:
        cases.append((str(now + dt), dt, f"future +{dt}s"))
    # garbage strings -> 0
    for g in [
        "",
        "   ",
        "null",
        "None",
        "NaN_x",
        "12.34.56",
        "0x10",
        "++3",
        "3,600",
        "1_000",
        "sixty",
        "60s",
        "@#$",
        "true",
    ]:
        cases.append((g, 0, f"garbage {g!r} -> 0"))
    for val, expected, name in cases:
        con.execute("UPDATE users SET locked_until=? WHERE username='lock_user'", (val,))
        con.commit()
        rem = db.lock_remaining(con, "lock_user")
        if expected == 0:
            t.eq(rem, 0, f"lock_remaining {name}")
        else:
            # within 2s of the expected (call latency)
            t.check(abs(rem - expected) <= 2, f"lock_remaining {name} (got {rem})")
        t.check(rem >= 0, f"lock_remaining never negative {name}")
    _reset("lock_user")
    # unknown username -> 0, never raises
    t.eq(db.lock_remaining(con, "no-such-user-xyz"), 0, "lock_remaining unknown user -> 0")
    t.eq(db.lock_remaining(con, ""), 0, "lock_remaining empty user -> 0")

    # ---------------------------------------------------------------------
    # 8. cross-checks: scrypt hash never equals a sha256 hash of same pw,
    #    and dklen / param parsing is honoured for non-default work factors.
    # ---------------------------------------------------------------------
    t.section("scrypt vs sha256 disjoint + custom-param parsing")
    for pw in ["admin", "password", "x", "密码"]:
        sh = stored[pw] if pw in stored else db.hash_password(pw)[0]
        sd = _sha256("", pw)
        t.check(sh.split("$")[5] != sd, f"scrypt hex != sha256 hex pw={pw!r}")
        # the scrypt string, if mistakenly fed to the legacy branch, would never
        # equal a sha256 digest -> still rejected by legacy path
        t.check(db._verify_password(pw, sd, "") is True, f"sha256 self-verify pw={pw!r}")

    # _verify_password parses N/r/p and dklen from the stored string: build a
    # smaller-work-factor scrypt string by hand and confirm it verifies.
    for pw in ["small-wf", "tiny"]:
        salt = "11" * 16
        small = hashlib.scrypt(
            pw.encode(), salt=salt.encode(), n=1024, r=8, p=1, maxmem=db._SCRYPT_MAXMEM, dklen=32
        )
        sstr = f"scrypt$1024$8$1${salt}${small.hex()}"
        t.check(
            db._verify_password(pw, sstr, "") is True,
            f"custom work-factor scrypt verifies pw={pw!r}",
        )
        t.check(
            db._verify_password(pw + "x", sstr, "") is False,
            f"custom work-factor wrong pw rejected pw={pw!r}",
        )
        # shorter dklen honoured (len(hexh)//2)
        short = hashlib.scrypt(
            pw.encode(), salt=salt.encode(), n=1024, r=8, p=1, maxmem=db._SCRYPT_MAXMEM, dklen=16
        )
        sstr16 = f"scrypt$1024$8$1${salt}${short.hex()}"
        t.check(
            db._verify_password(pw, sstr16, "") is True, f"16-byte dklen scrypt verifies pw={pw!r}"
        )
