"""Customer pages: UC-01, UC-04, UC-05, UC-06, UC-11, UC-12."""
from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for

from ..constants import ACTIVE_CONTRACT, PAYMENT_METHODS
from ..db import get_db
from ..helpers import form_text, one_or_404, parse_date, parse_money, today
from ..security import customer_required
from ..services import (UploadError, ZERO, attachments_for, available_units, get_invoice, has_files,
                        invoices_for, save_uploads, unit_is_free)

bp = Blueprint("customer", __name__, url_prefix="/customer")


@bp.before_request
@customer_required
def guard():
    pass


def my_contracts(db, active_only=False):
    sql = """SELECT c.*, un.unit_no, pr.name AS property_name FROM contract c
             JOIN unit un ON un.unit_id = c.unit_id JOIN property pr ON pr.property_id = un.property_id
             WHERE c.customer_id = ?"""
    args = [g.user["customer_id"]]
    if active_only:
        sql += " AND c.status IN ('Active','Move-Out Requested')"
    return db.execute(sql + " ORDER BY c.start_date DESC", args).fetchall()


def my_contract_or_404(db, contract_id):
    row = db.execute("""SELECT c.*, un.unit_no, pr.name AS property_name FROM contract c
                        JOIN unit un ON un.unit_id = c.unit_id JOIN property pr ON pr.property_id = un.property_id
                        WHERE c.contract_id = ? AND c.customer_id = ?""",
                     (contract_id, g.user["customer_id"])).fetchone()
    if row is None:
        abort(404)
    return row


def chosen_active_contract(db):
    """Contract chosen in a form; must belong to the customer and still be active."""
    try:
        cid = int(request.form.get("contract_id", ""))
    except ValueError:
        return None
    return db.execute("SELECT * FROM contract WHERE contract_id = ? AND customer_id = ? AND status IN ('Active','Move-Out Requested')",
                      (cid, g.user["customer_id"])).fetchone()


def render_with_contracts(template, db, **ctx):
    return render_template(template, contracts=my_contracts(db, True), **ctx)


# ----------------------------------------------------------- dashboard
@bp.route("/")
def dashboard():
    db = get_db()
    cid = g.user["customer_id"]
    contracts = my_contracts(db)
    invoices = invoices_for(db, "c.customer_id = ? AND c.status IN ('Active','Move-Out Requested')", (cid,))
    outstanding = sum((i["outstanding"] for i in invoices), ZERO)
    counts = {
        "requests": db.execute("SELECT COUNT(*) FROM rental_request WHERE customer_id=? AND status IN ('Waiting for Staff','Contacted','Approved')", (cid,)).fetchone()[0],
        "repairs": db.execute("""SELECT COUNT(*) FROM repair_request r JOIN contract c ON c.contract_id=r.contract_id
                                 WHERE c.customer_id=? AND r.status NOT IN ('Completed','Cancelled')""", (cid,)).fetchone()[0],
        "payments": db.execute("""SELECT COUNT(*) FROM payment p JOIN invoice i ON i.invoice_id=p.invoice_id
                                  JOIN contract c ON c.contract_id=i.contract_id
                                  WHERE c.customer_id=? AND p.status='Pending Verification'""", (cid,)).fetchone()[0],
    }
    return render_template("customer/dashboard.html", contracts=contracts, outstanding=outstanding, counts=counts,
                           overdue=[i for i in invoices if i["overdue"]])


# ----------------------------------------------------------- UC-01 rental request
@bp.route("/units")
def units():
    db = get_db()
    start, end = parse_date(request.args.get("start")), parse_date(request.args.get("end"))
    ptype = request.args.get("property_type", "")
    rows = available_units(db, start.isoformat() if start else None, end.isoformat() if end else None, ptype)
    return render_template("customer/units.html", units=rows, args=request.args, searched=bool(start and end))


