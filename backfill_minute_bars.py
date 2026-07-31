#!/usr/bin/env python3
"""Export PostgreSQL minute bars one month at a time as compressed CSV files."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator


DEFAULT_TICKERS = [
    "FPT", "VCB", "HPG", "MWG", "TCB",
    "MBB", "VPB", "SSI", "VND", "PNJ",
]


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date {value!r}; use YYYY-MM-DD"
        ) from exc


def first_of_next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def month_windows(start: date, end: date) -> Iterator[tuple[date, date]]:
    """Yield [start, end) windows, never crossing a calendar-month boundary."""
    cursor = start
    while cursor < end:
        window_end = min(first_of_next_month(cursor), end)
        yield cursor, window_end
        cursor = window_end


def json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def validate_row(row: tuple[Any, ...], columns: dict[str, int]) -> list[str]:
    problems: list[str] = []
    o = row[columns["matched_open"]]
    h = row[columns["matched_high"]]
    low = row[columns["matched_low"]]
    close = row[columns["matched_close"]]
    quantity = row[columns["matched_quantity"]]

    if any(value is None for value in (o, h, low, close)):
        problems.append("missing_ohlc")
    elif not (h >= max(o, close) and low <= min(o, close) and h >= low):
        problems.append("invalid_ohlc")

    if quantity is None or quantity < 0:
        problems.append("invalid_quantity")
    return problems


def export_month(
    conn: Any,
    query: str,
    output_dir: Path,
    start: date,
    end: date,
    tickers: list[str],
    fetch_size: int,
    overwrite: bool,
) -> dict[str, Any]:
    label = start.strftime("%Y_%m")
    output_path = output_dir / f"minute_bars_{label}.csv.gz"
    metadata_path = output_dir / f"minute_bars_{label}.json"
    temporary_path = output_dir / f".minute_bars_{label}.csv.gz.part"

    if output_path.exists() and not overwrite:
        print(f"SKIP {label}: {output_path} already exists", flush=True)
        return {"period": label, "status": "skipped", "file": str(output_path)}

    stats: dict[str, Any] = {
        "period": label,
        "status": "running",
        "start_inclusive": start.isoformat(),
        "end_exclusive": end.isoformat(),
        "requested_tickers": tickers,
        "rows": 0,
        "matched_quantity_sum": 0,
        "tickers_found": [],
        "first_minute": None,
        "last_minute": None,
        "duplicate_keys": 0,
        "missing_ohlc_rows": 0,
        "invalid_ohlc_rows": 0,
        "invalid_quantity_rows": 0,
        "file": str(output_path),
    }
    seen_tickers: set[str] = set()
    previous_key: tuple[Any, Any] | None = None

    print(f"RUN  {label}: {start} <= event_time < {end}", flush=True)
    try:
        cursor_name = f"minute_export_{start.year}_{start.month:02d}"
        with conn.cursor(name=cursor_name) as cursor:
            cursor.itersize = fetch_size
            cursor.execute(
                query,
                {"start_time": start, "end_time": end, "tickers": tickers},
            )
            headers = [description.name for description in cursor.description]
            column_index = {name: index for index, name in enumerate(headers)}
            required = {
                "minute", "tickersymbol", "matched_open", "matched_high",
                "matched_low", "matched_close", "matched_quantity",
            }
            missing = required.difference(column_index)
            if missing:
                raise RuntimeError(f"Query is missing required columns: {sorted(missing)}")

            with gzip.open(temporary_path, "wt", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(headers)

                while True:
                    rows = cursor.fetchmany(fetch_size)
                    if not rows:
                        break
                    for row in rows:
                        writer.writerow(row)
                        stats["rows"] += 1

                        minute = row[column_index["minute"]]
                        ticker = row[column_index["tickersymbol"]]
                        seen_tickers.add(ticker)
                        if stats["first_minute"] is None or minute < stats["first_minute"]:
                            stats["first_minute"] = minute
                        if stats["last_minute"] is None or minute > stats["last_minute"]:
                            stats["last_minute"] = minute

                        key = (ticker, minute)
                        if key == previous_key:
                            stats["duplicate_keys"] += 1
                        previous_key = key

                        quantity = row[column_index["matched_quantity"]]
                        if quantity is not None:
                            stats["matched_quantity_sum"] += int(quantity)

                        for problem in validate_row(row, column_index):
                            stats[f"{problem}_rows"] += 1

        if stats["duplicate_keys"]:
            raise RuntimeError(
                f"Found {stats['duplicate_keys']} duplicate (ticker, minute) keys"
            )
        if stats["invalid_ohlc_rows"] or stats["invalid_quantity_rows"]:
            raise RuntimeError(
                "Validation failed: "
                f"invalid OHLC={stats['invalid_ohlc_rows']}, "
                f"invalid quantity={stats['invalid_quantity_rows']}"
            )

        stats["tickers_found"] = sorted(seen_tickers)
        stats["missing_tickers"] = sorted(set(tickers).difference(seen_tickers))
        stats["status"] = "complete"
        os.replace(temporary_path, output_path)
        metadata_path.write_text(
            json.dumps(stats, indent=2, default=json_value) + "\n",
            encoding="utf-8",
        )
        conn.commit()
        warning = ""
        if stats["missing_tickers"]:
            warning = f"; missing tickers={','.join(stats['missing_tickers'])}"
        print(
            f"DONE {label}: {stats['rows']:,} rows -> {output_path}{warning}",
            flush=True,
        )
        return stats
    except Exception:
        conn.rollback()
        if temporary_path.exists():
            temporary_path.unlink()
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backfill one-minute bars from PostgreSQL month by month."
    )
    parser.add_argument("--start-date", type=parse_date, default=date(2022, 1, 1))
    parser.add_argument(
        "--end-date",
        type=parse_date,
        default=date(2026, 7, 17),
        help="Exclusive end date (default: 2026-07-17)",
    )
    parser.add_argument(
        "--tickers",
        nargs="+",
        default=DEFAULT_TICKERS,
        help="Space-separated ticker symbols",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("data/minute_bars")
    )
    parser.add_argument(
        "--query", type=Path, default=Path("grid_minute_export_query.sql")
    )
    parser.add_argument("--fetch-size", type=int, default=10_000)
    parser.add_argument(
        "--statement-timeout",
        default=None,
        help=(
            "PostgreSQL timeout for each monthly query, such as 60min. "
            "By default, use the server setting; use 0 only for no timeout."
        ),
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace completed monthly files (default: skip them)",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.start_date >= args.end_date:
        raise SystemExit("--start-date must be before --end-date")
    if args.fetch_size <= 0:
        raise SystemExit("--fetch-size must be positive")
    if not args.query.exists():
        raise SystemExit(f"Query file not found: {args.query}")

    try:
        import psycopg
    except ImportError:
        raise SystemExit(
            "Missing psycopg. Install it with: "
            "python3 -m pip install -r requirements-backfill.txt"
        ) from None

    args.output_dir.mkdir(parents=True, exist_ok=True)
    query = args.query.read_text(encoding="utf-8")
    tickers = list(dict.fromkeys(ticker.upper() for ticker in args.tickers))
    connection_string = os.environ.get("DATABASE_URL", "")

    try:
        with psycopg.connect(connection_string) as conn:
            if args.statement_timeout is not None:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT set_config('statement_timeout', %s, false)",
                        (args.statement_timeout,),
                    )
                conn.commit()
                print(
                    f"PostgreSQL statement timeout: {args.statement_timeout}",
                    flush=True,
                )
            for window_start, window_end in month_windows(
                args.start_date, args.end_date
            ):
                export_month(
                    conn=conn,
                    query=query,
                    output_dir=args.output_dir,
                    start=window_start,
                    end=window_end,
                    tickers=tickers,
                    fetch_size=args.fetch_size,
                    overwrite=args.overwrite,
                )
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        print("Fix the issue and rerun; completed months will be skipped.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
