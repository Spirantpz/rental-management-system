"""Demo data. `seed_demo` builds a brand-new database; dates are relative to today."""
import base64
import os
import uuid
from datetime import date, timedelta

from werkzeug.security import generate_password_hash

from . import db as database

# 1x1 pixel PNG used as demo "payment proof" / "repair photo"
_PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg==")

DEMO_PASSWORD_STAFF = "staff1234"
DEMO_PASSWORD_CUSTOMER = "customer1234"


def _iso(d):
    return d.isoformat()


def _period(d):
    return d.strftime("%Y-%m")


def _prev_month_start(d):
    return (d.replace(day=1) - timedelta(days=1)).replace(day=1)


def seed_demo(db_path, upload_folder):
    database.create_schema(db_path)
    conn = database.connect(db_path)
    try:
        _seed(conn, upload_folder)
        conn.commit()
    finally:
        conn.close()


def _user(conn, username, password, role, customer_id=None, staff_id=None):
    return conn.execute(
        "INSERT INTO user_account (username, password_hash, role, customer_id, staff_id) VALUES (?,?,?,?,?)",
        (username, generate_password_hash(password), role, customer_id, staff_id)).lastrowid


def _attach(conn, upload_folder, etype, eid, user_id, name="demo-photo.png", description=None):
    os.makedirs(upload_folder, exist_ok=True)
    stored = uuid.uuid4().hex + ".png"
    with open(os.path.join(upload_folder, stored), "wb") as f:
        f.write(_PNG)
    conn.execute("""INSERT INTO attachment (entity_type, entity_id, original_name, stored_name, mime_type,
                    size_bytes, description, uploaded_by_user_id) VALUES (?,?,?,?,?,?,?,?)""",
                 (etype, eid, name, stored, "image/png", len(_PNG), description, user_id))


