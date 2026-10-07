"""Business rules: balances, deposit settlement, overlap check, attachments."""
import os
import uuid
from decimal import Decimal, ROUND_HALF_UP

from flask import current_app

from .helpers import today

ZERO = Decimal("0.00")


def D(value):
    return Decimal(str(value or 0)).quantize(Decimal("0.01"), ROUND_HALF_UP)


# ---------------------------------------------------------------- invoices
def _invoice_dict(row):
    d = dict(row)
    total = D(row["rent_fee"]) + D(row["water_fee"]) + D(row["electric_fee"])   # Rent + Water + Electricity
    paid = D(row["paid_raw"])                                                   # Verified payments only
    d["total"] = total
    d["paid"] = paid
    d["pending"] = D(row["pending_raw"])
    d["outstanding"] = max(total - paid, ZERO)                                  # Total - Verified Payments
    d["overdue"] = d["outstanding"] > 0 and row["due_date"] < today()
    return d


def invoices_for(db, where="1=1", args=(), order="i.due_date DESC, i.invoice_id DESC"):
    """Invoices with total / paid / outstanding. `where` must be a fixed SQL string (not user input)."""
    rows = db.execute(
        f"""SELECT i.*, c.customer_id, c.status AS contract_status, cu.full_name AS customer_name,
                   un.unit_no, pr.name AS property_name,
                   COALESCE((SELECT SUM(p.amount) FROM payment p
                             WHERE p.invoice_id = i.invoice_id AND p.status = 'Verified'), 0) AS paid_raw,
                   COALESCE((SELECT SUM(p.amount) FROM payment p
                             WHERE p.invoice_id = i.invoice_id AND p.status = 'Pending Verification'), 0) AS pending_raw
            FROM invoice i
            JOIN contract c ON c.contract_id = i.contract_id
            JOIN customer cu ON cu.customer_id = c.customer_id
            JOIN unit un ON un.unit_id = c.unit_id
            JOIN property pr ON pr.property_id = un.property_id
            WHERE {where} ORDER BY {order}""", args).fetchall()
    return [_invoice_dict(r) for r in rows]


def get_invoice(db, invoice_id):
    rows = invoices_for(db, "i.invoice_id = ?", (invoice_id,))
    return rows[0] if rows else None


def refresh_invoice_status(db, invoice_id):
    inv = get_invoice(db, invoice_id)
    if inv["outstanding"] == 0:
        status = "Paid"
    elif inv["paid"] > 0:
        status = "Partially Paid"
    else:
        status = "Unpaid"
    db.execute("UPDATE invoice SET status = ? WHERE invoice_id = ?", (status, invoice_id))


def contract_outstanding(db, contract_id):
    return sum((i["outstanding"] for i in invoices_for(db, "i.contract_id = ?", (contract_id,))), ZERO)


# ------------------------------------------------------------ payments
def verify_payment(db, payment_id, staff_id):
    """Mark a pending payment Verified. Returns (ok, message)."""
    pay = db.execute("SELECT * FROM payment WHERE payment_id = ?", (payment_id,)).fetchone()
    if pay is None or pay["status"] != "Pending Verification":
        return False, "This payment is not waiting for verification."
    inv = get_invoice(db, pay["invoice_id"])
    if D(pay["amount"]) > inv["outstanding"]:
        return False, ("Amount is higher than the outstanding balance (%s). Reject it and ask the customer to resubmit."
                       % inv["outstanding"])
    receipt = "RC-%s-%05d" % (today()[:4], payment_id)
    db.execute("""UPDATE payment SET status='Verified', verified_by_staff_id=?, verified_date=?, receipt_no=?
                  WHERE payment_id=?""", (staff_id, today(), receipt, payment_id))
    refresh_invoice_status(db, pay["invoice_id"])
    return True, "Payment verified. Receipt %s issued." % receipt


def reject_payment(db, payment_id, reason):
    pay = db.execute("SELECT * FROM payment WHERE payment_id = ?", (payment_id,)).fetchone()
    if pay is None or pay["status"] != "Pending Verification":
        return False, "This payment is not waiting for verification."
    db.execute("UPDATE payment SET status='Rejected', reject_reason=? WHERE payment_id=?", (reason, payment_id))
    return True, "Payment rejected."


# ------------------------------------------------------------ contracts
def find_overlap(db, unit_id, start, end, exclude_contract_id=None):
    """Return an active/future contract of the same unit that overlaps [start, end], or None."""
    sql = """SELECT * FROM contract WHERE unit_id = ? AND status IN ('Active','Move-Out Requested')
             AND start_date <= ? AND end_date >= ?"""
    args = [unit_id, end, start]
    if exclude_contract_id:
        sql += " AND contract_id <> ?"
        args.append(exclude_contract_id)
    return db.execute(sql, args).fetchone()


def unit_is_free(db, unit_id, start, end):
    """Availability = unit is open for rent AND no overlapping active/future contract (UNIT.status alone is not enough)."""
    unit = db.execute("SELECT status FROM unit WHERE unit_id = ?", (unit_id,)).fetchone()
    return unit is not None and unit["status"] == "available" and find_overlap(db, unit_id, start, end) is None


