# LabDesk Render-Category System — Design Document

**Author:** Lead engineer, report renderer
**Scope:** `src/labdesk/render/report_doc.py` and supporting catalog/storage
**Date:** 2026-06-20

## 0. Problem statement (grounded in current code)

`build_report()` (report_doc.py:592) dispatches on exactly one bit: `tests.is_culture`. Culture → `_draw_culture`; **everything else** → `_measure_test` + `_draw_test_table`, which is a hard-coded 4-column grid **TEST | REFERENCE RANGE | UNIT | CURRENT** (report_doc.py:337-341). Consequences observed across the 85 audited tests:

- **Descriptive/imaging (678, 679)** are crammed into a 15%-wide CURRENT column; organ-normal text lands under "REFERENCE RANGE"; `part_type='H'` CONCLUSION rows render as a subhead band with **no value cell**, so the impression is *silently dropped* (report_doc.py:281-282, 405-419).
- **Qualitative serology (44 tests)** print a permanently empty UNIT column; result text is never polarity-coloured (only numeric `_flag_arrow` fires — formatting.py:125).
- **Molecular PCR** has no Interpretation/Conclusion block at all, and "IU/mL" prints next to "Not Detected".
- `part_type` codes in the live data (`N/P`, `VIR`, `HIV`, `N/R`, `B`, `W`, `NORML`) are **all** treated as `N` — only `H` is special-cased. The schema comment claims `Y/T` exist (schema.sql:81) but the UI only offers `N/H/L` (catalog_dialogs.py:96).

---

## A. Final render-category taxonomy (5 categories)

All categories reuse the existing letterhead/patient-card header (`_report_header`, report_doc.py:110), the teal `top_rounded` title bar (report_doc.py:324), pagination loop (report_doc.py:400-477), and footer (`_report_footer`). `content_w` is the printable width after 8mm margins.

### A1. `numeric_tabular` — the existing grid (unchanged, default)

Clinical chemistry, hematology, coagulation, body-fluid panels, quantitative viral load.

| Column | Width | Align | Wrap | Notes |
|---|---|---|---|---|
| TEST | `0.26·content_w` | left | yes | sub-headers (`H`) span full width, no value cell |
| REFERENCE RANGE | `0.46·rest` where `rest = content_w − test − unit` | center | 1-2 lines (M:/F: split via `_ref_lines`) | muted |
| UNIT | `0.11·content_w` | center | no | muted |
| history…/CURRENT | `(content_w − test − ref − unit)/nval` | center, **bold** | numeric one line; text wraps | flag arrow ↑/↓ via `_flag_arrow` |

- **Units shown:** yes. **Reference shown:** yes.
- **Flags:** `H`(red ↑)/`L`(amber ↓) from `_flag` — keep.
- **Conclusion block:** none (optional Remarks + Method via `_draw_blocks_after_table`).
- **Sub-headers:** `H` rows render as `SUBHEAD_BG` bands (report_doc.py:405).

### A2. `qualitative` — 3-column, no unit column

Serology/immunology Reactive/Non-Reactive, blood group, Coombs, cross-match, drug screens, qualitative PCR.

| Column | Width | Align | Wrap | Notes |
|---|---|---|---|---|
| TEST | `0.40·content_w` | left | yes | `H` sub-headers span full width |
| RESULT | `0.35·content_w` | left/center, **bold** | yes ("Positive (1:320)") | **polarity-coloured** |
| REFERENCE | `0.25·content_w` | center | yes | header reads **"REFERENCE"** not "REFERENCE RANGE"; muted |

- **No UNIT column.** **Reference shown:** yes (word-based, e.g. "Non-Reactive").
- **Polarity colouring** (new `_polarity` helper, §E): `reactive|positive|detected|present|+ve|seen|abnormal` → `RED`; `non-reactive|negative|not detected|absent|nil|-ve` → `GREEN`/`INK`; valid blood groups & unknown free-text → `INK` (never red-flag a blood group).
- **Conclusion block:** optional. Render an **Interpretation** block only when interpretation text is present (Widal/Dengue/Typhoid combos, cross-match verdict). Never synthesize.
- **Legend/`L` rows** (e.g. Typhidot "IgG Positive only:") must NOT render as result rows → move to a footnote block (see §D, fix-type 4).

