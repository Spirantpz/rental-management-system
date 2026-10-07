"""Repairs (UC-08) and extension requests (UC-09)."""
from flask import flash, g, redirect, render_template, request, url_for

from ...constants import REPAIR_STATUSES
from ...db import get_db
from ...helpers import form_text, one_or_404, parse_money, today
from ...services import UploadError, attachments_for, save_uploads
from . import bp
from .contracts import staff_list

REPAIR_SELECT = """SELECT r.*, cu.full_name AS customer_name, cu.phone, un.unit_no, pr.name AS property_name, st.full_name AS staff_name
                   FROM repair_request r JOIN contract c ON c.contract_id = r.contract_id
                   JOIN customer cu ON cu.customer_id = c.customer_id JOIN unit un ON un.unit_id = c.unit_id
                   JOIN property pr ON pr.property_id = un.property_id LEFT JOIN staff st ON st.staff_id = r.assigned_staff_id"""


@bp.route("/repairs")
def repairs():
    status = request.args.get("status", "open")
    where, args = "", ()
    if status == "open":
        where = " WHERE r.status NOT IN ('Completed','Cancelled')"
    elif status:
        where, args = " WHERE r.status = ?", (status,)
    rows = get_db().execute(REPAIR_SELECT + where + " ORDER BY r.repair_id DESC", args).fetchall()
    return render_template("staff/repairs.html", repairs=rows, status=status, statuses=REPAIR_STATUSES)


@bp.route("/repairs/<int:repair_id>")
def repair_detail(repair_id):
    db = get_db()
    r = one_or_404(db, REPAIR_SELECT + " WHERE r.repair_id = ?", (repair_id,))
    return render_template("staff/repair_detail.html", r=r, files=attachments_for(db, "repair", repair_id),
                           staff=staff_list(db), statuses=REPAIR_STATUSES)


@bp.route("/repairs/<int:repair_id>/update", methods=["POST"])
def repair_update(repair_id):
    db = get_db()
    r = one_or_404(db, "SELECT * FROM repair_request WHERE repair_id = ?", (repair_id,))
    f = request.form
    status = f.get("status")
    assigned = f.get("assigned_staff_id") or None
    cost = parse_money(f["cost"]) if f.get("cost", "").strip() else None
    note = form_text(f, "staff_note")
    errors = []
    if r["status"] in ("Completed", "Cancelled"):
        errors.append("This repair is closed and cannot be changed.")
    if status not in REPAIR_STATUSES:
        errors.append("Choose a valid status.")
    if assigned and not db.execute("SELECT 1 FROM staff WHERE staff_id = ?", (assigned,)).fetchone():
        errors.append("Choose a valid staff member.")
    if f.get("cost", "").strip() and cost is None:
        errors.append("Cost must be a valid amount.")
    if status == "Completed" and cost is None:
        errors.append("Enter the final cost (0 if free) to complete the job.")
    if status == "Awaiting Customer Approval" and (cost is None or not note):
        errors.append("Enter the estimated cost and explain it in the note so the customer can approve.")
    if status in ("In Progress", "Completed") and not assigned:
        errors.append("Assign a staff member before starting or completing the job.")
    if errors:
        for e in errors:
            flash(e, "danger")
    else:
        try:
            db.execute("""UPDATE repair_request SET assigned_staff_id=?, status=?, cost=?, staff_note=?, completed_date=?
                          WHERE repair_id=?""", (assigned, status, cost, note, today() if status == "Completed" else None, repair_id))
            save_uploads(db, request.files.getlist("evidence"), "repair", repair_id, g.user["user_id"], "Staff / completion evidence")
            db.commit()
            flash("Repair updated." + (" The customer will see that their approval is needed." if status == "Awaiting Customer Approval" else ""), "success")
        except UploadError as exc:
            db.rollback()
            flash(str(exc), "danger")
    return redirect(url_for("staff.repair_detail", repair_id=repair_id))


# ------------------------------------------------------------ extension requests
EXT_SELECT = """SELECT e.*, cu.full_name AS customer_name, un.unit_no, pr.name AS property_name, st.full_name AS staff_name
                FROM extension_request e JOIN contract c ON c.contract_id = e.contract_id
                JOIN customer cu ON cu.customer_id = c.customer_id JOIN unit un ON un.unit_id = c.unit_id
                JOIN property pr ON pr.property_id = un.property_id LEFT JOIN staff st ON st.staff_id = e.decided_by_staff_id"""


@bp.route("/extensions")
def extensions():
    status = request.args.get("status", "Pending Review")
    rows = get_db().execute(EXT_SELECT + " WHERE ? = '' OR e.status = ? ORDER BY e.request_id DESC", (status, status)).fetchall()
    return render_template("staff/extensions.html", extensions=rows, status=status)


@bp.route("/extensions/<int:request_id>")
def extension_detail(request_id):
    db = get_db()
    return render_template("staff/extension_detail.html", e=one_or_404(db, EXT_SELECT + " WHERE e.request_id = ?", (request_id,)),
                           files=attachments_for(db, "extension", request_id))


@bp.route("/extensions/<int:request_id>/decide", methods=["POST"])
def extension_decide(request_id):
    db = get_db()
    e = one_or_404(db, "SELECT * FROM extension_request WHERE request_id = ?", (request_id,))
    decision, reason = request.form.get("decision"), form_text(request.form, "condition_or_reason")
    if e["status"] != "Pending Review":
        flash("This request was already decided or is waiting for the customer.", "warning")
    elif decision not in ("Approved", "Rejected", "Needs More Info"):
        flash("Choose a decision.", "danger")
    elif decision != "Approved" and not reason:
        flash("Enter the reason so the customer understands the decision.", "danger")
    else:
        final = decision in ("Approved", "Rejected")        # 'Needs More Info' is not a final decision
        db.execute("""UPDATE extension_request SET status=?, condition_or_reason=?, decided_by_staff_id=?, decision_date=?
                      WHERE request_id=?""", (decision, reason, g.user["staff_id"] if final else None, today() if final else None, request_id))
        db.commit()
        flash("Decision saved: %s." % decision, "success")
    return redirect(url_for("staff.extension_detail", request_id=request_id))