@bp.route("/rental-requests/new", methods=["GET", "POST"])
def rental_request_new():
    db = get_db()
    alternatives = []
    if request.method == "POST":
        f = request.form
        start, end = parse_date(f.get("start_date")), parse_date(f.get("end_date"))
        ptype = form_text(f, "property_type") or None
        unit_id = int(f["unit_id"]) if f.get("unit_id", "").isdigit() else None
        errors = []
        s = e = None
        if not start or not end:
            errors.append("Please enter the start and end dates.")
        elif start < parse_date(today()):
            errors.append("The start date cannot be in the past.")
        elif end < start:
            errors.append("The end date must be on or after the start date.")
        if not errors:
            s, e = start.isoformat(), end.isoformat()
            if unit_id:
                available = unit_is_free(db, unit_id, s, e)
            else:
                available = bool(available_units(db, s, e, ptype))
            if not available:
                errors.append("No unit matching your request is available for these dates. "
                              "Here are other available units; you can choose one of them.")
                alternatives = available_units(db, s, e)
        if errors:
            for msg in errors:
                flash(msg, "danger")
        else:
            rid = db.execute("""INSERT INTO rental_request (customer_id, unit_id, desired_property_type, desired_start_date,
                                desired_end_date, requirements, status, created_date) VALUES (?,?,?,?,?,?,?,?)""",
                             (g.user["customer_id"], unit_id, ptype, s, e, form_text(f, "requirements"),
                              "Waiting for Staff", today())).lastrowid
            db.commit()
            flash("Your rental request #%d was sent. Staff will contact you." % rid, "success")
            return redirect(url_for("customer.rental_requests"))
    unit = None
    unit_arg = request.values.get("unit_id", "")
    if unit_arg.isdigit():
        unit = db.execute("""SELECT un.*, pr.name AS property_name, pr.property_type FROM unit un
                             JOIN property pr ON pr.property_id = un.property_id WHERE un.unit_id = ?""", (int(unit_arg),)).fetchone()
    return render_template("customer/rental_request_form.html", unit=unit, form=request.values, alternatives=alternatives,
                           property_types=current_app.config["PROPERTY_TYPES"])


@bp.route("/rental-requests")
def rental_requests():
    rows = get_db().execute("""SELECT r.*, un.unit_no, pr.name AS property_name FROM rental_request r
                               LEFT JOIN unit un ON un.unit_id = r.unit_id LEFT JOIN property pr ON pr.property_id = un.property_id
                               WHERE r.customer_id = ? ORDER BY r.request_id DESC""", (g.user["customer_id"],)).fetchall()
    return render_template("customer/rental_requests.html", requests=rows)


@bp.route("/rental-requests/<int:request_id>/cancel", methods=["POST"])
def rental_request_cancel(request_id):
    db = get_db()
    r = one_or_404(db, "SELECT * FROM rental_request WHERE request_id = ? AND customer_id = ?", (request_id, g.user["customer_id"]))
    if r["status"] in ("Waiting for Staff", "Contacted"):
        db.execute("UPDATE rental_request SET status = 'Cancelled' WHERE request_id = ?", (request_id,))
        db.commit()
        flash("Request cancelled.", "info")
    else:
        flash("This request can no longer be cancelled.", "warning")
    return redirect(url_for("customer.rental_requests"))


# ----------------------------------------------------------- contracts
@bp.route("/contracts/<int:contract_id>")
def contract_detail(contract_id):
    db = get_db()
    c = my_contract_or_404(db, contract_id)
    return render_template(
        "customer/contract.html", c=c, invoices=invoices_for(db, "i.contract_id = ?", (contract_id,)),
        repairs=db.execute("SELECT * FROM repair_request WHERE contract_id = ? ORDER BY repair_id DESC", (contract_id,)).fetchall(),
        extensions=db.execute("SELECT * FROM extension_request WHERE contract_id = ? ORDER BY request_id DESC", (contract_id,)).fetchall(),
        moveouts=db.execute("SELECT * FROM move_out_request WHERE contract_id = ? ORDER BY move_out_id DESC", (contract_id,)).fetchall())


# ----------------------------------------------------------- UC-05 outstanding balance
@bp.route("/balance")
def balance():
    db = get_db()
    invoices = invoices_for(db, "c.customer_id = ? AND c.status IN ('Active','Move-Out Requested')", (g.user["customer_id"],),
                            order="i.due_date, i.invoice_id")
    open_invoices = [i for i in invoices if i["outstanding"] > 0]
    return render_template("customer/balance.html", invoices=invoices, open_invoices=open_invoices,
                           total=sum((i["outstanding"] for i in open_invoices), ZERO))


