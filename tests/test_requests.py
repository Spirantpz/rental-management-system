"""HTTP-level tests: permissions, main workflows, page smoke tests."""
import io
from datetime import date, timedelta

from tests.base import AppTestCase, png

TODAY = date.today()


def iso(days):
    return (TODAY + timedelta(days=days)).isoformat()


class Permissions(AppTestCase):
    def test_login_required(self):
        r = self.client.get("/staff/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login", r.headers["Location"])

    def test_wrong_password(self):
        r = self.login("staff1", "nope")
        self.assertIn(b"Wrong username or password", r.data)

    def test_customer_cannot_open_staff_pages(self):
        self.login("customer1")
        for url in ("/staff/", "/staff/contracts", "/staff/payments", "/staff/customers"):
            self.assertEqual(self.client.get(url).status_code, 403, url)

    def test_staff_cannot_open_customer_pages(self):
        self.login("staff1")
        self.assertEqual(self.client.get("/customer/balance").status_code, 403)

    def test_customer_cannot_see_other_customers_contract(self):
        self.login("customer3")
        self.assertEqual(self.client.get("/customer/contracts/2").status_code, 404)
        self.assertEqual(self.client.get("/customer/invoices/3/pay").status_code, 404)

    def test_customer_cannot_verify_payment(self):
        self.login("customer1")
        self.post("/staff/payments/4/verify")
        self.assertEqual(self.scalar("SELECT status FROM payment WHERE payment_id=4"), "Pending Verification")

    def test_incident_files_staff_only(self):
        conn = self.db()
        conn.execute("""INSERT INTO attachment (entity_type, entity_id, original_name, stored_name, mime_type, size_bytes)
                        VALUES ('incident', 1, 'a.png', 'x.png', 'image/png', 1)""")
        conn.commit()
        aid = conn.execute("SELECT MAX(attachment_id) FROM attachment").fetchone()[0]
        conn.close()
        self.login("customer3")
        self.assertEqual(self.client.get("/files/%d" % aid).status_code, 403)

    def test_logout(self):
        self.login("staff1")
        self.post("/logout")
        self.assertEqual(self.client.get("/staff/").status_code, 302)


class Customers(AppTestCase):
    def test_duplicate_id_card_detected(self):
        self.login("staff1")
        r = self.post("/staff/customers/new", {"full_name": "Dup", "phone": "1", "id_card_no": "1100100000011", "address": "x"})
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM customer WHERE id_card_no='1100100000011'"), 1)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM customer WHERE full_name='Dup'"), 0)


class Properties(AppTestCase):
    def test_cannot_delete_unit_with_contract(self):
        self.login("staff1")
        self.post("/staff/properties/2/units/2/delete")
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM unit WHERE unit_id=2"), 1)

    def test_cannot_delete_property_with_units(self):
        self.login("staff1")
        self.post("/staff/properties/2/delete")
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM property WHERE property_id=2"), 1)

    def test_add_property_and_unit(self):
        self.login("staff1")
        self.post("/staff/properties/new", {"name": "New Place", "address": "1 Road", "property_type": "House"})
        pid = self.scalar("SELECT property_id FROM property WHERE name='New Place'")
        self.assertIsNotNone(pid)
        self.post("/staff/properties/%d/units/new" % pid, {"unit_no": "N1", "rent_price": "5000", "status": "available"})
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM unit WHERE property_id=?", (pid,)), 1)


