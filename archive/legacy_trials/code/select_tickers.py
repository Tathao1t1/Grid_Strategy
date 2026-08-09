#!/usr/bin/env python3
"""Select grid-trading candidates using training data only.

The algorithm is intentionally simple and explainable:

1. Read the existing ``primary_split`` column.
2. Put ``development`` rows into training and keep ``final_test`` untouched.
3. Use an aligned 10-session lookback, refreshed every 5 sessions.
4. Calculate Efficiency Ratio (ER), return, and high-low range per block.
5. Exclude windows containing a detected corporate-action/reference reset.
6. Label valid windows as sideways, uptrend, or downtrend, and separately
   flag sudden deep downtrends.
7. Count the training regimes for each ticker and apply transparent rules.

No value from the final-test period is used to calculate a regime, threshold,
score, ranking, or selected ticker.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Iterable


REGIMES = (
    "oscillating_sideways",
    "quiet_sideways",
    "uptrend",
    "downtrend",
)

REQUIRED_COLUMNS = {
    "datetime",
    "tickersymbol",
    "open",
    "high",
    "low",
    "close",
    "ceiling",
    "floor",
    "primary_split",
}


@dataclass(frozen=True)
class DailyPrice:
    """Only the daily fields required by the selection algorithm."""

    trading_date: date
    ticker: str
    open: float
    high: float
    low: float
    close: float
    ceiling: float | None
    floor: float | None
    reference_reset: bool = False


@dataclass(frozen=True)
class RegimePeriod:
    """Calculated result for one ticker in one aligned training block."""

    period_id: int
    ticker: str
    start_date: date
    end_date: date
    sessions: int
    start_close: float
    end_close: float
    efficiency_ratio: float
    period_return: float
    range_pct: float
    regime: str
    reference_reset_detected: bool


def parse_fraction(value: str) -> float:
    """Parse a command-line fraction and reject percentages such as 35."""
    parsed = float(value)
    if not 0.0 <= parsed <= 1.0:
        raise argparse.ArgumentTypeError(
            f"Expected a fraction between 0 and 1, received {value!r}"
        )
    return parsed


def parse_negative_fraction(value: str) -> float:
    parsed = float(value)
    if not -1.0 < parsed < 0.0:
        raise argparse.ArgumentTypeError(
            f"Expected a negative fraction between -1 and 0, received {value!r}"
        )
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rank grid candidates using development rows only."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data_algotradeDB_split.csv"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/ticker_selection"),
    )
    parser.add_argument(
        "--block-size",
        type=int,
        default=10,
        help="Trading sessions in each regime lookback window (default: 10)",
    )
    parser.add_argument(
        "--step-size",
        type=int,
        default=5,
        help=(
            "Sessions between measurements (default: 5, so a 10-session "
            "ER is refreshed approximately weekly)"
        ),
    )
    parser.add_argument(
        "--er-threshold",
        type=parse_fraction,
        default=0.35,
        help="ER below this is sideways; otherwise trending (default: 0.35)",
    )
    parser.add_argument(
        "--min-range-pct",
        type=parse_fraction,
        default=0.012,
        help=(
            "Minimum two-week high-low range for useful sideways movement "
            "as a fraction (default: 0.012 = 1.2%%)"
        ),
    )
    parser.add_argument(
        "--min-oscillating-pct",
        type=parse_fraction,
        default=0.35,
        help="Minimum oscillating-sideways share (default: 0.35)",
    )
    parser.add_argument(
        "--max-downtrend-pct",
        type=parse_fraction,
        default=0.25,
        help="Maximum downtrend share (default: 0.25)",
    )
    parser.add_argument(
        "--deep-downtrend-return",
        type=parse_negative_fraction,
        default=-0.08,
        help=(
            "A downtrend window at or below this return is deep "
            "(default: -0.08 = -8%%)"
        ),
    )
    parser.add_argument(
        "--max-deep-downtrend-pct",
        type=parse_fraction,
        default=0.05,
        help="Maximum share of deep-downtrend windows (default: 0.05)",
    )
    parser.add_argument(
        "--min-favorable-pct",
        type=parse_fraction,
        default=0.60,
        help="Minimum sideways-plus-uptrend share (default: 0.60)",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=0,
        help="Keep only the top N eligible tickers; 0 keeps all eligible",
    )
    return parser


def read_source(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")

    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames or []
        missing = REQUIRED_COLUMNS.difference(headers)
        if missing:
            raise ValueError(f"Input is missing columns: {sorted(missing)}")
        rows = list(reader)

    if not rows:
        raise ValueError("Input file contains no data rows")
    return headers, rows


def split_rows(
    rows: Iterable[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Perform the hard leakage boundary before any feature calculation."""
    training: list[dict[str, str]] = []
    test: list[dict[str, str]] = []

    for row in rows:
        split = row["primary_split"].strip()
        if split == "development":
            training.append(row)
        elif split == "final_test":
            test.append(row)
        else:
            raise ValueError(f"Unexpected primary_split value: {split!r}")

    if not training or not test:
        raise ValueError("Both development and final_test rows are required")

    last_train_date = max(date.fromisoformat(row["datetime"]) for row in training)
    first_test_date = min(date.fromisoformat(row["datetime"]) for row in test)
    if last_train_date >= first_test_date:
        raise ValueError(
            "Leakage risk: training dates overlap or follow final-test dates"
        )
    return training, test


