"""Content builders: settings accessor, header data, patient card, cumulative
history, value cells and the per-test report / culture sections + signatures.

Imports :mod:`.formatting` and :mod:`..db`.
"""

from __future__ import annotations

from .. import db
from .constants import AMBER, BODY, GREEN, RED
from .formatting import (
    _esc,
    _flag_arrow,
    _fmt_date,
    _method_block,
    _remarks_block,
    _resolve_ref,
    smart_title,
)


def _g(con):
    return lambda k, d="": db.get_setting(con, k, d)


def _user_display(con, username: str) -> str:
    """Show the staff member's full name (falling back to the username) so the
    receipt reads 'Registered by: Farhan Ali', not 'admin'."""
    username = (username or "").strip()
    if not username:
        return ""
    row = con.execute(
        "SELECT full_name FROM users WHERE username=?", (username,)
    ).fetchone()
    full = (row["full_name"] if row and row["full_name"] else "").strip()
    return full or username


# ---------------------------------------------------------------------------
# Shared header data
# ---------------------------------------------------------------------------
def _contacts(g) -> str:
    return " | ".join(
        x
        for x in [
            f"Ph: {_esc(g('phone'))}" if g("phone") else "",
            f"Mob: {_esc(g('mobile'))}" if g("mobile") else "",
            _esc(g("email")) if g("email") else "",
        ]
        if x
    )


def _regs(g) -> str:
    return " | ".join(
        x
        for x in [
            f"PHC Reg #: {_esc(g('phc_reg_no'))}" if g("phc_reg_no") else "",
            f"Lab Reg #: {_esc(g('lab_reg_no'))}" if g("lab_reg_no") else "",
        ]
        if x
    )


def _patient_pairs(r, *, include_reporting: bool = True):
    title = (r["title"] + " ") if ("title" in r.keys() and r["title"]) else ""
    mr = r["mr_no"] if "mr_no" in r.keys() else ""
    lab = r["lab_no"] or (r["case_no"] if "case_no" in r.keys() else "")
    age_sex = f"{r['age']} {r['age_desc']} / {r['sex']}"
    received = (r["received_at"] or "")[:16]
    pairs = [
        ("Patient Name", title + (r["patient_name"] or "")),
        ("Lab No.", lab),
        ("Registration Date", received),
        ("Specimen", r["specimen"]),
        ("Age / Sex", age_sex),
        ("Patient ID", mr),
        ("Referred By", r["dr_name"]),
    ]
    # The reporting date is real only once results are finalised — it is stamped
    # on receipts.reported_at then and stays stable across reprints. NEVER
    # fabricate "now": an unreported receipt or a pre-save preview must show no
    # reporting time (blank → renders as "—"). The cash receipt (a billing doc)
    # omits the field entirely via include_reporting=False.
    if include_reporting:
        rep_raw = (
            r["reported_at"] if "reported_at" in r.keys() and r["reported_at"] else ""
        )
        pairs.append(("Reporting Date", rep_raw[:16]))
    return pairs


def _patient_card(r, *, include_reporting: bool = True) -> str:
    cells = "".join(
        f'<div class="ig"><span class="l">{_esc(lbl)}</span>'
        f'<span class="v">{_esc(val) if val else "—"}</span></div>'
        for lbl, val in _patient_pairs(r, include_reporting=include_reporting)
    )
    return f'<div class="patient-card">{cells}</div>'


# ---------------------------------------------------------------------------
# Cumulative history (previous results for the same patient & test)
# ---------------------------------------------------------------------------
def _history_for_item(con, item, receipt):
    """Up to 3 previous visits' results for the SAME patient & SAME test, oldest
    first (the cumulative-report standard: current + last 3). Patients matched on
    Patient ID (the cross-visit "same no"); falls back to patient_id. Gated by the
    'show_history' lab setting. Returns (date_labels, [ {parameter_id: value}, … ])."""
    # Cumulative/serial history is a per-lab choice: accredited centres print dated
    # prior-value columns, while many smaller labs ship current-only reports. Honour
    # the 'show_history' setting (default on); off ⇒ no prior columns at all.
    if (db.get_setting(con, "show_history", "1") or "1") != "1":
        return [], []
    rk = receipt.keys()
    mr = (receipt["mr_no"] if "mr_no" in rk else None) or ""
    pid = receipt["patient_id"] if "patient_id" in rk else None
    received = receipt["received_at"] or ""
    rid = receipt["id"]
    conds, params = [], []
    if mr.strip():
        conds.append("rc.mr_no = ?")
        params.append(mr)
    if pid is not None:
        conds.append("rc.patient_id = ?")
        params.append(pid)
    if not conds:
        return [], []
    # Only FINALISED, non-voided prior visits belong in the cumulative history:
    #  * voided bills are cancelled — their numbers must never resurface;
    #  * pending / in-progress bills have no confirmed results — they would show
    #    an all-dashes column (or, worse, unverified work-in-progress values).
    # Over-fetch (LIMIT 8) then keep the newest 4 that actually carry values, so a
    # finalised visit that happened to leave this test blank can't crowd out a real
    # one or add an empty column.
    q = f"""SELECT ri.id AS item_id, rc.received_at AS dt
             FROM receipt_items ri JOIN receipts rc ON rc.id = ri.receipt_id
             WHERE ri.test_id = ? AND rc.id != ? AND ({" OR ".join(conds)})
               AND (rc.received_at < ? OR (rc.received_at = ? AND rc.id < ?))
               AND {db.NOT_VOIDED}
               AND rc.status IN ('reported', 'delivered')
             ORDER BY rc.received_at DESC, rc.id DESC LIMIT 8"""
    rows = con.execute(
        q, [item["test_id"], rid, *params, received, received, rid]
    ).fetchall()
    labels, maps = [], []
    for row in rows:  # newest → oldest from SQL
        vals = con.execute(
            "SELECT parameter_id, value FROM results WHERE receipt_item_id=?",
            (row["item_id"],),
        ).fetchall()
        vmap = {v["parameter_id"]: v["value"] for v in vals if v["value"]}
        if not vmap:
            continue  # no entered values → no empty column
        labels.append((row["dt"] or "")[:10])
        maps.append(vmap)
        if len(maps) == 3:  # cumulative-report standard: current + up to 3 prior
            break
    labels.reverse()
    maps.reverse()  # oldest → newest, left to right
    return labels, maps


