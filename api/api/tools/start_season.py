"""Start a new trading season.

Archives every agent's portfolio (renamed to '<strategy>@s<N>' in
portfolio_states), cancels active intents, clears agent state, and bumps
meta.current_season. Historical trades/snapshots/decision logs keep their
season number and stay queryable.

Run inside the Fly machine:
    python -m api.tools.start_season --yes
"""

from __future__ import annotations

import sys

from api.db.sqlite import db


def main() -> None:
    if "--yes" not in sys.argv:
        print("This archives all portfolios and starts a fresh season.")
        print("Re-run with --yes to confirm.")
        sys.exit(1)
    db.init_db()
    old = db.get_current_season()
    new = db.start_new_season()
    print(f"Season {new} started (season {old} archived).")
    print("Restart the app (or wait for the next tick) so fresh portfolios initialize.")


if __name__ == "__main__":
    main()
