"""Machine fingerprint for node-locked licensing.

Collects up to three stable hardware/OS signals and returns them HASHED (so the
raw machine identifiers never travel in the activation request or sit in the
license file). The license records whichever signals were available at issue
time; verification (in __init__.py) tolerates ONE of them changing — so swapping
a disk or a network card doesn't lock the lab out, but copying the app to a
different machine (where none match) is refused.

Signals, in order of reliability on Linux:
  * machine_id — /etc/machine-id (set at OS install; survives hardware changes,
    needs no root). Primary anchor.
  * mac        — first non-virtual, non-loopback NIC hardware address.
  * disk       — root/first block-device serial, best-effort (may be empty
    without privileges; simply omitted when unavailable).
"""

from __future__ import annotations

import contextlib
import hashlib
from pathlib import Path

# Salt the hashes with an app-specific tag so a fingerprint can't be correlated
# with the same machine's fingerprint in some other product, and bump-able if the
# scheme ever changes.
_TAG = b"labdesk-fingerprint-v1|"


def _hash(value: str) -> str:
    return hashlib.sha256(_TAG + value.strip().encode("utf-8", "replace")).hexdigest()


def _machine_id() -> str | None:
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        with contextlib.suppress(OSError):
            text = Path(path).read_text(encoding="utf-8").strip()
            if text:
                return text
    return None


def _primary_mac() -> str | None:
    """First real NIC's MAC: skip loopback and virtual interfaces (docker/veth/
    virbr/bridges), prefer ones backed by a physical device, deterministic order."""
    net = Path("/sys/class/net")
    if not net.is_dir():
        return None
    virtual_prefixes = (
        "lo",
        "docker",
        "veth",
        "virbr",
        "br-",
        "vmnet",
        "tun",
        "tap",
        "vnet",
    )
    candidates = []
    with contextlib.suppress(OSError):
        for iface in sorted(p.name for p in net.iterdir()):
            if iface.startswith(virtual_prefixes):
                continue
            addr_file = net / iface / "address"
            with contextlib.suppress(OSError):
                mac = addr_file.read_text(encoding="utf-8").strip()
                if not mac or mac == "00:00:00:00:00:00":
                    continue
                has_device = (net / iface / "device").exists()
                candidates.append((0 if has_device else 1, iface, mac))
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][2]


def _disk_serial() -> str | None:
    """Best-effort serial of a physical block device (no root needed when the
    kernel exposes it under /sys). Returns None when nothing readable — the
    fingerprint then just relies on machine_id + mac."""
    blockdir = Path("/sys/block")
    if not blockdir.is_dir():
        return None
    skip = ("loop", "ram", "dm-", "zram", "sr", "md")
    with contextlib.suppress(OSError):
        for dev in sorted(p.name for p in blockdir.iterdir()):
            if dev.startswith(skip):
                continue
            for rel in ("device/serial", "device/wwid", "serial"):
                with contextlib.suppress(OSError):
                    val = (blockdir / dev / rel).read_text(encoding="utf-8").strip()
                    if val:
                        return val
    return None


def collect_signals() -> dict[str, str]:
    """Return {name: sha256hex} for every signal currently available on this
    machine (omitting any that can't be read)."""
    raw = {
        "machine_id": _machine_id(),
        "mac": _primary_mac(),
        "disk": _disk_serial(),
    }
    return {name: _hash(val) for name, val in raw.items() if val}


def fingerprint_code(signals: dict[str, str] | None = None) -> str:
    """A short, human-friendly code for display/quick reference (NOT the binding
    data — the request blob carries the full hashed signals). Grouped hyphen form,
    e.g. LD-9F3A-2C71-B048-5E16."""
    sig = signals if signals is not None else collect_signals()
    joined = "|".join(f"{k}={sig[k]}" for k in sorted(sig))
    digest = hashlib.sha256(_TAG + b"code|" + joined.encode()).hexdigest().upper()
    groups = [digest[i : i + 4] for i in range(0, 16, 4)]
    return "LD-" + "-".join(groups)
