"""Paths and settings. Works both from source and from the PyInstaller folder."""
import os
import sys


def base_dir():
    """Folder that holds data/, uploads/ and logs/ (next to the EXE when packaged)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Config:
    BASE_DIR = base_dir()
    DATA_DIR = os.path.join(BASE_DIR, "data")
    DATABASE = os.path.join(DATA_DIR, "rental.db")
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
    LOG_DIR = os.path.join(BASE_DIR, "logs")
    MAX_UPLOAD_MB = 5
    MAX_CONTENT_LENGTH = 25 * 1024 * 1024        # whole request (several files)
    ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "pdf"}
    PROPERTY_TYPES = ["House", "Townhouse", "Apartment", "Room"]
    AUTO_CREATE_DEMO_DB = True                   # first run creates a demo database