### A3. `molecular` — hybrid qualitative/quantitative + mandatory Interpretation

HBV/HCV/MTB PCR (QL and QN), HCV genotyping.

- **Sub-layout switch driven per-row by units presence:**
  - **Qualitative rows** (no unit, result Detected/Not Detected) → render via the **qualitative** 3-column path; REFERENCE = "Not Detected".
  - **Quantitative rows** (unit IU/mL) → render via **numeric_tabular** path BUT **suppress `_flag_arrow`** (a viral load is not "high"); the range column is relabelled **"MEASURING RANGE"** and holds LLoQ–ULoQ. Always carry both IU/mL and log10 in the value cell.
- **Procedure-step rows** (`- DNA Extraction`, `- Nested PCR`, `- Examination on Gel`; legacy `part_type='B'`) → **suppressed from the table** (re-tagged `L` and routed to Method footer).
- **Conclusion block:** **MANDATORY** — render an `IMPRESSION/INTERPRETATION` block (§A5 block) even if the catalog only has a method note. If no conclusion text is entered, print a placeholder hint in entry UI; never leave the section absent.
- **Method footer:** keep WHO IS traceability / LoD via existing `_draw_blocks_after_table`.

### A4. `descriptive` — 2-column Organ/Section | Findings + mandatory IMPRESSION