# ----------------------------------------------------------- UC-04 submit payment
@bp.route("/invoices/<int:invoice_id>/pay", methods=["GET", "POST"])
def pay(invoice_id):
    db = get_db()
    inv = get_invoice(db, invoice_id)
    if inv is None or inv["customer_id"] != g.user["customer_id"]:
        abort(404)
    payments = db.execute("SELECT * FROM payment WHERE invoice_id = ? ORDER BY payment_id DESC", (invoice_id,)).fetchall()
    if request.method == "POST":
        f = request.form
        amount = parse_money(f.get("amount"), allow_zero=False)
        pdate = parse_date(f.get("payment_date"))
        errors = []
        if inv["contract_status"] not in ACTIVE_CONTRACT:
            errors.append("This contract is closed. Please contact staff.")
        if inv["outstanding"] <= 0:
            errors.append("This invoice has no outstanding balance.")
        if amount is None:
            errors.append("Enter a valid amount greater than 0.")
        elif amount > inv["outstanding"]:
            errors.append("The amount is higher than the outstanding balance (%s)." % inv["outstanding"])
        if pdate is None or pdate.isoformat() > today():
            errors.append("Enter a valid payment date (not in the future).")
        if f.get("payment_method") not in PAYMENT_METHODS:
            errors.append("Choose a payment method.")
        files = request.files.getlist("proof")
        if not has_files(files):
            errors.append("Please upload your payment proof (slip or receipt image / PDF).")
        if not errors:
            try:
                pid = db.execute("""INSERT INTO payment (invoice_id, amount, payment_date, payment_method, note, status,
                                    submitted_by_user_id) VALUES (?,?,?,?,?,?,?)""",
                                 (invoice_id, amount, pdate.isoformat(), f["payment_method"], form_text(f, "note"),
                                  "Pending Verification", g.user["user_id"])).lastrowid
                save_uploads(db, files, "payment", pid, g.user["user_id"], "Payment proof")
                db.commit()
                flash("Payment submitted. It will count after staff verify it.", "success")
                return redirect(url_for("customer.pay", invoice_id=invoice_id))
            except UploadError as exc:
                db.rollback()
                errors.append(str(exc))
        for msg in errors:
            flash(msg, "danger")
    proofs = {p["payment_id"]: attachments_for(db, "payment", p["payment_id"]) for p in payments}
    return render_template("customer/pay.html", inv=inv, payments=payments, proofs=proofs, methods=PAYMENT_METHODS,
                           form=request.form, today=today())


@bp.route("/payments/<int:payment_id>/receipt")
def receipt(payment_id):
    db = get_db()
    p = one_or_404(db, """SELECT p.*, i.period, c.customer_id, cu.full_name AS customer_name, un.unit_no, pr.name AS property_name,
                          st.full_name AS staff_name FROM payment p JOIN invoice i ON i.invoice_id = p.invoice_id
                          JOIN contract c ON c.contract_id = i.contract_id JOIN customer cu ON cu.customer_id = c.customer_id
                          JOIN unit un ON un.unit_id = c.unit_id JOIN property pr ON pr.property_id = un.property_id
                          LEFT JOIN staff st ON st.staff_id = p.verified_by_staff_id
                          WHERE p.payment_id = ? AND p.status = 'Verified'""", (payment_id,))
    if p["customer_id"] != g.user["customer_id"]:
        abort(404)
    return render_template("receipt.html", p=p)


# ----------------------------------------------------------- UC-11 repairs
@bp.route("/repairs", methods=["GET", "POST"])
def repairs():
    db = get_db()
    if request.method == "POST":
        c = chosen_active_contract(db)
        desc = form_text(request.form, "description")
        files = request.files.getlist("photos")
        if c is None:
            flash("Choose one of your active contracts.", "danger")
        elif not desc:
            flash("Please describe the problem.", "danger")
        else:
            try:
                rid = db.execute("INSERT INTO repair_request (contract_id, description, status, created_date) VALUES (?,?,?,?)",
                                 (c["contract_id"], desc, "Pending", today())).lastrowid
                save_uploads(db, files, "repair", rid, g.user["user_id"], "Repair photo")
                db.commit()
            except UploadError as exc:
                db.rollback()
                flash(str(exc), "danger")
            else:
                flash("Repair request #%d sent." % rid, "success")
                if not has_files(files):
                    flash("No photo was attached. You can add photos later on the request page.", "warning")
                return redirect(url_for("customer.repair_detail", repair_id=rid))
    rows = db.execute("""SELECT r.*, un.unit_no, pr.name AS property_name FROM repair_request r
                         JOIN contract c ON c.contract_id = r.contract_id JOIN unit un ON un.unit_id = c.unit_id
                         JOIN property pr ON pr.property_id = un.property_id
                         WHERE c.customer_id = ? ORDER BY r.repair_id DESC""", (g.user["customer_id"],)).fetchall()
    return render_with_contracts("customer/repairs.html", db, repairs=rows, form=request.form)


