"""Rental requests (UC-01 staff side), contracts (UC-13), move-out & deposit settlement (UC-10), incidents (UC-15)."""
import sqlite3

from flask import abort, flash, g, redirect, render_template, request, url_for

from ...constants import INCIDENT_STATUSES
from ...db import get_db
from ...helpers import form_text, one_or_404, parse_date, parse_money, today
from ...services import (UploadError, attachments_for, available_units, find_overlap,
                         invoices_for, save_uploads, settlement, unit_is_free)
from . import bp

CONTRACT_SELECT = """SELECT c.*, cu.full_name AS customer_name, un.unit_no, un.rent_price, pr.name AS property_name,
                            st.full_name AS staff_name
                     FROM contract c JOIN customer cu ON cu.customer_id = c.customer_id
                     JOIN unit un ON un.unit_id = c.unit_id JOIN property pr ON pr.property_id = un.property_id
                     JOIN staff st ON st.staff_id = c.staff_id"""


def staff_list(db):
    return db.execute("SELECT * FROM staff ORDER BY full_name").fetchall()


def active_contracts(db):
    return db.execute(CONTRACT_SELECT + " WHERE c.status IN ('Active','Move-Out Requested') ORDER BY cu.full_name").fetchall()


# ------------------------------------------------------------ rental requests
@bp.route("/rental-requests")
def rental_requests():
    status = request.args.get("status", "")
    rows = get_db().execute("""SELECT r.*, cu.full_name AS customer_name, un.unit_no, pr.name AS property_name
                               FROM rental_request r JOIN customer cu ON cu.customer_id = r.customer_id
                               LEFT JOIN unit un ON un.unit_id = r.unit_id LEFT JOIN property pr ON pr.property_id = un.property_id
                               WHERE ? = '' OR r.status = ? ORDER BY r.request_id DESC""", (status, status)).fetchall()
    return render_template("staff/rental_requests.html", requests=rows, status=status)


@bp.route("/rental-requests/new", methods=["GET", "POST"])
def rental_request_new():
    """Walk-in / phone customer: staff enters the request on the customer's behalf."""
    db = get_db()
    if request.method == "POST":
        f = request.form
        start, end = parse_date(f.get("start_date")), parse_date(f.get("end_date"))
        cust = db.execute("SELECT 1 FROM customer WHERE customer_id = ?", (f.get("customer_id", ""),)).fetchone()
        unit_id = int(f["unit_id"]) if f.get("unit_id", "").isdigit() else None
        if not cust or not start or not end or end < start:
            flash("Choose a customer and enter valid start / end dates.", "danger")
        elif unit_id and not unit_is_free(db, unit_id, start.isoformat(), end.isoformat()):
            flash("That unit is not available for these dates.", "danger")
        else:
            rid = db.execute("""INSERT INTO rental_request (customer_id, unit_id, desired_start_date, desired_end_date, requirements,
                                status, created_date, handled_by_staff_id, handled_date) VALUES (?,?,?,?,?,?,?,?,?)""",
                             (f["customer_id"], unit_id, start.isoformat(), end.isoformat(), form_text(f, "requirements"),
                              "Contacted", today(), g.user["staff_id"], today())).lastrowid
            db.commit()
            flash("Request #%d created." % rid, "success")
            return redirect(url_for("staff.rental_request_detail", request_id=rid))
    customers = db.execute("SELECT customer_id, full_name, id_card_no FROM customer ORDER BY full_name").fetchall()
    return render_template("staff/rental_request_new.html", customers=customers, units=available_units(db), form=request.form)


