from __future__ import annotations

import argparse
import logging
import os
import subprocess
from pathlib import Path

import duckdb

from .analytics import build_analytics
from .config import Paths
from .conform import build_conformed
from .download import download
from .validate import validate


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="weather-vibes")
    root.add_argument("--data-dir", type=Path,
                      default=Path(os.environ.get("WEATHER_VIBES_DATA_DIR", "data")))
    root.add_argument("--verbose", action="store_true")
    commands = root.add_subparsers(dest="command", required=True)
    fetch = commands.add_parser("download", help="refresh NOAA raw files")
    fetch.add_argument("--limit", type=int, help="download only N stations (smoke tests)")
    fetch.add_argument("--workers", type=int, default=6)
    commands.add_parser("build-conformed")
    commands.add_parser("build-analytics")
    run = commands.add_parser("run", help="download and build all layers")
    run.add_argument("--limit", type=int)
    run.add_argument("--workers", type=int, default=6)
    commands.add_parser("validate")
    commands.add_parser("query", help="open the DuckDB CLI, if installed")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    paths = Paths(args.data_dir.resolve())
    if args.command in {"download", "run"}:
        download(paths, args.limit, args.workers)
    if args.command in {"build-conformed", "run"}:
        build_conformed(paths)
    if args.command in {"build-analytics", "run"}:
        build_analytics(paths)
    if args.command in {"validate", "run"}:
        results = validate(paths)
        logging.info("all %d validation checks passed", len(results))
    if args.command == "query":
        try:
            return subprocess.call(["duckdb", str(paths.database)])
        except FileNotFoundError:
            con = duckdb.connect(str(paths.database), read_only=True)
            print("DuckDB CLI not found. Views:", ", ".join(
                row[0] for row in con.execute("SHOW TABLES").fetchall()))
            con.close()
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