def my_repair_or_404(db, repair_id):
    return one_or_404(db, """SELECT r.*, un.unit_no, pr.name AS property_name, st.full_name AS staff_name
                             FROM repair_request r JOIN contract c ON c.contract_id = r.contract_id
                             JOIN unit un ON un.unit_id = c.unit_id JOIN property pr ON pr.property_id = un.property_id
                             LEFT JOIN staff st ON st.staff_id = r.assigned_staff_id
                             WHERE r.repair_id = ? AND c.customer_id = ?""", (repair_id, g.user["customer_id"]))


@bp.route("/repairs/<int:repair_id>")
def repair_detail(repair_id):
    db = get_db()
    return render_template("customer/repair_detail.html", r=my_repair_or_404(db, repair_id),
                           files=attachments_for(db, "repair", repair_id))


@bp.route("/repairs/<int:repair_id>/photos", methods=["POST"])
def repair_add_photos(repair_id):
    db = get_db()
    my_repair_or_404(db, repair_id)
    try:
        n = save_uploads(db, request.files.getlist("photos"), "repair", repair_id, g.user["user_id"], "Repair photo")
        db.commit()
        flash("%d file(s) added." % n if n else "Choose a file first.", "success" if n else "warning")
    except UploadError as exc:
        db.rollback()
        flash(str(exc), "danger")
    return redirect(url_for("customer.repair_detail", repair_id=repair_id))


@bp.route("/repairs/<int:repair_id>/respond", methods=["POST"])
def repair_respond(repair_id):
    """Customer approves or declines extra cost / time proposed by staff."""
    db = get_db()
    r = my_repair_or_404(db, repair_id)
    if r["status"] == "Awaiting Customer Approval":
        approve = request.form.get("action") == "approve"
        db.execute("UPDATE repair_request SET status = ? WHERE repair_id = ?",
                   ("In Progress" if approve else "Cancelled", repair_id))
        db.commit()
        flash("You approved the repair." if approve else "You declined the repair.", "info")
    return redirect(url_for("customer.repair_detail", repair_id=repair_id))


# ----------------------------------------------------------- UC-06 extension requests
@bp.route("/extensions", methods=["GET", "POST"])
def extensions():
    db = get_db()
    if request.method == "POST":
        c = chosen_active_contract(db)
        scope = form_text(request.form, "scope_description")
        files = request.files.getlist("documents")
        if c is None:
            flash("Choose one of your active contracts.", "danger")
        elif not scope:
            flash("Please describe the work you want to do.", "danger")
        elif not has_files(files):
            flash("Please attach at least one supporting document or plan.", "danger")
        else:
            try:
                rid = db.execute("INSERT INTO extension_request (contract_id, scope_description, status, created_date) VALUES (?,?,?,?)",
                                 (c["contract_id"], scope, "Pending Review", today())).lastrowid
                save_uploads(db, files, "extension", rid, g.user["user_id"], "Supporting document")
                db.commit()
            except UploadError as exc:
                db.rollback()
                flash(str(exc), "danger")
            else:
                flash("Request #%d sent for review." % rid, "success")
                return redirect(url_for("customer.extension_detail", request_id=rid))
    rows = db.execute("""SELECT e.*, un.unit_no, pr.name AS property_name FROM extension_request e
                         JOIN contract c ON c.contract_id = e.contract_id JOIN unit un ON un.unit_id = c.unit_id
                         JOIN property pr ON pr.property_id = un.property_id
                         WHERE c.customer_id = ? ORDER BY e.request_id DESC""", (g.user["customer_id"],)).fetchall()
    return render_with_contracts("customer/extensions.html", db, extensions=rows, form=request.form)


def my_extension_or_404(db, request_id):
    return one_or_404(db, """SELECT e.*, un.unit_no, pr.name AS property_name FROM extension_request e
                             JOIN contract c ON c.contract_id = e.contract_id JOIN unit un ON un.unit_id = c.unit_id
                             JOIN property pr ON pr.property_id = un.property_id
                             WHERE e.request_id = ? AND c.customer_id = ?""", (request_id, g.user["customer_id"]))