@bp.route("/rental-requests/<int:request_id>")
def rental_request_detail(request_id):
    db = get_db()
    r = one_or_404(db, """SELECT r.*, cu.full_name AS customer_name, cu.phone, un.unit_no, un.rent_price, pr.name AS property_name,
                          st.full_name AS staff_name FROM rental_request r JOIN customer cu ON cu.customer_id = r.customer_id
                          LEFT JOIN unit un ON un.unit_id = r.unit_id LEFT JOIN property pr ON pr.property_id = un.property_id
                          LEFT JOIN staff st ON st.staff_id = r.handled_by_staff_id WHERE r.request_id = ?""", (request_id,))
    free = None
    if r["unit_id"]:
        free = unit_is_free(db, r["unit_id"], r["desired_start_date"], r["desired_end_date"])
    contract = db.execute("SELECT contract_id FROM contract WHERE rental_request_id = ?", (request_id,)).fetchone()
    return render_template("staff/rental_request_detail.html", r=r, free=free, contract=contract,
                           matches=available_units(db, r["desired_start_date"], r["desired_end_date"], r["desired_property_type"]))


@bp.route("/rental-requests/<int:request_id>/update", methods=["POST"])
def rental_request_update(request_id):
    db = get_db()
    r = one_or_404(db, "SELECT * FROM rental_request WHERE request_id = ?", (request_id,))
    status = request.form.get("status")
    unit_id = int(request.form["unit_id"]) if request.form.get("unit_id", "").isdigit() else r["unit_id"]
    if r["status"] in ("Converted", "Cancelled"):
        flash("This request is closed and cannot be changed.", "warning")
    elif status not in ("Contacted", "Approved", "Rejected"):
        flash("Choose a valid status.", "danger")
    elif status == "Approved" and not (unit_id and unit_is_free(db, unit_id, r["desired_start_date"], r["desired_end_date"])):
        flash("Choose a unit that is available for the requested dates before approving.", "danger")
    else:
        db.execute("""UPDATE rental_request SET status=?, unit_id=?, staff_note=?, handled_by_staff_id=?, handled_date=?
                      WHERE request_id=?""", (status, unit_id, form_text(request.form, "staff_note"), g.user["staff_id"], today(), request_id))
        db.commit()
        flash("Request updated.", "success")
    return redirect(url_for("staff.rental_request_detail", request_id=request_id))


# ------------------------------------------------------------ contracts
@bp.route("/contracts")
def contracts():
    status = request.args.get("status", "")
    rows = get_db().execute(CONTRACT_SELECT + " WHERE ? = '' OR c.status = ? ORDER BY c.contract_id DESC", (status, status)).fetchall()
    return render_template("staff/contracts.html", contracts=rows, status=status)


@bp.route("/contracts/new", methods=["GET", "POST"])
def contract_new():
    """A contract can only be created from an Approved rental request."""
    db = get_db()
    rid = request.values.get("request_id", "")
    if not rid.isdigit():
        abort(404)
    r = one_or_404(db, """SELECT r.*, cu.full_name AS customer_name FROM rental_request r
                          JOIN customer cu ON cu.customer_id = r.customer_id WHERE r.request_id = ?""", (rid,))
    if r["status"] != "Approved":
        flash("Only an Approved rental request can be converted into a contract.", "warning")
        return redirect(url_for("staff.rental_request_detail", request_id=r["request_id"]))
    if request.method == "POST":
        f = request.form
        start, end, deposit = parse_date(f.get("start_date")), parse_date(f.get("end_date")), parse_money(f.get("deposit_amount"))
        unit_id = int(f["unit_id"]) if f.get("unit_id", "").isdigit() else None
        if not (start and end and unit_id) or end < start or deposit is None:
            flash("Enter valid dates, a unit and a deposit amount.", "danger")
        elif not f.get("signed"):
            flash("The contract is only started after the customer has reviewed and signed it. Tick the box when this is done.", "warning")
        elif not unit_is_free(db, unit_id, start.isoformat(), end.isoformat()):
            clash = find_overlap(db, unit_id, start.isoformat(), end.isoformat())
            flash("This unit cannot be rented for these dates" + (" (overlaps contract #%d)." % clash["contract_id"] if clash else
                  " (the unit is not open for rent).") + " Nothing was saved.", "danger")
        else:
            try:
                cid = db.execute("""INSERT INTO contract (rental_request_id, customer_id, unit_id, staff_id, start_date, end_date,
                                    deposit_amount, status) VALUES (?,?,?,?,?,?,?,?)""",
                                 (r["request_id"], r["customer_id"], unit_id, g.user["staff_id"], start.isoformat(),
                                  end.isoformat(), deposit, "Active")).lastrowid
                db.execute("UPDATE rental_request SET status = 'Converted', unit_id = ? WHERE request_id = ?", (unit_id, r["request_id"]))
                db.commit()
                flash("Contract #%d started." % cid, "success")
                return redirect(url_for("staff.contract_detail", contract_id=cid))
            except sqlite3.IntegrityError as exc:
                db.rollback()
                flash("The database refused the contract: %s" % exc, "danger")
    form = request.form if request.method == "POST" else {
        "start_date": r["desired_start_date"], "end_date": r["desired_end_date"], "unit_id": r["unit_id"], "deposit_amount": ""}
    units = available_units(db, r["desired_start_date"], r["desired_end_date"])
    return render_template("staff/contract_form.html", r=r, units=units, form=form)


