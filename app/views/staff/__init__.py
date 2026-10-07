"""Staff area: one blueprint, split over several files to keep each file small."""
from flask import Blueprint

from ...security import staff_required

bp = Blueprint("staff", __name__, url_prefix="/staff")


@bp.before_request
@staff_required
def guard():
    pass


from . import master, contracts, billing, requests  # noqa: E402,F401  (register the routes)
