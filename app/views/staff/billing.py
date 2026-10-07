"""Invoices and payments (UC-07, staff side of UC-04/UC-05)."""
import calendar
import re
from datetime import date, timedelta

from flask import flash, g, redirect, render_template, request, url_for

from ...constants import PAYMENT_METHODS
from ...db import get_db
from ...helpers import form_text, one_or_404, parse_date, parse_money, today
from ...services import attachments_for, get_invoice, invoices_for, reject_payment, verify_payment
from . import bp
from .contracts import active_contracts


@bp.route("/invoices")
def invoices():
    show = request.args.get("show", "open")
    rows = invoices_for(get_db())
    if show == "open":
        rows = [i for i in rows if i["outstanding"] > 0]
    elif show == "overdue":
        rows = [i for i in rows if i["overdue"]]
    return render_template("staff/invoices.html", invoices=rows, show=show)


@bp.route("/invoices/new", methods=["GET", "POST"])
def invoice_new():
    db = get_db()
    if request.method == "POST":
        f = request.form
        period = form_text(f, "period")
        due = parse_date(f.get("due_date"))
        rent, water, electric = parse_money(f.get("rent_fee")), parse_money(f.get("water_fee") or "0"), parse_money(f.get("electric_fee") or "0")
        c = db.execute("SELECT * FROM contract WHERE contract_id = ? AND status IN ('Active','Move-Out Requested')", (f.get("contract_id", ""),)).fetchone()
        errors = []
        if c is None:
            errors.append("Choose an active contract.")
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", period):
            errors.append("Billing period must look like 2026-10.")
        elif c is not None:
            y, m = int(period[:4]), int(period[5:])
            first, last = "%s-01" % period, "%s-%02d" % (period, calendar.monthrange(y, m)[1])
            if c["start_date"] > last or c["end_date"] < first:
                errors.append("This period is outside the contract dates (%s to %s)." % (c["start_date"], c["end_date"]))
        if due is None or None in (rent, water, electric):
            errors.append("Enter a due date and valid amounts (rent, water, electricity).")
        if not errors and db.execute("SELECT 1 FROM invoice WHERE contract_id = ? AND period = ?", (c["contract_id"], period)).fetchone():
            errors.append("An invoice for this contract and period already exists.")
        if errors:
            for e in errors:
                flash(e, "danger")
        else:
            iid = db.execute("""INSERT INTO invoice (contract_id, period, rent_fee, water_fee, electric_fee, due_date, status)
                                VALUES (?,?,?,?,?,?,?)""", (c["contract_id"], period, rent, water, electric, due.isoformat(), "Unpaid")).lastrowid
            db.commit()
            flash("Invoice #%d issued. Total %s." % (iid, rent + water + electric), "success")
            return redirect(url_for("staff.invoice_detail", invoice_id=iid))
    default = {"period": today()[:7], "due_date": (date.today() + timedelta(days=7)).isoformat(), "water_fee": "0", "electric_fee": "0",
               "contract_id": request.args.get("contract_id", "")}
    return render_template("staff/invoice_form.html", contracts=active_contracts(db), form=request.form if request.method == "POST" else default)


@bp.route("/invoices/<int:invoice_id>")
def invoice_detail(invoice_id):
    db = get_db()
    inv = get_invoice(db, invoice_id) or one_or_404(db, "SELECT 1 WHERE 0")
    pays = db.execute("""SELECT p.*, st.full_name AS verifier FROM payment p LEFT JOIN staff st ON st.staff_id = p.verified_by_staff_id
                         WHERE p.invoice_id = ? ORDER BY p.payment_id DESC""", (invoice_id,)).fetchall()
    return render_template("staff/invoice_detail.html", inv=inv, payments=pays, methods=PAYMENT_METHODS, today=today(),
                           proofs={p["payment_id"]: attachments_for(db, "payment", p["payment_id"]) for p in pays})


