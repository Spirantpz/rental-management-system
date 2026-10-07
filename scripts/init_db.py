"""Create an empty database (tables only, no data). Refuses to overwrite an existing one."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import Config
from app.db import create_schema


def main():
    if os.path.exists(Config.DATABASE):
        print("Database already exists:", Config.DATABASE, "- use scripts.reset_db to rebuild it.")
        return 1
    create_schema(Config.DATABASE)
    print("Created empty database:", Config.DATABASE)
    print("Note: it has no login accounts. Use scripts.seed_demo for demo data.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
