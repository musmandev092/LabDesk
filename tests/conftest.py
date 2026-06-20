"""Shared fixtures: a real encrypted SQLCipher database in a throwaway temp dir.

Every test gets an isolated data dir (LABDESK_DATA_DIR) and a per-test session key,
so the suite exercises the same code paths the app uses — encrypted at rest, no
mocking of the DB layer. License enforcement / self-test env vars are neutralised so
they can't leak in from the developer's shell.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Neutralise environment that would otherwise change behaviour under test."""
    for var in (
        "LABDESK_ENFORCE_LICENSE",
        "LABDESK_SELFTEST",
        "LABDESK_ALLOW_PLAINTEXT",
        "LABDESK_DB_KEY",
        "LABDESK_SIGNING_KEY_DIR",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "labdesk-data"
    d.mkdir()
    monkeypatch.setenv("LABDESK_DATA_DIR", str(d))
    return d


@pytest.fixture
def db(data_dir):
    """The labdesk.db package with a fresh session key set. Each test gets a brand-new
    temp data dir (so the on-disk DB is fresh); the only shared state is the in-memory
    session key, which we set/clear per test."""
    import labdesk.db as dbmod

    if not dbmod.ENCRYPTION_AVAILABLE:
        pytest.skip("sqlcipher3 not available in this environment")
    dbmod.unlock("test-passphrase-123")
    yield dbmod
    dbmod.lock()


@pytest.fixture
def con(db):
    c = db.init_db()
    yield c
    c.close()