@bp.route("/invoices/<int:invoice_id>/record-payment", methods=["POST"])
def record_payment(invoice_id):
    """Staff received money directly (cash / counter): recorded as already Verified."""
    db = get_db()
    inv = get_invoice(db, invoice_id) or one_or_404(db, "SELECT 1 WHERE 0")
    amount, d = parse_money(request.form.get("amount"), allow_zero=False), parse_date(request.form.get("payment_date"))
    if amount is None or d is None or request.form.get("payment_method") not in PAYMENT_METHODS:
        flash("Enter a valid amount, date and method.", "danger")
    elif amount > inv["outstanding"]:
        flash("The amount is higher than the outstanding balance (%s)." % inv["outstanding"], "danger")
    else:
        pid = db.execute("""INSERT INTO payment (invoice_id, amount, payment_date, payment_method, note, status, submitted_by_user_id)
                            VALUES (?,?,?,?,?,?,?)""", (invoice_id, amount, d.isoformat(), request.form["payment_method"],
                                                         form_text(request.form, "note"), "Pending Verification", g.user["user_id"])).lastrowid
        ok, msg = verify_payment(db, pid, g.user["staff_id"])
        db.commit()
        flash(msg, "success" if ok else "danger")
    return redirect(url_for("staff.invoice_detail", invoice_id=invoice_id))


@bp.route("/payments")
def payments():
    status = request.args.get("status", "Pending Verification")
    db = get_db()
    rows = db.execute("""SELECT p.*, i.period, i.contract_id, cu.full_name AS customer_name, un.unit_no
                         FROM payment p JOIN invoice i ON i.invoice_id = p.invoice_id
                         JOIN contract c ON c.contract_id = i.contract_id JOIN customer cu ON cu.customer_id = c.customer_id
                         JOIN unit un ON un.unit_id = c.unit_id
                         WHERE ? = '' OR p.status = ? ORDER BY p.payment_id DESC""", (status, status)).fetchall()
    return render_template("staff/payments.html", payments=rows, status=status,
                           proofs={p["payment_id"]: attachments_for(db, "payment", p["payment_id"]) for p in rows})


@bp.route("/payments/<int:payment_id>/verify", methods=["POST"])
def payment_verify(payment_id):
    db = get_db()
    ok, msg = verify_payment(db, payment_id, g.user["staff_id"])
    db.commit()
    flash(msg, "success" if ok else "danger")
    return redirect(_safe_next() or url_for("staff.payments"))


@bp.route("/payments/<int:payment_id>/reject", methods=["POST"])
def payment_reject(payment_id):
    db = get_db()
    reason = form_text(request.form, "reason")
    if not reason:
        flash("Enter a reason so the customer knows what to fix.", "danger")
    else:
        ok, msg = reject_payment(db, payment_id, reason)
        db.commit()
        flash(msg, "info" if ok else "danger")
    return redirect(_safe_next() or url_for("staff.payments"))


def _safe_next():
    """Only allow redirects to pages inside this application."""
    target = request.form.get("next") or ""
    return target if target.startswith("/") and not target.startswith("//") else None


@bp.route("/payments/<int:payment_id>/receipt")
def receipt(payment_id):
    p = one_or_404(get_db(), """SELECT p.*, i.period, cu.full_name AS customer_name, un.unit_no, pr.name AS property_name,
                                st.full_name AS staff_name FROM payment p JOIN invoice i ON i.invoice_id = p.invoice_id
                                JOIN contract c ON c.contract_id = i.contract_id JOIN customer cu ON cu.customer_id = c.customer_id
                                JOIN unit un ON un.unit_id = c.unit_id JOIN property pr ON pr.property_id = un.property_id
                                LEFT JOIN staff st ON st.staff_id = p.verified_by_staff_id
                                WHERE p.payment_id = ? AND p.status = 'Verified'""", (payment_id,))
    return render_template("receipt.html", p=p)
