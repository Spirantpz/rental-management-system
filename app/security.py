"""Login / role checks and CSRF protection."""
import hmac
import secrets
from functools import wraps

from flask import abort, flash, g, redirect, request, session, url_for
from markupsafe import Markup


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            flash("Please log in first.", "warning")
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)
    return wrapped


def role_required(role):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if g.user is None:
                flash("Please log in first.", "warning")
                return redirect(url_for("auth.login"))
            if g.user["role"] != role:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


staff_required = role_required("staff")
customer_required = role_required("customer")


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


def csrf_input():
    return Markup('<input type="hidden" name="csrf_token" value="%s">' % csrf_token())


def check_csrf(app):
    if not app.config.get("CSRF_ENABLED", True) or request.method != "POST":
        return
    sent = request.form.get("csrf_token", "")
    if not sent or not hmac.compare_digest(sent, session.get("csrf", "")):
        abort(400, "Your form expired. Please go back, refresh the page and try again.")
