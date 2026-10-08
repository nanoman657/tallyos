"""
Command line entry points.

    python -m app.cli init-db               create tables
    python -m app.cli seed --reset          wipe and load demo data (simulated ads)
    python -m app.cli run-loop [--dry-run] [--as-of YYYY-MM-DD]
                                            one sense-think-act cycle (cron this daily)
"""

import argparse
import json
from datetime import date

from .ads import get_platform
from .config import get_settings
from .db import connect, init_schema, session
from .growth.loop import _jsonable, run_cycle


def reset_schema(database_url: str = None) -> None:
    conn = connect(database_url)
    conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    conn.commit()
    conn.close()


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="tallyos")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db")
    p_seed = sub.add_parser("seed")
    p_seed.add_argument("--reset", action="store_true", help="drop all data first")
    p_loop = sub.add_parser("run-loop")
    p_loop.add_argument("--dry-run", action="store_true")
    p_loop.add_argument("--as-of", type=date.fromisoformat)
    args = parser.parse_args(argv)
    settings = get_settings()

    if args.cmd == "seed" and args.reset:
        reset_schema()
    conn = connect()
    init_schema(conn)
    conn.close()

    if args.cmd == "seed":
        from .seed import seed
        with session() as db:
            print(json.dumps(seed(db, settings), indent=2))
    elif args.cmd == "run-loop":
        with session() as db:
            result = run_cycle(db, get_platform(db, settings), settings, as_of=args.as_of, dry_run=args.dry_run)
            print(json.dumps(_jsonable({"run_id": result["run_id"], "think": result["think"]["decisions"],
                                        "act": result["act"]}), indent=2))
    else:
        print("schema ready")


if __name__ == "__main__":
    main()
