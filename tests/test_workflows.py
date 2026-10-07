"""Business rules at service level: balances, settlement, availability."""
from decimal import Decimal

from app import services
from app.db import connect
from tests.base import AppTestCase


class Finance(AppTestCase):
    def setUp(self):
        super().setUp()
        self.conn = connect(self.db_path)

    def tearDown(self):
        self.conn.close()
        super().tearDown()

    def test_invoice_total_and_verified_only_balance(self):
        inv = services.get_invoice(self.conn, 3)
        self.assertEqual(inv["total"], Decimal("10400"))
        self.assertEqual(inv["outstanding"], Decimal("5400"))      # pending 5400 does not count

    def test_verify_reduces_balance_and_partial_status(self):
        ok, _ = services.verify_payment(self.conn, 4, 1)
        self.assertTrue(ok)
        self.conn.commit()
        inv = services.get_invoice(self.conn, 3)
        self.assertEqual(inv["outstanding"], Decimal("0"))
        self.assertEqual(self.conn.execute("SELECT status FROM invoice WHERE invoice_id=3").fetchone()[0], "Paid")

    def test_reject_does_not_change_balance(self):
        ok, _ = services.reject_payment(self.conn, 4, "blurry")
        self.assertTrue(ok)
        self.assertEqual(services.get_invoice(self.conn, 3)["outstanding"], Decimal("5400"))

    def test_overpayment_refused(self):
        self.conn.execute("UPDATE payment SET amount = 9999 WHERE payment_id = 4")
        ok, _ = services.verify_payment(self.conn, 4, 1)
        self.assertFalse(ok)

    def test_settlement_refund_positive(self):
        self.conn.execute("UPDATE invoice SET status='Paid' WHERE invoice_id=3")
        s = services.settlement(self.conn, 2)
        # deposit 19000 - deductions 0 - outstanding 5400
        self.assertEqual(s["refund"], Decimal("13600"))
        self.assertEqual(s["amount_due"], Decimal("0"))

    def test_settlement_negative(self):
        self.conn.execute("""INSERT INTO damage_record (contract_id, description, deduction_amount, recorded_by_staff_id, recorded_date)
                             VALUES (2, 'big damage', 15000, 1, date('now'))""")
        s = services.settlement(self.conn, 2)
        self.assertEqual(s["refund"], Decimal("-1400"))
        self.assertEqual(s["amount_due"], Decimal("1400"))

    def test_voided_damage_ignored(self):
        did = self.conn.execute("""INSERT INTO damage_record (contract_id, description, deduction_amount, recorded_by_staff_id, recorded_date)
                                   VALUES (2, 'x', 1000, 1, date('now'))""").lastrowid
        self.conn.execute("UPDATE damage_record SET is_voided=1, void_reason='mistake' WHERE damage_id=?", (did,))
        self.assertEqual(services.settlement(self.conn, 2)["deductions"], Decimal("0"))

    def test_availability_checks_contracts_not_just_status(self):
        # T1 (unit 2) has status 'available' but an active contract
        self.assertEqual(self.conn.execute("SELECT status FROM unit WHERE unit_id=2").fetchone()[0], "available")
        self.assertFalse(services.unit_is_free(self.conn, 2, "2000-01-01", "2099-01-01") and True)
        self.assertTrue(services.unit_is_free(self.conn, 7, "2030-01-01", "2030-02-01"))
        self.assertFalse(services.unit_is_free(self.conn, 4, "2030-01-01", "2030-02-01"))   # maintenance
