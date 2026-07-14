"""Classify a catalog test into a printed-report render category."""

from __future__ import annotations

import re

RENDER_CATEGORIES = (
    "numeric_tabular",
    "qualitative",
    "blood_bank",
    "descriptive",
    "obstetric",
    "culture",
)

# A reference value with a number/relation → treat the test as numeric.
_NUM_RANGE = re.compile(
    r"\d\s*[-–]\s*\d|[<>]=?\s*\d|\bup\s*to\b|less than|more than|upto", re.I
)

_DESC_HEAD = (
    "ultrasound",
    "ultrasonography",
    "sonograph",
    "x-ray",
    "x ray",
    "xray",
    "doppler",
    "histopath",
    "biopsy",
    "cytolog",
    "fnac",
)
_DESC_NAME = (
    "liver",
    "gall bladder",
    "gallbladder",
    "kidney",
    "spleen",
    "pancreas",
    "uterus",
    "placenta",
    "fetal",
    "foetal",
    "prostate",
    "urinary bladder",
    "specimen",
    "gross",
    "microscop",
    "impression",
    "conclusion",
    "organ",
)
_QUAL_WORDS = (
    "reactive",
    "non-reactive",
    "non reactive",
    "positive",
    "negative",
    "detected",
    "not detected",
    "present",
    "absent",
    "compatible",
    "nil",
)
_QUAL_PTYPES = {"N/P", "N/R", "VIR", "HIV", "B"}

# Blood-bank tests report a result with no reference column.
_BLOODBANK = (
    "blood group",
    "cross match",
    "cross-match",
    "crossmatch",
    "coomb",
    "rh typing",
    "compatibility",
)

# Molecular/NAAT method words; excludes bare "DNA"/"RNA" (serology false positives).
_MOLECULAR = ("pcr", "genotyp", "viral load", "real-time", "real time", "naat")

_OBSTETRIC = (
    "obstetric",
    "antenatal",
    "anomaly scan",
    "growth scan",
    "dating scan",
    "biophysical profile",
)


def _get(row: object, key: str) -> object:
    """Read ``row[key]`` for a sqlite3.Row / dict, returning None when absent."""
    try:
        return row[key]  # type: ignore[index]
    except (KeyError, IndexError, TypeError):
        return None


def _looks_numeric(*texts: object) -> bool:
    return any(t and _NUM_RANGE.search(str(t)) for t in texts)


def classify(test: object, params: list) -> str:
    """Return the render category for one test given its parameter rows."""
    if _get(test, "is_culture"):
        return "culture"

    head = (str(_get(test, "report_head") or "")).lower()
    tname = (str(_get(test, "name") or "")).lower()
    names = " ".join(str(_get(p, "name") or "") for p in params).lower()
    refs = " ".join(
        f"{_get(p, 'ref_male') or ''} {_get(p, 'ref_female') or ''}" for p in params
    ).lower()
    ptypes = {(str(_get(p, "part_type") or "N")).upper() for p in params}
    any_unit = any((str(_get(p, "units") or "")).strip() for p in params)
    any_numref = any(
        _looks_numeric(_get(p, "ref_male"), _get(p, "ref_female")) for p in params
    )

    if any(k in tname for k in _BLOODBANK):
        return "blood_bank"

    if any(k in tname for k in _OBSTETRIC) or any(k in head for k in _OBSTETRIC):
        return "obstetric"

    if any(k in head for k in _DESC_HEAD) or any(k in tname for k in _DESC_HEAD):
        return "descriptive"
    if sum(k in names for k in _DESC_NAME) >= 2 and not any_unit and not any_numref:
        return "descriptive"

    if (ptypes & _QUAL_PTYPES) and not any_unit and not any_numref:
        return "qualitative"
    if (not any_unit) and (not any_numref) and any(w in refs for w in _QUAL_WORDS):
        return "qualitative"

    if (not any_unit) and (not any_numref) and any(k in tname for k in _MOLECULAR):
        return "qualitative"

    return "numeric_tabular"


def category_for_test(con: object, test_id: int) -> str:
    """Classify a test by id using a live connection; honours a stored override."""
    test = con.execute(  # type: ignore[attr-defined]
        "SELECT * FROM tests WHERE id=?", (test_id,)
    ).fetchone()
    if test is None:
        return "numeric_tabular"
    override = _get(test, "render_category")
    if override:
        return str(override)
    params = con.execute(  # type: ignore[attr-defined]
        "SELECT * FROM test_parameters WHERE test_id=? ORDER BY seq", (test_id,)
    ).fetchall()
    return classify(test, params)
