"""Login, logout and customer self-registration."""
import sqlite3

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from ..db import get_db
from ..helpers import form_text

bp = Blueprint("auth", __name__)


def home_for(user):
    return url_for("staff.dashboard" if user["role"] == "staff" else "customer.dashboard")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(home_for(g.user))
    if request.method == "POST":
        username = form_text(request.form, "username")
        password = request.form.get("password", "")
        user = get_db().execute("SELECT * FROM user_account WHERE username = ? AND is_active = 1",
                                (username,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["user_id"]
            return redirect(home_for(user))
        flash("Wrong username or password.", "danger")
    return render_template("login.html")


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))


@bp.route("/register", methods=["GET", "POST"])
def register():
    """Customers can create their own account."""
    if request.method == "POST":
        f = request.form
        full_name, id_card = form_text(f, "full_name"), form_text(f, "id_card_no")
        username, password = form_text(f, "username"), f.get("password", "")
        errors = []
        if not full_name or not id_card or not username:
            errors.append("Name, ID card number and username are required.")
        if len(password) < 6:
            errors.append("Password must be at least 6 characters.")
        if password != f.get("password2"):
            errors.append("The two passwords do not match.")
        db = get_db()
        if id_card and db.execute("SELECT 1 FROM customer WHERE id_card_no = ?", (id_card,)).fetchone():
            errors.append("This ID card number is already registered. Please ask staff to create or reset your login.")
        if username and db.execute("SELECT 1 FROM user_account WHERE username = ?", (username,)).fetchone():
            errors.append("This username is already taken.")
        if not errors:
            try:
                cid = db.execute("INSERT INTO customer (full_name, phone, id_card_no, address) VALUES (?,?,?,?)",
                                 (full_name, form_text(f, "phone"), id_card, form_text(f, "address"))).lastrowid
                db.execute("INSERT INTO user_account (username, password_hash, role, customer_id) VALUES (?,?,?,?)",
                           (username, generate_password_hash(password), "customer", cid))
                db.commit()
            except sqlite3.IntegrityError:
                db.rollback()
                errors.append("Could not create the account (duplicate data).")
            else:
                flash("Account created. You can log in now.", "success")
                return redirect(url_for("auth.login"))
        for e in errors:
            flash(e, "danger")
    return render_template("register.html", form=request.form)