Ultrasound (abdominal/obstetric), X-ray, histopathology, cytology/FNAC, descriptive stool/urine, kidney-stone, morphology narratives. (Merges the standards' `descriptive_imaging` + `descriptive_narrative` — identical layout.)

| Column | Width | Align | Wrap | Notes |
|---|---|---|---|---|
| ORGAN/PART (or SECTION) | `0.28·content_w` | top-left, **bold/uppercase** | yes | label only |
| FINDINGS | `0.72·content_w` | top-left | **yes, grows row height** (`d.text_height(..., wrap=True)`) | free narrative; preserve embedded `\n` |

- **No UNIT, no REFERENCE columns** (do not draw empty headers).
- **Degenerate mode:** single-paragraph X-ray → one row with blank/"Findings" label.
- **Biometry sub-block** (obstetric): inline `LABEL = value unit (GA weeks+days)` lines inside a "Fetal Biometry" findings cell — never the numeric grid.
- **IMPRESSION block (mandatory):** §A5.
- **Flags:** none. **Pagination:** rows break across pages, header repeats, keep IMPRESSION + signature together.

### A5. Shared `IMPRESSION/CONCLUSION` block primitive (used by A3 & A4)

Full content-width, **below** the table, visually emphasised (accent left-bar + `SUBHEAD_BG`/`LIGHT` tint, reusing the Remarks-box primitive at report_doc.py:557-558):

```
┌▌ IMPRESSION                                  (bold, uppercase, TEAL_DARK) ┐
│ 1. ...wrapped body text spanning full width, numbered when multi-point... │
└───────────────────────────────────────────────────────────────────────────┘
```

- Heading synonyms accepted by category: `IMPRESSION` (imaging/histo), `INTERPRETATION` (molecular), `CONCLUSION`. Not clipped to any column. Kept-together on pagination.

---

## B. Deterministic classification rule (works for all 706)

A test maps to exactly one category. Evaluate **top to bottom; first match wins.** Inputs: `is_culture`, the **set** of `part_type` codes across its `test_parameters`, whether **any** parameter has a non-empty `units`, `report_type`, `report_head`, and test/param name tokens. This is computed once per test and stored in a new `tests.render_category` column (see §E) so it is stable and overridable.

```
def classify(test, params):
    # 0. Culture is orthogonal — existing path.
    if test.is_culture: return "culture"

    names   = " ".join(p.name or "" for p in params).lower()
    head    = (test.report_head or "").lower()
    tname   = test.name.lower()
    ptypes  = {(p.part_type or "N").upper() for p in params}
    any_unit = any((p.units or "").strip() for p in params)

    # 1. DESCRIPTIVE — imaging + narrative anatomic pathology.
    DESC_HEAD = ("ultrasound","ultrasonography","x-ray","x ray","sonograph",
                 "histopath","biopsy","cytolog","fnac","ct ","mri","doppler")
    DESC_NAME = ("ultrasound","obstetric","abdomen","specimen","gross examination",
                 "microscopic examination","impression","conclusion","organ",
                 "liver","gallbladder","placenta","fetal","foetal")
    if test.report_type in ("3","6","7"):              # legacy imaging/histo template ids
        return "descriptive"
    if any(k in head for k in DESC_HEAD): return "descriptive"
    if (sum(k in names for k in DESC_NAME) >= 2) and not any_unit:
        return "descriptive"

    # 2. MOLECULAR — PCR / NAAT / viral load / genotyping.
    MOL = ("pcr","rna","dna","viral load","genotyp","real-time","real time",
           "naat","amplificat")
    if any(k in tname or k in head for k in MOL):
        return "molecular"
    if "B" in ptypes and any(k in names for k in ("extraction","nested","gel","amplif")):
        return "molecular"

    # 3. QUALITATIVE — word-result serology/immunology/blood-bank, no real units.
    #    Trigger when NO parameter carries a unit AND the references/results are
    #    word-states, OR a legacy qualitative part_type tag is present.
    QUAL_PTYPE = {"N/P","VIR","HIV","N/R"}             # legacy qualitative markers
    QUAL_REF   = ("non-reactive","reactive","negative","positive","not detected",
                  "detected","compatible","absent")
    refs = " ".join((p.ref_male or "")+" "+(p.ref_female or "") for p in params).lower()
    if (ptypes & QUAL_PTYPE) and not any_unit:
        return "qualitative"
    if (not any_unit) and any(k in refs for k in QUAL_REF) \
       and not any(_looks_numeric_range(p.ref_male) for p in params):
        return "qualitative"

    # 4. NUMERIC_TABULAR — default for everything quantitative (chemistry,
    #    haematology, coagulation, body-fluid panels, single numeric analytes).
    return "numeric_tabular"
```

**Helpers:** `_looks_numeric_range(ref)` = regex `\d+\s*[-–]\s*\d+` or leading `<|>|<=|>=` + number (mirrors `_flag`, formatting.py:99-121). A test with a real numeric range stays `numeric_tabular` even if a stray word appears.

**Why deterministic for all 706:** the catalog totals (single_free 382, single_param 192, culture 47, qualitative 44, numeric 26, mixed 14, imaging 1) are covered because (a) culture is `is_culture`; (b) `single_free`/`single_param` with no units + word reference fall to qualitative or numeric by rule 3/4; (c) imaging/narrative caught by rule 1 head/name/report_type; (d) PCR caught by rule 2 name. The rule **never throws** — rule 4 is the catch-all.

**Mismatch handling vs the audit:** the rule's output may differ from a one-off human assignment (e.g. body-fluid panels with `Less Than:` refs stay numeric — correct). The `render_category` column is human-overridable in the catalog UI, so the rule provides a *default seed*, and the 20 broken tests get explicit overrides.

---

## C. Per-test mapping (audited tests)

Category = the render category to route to. Severity from the audit.

| id | name | category | severity |
|---|---|---|---|
| 678 | Ultrasound-Abdominal | descriptive | broken |
| 679 | Ultrasound-Obstetrical Examination | descriptive | broken |
| 42 | ANA | qualitative | minor |
| 59 | Anti ds DNA | numeric_tabular | minor |
| 69 | Anti HBc (Total) | qualitative | minor |
| 70 | Anti HBc lgG | qualitative | minor |
| 71 | Anti HBc lgM | qualitative | minor |
| 72 | Anti HBe | qualitative | minor |
| 75 | Anti HCV (Screening) | qualitative | minor |
| 154 | Blood Group & Rh Factor | qualitative | minor |
| 211 | Coomb's Test (Direct) | qualitative | minor |
| 212 | Coomb's Test (Indirect) | qualitative | minor |
| 226 | Cross Matching | qualitative | **broken** |
| 227 | Cross Matching With Elisa | qualitative | minor |
| 228 | Cross Matching With Screening | qualitative | minor |
| 339 | Anti HAV lgG | qualitative | minor |
| 340 | Anti HAV lgM | qualitative | minor |
| 344 | HBeAg | qualitative | minor |
| 346 | HBsAg (Screening) | qualitative | minor |
| 347 | HBV DNA by PCR (QL) | molecular | **broken** |
| 348 | HBV DNA by PCR (QN) | molecular | **broken** |
| 350 | HCV Genotyping | molecular | **broken** |
| 351 | HCV RNA by PCR (QL) | molecular | **broken** |
| 352 | HCV RNA by PCR (QN) | molecular | **broken** |
| 355 | HDV Antigen | qualitative | minor |
| 357 | H. Pylori Abs (Screening) | qualitative | minor |
| 359 | Hepatitis Virological Profile | qualitative | minor |
| 363 | HIV (Aids) by ELISA | qualitative | minor |
| 364 | HIV (Aids) by Screening | qualitative | minor |
| 372 | ICT Malaria | qualitative | minor |
| 442 | Morphine Derivatives | qualitative | ok |
| 444 | MTB By PCR (QL) | molecular | minor |
| 448 | Mycodot (Screening) | qualitative | ok |
| 449 | Mycodot IgG | qualitative | minor |
| 520 | RH Antibodies | qualitative | ok |
| 550 | Stool for H.Pylori Antigen | qualitative | ok |
| 592 | TPHA (Triponema Pallidium) | qualitative | ok |
| 597 | Typhidot IgG | qualitative | **broken** |
| 598 | Typhidot IgM | qualitative | **broken** |
| 599 | Typhidot Test (IgG & IgM) | qualitative | **broken** |
| 652 | VDRL (RPR) | qualitative | **broken** |
| 671 | Anti HDV IgG | qualitative | minor |
| 672 | Anti HDV IgM | qualitative | minor |
| 675 | Pregnancy Test - Serum | qualitative | minor |
| 676 | Pregnancy Test - Urine | qualitative | minor |
| 680 | Dengue Virus (IgG & IgM) | qualitative | **broken** |
| 699 | TB Screening | qualitative | minor |
| 333 | HCV RNA REAL-TIME PCR (QN) | molecular (numeric sub) | minor |
| 334 | HBV DNA REAL-TIME PCR (QL) | molecular (qual sub) | minor |
| 335 | HBV DNA REAL-TIME PCR (QN) | molecular (numeric sub) | ok |
| 700 | HCV RNA REAL-TIME PCR (QUALITATIVE) | molecular (qual sub) | minor |
| 21 | Acid Phosphatase | numeric_tabular | minor |
| 110 | APTT | numeric_tabular | ok |
| 115 | Ascitic Fluid For Analysis (C/E) | numeric_tabular | minor |
| 159 | Breast Milk for C/E | numeric_tabular | **broken** |
| 190 | Cardiac Enzymes (CPK,CKMB,SGOT,LDH) | numeric_tabular | minor |
| 203 | Cholesterol | numeric_tabular | minor |
| 229 | CRP | numeric_tabular | **broken** |
| 232 | CSF For Analysis | numeric_tabular | **broken** |
| 256 | Cyst Fluid for C/E | numeric_tabular | minor |
| 267 | DLC | numeric_tabular | minor |
| 303 | Fluid For C/E | numeric_tabular | minor |
| 331 | GTT | numeric_tabular | minor |
| 338 | Haptoglobin | numeric_tabular | **broken** |
| 354 | HDL (Cholesterol) | numeric_tabular | ok |
| 356 | Helicobacter Pylori Abs (lgG,IgM) | qualitative | minor |
| 390 | Joint Fluid For Analysis | numeric_tabular | minor |
| 397 | Kidney Stone for Analysis | descriptive | minor |
| 420 | Lipid Profile | numeric_tabular | minor |
| 426 | Mantoux Test (Heafs Test) | qualitative | minor |
| 469 | Peritoneal Fluid For Analysis | numeric_tabular | minor |
| 486 | Pleural Fluid For Analysis | numeric_tabular | minor |
| 503 | PT (Prothrombin Time) Factor-II | numeric_tabular | minor |
| 515 | RBC's Morphology | numeric_tabular | minor |
| 527 | Semen Analysis | numeric_tabular | minor |
| 531 | Serum Electrolytes | numeric_tabular | minor |
| 547 | Stool For C/E | numeric_tabular | minor |
| 574 | T3, T4, TSH | numeric_tabular | minor |
| 587 | Torch Profile | qualitative | **broken** |
| 621 | Urine Complete Examination | numeric_tabular | minor |
| 660 | WBC's Morphology | numeric_tabular | **broken** (wrong params) |
| 683 | CBC-Blood Complete Examination | numeric_tabular | minor |
| 684 | LFT | numeric_tabular | minor |
| 685 | RFT | numeric_tabular | ok |
| 701 | 17-Ketogenic Steroids | numeric_tabular | **broken** (placeholder data) |

20 broken: 226, 347, 348, 350, 351, 352, 597, 598, 599, 652, 680, 587, 159, 229, 232, 338, 660, 701, 678, 679.

---

## D. Prioritized DATA-FIX list (grouped by fix type)

Renderer changes (§E) fix layout; these fixes repair **catalog data** the renderer cannot infer. Ordered most impactful first.

### Fix-type 1 — STRUCTURALLY BROKEN: missing/placeholder result row (cannot produce a report) — **CRITICAL**
1. **338 Haptoglobin** — all 3 param rows null (no name/units/ref). Rebuild one row: `Haptoglobin | result | mg/dL | 36–195`. Renders "No result entered." until fixed.
2. **701 17-Ketogenic Steroids** — 7 stub rows (`c`,`cc`,…), junk units (`cal`,`nl`,`cm`), wrong ref `5-9`. Replace with one row: `17-Ketogenic Steroids | result | mg/24 hr | M: 5–23 / F: 3–15`.
3. **226 Cross Matching** — compatibility verdict row absent (only an `H` "CROSS MATCHING" band). Add an `N` row `Cross-match | Result | — | Compatible` so the verdict can be entered/printed.
4. **660 WBC's Morphology** — all params are RBC descriptors copied from 515. Replace with true WBC morphology params (Toxic Granulation, Left Shift, Hypersegmentation, Blasts, Atypical Lymphocytes, Bands), ref "Nil/Absent".
5. **229 CRP** — duplicate analyte: delete the phantom `-` row (seq 2), keep one `C-Reactive Protein` row, standardise ref to `< 6` mg/L, set `part_type='N'`.

### Fix-type 2 — mis-tagged `part_type` (rows render wrong / drop content) — **HIGH**
6. **678, 679** — CONCLUSION/IMPRESSION currently `part_type='H'` (renders as subhead band, value dropped). After §E these become a typed **conclusion** row, but the catalog row must be re-tagged from `H` → `C` (new conclusion type) or `N`.
7. **PCR procedure steps** (347, 348, 350, 351, 352, 444, 333, 334, 335, 700) — `part_type='B'` / `L`-with-name steps (`- DNA Extraction`, `- Nested PCR`, `- Examination on Gel`, `METHODOLOGY::`) must be re-tagged `L` (note-only, suppressed) so they leave the result table; their text belongs in `method_note`.
8. **Legend `L`/named rows** (597, 598, 599, 680, 426, 652) — interpretation keys ("IgG Positive only:", etc.) render as orphan rows. Re-tag so name+no-value `L` rows are suppressed from the grid and emitted as a footnote (renderer change in §E covers suppression; data fix = ensure they are `L` with the legend text in `group_head`/`method_note`).
9. **Separator `-` rows** (226, 227, 228, 652) — `L`/`N` rows named `-` print as empty noise rows; delete or re-tag `L`.

### Fix-type 3 — wrong/misleading reference or unit content — **MEDIUM (patient-safety first)**
10. **232 CSF — Lymphocytes ref `60-70%`** is the *blood* DLC range, clinically wrong for CSF. **Patient-safety: fix first in this group.** Set to CSF-appropriate (`<5 cells/cmm`, differential only when raised).
11. **587 Torch Profile** — refs `Non-Reactive ( < 1.0 Index )` cause `_flag` to amber-flag *normal* results (it matches the embedded `< 1.0`). Route to qualitative (§E suppresses flags) AND/OR strip the `< 1.0` from the ref. units `Index` → drop (qualitative).
12. **159 Breast Milk** — `units='White'` on Colour and `units='LEFT'`/`'00 ml'` misused as data. Move side to a name/`N` row; clear bogus units.
13. **652 VDRL** — long false-positive disclaimers sit in `ref_male`; set ref to `Non-Reactive`, move disclaimers to `method_note`.
14. **Unit casing batch** (59 `IU/ml`, 190 `U/I`→`U/L`, 203/354 `mg/dl`, 574 `mlU/L`→`mIU/L`, 469/486 `G/dl`→`g/dL`, 531 names `Bicorbonate`/`Potassium (K+}`, 684 A/G Ratio `%`→blank) — cosmetic, batch-correctable via one SQL pass.
15. **`Upto:`/`Less Than:`/`More Than:` refs** (21, 115, 469, 486, 527, 547, 229) — not parsed by `_flag` regex (formatting.py:102-121 expects `< / > / a-b`). Rewrite to `< x` / `> x` to restore auto-flagging. Affects ~7 panels with many rows each.

### Fix-type 4 — missing conclusion/interpretation source data — **MEDIUM**
16. Molecular tests (347–352, 333–335, 444, 700) and imaging (678, 679) need a **conclusion entry field** (delivered by §E); seed catalog with a conclusion-template hint per test.

### Fix-type 5 — cosmetic name typos — **LOW**
17. `lgG`/`lgM`→`IgG`/`IgM` (70,71,339,340), `Triponema`→`Treponema` (592), `Oders`→`Odour` (527), `Mycobactrium Tuberclusis` (699), `Bilirubine`/`Phasphatase` (684), `HCT (PVC)`→`(PCV)` (683), trailing `.` in `URINE REPORT.` (676).

---

## E. Implementation plan for `report_doc.py`

### E1. Storage / schema
1. **`tests.render_category TEXT`** (nullable). Migration in `db/_config.py`’s column-ensure path. Backfill via `classify()` (§B) in a one-off script; human-overridable in the catalog UI. `build_report` reads it; falls back to `classify()` at render time if null.
2. **Conclusion field.** Reuse `receipt_items.remarks` pattern. Add **`receipt_items.conclusion TEXT`** (printed impression/interpretation per item) — mirrors `remarks` (schema.sql:173), so it is per-result-set and reproducible. No new table needed.
3. **New `part_type` codes** in `PART_TYPES` (catalog_dialogs.py:96): add `("Conclusion / Impression", "C")` and document that `L`-with-name = footnote (not a result row). Keep `N/P,VIR,HIV,N/R,B` as **aliases** normalised at load (`_norm_ptype`).

### E2. Dispatch — replace the single branch in `build_report` (report_doc.py:625-645)
```python
cat = it_render_category(con, it)          # tests.render_category or classify()
if cat == "culture":          _draw_culture(...)
elif cat == "descriptive":    lay = _measure_descriptive(...); _draw_descriptive_table(...)
elif cat == "qualitative":    lay = _measure_qual(...);        _draw_qual_table(...)
elif cat == "molecular":      lay = _measure_molecular(...);   _draw_molecular(...)
else:                         lay = _measure_test(...);        _draw_test_table(...)   # unchanged
```
Each `_measure_*` returns the same `{title,cw,rows,head,item}` shape so the **pagination loop and `_report_footer` stay identical**. After the table (all categories) call a shared `_draw_blocks_after_table` + new `_draw_conclusion`.

### E3. New draw functions

**`_normalize_ptype(code)`** — maps `N/P,VIR,HIV,N/R,W,NORML,B`→`N` (except `B`→`L` for molecular steps), passes `H,L,C` through. Used by every `_measure_*` so legacy tags behave.

**`_polarity(value)` → `RED | GREEN | INK`** — keyword map (§A2). Used by qualitative & molecular.

**`_measure_qual` / `_draw_qual_table`** — 3 columns (0.40/0.35/0.25), header "TEST | RESULT | REFERENCE", no UNIT. RESULT bold, coloured by `_polarity`. `H`→subhead (reuse). `L`-with-name → collect into a `legend` list, render below the table as a footnote block (fixes 597/598/599/680/426/652). Reference wraps. Reuse row striping, `BORDER` rects, body-bottom break logic from `_draw_test_table`.

**`_measure_descriptive` / `_draw_descriptive_table`** — 2 columns (0.28/0.72), header "PART | FINDINGS" (or no header in degenerate mode). Both cells **top-aligned, `wrap=True`**; row height `= max(label_h, findings_h)+pad` using `d.text_height(text, f, w, wrap=True)` (the plumbing already exists — report_doc.py:290-293). Preserve embedded `\n`. `C`/conclusion rows are **excluded** here and routed to `_draw_conclusion`. Pagination identical; header repeats; keep impression together.

**`_draw_molecular`** — iterate rows; per row, if `units` present → numeric-style row with **flag suppressed** and range column titled "MEASURING RANGE"; else → qualitative-style row. `B`/`L` steps suppressed. Always followed by `_draw_conclusion` (mandatory).

**`_draw_conclusion(d, item, x0, y, heading)`** — the §A5 primitive: accent left-bar (`d.fill_rect(x0,y,px(3),h,ACCENT)`) + `LIGHT` fill (clone of report_doc.py:557-558), bold uppercase heading in `TEAL_DARK`, wrapped body from `receipt_items.conclusion`. Numbered if multi-line. Called for `descriptive` (heading "IMPRESSION") and `molecular` (heading "INTERPRETATION"). Kept-together: if it would split, push to next page before drawing.

### E4. Entry UI (worklist) for the conclusion
- In the result-entry dialog, when the item's `render_category ∈ {descriptive, molecular}`, show a multi-line **"Impression / Interpretation"** text box (alongside the existing per-item Remarks box). Persist to `receipt_items.conclusion`.
- For `descriptive` tests, each organ/section param is a normal name→value row (the FINDINGS value can be multi-line); only the impression uses the conclusion box. Re-tag the legacy `H`-CONCLUSION rows (678/679) to `C` or drop them — the impression now comes from the dedicated field.

### E5. Flag suppression
Add a `flags_enabled` boolean per category in `_draw_value` callers: `True` for numeric_tabular, **`False` for qualitative & molecular** (skip `_flag_arrow`; use `_polarity` instead). This fixes the 587 amber-on-normal bug without touching `formatting.py`.

### E6. Rollout / test
1. Land schema + `classify()` + `_normalize_ptype` (no behaviour change; numeric path still default).
2. Backfill `render_category`; spot-check against §C.
3. Add `_draw_qual_table`, then `_draw_descriptive_table`, then `_draw_molecular` + `_draw_conclusion` incrementally; render the 85 audited receipts to PDF and diff visually.
4. Apply §D data fixes (fix-types 1-2 before re-render of broken tests; 3-5 batched).
5. Regression: confirm the 26 numeric_tabular + 47 culture tests render byte-identically (they take the unchanged path).

**Key files:** renderer `src/labdesk/render/report_doc.py`; flag logic `src/labdesk/report/formatting.py`; part-type UI `src/labdesk/presentation/catalog_dialogs.py`; schema `src/labdesk/schema.sql` + column-ensure in `src/labdesk/db/_config.py`.