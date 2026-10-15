"""Command-line helpers: `python -m app.cli seed-demo` loads reference and demo data."""

from __future__ import annotations

import sys

from app.core.db import SessionLocal, init_db


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "help"
    if cmd == "seed-demo":
        init_db()
        from app.demo import seed_demo
        from app.seed import seed_reference_data

        with SessionLocal() as db:
            seed_reference_data(db)
            seed_demo(db)
            db.commit()
        print("reference and demo data loaded")
        return 0
    if cmd == "init-db":
        init_db()
        print("database initialised")
        return 0
    print("usage: python -m app.cli [seed-demo|init-db]")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
