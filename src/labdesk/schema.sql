-- LabDesk — clean application schema (SQLite)
-- Designed to preserve the legacy report-template flexibility while
-- normalising patients / receipts / results / accounting.
-- All money stored as REAL (PKR). Dates stored as ISO-8601 TEXT.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- Settings / branding (replaces legacy MyInformation)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- ---------------------------------------------------------------------------
-- Users / login (replaces the Access .mdw workgroup file)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL,
    full_name     TEXT,
    pass_hash     TEXT NOT NULL,        -- sha256(salt + password)
    salt          TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'operator',  -- admin | operator | viewer
    active        INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- ---------------------------------------------------------------------------
-- Referring doctors
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS doctors (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    code      TEXT,                     -- legacy DrID
    name      TEXT NOT NULL,
    hospital  TEXT,
    address   TEXT,
    area      TEXT,
    tel       TEXT,
    mobile    TEXT,
    active    INTEGER NOT NULL DEFAULT 1
);

-- ---------------------------------------------------------------------------
-- Report section heads (e.g. "LIVER FUNCTIONS REPORT") and report layouts
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS report_heads (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name  TEXT UNIQUE NOT NULL
);

-- ---------------------------------------------------------------------------
-- Test catalog (legacy Tests)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tests (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    legacy_no       INTEGER,            -- original TestNo (kept for traceability)
    name            TEXT NOT NULL,      -- Test Description
    charges         REAL NOT NULL DEFAULT 0,
    category        TEXT,               -- Routine | Special | X-Ray | ...
    sample_required TEXT,
    carry_out       TEXT,               -- method / instrument
    report_label    TEXT,               -- legacy "Report" free text
    after_days      INTEGER DEFAULT 0,  -- TAT in days
    report_type     TEXT,               -- legacy layout id (1..n); drives template
    report_head     TEXT,               -- section title on the printed report
    method_note     TEXT,               -- methodology / comments (legacy Rem-Com-Method)
    is_culture      INTEGER NOT NULL DEFAULT 0,
    active          INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_tests_name ON tests(name);
CREATE INDEX IF NOT EXISTS ix_tests_legacy ON tests(legacy_no);

-- ---------------------------------------------------------------------------
-- Test parameters / report lines (legacy TestParticulars)
-- part_type:  N = normal result line, L = continuation/extra-range line,
--             H = heading line, Y = yes/no, T = free text
-- A line with NULL name + a range value is a wrapped continuation of the
-- previous parameter (multiple reference ranges, phases, etc.).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS test_parameters (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    test_id      INTEGER NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
    seq          INTEGER NOT NULL DEFAULT 0,   -- preserves legacy TestPartID order
    legacy_id    INTEGER,
    part_type    TEXT NOT NULL DEFAULT 'N',
    group_head   TEXT,                         -- Part-Head
    group_head_no INTEGER DEFAULT 0,
    name         TEXT,                         -- PARTICULARS
    units        TEXT,
    superscript  TEXT,
    ref_male     TEXT,
    ref_female   TEXT,
    default_result TEXT,                       -- pre-filled value if any
    yn           INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_param_test ON test_parameters(test_id, seq);

-- ---------------------------------------------------------------------------
-- Reusable result pick-lists (legacy Combo* / ResultCombo / Remarks)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS result_templates (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT NOT NULL,              -- combo name / category
    value   TEXT NOT NULL,             -- one option
    seq     INTEGER DEFAULT 0
);

-- ---------------------------------------------------------------------------
-- Patients (deduped from legacy receipts; created on first receipt)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS patients (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT NOT NULL,
    age       INTEGER,
    age_desc  TEXT,                     -- Years/Months/Days
    sex       TEXT,
    telephone TEXT,
    address   TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS ix_patients_name ON patients(name);

-- ---------------------------------------------------------------------------
-- Receipts (legacy SampleReceipts-2) — one visit / invoice
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS receipts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    lab_no        TEXT,                 -- printed lab id / serial
    patient_id    INTEGER REFERENCES patients(id),
    doctor_id     INTEGER REFERENCES doctors(id),
    -- patient snapshot (kept on the receipt so edits to the patient record
    -- never rewrite history)
    patient_name  TEXT,
    age           INTEGER,
    age_desc      TEXT,
    sex           TEXT,
    telephone     TEXT,
    address       TEXT,
    dr_name       TEXT,
    specimen      TEXT,
    received_at   TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    report_due    TEXT,
    subtotal      REAL NOT NULL DEFAULT 0,
    discount_pct  REAL NOT NULL DEFAULT 0,
    less          REAL NOT NULL DEFAULT 0,
    net_amount    REAL NOT NULL DEFAULT 0,
    paid          REAL NOT NULL DEFAULT 0,
    due           REAL NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'pending', -- pending|in_progress|reported|delivered
    created_by    TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS ix_receipts_date ON receipts(received_at);
CREATE INDEX IF NOT EXISTS ix_receipts_status ON receipts(status);

-- ---------------------------------------------------------------------------
-- Tests ordered on a receipt (line items)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS receipt_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_id  INTEGER NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
    test_id     INTEGER NOT NULL REFERENCES tests(id),
    test_name   TEXT,                   -- snapshot
    charge      REAL NOT NULL DEFAULT 0,
    remarks     TEXT,                   -- free-text remarks printed under results
    reported    INTEGER NOT NULL DEFAULT 0,
    reported_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_items_receipt ON receipt_items(receipt_id);

-- ---------------------------------------------------------------------------
-- Entered results, one row per parameter per receipt-item
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_item_id INTEGER NOT NULL REFERENCES receipt_items(id) ON DELETE CASCADE,
    parameter_id    INTEGER REFERENCES test_parameters(id),
    -- snapshot of the line so the printed report is reproducible forever
    seq             INTEGER DEFAULT 0,
    part_type       TEXT,
    group_head      TEXT,
    name            TEXT,
    units           TEXT,
    superscript     TEXT,
    ref_text        TEXT,               -- resolved range for this patient's sex
    value           TEXT,               -- the entered result
    flag            TEXT,               -- H/L/A abnormal flag (optional)
    hidden          INTEGER NOT NULL DEFAULT 0,  -- 1 = exclude this row from the report
    UNIQUE(receipt_item_id, parameter_id)
);
CREATE INDEX IF NOT EXISTS ix_results_item ON results(receipt_item_id);

-- ---------------------------------------------------------------------------
-- Microbiology / culture (legacy CultureMain, CulSpecimen, CulRpt, Growth...)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cultures (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_item_id INTEGER REFERENCES receipt_items(id) ON DELETE CASCADE,
    specimen       TEXT,
    growth         TEXT,
    organism       TEXT,
    colony_count   TEXT,
    gram_stain     TEXT,
    zn_stain       TEXT,
    remarks        TEXT,
    reported_at    TEXT
);
CREATE TABLE IF NOT EXISTS culture_sensitivity (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    culture_id  INTEGER NOT NULL REFERENCES cultures(id) ON DELETE CASCADE,
    antibiotic  TEXT NOT NULL,
    result      TEXT             -- S / I / R
);
-- reference lists for microbiology dropdowns
CREATE TABLE IF NOT EXISTS micro_lists (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    kind  TEXT NOT NULL,         -- specimen | organism | antibiotic | growth | gram | zn
    value TEXT NOT NULL,
    seq   INTEGER DEFAULT 0
);

-- ---------------------------------------------------------------------------
-- Medicines / inventory (legacy Medicines, Stocks)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS medicines (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT NOT NULL,
    company   TEXT,
    pack      TEXT,
    price     REAL DEFAULT 0,
    qty       REAL DEFAULT 0,
    active    INTEGER NOT NULL DEFAULT 1
);

-- ---------------------------------------------------------------------------
-- Accounting (legacy BalSheet, Expenses, Due Amounts)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS expenses (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    date      TEXT NOT NULL DEFAULT (date('now','localtime')),
    head      TEXT,                     -- expense category
    detail    TEXT,
    amount    REAL NOT NULL DEFAULT 0,
    created_by TEXT
);
CREATE TABLE IF NOT EXISTS ledger (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    date      TEXT NOT NULL DEFAULT (date('now','localtime')),
    kind      TEXT NOT NULL,            -- income | expense | due_recovery
    ref_id    INTEGER,                  -- receipt id / expense id
    detail    TEXT,
    debit     REAL NOT NULL DEFAULT 0,
    credit    REAL NOT NULL DEFAULT 0
);

-- ---------------------------------------------------------------------------
-- Audit log
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    at        TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    username  TEXT,
    action    TEXT,
    detail    TEXT
);

-- Schema version marker
INSERT OR IGNORE INTO settings(key, value) VALUES ('schema_version', '1');
