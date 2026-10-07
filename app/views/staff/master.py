"""Dashboard, properties/units (UC-02), customers (UC-03), tenant history (UC-14)."""
import sqlite3

from flask import current_app, flash, redirect, render_template, request, url_for
from werkzeug.security import generate_password_hash

from ...constants import UNIT_STATUSES
from ...db import get_db
from ...helpers import form_text, one_or_404, parse_money, today
from ...services import ZERO, invoices_for
from . import bp


@bp.route("/")
def dashboard():
    db = get_db()
    one = lambda sql, a=(): db.execute(sql, a).fetchone()[0]
    stats = {
        "requests": one("SELECT COUNT(*) FROM rental_request WHERE status IN ('Waiting for Staff','Contacted')"),
        "approved": one("SELECT COUNT(*) FROM rental_request WHERE status = 'Approved'"),
        "payments": one("SELECT COUNT(*) FROM payment WHERE status = 'Pending Verification'"),
        "repairs": one("SELECT COUNT(*) FROM repair_request WHERE status NOT IN ('Completed','Cancelled')"),
        "extensions": one("SELECT COUNT(*) FROM extension_request WHERE status = 'Pending Review'"),
        "moveouts": one("SELECT COUNT(*) FROM move_out_request WHERE status IN ('Pending','Acknowledged')"),
        "contracts": one("SELECT COUNT(*) FROM contract WHERE status IN ('Active','Move-Out Requested')"),
        "incidents": one("SELECT COUNT(*) FROM incident_log WHERE resolution_status = 'Under Investigation'"),
    }
    overdue = [i for i in invoices_for(db, "c.status IN ('Active','Move-Out Requested')") if i["overdue"]]
    stats["overdue"] = len(overdue)
    stats["overdue_total"] = sum((i["outstanding"] for i in overdue), ZERO)
    stats["units_free"] = one("""SELECT COUNT(*) FROM unit u WHERE u.status = 'available' AND NOT EXISTS
        (SELECT 1 FROM contract c WHERE c.unit_id = u.unit_id AND c.status IN ('Active','Move-Out Requested')
         AND c.start_date <= ? AND c.end_date >= ?)""", (today(), today()))
    return render_template("staff/dashboard.html", s=stats, overdue=overdue[:5])


# ------------------------------------------------------------ UC-02 properties & units
@bp.route("/properties")
def properties():
    rows = get_db().execute("""SELECT p.*, (SELECT COUNT(*) FROM unit u WHERE u.property_id = p.property_id) AS unit_count
                               FROM property p ORDER BY p.name""").fetchall()
    return render_template("staff/properties.html", properties=rows)


def _property_form(db, property_id=None):
    row = one_or_404(db, "SELECT * FROM property WHERE property_id = ?", (property_id,)) if property_id else None
    if request.method == "POST":
        f = request.form
        name, address, ptype = form_text(f, "name"), form_text(f, "address"), form_text(f, "property_type")
        if not (name and address and ptype):
            flash("Name, address and type are required. Nothing was saved.", "danger")
        else:
            if row:
                db.execute("UPDATE property SET name=?, address=?, property_type=? WHERE property_id=?",
                           (name, address, ptype, property_id))
            else:
                property_id = db.execute("INSERT INTO property (name, address, property_type) VALUES (?,?,?)",
                                         (name, address, ptype)).lastrowid
            db.commit()
            flash("Property saved.", "success")
            return redirect(url_for("staff.property_detail", property_id=property_id))
    return render_template("staff/property_form.html", p=row, form=request.form,
                           types=current_app.config["PROPERTY_TYPES"])


@bp.route("/properties/new", methods=["GET", "POST"])
def property_new():
    return _property_form(get_db())


@bp.route("/properties/<int:property_id>/edit", methods=["GET", "POST"])
def property_edit(property_id):
    return _property_form(get_db(), property_id)


@bp.route("/properties/<int:property_id>")
def property_detail(property_id):
    db = get_db()
    p = one_or_404(db, "SELECT * FROM property WHERE property_id = ?", (property_id,))
    units = db.execute("""SELECT u.*, (SELECT c.contract_id FROM contract c WHERE c.unit_id = u.unit_id
                          AND c.status IN ('Active','Move-Out Requested') AND c.start_date <= ? AND c.end_date >= ?) AS occupied_by,
                          (SELECT COUNT(*) FROM contract c WHERE c.unit_id = u.unit_id
                           AND c.status IN ('Active','Move-Out Requested') AND c.start_date > ?) AS future_contracts
                          FROM unit u WHERE u.property_id = ? ORDER BY u.unit_no""", (today(), today(), today(), property_id)).fetchall()
    return render_template("staff/property_detail.html", p=p, units=units)