def _seed(conn, uploads):
    t = date.today()
    q = lambda sql, a=(): conn.execute(sql, a).lastrowid

    # ---- staff + accounts
    s1 = q("INSERT INTO staff (full_name, role, phone) VALUES (?,?,?)", ("Somchai Jaidee", "Manager", "081-111-1111"))
    s2 = q("INSERT INTO staff (full_name, role, phone) VALUES (?,?,?)", ("Malee Sukjai", "Technician", "081-222-2222"))
    _user(conn, "staff1", DEMO_PASSWORD_STAFF, "staff", staff_id=s1)
    _user(conn, "staff2", DEMO_PASSWORD_STAFF, "staff", staff_id=s2)

    # ---- customers + accounts
    c1 = q("INSERT INTO customer (full_name, phone, id_card_no, address) VALUES (?,?,?,?)",
           ("Anong Rakdee", "089-100-0001", "1100100000011", "12 Sukhumvit Rd, Bangkok"))
    c2 = q("INSERT INTO customer (full_name, phone, id_card_no, address) VALUES (?,?,?,?)",
           ("Boonmee Charoen", "089-100-0002", "1100100000022", "55 Rama IV Rd, Bangkok"))
    c3 = q("INSERT INTO customer (full_name, phone, id_card_no, address) VALUES (?,?,?,?)",
           ("Chai Wongsa", "089-100-0003", "1100100000033", "7 Silom Rd, Bangkok"))
    u_c1 = _user(conn, "customer1", DEMO_PASSWORD_CUSTOMER, "customer", customer_id=c1)
    _user(conn, "customer2", DEMO_PASSWORD_CUSTOMER, "customer", customer_id=c2)
    _user(conn, "customer3", DEMO_PASSWORD_CUSTOMER, "customer", customer_id=c3)

    # ---- properties + units
    p1 = q("INSERT INTO property (name, address, property_type) VALUES (?,?,?)",
           ("Sunrise House", "99 Lat Phrao Rd, Bangkok", "House"))
    p2 = q("INSERT INTO property (name, address, property_type) VALUES (?,?,?)",
           ("Lotus Townhomes", "21 Ratchada Rd, Bangkok", "Townhouse"))
    p3 = q("INSERT INTO property (name, address, property_type) VALUES (?,?,?)",
           ("River View Apartment", "8 Charoen Krung Rd, Bangkok", "Apartment"))
    unit = lambda p, no, price, st="available": q(
        "INSERT INTO unit (property_id, unit_no, rent_price, status) VALUES (?,?,?,?)", (p, no, price, st))
    u_a1 = unit(p1, "A1", 15000)
    u_t1 = unit(p2, "T1", 9500)
    unit(p2, "T2", 9500)
    unit(p2, "T3", 10500, "maintenance")
    u_101 = unit(p3, "101", 6500)
    u_102 = unit(p3, "102", 6500)
    unit(p3, "201", 7500)

    # ---- 1) ended contract (history demo) for Chai on River View 102
    start3, end3, out3 = t - timedelta(days=430), t - timedelta(days=65), t - timedelta(days=65)
    r3 = q("""INSERT INTO rental_request (customer_id, unit_id, desired_property_type, desired_start_date,
              desired_end_date, requirements, status, created_date, handled_by_staff_id, handled_date)
              VALUES (?,?,?,?,?,?,?,?,?,?)""",
           (c3, u_102, "Apartment", _iso(start3), _iso(end3), "Near BTS", "Converted", _iso(start3 - timedelta(days=7)),
            s1, _iso(start3 - timedelta(days=5))))
    k3 = q("""INSERT INTO contract (rental_request_id, customer_id, unit_id, staff_id, start_date, end_date,
              deposit_amount, status, move_out_date, refund_amount, settlement_note)
              VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
           (r3, c3, u_102, s1, _iso(start3), _iso(end3), 13000, "Ended", _iso(out3), 11500.0,
            "Refund after wall repair deduction"))
    i3 = q("INSERT INTO invoice (contract_id, period, rent_fee, water_fee, electric_fee, due_date, status) VALUES (?,?,?,?,?,?,?)",
           (k3, _period(end3 - timedelta(days=40)), 6500, 150, 480, _iso(end3 - timedelta(days=33)), "Paid"))
    conn.execute("""INSERT INTO payment (invoice_id, amount, payment_date, payment_method, status, verified_by_staff_id,
                    verified_date, receipt_no) VALUES (?,?,?,?,?,?,?,?)""",
                 (i3, 7130, _iso(end3 - timedelta(days=35)), "Bank Transfer", "Verified", s1,
                  _iso(end3 - timedelta(days=34)), "RC-DEMO-00001"))
    q("INSERT INTO damage_record (contract_id, description, deduction_amount, recorded_by_staff_id, recorded_date) VALUES (?,?,?,?,?)",
      (k3, "Wall repainting after move-out", 1500, s1, _iso(out3)))
    q("""INSERT INTO incident_log (contract_id, responsible_staff_id, incident_date, description, resolution_status, resolution_note)
         VALUES (?,?,?,?,?,?)""", (k3, s1, _iso(start3 + timedelta(days=120)), "Noise complaint from neighbour", "Resolved",
                                    "Tenant warned, no repeat"))

    # ---- 2) active contract: Anong on Lotus T1
    start1, end1 = t - timedelta(days=62), t + timedelta(days=303)
    r1 = q("""INSERT INTO rental_request (customer_id, unit_id, desired_property_type, desired_start_date,
              desired_end_date, requirements, status, created_date, handled_by_staff_id, handled_date)
              VALUES (?,?,?,?,?,?,?,?,?,?)""",
           (c1, u_t1, "Townhouse", _iso(start1), _iso(end1), "Pet friendly", "Converted",
            _iso(start1 - timedelta(days=6)), s1, _iso(start1 - timedelta(days=3))))
    k1 = q("""INSERT INTO contract (rental_request_id, customer_id, unit_id, staff_id, start_date, end_date,
              deposit_amount, status) VALUES (?,?,?,?,?,?,?,?)""", (r1, c1, u_t1, s1, _iso(start1), _iso(end1), 19000, "Active"))
    prev = _prev_month_start(t)
    inv_prev = q("INSERT INTO invoice (contract_id, period, rent_fee, water_fee, electric_fee, due_date, status) VALUES (?,?,?,?,?,?,?)",
                 (k1, _period(prev), 9500, 180, 620, _iso(prev.replace(day=28)), "Paid"))
    conn.execute("""INSERT INTO payment (invoice_id, amount, payment_date, payment_method, status, verified_by_staff_id,
                    verified_date, receipt_no, submitted_by_user_id) VALUES (?,?,?,?,?,?,?,?,?)""",
                 (inv_prev, 10300, _iso(prev.replace(day=27)), "PromptPay", "Verified", s1, _iso(prev.replace(day=28)),
                  "RC-DEMO-00002", u_c1))
    inv_now = q("INSERT INTO invoice (contract_id, period, rent_fee, water_fee, electric_fee, due_date, status) VALUES (?,?,?,?,?,?,?)",
                (k1, _period(t), 9500, 200, 700, _iso(t + timedelta(days=7)), "Partially Paid"))
    conn.execute("""INSERT INTO payment (invoice_id, amount, payment_date, payment_method, status, verified_by_staff_id,
                    verified_date, receipt_no, submitted_by_user_id) VALUES (?,?,?,?,?,?,?,?,?)""",
                 (inv_now, 5000, _iso(t - timedelta(days=1)), "Bank Transfer", "Verified", s1, _iso(t), "RC-DEMO-00003", u_c1))
    pend = q("""INSERT INTO payment (invoice_id, amount, payment_date, payment_method, status, submitted_by_user_id, note)
                VALUES (?,?,?,?,?,?,?)""", (inv_now, 5400, _iso(t), "Bank Transfer", "Pending Verification", u_c1,
                                            "Second installment"))
    _attach(conn, uploads, "payment", pend, u_c1, "transfer-slip.png", "Payment proof")
    rep1 = q("INSERT INTO repair_request (contract_id, description, status, created_date) VALUES (?,?,?,?)",
             (k1, "Kitchen sink is leaking", "Pending", _iso(t - timedelta(days=1))))
    _attach(conn, uploads, "repair", rep1, u_c1, "sink.png", "Photo of the leak")
    q("""INSERT INTO repair_request (contract_id, assigned_staff_id, description, status, created_date, staff_note)
         VALUES (?,?,?,?,?,?)""", (k1, s2, "Bedroom light does not work", "In Progress", _iso(t - timedelta(days=5)),
                                   "Replacing the ceiling light fitting"))
    ext = q("INSERT INTO extension_request (contract_id, scope_description, status, created_date) VALUES (?,?,?,?)",
            (k1, "Build a small wooden roof over the back patio", "Pending Review", _iso(t - timedelta(days=2))))
    _attach(conn, uploads, "extension", ext, u_c1, "patio-plan.png", "Plan drawing")

    # ---- 3) rental requests waiting for staff
    q("""INSERT INTO rental_request (customer_id, unit_id, desired_property_type, desired_start_date, desired_end_date,
         requirements, status, created_date) VALUES (?,?,?,?,?,?,?,?)""",
      (c2, u_101, "Apartment", _iso(t + timedelta(days=14)), _iso(t + timedelta(days=378)), "Quiet floor, 1 year",
       "Waiting for Staff", _iso(t)))
    q("""INSERT INTO rental_request (customer_id, unit_id, desired_property_type, desired_start_date, desired_end_date,
         requirements, status, created_date, handled_by_staff_id, handled_date, staff_note) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
      (c2, u_a1, "House", _iso(t + timedelta(days=30)), _iso(t + timedelta(days=395)), "Family of four", "Approved",
       _iso(t - timedelta(days=3)), s1, _iso(t - timedelta(days=1)), "Viewing done, terms agreed"))