@bp.route("/contracts/<int:contract_id>")
def contract_detail(contract_id):
    db = get_db()
    c = one_or_404(db, CONTRACT_SELECT + " WHERE c.contract_id = ?", (contract_id,))
    count = lambda t: db.execute("SELECT COUNT(*) FROM %s WHERE contract_id = ?" % t, (contract_id,)).fetchone()[0]
    return render_template(
        "staff/contract_detail.html", c=c, invoices=invoices_for(db, "i.contract_id = ?", (contract_id,)),
        counts={"repairs": count("repair_request"), "extensions": count("extension_request"), "incidents": count("incident_log"),
                "damages": count("damage_record")},
        moveouts=db.execute("SELECT * FROM move_out_request WHERE contract_id = ? ORDER BY move_out_id DESC", (contract_id,)).fetchall(),
        open_moveout=db.execute("SELECT * FROM move_out_request WHERE contract_id = ? AND status IN ('Pending','Acknowledged')", (contract_id,)).fetchone())


# ------------------------------------------------------------ move-out and deposit settlement (UC-10)
@bp.route("/move-outs")
def move_outs():
    rows = get_db().execute("""SELECT m.*, cu.full_name AS customer_name, un.unit_no, pr.name AS property_name, c.status AS contract_status
                               FROM move_out_request m JOIN contract c ON c.contract_id = m.contract_id
                               JOIN customer cu ON cu.customer_id = c.customer_id JOIN unit un ON un.unit_id = c.unit_id
                               JOIN property pr ON pr.property_id = un.property_id
                               ORDER BY (m.status IN ('Pending','Acknowledged')) DESC, m.move_out_id DESC""").fetchall()
    return render_template("staff/move_outs.html", moveouts=rows)


@bp.route("/contracts/<int:contract_id>/move-out/start", methods=["POST"])
def move_out_start(contract_id):
    """Staff starts the move-out process (contract about to expire, or tenant told staff in person)."""
    db = get_db()
    c = one_or_404(db, "SELECT * FROM contract WHERE contract_id = ?", (contract_id,))
    d = parse_date(request.form.get("move_out_date")) or parse_date(c["end_date"])
    if c["status"] != "Active":
        flash("A move-out can only be started for an Active contract.", "warning")
        return redirect(url_for("staff.contract_detail", contract_id=contract_id))
    mid = db.execute("""INSERT INTO move_out_request (contract_id, requested_move_out_date, reason, early_notice, status, created_date,
                        created_by_user_id, handled_by_staff_id, handled_date) VALUES (?,?,?,?,?,?,?,?,?)""",
                     (contract_id, d.isoformat(), "Started by staff", int(d.isoformat() < c["end_date"]), "Acknowledged", today(),
                      g.user["user_id"], g.user["staff_id"], today())).lastrowid
    db.execute("UPDATE contract SET status = 'Move-Out Requested' WHERE contract_id = ?", (contract_id,))
    db.commit()
    return redirect(url_for("staff.move_out_detail", move_out_id=mid))