def _prev_impression(con, item, receipt):
    """The most recent PRIOR finalised impression/conclusion for the same patient &
    same test (for a 'compared with previous study' note on imaging). Honours the
    'show_history' setting. Returns (date, text) or None."""
    if (db.get_setting(con, "show_history", "1") or "1") != "1":
        return None
    rk = receipt.keys()
    mr = (receipt["mr_no"] if "mr_no" in rk else None) or ""
    pid = receipt["patient_id"] if "patient_id" in rk else None
    received = receipt["received_at"] or ""
    rid = receipt["id"]
    conds, params = [], []
    if mr.strip():
        conds.append("rc.mr_no = ?")
        params.append(mr)
    if pid is not None:
        conds.append("rc.patient_id = ?")
        params.append(pid)
    if not conds:
        return None
    row = con.execute(
        f"""SELECT rc.received_at AS dt, ri.conclusion AS concl
             FROM receipt_items ri JOIN receipts rc ON rc.id = ri.receipt_id
             WHERE ri.test_id = ? AND rc.id != ? AND ({" OR ".join(conds)})
               AND (rc.received_at < ? OR (rc.received_at = ? AND rc.id < ?))
               AND {db.NOT_VOIDED} AND rc.status IN ('reported', 'delivered')
               AND COALESCE(ri.conclusion, '') != ''
             ORDER BY rc.received_at DESC, rc.id DESC LIMIT 1""",
        [item["test_id"], rid, *params, received, received, rid],
    ).fetchone()
    if not row:
        return None
    return ((row["dt"] or "")[:10], row["concl"])


def _value_cell(value, ref, *, current=False):
    if not value:
        # no result entered → a clear placeholder rather than a blank cell
        return '<td style="color:#94a3b8;">—</td>'
    arrow = _flag_arrow(value, ref)
    cls = f' class="{arrow[1]}"' if arrow else ""
    arr = f" {arrow[0]}" if arrow else ""
    style = ' style="font-size:1.1em;"' if current else ""
    return f"<td{cls}{style}>{_esc(value)}{arr}</td>"


