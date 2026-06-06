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
    "technician":   (3, "Lab Technician", "Results + approve discounts (manager)"),
    "admin":        (5, "Administrator", "Full access + settings & users"),
}

# minimum level required to see each page (by its NAV label)
PAGE_MIN_LEVEL = {
    "Dashboard": 1,
    "Reception / Billing": 2,
    "Receipts": 2,
    "Test Catalog": 2,            # visible to most; editing gated separately
    "Doctors": 2,
    "Worklist / Results": 3,
    "Microbiology": 3,
    "Accounts": 4,
    "Settings": 4,
}

# capability -> minimum level
CAP_MIN_LEVEL = {
    "edit_catalog": 4,            # add/edit tests
    "manage_users": 5,            # create/disable users
    "edit_settings": 4,
    "delete": 4,                  # destructive actions (e.g. delete doctor)
    "apply_discount": 3,          # give a bill discount (Technician/Admin = "manager")
}


def level(role: str) -> int:
    return ROLES.get(role, ("", 0))[0] if role in ROLES else 0


def role_label(role: str) -> str:
    return ROLES[role][1] if role in ROLES else (role or "User")


def can_view_page(role: str, page_label: str) -> bool:
    return level(role) >= PAGE_MIN_LEVEL.get(page_label, 1)


def can(role: str, capability: str) -> bool:
    return level(role) >= CAP_MIN_LEVEL.get(capability, 99)
