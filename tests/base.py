"""Shared test helpers. The demo database is built once and copied for every test."""
import os
import shutil
import sqlite3
import tempfile
import unittest

from app import create_app
from app.seed import seed_demo

_TEMPLATE_DIR = tempfile.mkdtemp(prefix="rental-template-")
_TEMPLATE_DB = os.path.join(_TEMPLATE_DIR, "rental.db")
_TEMPLATE_UPLOADS = os.path.join(_TEMPLATE_DIR, "uploads")
seed_demo(_TEMPLATE_DB, _TEMPLATE_UPLOADS)

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
       b"\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7\x9a\xa0\xa0\x00\x00\x00\x00IEND\xaeB`\x82")


def png():
    import io
    return io.BytesIO(PNG)


class AppTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rental-test-")
        self.db_path = os.path.join(self.tmp, "rental.db")
        self.uploads = os.path.join(self.tmp, "uploads")
        shutil.copy(_TEMPLATE_DB, self.db_path)
        shutil.copytree(_TEMPLATE_UPLOADS, self.uploads)
        self.app = create_app({"DATABASE": self.db_path, "UPLOAD_FOLDER": self.uploads,
                               "LOG_DIR": os.path.join(self.tmp, "logs"), "AUTO_CREATE_DEMO_DB": False,
                               "SECRET_KEY": "test", "TESTING": True, "CSRF_ENABLED": False})
        self.client = self.app.test_client()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # helpers
    def db(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def scalar(self, sql, args=()):
        conn = self.db()
        try:
            row = conn.execute(sql, args).fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    def login(self, username, password=None, client=None):
        client = client or self.client
        if password is None:
            password = "staff1234" if username.startswith("staff") else "customer1234"
        return client.post("/login", data={"username": username, "password": password}, follow_redirects=True)

    def post(self, url, data=None, **kw):
        return self.client.post(url, data=data or {}, follow_redirects=True, **kw)