class RentalAndContract(AppTestCase):
    def test_customer_rental_request(self):
        self.login("customer1")
        self.post("/customer/rental-requests/new", {"unit_id": "7", "start_date": iso(10), "end_date": iso(100), "requirements": "x"})
        self.assertEqual(self.scalar("SELECT status FROM rental_request ORDER BY request_id DESC LIMIT 1"), "Waiting for Staff")

    def test_request_for_unavailable_unit_rejected(self):
        self.login("customer2")
        n = self.scalar("SELECT COUNT(*) FROM rental_request")
        self.post("/customer/rental-requests/new", {"unit_id": "2", "start_date": iso(10), "end_date": iso(100)})
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM rental_request"), n)

    def test_past_start_date_rejected(self):
        self.login("customer1")
        n = self.scalar("SELECT COUNT(*) FROM rental_request")
        self.post("/customer/rental-requests/new", {"unit_id": "7", "start_date": iso(-5), "end_date": iso(100)})
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM rental_request"), n)

    def test_contract_needs_approved_request(self):
        self.login("staff1")
        r = self.post("/staff/contracts/new?request_id=3", {"unit_id": "5", "start_date": iso(5), "end_date": iso(200),
                                                             "deposit_amount": "1000", "signed": "1"})
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM contract WHERE rental_request_id=3"), 0)

    def test_contract_from_approved_request(self):
        self.login("staff1")
        self.post("/staff/contracts/new?request_id=4", {"request_id": "4", "unit_id": "1", "start_date": iso(5), "end_date": iso(200),
                                                         "deposit_amount": "30000", "signed": "1"})
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM contract WHERE rental_request_id=4"), 1)
        self.assertEqual(self.scalar("SELECT status FROM rental_request WHERE request_id=4"), "Converted")

    def test_contract_requires_signed_box(self):
        self.login("staff1")
        self.post("/staff/contracts/new?request_id=4", {"request_id": "4", "unit_id": "1", "start_date": iso(5), "end_date": iso(200),
                                                         "deposit_amount": "30000"})
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM contract WHERE rental_request_id=4"), 0)

    def test_overlapping_contract_refused_by_app(self):
        self.login("staff1")
        self.post("/staff/contracts/new?request_id=4", {"request_id": "4", "unit_id": "2", "start_date": iso(5), "end_date": iso(200),
                                                         "deposit_amount": "1", "signed": "1"})
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM contract WHERE rental_request_id=4"), 0)


class Payments(AppTestCase):
    def pay(self, amount="1000", name="slip.png", data=None):
        return self.client.post("/customer/invoices/3/pay", data={
            "amount": amount, "payment_date": TODAY.isoformat(), "payment_method": "Bank Transfer",
            "proof": (data or png(), name)}, content_type="multipart/form-data", follow_redirects=True)

    def test_submit_creates_pending_with_attachment(self):
        self.login("customer1")
        self.pay("1000")
        self.assertEqual(self.scalar("SELECT status FROM payment ORDER BY payment_id DESC LIMIT 1"), "Pending Verification")
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM attachment WHERE entity_type='payment' AND entity_id=(SELECT MAX(payment_id) FROM payment)"), 1)

    def test_proof_required(self):
        self.login("customer1")
        n = self.scalar("SELECT COUNT(*) FROM payment")
        self.client.post("/customer/invoices/3/pay", data={"amount": "100", "payment_date": TODAY.isoformat(),
                         "payment_method": "Cash"}, follow_redirects=True)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM payment"), n)

    def test_overpay_refused(self):
        self.login("customer1")
        n = self.scalar("SELECT COUNT(*) FROM payment")
        self.pay("999999")
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM payment"), n)

    def test_bad_file_type_and_fake_png_refused(self):
        self.login("customer1")
        n = self.scalar("SELECT COUNT(*) FROM payment")
        self.pay("100", "evil.exe", io.BytesIO(b"MZ..."))
        self.pay("100", "fake.png", io.BytesIO(b"not an image"))
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM payment"), n)

    def test_too_large_refused(self):
        self.login("customer1")
        n = self.scalar("SELECT COUNT(*) FROM payment")
        self.pay("100", "big.png", io.BytesIO(b"\x89PNG" + b"0" * (6 * 1024 * 1024)))
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM payment"), n)

    def test_staff_verify_and_receipt(self):
        self.login("staff1")
        self.post("/staff/payments/4/verify")
        self.assertEqual(self.scalar("SELECT status FROM payment WHERE payment_id=4"), "Verified")
        self.assertEqual(self.scalar("SELECT verified_by_staff_id FROM payment WHERE payment_id=4"), 1)
        self.assertEqual(self.client.get("/staff/payments/4/receipt").status_code, 200)

    def test_staff_reject(self):
        self.login("staff1")
        self.post("/staff/payments/4/reject", {"reason": "unreadable"})
        self.assertEqual(self.scalar("SELECT status FROM payment WHERE payment_id=4"), "Rejected")


