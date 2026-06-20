# Plan — per-category design for special (non-tabular) tests

Goal: every test type has a **properly designed trio** — (1) printed **Output**,
(2) result-entry / **Saving** screen, (3) **Catalog parameter editing** — that
matches how that kind of test actually works. Tabular tests (CBC/LFT/RFT and
single-analyte chemistry) already share one design and are done. This plan covers
the rest. Grounded in the researched conventions in `audit/14` (international +
Pakistani labs).

Legend: ✅ done · ◔ partial · ☐ to-do.

## The category matrix

| # | Category | Output (report) | Saving (entry) | Catalog param editing | State |
|---|---|---|---|---|---|
| 1 | **numeric_tabular** (CBC, LFT, RFT, chemistry, single analyte) | Test │ Reference │ Unit │ Result (+ history cols) | Show │ Parameter │ Result │ Unit │ Reference, live flag | N/H/L rows + units + ref M/F | ✅ |
| 2 | **qualitative_serology** (Widal, Typhidot, VDRL, HBsAg, Dengue…) | Test │ Result │ Reference (no unit), polarity colour | Result **dropdown** + Reference shown | rows + ref word + result options | ◔ (no per-param options field yet) |
| 3 | **blood_bank** (Blood Group & Rh, Cross-match, Coombs) | Test │ Result **only — NO reference column** | Result dropdown (A/B/AB/O, +/–, Compatible) | rows + result options | ☐ split out of qualitative |
| 4 | **descriptive_imaging** (abdominal/KUB ultrasound, X-ray) | Organ │ Findings + Impression (narrative) | multi-line finding box, normal default pre-filled | organ rows; ref = the normal default phrase | ✅ |
| 5 | **obstetric_ultrasound** (fetal biometry) | header (LMP/GA/EDD) + Parameter │ Result │ GA-equiv │ Percentile + Impression | value boxes + GA helper | biometry params | ☐ new special type |
| 6 | **histopathology / cytology** | stacked sections: Specimen, Clinical history, Gross, Microscopy, **Impression/Diagnosis**, Note | one multi-line box per section | section rows | ☐ (now renders as imaging 2-col) |
| 7 | **molecular / PCR** (HBV/HCV/MTB qual + viral-load QN) | per-row qual/quant + mandatory **Interpretation** block | dropdown (Detected/Not Detected) or value; interpretation box | rows + steps as notes | ◔ (interpretation optional today) |
| 8 | **stool / urine R/E** | sectioned (Physical/Chemical/Microscopic) Parameter │ Result │ Reference │ Unit | grid under H subheads | already N/H rows | ◔ (works via numeric_tabular) |
| 9 | **semen_analysis** | Parameter │ Result │ Reference │ Unit (WHO numeric) | numeric grid | numeric rows | ◔ (works via numeric_tabular) |
| 10 | **culture / sensitivity** | dedicated culture renderer | microbiology screen | micro lists | ✅ |

## Cross-cutting: category-aware Catalog editor

Today `Test Catalog → edit parameters` (`presentation/catalog_dialogs.py`) offers
only part_type N/H/L and free text. Plan: make the parameter editor **adapt to the
test's render category**, and expose a **`render_category` override** on the test
dialog (currently classified only at render time). Per category the editor should
offer the right fields:

- imaging → an **organ list** with a "normal default phrase" per organ;
- qualitative/blood-bank → a **result-options** list per parameter (the dropdown
  values) + the reference word;
- histopath → a **fixed section list** (Specimen/Gross/Microscopy/Impression/Note);
- obstetric → the **biometry parameter set**;
- numeric → today's units + ref M/F (unchanged).

## Proposed implementation phases (each shippable, gated, reversible)

**Phase A — blood_bank split (small).** Add a `blood_bank` render category +
2-column Output (no reference) + entry dropdowns. Reclassify Blood Group/Rh,
cross-match, Coombs out of qualitative. Low risk.

**Phase B — histopathology sections (medium).** Add a `histopath` category with a
stacked-section Output + section entry boxes. Reclassify Biopsy/H-P/cytology/FNAC.

**Phase C — molecular interpretation (small).** Make the Interpretation block
mandatory for PCR; suppress range flags on viral-load rows; route procedure steps
to the method note.

**Phase D — obstetric biometry (larger).** New biometry Output (header + GA/percentile
table) + entry with a GA helper. Most specialised; do last.

**Phase E — category-aware Catalog editor (medium).** The cross-cutting editor work
above + the `render_category` override control, so labs can define/repair any test
type correctly from inside the app.

**Phase F — descriptive history (small).** Show the most recent prior finding under
each organ on the imaging report (radiologists compare to the last study).

## Sequencing note

This is the *plan only*. Implementation starts after sign-off; each phase lands as
its own gated commit (tests + render proofs) before the next, so nothing half-built
ships. Phases are independent — they can be reordered by priority.
