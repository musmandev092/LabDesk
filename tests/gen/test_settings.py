"""Settings + WhatsApp caption templating invariants.

Focus (per QA brief): src/labdesk/db.py get_setting / set_setting / currency
and the caption templating in whatsapp.py (_caption / _cfg timeout clamp).

Round-trips many keys/values, exercises update semantics, default fallback,
unicode/empty/garbage values, and proves the caption templates cannot leak
python internals: _caption uses plain str.replace (NOT str.format) so a crafted
template like "{lab.__class__}" must be returned literally, and unknown
placeholders like "{bogus}" pass through unchanged.

This module emits well over 2,000 cases.
"""
from __future__ import annotations


def register(t):
    db = t.db
    wa = t.whatsapp
    con = t.con

    # =====================================================================
    # 1) get_setting / set_setting round-trip + update semantics
    # =====================================================================
    t.section("setting round-trip / update / default fallback")

    # A large pool of values covering empties, unicode, garbage, extremes.
    VALUES = [
        "", " ", "0", "1", "v1", "v2", "Rs.", "PKR", "₨", "$",
        "hello world", "  leading+trailing  ", "line1\nline2", "tab\there",
        "ünïcødé", "漢字テスト", "العربية", "emoji 🧪🔬", "{lab}", "{lab.__class__}",
        "'; DROP TABLE settings;--", '"quoted"', "back\\slash", "null\x00byte"[:4],
        "-1", "99999999", "3.14159", "True", "False", "None",
        "x" * 500, "<html>&amp;</html>", "%s %d {0}", "café",
    ]

    # Round-trip + idempotent re-write + update to a different value.
    for i, v in enumerate(VALUES):
        key = f"gen_rt_{i}"
        db.set_setting(con, key, v)
        t.eq(db.get_setting(con, key), v, f"round-trip key={key!r}")
        # writing the same value again must keep it (idempotent upsert)
        db.set_setting(con, key, v)
        t.eq(db.get_setting(con, key), v, f"idempotent re-set key={key!r}")
        # default is ignored when the key exists (even if value is empty string)
        t.eq(db.get_setting(con, key, "DEFAULT_SHOULD_NOT_SHOW"), v,
             f"existing key ignores default key={key!r}")

    # Update semantics: last write wins, across every pair of distinct values.
    for i, v1 in enumerate(VALUES):
        for v2 in VALUES[:16]:
            db.set_setting(con, "gen_upd", v1)
            t.eq(db.get_setting(con, "gen_upd"), v1, f"update step1 {v1!r}")
            db.set_setting(con, "gen_upd", v2)
            t.eq(db.get_setting(con, "gen_upd"), v2, f"update step2 -> {v2!r}")

    # =====================================================================
    # 2) default fallback for missing keys
    # =====================================================================
    t.section("default fallback for missing keys")
    MISSING = ["totally_missing_key", "", "  ", "no.such.key", "MixedCaseKey",
               "key with spaces", "키없음", "{tpl}", "x" * 200]
    DEFAULTS = ["", "fallback", "Rs.", "0", "₨", "ünïcødé", "multi\nline"]
    for mk in MISSING:
        for d in DEFAULTS:
            t.eq(db.get_setting(con, mk, d), d, f"missing key={mk!r} -> default {d!r}")
        # default param itself defaults to "" when omitted
        t.eq(db.get_setting(con, mk), "", f"missing key={mk!r} -> '' when no default")

    # =====================================================================
    # 3) NULL value in DB falls back to default (get_setting: row[0] is None)
    # =====================================================================
    t.section("NULL stored value -> default")
    for i, d in enumerate(["", "FB", "Rs.", "0"]):
        nk = f"gen_null_{i}"
        # insert an explicit NULL value
        con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES (?,NULL)", (nk,))
        con.commit()
        t.eq(db.get_setting(con, nk, d), d, f"NULL value key={nk!r} -> default {d!r}")
        # and once overwritten with a real value, it is returned
        db.set_setting(con, nk, "real")
        t.eq(db.get_setting(con, nk), "real", f"NULL then set key={nk!r}")

    # =====================================================================
    # 4) currency() — default Rs., reflects setting, matches get_setting
    # =====================================================================
    t.section("currency() default + override")
    CUR_VALUES = ["Rs.", "PKR", "₨", "$", "€", "£", "USD", "", "Rs", "  Rs.  ",
                  "Rupees", "د.إ", "৳", "x" * 50]
    for c in CUR_VALUES:
        db.set_setting(con, "currency", c)
        t.eq(db.currency(con), c, f"currency override -> {c!r}")
        t.eq(db.currency(con), db.get_setting(con, "currency", "Rs."),
             f"currency matches get_setting {c!r}")
    # When the currency row holds NULL, currency() falls back to Rs.
    con.execute("UPDATE settings SET value=NULL WHERE key='currency'")
    con.commit()
    t.eq(db.currency(con), "Rs.", "currency NULL -> Rs. default")
    db.set_setting(con, "currency", "Rs.")  # restore sane default

    # =====================================================================
    # 5) DEFAULT_SETTINGS keys are all present after init_db
    # =====================================================================
    t.section("default settings seeded")
    for k, v in db.DEFAULT_SETTINGS.items():
        # the seeded value must be retrievable (init_db ran in the runner)
        got = db.get_setting(con, k, "\x00SENTINEL")
        t.check(got != "\x00SENTINEL", f"default setting {k!r} present in DB")
    # A few specific seeded defaults we know the correct value of.
    KNOWN_DEFAULTS = {
        "currency": "Rs.",
        "whatsapp_country_code": "92",
        "whatsapp_timeout": "40",
        "whatsapp_auto": "0",
        "whatsapp_auto_receipt": "0",
        "lab_no_prefix": "LAB",
        "promo_discount_pct": "0",
        "theme": "light",
        "idle_lock_minutes": "0",
        "whatsapp_session": "default",
    }
    # currency was just restored above; assert the rest from DEFAULT_SETTINGS dict.
    for k, want in KNOWN_DEFAULTS.items():
        t.eq(db.DEFAULT_SETTINGS.get(k), want, f"DEFAULT_SETTINGS[{k!r}]")

    # =====================================================================
    # 6) caption templating: blank template -> fallback
    # =====================================================================
    t.section("caption blank -> fallback")
    FALLBACKS = ["FB", "", "Your laboratory report", "Lab — Report 1 for Joe", "₨ caption"]
    for fb in FALLBACKS:
        # unknown key -> never set -> blank template -> fallback
        t.eq(wa._caption(con, "gen_no_such_caption_key", fb, lab="L", lab_no="N", name="X"),
             fb, f"blank template -> fallback {fb!r}")
        # explicitly-blank stored template -> fallback
        db.set_setting(con, "whatsapp_report_caption", "")
        t.eq(wa._caption(con, "whatsapp_report_caption", fb, lab="L"),
             fb, f"empty stored template -> fallback {fb!r}")
        # whitespace-only template -> stripped to blank -> fallback
        db.set_setting(con, "whatsapp_report_caption", "   ")
        t.eq(wa._caption(con, "whatsapp_report_caption", fb, lab="L"),
             fb, f"whitespace template -> fallback {fb!r}")
    db.set_setting(con, "whatsapp_report_caption", "")

    # =====================================================================
    # 7) caption placeholder substitution ({lab}/{lab_no}/{name})
    # =====================================================================
    t.section("caption placeholder substitution")
    LABS = ["Allied Lab", "", "L&L", "ünïlab", "漢字", "Lab {x}", "a" * 100]
    NOS = ["LAB-001", "", "0001", "N/1", "9999999"]
    NAMES = ["Joe", "", "Ali Hassan", "O'Brien", "测试", "{name}", "🧑"]
    for lab in LABS:
        for no in NOS:
            for nm in NAMES:
                db.set_setting(con, "whatsapp_report_caption", "{lab}/{lab_no}/{name}")
                want = f"{lab}/{no}/{nm}"
                got = wa._caption(con, "whatsapp_report_caption", "FB",
                                  lab=lab, lab_no=no, name=nm)
                t.eq(got, want, f"render lab={lab!r} no={no!r} nm={nm!r}")
                # order-independent: a different ordering still substitutes each token
                db.set_setting(con, "whatsapp_report_caption", "{name}|{lab}|{lab_no}")
                t.eq(wa._caption(con, "whatsapp_report_caption", "FB",
                                 lab=lab, lab_no=no, name=nm),
                     f"{nm}|{lab}|{no}", f"reordered render lab={lab!r}")
    db.set_setting(con, "whatsapp_report_caption", "")

    # =====================================================================
    # 8) SECURITY: format-string / internals injection must be sanitized.
    #    _caption uses str.replace, never str.format, so these stay literal
    #    (a str.format implementation would leak object internals / crash).
    # =====================================================================
    t.section("caption injection cannot leak python internals")
    INJECTIONS = [
        "{lab.__class__}",
        "{lab.__class__.__mro__}",
        "{lab.__class__.__bases__[0].__subclasses__}",
        "{lab!r}",
        "{lab:>80}",
        "{0}",
        "{1}",
        "{}",
        "{lab[0]}",
        "{name.__dict__}",
        "{lab_no.__init__.__globals__}",
        "{{lab}}",                      # literal braces, not a placeholder
        "{ lab }",                      # spaces -> not the exact token {lab}
        "{LAB}",                        # wrong case -> not substituted
        "{lab_no_extra}",               # superstring -> only {lab_no} token matches
        "%(lab)s",                      # printf-style -> untouched
        "${lab}",                       # shell-style -> only {lab} part substituted
    ]
    for inj in INJECTIONS:
        db.set_setting(con, "whatsapp_report_caption", inj)
        got = wa._caption(con, "whatsapp_report_caption", "FB",
                          lab="LABVAL", lab_no="NOVAL", name="NAMEVAL")
        # The known whole tokens {lab}, {lab_no}, {name} are the ONLY things
        # replaced; everything else (dotted attrs, format specs) stays literal.
        expected = (inj.replace("{lab}", "LABVAL")
                       .replace("{lab_no}", "NOVAL")
                       .replace("{name}", "NAMEVAL"))
        t.eq(got, expected, f"injection literal-safe {inj!r}")
        # Hard invariants: no python internals ever leak into the output.
        t.check("<class" not in got, f"no <class leak {inj!r}")
        t.check("object at 0x" not in got, f"no repr/addr leak {inj!r}")
        t.check("__subclasses__" not in got or "__subclasses__" in inj,
                f"no method-object leak {inj!r}")
        t.check("globals" not in got.lower() or "globals" in inj.lower(),
                f"no globals leak {inj!r}")
    db.set_setting(con, "whatsapp_report_caption", "")

    # Specific, named guarantee from the brief: {lab.__class__} sanitized.
    db.set_setting(con, "whatsapp_report_caption", "{lab.__class__}")
    t.eq(wa._caption(con, "whatsapp_report_caption", "FB", lab="L"),
         "{lab.__class__}", "{lab.__class__} kept literal (no .format)")
    db.set_setting(con, "whatsapp_report_caption", "")

    # =====================================================================
    # 9) Unknown placeholder passes through unchanged (no KeyError/crash)
    # =====================================================================
    t.section("unknown placeholder passes through")
    UNKNOWN = ["{bogus}", "{x}{y}{z}", "prefix {unknown} suffix", "{labx}",
               "{nam}", "{lab_n}", "no placeholders at all", "{lab_no_}"]
    for u in UNKNOWN:
        db.set_setting(con, "whatsapp_report_caption", u)
        # only the exact known tokens substitute; these contain none, so unchanged
        got = wa._caption(con, "whatsapp_report_caption", "FB",
                          lab="LV", lab_no="NV", name="NM")
        want = (u.replace("{lab}", "LV").replace("{lab_no}", "NV")
                 .replace("{name}", "NM"))
        t.eq(got, want, f"unknown placeholder passthrough {u!r}")
    db.set_setting(con, "whatsapp_report_caption", "")

    # =====================================================================
    # 10) caption works on the receipt caption key too (same code path)
    # =====================================================================
    t.section("receipt caption key")
    for lab in LABS[:4]:
        for nm in NAMES[:4]:
            db.set_setting(con, "whatsapp_receipt_caption", "{lab} bill for {name}")
            t.eq(wa._caption(con, "whatsapp_receipt_caption", "FB", lab=lab, name=nm),
                 f"{lab} bill for {nm}", f"receipt caption lab={lab!r} nm={nm!r}")
    db.set_setting(con, "whatsapp_receipt_caption", "")

    # =====================================================================
    # 11) _cfg timeout clamping (5..120, bad -> 40) across many values
    # =====================================================================
    t.section("whatsapp_timeout clamping in _cfg")
    # (value-string, expected-clamped-int)
    TIMEOUTS = [
        ("0", 5), ("1", 5), ("4", 5), ("5", 5), ("6", 6), ("39", 39), ("40", 40),
        ("41", 41), ("119", 119), ("120", 120), ("121", 120), ("9999", 120),
        ("-5", 5), ("-100", 5), ("100", 100), ("60", 60), ("30", 30),
        ("3.9", 5), ("5.9", 5), ("40.0", 40), ("119.9", 119),
        # garbage / empty -> default 40 ; "1e3" is a valid float (1000) -> clamp 120
        ("", 40), ("abc", 40), ("  ", 40), ("4o", 40), ("1e3", 120),
        ("nan", 40), ("0x10", 40), ("40 ", 40), (" 30", 30),
    ]
    for val, want in TIMEOUTS:
        db.set_setting(con, "whatsapp_timeout", val)
        try:
            got = wa._cfg(con)["timeout"]
        except Exception as e:  # _cfg must never raise on bad input
            got = f"RAISED:{e!r}"
        t.eq(got, want, f"timeout {val!r} -> {want}")

    # BUG: "inf"/"-inf" parse as float() but int(inf) raises OverflowError, which
    # _cfg only guards against (TypeError, ValueError) — so _cfg() crashes and the
    # whole WhatsApp send aborts. A sane timeout setting should never crash _cfg.
    for bad in ("inf", "-inf", "Infinity"):
        db.set_setting(con, "whatsapp_timeout", bad)
        raised = False
        try:
            wa._cfg(con)
        except Exception:
            raised = True
        t.check(not raised, f"_cfg must not crash on whatsapp_timeout={bad!r}")
    db.set_setting(con, "whatsapp_timeout", "40")

    # =====================================================================
    # 12) _cfg url/token/cc reflect settings + secret, url is rstrip('/')-ed
    # =====================================================================
    t.section("_cfg url / token / country code")
    URLS = [
        ("http://localhost:8080", "http://localhost:8080"),
        ("http://localhost:8080/", "http://localhost:8080"),
        ("http://localhost:8080///", "http://localhost:8080"),
        ("https://gw.example/api/", "https://gw.example/api"),
        ("", ""),
        ("http://h:80/", "http://h:80"),
    ]
    for raw, want in URLS:
        db.set_setting(con, "whatsapp_url", raw)
        t.eq(wa._cfg(con)["url"], want, f"_cfg url rstrip {raw!r}")
    # token comes from the secret file in preference to the DB
    db.set_secret("whatsapp_api_key", "SECRET_TOK")
    t.eq(wa._cfg(con)["token"], "SECRET_TOK", "_cfg token from secret")
    db.set_secret("whatsapp_api_key", "")
    db.set_setting(con, "whatsapp_api_key", "DB_TOK")
    t.eq(wa._cfg(con)["token"], "DB_TOK", "_cfg token falls back to DB value")
    db.set_setting(con, "whatsapp_api_key", "")
    # country code: empty / NULL -> default "92"
    for cc, want in [("92", "92"), ("1", "1"), ("44", "44"), ("", "92"), ("971", "971")]:
        db.set_setting(con, "whatsapp_country_code", cc)
        t.eq(wa._cfg(con)["cc"], want, f"_cfg cc {cc!r} -> {want}")
    db.set_setting(con, "whatsapp_country_code", "92")
    db.set_setting(con, "whatsapp_url", "")

    # =====================================================================
    # 13) Persistence: every key independent; bulk write/read across a grid
    # =====================================================================
    t.section("bulk independent-key persistence grid")
    KEYS = [f"gen_bulk_{i}" for i in range(40)]
    GRID_VALS = ["A", "B", "ünï", "漢", "", "0", "Rs.", "{lab}", "x" * 80]
    # write a distinct value per key, then verify none clobbered another
    for vi, gv in enumerate(GRID_VALS):
        for ki, k in enumerate(KEYS):
            db.set_setting(con, k, f"{gv}#{ki}")
        for ki, k in enumerate(KEYS):
            t.eq(db.get_setting(con, k), f"{gv}#{ki}",
                 f"bulk key {k} val-round {vi}")

    # =====================================================================
    # 14) get_setting type guarantee: always returns the stored str exactly
    # =====================================================================
    t.section("get_setting returns stored string exactly (type/identity)")
    for i, v in enumerate(["123", "0", "-1", "3.14", " padded ", ""]):
        k = f"gen_type_{i}"
        db.set_setting(con, k, v)
        got = db.get_setting(con, k)
        t.check(isinstance(got, str), f"get_setting returns str key={k}")
        t.eq(got, v, f"get_setting exact str key={k}")