@bp.route("/move-outs/<int:move_out_id>")
def move_out_detail(move_out_id):
    db = get_db()
    m = one_or_404(db, "SELECT * FROM move_out_request WHERE move_out_id = ?", (move_out_id,))
    c = one_or_404(db, CONTRACT_SELECT + " WHERE c.contract_id = ?", (m["contract_id"],))
    damages = db.execute("SELECT * FROM damage_record WHERE contract_id = ? ORDER BY damage_id", (c["contract_id"],)).fetchall()
    pending = db.execute("""SELECT COUNT(*) FROM payment p JOIN invoice i ON i.invoice_id = p.invoice_id
                            WHERE i.contract_id = ? AND p.status = 'Pending Verification'""", (c["contract_id"],)).fetchone()[0]
    return render_template(
        "staff/move_out_detail.html", m=m, c=c, damages=damages, pending_payments=pending, s=settlement(db, c["contract_id"]),
        invoices=invoices_for(db, "i.contract_id = ?", (c["contract_id"],)), today=today(),
        damage_files={d["damage_id"]: attachments_for(db, "damage", d["damage_id"]) for d in damages})


@bp.route("/move-outs/<int:move_out_id>/acknowledge", methods=["POST"])
def move_out_acknowledge(move_out_id):
    db = get_db()
    m = one_or_404(db, "SELECT * FROM move_out_request WHERE move_out_id = ?", (move_out_id,))
    if m["status"] == "Pending":
        db.execute("UPDATE move_out_request SET status='Acknowledged', handled_by_staff_id=?, handled_date=?, staff_note=? WHERE move_out_id=?",
                   (g.user["staff_id"], today(), form_text(request.form, "staff_note"), move_out_id))
        db.commit()
        flash("Move-out acknowledged.", "success")
    return redirect(url_for("staff.move_out_detail", move_out_id=move_out_id))


@bp.route("/move-outs/<int:move_out_id>/damage", methods=["POST"])
def damage_add(move_out_id):
    db = get_db()
    m = one_or_404(db, "SELECT * FROM move_out_request WHERE move_out_id = ?", (move_out_id,))
    desc, amount = form_text(request.form, "description"), parse_money(request.form.get("deduction_amount"))
    if m["status"] not in ("Pending", "Acknowledged"):
        flash("This move-out is already completed.", "warning")
    elif not desc or amount is None:
        flash("Enter a description and a valid deduction amount.", "danger")
    else:
        try:
            did = db.execute("""INSERT INTO damage_record (contract_id, description, deduction_amount, recorded_by_staff_id, recorded_date)
                                VALUES (?,?,?,?,?)""", (m["contract_id"], desc, amount, g.user["staff_id"], today())).lastrowid
            save_uploads(db, request.files.getlist("photos"), "damage", did, g.user["user_id"], "Damage photo")
            db.commit()
            flash("Damage recorded.", "success")
        except UploadError as exc:
            db.rollback()
            flash(str(exc), "danger")
    return redirect(url_for("staff.move_out_detail", move_out_id=move_out_id))


@bp.route("/damages/<int:damage_id>/void", methods=["POST"])
def damage_void(damage_id):
    """Damage records are never deleted; a wrong one is voided with a reason."""
    db = get_db()
    d = one_or_404(db, "SELECT * FROM damage_record WHERE damage_id = ?", (damage_id,))
    m = db.execute("SELECT * FROM move_out_request WHERE contract_id = ? ORDER BY move_out_id DESC", (d["contract_id"],)).fetchone()
    reason = form_text(request.form, "void_reason")
    c = db.execute("SELECT status FROM contract WHERE contract_id = ?", (d["contract_id"],)).fetchone()
    if c["status"] not in ("Active", "Move-Out Requested"):
        flash("The contract is already settled; records can no longer be changed.", "warning")
    elif not reason:
        flash("Enter the reason for voiding this deduction.", "danger")
    else:
        db.execute("UPDATE damage_record SET is_voided = 1, void_reason = ? WHERE damage_id = ?", (reason, damage_id))
        db.commit()
        flash("Deduction voided (kept in history).", "info")
    return redirect(url_for("staff.move_out_detail", move_out_id=m["move_out_id"]) if m else url_for("staff.contracts"))


