"""Generator — services layer (extracted business logic).

Source under test:
  src/labdesk/services/billing.py  :: compute_bill_totals, get_active_promo_discount
  src/labdesk/services/receipts.py :: void_receipt, mark_receipt_delivered

These assert the EXTRACTED functions reproduce the views' original inline
arithmetic / SQL byte-for-byte:

  * compute_bill_totals in BOTH rounding modes, checked against independently
    recomputed expected values AND against the old inline formulas:
      - reception  (round_to_paisa=False):  net = max(0, sub - sub*pct/100), sub = sum
      - receipts   (round_to_paisa=True):   sub = round(sum,2);
                                            net = round(max(0, sub - sub*pct/100), 2);
                                            due/change rounded to 2 dp
  * get_active_promo_discount: pct read, 0..100 clamp, promo_until past/future/
    blank/invalid handling.
  * void_receipt / mark_receipt_delivered: row columns + audit_log row written;
    ledger reversal only when paid>0.
"""

from __future__ import annotations

from labdesk.services import billing
from labdesk.services import receipts as receipts_svc


# ---- old inline formulas (copied verbatim from the views pre-extraction) ----
def _old_reception(items, pct, paid):
    sub = sum(c["charge"] for c in items)
    disc = sub * pct / 100.0
    net = max(0.0, sub - disc)
    due = max(0.0, net - paid)
    change = max(0.0, paid - net)
    return sub, net, due, change


def _old_receipts(items, pct, paid):
    sub = round(sum(c["charge"] for c in items), 2)
    net = round(max(0.0, sub - sub * pct / 100.0), 2)
    due = round(max(0.0, net - paid), 2)
    change = round(max(0.0, paid - net), 2)
    return sub, net, due, change


def _items(charges):
    return [{"charge": c} for c in charges]


def _audit_count(t, action, needle=None):
    if needle is None:
        return t.con.execute("SELECT COUNT(*) FROM audit_log WHERE action=?", (action,)).fetchone()[
            0
        ]
    return t.con.execute(
        "SELECT COUNT(*) FROM audit_log WHERE action=? AND detail LIKE ?",
        (action, f"%{needle}%"),
    ).fetchone()[0]