def available_units(db, start=None, end=None, property_type=None):
    rows = db.execute(
        """SELECT un.*, pr.name AS property_name, pr.address, pr.property_type
           FROM unit un JOIN property pr ON pr.property_id = un.property_id
           WHERE un.status = 'available' AND (? IS NULL OR pr.property_type = ?)
           ORDER BY pr.name, un.unit_no""", (property_type or None, property_type or None)).fetchall()
    if start and end:
        rows = [r for r in rows if find_overlap(db, r["unit_id"], start, end) is None]
    else:
        rows = [r for r in rows if find_overlap(db, r["unit_id"], today(), today()) is None]
    return rows


# ------------------------------------------------------------ deposit settlement
def settlement(db, contract_id):
    """Refund = Deposit - Valid Deductions - Outstanding obligations. Negative => customer still owes money."""
    c = db.execute("SELECT * FROM contract WHERE contract_id = ?", (contract_id,)).fetchone()
    deposit = D(c["deposit_amount"])
    deductions = D(db.execute(
        "SELECT COALESCE(SUM(deduction_amount),0) FROM damage_record WHERE contract_id = ? AND is_voided = 0",
        (contract_id,)).fetchone()[0])
    outstanding = contract_outstanding(db, contract_id)
    refund = deposit - deductions - outstanding
    return {"deposit": deposit, "deductions": deductions, "outstanding": outstanding,
            "refund": refund, "amount_due": -refund if refund < 0 else ZERO}


# ------------------------------------------------------------ attachments
_MAGIC = {"jpg": (b"\xff\xd8",), "jpeg": (b"\xff\xd8",), "png": (b"\x89PNG",), "pdf": (b"%PDF",)}
_MIME = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "pdf": "application/pdf"}


class UploadError(ValueError):
    pass


def has_files(files):
    return any(f and f.filename for f in files)


def save_uploads(db, files, entity_type, entity_id, user_id, description=None):
    """Validate every non-empty file, then save them all. Raises UploadError on a bad file. Returns number saved."""
    cfg = current_app.config
    max_bytes = cfg["MAX_UPLOAD_MB"] * 1024 * 1024
    ready = []
    for f in files:
        if not f or not f.filename:
            continue
        ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
        if ext not in cfg["ALLOWED_EXTENSIONS"]:
            raise UploadError("File '%s' is not allowed. Allowed types: %s."
                              % (f.filename, ", ".join(sorted(cfg["ALLOWED_EXTENSIONS"]))))
        data = f.read()
        if len(data) > max_bytes:
            raise UploadError("File '%s' is larger than %d MB." % (f.filename, cfg["MAX_UPLOAD_MB"]))
        if not data or not data.startswith(_MAGIC[ext]):
            raise UploadError("File '%s' is empty or is not a real %s file." % (f.filename, ext.upper()))
        ready.append((f.filename, ext, data))
    os.makedirs(cfg["UPLOAD_FOLDER"], exist_ok=True)
    for name, ext, data in ready:
        stored = uuid.uuid4().hex + "." + ext
        with open(os.path.join(cfg["UPLOAD_FOLDER"], stored), "wb") as out:
            out.write(data)
        db.execute("""INSERT INTO attachment (entity_type, entity_id, original_name, stored_name, mime_type,
                      size_bytes, description, uploaded_by_user_id) VALUES (?,?,?,?,?,?,?,?)""",
                   (entity_type, entity_id, os.path.basename(name)[:150], stored, _MIME[ext],
                    len(data), description, user_id))
    return len(ready)


def attachments_for(db, entity_type, entity_id):
    return db.execute("SELECT * FROM attachment WHERE entity_type = ? AND entity_id = ? ORDER BY attachment_id",
                      (entity_type, entity_id)).fetchall()


# Which customer owns an attachment (None = staff only, e.g. incident evidence)
_OWNER_SQL = {
    "payment": """SELECT c.customer_id FROM payment p JOIN invoice i ON i.invoice_id=p.invoice_id
                  JOIN contract c ON c.contract_id=i.contract_id WHERE p.payment_id=?""",
    "repair": "SELECT c.customer_id FROM repair_request r JOIN contract c ON c.contract_id=r.contract_id WHERE r.repair_id=?",
    "extension": "SELECT c.customer_id FROM extension_request r JOIN contract c ON c.contract_id=r.contract_id WHERE r.request_id=?",
    "damage": "SELECT c.customer_id FROM damage_record r JOIN contract c ON c.contract_id=r.contract_id WHERE r.damage_id=?",
    "rental_request": "SELECT customer_id FROM rental_request WHERE request_id=?",
    "move_out": "SELECT c.customer_id FROM move_out_request r JOIN contract c ON c.contract_id=r.contract_id WHERE r.move_out_id=?",
}


def attachment_owner(db, att):
    sql = _OWNER_SQL.get(att["entity_type"])
    if sql is None:
        return None
    row = db.execute(sql, (att["entity_id"],)).fetchone()
    return row[0] if row else None
