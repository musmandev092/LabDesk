# LabDesk Report-Rendering Decision Table

## Per-Family Decisions

| # | Test Family | (a) Real normal/reference value? | (b) Show NORMAL/REFERENCE column? | (c) Recommended columns, in order |
|---|---|---|---|---|
| 1 | **Abdominal / Pelvic / KUB Ultrasound** (radiology) | No | **No** | `Organ label` → `Finding (free-text)`; then free-text **Impression** block. Header block above; no result/unit/reference columns. |
| 2 | **Obstetric ultrasound — fetal biometry** (BPD/HC/AC/FL/EFW) | Yes (GA-dependent) | **No** (replaced by GA-equivalent/percentile) | `Parameter` → `Result (value+unit)` → `GA Equivalent (w+d)` → `Percentile (optional)`. Header: LMP, Dating/Composite GA, EDD, viability/presentation. Reference column ON **only** for the optional Doppler indices sub-section (UA PI/RI, MCA PI). |
| 3 | **Plain X-ray / radiology** (chest, bones) | No | **No** | `Study/Examination + Views`, optional `Clinical History`, free-text **Findings**, free-text **Impression/Opinion**, radiologist signature. No result/unit/reference fields. |
| 4 | **Histopathology / Cytology / FNAC** | No | **No** | Stacked labelled sections: `Specimen/Site` → `Clinical History` → `Gross/Macroscopic` → `Microscopic (or Cytology Findings)` → **Impression/Diagnosis** (emphasized) → `Comment/Note` (Bethesda/Milan category here). Sign-out footer. |
| 5 | **Qualitative serology / immunology** (Widal, Typhidot, VDRL/RPR, HBsAg, Anti-HCV, Dengue/Typhoid IgG-IgM, ICT malaria) | Yes | **Yes** (never leave blank) | `Test` → `Result` → `Reference Range / Normal Value` → `Unit/Method`. Reference auto-fills: *Non-Reactive* (HBsAg/Anti-HCV/VDRL), *Negative* (IgG/IgM, ICT), titre cutoffs for Widal, `<1.0 Non-Reactive` for semi-quant S/CO index. |
| 6 | **Blood bank** (ABO/Rh, cross-match, Coombs) | No | **No** | `Test/Investigation` → `Result`. Cross-match adds recipient/donor group, unit no., method, **Interpretation = Compatible/Incompatible**. Coombs result ± agglutination grade. If sharing the global grid, render reference cell blank (not "N/A"). |
| 7 | **Semen Analysis** (Seminogram) | Yes (WHO limits) | **Yes** (per-row optional) | `Parameter` → `Result` → `Reference Range` → `Unit`. Grouped sub-headers (Physical / Microscopic / Morphology). Reference populated for numeric rows (WHO 2021 defaults); blank/expected-descriptor for descriptive rows. Free-text **Impression** (e.g. Normozoospermia) below. |
| 8 | **Stool R/E & Urine C/E** (urinalysis) | Yes (mostly descriptive) | **Yes** (as free-text "expected normal") | `Parameter` → `Result` → `Reference/Normal` → `Unit (optional)`, under PHYSICAL / CHEMICAL / MICROSCOPIC sub-headers. Reference is a free-text string (*Nil*, *Negative*, *Pale Yellow*, *Clear*, *0-5 /HPF*, `1.005-1.030`), **not** a numeric min/max. Only Sp. Gravity & pH are true ranges. |

## Overall Rule for LabDesk Render Categories

Group every test by **render category**, not by department, and let the category — not the individual test — decide whether the reference column prints:

1. **NARRATIVE / DESCRIPTIVE** (families 1, 3, 4; obstetric US #2 is a narrative variant) → free-text, section-per-row layout (`label : body`), emphasized Impression/Diagnosis, editable "normal-default" phrases. **No** result/unit/reference columns. Data model = text/narrative result type with numeric/unit/reference fields left unpopulated.

2. **QUALITATIVE / INTERPRETIVE** (families 5 and 6) → shared 4-column grid. The reference column is **kept and pre-filled with the expected normal word** for serology (#5), but **suppressed (blank, not "N/A")** for blood bank (#6) where no normal state exists. Distinction: serology has an "expected normal" (Non-Reactive/Negative); blood-bank results (a group, a compatibility verdict) have none.

3. **SEMI-QUANTITATIVE / MIXED PANEL** (families 7 and 8) → grouped 4-column table with sub-headers; the reference column is **on**, but modelled **per-row as a free-text "normal value" string** (so it holds `Negative`, `0-5 /HPF`, `Nil`, or a true numeric range interchangeably) and may be blank on descriptive rows.

**One operative principle:** make the Reference/Normal column **conditional at the category level and free-text at the row level**. Never force a numeric min/max onto a descriptive normal, never auto-insert an empty reference cell from the catalog (gate it on category), and never render literal "N/A" clutter — a suppressed column or a blank cell, decided by category, is the correct behaviour.