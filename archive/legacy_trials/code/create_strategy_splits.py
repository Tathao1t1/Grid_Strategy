#!/usr/bin/env python3
"""Create leakage-safe walk-forward date splits for the grid strategy.

This script does not duplicate the large minute-bar dataset. It creates a
small date manifest that the daily-feature code and minute backtester can both
use:

* Rolling 12-calendar-month in-sample window.
* Immediately following 2-calendar-month out-of-sample window.
* Non-overlapping out-of-sample windows.
* Existing ``final_test`` period preserved as a completely untouched holdout.

The ticker list is a fixed research universe. A downstream study may either
trade those names directly or perform point-in-time selection inside each
training fold.
"""

from __future__ import annotations

import argparse
import calendar
import csv
import json
from collections import defaultdict
from datetime import date
from pathlib import Path


DEFAULT_TICKERS = ("VCB", "VPB")
REQUIRED_COLUMNS = {"datetime", "tickersymbol", "primary_split"}


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date {value!r}; use YYYY-MM-DD"
        ) from exc


def month_start(value: date) -> date:
    return date(value.year, value.month, 1)


def add_months(value: date, months: int) -> date:
    """Add whole calendar months to a first-of-month date."""
    total = value.year * 12 + (value.month - 1) + months
    return date(total // 12, total % 12 + 1, 1)


def shift_date_by_months(value: date, months: int) -> date:
    """Shift a date by calendar months while preserving its day when possible."""
    total = value.year * 12 + (value.month - 1) + months
    year = total // 12
    month = total % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create rolling in-sample/out-of-sample strategy folds."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data_algotradeDB_split.csv"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/strategy_splits"),
    )
    parser.add_argument(
        "--tickers",
        nargs="+",
        default=list(DEFAULT_TICKERS),
    )
    parser.add_argument(
        "--train-months",
        type=int,
        default=12,
        help="Rolling in-sample calendar months (default: 12)",
    )
    parser.add_argument(
        "--oos-months",
        type=int,
        default=2,
        help="Non-overlapping validation months per fold (default: 2)",
    )
    parser.add_argument(
        "--selection-mode",
        choices=("fixed_prototype", "point_in_time_rotation"),
        default="fixed_prototype",
        help=(
            "Describe whether downstream tickers remain fixed or are selected "
            "again using each fold's in-sample rows."
        ),
    )
    return parser


def read_split_dates(
    path: Path, requested_tickers: set[str]
) -> tuple[dict[str, dict[str, set[date]]], list[str]]:
    """Read only dates and split labels; no price is used to define folds."""
    if not path.exists():
        raise FileNotFoundError(f"Input not found: {path}")

    dates: dict[str, dict[str, set[date]]] = defaultdict(
        lambda: defaultdict(set)
    )
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames or []
        missing = REQUIRED_COLUMNS.difference(headers)
        if missing:
            raise ValueError(f"Input is missing columns: {sorted(missing)}")

        for row in reader:
            ticker = row["tickersymbol"].strip().upper()
            if ticker not in requested_tickers:
                continue
            split = row["primary_split"].strip()
            if split not in {"development", "final_test"}:
                raise ValueError(f"Unexpected primary_split: {split!r}")
            dates[split][ticker].add(date.fromisoformat(row["datetime"]))

    available = sorted(
        set(dates["development"]).intersection(dates["final_test"])
    )
    if set(available) != requested_tickers:
        missing_tickers = sorted(requested_tickers.difference(available))
        raise ValueError(f"Tickers missing from one or both splits: {missing_tickers}")
    return dates, available


def common_dates(
    split_dates: dict[str, set[date]], tickers: list[str], split: str
) -> list[date]:
    """Require identical trading calendars for fair multi-ticker folds."""
    base = split_dates[tickers[0]]
    for ticker in tickers[1:]:
        if split_dates[ticker] != base:
            only_base = sorted(base.difference(split_dates[ticker]))
            only_ticker = sorted(split_dates[ticker].difference(base))
            raise ValueError(
                f"{split} calendars differ for {tickers[0]} and {ticker}: "
                f"missing={only_base[:3]}, extra={only_ticker[:3]}"
            )
    return sorted(base)


