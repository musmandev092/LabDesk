"""Role-based access control: numeric level per role gates pages and capabilities."""

from __future__ import annotations

# role key -> (level, display label, description). Higher levels include lower.
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
    "Test Catalog": 2,
    "Doctors": 2,
    "Worklist / Results": 3,
    "Microbiology": 3,
    "Accounts": 4,
    "Settings": 4,
    "Logs": 5,
}

# capability -> minimum level
CAP_MIN_LEVEL = {
    "edit_catalog": 4,
    "manage_users": 5,
    "edit_settings": 4,
    "delete": 4,
    "apply_discount": 3,
    "manage_backups": 5,
    "create_receipt": 2,
    "void_receipt": 4,
    "record_expense": 4,
    "receive_payment": 2,
    "deliver_report": 2,
    "enter_results": 3,
    "finalize_results": 3,
    "edit_finalized_results": 5,
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
    """Authoritative authorization gate; raises PermissionError if not permitted."""
    if not can(role, capability):
        raise PermissionError(
            f"role {role!r} is not permitted to perform: {capability}"
        )