def _report_section(con, item, sex, receipt) -> str:
    """One test: teal title bar + the cumulative results table."""
    results = con.execute(
        """SELECT res.*, tp.ref_male AS p_male, tp.ref_female AS p_female
           FROM results res LEFT JOIN test_parameters tp ON tp.id = res.parameter_id
           WHERE res.receipt_item_id=? ORDER BY res.seq""",
        (item["id"],),
    ).fetchall()
    head = con.execute(
        "SELECT report_head, method_note FROM tests WHERE id=?", (item["test_id"],)
    ).fetchone()
    title = smart_title(
        head["report_head"] if head and head["report_head"] else item["test_name"]
    )
    hist_labels, hist_maps = _history_for_item(con, item, receipt)
    ncols = 3 + len(hist_labels) + 1

    prev_ths = "".join(f"<th>{_fmt_date(l)}</th>" for l in hist_labels)
    cur_date = _fmt_date((receipt["received_at"] or "")[:10])
    thead = (
        f"<tr><th class='test'>Test</th><th>Reference Range</th><th>Unit</th>"
        f"{prev_ths}<th class='cur'>Current<br>"
        f"<span style='font-weight:400;font-size:.85em;'>{cur_date}</span></th></tr>"
    )

    rows = []
    for res in results:
        if "hidden" in res.keys() and res["hidden"]:
            continue  # parameter unticked in the entry screen → omit from the report
        if (res["part_type"] or "N").upper() == "H":
            rows.append(
                f"<tr class='subhead'><td colspan='{ncols}'>{_esc(res['name'])}</td></tr>"
            )
            continue
        val = str(res["value"]).strip() if res["value"] is not None else ""
        pid = res["parameter_id"] if "parameter_id" in res.keys() else None
        hist_cells = [m.get(pid) for m in hist_maps]
        has_hist = any(str(h).strip() for h in hist_cells if h is not None)
        # Blank current value → omit the row, unless prior results exist (then keep
        # the row for its history and label the current cell "No result").
        if not val and not has_hist:
            continue
        ref_disp, ref_flag = _resolve_ref(res, sex)
        prev = "".join(_value_cell(h, ref_flag) for h in hist_cells)
        cur = (
            "<td class='cur' style='color:#999;'>No result</td>"
            if not val
            else _value_cell(res["value"], ref_flag, current=True)
        )
        rows.append(
            f"<tr><td class='test'>{_esc(res['name'])}</td>"
            f"<td class='ref'>{ref_disp}</td>"
            f"<td class='unit'>{_esc(res['units'])}</td>{prev}{cur}</tr>"
        )
    if not rows:
        rows.append(
            f"<tr><td colspan='{ncols}' style='color:#999;'><i>No result entered.</i></td></tr>"
        )

    method = _method_block(head)
    remarks = _remarks_block(item["remarks"] if "remarks" in item.keys() else "")

    return (
        f"<div class='title-bar'>{_esc(title)}</div>"
        f"<table class='report'><thead>{thead}</thead><tbody>{''.join(rows)}</tbody></table>"
        f"{remarks}{method}"
    )


def _culture_section(con, item) -> str:
    """Microbiology Culture & Sensitivity block for a culture test."""
    head = con.execute(
        "SELECT report_head, method_note FROM tests WHERE id=?", (item["test_id"],)
    ).fetchone()
    title = smart_title(
        head["report_head"] if head and head["report_head"] else item["test_name"]
    )
    cur = con.execute(
        "SELECT * FROM cultures WHERE receipt_item_id=? ORDER BY id DESC LIMIT 1",
        (item["id"],),
    ).fetchone()
    if not cur:
        return (
            f"<div class='title-bar'>{_esc(title)}</div>"
            "<table class='report'><tbody><tr><td style='color:#999;'>"
            "<i>No culture result entered.</i></td></tr></tbody></table>"
        )
    findings = []
    for label, val in (
        ("Specimen", cur["specimen"]),
        ("Growth", cur["growth"]),
        ("Organism", cur["organism"]),
        ("Colony count", cur["colony_count"]),
        ("Gram stain", cur["gram_stain"]),
        ("ZN stain", cur["zn_stain"]),
    ):
        if val:
            findings.append(
                f"<tr><td class='test' style='width:30%;'>{_esc(label)}</td>"
                f"<td style='text-align:left;'>{_esc(val)}</td></tr>"
            )
    findings_tbl = (
        f"<table class='report'><tbody>{''.join(findings)}</tbody></table>"
        if findings
        else ""
    )

    sens = con.execute(
        "SELECT antibiotic, result FROM culture_sensitivity WHERE culture_id=? ORDER BY antibiotic",
        (cur["id"],),
    ).fetchall()
    sens_tbl = ""
    if sens:
        colour = {"S": GREEN, "I": AMBER, "R": RED}
        full = {"S": "Sensitive", "I": "Intermediate", "R": "Resistant"}
        rows = "".join(
            f"<tr><td class='test' style='text-align:left;'>{_esc(s['antibiotic'])}</td>"
            f"<td style='color:{colour.get((s['result'] or '').upper(), BODY)};font-weight:700;'>"
            f"{_esc((s['result'] or '').upper())} — {full.get((s['result'] or '').upper(), '')}</td></tr>"
            for s in sens
        )
        sens_tbl = (
            "<table class='report' style='margin-top:3mm;'><thead><tr>"
            "<th class='test'>Antibiotic</th><th>Sensitivity</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )

    rk = item.keys()
    rem_txt = ((item["remarks"] if "remarks" in rk else "") or "").strip() or (
        (cur["remarks"] or "").strip() if "remarks" in cur.keys() else ""
    )
    remarks = _remarks_block(rem_txt)
    method = _method_block(head)
    return (
        f"<div class='title-bar'>{_esc(title)}</div>"
        f"{findings_tbl}{sens_tbl}{remarks}{method}"
    )


def _signatures(con) -> str:
    g = _g(con)
    sigs = [(g(f"signatory_{i}_name"), g(f"signatory_{i}_title")) for i in (1, 2)]
    sigs = [(n, t) for n, t in sigs if n]
    if not sigs:
        return ""
    blocks = "".join(
        f"<div class='sig'><div class='line'>{_esc(n)}</div><div class='t'>{_esc(t)}</div></div>"
        for n, t in sigs
    )
    return f"<div class='sigs'>{blocks}</div>"