def create_folds(
    development_dates: list[date],
    train_months: int,
    oos_months: int,
) -> list[dict[str, object]]:
    """Create rolling training windows and non-overlapping future OOS windows."""
    if train_months < 3:
        raise ValueError("train_months must be at least 3")
    if oos_months < 1:
        raise ValueError("oos_months must be positive")

    first_development_month = month_start(development_dates[0])
    # Only complete calendar months are eligible for OOS validation.
    first_incomplete_month = month_start(development_dates[-1])
    first_oos_boundary = add_months(first_development_month, train_months)

    folds: list[dict[str, object]] = []
    oos_boundary = first_oos_boundary
    fold_id = 1

    while add_months(oos_boundary, oos_months) <= first_incomplete_month:
        train_boundary = add_months(oos_boundary, -train_months)
        oos_end_boundary = add_months(oos_boundary, oos_months)

        train_dates = [
            value
            for value in development_dates
            if train_boundary <= value < oos_boundary
        ]
        oos_dates = [
            value
            for value in development_dates
            if oos_boundary <= value < oos_end_boundary
        ]
        if not train_dates or not oos_dates:
            raise ValueError(
                f"Empty dates while building fold {fold_id}: "
                f"{train_boundary} / {oos_boundary}"
            )

        folds.append(
            {
                "fold_id": f"wf_{fold_id:02d}",
                "train_boundary_start": train_boundary,
                "train_start": train_dates[0],
                "train_end": train_dates[-1],
                "oos_boundary_start": oos_boundary,
                "oos_start": oos_dates[0],
                "oos_end": oos_dates[-1],
                "oos_boundary_end_exclusive": oos_end_boundary,
                "train_sessions": len(train_dates),
                "oos_sessions": len(oos_dates),
                "train_dates": train_dates,
                "oos_dates": oos_dates,
            }
        )
        fold_id += 1
        oos_boundary = add_months(oos_boundary, oos_months)
    return folds


def write_fold_summary(
    path: Path, folds: list[dict[str, object]], tickers: list[str]
) -> None:
    headers = [
        "fold_id",
        "train_boundary_start",
        "train_start",
        "train_end",
        "oos_boundary_start",
        "oos_start",
        "oos_end",
        "oos_boundary_end_exclusive",
        "train_sessions",
        "oos_sessions",
        "tickers",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for fold in folds:
            writer.writerow(
                {
                    key: (
                        fold[key].isoformat()
                        if isinstance(fold[key], date)
                        else fold[key]
                    )
                    for key in headers
                    if key != "tickers"
                }
                | {"tickers": "|".join(tickers)}
            )


def write_date_assignments(
    path: Path, folds: list[dict[str, object]]
) -> None:
    """One row per fold/date/role, suitable for joining to market data."""
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["fold_id", "trading_date", "role"]
        )
        writer.writeheader()
        for fold in folds:
            for trading_date in fold["train_dates"]:
                writer.writerow(
                    {
                        "fold_id": fold["fold_id"],
                        "trading_date": trading_date.isoformat(),
                        "role": "in_sample",
                    }
                )
            for trading_date in fold["oos_dates"]:
                writer.writerow(
                    {
                        "fold_id": fold["fold_id"],
                        "trading_date": trading_date.isoformat(),
                        "role": "walk_forward_oos",
                    }
                )