def write_split(
    path: Path, headers: list[str], rows: list[dict[str, str]]
) -> None:
    """Write explicit split files so the held-out boundary is easy to audit."""
    ordered = sorted(rows, key=lambda row: (row["datetime"], row["tickersymbol"]))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(ordered)


def parse_training_rows(rows: Iterable[dict[str, str]]) -> list[DailyPrice]:
    """Convert training rows and identify exchange reference-price resets.

    On an ordinary day, today's exchange reference price is approximately
    yesterday's close. We estimate today's reference as the midpoint of its
    ceiling and floor. A difference greater than 2% from yesterday's close is
    treated as a corporate-action/reference reset. Windows containing that
    boundary are excluded instead of being mislabeled as deep market crashes.
    """
    parsed: list[DailyPrice] = []
    seen_keys: set[tuple[str, date]] = set()

    for row in rows:
        trading_date = date.fromisoformat(row["datetime"])
        ticker = row["tickersymbol"].strip().upper()
        key = (ticker, trading_date)
        if key in seen_keys:
            raise ValueError(f"Duplicate training key: {ticker} {trading_date}")
        seen_keys.add(key)

        open_price = float(row["open"])
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        if not all(
            math.isfinite(value) and value > 0
            for value in (open_price, high, low, close)
        ):
            raise ValueError(f"Invalid price for {ticker} on {trading_date}")
        if high < max(open_price, low, close) or low > min(open_price, close):
            raise ValueError(f"Invalid OHLC relationship for {ticker} on {trading_date}")

        ceiling = float(row["ceiling"]) if row["ceiling"].strip() else None
        floor = float(row["floor"]) if row["floor"].strip() else None
        parsed.append(
            DailyPrice(
                trading_date=trading_date,
                ticker=ticker,
                open=open_price,
                high=high,
                low=low,
                close=close,
                ceiling=ceiling,
                floor=floor,
            )
        )

    by_ticker: dict[str, list[DailyPrice]] = defaultdict(list)
    for daily in parsed:
        by_ticker[daily.ticker].append(daily)

    with_reset_flags: list[DailyPrice] = []
    for ticker_rows in by_ticker.values():
        ticker_rows.sort(key=lambda daily: daily.trading_date)
        previous: DailyPrice | None = None
        for daily in ticker_rows:
            implied_reference = (
                (daily.ceiling + daily.floor) / 2.0
                if daily.ceiling is not None and daily.floor is not None
                else None
            )
            reference_reset = bool(
                previous is not None
                and implied_reference is not None
                and abs(implied_reference / previous.close - 1.0) > 0.02
            )
            with_reset_flags.append(
                replace(daily, reference_reset=reference_reset)
            )
            previous = daily
    return with_reset_flags