@bp.route("/move-outs/<int:move_out_id>/finalize", methods=["POST"])
def move_out_finalize(move_out_id):
    db = get_db()
    m = one_or_404(db, "SELECT * FROM move_out_request WHERE move_out_id = ?", (move_out_id,))
    c = one_or_404(db, "SELECT * FROM contract WHERE contract_id = ?", (m["contract_id"],))
    d = parse_date(request.form.get("move_out_date"))
    pending = db.execute("""SELECT COUNT(*) FROM payment p JOIN invoice i ON i.invoice_id = p.invoice_id
                            WHERE i.contract_id = ? AND p.status = 'Pending Verification'""", (c["contract_id"],)).fetchone()[0]
    if m["status"] not in ("Pending", "Acknowledged") or c["status"] != "Move-Out Requested":
        flash("This move-out cannot be finalized (already completed?).", "warning")
    elif d is None:
        flash("Enter the actual move-out date.", "danger")
    elif pending:
        flash("Verify or reject the pending payments first, so the settlement uses the final balance.", "danger")
    else:
        s = settlement(db, c["contract_id"])
        status = "Ended" if s["refund"] >= 0 else "Amount Due"
        note = form_text(request.form, "settlement_note") or (
            "Refund %s" % s["refund"] if s["refund"] >= 0 else "Customer owes %s" % s["amount_due"])
        db.execute("""UPDATE contract SET status=?, move_out_date=?, refund_amount=?, settlement_note=? WHERE contract_id=?""",
                   (status, d.isoformat(), s["refund"], note, c["contract_id"]))
        db.execute("UPDATE move_out_request SET status='Completed', handled_by_staff_id=?, handled_date=? WHERE move_out_id=?",
                   (g.user["staff_id"], today(), move_out_id))
        db.commit()
        if s["refund"] >= 0:
            flash("Contract closed. Refund the deposit balance of %s to the customer." % s["refund"], "success")
        else:
            flash("The customer still owes %s. The contract stays open for payment until the amount is collected." % s["amount_due"], "warning")
    return redirect(url_for("staff.move_out_detail", move_out_id=move_out_id))


@bp.route("/contracts/<int:contract_id>/amount-collected", methods=["POST"])
def amount_collected(contract_id):
    db = get_db()
    c = one_or_404(db, "SELECT * FROM contract WHERE contract_id = ?", (contract_id,))
    if c["status"] == "Amount Due":
        note = "%s | Amount collected on %s. %s" % (c["settlement_note"] or "", today(), form_text(request.form, "note"))
        db.execute("UPDATE contract SET status = 'Ended', settlement_note = ? WHERE contract_id = ?", (note.strip(), contract_id))
        db.commit()
        flash("Marked as collected. The contract is now closed.", "success")
    m = db.execute("SELECT move_out_id FROM move_out_request WHERE contract_id = ? ORDER BY move_out_id DESC", (contract_id,)).fetchone()
    return redirect(url_for("staff.move_out_detail", move_out_id=m["move_out_id"]) if m else url_for("staff.contract_detail", contract_id=contract_id))


# ------------------------------------------------------------ incidents (UC-15)
@bp.route("/incidents")
def incidents():
    status = request.args.get("status", "")
    rows = get_db().execute("""SELECT i.*, cu.full_name AS customer_name, un.unit_no, pr.name AS property_name, st.full_name AS staff_name
                               FROM incident_log i JOIN contract c ON c.contract_id = i.contract_id
                               JOIN customer cu ON cu.customer_id = c.customer_id JOIN unit un ON un.unit_id = c.unit_id
                               JOIN property pr ON pr.property_id = un.property_id JOIN staff st ON st.staff_id = i.responsible_staff_id
                               WHERE ? = '' OR i.resolution_status = ? ORDER BY i.incident_id DESC""", (status, status)).fetchall()
    return render_template("staff/incidents.html", incidents=rows, status=status, statuses=INCIDENT_STATUSES)


