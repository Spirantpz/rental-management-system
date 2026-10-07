"""SQLite helpers."""
import os
import sqlite3
from decimal import Decimal

from flask import current_app, g

sqlite3.register_adapter(Decimal, lambda d: float(d))
SCHEMA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")


def connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db():
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def create_schema(path):
    """Create an empty database with all tables."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = connect(path)
    with open(SCHEMA_FILE, encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()


def database_ready(path):
    if not os.path.exists(path):
        return False
    conn = connect(path)
    try:
        row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_account'").fetchone()
        return row is not None
    finally:
        conn.close()