@bp.route("/properties/<int:property_id>/delete", methods=["POST"])
def property_delete(property_id):
    db = get_db()
    try:
        db.execute("DELETE FROM property WHERE property_id = ?", (property_id,))
        db.commit()
        flash("Property deleted.", "success")
        return redirect(url_for("staff.properties"))
    except sqlite3.IntegrityError:
        db.rollback()
        flash("This property still has units, so it cannot be deleted. Nothing was changed.", "danger")
        return redirect(url_for("staff.property_detail", property_id=property_id))


def _unit_form(db, property_id, unit_id=None):
    p = one_or_404(db, "SELECT * FROM property WHERE property_id = ?", (property_id,))
    row = one_or_404(db, "SELECT * FROM unit WHERE unit_id = ? AND property_id = ?", (unit_id, property_id)) if unit_id else None
    if request.method == "POST":
        f = request.form
        unit_no, price, status = form_text(f, "unit_no"), parse_money(f.get("rent_price")), f.get("status")
        if not unit_no or price is None or status not in UNIT_STATUSES:
            flash("Unit number, a valid rent price and status are required. Nothing was saved.", "danger")
        else:
            try:
                if row:
                    db.execute("UPDATE unit SET unit_no=?, rent_price=?, status=? WHERE unit_id=?", (unit_no, price, status, unit_id))
                else:
                    db.execute("INSERT INTO unit (property_id, unit_no, rent_price, status) VALUES (?,?,?,?)",
                               (property_id, unit_no, price, status))
                db.commit()
                flash("Unit saved.", "success")
                return redirect(url_for("staff.property_detail", property_id=property_id))
            except sqlite3.IntegrityError:
                db.rollback()
                flash("Unit number '%s' already exists in this property. Nothing was saved." % unit_no, "danger")
    return render_template("staff/unit_form.html", p=p, u=row, form=request.form, statuses=UNIT_STATUSES)


@bp.route("/properties/<int:property_id>/units/new", methods=["GET", "POST"])
def unit_new(property_id):
    return _unit_form(get_db(), property_id)


@bp.route("/properties/<int:property_id>/units/<int:unit_id>/edit", methods=["GET", "POST"])
def unit_edit(property_id, unit_id):
    return _unit_form(get_db(), property_id, unit_id)


@bp.route("/properties/<int:property_id>/units/<int:unit_id>/delete", methods=["POST"])
def unit_delete(property_id, unit_id):
    db = get_db()
    try:
        db.execute("DELETE FROM unit WHERE unit_id = ? AND property_id = ?", (unit_id, property_id))
        db.commit()
        flash("Unit deleted.", "success")
    except sqlite3.IntegrityError:
        db.rollback()
        flash("This unit has rental history (requests or contracts) and cannot be deleted. "
              "Set its status to 'inactive' instead.", "danger")
    return redirect(url_for("staff.property_detail", property_id=property_id))


# ------------------------------------------------------------ UC-03 customers
@bp.route("/customers")
def customers():
    q = form_text(request.args, "q")
    like = "%" + q + "%"
    rows = get_db().execute("""SELECT cu.*, (SELECT username FROM user_account u WHERE u.customer_id = cu.customer_id) AS username
                               FROM customer cu WHERE ? = '' OR cu.full_name LIKE ? OR cu.id_card_no LIKE ? OR cu.phone LIKE ?
                               ORDER BY cu.full_name""", (q, like, like, like)).fetchall()
    return render_template("staff/customers.html", customers=rows, q=q)