@bp.route("/incidents/new", methods=["GET", "POST"])
def incident_new():
    db = get_db()
    if request.method == "POST":
        f = request.form
        d = parse_date(f.get("incident_date"))
        active = db.execute("SELECT 1 FROM contract WHERE contract_id = ? AND status IN ('Active','Move-Out Requested')", (f.get("contract_id", ""),)).fetchone()
        staff = db.execute("SELECT 1 FROM staff WHERE staff_id = ?", (f.get("responsible_staff_id", ""),)).fetchone()
        if not active or not staff or d is None or not form_text(f, "description") or f.get("resolution_status") not in INCIDENT_STATUSES:
            flash("Choose an active contract, responsible staff, a valid date, a status and describe the incident.", "danger")
        else:
            try:
                iid = db.execute("""INSERT INTO incident_log (contract_id, responsible_staff_id, incident_date, description, resolution_status,
                                    resolution_note) VALUES (?,?,?,?,?,?)""",
                                 (f["contract_id"], f["responsible_staff_id"], d.isoformat(), form_text(f, "description"),
                                  f["resolution_status"], form_text(f, "resolution_note"))).lastrowid
                save_uploads(db, request.files.getlist("evidence"), "incident", iid, g.user["user_id"], "Incident evidence")
                db.commit()
                flash("Incident #%d recorded." % iid, "success")
                return redirect(url_for("staff.incident_detail", incident_id=iid))
            except UploadError as exc:
                db.rollback()
                flash(str(exc), "danger")
    return render_template("staff/incident_form.html", contracts=active_contracts(db), staff=staff_list(db),
                           statuses=INCIDENT_STATUSES, form=request.form, today=today(),
                           contract_id=request.args.get("contract_id", ""))


@bp.route("/incidents/<int:incident_id>")
def incident_detail(incident_id):
    db = get_db()
    i = one_or_404(db, """SELECT i.*, cu.full_name AS customer_name, cu.customer_id, un.unit_no, pr.name AS property_name
                          FROM incident_log i JOIN contract c ON c.contract_id = i.contract_id
                          JOIN customer cu ON cu.customer_id = c.customer_id JOIN unit un ON un.unit_id = c.unit_id
                          JOIN property pr ON pr.property_id = un.property_id WHERE i.incident_id = ?""", (incident_id,))
    return render_template("staff/incident_detail.html", i=i, files=attachments_for(db, "incident", incident_id),
                           staff=staff_list(db), statuses=INCIDENT_STATUSES)


@bp.route("/incidents/<int:incident_id>/update", methods=["POST"])
def incident_update(incident_id):
    db = get_db()
    one_or_404(db, "SELECT 1 FROM incident_log WHERE incident_id = ?", (incident_id,))
    f = request.form
    if f.get("resolution_status") not in INCIDENT_STATUSES or not db.execute("SELECT 1 FROM staff WHERE staff_id = ?", (f.get("responsible_staff_id", ""),)).fetchone():
        flash("Choose a valid status and responsible staff.", "danger")
    else:
        try:
            db.execute("UPDATE incident_log SET resolution_status=?, resolution_note=?, responsible_staff_id=? WHERE incident_id=?",
                       (f["resolution_status"], form_text(f, "resolution_note"), f["responsible_staff_id"], incident_id))
            save_uploads(db, request.files.getlist("evidence"), "incident", incident_id, g.user["user_id"], "Incident evidence")
            db.commit()
            flash("Incident updated.", "success")
        except UploadError as exc:
            db.rollback()
            flash(str(exc), "danger")
    return redirect(url_for("staff.incident_detail", incident_id=incident_id))