def main() -> int:
    args = build_parser().parse_args()
    tickers = list(dict.fromkeys(ticker.upper() for ticker in args.tickers))
    split_dates, tickers = read_split_dates(args.input, set(tickers))

    development_dates = common_dates(
        split_dates["development"], tickers, "development"
    )
    final_test_dates = common_dates(
        split_dates["final_test"], tickers, "final_test"
    )
    if development_dates[-1] >= final_test_dates[0]:
        raise ValueError("Development and final-test dates overlap")

    folds = create_folds(
        development_dates,
        train_months=args.train_months,
        oos_months=args.oos_months,
    )
    if not folds:
        raise ValueError("No complete walk-forward folds could be created")

    # Verify that walk-forward OOS windows never overlap one another.
    seen_oos_dates: set[date] = set()
    for fold in folds:
        overlap = seen_oos_dates.intersection(fold["oos_dates"])
        if overlap:
            raise ValueError(f"Overlapping OOS dates: {sorted(overlap)[:3]}")
        seen_oos_dates.update(fold["oos_dates"])

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_fold_summary(
        args.output_dir / "walk_forward_folds.csv", folds, tickers
    )
    write_date_assignments(
        args.output_dir / "walk_forward_date_assignments.csv", folds
    )

    final_config_training_start = shift_date_by_months(
        final_test_dates[0], -args.train_months
    )
    final_config_training_dates = [
        value
        for value in development_dates
        if final_config_training_start <= value < final_test_dates[0]
    ]

    last_oos_date = max(fold["oos_end"] for fold in folds)
    unused_development_tail = [
        value for value in development_dates if value > last_oos_date
    ]
    audit = {
        "input": str(args.input),
        "tickers": tickers,
        "policy": {
            "train_months": args.train_months,
            "oos_months": args.oos_months,
            "window_type": "rolling",
            "oos_windows_overlap": False,
            "split_by": "global trading date",
        },
        "walk_forward": {
            "fold_count": len(folds),
            "first_oos_start": folds[0]["oos_start"].isoformat(),
            "last_oos_end": folds[-1]["oos_end"].isoformat(),
            "total_unique_oos_sessions": len(seen_oos_dates),
            "unused_development_tail": [
                value.isoformat() for value in unused_development_tail
            ],
        },
        "final_parameter_training": {
            "start": final_config_training_dates[0].isoformat(),
            "end": final_config_training_dates[-1].isoformat(),
            "sessions": len(final_config_training_dates),
            "purpose": (
                "After the rules are frozen using walk-forward results, fit "
                "the final parameter set here without reading final_test."
            ),
        },
        "final_holdout": {
            "start": final_test_dates[0].isoformat(),
            "end": final_test_dates[-1].isoformat(),
            "sessions": len(final_test_dates),
            "status": "LOCKED_DO_NOT_TUNE",
        },
        "leakage_guards": [
            "Every OOS period occurs strictly after its training period.",
            "OOS validation periods are non-overlapping.",
            "The existing final_test period is excluded from every fold.",
            "All tickers use the same global trading-date boundaries.",
        ],
        "selection_scope_note": (
            (
                f"{', '.join(tickers)} form a fixed research universe. "
                "The downstream rotation study must recompute eligibility "
                "and ranking independently inside every fold using only "
                "that fold's in-sample rows."
            )
            if args.selection_mode == "point_in_time_rotation"
            else (
                f"{', '.join(tickers)} "
                f"{'is a fixed prototype ticker' if len(tickers) == 1 else 'are fixed prototype tickers'}. "
                "The folds provide time-ordered strategy partitions but do "
                "not recreate point-in-time ticker selection."
            )
        )
        + " The final holdout remains locked and is not assigned to a fold.",
    }
    (args.output_dir / "split_audit.json").write_text(
        json.dumps(audit, indent=2) + "\n", encoding="utf-8"
    )

    print(
        f"Created {len(folds)} rolling folds for {', '.join(tickers)}: "
        f"{args.train_months} months IS / {args.oos_months} months OOS"
    )
    print(
        f"Walk-forward OOS: {audit['walk_forward']['first_oos_start']} to "
        f"{audit['walk_forward']['last_oos_end']} "
        f"({len(seen_oos_dates)} unique sessions)"
    )
    print(
        f"FINAL HOLDOUT LOCKED: {audit['final_holdout']['start']} to "
        f"{audit['final_holdout']['end']} "
        f"({audit['final_holdout']['sessions']} sessions)"
    )
    print(f"Outputs: {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
