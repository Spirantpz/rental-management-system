"""Download uploaded files with permission checks."""
import os

from flask import Blueprint, abort, current_app, g, send_from_directory

from ..db import get_db
from ..security import login_required
from ..services import attachment_owner

bp = Blueprint("files", __name__, url_prefix="/files")


@bp.route("/<int:attachment_id>")
@login_required
def download(attachment_id):
    db = get_db()
    att = db.execute("SELECT * FROM attachment WHERE attachment_id = ?", (attachment_id,)).fetchone()
    if att is None:
        abort(404)
    if g.user["role"] == "customer" and attachment_owner(db, att) != g.user["customer_id"]:
        abort(403)
    path = current_app.config["UPLOAD_FOLDER"]
    if not os.path.exists(os.path.join(path, att["stored_name"])):
        abort(404)
    return send_from_directory(path, att["stored_name"], mimetype=att["mime_type"],
                               download_name=att["original_name"], as_attachment=False)
