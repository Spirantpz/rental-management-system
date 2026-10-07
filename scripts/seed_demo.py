"""Create a database filled with demo data. Refuses to overwrite an existing one."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import Config
from app.seed import seed_demo


def main():
    if os.path.exists(Config.DATABASE):
        print("Database already exists:", Config.DATABASE, "- use scripts.reset_db to rebuild it.")
        return 1
    seed_demo(Config.DATABASE, Config.UPLOAD_FOLDER)
    print("Demo database created:", Config.DATABASE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
