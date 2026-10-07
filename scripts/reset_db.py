"""Back up data/ and uploads/ to backups/<timestamp>/, then rebuild the demo database."""
import os
import shutil
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import Config
from app.seed import seed_demo


def reset():
    backup = None
    if os.path.exists(Config.DATABASE) or os.path.isdir(Config.UPLOAD_FOLDER):
        backup = os.path.join(Config.BASE_DIR, "backups", datetime.now().strftime("%Y%m%d-%H%M%S"))
        os.makedirs(backup, exist_ok=True)
        if os.path.exists(Config.DATABASE):
            shutil.copy2(Config.DATABASE, os.path.join(backup, "rental.db"))
        if os.path.isdir(Config.UPLOAD_FOLDER):
            shutil.copytree(Config.UPLOAD_FOLDER, os.path.join(backup, "uploads"))
    for path in (Config.DATABASE, Config.DATABASE + "-wal", Config.DATABASE + "-shm"):
        if os.path.exists(path):
            os.remove(path)
    if os.path.isdir(Config.UPLOAD_FOLDER):
        shutil.rmtree(Config.UPLOAD_FOLDER)
    os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
    seed_demo(Config.DATABASE, Config.UPLOAD_FOLDER)
    print("Demo data restored.")
    if backup:
        print("Previous data was backed up to:", backup)


if __name__ == "__main__":
    reset()
