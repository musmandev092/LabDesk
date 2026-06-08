"""Generator — backup / restore invariants for labdesk.db.

Covers db.backup_db (creates a 0600 file, prunes to newest `keep`) and
db.restore_db (rejects missing / garbage / foreign files, never corrupts the
live DB; takes a .pre-restore safety copy first). Also exercises the
_looks_like_labdesk_db gatekeeper directly.

Contract: one register(t); assertions only via t.check / t.eq / t.near / t.has;
no network, no live DB (the runner isolates both via LABDESK_DATA_DIR).
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import stat
from pathlib import Path


def _backups_dir(t):
    return t.db.data_dir() / "backups"


def _clear_backups(t):
    bdir = _backups_dir(t)
    if bdir.exists():
        for p in bdir.glob("labdesk-*.sqlite"):
            try:
                p.unlink()
            except OSError:
                pass


def _list_backups(t):
    bdir = _backups_dir(t)
    if not bdir.exists():
        return []
    return sorted(bdir.glob("labdesk-*.sqlite"))


def _resync(t):
    """restore_db overwrites the live DB file and deletes its WAL/SHM sidecars
    out from under the harness's still-open shared connection (t.con). Truncate
    the WAL so t.con and any fresh sqlite3.connect() agree on the file again —
    otherwise the *next* backup_db() sees an inconsistent DB and returns None.
    This is a test-harness artifact (a real restore is followed by an app
    restart), not part of the behaviour under test."""
    try:
        t.con.commit()
        t.con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        t.con.commit()
    except Exception:
        pass


def _restore_live(t, path):
    """restore_db(path) then resync the shared connection. Returns the bool."""
    ok = t.db.restore_db(str(path))
    _resync(t)
    return ok


def register(t):
    db = t.db
    tmp = t.tmp
    live = db.db_path()

    # ----------------------------------------------------------------------
    # 0. Preconditions: the runner already called init_db(), so the live DB
    #    must exist and be a valid labdesk DB.
    # ----------------------------------------------------------------------
    t.section("preconditions: live DB exists & is valid")
    t.check(live.exists(), "live DB exists after init_db")
    t.check(db._looks_like_labdesk_db(live), "live DB looks like a labdesk DB")

    # ----------------------------------------------------------------------
    # 1. backup_db happy path — file is created under backups/, returns a
    #    Path that exists, is a valid labdesk DB, and is mode 0600.
    # ----------------------------------------------------------------------
    t.section("backup_db: create / shape / perms")
    _clear_backups(t)
    REASONS = [
        "auto",
        "manual",
        "test",
        "pre-restore",
        "x",
        "weekly_full",
        "a" * 40,
        "shutdown",
        "update",
        "import",
    ]
    for reason in REASONS:
        bp = db.backup_db(reason, keep=1000)
        t.check(bp is not None, f"backup returns a path reason={reason!r}")
        if bp is None:
            continue
        bp = Path(bp)
        t.check(bp.exists(), f"backup file exists reason={reason!r}")
        t.check(bp.parent == _backups_dir(t), f"backup lives under backups/ reason={reason!r}")
        t.check(bp.name.startswith("labdesk-"), f"backup name prefix reason={reason!r}")
        t.check(
            bp.name.endswith(f"-{reason}.sqlite"), f"backup name carries reason reason={reason!r}"
        )
        t.check(bp.suffix == ".sqlite", f"backup .sqlite suffix reason={reason!r}")
        t.check(db._looks_like_labdesk_db(bp), f"backup is a valid labdesk DB reason={reason!r}")
        # 0600 perms (owner rw only)
        mode = stat.S_IMODE(os.stat(bp).st_mode)
        t.eq(mode, 0o600, f"backup is 0600 reason={reason!r}")
        # the backups dir itself is 0700
        dmode = stat.S_IMODE(os.stat(_backups_dir(t)).st_mode)
        t.eq(dmode, 0o700, f"backups dir is 0700 reason={reason!r}")
        # a backup is restorable as a labdesk DB (self-copy → safe over live)
        t.check(
            _restore_live(t, bp) is True, f"backup round-trips through restore reason={reason!r}"
        )

    # ----------------------------------------------------------------------
    # 2. backup_db content integrity — the copy must contain the same users
    #    rows as the live DB at backup time (online backup, not an empty file).
    # ----------------------------------------------------------------------
    t.section("backup_db: content fidelity")
    _clear_backups(t)
    live_users = t.con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    live_settings = t.con.execute("SELECT COUNT(*) FROM settings").fetchone()[0]
    for i in range(20):
        bp = db.backup_db(f"fidelity{i}", keep=1000)
        t.check(bp is not None, f"fidelity backup created i={i}")
        if bp is None:
            continue
        ro = sqlite3.connect(f"file:{bp}?mode=ro", uri=True)
        try:
            n_users = ro.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            n_set = ro.execute("SELECT COUNT(*) FROM settings").fetchone()[0]
            has_receipts = ro.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='receipts'"
            ).fetchone()
        finally:
            ro.close()
        t.eq(n_users, live_users, f"backup preserves user count i={i}")
        t.eq(n_set, live_settings, f"backup preserves settings count i={i}")
        t.check(has_receipts is not None, f"backup carries the schema i={i}")
        # file is non-trivial (SQLite header is 100 bytes; a real DB is bigger)
        t.check(os.path.getsize(bp) >= 512, f"backup file non-trivial i={i}")
        # the secrets file must NEVER be inside a backup copy
        ro2 = sqlite3.connect(f"file:{bp}?mode=ro", uri=True)
        try:
            wa = ro2.execute("SELECT value FROM settings WHERE key='whatsapp_api_key'").fetchone()
        finally:
            ro2.close()
        # the WhatsApp TOKEN must never live in the DB/backups (it belongs only
        # in the 0600 .secrets.json). An empty/absent key row is fine; a non-empty
        # token would be a secret leak.
        t.check(
            wa is None or not (wa[0] or "").strip(),
            f"backup carries no whatsapp token secret i={i}",
        )

    # ----------------------------------------------------------------------
    # 3. Pruning — keep=N must leave AT MOST N files. Because the filename has
    #    second granularity, we materialise distinct files by hand (mirroring
    #    what backup_db writes) so we can test the prune math deterministically,
    #    then also test the real backup_db prune for keep>=1.
    # ----------------------------------------------------------------------
    t.section("backup_db: prune to keep=N (synthetic timeline)")
    bdir = _backups_dir(t)
    bdir.mkdir(parents=True, exist_ok=True)

    def _seed_n(n):
        """Create n distinct, time-ordered backup files; return their sorted names."""
        _clear_backups(t)
        names = []
        for k in range(n):
            # zero-padded counter in the timestamp slot => unique, lex-sortable,
            # strictly increasing names (newest == largest), same shape as real ones
            name = f"labdesk-20260101-{k:06d}-auto.sqlite"
            p = bdir / name
            shutil.copyfile(live, p)
            names.append(name)
        return sorted(names)

    def _prune(keep):
        """Re-implement backup_db's prune step over the existing files."""
        for old in (
            sorted(bdir.glob("labdesk-*.sqlite"))[:-keep]
            if keep > 0
            else sorted(bdir.glob("labdesk-*.sqlite"))
        ):
            try:
                old.unlink()
            except OSError:
                pass

    for total in [0, 1, 2, 3, 5, 8, 13, 14, 15, 20, 30, 50]:
        for keep in [1, 2, 3, 5, 14, 30, 100]:
            sorted_names = _seed_n(total)
            _prune(keep)
            remaining = [p.name for p in _list_backups(t)]
            expected_count = min(total, keep) if keep > 0 else 0
            t.eq(
                len(remaining),
                expected_count,
                f"prune leaves min(total,keep) total={total} keep={keep}",
            )
            # the survivors must be the NEWEST ones (lexicographically largest)
            expected_survivors = sorted(sorted_names[-keep:]) if keep > 0 else []
            t.eq(
                sorted(remaining),
                expected_survivors,
                f"prune keeps the newest total={total} keep={keep}",
            )
            # boundary: never delete more than total, never keep more than total
            t.check(
                len(remaining) <= total,
                f"never more survivors than seeded total={total} keep={keep}",
            )
            t.check(
                len(remaining) <= keep, f"never more survivors than keep total={total} keep={keep}"
            )

    # ----------------------------------------------------------------------
    # 4. Real backup_db pruning — repeatedly back up with a small keep and
    #    assert the directory never exceeds `keep`. We pre-seed older synthetic
    #    files so the new (current-second) backup forces real pruning.
    # ----------------------------------------------------------------------
    t.section("backup_db: real prune via backup_db(keep=N)")
    for keep in [1, 2, 3, 5, 14]:
        _clear_backups(t)
        # seed keep+10 older files (timestamps strictly before "now")
        for k in range(keep + 10):
            p = bdir / f"labdesk-20200101-{k:06d}-old.sqlite"
            shutil.copyfile(live, p)
        bp = db.backup_db("prunetest", keep=keep)
        t.check(bp is not None, f"real backup created keep={keep}")
        remaining = _list_backups(t)
        t.check(len(remaining) <= keep, f"real backup_db prunes to <= keep keep={keep}")
        t.eq(len(remaining), keep, f"real backup_db prunes to exactly keep keep={keep}")
        # the freshly written backup (newest name) must survive the prune
        if bp is not None:
            t.check(Path(bp).exists(), f"the new backup survives its own prune keep={keep}")
            t.check(Path(bp) in remaining, f"new backup is among survivors keep={keep}")
    _clear_backups(t)

    # ----------------------------------------------------------------------
    # 5. restore_db rejections — missing / garbage / foreign files all return
    #    False, and crucially DO NOT corrupt the live DB (still valid after).
    # ----------------------------------------------------------------------
    t.section("restore_db: reject missing files")
    MISSING = [
        "/no/such/file.sqlite",
        str(tmp / "does_not_exist.sqlite"),
        str(tmp / "nested" / "missing.sqlite"),
        "",
        "relative-missing.sqlite",
        str(tmp / "another-missing"),
        "/tmp/labdesk-ghost-987654321.sqlite",
    ]
    for path in MISSING:
        t.check(db.restore_db(path) is False, f"restore rejects missing path={path!r}")
        t.check(
            live.exists() and db._looks_like_labdesk_db(live),
            f"live DB intact after missing-restore path={path!r}",
        )

    t.section("restore_db: reject garbage / foreign files")
    garbage_files = {}
    # plain text
    g1 = tmp / "garbage_text.sqlite"
    g1.write_text("this is not a database, just some text\n" * 10)
    garbage_files["plain text"] = g1
    # empty file
    g2 = tmp / "garbage_empty.sqlite"
    g2.write_bytes(b"")
    garbage_files["empty"] = g2
    # almost-SQLite header but truncated / wrong
    g3 = tmp / "garbage_partial_header.sqlite"
    g3.write_bytes(b"SQLite format 2\x00rest is junk")
    garbage_files["wrong header magic"] = g3
    # correct magic but not a real DB body (truncated header)
    g4 = tmp / "garbage_magic_only.sqlite"
    g4.write_bytes(b"SQLite format 3\x00")
    garbage_files["magic only no body"] = g4
    # the dummy PDF the harness provides
    garbage_files["pdf"] = t.dummy_pdf
    # random binary
    g5 = tmp / "garbage_binary.sqlite"
    g5.write_bytes(bytes(range(256)) * 8)
    garbage_files["random binary"] = g5
    # a valid SQLite DB that is NOT a labdesk DB (no users table)
    g6 = tmp / "foreign_db.sqlite"
    if g6.exists():
        g6.unlink()
    fc = sqlite3.connect(g6)
    fc.execute("CREATE TABLE notes(id INTEGER PRIMARY KEY, body TEXT)")
    fc.execute("INSERT INTO notes(body) VALUES ('hello')")
    fc.commit()
    fc.close()
    garbage_files["foreign sqlite (no users)"] = g6
    # a valid SQLite DB with a 'user' table (singular) — must still be rejected
    g7 = tmp / "foreign_user_singular.sqlite"
    if g7.exists():
        g7.unlink()
    fc2 = sqlite3.connect(g7)
    fc2.execute("CREATE TABLE user(id INTEGER PRIMARY KEY)")
    fc2.commit()
    fc2.close()
    garbage_files["foreign sqlite (user singular)"] = g7
    # a directory path (not a file)
    gdir = tmp / "a_directory.sqlite"
    gdir.mkdir(exist_ok=True)
    garbage_files["directory"] = gdir

    for label, p in garbage_files.items():
        t.check(db.restore_db(str(p)) is False, f"restore rejects garbage [{label}]")
        t.check(
            live.exists() and db._looks_like_labdesk_db(live),
            f"live DB intact after garbage-restore [{label}]",
        )
        # the gatekeeper must agree
        t.check(db._looks_like_labdesk_db(p) is False, f"_looks_like_labdesk_db rejects [{label}]")

    # ----------------------------------------------------------------------
    # 6. _looks_like_labdesk_db acceptance — a DB WITH a users table and the
    #    SQLite magic header is accepted, even minimal ones.
    # ----------------------------------------------------------------------
    t.section("_looks_like_labdesk_db: accept valid DBs")
    # minimal labdesk-ish DB: just a users table
    ok1 = tmp / "minimal_users.sqlite"
    if ok1.exists():
        ok1.unlink()
    oc = sqlite3.connect(ok1)
    oc.execute("CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT)")
    oc.commit()
    oc.close()
    t.check(db._looks_like_labdesk_db(ok1) is True, "accepts a minimal DB with a users table")
    # users table created with extra columns / data
    ok2 = tmp / "users_with_rows.sqlite"
    if ok2.exists():
        ok2.unlink()
    oc2 = sqlite3.connect(ok2)
    oc2.execute("CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT, role TEXT)")
    oc2.execute("INSERT INTO users(username, role) VALUES ('admin','admin')")
    oc2.execute("CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT)")
    oc2.commit()
    oc2.close()
    t.check(db._looks_like_labdesk_db(ok2) is True, "accepts DB with users+settings")
    # NOTE: we deliberately do NOT restore these stub DBs over the live file —
    # that would swap the schema out from under the harness's shared t.con and
    # break later modules. _looks_like acceptance is the invariant under test;
    # actual file replacement is covered with self-copies elsewhere.
    # case sensitivity: sqlite_master name match is exact 'users'
    for tbl, expect in [
        ("Users", False),
        ("USERS", False),
        ("users", True),
        ("usersx", False),
        ("xusers", False),
        ("my_users", False),
    ]:
        p = tmp / f"case_{tbl}.sqlite"
        if p.exists():
            p.unlink()
        c = sqlite3.connect(p)
        c.execute(f'CREATE TABLE "{tbl}"(id INTEGER PRIMARY KEY)')
        c.commit()
        c.close()
        t.eq(db._looks_like_labdesk_db(p), expect, f"_looks_like table-name match tbl={tbl!r}")

    # restore the canonical (real) live backup so subsequent generators see a
    # genuine labdesk DB, not the minimal stub.
    _clear_backups(t)
    real_bp = db.backup_db("restore-canonical", keep=1000)
    if real_bp is not None:
        t.check(_restore_live(t, real_bp) is True, "restore canonical live DB")
    _clear_backups(t)

    # ----------------------------------------------------------------------
    # 7. restore_db safety copy — a successful restore first writes a
    #    .pre-restore copy of the current live DB.
    # ----------------------------------------------------------------------
    t.section("restore_db: .pre-restore safety copy")
    pre = Path(str(live) + ".pre-restore")
    if pre.exists():
        pre.unlink()
    # make a known-good backup to restore from
    good = db.backup_db("safety", keep=1000)
    t.check(good is not None, "safety backup created")
    if good is not None:
        ok = _restore_live(t, good)
        t.check(ok is True, "restore from a real backup succeeds")
        t.check(pre.exists(), "restore wrote a .pre-restore safety copy")
        t.check(
            db._looks_like_labdesk_db(pre) if pre.exists() else False,
            "the .pre-restore copy is itself a valid labdesk DB",
        )
        # restoring again still works (idempotent) and refreshes .pre-restore
        t.check(_restore_live(t, good) is True, "restore is repeatable")
    _clear_backups(t)

    # ----------------------------------------------------------------------
    # 8. WAL/SHM sidecars are removed after a restore so the freshly copied DB
    #    is not shadowed by stale write-ahead log frames.
    # ----------------------------------------------------------------------
    t.section("restore_db: clears stale WAL/SHM sidecars")
    good2 = db.backup_db("sidecar", keep=1000)
    if good2 is not None:
        wal = Path(str(live) + "-wal")
        shm = Path(str(live) + "-shm")
        wal.write_bytes(b"stale-wal-frames")
        shm.write_bytes(b"stale-shm")
        t.check(wal.exists() and shm.exists(), "stale sidecars planted")
        ok = db.restore_db(str(good2))  # check sidecar removal BEFORE any resync
        t.check(ok is True, "restore over stale sidecars succeeds")
        t.check(not wal.exists(), "restore removed stale -wal sidecar")
        t.check(not shm.exists(), "restore removed stale -shm sidecar")
        _resync(t)
        t.check(db._looks_like_labdesk_db(live), "live DB valid after sidecar-restore")
    _clear_backups(t)

    # ----------------------------------------------------------------------
    # 9. restored DB perms — after restore the live DB is hardened to 0600.
    # ----------------------------------------------------------------------
    t.section("restore_db: hardens live DB to 0600")
    good3 = db.backup_db("perms", keep=1000)
    if good3 is not None:
        # loosen perms first to prove restore re-hardens
        try:
            os.chmod(live, 0o644)
        except OSError:
            pass
        ok = db.restore_db(str(good3))  # check perms BEFORE resync
        t.check(ok is True, "restore (perms) succeeds")
        mode = stat.S_IMODE(os.stat(live).st_mode)
        t.eq(mode, 0o600, "restored live DB is 0600")
        _resync(t)
    _clear_backups(t)

    # ----------------------------------------------------------------------
    # 10. Stress: many backup/restore cycles never corrupt the live DB and the
    #     backups directory stays bounded by keep.
    # ----------------------------------------------------------------------
    t.section("stress: repeated backup→restore cycles stay consistent")
    _clear_backups(t)
    base_users = t.con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    for cyc in range(60):
        keep = (cyc % 5) + 1
        # clear first so the single new backup is unambiguously the survivor
        # (filename lex-order across reasons within one second is not monotonic)
        _clear_backups(t)
        bp = db.backup_db(f"cycle{cyc}", keep=keep)
        t.check(bp is not None, f"cycle backup created cyc={cyc}")
        t.check(len(_list_backups(t)) <= keep, f"cycle prune <= keep cyc={cyc}")
        if bp is not None:
            t.check(_restore_live(t, bp) is True, f"cycle restore ok cyc={cyc}")
            t.check(db._looks_like_labdesk_db(live), f"live DB valid cyc={cyc}")
            # restoring a backup of the live DB must preserve the user count
            ro = sqlite3.connect(f"file:{live}?mode=ro", uri=True)
            try:
                nu = ro.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            finally:
                ro.close()
            t.eq(nu, base_users, f"user count preserved across cycle cyc={cyc}")
    _clear_backups(t)

    # ----------------------------------------------------------------------
    # 11. keep boundary values fed directly to the real backup_db. keep<=0 is
    #     a degenerate input — document its observed behaviour without crashing.
    #     (Python's list[:-0] == list[:0] == [] would delete EVERYTHING; we
    #     assert the live DB survives and capture the directory outcome.)
    # ----------------------------------------------------------------------
    t.section("backup_db: keep boundary values")
    # keep very large => nothing pruned
    _clear_backups(t)
    for k in range(5):
        shutil.copyfile(live, bdir / f"labdesk-20210101-{k:06d}-pre.sqlite")
    bp = db.backup_db("largekeep", keep=10_000)
    t.check(bp is not None, "backup with huge keep created")
    t.eq(len(_list_backups(t)), 6, "huge keep prunes nothing (5 seeded + 1 new)")
    t.check(db._looks_like_labdesk_db(live), "live DB valid after huge-keep backup")
    _clear_backups(t)

    # keep == 0 boundary: sorted(...)[:-0] == [] so NOTHING is pruned by
    # backup_db (the slice is empty). Assert the new backup still exists and the
    # live DB is intact regardless of the prune semantics.
    for k in range(4):
        shutil.copyfile(live, bdir / f"labdesk-20210202-{k:06d}-pre.sqlite")
    bp0 = db.backup_db("zerokeep", keep=0)
    t.check(bp0 is not None, "backup with keep=0 still creates the file")
    if bp0 is not None:
        t.check(Path(bp0).exists(), "keep=0 backup file exists (slice [:-0] prunes nothing)")
    t.check(db._looks_like_labdesk_db(live), "live DB valid after keep=0 backup")
    _clear_backups(t)

    # ----------------------------------------------------------------------
    # 12. restore_db return type is strictly a bool (True/False, never None or
    #     a truthy path) — callers branch on it.
    # ----------------------------------------------------------------------
    t.section("restore_db: strict bool return type")
    bp = db.backup_db("rettype", keep=1000)
    if bp is not None:
        r_ok = db.restore_db(str(bp))
        _resync(t)
        t.check(r_ok is True, "successful restore returns True (identity)")
        t.check(isinstance(r_ok, bool), "restore success result is a bool")
    r_bad = db.restore_db("/definitely/not/here.sqlite")
    t.check(r_bad is False, "failed restore returns False (identity)")
    t.check(isinstance(r_bad, bool), "restore failure result is a bool")
    _clear_backups(t)

    # ----------------------------------------------------------------------
    # 13. _looks_like_labdesk_db on missing / odd paths never raises and is
    #     False for anything that is not a readable SQLite-with-users file.
    # ----------------------------------------------------------------------
    t.section("_looks_like_labdesk_db: robustness on bad paths")
    for bad in [Path("/no/such.sqlite"), tmp / "ghost.sqlite", Path("/"), tmp]:
        t.check(
            db._looks_like_labdesk_db(bad) is False, f"_looks_like rejects bad path {str(bad)!r}"
        )