def aligned_date_blocks(
    training: list[DailyPrice], block_size: int, step_size: int
) -> tuple[list[list[date]], list[date]]:
    """Build identical trailing windows for every ticker, anchored at cutoff.

    With block_size=10 and step_size=5, each observation measures roughly two
    trading weeks and the classification is refreshed roughly once per week.
    Anchoring at the cutoff preserves the latest available training window.
    """
    if block_size < 3:
        raise ValueError("block_size must be at least 3 sessions")
    if step_size < 1 or step_size > block_size:
        raise ValueError("step_size must be between 1 and block_size")

    dates = sorted({row.trading_date for row in training})
    if len(dates) < block_size:
        raise ValueError("Training set is shorter than one regime window")

    # Work backward from the cutoff, then reverse into chronological order.
    # This avoids discarding the freshest training observations.
    blocks_reversed: list[list[date]] = []
    end = len(dates)
    while end >= block_size:
        blocks_reversed.append(dates[end - block_size : end])
        end -= step_size
    blocks = list(reversed(blocks_reversed))
    unused_dates = dates[: max(0, end)]
    return blocks, unused_dates


def classify_period(
    ticker: str,
    period_id: int,
    rows: list[DailyPrice],
    er_threshold: float,
    min_range_pct: float,
) -> RegimePeriod:
    """Calculate the three simple measurements and assign one regime."""
    rows = sorted(rows, key=lambda row: row.trading_date)
    closes = [row.close for row in rows]

    # ER compares straight-line movement with the entire path traveled.
    direct_move = abs(closes[-1] - closes[0])
    path_length = sum(
        abs(current - previous)
        for previous, current in zip(closes, closes[1:])
    )
    efficiency_ratio = direct_move / path_length if path_length > 0 else 0.0

    period_return = closes[-1] / closes[0] - 1.0
    range_pct = (max(row.high for row in rows) - min(row.low for row in rows)) / closes[0]

    reference_reset_detected = any(row.reference_reset for row in rows)
    if reference_reset_detected:
        regime = "excluded_reference_reset"
    elif efficiency_ratio < er_threshold:
        regime = (
            "oscillating_sideways"
            if range_pct >= min_range_pct
            else "quiet_sideways"
        )
    elif period_return > 0:
        regime = "uptrend"
    else:
        regime = "downtrend"

    return RegimePeriod(
        period_id=period_id,
        ticker=ticker,
        start_date=rows[0].trading_date,
        end_date=rows[-1].trading_date,
        sessions=len(rows),
        start_close=closes[0],
        end_close=closes[-1],
        efficiency_ratio=efficiency_ratio,
        period_return=period_return,
        range_pct=range_pct,
        regime=regime,
        reference_reset_detected=reference_reset_detected,
    )


def calculate_training_regimes(
    training: list[DailyPrice],
    blocks: list[list[date]],
    er_threshold: float,
    min_range_pct: float,
) -> list[RegimePeriod]:
    """Calculate regimes without accepting or accessing any final-test rows."""
    by_ticker_date = {
        (row.ticker, row.trading_date): row
        for row in training
    }
    tickers = sorted({row.ticker for row in training})
    results: list[RegimePeriod] = []

    for period_id, block_dates in enumerate(blocks, start=1):
        for ticker in tickers:
            period_rows = [
                by_ticker_date[(ticker, trading_date)]
                for trading_date in block_dates
                if (ticker, trading_date) in by_ticker_date
            ]
            if len(period_rows) != len(block_dates):
                raise ValueError(
                    f"Missing training session in period {period_id} for {ticker}; "
                    "aligned comparison would be invalid"
                )
            results.append(
                classify_period(
                    ticker=ticker,
                    period_id=period_id,
                    rows=period_rows,
                    er_threshold=er_threshold,
                    min_range_pct=min_range_pct,
                )
            )
    return results


