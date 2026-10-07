"""Rental Management System: Flask application factory."""
import logging
import os
import secrets
from logging.handlers import RotatingFileHandler

from flask import Flask, g, redirect, render_template, session, url_for
from markupsafe import Markup, escape

from .config import Config
from . import db as database
from . import security


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    data_dir = os.path.dirname(app.config["DATABASE"])
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    os.makedirs(app.config["LOG_DIR"], exist_ok=True)
    app.config["SECRET_KEY"] = app.config.get("SECRET_KEY") or _load_secret_key(data_dir)
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    _setup_logging(app)

    # First run: build the demo database automatically.
    if app.config["AUTO_CREATE_DEMO_DB"] and not database.database_ready(app.config["DATABASE"]):
        from .seed import seed_demo
        seed_demo(app.config["DATABASE"], app.config["UPLOAD_FOLDER"])
        app.logger.info("Created a new demo database at %s", app.config["DATABASE"])

    app.teardown_appcontext(database.close_db)

    @app.before_request
    def load_user():
        security.check_csrf(app)
        g.user = None
        uid = session.get("user_id")
        if uid:
            g.user = database.get_db().execute(
                """SELECT u.*, COALESCE(cu.full_name, st.full_name) AS display_name
                   FROM user_account u LEFT JOIN customer cu ON cu.customer_id = u.customer_id
                   LEFT JOIN staff st ON st.staff_id = u.staff_id
                   WHERE u.user_id = ? AND u.is_active = 1""", (uid,)).fetchone()
            if g.user is None:
                session.clear()

    @app.after_request
    def headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Cache-Control"] = "no-store"
        return resp

    app.jinja_env.globals["csrf_input"] = security.csrf_input
    app.jinja_env.filters["money"] = lambda v: "{:,.2f}".format(float(v or 0))
    app.jinja_env.filters["badge"] = _badge

    from .views import auth, customer, files, staff
    app.register_blueprint(auth.bp)
    app.register_blueprint(customer.bp)
    app.register_blueprint(staff.bp)
    app.register_blueprint(files.bp)

    @app.route("/")
    def index():
        if g.user is None:
            return redirect(url_for("auth.login"))
        return redirect(url_for("staff.dashboard" if g.user["role"] == "staff" else "customer.dashboard"))

    for code, title in ((400, "Bad request"), (403, "Not allowed"), (404, "Page not found"),
                        (413, "File too large")):
        app.register_error_handler(code, _make_error_handler(code, title))

    @app.errorhandler(500)
    def server_error(e):
        app.logger.exception("Server error")
        return render_template("error.html", code=500, title="Something went wrong",
                               message="An unexpected error occurred. Details were written to the log file."), 500

    return app


def _make_error_handler(code, title):
    def handler(e):
        message = getattr(e, "description", "") or ""
        if code == 413:
            message = "The upload is too large. Each file must be at most 5 MB."
        return render_template("error.html", code=code, title=title, message=message), code
    return handler


def _badge(value):
    slug = "".join(ch if ch.isalnum() else "-" for ch in str(value).lower())
    return Markup('<span class="badge b-%s">%s</span>' % (slug, escape(value)))


def _load_secret_key(data_dir):
    path = os.path.join(data_dir, "secret.key")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    key = secrets.token_hex(32)
    with open(path, "w", encoding="utf-8") as f:
        f.write(key)
    return key


def _setup_logging(app):
    if app.config.get("TESTING"):
        return
    handler = RotatingFileHandler(os.path.join(app.config["LOG_DIR"], "app.log"),
                                  maxBytes=500_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    handler.setLevel(logging.INFO)
    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)
