"""Database layer for LabDesk.

A thin wrapper over sqlite3: locates the data directory, initialises the
schema, seeds default settings + an admin user, and hands out connections.
The DB lives next to the user's data (XDG dir when packaged), so the AppImage
stays read-only while data persists across updates.

This package was split out of a single ``db.py`` module by responsibility; this
``__init__`` re-exports the complete public API so ``from ..db import X`` and
``db.X(...)`` keep working unchanged. Layering (a module only imports from those
above it): _config → paths/crypto → connection → settings/audit → backup/auth →
patient_id → queries.
"""

from __future__ import annotations

# Stdlib modules that were importable as ``db.<name>`` from the original
# single-file module — kept re-exported so the public surface is unchanged.
import hashlib  # noqa: F401
import hmac  # noqa: F401
import json  # noqa: F401
import os  # noqa: F401
import re as _re  # noqa: F401
import secrets  # noqa: F401
import shutil  # noqa: F401
import time  # noqa: F401
from pathlib import Path  # noqa: F401

from ._config import (
    _EXTRA_COLUMNS,
    _LOCK_MAX_SECONDS,
    _LOCK_SECONDS,
    _MAX_FAILS,
    _SCRYPT_MAXMEM,
    _SCRYPT_N,
    _SCRYPT_P,
    _SCRYPT_R,
    APP_NAME,
    APP_VERSION,
    CATALOG_VERSION,
    DEFAULT_SETTINGS,
    NOT_VOIDED,
    RECEIVED_TODAY,
    SCHEMA_FILE,
    SEED_DB,
)
from ._driver import ENCRYPTION_AVAILABLE
from ._driver import sqlite3 as sqlite3  # explicit re-export (PEP 484)
from .audit import (
    _audit_fallback,
    audit_anchor_status,
    log_audit,
    rechain_audit,
    verify_audit_chain,
)
from .auth import (
    lock_remaining,
    verify_user,
)
from .backup import (
    _looks_like_labdesk_db,
    auto_backup,
    backup_db,
    backup_to,
    fallback_backup_dir,
    restore_db,
)
from .connection import (
    _ensure_columns,
    _ensure_indexes,
    _sync_catalog_from_seed,
    connect,
    db_is_plaintext,
    init_db,
    is_unlocked,
    lock,
    migrate_plaintext_to_encrypted,
    rekey_database,
    unlock,
    verify_passphrase,
)
from .crypto import (
    _DUMMY_HASH,
    _dummy_verify,
    _verify_password,
    hash_password,
)
from .paths import (
    _harden_perms,
    _secret_path,
    data_dir,
    db_path,
    get_secret,
    import_asset,
    set_secret,
)
from .patient_id import (
    _PID_ALPHABET,
    _PID_RE,
    _pid_check_letter,
    format_patient_id,
    validate_patient_id,
)
from .queries import (
    ParameterInUseError,
    delete_panel,
    list_panels,
    panel_tests,
    receive_due,
    save_panel,
    save_test_parameters,
)
from .settings import (
    currency,
    get_setting,
    set_setting,
    set_settings,
)

__all__ = [
    "APP_NAME",
    "APP_VERSION",
    "CATALOG_VERSION",
    "DEFAULT_SETTINGS",
    "ENCRYPTION_AVAILABLE",
    "NOT_VOIDED",
    "RECEIVED_TODAY",
    "SCHEMA_FILE",
    "SEED_DB",
    "_DUMMY_HASH",
    "_EXTRA_COLUMNS",
    "_LOCK_MAX_SECONDS",
    "_LOCK_SECONDS",
    "_MAX_FAILS",
    "_PID_ALPHABET",
    "_PID_RE",
    "_SCRYPT_MAXMEM",
    "_SCRYPT_N",
    "_SCRYPT_P",
    "_SCRYPT_R",
    "ParameterInUseError",
    "_audit_fallback",
    "_dummy_verify",
    "_ensure_columns",
    "_ensure_indexes",
    "_harden_perms",
    "_looks_like_labdesk_db",
    "_pid_check_letter",
    "_secret_path",
    "_sync_catalog_from_seed",
    # underscore helpers other code / tests may touch
    "_verify_password",
    "audit_anchor_status",
    "auto_backup",
    "backup_db",
    "backup_to",
    "connect",
    "currency",
    "data_dir",
    "db_is_plaintext",
    "db_path",
    "delete_panel",
    "fallback_backup_dir",
    "format_patient_id",
    "get_secret",
    "get_setting",
    "hash_password",
    "import_asset",
    "init_db",
    "is_unlocked",
    "list_panels",
    "lock",
    "lock_remaining",
    "log_audit",
    "migrate_plaintext_to_encrypted",
    "panel_tests",
    "receive_due",
    "rechain_audit",
    "rekey_database",
    "restore_db",
    "save_panel",
    "save_test_parameters",
    "set_secret",
    "set_setting",
    "set_settings",
    "unlock",
    "validate_patient_id",
    "verify_audit_chain",
    "verify_passphrase",
    "verify_user",
]