def summarize_tickers(
    periods: list[RegimePeriod],
    min_oscillating_pct: float,
    max_downtrend_pct: float,
    deep_downtrend_return: float,
    max_deep_downtrend_pct: float,
    min_favorable_pct: float,
) -> list[dict[str, object]]:
    by_ticker: dict[str, list[RegimePeriod]] = defaultdict(list)
    for period in periods:
        by_ticker[period.ticker].append(period)

    summaries: list[dict[str, object]] = []
    for ticker, all_ticker_periods in by_ticker.items():
        ticker_periods = [
            period for period in all_ticker_periods if period.regime in REGIMES
        ]
        excluded_reference_resets = len(all_ticker_periods) - len(ticker_periods)
        if not ticker_periods:
            raise ValueError(f"No valid regime periods remain for {ticker}")

        counts = Counter(period.regime for period in ticker_periods)
        total = len(ticker_periods)
        percentages = {regime: counts[regime] / total for regime in REGIMES}
        favorable_pct = percentages["oscillating_sideways"] + percentages["uptrend"]
        deep_downtrend_count = sum(
            period.regime == "downtrend"
            and period.period_return <= deep_downtrend_return
            for period in ticker_periods
        )
        deep_downtrend_pct = deep_downtrend_count / total
        worst_period_return = min(period.period_return for period in ticker_periods)

        # Simple score: sideways receives full credit, uptrend partial credit,
        # while downtrend and unprofitable quiet markets are penalized.
        score = (
            percentages["oscillating_sideways"]
            + 0.50 * percentages["uptrend"]
            - percentages["downtrend"]
            - 0.50 * percentages["quiet_sideways"]
            - deep_downtrend_pct
        )
        eligible = (
            percentages["oscillating_sideways"] >= min_oscillating_pct
            and percentages["downtrend"] <= max_downtrend_pct
            and deep_downtrend_pct <= max_deep_downtrend_pct
            and favorable_pct >= min_favorable_pct
        )

        summaries.append(
            {
                "tickersymbol": ticker,
                "observed_windows": len(all_ticker_periods),
                "total_periods": total,
                "excluded_reference_reset_count": excluded_reference_resets,
                "oscillating_sideways_count": counts["oscillating_sideways"],
                "quiet_sideways_count": counts["quiet_sideways"],
                "uptrend_count": counts["uptrend"],
                "downtrend_count": counts["downtrend"],
                "deep_downtrend_count": deep_downtrend_count,
                "oscillating_sideways_pct": percentages["oscillating_sideways"],
                "quiet_sideways_pct": percentages["quiet_sideways"],
                "uptrend_pct": percentages["uptrend"],
                "downtrend_pct": percentages["downtrend"],
                "deep_downtrend_pct": deep_downtrend_pct,
                "favorable_pct": favorable_pct,
                "worst_valid_period_return": worst_period_return,
                "selection_score": score,
                "eligible": eligible,
            }
        )

    return sorted(
        summaries,
        key=lambda row: (-float(row["selection_score"]), str(row["tickersymbol"])),
    )