def _customer_form(db, customer_id=None):
    row = one_or_404(db, "SELECT * FROM customer WHERE customer_id = ?", (customer_id,)) if customer_id else None
    account = db.execute("SELECT * FROM user_account WHERE customer_id = ?", (customer_id,)).fetchone() if customer_id else None
    duplicate = None
    if request.method == "POST":
        f = request.form
        name, id_card = form_text(f, "full_name"), form_text(f, "id_card_no")
        username, password = form_text(f, "username"), f.get("password", "")
        errors = []
        if not name or not id_card:
            errors.append("Full name and ID card number are required.")
        other = db.execute("SELECT * FROM customer WHERE id_card_no = ? AND customer_id IS NOT ?", (id_card, customer_id)).fetchone() if id_card else None
        if other:
            duplicate = other
            errors.append("A customer with this ID card number already exists. Use the existing record instead of creating a duplicate.")
        if (username or password) and not account:
            if not username or len(password) < 6:
                errors.append("To create a login, enter a username and a password of at least 6 characters.")
            elif db.execute("SELECT 1 FROM user_account WHERE username = ?", (username,)).fetchone():
                errors.append("This username is already taken.")
        elif account and password and len(password) < 6:
            errors.append("The new password must be at least 6 characters.")
        if errors:
            for e in errors:
                flash(e, "danger")
        else:
            try:
                if row:
                    db.execute("UPDATE customer SET full_name=?, phone=?, id_card_no=?, address=? WHERE customer_id=?",
                               (name, form_text(f, "phone"), id_card, form_text(f, "address"), customer_id))
                else:
                    customer_id = db.execute("INSERT INTO customer (full_name, phone, id_card_no, address) VALUES (?,?,?,?)",
                                             (name, form_text(f, "phone"), id_card, form_text(f, "address"))).lastrowid
                if account and password:
                    db.execute("UPDATE user_account SET password_hash = ? WHERE user_id = ?", (generate_password_hash(password), account["user_id"]))
                elif not account and username and password:
                    db.execute("INSERT INTO user_account (username, password_hash, role, customer_id) VALUES (?,?,?,?)",
                               (username, generate_password_hash(password), "customer", customer_id))
                db.commit()
                flash("Customer saved.", "success")
                return redirect(url_for("staff.customer_history", customer_id=customer_id))
            except sqlite3.IntegrityError:
                db.rollback()
                flash("Could not save: duplicate ID card number or username.", "danger")
    return render_template("staff/customer_form.html", c=row, account=account, form=request.form, duplicate=duplicate)


@bp.route("/customers/new", methods=["GET", "POST"])
def customer_new():
    return _customer_form(get_db())


@bp.route("/customers/<int:customer_id>/edit", methods=["GET", "POST"])
def customer_edit(customer_id):
    return _customer_form(get_db(), customer_id)


# ------------------------------------------------------------ UC-14 tenant history
@bp.route("/customers/<int:customer_id>/history")
def customer_history(customer_id):
    db = get_db()
    c = one_or_404(db, "SELECT * FROM customer WHERE customer_id = ?", (customer_id,))
    contracts = db.execute("""SELECT c.*, un.unit_no, pr.name AS property_name FROM contract c
                              JOIN unit un ON un.unit_id = c.unit_id JOIN property pr ON pr.property_id = un.property_id
                              WHERE c.customer_id = ? ORDER BY c.start_date DESC""", (customer_id,)).fetchall()
    ids = [k["contract_id"] for k in contracts]
    marks = ",".join("?" * len(ids))
    fetch = lambda table, order: db.execute("SELECT * FROM %s WHERE contract_id IN (%s) ORDER BY %s" % (table, marks, order), ids).fetchall() if ids else []
    payments = db.execute("""SELECT p.*, i.period, i.contract_id FROM payment p JOIN invoice i ON i.invoice_id = p.invoice_id
                             WHERE i.contract_id IN (%s) ORDER BY p.payment_id DESC""" % marks, ids).fetchall() if ids else []
    return render_template(
        "staff/customer_history.html", c=c, contracts=contracts,
        invoices=invoices_for(db, "c.customer_id = ?", (customer_id,), order="i.period DESC, i.invoice_id DESC"),
        payments=payments, repairs=fetch("repair_request", "repair_id DESC"), extensions=fetch("extension_request", "request_id DESC"),
        damages=fetch("damage_record", "damage_id DESC"), incidents=fetch("incident_log", "incident_date DESC"),
        moveouts=fetch("move_out_request", "move_out_id DESC"),
        requests=db.execute("SELECT * FROM rental_request WHERE customer_id = ? ORDER BY request_id DESC", (customer_id,)).fetchall())
