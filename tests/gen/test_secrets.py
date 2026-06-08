"""Generator — secret store invariants (db.set_secret / db.get_secret).

The secret store is a 0600 JSON file (``.secrets.json``) in the data dir, kept
OUT of the SQLite DB so DB copies/backups don't leak tokens. Contract:
  * set_secret(key, value) -> None              (last write wins)
  * get_secret(key, default="") -> str          (str()-coerced, default on miss)
This module covers round-trip, default fallback, overwrite, unicode, extremes,
and that secrets and settings live in separate stores.
"""
from __future__ import annotations


def register(t):
    db = t.db
    con = t.con

    # ----------------------------------------------------------------------
    t.section("round-trip: many keys / values persist & coerce to str")
    KEYS = [
        "whatsapp_api_key", "k", "K", "key_1", "key-2", "key.3", "key 4",
        "UPPER", "lower", "MiXeD", "123numeric", "with_underscore",
        "dotted.key.name", "slash/key", "a" * 200, "x" * 1000,
    ]
    VALUES = [
        "topsecret", "", " ", "  spaces  ", "tab\tinside", "new\nline",
        "0", "1", "false", "true", "null", "None",
        "v" * 500, "x" * 4000, "00123", "+923001234567",
        '{"json":"like"}', "a,b,c", "line1\r\nline2", "trailing ",
    ]
    for ki, key in enumerate(KEYS):
        for value in VALUES:
            db.set_secret(key, value)
            got = db.get_secret(key)
            # round-trips exactly (already a str -> str() is identity)
            t.eq(got, value, f"roundtrip key={key!r} val={value!r}")
            # return type is always str
            t.check(isinstance(got, str), f"str type key={key!r}")
            # present key ignores the default argument
            t.eq(db.get_secret(key, "FALLBACK"), value,
                 f"present-ignores-default key={key!r} val={value!r}")

    # ----------------------------------------------------------------------
    t.section("default fallback: missing keys return the supplied default")
    MISSING = [
        "definitely_absent_key", "____nope____", "missing-1", "no.such.key",
        "", " ", "0", "MISSINGUNI_éè", "x" * 300,
    ]
    DEFAULTS = ["", "d", "default-value", "0", "None", "☃ snow",
                " padded ", "multi\nline", "x" * 256]
    for mk in MISSING:
        # ensure the key is truly absent (overwrite any earlier write? -- these
        # names never collide with KEYS above, so they stay absent)
        for d in DEFAULTS:
            t.eq(db.get_secret(mk, d), d, f"default key={mk!r} default={d!r}")
            t.check(isinstance(db.get_secret(mk, d), str),
                    f"default str-type key={mk!r}")
        # the zero-arg default is the empty string
        t.eq(db.get_secret(mk), "", f"empty-default key={mk!r}")

    # ----------------------------------------------------------------------
    t.section("overwrite semantics: last write wins, no accumulation")
    OW_KEY = "overwrite_target_key"
    SEQ = ["first", "second", "", "third", "third", "éèê",
           "0", "x" * 2000, "final", " spaced final "]
    for v in SEQ:
        db.set_secret(OW_KEY, v)
        t.eq(db.get_secret(OW_KEY), v, f"overwrite -> {v!r}")
    # a long overwrite chain on several keys, interleaved
    OW_KEYS = ["ow_a", "ow_b", "ow_c"]
    for i in range(40):
        for k in OW_KEYS:
            val = f"{k}#{i}"
            db.set_secret(k, val)
        # after writing all three this round, each still holds its own value
        for k in OW_KEYS:
            t.eq(db.get_secret(k), f"{k}#{i}", f"interleaved {k} round {i}")
    # final state after the loop is the last iteration's value
    for k in OW_KEYS:
        t.eq(db.get_secret(k), f"{k}#39", f"final interleaved {k}")

    # ----------------------------------------------------------------------
    t.section("independence: many keys coexist without clobbering each other")
    COEXIST = {f"coex_{i}": f"value_{i}_payload" for i in range(120)}
    for k, v in COEXIST.items():
        db.set_secret(k, v)
    for k, v in COEXIST.items():
        t.eq(db.get_secret(k), v, f"coexist {k}")
    # and they all survive after writing an unrelated key
    db.set_secret("coex_unrelated", "zzz")
    for k, v in COEXIST.items():
        t.eq(db.get_secret(k), v, f"coexist-after-unrelated {k}")

    # ----------------------------------------------------------------------
    t.section("unicode: keys and values round-trip byte-for-byte")
    UNI = [
        "café", "über", "naïve", "你好", "こんにちは",
        "مرحبا", "नमस्ते", "שלום",
        "emoji_\U0001f600", "\U0001f512key", "mix_ed_é_你_\U0001f680",
        "zero​width", "combining_é", "€£¥", "☃☄★",
    ]
    for u in UNI:
        # unicode value under an ascii key
        db.set_secret("uni_val_key", u)
        t.eq(db.get_secret("uni_val_key"), u, f"unicode value {u!r}")
        # unicode key with an ascii value
        db.set_secret(u, "ascii_payload")
        t.eq(db.get_secret(u), "ascii_payload", f"unicode key {u!r}")
        # unicode key AND value
        db.set_secret(u, u)
        t.eq(db.get_secret(u), u, f"unicode key+val {u!r}")
        # default fallback for an absent unicode key keeps the unicode default
        t.eq(db.get_secret("absent_" + u, u), u, f"unicode default {u!r}")

    # ----------------------------------------------------------------------
    t.section("separation: secrets store is distinct from the settings table")
    SHARED = ["whatsapp_api_key", "currency", "shared_name", "k", "token"]
    for k in SHARED:
        secret_val = f"SECRET::{k}"
        setting_val = f"SETTING::{k}"
        db.set_secret(k, secret_val)
        db.set_setting(con, k, setting_val)
        # each store keeps its own value under the same key
        t.eq(db.get_secret(k), secret_val, f"secret unaffected by setting {k}")
        t.eq(db.get_setting(con, k), setting_val, f"setting unaffected by secret {k}")
        # writing a secret does not create a settings row (and vice versa)
        only_secret = f"only_secret_{k}"
        db.set_secret(only_secret, "S")
        t.eq(db.get_secret(only_secret), "S", f"only-secret present {k}")
        t.eq(db.get_setting(con, only_secret, "MISS"), "MISS",
             f"only-secret absent from settings {k}")
        only_setting = f"only_setting_{k}"
        db.set_setting(con, only_setting, "T")
        t.eq(db.get_setting(con, only_setting), "T", f"only-setting present {k}")
        t.eq(db.get_secret(only_setting, "MISS"), "MISS",
             f"only-setting absent from secrets {k}")

    # secrets must NOT be persisted inside the sqlite settings table at all
    db.set_secret("secret_not_in_db", "must_not_leak_to_db")
    row = con.execute(
        "SELECT value FROM settings WHERE key=?", ("secret_not_in_db",)
    ).fetchone()
    t.check(row is None, "secret never written to settings table")

    # ----------------------------------------------------------------------
    t.section("boundaries / extremes / odd inputs")
    # empty string key is a legal key
    db.set_secret("", "empty_key_value")
    t.eq(db.get_secret(""), "empty_key_value", "empty key round-trip")
    db.set_secret("", "overwritten_empty")
    t.eq(db.get_secret(""), "overwritten_empty", "empty key overwrite")

    # very large value
    big = "B" * 200000
    db.set_secret("big_value_key", big)
    t.eq(db.get_secret("big_value_key"), big, "200k value round-trip")
    t.eq(len(db.get_secret("big_value_key")), 200000, "200k length preserved")

    # value that looks like JSON should not be parsed/mangled
    for jv in ['{"a":1}', "[1,2,3]", "true", "null", "123", "1.5e3",
               '"quoted"', "{broken json", "}{", "\\escaped"]:
        db.set_secret("json_like_key", jv)
        t.eq(db.get_secret("json_like_key"), jv, f"json-like value {jv!r}")

    # keys that look like JSON syntax
    for jk in ['{"x":1}', "[0]", '"q"', "key:with:colons", "key=eq"]:
        db.set_secret(jk, "ok")
        t.eq(db.get_secret(jk), "ok", f"json-like key {jk!r}")

    # whitespace-only and control characters preserved verbatim
    for wv in [" ", "\t", "\n", "\r\n", "  \t  ", "\x07bell", "a\x00b"]:
        db.set_secret("ws_key", wv)
        t.eq(db.get_secret("ws_key"), wv, f"whitespace/ctrl value {wv!r}")

    # repeatedly clearing to empty then setting again
    for i in range(30):
        db.set_secret("toggle_key", "")
        t.eq(db.get_secret("toggle_key"), "", f"cleared toggle {i}")
        db.set_secret("toggle_key", f"on_{i}")
        t.eq(db.get_secret("toggle_key"), f"on_{i}", f"set toggle {i}")

    # default argument with an empty stored value: an explicitly stored "" is a
    # real value, NOT a miss -> the default must be ignored.
    db.set_secret("stored_empty_key", "")
    t.eq(db.get_secret("stored_empty_key", "DEFAULT"), "",
         "stored empty value beats default")
