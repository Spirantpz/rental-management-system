"""Small helpers shared by the views."""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from flask import abort


def today():
    return date.today().isoformat()


def parse_date(text):
    try:
        return datetime.strptime((text or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_money(text, allow_zero=True):
    """Return Decimal (2 places) or None when invalid / negative."""
    try:
        value = Decimal(str(text).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None
    if not value.is_finite() or value < 0 or (value == 0 and not allow_zero):
        return None
    return value.quantize(Decimal("0.01"))


def one_or_404(db, sql, args=()):
    row = db.execute(sql, args).fetchone()
    if row is None:
        abort(404)
    return row


def form_text(form, name):
    return (form.get(name) or "").strip()
