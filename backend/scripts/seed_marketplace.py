"""Make the five demo creators and their published listings (safe to run again).

Usage: python scripts/seed_marketplace.py [--compute-now]
Uses the configured database and market data provider. By default each listing's performance is
queued for the backtest worker of a running server; --compute-now measures it here instead.
"""

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.db import SessionLocal  # noqa: E402
from app.market_data import get_provider  # noqa: E402
from app.marketplace.performance import compute_performance  # noqa: E402
from app.marketplace.seed import seed_marketplace  # noqa: E402
from app.migrate import upgrade_database  # noqa: E402
from app.models import User  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--compute-now", action="store_true", help="measure performance here, not on the worker"
    )
    args = parser.parse_args()
    upgrade_database()
    provider = get_provider()
    with SessionLocal() as db:
        for listing in seed_marketplace(db, provider):
            owner = db.get(User, listing.owner_user_id)
            line = f"{owner.username}: {listing.name} [{listing.status}]"
            if args.compute_now:
                for row in compute_performance(db, provider, listing):
                    line += f"\n    {row.window}: {row.status}" + (f" ({row.note})" if row.note else "")
            print(line)


if __name__ == "__main__":
    main()