def write_periods(path: Path, periods: list[RegimePeriod]) -> None:
    headers = [
        "period_id", "tickersymbol", "start_date", "end_date", "sessions",
        "start_close", "end_close", "efficiency_ratio", "period_return",
        "range_pct", "regime", "reference_reset_detected",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for period in periods:
            writer.writerow(
                {
                    "period_id": period.period_id,
                    "tickersymbol": period.ticker,
                    "start_date": period.start_date.isoformat(),
                    "end_date": period.end_date.isoformat(),
                    "sessions": period.sessions,
                    "start_close": f"{period.start_close:.6f}",
                    "end_close": f"{period.end_close:.6f}",
                    "efficiency_ratio": f"{period.efficiency_ratio:.8f}",
                    "period_return": f"{period.period_return:.8f}",
                    "range_pct": f"{period.range_pct:.8f}",
                    "regime": period.regime,
                    "reference_reset_detected": period.reference_reset_detected,
                }
            )


def write_summary(path: Path, summaries: list[dict[str, object]]) -> None:
    headers = list(summaries[0])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for summary in summaries:
            output = summary.copy()
            for key in (
                "oscillating_sideways_pct", "quiet_sideways_pct", "uptrend_pct",
                "downtrend_pct", "deep_downtrend_pct", "favorable_pct",
                "worst_valid_period_return", "selection_score",
            ):
                output[key] = f"{float(output[key]):.6f}"
            writer.writerow(output)


def main() -> int:
    args = build_parser().parse_args()
    if args.block_size < 3:
        raise SystemExit("--block-size must be at least 3")
    if args.step_size < 1 or args.step_size > args.block_size:
        raise SystemExit("--step-size must be between 1 and --block-size")
    if args.top_n < 0:
        raise SystemExit("--top-n cannot be negative")

    headers, source_rows = read_source(args.input)

    # CRITICAL LEAKAGE BARRIER: split first. Only training_rows is passed to
    # parse_training_rows() and calculate_training_regimes().
    training_rows, test_rows = split_rows(source_rows)
    training = parse_training_rows(training_rows)

    blocks, unused_dates = aligned_date_blocks(
        training, args.block_size, args.step_size
    )
    periods = calculate_training_regimes(
        training=training,
        blocks=blocks,
        er_threshold=args.er_threshold,
        min_range_pct=args.min_range_pct,
    )
    summaries = summarize_tickers(
        periods=periods,
        min_oscillating_pct=args.min_oscillating_pct,
        max_downtrend_pct=args.max_downtrend_pct,
        deep_downtrend_return=args.deep_downtrend_return,
        max_deep_downtrend_pct=args.max_deep_downtrend_pct,
        min_favorable_pct=args.min_favorable_pct,
    )

    eligible = [summary for summary in summaries if bool(summary["eligible"])]
    selected = eligible[: args.top_n] if args.top_n else eligible
    selected_tickers = [str(summary["tickersymbol"]) for summary in selected]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_split(args.output_dir / "train_daily.csv", headers, training_rows)
    write_split(args.output_dir / "test_daily_HELD_OUT.csv", headers, test_rows)
    write_periods(args.output_dir / "training_regimes.csv", periods)
    write_summary(args.output_dir / "ticker_regime_summary.csv", summaries)
    (args.output_dir / "selected_tickers.txt").write_text(
        "\n".join(selected_tickers) + ("\n" if selected_tickers else ""),
        encoding="utf-8",
    )

    train_dates = sorted({row.trading_date for row in training})
    test_dates = sorted({date.fromisoformat(row["datetime"]) for row in test_rows})
    audit = {
        "input": str(args.input),
        "leakage_policy": (
            "Only primary_split=development rows were passed to regime "
            "calculation, summary, eligibility, score, ranking, and selection."
        ),
        "test_used_for_selection": False,
        "training_rows": len(training_rows),
        "training_start": train_dates[0].isoformat(),
        "training_end": train_dates[-1].isoformat(),
        "test_rows_held_out": len(test_rows),
        "test_start": test_dates[0].isoformat(),
        "test_end": test_dates[-1].isoformat(),
        "tickers": sorted({row.ticker for row in training}),
        "block_size_sessions": args.block_size,
        "step_size_sessions": args.step_size,
        "complete_training_blocks": len(blocks),
        "unused_training_dates": [value.isoformat() for value in unused_dates],
        "parameters": {
            "er_threshold": args.er_threshold,
            "min_range_pct": args.min_range_pct,
            "min_oscillating_pct": args.min_oscillating_pct,
            "max_downtrend_pct": args.max_downtrend_pct,
            "deep_downtrend_return": args.deep_downtrend_return,
            "max_deep_downtrend_pct": args.max_deep_downtrend_pct,
            "min_favorable_pct": args.min_favorable_pct,
            "top_n": args.top_n,
        },
        "selected_tickers": selected_tickers,
    }
    (args.output_dir / "selection_audit.json").write_text(
        json.dumps(audit, indent=2) + "\n",
        encoding="utf-8",
    )

    print(
        f"Training: {audit['training_start']} to {audit['training_end']} "
        f"({len(training_rows):,} rows)"
    )
    print(
        f"HELD OUT: {audit['test_start']} to {audit['test_end']} "
        f"({len(test_rows):,} rows; not used for selection)"
    )
    print(
        f"Regimes: {len(blocks)} complete blocks x "
        f"{len(audit['tickers'])} tickers = {len(periods):,} observations"
    )
    print("\nTraining-only ranking:")
    for rank, summary in enumerate(summaries, start=1):
        print(
            f"{rank:>2}. {summary['tickersymbol']}: "
            f"score={float(summary['selection_score']):.3f}, "
            f"sideways={float(summary['oscillating_sideways_pct']):.1%}, "
            f"up={float(summary['uptrend_pct']):.1%}, "
            f"down={float(summary['downtrend_pct']):.1%}, "
            f"deep={float(summary['deep_downtrend_pct']):.1%}, "
            f"eligible={summary['eligible']}"
        )
    print(f"\nSelected: {', '.join(selected_tickers) if selected_tickers else 'none'}")
    print(f"Outputs: {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
