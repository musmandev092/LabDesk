"""Classify a catalog test into a printed-report *render category*.

Pure: no Qt, no DB. Takes the ``tests`` row and its ``test_parameters`` rows
(any mapping that supports ``row[key]`` — ``sqlite3.Row`` or ``dict``) and
returns one of :data:`RENDER_CATEGORIES`. The renderer (``render.report_doc``)
calls this to pick a layout, the catalog editor uses it when a test is saved,
and the seed builder stores the result in ``tests.render_category``.

Why classify at render time (not only a stored column): catalog sync into an
existing lab DB is *additive-only* (db.connection._sync_catalog_from_seed never
rewrites a lab's own rows), so a stored ``render_category`` would stay NULL on
upgrades. Classifying from the data the renderer already reads makes the right
layout apply on both fresh and existing installs with no migration. A non-NULL
stored ``render_category`` still wins, so a lab can override a misclassification.

Categories:
  * ``numeric_tabular`` — TEST | REFERENCE | UNIT | RESULT, numeric values with
    numeric/relational ranges (CBC, LFT, RFT, electrolytes, viral load). Default.
  * ``qualitative``     — TEST | RESULT | REFERENCE, word-state results
    (Positive/Negative, Reactive/Non-Reactive, Detected/Not Detected); NO unit
    column. Serology, immunology, blood bank, qualitative PCR.
  * ``descriptive``     — PART/ORGAN | FINDINGS (wide, wrapping) + an optional
    IMPRESSION/CONCLUSION block. Ultrasound, X-ray, histopathology, cytology.
  * ``culture``         — handled by the dedicated culture renderer.
"""

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

# A reference value that carries a number/relation → treat the test as numeric,
# even if a stray word appears. Mirrors report.formatting._flag's parsing.
_NUM_RANGE = re.compile(
    r"\d\s*[-–]\s*\d|[<>]=?\s*\d|\bup\s*to\b|less than|more than|upto", re.I
)

# Imaging / anatomic-pathology signals on the report head or test name.
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
# Anatomic / narrative parameter names — two or more ⇒ a descriptive report.
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
# Word-state result vocabulary for qualitative serology / molecular results.
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
# Legacy qualitative part_type tags carried in the catalog data.
_QUAL_PTYPES = {"N/P", "N/R", "VIR", "HIV", "B"}

# Blood-bank tests report a result with NO reference column (group, cross-match,
# Coombs). Detected by test name. Standard practice: Test | Result only.
_BLOODBANK = (
    "blood group",
    "cross match",
    "cross-match",
    "crossmatch",
    "coomb",
    "rh typing",
    "compatibility",
)

# Molecular / NAAT method words — match these, NOT bare "DNA"/"RNA" (which appear
# in serology like anti-dsDNA). A qualitative PCR → Detected/Not Detected.
_MOLECULAR = ("pcr", "genotyp", "viral load", "real-time", "real time", "naat")

# Obstetric / antenatal ultrasound — a biometry table (Parameter | Normal | Unit |
# Result) + impression, rather than the plain organ-narrative of an abdominal scan.
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

    # 1. Blood bank — result-only, no reference column.
    if any(k in tname for k in _BLOODBANK):
        return "blood_bank"

    # 1b. Obstetric ultrasound — biometry table (measurements + units) + impression,
    #     checked before the generic descriptive-imaging rule below.
    if any(k in tname for k in _OBSTETRIC) or any(k in head for k in _OBSTETRIC):
        return "obstetric"

    # 2. Descriptive / imaging / narrative — strong head/name signal wins outright.
    if any(k in head for k in _DESC_HEAD) or any(k in tname for k in _DESC_HEAD):
        return "descriptive"
    if sum(k in names for k in _DESC_NAME) >= 2 and not any_unit and not any_numref:
        return "descriptive"

    # 2. Qualitative — word-state results, no real units, no numeric ranges.
    if (ptypes & _QUAL_PTYPES) and not any_unit and not any_numref:
        return "qualitative"
    if (not any_unit) and (not any_numref) and any(w in refs for w in _QUAL_WORDS):
        return "qualitative"

    # 3. Molecular / PCR — a Detected/Not-Detected NAAT result (no unit, no numeric
    #    range) reads as qualitative + an interpretation block. Quantitative viral
    #    load (carries a unit / numeric range) falls through to the numeric grid.
    #    Matched on method words only ("pcr", "genotyp"…), NOT bare "DNA"/"RNA", so
    #    anti-dsDNA and similar serology are not misrouted.
    if (not any_unit) and (not any_numref) and any(k in tname for k in _MOLECULAR):
        return "qualitative"

    # 4. Default — the numeric tabular grid.
    return "numeric_tabular"


def category_for_test(con: object, test_id: int) -> str:
    """Convenience: classify a test by id using a live connection. Honours a
    non-NULL ``tests.render_category`` override, else classifies from the data."""
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