@bp.route("/extensions/<int:request_id>")
def extension_detail(request_id):
    db = get_db()
    return render_template("customer/extension_detail.html", e=my_extension_or_404(db, request_id),
                           files=attachments_for(db, "extension", request_id))


@bp.route("/extensions/<int:request_id>/resubmit", methods=["POST"])
def extension_resubmit(request_id):
    db = get_db()
    e = my_extension_or_404(db, request_id)
    files = request.files.getlist("documents")
    note = form_text(request.form, "scope_description")
    if e["status"] != "Needs More Info":
        flash("This request is not waiting for more information.", "warning")
    elif not note and not has_files(files):
        flash("Add a description or a new document.", "danger")
    else:
        try:
            save_uploads(db, files, "extension", request_id, g.user["user_id"], "Supporting document")
            db.execute("UPDATE extension_request SET status = 'Pending Review', scope_description = ? WHERE request_id = ?",
                       (note or e["scope_description"], request_id))
            db.commit()
            flash("Your request was resubmitted for review.", "success")
        except UploadError as exc:
            db.rollback()
            flash(str(exc), "danger")
    return redirect(url_for("customer.extension_detail", request_id=request_id))


# ----------------------------------------------------------- UC-12 move-out
@bp.route("/move-out", methods=["GET", "POST"])
def move_out():
    db = get_db()
    needs_confirm = None
    if request.method == "POST":
        c = chosen_active_contract(db)
        d = parse_date(request.form.get("move_out_date"))
        if c is None or c["status"] != "Active":
            flash("Choose one of your active contracts (without a move-out request already open).", "danger")
        elif d is None or d.isoformat() < today():
            flash("Enter a valid move-out date (today or later).", "danger")
        else:
            early = d.isoformat() < c["end_date"]
            if early and not request.form.get("confirm_early"):
                needs_confirm = c
                flash("Your contract ends on %s. Moving out earlier may involve a fee under the contract terms. "
                      "Tick the box to confirm." % c["end_date"], "warning")
            else:
                db.execute("""INSERT INTO move_out_request (contract_id, requested_move_out_date, reason, early_notice, status,
                              created_date, created_by_user_id) VALUES (?,?,?,?,?,?,?)""",
                           (c["contract_id"], d.isoformat(), form_text(request.form, "reason"), int(early), "Pending",
                            today(), g.user["user_id"]))
                db.execute("UPDATE contract SET status = 'Move-Out Requested' WHERE contract_id = ?", (c["contract_id"],))
                db.commit()
                flash("Move-out notice sent. Staff will arrange the inspection and deposit settlement.", "success")
                return redirect(url_for("customer.move_out"))
    rows = db.execute("""SELECT m.*, un.unit_no, pr.name AS property_name, c.end_date, c.status AS contract_status,
                                c.refund_amount, c.move_out_date, c.settlement_note
                         FROM move_out_request m JOIN contract c ON c.contract_id = m.contract_id
                         JOIN unit un ON un.unit_id = c.unit_id JOIN property pr ON pr.property_id = un.property_id
                         WHERE c.customer_id = ? ORDER BY m.move_out_id DESC""", (g.user["customer_id"],)).fetchall()
    return render_with_contracts("customer/move_out.html", db, requests=rows, form=request.form, needs_confirm=needs_confirm)


@bp.route("/move-out/<int:move_out_id>/cancel", methods=["POST"])
def move_out_cancel(move_out_id):
    db = get_db()
    m = one_or_404(db, """SELECT m.* FROM move_out_request m JOIN contract c ON c.contract_id = m.contract_id
                          WHERE m.move_out_id = ? AND c.customer_id = ?""", (move_out_id, g.user["customer_id"]))
    if m["status"] == "Pending":
        db.execute("UPDATE move_out_request SET status = 'Cancelled' WHERE move_out_id = ?", (move_out_id,))
        db.execute("UPDATE contract SET status = 'Active' WHERE contract_id = ? AND status = 'Move-Out Requested'", (m["contract_id"],))
        db.commit()
        flash("Move-out request cancelled.", "info")
    else:
        flash("This request can no longer be cancelled.", "warning")
    return redirect(url_for("customer.move_out"))