def register(t):
    # ========================================================================
    # compute_bill_totals — both rounding modes
    # ========================================================================
    t.section("services.billing.compute_bill_totals (reception, round_to_paisa=False)")
    CARTS = [
        [],
        [100],
        [0],
        [50, 50],
        [333.33],
        [333.33, 666.67],
        [100, 250, 4999],
        [0.01, 0.01, 0.01],
        [123456.78],
        [10, 20, 30, 40, 50],
        [999.999],
    ]
    PCTS = [0, 5, 10, 12.5, 20, 30, 33, 50, 75, 100]

    for charges in CARTS:
        items = _items(charges)
        raw_sub = sum(charges)
        for pct in PCTS:
            for paid in [0, raw_sub / 3, raw_sub / 2, raw_sub, raw_sub + 1, raw_sub + 500]:
                # --- reception mode: round_to_paisa=False -------------------
                d = billing.compute_bill_totals(items, pct, paid, round_to_paisa=False)
                e_sub, e_net, e_due, e_change = _old_reception(items, pct, paid)
                tag = f"recv charges={charges} pct={pct} paid={paid:.4f}"
                t.near(d["subtotal"], e_sub, f"sub == sum {tag}")
                t.near(d["net"], e_net, f"net == old formula {tag}")
                t.near(d["due"], e_due, f"due == old formula {tag}")
                t.near(d["change"], e_change, f"change == old formula {tag}")
                t.near(d["discount"], e_sub - e_net, f"discount == sub-net {tag}")
                t.near(d["paid"], paid, f"paid echoed {tag}")
                # independent invariants
                t.check(d["net"] <= d["subtotal"] + 1e-9, f"net<=sub {tag}")
                t.check(d["due"] >= -1e-9 and d["change"] >= -1e-9, f"due/change>=0 {tag}")
                t.check(
                    not (d["due"] > 1e-6 and d["change"] > 1e-6),
                    f"never due AND change {tag}",
                )
                # NOT rounded in reception mode: net is the raw float
                t.near(
                    d["net"],
                    max(0.0, raw_sub - raw_sub * pct / 100.0),
                    f"net unrounded {tag}",
                )

    t.section("services.billing.compute_bill_totals (receipts, round_to_paisa=True)")
    for charges in CARTS:
        items = _items(charges)
        for pct in PCTS:
            r_sub = round(sum(charges), 2)
            for paid in [0, r_sub / 3, r_sub / 2, r_sub, r_sub + 1, r_sub + 500]:
                d = billing.compute_bill_totals(items, pct, paid, round_to_paisa=True)
                e_sub, e_net, e_due, e_change = _old_receipts(items, pct, paid)
                tag = f"rcpt charges={charges} pct={pct} paid={paid:.4f}"
                t.near(d["subtotal"], e_sub, f"sub == round(sum,2) {tag}")
                t.near(d["net"], e_net, f"net == old rcpt formula {tag}")
                t.near(d["due"], e_due, f"due == old rcpt formula {tag}")
                t.near(d["change"], e_change, f"change == old rcpt formula {tag}")
                t.near(d["discount"], e_sub - e_net, f"discount == sub-net {tag}")
                # all money values are 2-dp stable in this mode
                t.near(round(d["subtotal"], 2), d["subtotal"], f"sub 2dp {tag}")
                t.near(round(d["net"], 2), d["net"], f"net 2dp {tag}")
                t.near(round(d["due"], 2), d["due"], f"due 2dp {tag}")
                t.near(round(d["change"], 2), d["change"], f"change 2dp {tag}")
                t.check(d["net"] <= d["subtotal"] + 1e-9, f"net<=sub {tag}")
                t.check(
                    not (d["due"] > 1e-6 and d["change"] > 1e-6),
                    f"never due AND change {tag}",
                )

    # the two modes must AGREE on net for whole-rupee carts (no rounding ambiguity)
    t.section("services.billing.compute_bill_totals (mode equivalence on whole rupees)")
    for charges in [[100], [1000, 250], [4999, 1], [50, 50, 50]]:
        for pct in PCTS:
            a = billing.compute_bill_totals(_items(charges), pct, 0, round_to_paisa=False)
            b = billing.compute_bill_totals(_items(charges), pct, 0, round_to_paisa=True)
            tag = f"charges={charges} pct={pct}"
            t.near(a["subtotal"], b["subtotal"], f"sub agrees {tag}")
            t.near(a["net"], b["net"], f"net agrees {tag}")

    # ========================================================================
    # get_active_promo_discount
    # ========================================================================
    t.section("services.billing.get_active_promo_discount (pct + clamp + until)")

    def _set(key, val):
        t.db.set_setting(t.con, key, val)

    import datetime

    today = datetime.date.today()
    future = (today + datetime.timedelta(days=30)).isoformat()
    past = (today - datetime.timedelta(days=1)).isoformat()
    todaystr = today.isoformat()

    # pct read, no until → returned as-is (clamped)
    _set("promo_until", "")
    for raw, expect in [
        ("0", 0.0),
        ("5", 5.0),
        ("12.5", 12.5),
        ("100", 100.0),
        ("150", 100.0),  # clamp high
        ("-10", 0.0),  # clamp low
        ("", 0.0),
        ("abc", 0.0),  # non-numeric → 0
    ]:
        _set("promo_discount_pct", raw)
        got = billing.get_active_promo_discount(t.con)
        t.near(got, expect, f"promo pct raw={raw!r} no-until")

    # until handling
    _set("promo_discount_pct", "20")
    _set("promo_until", future)
    t.near(billing.get_active_promo_discount(t.con), 20.0, "promo active when until in future")
    _set("promo_until", todaystr)
    t.near(billing.get_active_promo_discount(t.con), 20.0, "promo active on the until day itself")
    _set("promo_until", past)
    t.near(billing.get_active_promo_discount(t.con), 0.0, "promo expired when until in past")
    _set("promo_until", "not-a-date")
    t.near(
        billing.get_active_promo_discount(t.con),
        20.0,
        "invalid until date ignored (promo stays active)",
    )
    _set("promo_until", "")
    t.near(billing.get_active_promo_discount(t.con), 20.0, "blank until → promo active")
    # clamp still applies with an until present
    _set("promo_discount_pct", "200")
    _set("promo_until", future)
    t.near(billing.get_active_promo_discount(t.con), 100.0, "clamp high with future until")

    # reset promo so it can't leak into other modules
    _set("promo_discount_pct", "0")
    _set("promo_until", "")

    # ========================================================================
    # receipts_svc.void_receipt
    # ========================================================================
    t.section("services.receipts.void_receipt (row + audit + ledger reversal)")
    for paid in [0.0, 1000.0, 250.0]:
        rid = t.make_receipt(sub=1000.0, paid=paid, with_results=False)
        lab_no = t.con.execute("SELECT lab_no FROM receipts WHERE id=?", (rid,)).fetchone()[
            "lab_no"
        ]
        a0 = _audit_count(t, "receipt_voided")
        l0 = t.con.execute(
            "SELECT COUNT(*) FROM ledger WHERE ref_id=? AND kind='void'", (rid,)
        ).fetchone()[0]

        receipts_svc.void_receipt(t.con, rid, "duplicate entry", "voider")

        row = t.con.execute(
            "SELECT voided, void_reason, voided_by, voided_at, due FROM receipts WHERE id=?",
            (rid,),
        ).fetchone()
        t.eq(row["voided"], 1, f"voided flag set paid={paid}")
        t.eq(row["void_reason"], "duplicate entry", f"void_reason stored paid={paid}")
        t.eq(row["voided_by"], "voider", f"voided_by stored paid={paid}")
        t.eq(row["due"], 0, f"due zeroed paid={paid}")
        t.check(bool(row["voided_at"]), f"voided_at timestamp set paid={paid}")
        # audit row written, referencing the lab_no
        t.eq(_audit_count(t, "receipt_voided"), a0 + 1, f"one void audit row paid={paid}")
        t.check(
            _audit_count(t, "receipt_voided", lab_no) >= 1,
            f"void audit names lab_no paid={paid}",
        )
        # ledger reversal ONLY when paid>0
        l1 = t.con.execute(
            "SELECT COUNT(*), COALESCE(SUM(debit),0) FROM ledger WHERE ref_id=? AND kind='void'",
            (rid,),
        ).fetchone()
        if paid > 0:
            t.eq(l1[0], l0 + 1, f"ledger void row written paid={paid}")
            t.near(float(l1[1]), paid, f"ledger debit == paid paid={paid}")
        else:
            t.eq(l1[0], l0, f"no ledger row when unpaid paid={paid}")

    # ========================================================================
    # receipts_svc.mark_receipt_delivered
    # ========================================================================
    t.section("services.receipts.mark_receipt_delivered (status + audit)")
    rid = t.make_receipt(sub=500.0, paid=500.0, with_results=True, status="reported")
    lab_no = t.con.execute("SELECT lab_no FROM receipts WHERE id=?", (rid,)).fetchone()["lab_no"]
    a0 = _audit_count(t, "report_delivered")
    receipts_svc.mark_receipt_delivered(t.con, rid, "deliverer")
    row = t.con.execute(
        "SELECT status, delivered_by, delivered_at FROM receipts WHERE id=?", (rid,)
    ).fetchone()
    t.eq(row["status"], "delivered", "status set to delivered")
    t.eq(row["delivered_by"], "deliverer", "delivered_by stored")
    t.check(bool(row["delivered_at"]), "delivered_at timestamp set")
    t.eq(_audit_count(t, "report_delivered"), a0 + 1, "one delivered audit row")
    t.check(
        _audit_count(t, "report_delivered", lab_no) >= 1,
        "delivered audit names lab_no",
    )

    # fallback detail when lab_no is blank → '#<rid>'
    rid2 = t.make_receipt(sub=300.0, paid=0.0, with_results=True, status="reported")
    t.con.execute("UPDATE receipts SET lab_no='' WHERE id=?", (rid2,))
    t.con.commit()
    a1 = _audit_count(t, "report_delivered")
    receipts_svc.mark_receipt_delivered(t.con, rid2, "deliverer")
    t.eq(_audit_count(t, "report_delivered"), a1 + 1, "blank lab_no still audits")
    t.check(
        _audit_count(t, "report_delivered", f"#{rid2}") >= 1,
        "blank lab_no falls back to '#<rid>' in audit",
    )
