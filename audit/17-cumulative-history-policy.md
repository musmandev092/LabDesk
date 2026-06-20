# LabDesk Serial-Results Display Policy

Default posture: history is a **per-test-family capability**, not a global default. Numeric analytes trend in dated columns; interpretive/identity results do not.

---

## By render category

### 1. numeric_tabular (clinical chemistry, endocrine, hematology, coagulation)
- **Show previous?** Yes — when ≥2 dated results exist for same patient+test.
- **How many columns?** Up to **3 prior** dated values (current + last 3), newest-first. *(Tighten LabDesk's current cap of 4 down to 3.)*
- **Shape:** Dated columns (`Date | Value | flag`). Delta/arrow flag (↑/↓/flat) on delta-check analytes: creatinine, eGFR, K⁺, Na⁺, Hb/ferritin, HbA1c, LFT enzymes. Optional sparkline (not full graph) for HbA1c, glucose, eGFR/creatinine.
- **Lookback tiering:** HbA1c ~24 mo; glucose/lipids/TSH/vit D/ferritin/uric acid ~12 mo; creatinine/eGFR/urea/electrolytes/LFTs ~6–12 mo (show closely-spaced inpatient values for AKI/dialysis).
- **Do NOT show history for:** ESR, and stable CBC indices — **MCV, MCH, MCHC, RDW, RBC, differential %** (one-time by default). Outpatient walk-in single-test prints: off unless toggled.
- **Special case:** INR always offers a trend view (`Date | INR | dose`) + optional sparkline.

### 2. qualitative / serology
- **Show previous?** **No** for qualitative reactive/non-reactive markers. **Yes (limited)** for numeric titres only.
- **How many columns?** Qualitative: **zero**. Titres (VDRL/RPR, Widal O&H): last **1–2** same-method values only.
- **Shape:** Qualitative → none (print current result + S/CO or index + cutoff). Titre → inline `Previous: 1:32 (date)` or a 2–3 col dated table, plus a derived "4-fold / two-tube change" note. **Never** a multi-point graph.
- **Do NOT show history for:** HBsAg, anti-HCV, HIV screen, Typhidot IgM/IgG, Dengue NS1/IgM/IgG. A "change" here is a new diagnosis, not a trend — serial columns add false reassurance and clutter.
- **Method rule:** VDRL↔VDRL, RPR↔RPR only; titres are not interchangeable.

### 3. blood_bank (group / crossmatch / antibody screen)
- **Show previous?** **No** (display-wise). History is **verification-only**.
- **How many columns?** Zero.
- **Shape:** None. Auto-check current ABO/Rh + antibody record against history; raise a **hard alert on any discrepancy**. Print only current group + crossmatch result. The prior group is a safety rule, never a displayed trend.

### 4. descriptive_imaging (ultrasound / X-ray)
- **Show previous?** **No** columnar/serial block.
- **How many columns?** Zero.
- **Shape:** Single free-text **"Comparison / Previous study"** field — narrative compare to the **last 1** relevant prior + optional link to that report. No auto-tabulation, no trend graph.
- **Narrow opt-in exceptions:** serial obstetric biometry → growth-**percentile chart** (not report columns); thyroid/breast nodule follow-up → single inline "prior size" note.

### 5. histopath / cytology
- **Show previous?** **No** serial/columnar block.
- **How many columns?** Zero.
- **Shape:** Standalone synoptic diagnosis + a free-text **"Previous specimen"** comparison field (narrative, last 1) + optional link. Prior specimens enter via cyto-histo correlation as QA, not patient-facing columns.
- **Exception:** Cervical/Pap cytology may show a short **prior-result + screening-date line** (the one cytology test where this is justified).

### 6. molecular / viral-load (quantitative HBV-DNA, HCV-RNA — and the tumor-marker family: PSA, CEA, CA-125, CA19-9, CA15-3, AFP, quant β-hCG)
- **Show previous?** **Yes — DEFAULT ON** for the whole trendable-serial family.
- **How many columns?** Up to **4 prior** results (`Date | Result | Units`), newest-first.
- **Shape:** Dated table beneath current value + computed delta vs immediately prior: **absolute + % change** for tumor markers, **log10 change** for viral load (e.g. "−2.1 log vs 12-Mar-2026"). If ≥3 priors → small trend sparkline. Significant-change highlight (tumor marker >25% rise, CA-125 >2× nadir, viral load >1 log rise).
- **Guards:** Flag if assay/method changed (older values not directly comparable). Suppress with **"No prior result on file"** when zero priors — cleanly covers first-time/screening orders.

### 7. culture (microbiology)
- **Show previous?** **No.** Cultures are per-specimen interpretive identity+susceptibility results, not numeric analytes.
- **How many columns?** Zero.
- **Shape:** None. Each culture stands alone (organism, count, sensitivities). No dated columns, no trend.

---

## Tests that must NEVER show history (quick list)
ESR; CBC stability indices (MCV, MCH, MCHC, RDW, RBC, differential %); all qualitative serology (HBsAg, anti-HCV, HIV screen, Typhidot, Dengue NS1/IgM/IgG); blood-bank group/crossmatch (display); imaging (except obstetric/nodule exceptions); histopath/cytology (except Pap line); microbiology cultures.

---

## Implementation rule for the renderer
Each test carries a `result_type` enum {`numeric_serial`, `numeric_oneoff`, `qualitative`, `titre`, `interpretive`, `identity`} and a `show_history` flag with a per-family default. The renderer emits a dated-column history block **only** for `numeric_serial` and `titre` types, and only when `count(prior results for same patient + same analyte code + same method) ≥ 1`; it pulls up to N priors (N=3 for chemistry/hematology, N=4 for tumor-marker/viral-load, N=1–2 for titre), within the analyte's lookback window, newest-first, rendering `Date | Value | Units | flag` plus a delta/log-change annotation where defined. For `qualitative`, `interpretive`, `identity`, and `numeric_oneoff` it renders current-only; `interpretive` (imaging/histopath) additionally exposes a single free-text "Comparison to prior" field, and `identity` (blood bank) runs a silent history match that raises a hard discrepancy alert without displaying prior values. Method/assay changes invalidate cross-comparison (suppress or flag), and the whole history block is config-toggleable per lab to match house style (current-only for small labs, multi-column for accredited centres).