import sqlite3

from tests.base import AppTestCase


class DatabaseRules(AppTestCase):
    def test_overlap_insert_blocked(self):
        conn = self.db()
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("""INSERT INTO contract (customer_id, unit_id, staff_id, start_date, end_date, deposit_amount, status)
                            VALUES (2, 2, 1, date('now'), date('now','+30 day'), 100, 'Active')""")
        conn.close()

    def test_non_overlapping_future_contract_allowed(self):
        conn = self.db()
        conn.execute("""INSERT INTO contract (rental_request_id, customer_id, unit_id, staff_id, start_date, end_date, deposit_amount, status)
                        VALUES (4, 2, 2, 1, date('now','+400 day'), date('now','+500 day'), 100, 'Active')""")
        conn.commit()
        conn.close()

    def test_overlap_update_blocked(self):
        conn = self.db()
        conn.execute("""INSERT INTO contract (rental_request_id, customer_id, unit_id, staff_id, start_date, end_date, deposit_amount, status)
                        VALUES (4, 2, 2, 1, date('now','+400 day'), date('now','+500 day'), 100, 'Active')""")
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("UPDATE contract SET start_date = date('now') WHERE contract_id = last_insert_rowid()")
        conn.close()

    def test_no_delete_historical_tables(self):
        conn = self.db()
        for table in ("contract", "invoice", "payment", "repair_request", "incident_log",
                      "extension_request", "damage_record", "rental_request", "attachment"):
            with self.assertRaises(sqlite3.IntegrityError, msg=table):
                conn.execute("DELETE FROM %s" % table)
        conn.execute("""INSERT INTO move_out_request (contract_id, requested_move_out_date, status, created_date)
                        VALUES (2, date('now'), 'Pending', date('now'))""")
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM move_out_request")
        conn.close()

    def test_verified_payment_is_final(self):
        conn = self.db()
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("UPDATE payment SET amount = 1 WHERE payment_id = 3")
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("UPDATE payment SET status = 'Rejected' WHERE payment_id = 3")
        conn.close()

    def test_verified_requires_staff_and_receipt(self):
        conn = self.db()
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("UPDATE payment SET status = 'Verified' WHERE payment_id = 4")
        conn.close()

    def test_nullable_staff_columns(self):
        conn = self.db()
        conn.execute("""INSERT INTO payment (invoice_id, amount, payment_date, payment_method, status)
                        VALUES (3, 10, date('now'), 'Cash', 'Pending Verification')""")
        self.assertIsNone(self.scalar("SELECT assigned_staff_id FROM repair_request WHERE repair_id = 1"))
        self.assertIsNone(self.scalar("SELECT decided_by_staff_id FROM extension_request WHERE request_id = 1"))
        conn.close()

    def test_unit_no_unique_per_property(self):
        conn = self.db()
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO unit (property_id, unit_no, rent_price, status) VALUES (2, 'T1', 1, 'available')")
        conn.close()

    def test_contract_requires_unique_request(self):
        conn = self.db()
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("""INSERT INTO contract (rental_request_id, customer_id, unit_id, staff_id, start_date, end_date, deposit_amount, status)
                            VALUES (1, 1, 7, 1, date('now'), date('now','+30 day'), 1, 'Active')""")
        conn.close()
