#!/usr/bin/env python3
"""Create disjoint research roles for the sector-rotation reimplementation.

This manifest separates selector *development* from all trading evaluation.
The frozen selector may later calculate point-in-time features using history
available before a deployment, but its formula, thresholds and lookback may
only be chosen with ``selector_development`` rows.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path


DEFAULT_TICKERS = (
    "HPG",
    "MBB",
    "MWG",
    "SSI",
    "TCB",
    "VCB",
    "VND",
    "VPB",
)
REQUIRED_COLUMNS = {"datetime", "tickersymbol", "primary_split"}
TRADING_ROLES = {"in_sample", "optimization", "out_of_sample"}


@dataclass(frozen=True)
class Boundaries:
    selector_end: date = date(2022, 12, 30)
    in_sample_end: date = date(2023, 12, 29)
    optimization_end: date = date(2024, 12, 31)
    out_of_sample_end: date = date(2025, 6, 30)

    def validate(self) -> None:
        values = (
            self.selector_end,
            self.in_sample_end,
            self.optimization_end,
            self.out_of_sample_end,
        )
        if tuple(sorted(values)) != values or len(set(values)) != len(values):
            raise ValueError("Split boundaries must be strictly increasing")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def role_for(
    trading_date: date,
    primary_split: str,
    boundaries: Boundaries,
) -> str:
    if primary_split == "final_test":
        return "locked_final_test"
    if primary_split != "development":
        raise ValueError(f"Unexpected primary split: {primary_split!r}")
    if trading_date <= boundaries.selector_end:
        return "selector_development"
    if trading_date <= boundaries.in_sample_end:
        return "in_sample"
    if trading_date <= boundaries.optimization_end:
        return "optimization"
    if trading_date <= boundaries.out_of_sample_end:
        return "out_of_sample"
    return "unused_buffer"


def read_roles(
    input_path: Path,
    tickers: tuple[str, ...],
    boundaries: Boundaries,
) -> dict[date, str]:
    boundaries.validate()
    requested = set(tickers)
    rows_by_date: dict[date, dict[str, str]] = defaultdict(dict)

    with input_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        headers = set(reader.fieldnames or [])
        missing = REQUIRED_COLUMNS.difference(headers)
        if missing:
            raise ValueError(f"Input is missing columns: {sorted(missing)}")
        for row in reader:
            ticker = row["tickersymbol"].strip().upper()
            if ticker not in requested:
                continue
            trading_date = date.fromisoformat(row["datetime"].strip())
            if ticker in rows_by_date[trading_date]:
                raise ValueError(
                    f"Duplicate {ticker} row on {trading_date}"
                )
            rows_by_date[trading_date][ticker] = row["primary_split"].strip()

    if not rows_by_date:
        raise ValueError("No requested ticker rows were found")

    roles: dict[date, str] = {}
    for trading_date, rows in sorted(rows_by_date.items()):
        present = set(rows)
        if present != requested:
            raise ValueError(
                f"Incomplete universe on {trading_date}: "
                f"missing={sorted(requested - present)}, "
                f"extra={sorted(present - requested)}"
            )
        primary_splits = set(rows.values())
        if len(primary_splits) != 1:
            raise ValueError(
                f"Mixed primary splits on {trading_date}: "
                f"{sorted(primary_splits)}"
            )
        roles[trading_date] = role_for(
            trading_date, primary_splits.pop(), boundaries
        )
    return roles


def audit_roles(
    roles: dict[date, str],
    tickers: tuple[str, ...],
    input_path: Path,
    boundaries: Boundaries,
) -> dict[str, object]:
    dates_by_role: dict[str, list[date]] = defaultdict(list)
    for trading_date, role in roles.items():
        dates_by_role[role].append(trading_date)

    required = {
        "selector_development",
        "in_sample",
        "optimization",
        "out_of_sample",
        "locked_final_test",
    }
    missing_roles = required.difference(dates_by_role)
    if missing_roles:
        raise ValueError(f"Empty required roles: {sorted(missing_roles)}")

    selector_dates = set(dates_by_role["selector_development"])
    trading_dates = {
        trading_date
        for role in TRADING_ROLES
        for trading_date in dates_by_role[role]
    }
    overlap = sorted(selector_dates.intersection(trading_dates))
    if overlap:
        raise ValueError(
            f"Selector-development/trading overlap detected: {overlap[:5]}"
        )

    role_summary: dict[str, dict[str, object]] = {}
    for role, dates in sorted(dates_by_role.items()):
        role_summary[role] = {
            "first_date": min(dates).isoformat(),
            "last_date": max(dates).isoformat(),
            "sessions": len(dates),
            "rows": len(dates) * len(tickers),
        }

    return {
        "schema_version": "sector_rotation_splits.v1",
        "input_path": str(input_path),
        "input_sha256": sha256_file(input_path),
        "tickers": list(tickers),
        "boundaries": {
            "selector_end": boundaries.selector_end.isoformat(),
            "in_sample_end": boundaries.in_sample_end.isoformat(),
            "optimization_end": boundaries.optimization_end.isoformat(),
            "out_of_sample_end": boundaries.out_of_sample_end.isoformat(),
        },
        "roles": role_summary,
        "selector_trading_overlap_sessions": len(overlap),
        "selector_is_disjoint_from_all_trading_evaluation": not overlap,
        "locked_period_opened_by_this_script": False,
    }


def write_outputs(
    output_dir: Path,
    roles: dict[date, str],
    audit: dict[str, object],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    assignment_path = output_dir / "date_assignments.csv"
    with assignment_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=("trading_date", "research_role")
        )
        writer.writeheader()
        for trading_date, role in sorted(roles.items()):
            writer.writerow(
                {
                    "trading_date": trading_date.isoformat(),
                    "research_role": role,
                }
            )
    (output_dir / "split_audit.json").write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create disjoint sector-rotation research splits."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data_algotradeDB_split.csv"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/sector_rotation_splits"),
    )
    parser.add_argument(
        "--tickers",
        nargs="+",
        default=list(DEFAULT_TICKERS),
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    tickers = tuple(sorted(set(value.upper() for value in args.tickers)))
    boundaries = Boundaries()
    roles = read_roles(args.input, tickers, boundaries)
    audit = audit_roles(roles, tickers, args.input, boundaries)
    write_outputs(args.output_dir, roles, audit)
    print(json.dumps(audit, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