class Invoices(AppTestCase):
    def test_create_invoice_total(self):
        self.login("staff1")
        period = iso(40)[:7]
        self.post("/staff/invoices/new", {"contract_id": "2", "period": period, "due_date": iso(30),
                                          "rent_fee": "9500", "water_fee": "100", "electric_fee": "400"})
        inv = self.scalar("SELECT rent_fee+water_fee+electric_fee FROM invoice WHERE period=?", (period,))
        self.assertEqual(inv, 10000)

    def test_period_outside_contract_refused(self):
        self.login("staff1")
        self.post("/staff/invoices/new", {"contract_id": "2", "period": "2099-01", "due_date": iso(30), "rent_fee": "1"})
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM invoice WHERE period='2099-01'"), 0)

    def test_duplicate_period_refused(self):
        self.login("staff1")
        period = self.scalar("SELECT period FROM invoice WHERE invoice_id=3")
        n = self.scalar("SELECT COUNT(*) FROM invoice")
        self.post("/staff/invoices/new", {"contract_id": "2", "period": period, "due_date": iso(30), "rent_fee": "1"})
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM invoice"), n)


class RepairsAndExtensions(AppTestCase):
    def test_repair_lifecycle(self):
        self.login("customer1")
        self.client.post("/customer/repairs", data={"contract_id": "2", "description": "Leaking tap",
                         "photos": (png(), "leak.png")}, content_type="multipart/form-data", follow_redirects=True)
        rid = self.scalar("SELECT MAX(repair_id) FROM repair_request")
        self.assertIsNone(self.scalar("SELECT assigned_staff_id FROM repair_request WHERE repair_id=?", (rid,)))
        self.client.post("/logout")
        self.login("staff1")
        self.post("/staff/repairs/%d/update" % rid, {"status": "Completed", "assigned_staff_id": "", "cost": "0"})
        self.assertNotEqual(self.scalar("SELECT status FROM repair_request WHERE repair_id=?", (rid,)), "Completed")
        self.post("/staff/repairs/%d/update" % rid, {"status": "Completed", "assigned_staff_id": "2", "cost": "200"})
        self.assertEqual(self.scalar("SELECT status FROM repair_request WHERE repair_id=?", (rid,)), "Completed")

    def test_extension_needs_document(self):
        self.login("customer1")
        n = self.scalar("SELECT COUNT(*) FROM extension_request")
        self.post("/customer/extensions", {"contract_id": "2", "scope_description": "Build a shed"})
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM extension_request"), n)

    def test_extension_decision_sets_staff(self):
        self.login("staff1")
        self.post("/staff/extensions/1/decide", {"decision": "Approved", "condition_or_reason": "OK with conditions"})
        self.assertEqual(self.scalar("SELECT status FROM extension_request WHERE request_id=1"), "Approved")
        self.assertEqual(self.scalar("SELECT decided_by_staff_id FROM extension_request WHERE request_id=1"), 1)

    def test_rejection_needs_reason(self):
        self.login("staff1")
        self.post("/staff/extensions/1/decide", {"decision": "Rejected", "condition_or_reason": ""})
        self.assertEqual(self.scalar("SELECT status FROM extension_request WHERE request_id=1"), "Pending Review")


