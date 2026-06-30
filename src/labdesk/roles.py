"""Role-based access control.

Each user has a role with a numeric level. A page is visible when the user's
level meets the page's minimum level. Some in-page actions (editing the catalog,
managing users) require a higher level too.
"""

from __future__ import annotations

# role key -> (level, display label, description). Strict hierarchy: each higher
# level can do everything the levels below it can, plus more.
ROLES = {
    "receptionist": (2, "Receptionist", "Billing, patients, doctors"),
    "technician": (3, "Lab Technician", "Results + approve discounts (manager)"),
    "admin": (5, "Administrator", "Full access + settings & users"),
}

# minimum level required to see each page (by its NAV label)
PAGE_MIN_LEVEL = {
    "Dashboard": 1,
    "Reception / Billing": 2,
    "Receipts / Reports": 2,
    "Test Catalog": 2,  # visible to most; editing gated separately
    "Doctors": 2,
    "Worklist / Results": 3,
    "Microbiology": 3,
    "Accounts": 4,
    "Settings": 4,
    "Logs": 5,  # audit trail — admin only
}

# capability -> minimum level
CAP_MIN_LEVEL = {
    "edit_catalog": 4,  # add/edit tests + panels
    "manage_users": 5,  # create/disable users
    "edit_settings": 4,
    "delete": 4,  # destructive actions (e.g. delete doctor)
    "apply_discount": 3,  # give a bill discount (Technician/Admin = "manager")
    "manage_backups": 5,  # back up / restore the whole DB — admin only
    # money/receipt mutations (enforced in the service+query layer, not just the UI)
    "create_receipt": 2,  # create a bill at reception — receptionist+
    "void_receipt": 4,  # void a bill + reverse the ledger — manager/admin
    "record_expense": 4,  # add an expense + ledger debit — Accounts page (manager/admin)
    "receive_payment": 2,  # record a (partial) due payment — receptionist+
    "deliver_report": 2,  # mark a report delivered — receptionist+
    # clinical result/culture mutations (Worklist + Microbiology pages, level 3)
    "enter_results": 3,  # enter/save clinical results — technician+
    "finalize_results": 3,  # release/report results & cultures — technician+
    "edit_finalized_results": 5,  # edit an already-reported report — admin only
}


def level(role: str) -> int:
    if role not in ROLES:
        return 0
    return ROLES[role][0]


def role_label(role: str) -> str:
    return ROLES[role][1] if role in ROLES else (role or "User")


def can_view_page(role: str, page_label: str) -> bool:
    return level(role) >= PAGE_MIN_LEVEL.get(page_label, 1)


def can(role: str, capability: str) -> bool:
    return level(role) >= CAP_MIN_LEVEL.get(capability, 99)


def require(role: str, capability: str) -> None:
    """Authoritative authorization gate for the data/service layer. Raises
    PermissionError unless `role` is permitted `capability`.

    The UI's can()/can_view_page() only drive widget visibility (UX). This is the
    real check that mutators call so a privileged write can't be performed by a role
    that lacks it regardless of which code path reaches the mutator. (It is
    defence-in-depth, not a barrier against someone who edits the SQLCipher DB
    directly with the shared key — see README.)"""
    if not can(role, capability):
        raise PermissionError(
            f"role {role!r} is not permitted to perform: {capability}"
        )
