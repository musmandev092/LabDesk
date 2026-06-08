"""RBAC matrix generator for src/labdesk/roles.py.

Exercises the full role x page x capability matrix plus the privilege-ordering
(level monotonicity) invariant and degenerate / garbage inputs.

Contract (see tests/gen/test_billing.py):
  * expose exactly one ``register(t)``
  * emit assertions only through t.check / t.eq / t.near / t.has
"""

from __future__ import annotations


def register(t):
    r = t.roles

    # ---- ground-truth, derived straight from the module's own tables -------
    ROLES = r.ROLES  # key -> (level, label, desc)
    PAGES = r.PAGE_MIN_LEVEL  # page label -> min level
    CAPS = r.CAP_MIN_LEVEL  # capability -> min level

    # known roles ordered by ascending privilege
    known = sorted(ROLES.keys(), key=lambda k: ROLES[k][0])

    # a pool of "roles" including bogus / degenerate ones (all should be lvl 0)
    bogus = [
        "",
        "guest",
        "ADMIN",
        "Receptionist",
        "root",
        "superuser",
        "none",
        "0",
        "user",
        "Admin ",
        " admin",
        "tech",
        None,
        "manager",
        "Technician",
        "RECEPTIONIST",
        "admin\n",
        "\tadmin",
        "owner",
        "supervisor",
        "lab",
        "doctor",
        "nurse",
        "billing",
        "viewer",
        "anonymous",
        "system",
        "operator",
        "staff",
        "  ",
        "00admin",
        "admin1",
        "re ceptionist",
        "Lab Technician",
        "Administrator",
    ]

    t.section("level(): known roles, exact values & ordering")
    # exact level values for every known role
    for k, (lvl, label, _desc) in ROLES.items():
        t.eq(r.level(k), lvl, f"level({k!r})")
        t.check(r.level(k) >= 1, f"known role has positive level: {k}")

    # bogus / unknown roles always map to level 0
    for b in bogus:
        t.eq(r.level(b), 0, f"level(bogus={b!r})==0")
        t.check(r.level(b) < ROLES[known[0]][0], f"bogus below lowest known role: {b!r}")

    t.section("level(): strict ascending hierarchy")
    # the documented strict hierarchy: each higher key has a strictly higher level
    for lo, hi in zip(known, known[1:], strict=False):
        t.check(r.level(lo) < r.level(hi), f"strict order {lo}<{hi}: {r.level(lo)}<{r.level(hi)}")
    # documented concrete ordering: receptionist < technician < admin
    t.check(
        r.level("receptionist") < r.level("technician") < r.level("admin"),
        "receptionist<technician<admin",
    )
    t.eq(r.level("receptionist"), 2, "receptionist level==2")
    t.eq(r.level("technician"), 3, "technician level==3")
    t.eq(r.level("admin"), 5, "admin level==5")

    t.section("role_label()")
    for k, (_lvl, label, _desc) in ROLES.items():
        t.eq(r.role_label(k), label, f"role_label({k!r})")
    # unknown non-empty role echoes itself; empty/None -> 'User'
    for b in bogus:
        want = b if b else "User"
        t.eq(r.role_label(b), want, f"role_label(bogus={b!r})")

    all_roles = known + bogus

    # ======================================================================
    # can_view_page matrix: every role x every page (+ unknown pages)
    # ======================================================================
    t.section("can_view_page(): full role x page matrix")
    unknown_pages = [
        "Bogus Page",
        "",
        "settings",
        "DASHBOARD",
        "Reception",
        "Random",
        "xyz",
        "  Logs  ",
        "logs",
        "Account",
        "Microbiology ",
        "Reception/Billing",
        "Test catalog",
        "doctors",
        "Worklist",
        "Results",
        "Trash",
        "Audit",
    ]
    for role in all_roles:
        lvl = r.level(role)
        for page, minlvl in PAGES.items():
            got = r.can_view_page(role, page)
            want = lvl >= minlvl
            t.eq(got, want, f"can_view_page({role!r},{page!r})")
            # admin (top role) can always view every defined page
            if role == "admin":
                t.check(got, f"admin sees page {page!r}")
        # unknown pages default to min level 1 -> visible iff level>=1
        for page in unknown_pages:
            got = r.can_view_page(role, page)
            want = lvl >= 1
            t.eq(got, want, f"can_view_page unknown ({role!r},{page!r})")

    # ======================================================================
    # can() matrix: every role x every capability (+ unknown caps)
    # ======================================================================
    t.section("can(): full role x capability matrix")
    unknown_caps = [
        "",
        "fly",
        "edit",
        "DELETE",
        "manage_user",
        "discount",
        "edit_catalogue",
        "admin",
        "superpower",
        None,
        "Edit_catalog",
        "manage_backup",
        "apply_discounts",
        "editsettings",
        "create",
        "remove",
        "view",
        "read",
        "write",
        "backup",
        "restore",
        "users",
        "settings",
        "edit catalog",
        " delete",
        "delete ",
    ]
    for role in all_roles:
        lvl = r.level(role)
        for cap, minlvl in CAPS.items():
            got = r.can(role, cap)
            want = lvl >= minlvl
            t.eq(got, want, f"can({role!r},{cap!r})")
        # unknown capabilities default to min level 99 -> never permitted
        for cap in unknown_caps:
            got = r.can(role, cap)
            t.check(not got, f"unknown cap denied ({role!r},{cap!r})")

    # ======================================================================
    # privilege-ordering invariant: monotonicity across the full matrix.
    # If a lower-or-equal-level role can do X, every higher-level role must too.
    # ======================================================================
    t.section("monotonicity: page visibility never decreases with level")
    targets = list(PAGES.keys()) + unknown_pages
    for ra in all_roles:
        for rb in all_roles:
            if r.level(ra) <= r.level(rb):
                for page in targets:
                    if r.can_view_page(ra, page):
                        t.check(r.can_view_page(rb, page), f"mono page {page!r}: {ra}->{rb}")

    t.section("monotonicity: capabilities never decrease with level")
    cap_targets = list(CAPS.keys()) + unknown_caps
    for ra in all_roles:
        for rb in all_roles:
            if r.level(ra) <= r.level(rb):
                for cap in cap_targets:
                    if r.can(ra, cap):
                        t.check(r.can(rb, cap), f"mono cap {cap!r}: {ra}->{rb}")

    # ======================================================================
    # hard negative invariants: lower roles must NEVER do privileged actions.
    # ======================================================================
    t.section("hard denials for low-privilege roles")
    # receptionist (lvl 2) must not have any level>=3 capability or page
    for cap, minlvl in CAPS.items():
        if minlvl >= 3:
            t.check(not r.can("receptionist", cap), f"receptionist denied {cap}")
    for page, minlvl in PAGES.items():
        if minlvl >= 3:
            t.check(not r.can_view_page("receptionist", page), f"receptionist cannot see {page}")
    # technician (lvl 3) must not have any level>=4 capability or page
    for cap, minlvl in CAPS.items():
        if minlvl >= 4:
            t.check(not r.can("technician", cap), f"technician denied {cap}")
    for page, minlvl in PAGES.items():
        if minlvl >= 4:
            t.check(not r.can_view_page("technician", page), f"technician cannot see {page}")
    # bogus/unknown roles (lvl 0) must be denied EVERY capability and every
    # page whose min level exceeds 0 (i.e. all of them, min is 1).
    for b in bogus:
        for cap in CAPS:
            t.check(not r.can(b, cap), f"bogus {b!r} denied cap {cap}")
        for page in PAGES:
            t.check(not r.can_view_page(b, page), f"bogus {b!r} cannot see {page}")

    # ======================================================================
    # concrete spot checks of the documented design.
    # ======================================================================
    t.section("documented spot checks")
    # apply_discount = "manager" => technician & admin yes, receptionist no
    t.check(r.can("technician", "apply_discount"), "technician applies discount")
    t.check(r.can("admin", "apply_discount"), "admin applies discount")
    t.check(not r.can("receptionist", "apply_discount"), "receptionist cannot apply discount")
    # editing catalog / settings / delete require lvl 4 -> only admin
    for cap in ("edit_catalog", "edit_settings", "delete"):
        t.check(r.can("admin", cap), f"admin can {cap}")
        t.check(not r.can("technician", cap), f"technician cannot {cap}")
        t.check(not r.can("receptionist", cap), f"receptionist cannot {cap}")
    # users & backups require lvl 5 -> only admin
    for cap in ("manage_users", "manage_backups"):
        t.check(r.can("admin", cap), f"admin can {cap}")
        t.check(not r.can("technician", cap), f"technician cannot {cap}")
        t.check(not r.can("receptionist", cap), f"receptionist cannot {cap}")
    # Logs page is admin-only (min level 5)
    t.check(r.can_view_page("admin", "Logs"), "admin sees Logs")
    t.check(not r.can_view_page("technician", "Logs"), "technician no Logs")
    t.check(not r.can_view_page("receptionist", "Logs"), "receptionist no Logs")
    # Dashboard (min 1) visible to all real roles, not to bogus(lvl0)
    for role in known:
        t.check(r.can_view_page(role, "Dashboard"), f"{role} sees Dashboard")
    t.check(not r.can_view_page("", "Dashboard"), "empty role no Dashboard")

    # ======================================================================
    # capability vs page boundary self-consistency: a cap gated at level L
    # implies the holder also passes any page gated at <= L.
    # ======================================================================
    t.section("cross self-consistency: caps imply equal-or-lower pages")
    for role in known:
        lvl = r.level(role)
        for cap, cmin in CAPS.items():
            if r.can(role, cap):
                t.check(lvl >= cmin, f"{role} has {cap} only if level>=min")
        for page, pmin in PAGES.items():
            if r.can_view_page(role, page):
                t.check(lvl >= pmin, f"{role} sees {page} only if level>=min")