class MoveOut(AppTestCase):
    def start(self):
        self.login("customer1")
        self.post("/customer/move-out", {"contract_id": "2", "move_out_date": iso(5), "reason": "relocating", "confirm_early": "1"})
        return self.scalar("SELECT MAX(move_out_id) FROM move_out_request")

    def test_customer_notice_sets_contract_status(self):
        self.start()
        self.assertEqual(self.scalar("SELECT status FROM contract WHERE contract_id=2"), "Move-Out Requested")

    def test_finalize_blocked_with_pending_payment(self):
        mid = self.start()
        self.client.post("/logout")
        self.login("staff1")
        self.post("/staff/move-outs/%d/finalize" % mid, {"move_out_date": iso(5)})
        self.assertEqual(self.scalar("SELECT status FROM contract WHERE contract_id=2"), "Move-Out Requested")

    def test_settlement_refund(self):
        mid = self.start()
        self.client.post("/logout")
        self.login("staff1")
        self.post("/staff/payments/4/verify")
        self.post("/staff/move-outs/%d/damage" % mid, {"description": "Scratch", "deduction_amount": "1000"})
        self.post("/staff/move-outs/%d/finalize" % mid, {"move_out_date": iso(5)})
        self.assertEqual(self.scalar("SELECT status FROM contract WHERE contract_id=2"), "Ended")
        self.assertEqual(self.scalar("SELECT refund_amount FROM contract WHERE contract_id=2"), 18000)

    def test_settlement_negative_then_collected(self):
        mid = self.start()
        self.client.post("/logout")
        self.login("staff1")
        self.post("/staff/payments/4/reject", {"reason": "x"})            # 5400 stays outstanding
        self.post("/staff/move-outs/%d/damage" % mid, {"description": "Big", "deduction_amount": "15000"})
        self.post("/staff/move-outs/%d/finalize" % mid, {"move_out_date": iso(5)})
        self.assertEqual(self.scalar("SELECT status FROM contract WHERE contract_id=2"), "Amount Due")
        self.assertLess(self.scalar("SELECT refund_amount FROM contract WHERE contract_id=2"), 0)
        self.post("/staff/contracts/2/amount-collected", {"note": "cash"})
        self.assertEqual(self.scalar("SELECT status FROM contract WHERE contract_id=2"), "Ended")

    def test_damage_void_keeps_record(self):
        mid = self.start()
        self.client.post("/logout")
        self.login("staff1")
        self.post("/staff/move-outs/%d/damage" % mid, {"description": "Oops", "deduction_amount": "500"})
        did = self.scalar("SELECT MAX(damage_id) FROM damage_record")
        self.post("/staff/damages/%d/void" % did, {"void_reason": "mistake"})
        self.assertEqual(self.scalar("SELECT is_voided FROM damage_record WHERE damage_id=?", (did,)), 1)


class Incidents(AppTestCase):
    def test_log_incident(self):
        self.login("staff1")
        self.post("/staff/incidents/new", {"contract_id": "2", "responsible_staff_id": "1", "incident_date": TODAY.isoformat(),
                                           "description": "Broken gate", "resolution_status": "Under Investigation"})
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM incident_log WHERE description='Broken gate'"), 1)


class Smoke(AppTestCase):
    STAFF = ["/staff/", "/staff/properties", "/staff/properties/1", "/staff/properties/new", "/staff/properties/2/units/new",
             "/staff/customers", "/staff/customers/new", "/staff/customers/1/edit", "/staff/customers/3/history",
             "/staff/rental-requests", "/staff/rental-requests/3", "/staff/rental-requests/new",
             "/staff/contracts", "/staff/contracts/2", "/staff/contracts/new?request_id=4", "/staff/invoices",
             "/staff/invoices/3", "/staff/invoices/new", "/staff/payments", "/staff/payments/3/receipt", "/staff/repairs",
             "/staff/repairs/1", "/staff/extensions", "/staff/extensions/1", "/staff/move-outs", "/staff/incidents",
             "/staff/incidents/new"]
    CUSTOMER = ["/customer/", "/customer/units", "/customer/rental-requests", "/customer/rental-requests/new",
                "/customer/contracts/2", "/customer/balance", "/customer/invoices/3/pay", "/customer/repairs",
                "/customer/extensions", "/customer/move-out", "/customer/payments/3/receipt"]

    def test_staff_pages(self):
        self.login("staff1")
        for url in self.STAFF:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_customer_pages(self):
        self.login("customer1")
        for url in self.CUSTOMER:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_history_page_shows_ended_contract(self):
        self.login("staff1")
        r = self.client.get("/staff/customers/3/history")
        self.assertIn(b"102", r.data)
