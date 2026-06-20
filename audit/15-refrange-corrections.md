# Reference-range / unit corrections (validation workflow)

344 parameters validated; 39 need a change (29 range, 7 unit, 3 missing).

| Test | Parameter | Type | Conf | Current | Proposed ref (M / F) | Unit | Note |
|---|---|---|---|---|---|---|---|
| A/G Ratio | A/G Ratio | wrong_unit | high | units=%, ref=1.0 - 2.1 (M/F) | 1.0 - 2.5 |  | The albumin/globulin ratio is a dimensionless pure ratio; reporting it in '%' is clinicall |
| Alpha-MDBH | Alpha MDBH | wrong_range | high | units=U/l, ref=55 - 140 (M/F) | 72 - 182 | U/L | Alpha-HBDH (alpha-hydroxybutyrate dehydrogenase) standard adult reference range is 72–182  |
| Beta HCG | Beta HCG | wrong_unit | high | Male: < 5.0 IU/mL | Female: Up | < 5.0 / Non-pregnant: <  | mIU/mL | The reported unit 'IU/mL' is incorrect. The standard clinical unit for serum hCG is mIU/mL |
| Bilirubin Indirect (Unconjug | Bilirubin (Indirec | wrong_range | high | 0.1 - 0.7 mg/dL (both sexes) | 0.2 - 0.8 | mg/dL | Standard reference range for indirect (unconjugated) bilirubin per Tietz, Medscape, URMC,  |
| Bleeding Time | Bleeding Time | wrong_unit | high | 2 - 7 Minute / Seconds | 2 - 7 | minutes | Reference range 2–7 min is correct for the Ivy method (established standard; Medscape, Pra |
| C-4 | C-4 | wrong_range | high | 20 - 50 mg/dL | 16 - 47 | mg/dL | Current lower bound of 20 is too high — multiple authoritative sources cite the lower limi |
| C-Peptide Level | C-Peptide Level | wrong_range | high | 0.9 - 7.1 ng/mL | 0.9 - 4.0 | ng/mL | Unit ng/mL is correct. The upper limit of 7.1 ng/mL is inconsistent with established fasti |
| CA 15-3 | CA 15-3 | wrong_range | high | Less than 31.3 U/mL | < 30 | U/mL | The universal standard cutoff for CA 15-3 is <30 U/mL (Tietz, Medscape, URMC, AACC). The v |
| CBC-Blood Complete Examinati | ESR   ( WG ) | wrong_range | high | Male: 1–10 mm/hr | Female: 1–2 | 0 - 15 / 0 - 20 | mm/hr | Westergren ESR reference for adult males under 50 years is 0–15 mm/hr, not 0–10 mm/hr. An  |
| CSF For Analysis | Lymphocytes | wrong_range | high | 60 - 70 % | 40 - 80 | % | Normal CSF differential: lymphocytes 40–80%, monocytes 15–45% (Medscape, AAFP, Healthline, |
| Cardiac Enzymes (CPK, CKMB,  | LDH | wrong_range | high | 225 - 450 | 125 - 220 / 125 - 214 | U/L | The range 225–450 U/L is substantially above all published adult reference intervals for L |
| Cortisol (A.M.) | Cortisol (AM) | wrong_unit | high | 171 - 536 | 171 - 536 | nmol/L | The unit 'nM/L' is non-standard and ambiguous (nM = nanomolar = nmol/L, but the solidus fo |
| Cortisol (P.M.) | Cortisol (PM) | wrong_range | high | 50 - 350 | 80 - 270 | nmol/L | Two errors: (1) Unit 'nM/L' should be 'nmol/L'. (2) The range 50-350 nmol/L is incorrect.  |
| Cortisol (Random Urine) | Cortisol (Random U | wrong_unit | high | < 165 mIU/L | < 165 | nmol/L | mIU/L is not a recognised unit for cortisol anywhere in clinical chemistry (it is used for |
| Cyst Fluid for C/E | pH. | wrong_range | high | 7.30 - 7.40 | 7.40 - 7.60 |  | Normal transudative serous/cyst fluid pH is 7.45-7.60. The current range 7.30-7.40 corresp |
| FSH (Follicle Stimulating Ho | FSH | wrong_range | high | Male: 1.3-11.5 IU/L; Female: F | 1.3 - 11.5 / - Follicula | IU/L | Male range 1.3-11.5 IU/L is acceptable (literature: 1.3-14.5 IU/L). Follicular 2.2-15 and  |
| GH (Growth Hormone) | Growth Hormone | wrong_range | high | Both sexes: Upto: 20 mIU/L | < 2.6 / < 26 | mIU/L | Current range of 'Upto: 20 mIU/L' applied to both sexes is wrong. Using WHO IRP 98/574 con |
| Haptoglobin | (row seq 0 — unnam | missing | high |  | 16 - 220 | mg/dL | All three parameter rows for Haptoglobin have null name, units, and reference values. The  |
| Haptoglobin | (row seq 1 — unnam | missing | high |  | 16 - 220 | mg/dL | Second unnamed/blank row under Haptoglobin. Likely a label or sub-parameter row — name, un |
| Haptoglobin | (row seq 2 — unnam | missing | high |  | 16 - 220 | mg/dL | Third unnamed/blank row under Haptoglobin. All content null. Needs parameter name, unit, a |
| LFT-Liver Functions Tests | A/G Ratio | wrong_unit | high | 1.0–2.5 (units listed as %) | 1.0 - 2.5 |  | The A/G ratio is a dimensionless quantity (a pure ratio), not a percentage. The unit field |
| SGOT (AST) | SGOT (AST) | wrong_range | high | Male: 5–37 U/L | Female: 5–31  | 10 - 40 / 10 - 32 | U/L | Lower bound of 5 U/L is below all modern references. Tietz 6th ed. and WHO cite 10–40 U/L  |
| SGPT (ALT) | SGPT (ALT) | wrong_range | high | Male: 5–45 U/L | Female: 5–34  | 7 - 56 / 7 - 45 | U/L | Lower bound of 5 U/L is below established references. Tietz 6th ed. gives 7–56 U/L (male)  |
| Semen Analysis | Total Sperm Count | wrong_range | high | 15 - 120 | >= 16 | million/mL | WHO 2021 (6th edition) lower reference limit for sperm concentration is 16 million/mL (5th |
| Semen Analysis | Good Active Motile | wrong_range | high | 32 - 75 | >= 30 | % | WHO 2021 (6th edition) lower reference limit for progressive motility is 30% (reduced from |
| ALPHA 1-Anti Trypsin Level ( | Alpha-MBDH | wrong_range | medium | units=U/l, ref=55 - 140 (M/F) | 72 - 182 | U/L | The parameter name 'Alpha-MBDH' and unit 'U/l' indicate this is actually alpha-hydroxybuty |
| APTT (Activated Partial Thro | APTT | wrong_range | medium | 30 - 40 | 25 - 37 | Sec. | Mayo Clinic Laboratories reference interval is 25–37 seconds. Tietz and most authoritative |
| APTT (Activated Partial Thro | Control | wrong_range | medium | 30 - 40 | 25 - 37 | Sec. | The control value should mirror the reagent/instrument normal range. Same rationale as APT |
| Ammonia (NH3) | Ammonia (NH3) | wrong_range | medium | units=umol/L, ref=11 - 35 (M/F | 15 - 45 | umol/L | Units are correct. The current lower limit of 11 µmol/L and upper limit of 35 µmol/L are b |
| Amylase (Urine) | Urinary Amylase | wrong_unit | medium | units=AU/Hour, ref=Upto: 260 ( | Upto 17 | U/hr | The unit 'AU/Hour' is non-standard. The SI/modern unit is U/hr (or IU/hr). Standard adult  |
| CBC-Blood Complete Examinati | PCT | wrong_range | medium | 0.108–0.282 % (both sexes) | 0.19 - 0.36 | % | Plateletcrit (PCT) reference range is most commonly cited as 0.19–0.36% (HealthMatters, Do |
| Cardiac Enzymes (CPK, CKMB,  | CPK | wrong_range | medium | Male: 38 - 174 / Female: 26 -  | 39 - 308 / 26 - 192 | U/L | The upper limit for males (174 U/L) and females (140 U/L) are below widely accepted values |
| Cardiac Enzymes (CPK, CKMB,  | AST (SGOT) | wrong_range | medium | Male: 5 - 40 / Female: 5 - 32 | 10 - 40 / 9 - 32 | U/L | Tietz and most major references set the lower limit at 10 U/L for males and 9 U/L for fema |
| Cardiac Enzymes (CPK, CKMB,  | Alpha MBDH | wrong_range | medium | 55 - 140 | 72 - 182 | U/L | Alpha-hydroxybutyrate dehydrogenase (α-HBDH) reference range is published as 72–182 U/L in |
| PT (Prothrombin Time) Factor | INR | wrong_range | medium | 0.8 - 1.2 | 0.8 - 1.1 |  | Most authoritative sources (StatPearls, Mayo, Emedicine) cite the normal INR upper limit a |
| RBC's Morphology | Reticulocytes | wrong_range | medium | 0.5 - 2.5 | 0.5 - 2.0 | % | Tietz and most authoritative haematology references (Wintrobe, Dacie) cite the adult retic |
| Semen Analysis | Excellent Motile | wrong_range | medium | More Than: 60 | >= 42 | % | WHO 2021 lower reference limit for total motility (progressive + non-progressive) is 42%.  |
| T3, T4, TSH | T3 | wrong_range | medium | 0.92–2.79 nmol/L (both sexes) | 1.2 - 3.1 | nmol/L | Standard adult total T3 reference (Tietz, Medscape, WHO) is approximately 1.2–3.1 nmol/L.  |
| T3, T4, TSH | T4 | wrong_range | medium | 58–161 nmol/L (both sexes) | 58 - 140 | nmol/L | The standard adult total T4 reference range (Tietz 6th ed., Medscape) is 58–140 nmol/L (4. |
