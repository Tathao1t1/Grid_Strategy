#!/usr/bin/env python3
"""Leakage-safe in-sample edge study for Trial 3.

Trial 3 does not simulate a trading strategy. It tests whether a confirmed
pullback signal in VCB predicts cost-adjusted forward returns large enough to
justify building a later execution model.

The primary outcome is T+5 net return. T+3 and T+10 are diagnostic only.
Only VCB ``primary_split=development`` prices and fold ``role=in_sample``
dates are accepted.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import date
from pathlib import Path
from typing import Iterable, Sequence


TRIAL_ID = "TRIAL3-VCB-CONFIRMED-PULLBACK"
TICKER = "VCB"
PRICE_MULTIPLIER = 1_000
QUANTITY = 100
PRIMARY_HORIZON = 5
HORIZONS = (3, 5, 10)

DAILY_REQUIRED = {
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
ASSIGNMENT_REQUIRED = {"fold_id", "trading_date", "role"}

EVENT_BASE_FIELDS = (
    "event_id",
    "fold_id",
    "ticker",
    "signal_date",
    "entry_date",
    "feature_as_of",
    "entry_price_vnd",
    "entry_price",
    "opening_gap",
    "sma20",
    "sma50",
    "return_5_signal",
    "return_10_signal",
    "close_location",
    "atr14",
    "atr_fraction",
    "unverified_reference_days",
)
EVENT_HORIZON_FIELDS = tuple(
    field
    for horizon in HORIZONS
    for field in (
        f"exit_date_t{horizon}",
        f"exit_close_t{horizon}",
        f"gross_return_t{horizon}",
        f"net_pnl_vnd_t{horizon}",
        f"net_return_t{horizon}",
        f"double_cost_net_pnl_vnd_t{horizon}",
        f"double_cost_net_return_t{horizon}",
        f"mfe_t{horizon}",
        f"mae_t{horizon}",
    )
)
EVENT_PATH_FIELDS = (
    "locked_mae",
    "first_barrier",
    "barrier_date",
    "barrier_session_offset",
    "barrier_pre_settlement",
)
FOLD_CANDIDATE_FIELDS = (
    EVENT_BASE_FIELDS + EVENT_HORIZON_FIELDS + EVENT_PATH_FIELDS
)
UNIQUE_CANDIDATE_FIELDS = tuple(
    field for field in FOLD_CANDIDATE_FIELDS if field != "fold_id"
) + ("fold_memberships", "fold_membership_count")
PRIMARY_EVENT_FIELDS = UNIQUE_CANDIDATE_FIELDS + ("primary_sequence",)
QUARANTINED_FOLD_FIELDS = (
    "fold_id",
    "ticker",
    "signal_date",
    "entry_date",
    "reason",
    "reset_dates",
    "unverified_reference_dates",
)
QUARANTINED_UNIQUE_FIELDS = tuple(
    field for field in QUARANTINED_FOLD_FIELDS if field != "fold_id"
) + ("fold_memberships", "fold_membership_count")
FOLD_SUMMARY_FIELDS = (
    "fold_id",
    "primary_events",
    "mean_net_return_t5",
    "median_net_return_t5",
    "win_rate_t5",
    "profit_factor_t5",
    "evaluable_for_stability",
)


@dataclass(frozen=True)
class Config:
    ticker: str = TICKER
    quantity: int = QUANTITY

    sma_fast: int = 20
    sma_slow: int = 50
    atr_period: int = 14
    pullback_period: int = 5
    trend_return_period: int = 10

    pullback_return_min: float = -0.05
    pullback_return_max: float = -0.01
    trend_return_min: float = -0.07
    close_location_min: float = 0.60
    atr_fraction_max: float = 0.03

    commission_rate: float = 0.0015
    sell_tax_rate: float = 0.0010
    slippage_rate: float = 0.0005
    doubled_cost_multiplier: float = 2.0

    target_fraction: float = 0.015
    stop_fraction: float = 0.03
    locked_sessions: int = 2
    maximum_horizon: int = 10

    minimum_primary_events: int = 30
    minimum_years: int = 3
    minimum_events_per_year: int = 5
    minimum_mean_net_t5: float = 0.005
    minimum_median_net_t5: float = 0.0
    minimum_win_rate_t5: float = 0.55
    minimum_profit_factor_t5: float = 1.25
    minimum_doubled_mean_t5: float = 0.0
    minimum_doubled_profit_factor_t5: float = 1.0
    minimum_fold_events: int = 5
    minimum_positive_fold_fraction: float = 0.70
    minimum_locked_mae_p10: float = -0.05

    def validate(self) -> None:
        if self.ticker != TICKER:
            raise ValueError("Trial 3 is frozen for VCB only")
        if self.quantity != 100:
            raise ValueError("Trial 3 uses one 100-share research lot")
        if self.sma_slow < self.sma_fast:
            raise ValueError("Slow SMA must not be shorter than fast SMA")
        if self.maximum_horizon != max(HORIZONS):
            raise ValueError("Maximum horizon must remain T+10")
        if not (
            self.pullback_return_min
            < self.pullback_return_max
            < 0
        ):
            raise ValueError("Invalid pullback-return interval")


@dataclass(frozen=True)
class DailyBar:
    trading_date: date
    open_vnd: int
    high_vnd: int
    low_vnd: int
    close_vnd: int
    ceiling_vnd: int | None
    floor_vnd: int | None
    reference_reset: bool
    reference_available: bool
    reset_verifiable: bool


@dataclass(frozen=True)
class SignalFeature:
    as_of_date: date
    sma20_vnd: float
    sma50_vnd: float
    return_5: float
    return_10: float
    close_location: float
    atr14_vnd: float
    atr_fraction: float
    recent_reference_reset: bool
    unverified_reference_days: int
    eligible: bool
    failed_conditions: tuple[str, ...]


def quote_to_vnd(value: str | float) -> int:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"Invalid positive price: {value!r}")
    return int(round(number * PRICE_MULTIPLIER))


def vnd_to_quote(value: int | float) -> float:
    return float(value) / PRICE_MULTIPLIER


def optional_quote_to_vnd(value: str) -> int | None:
    return quote_to_vnd(value) if value.strip() else None


def money_cost(notional_vnd: int, rate: float) -> int:
    return int(math.ceil(notional_vnd * rate - 1e-12))


def acquisition_cash(
    price_vnd: int,
    config: Config,
    *,
    cost_multiplier: float,
) -> int:
    notional = price_vnd * config.quantity
    commission = money_cost(
        notional, config.commission_rate * cost_multiplier
    )
    slippage = money_cost(
        notional, config.slippage_rate * cost_multiplier
    )
    return notional + commission + slippage


def net_sale_cash(
    price_vnd: int,
    config: Config,
    *,
    cost_multiplier: float,
) -> int:
    notional = price_vnd * config.quantity
    commission = money_cost(
        notional, config.commission_rate * cost_multiplier
    )
    tax = money_cost(notional, config.sell_tax_rate)
    slippage = money_cost(
        notional, config.slippage_rate * cost_multiplier
    )
    return notional - commission - tax - slippage


def exact_net_return(
    entry_price_vnd: int,
    exit_price_vnd: int,
    config: Config,
    *,
    cost_multiplier: float,
) -> float:
    buy_cash = acquisition_cash(
        entry_price_vnd, config, cost_multiplier=cost_multiplier
    )
    sale_cash = net_sale_cash(
        exit_price_vnd, config, cost_multiplier=cost_multiplier
    )
    return sale_cash / buy_cash - 1.0


def exact_net_pnl(
    entry_price_vnd: int,
    exit_price_vnd: int,
    config: Config,
    *,
    cost_multiplier: float,
) -> int:
    return net_sale_cash(
        exit_price_vnd,
        config,
        cost_multiplier=cost_multiplier,
    ) - acquisition_cash(
        entry_price_vnd,
        config,
        cost_multiplier=cost_multiplier,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Study Trial 3 VCB confirmed-pullback events using in-sample "
            "fold dates only."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--daily-data",
        type=Path,
        default=Path("data_algotradeDB_split.csv"),
        help="Daily split file; only selected VCB in-sample prices are parsed",
    )
    parser.add_argument(
        "--assignments",
        type=Path,
        default=Path(
            "data/trial3_splits_vcb/walk_forward_date_assignments.csv"
        ),
        help="Walk-forward date-assignment manifest",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/trial3_pullback_edge"),
        help="Base directory for deterministic run subdirectories",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--fold",
        help=(
            "Run one in-sample fold for diagnostics only; it cannot advance "
            "the hypothesis"
        ),
    )
    group.add_argument(
        "--all-in-sample-folds",
        action="store_true",
        help="Run the pre-registered pooled in-sample study",
    )
    return parser


def read_development_vcb_calendar(path: Path) -> list[date]:
    """Read only VCB development dates, never final-test prices."""
    if not path.exists():
        raise FileNotFoundError(f"Daily data not found: {path}")

    calendar: list[date] = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = {
            "datetime",
            "tickersymbol",
            "primary_split",
        }.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Daily data missing columns: {sorted(missing)}")
        for row in reader:
            if row["tickersymbol"].strip().upper() != TICKER:
                continue
            split = row["primary_split"].strip()
            if split == "final_test":
                continue
            if split != "development":
                raise ValueError(f"Unexpected primary_split: {split!r}")
            calendar.append(date.fromisoformat(row["datetime"]))

    if not calendar:
        raise ValueError("No VCB development dates found")
    calendar.sort()
    if len(calendar) != len(set(calendar)):
        raise ValueError("Duplicate VCB development date")
    return calendar


def read_development_vcb(
    path: Path,
    *,
    allowed_dates: set[date] | None = None,
) -> list[DailyBar]:
    """Parse selected VCB development rows; final/OOS prices stay unparsed."""
    if not path.exists():
        raise FileNotFoundError(f"Daily data not found: {path}")

    raw: list[dict[str, str]] = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = DAILY_REQUIRED.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Daily data missing columns: {sorted(missing)}")
        for row in reader:
            if row["tickersymbol"].strip().upper() != TICKER:
                continue
            split = row["primary_split"].strip()
            if split == "development":
                row_date = date.fromisoformat(row["datetime"])
                if (
                    allowed_dates is not None
                    and row_date not in allowed_dates
                ):
                    continue
                raw.append(row)
            elif split == "final_test":
                continue
            else:
                raise ValueError(f"Unexpected primary_split: {split!r}")

    if not raw:
        raise ValueError("No VCB development rows found")
    raw.sort(key=lambda row: row["datetime"])

    bars: list[DailyBar] = []
    seen: set[date] = set()
    previous_close: int | None = None
    for row in raw:
        trading_date = date.fromisoformat(row["datetime"])
        if trading_date in seen:
            raise ValueError(f"Duplicate VCB daily key: {trading_date}")
        seen.add(trading_date)

        open_vnd = quote_to_vnd(row["open"])
        high_vnd = quote_to_vnd(row["high"])
        low_vnd = quote_to_vnd(row["low"])
        close_vnd = quote_to_vnd(row["close"])
        if high_vnd < max(open_vnd, low_vnd, close_vnd):
            raise ValueError(f"Invalid high for VCB on {trading_date}")
        if low_vnd > min(open_vnd, close_vnd):
            raise ValueError(f"Invalid low for VCB on {trading_date}")

        ceiling_vnd = optional_quote_to_vnd(row["ceiling"])
        floor_vnd = optional_quote_to_vnd(row["floor"])
        reference_available = (
            ceiling_vnd is not None and floor_vnd is not None
        )
        reset_verifiable = (
            previous_close is not None and reference_available
        )
        implied_reference = (
            (ceiling_vnd + floor_vnd) / 2.0
            if reference_available
            else None
        )
        reference_reset = bool(
            reset_verifiable
            and abs(implied_reference / previous_close - 1.0) > 0.02
        )
        bars.append(
            DailyBar(
                trading_date=trading_date,
                open_vnd=open_vnd,
                high_vnd=high_vnd,
                low_vnd=low_vnd,
                close_vnd=close_vnd,
                ceiling_vnd=ceiling_vnd,
                floor_vnd=floor_vnd,
                reference_reset=reference_reset,
                reference_available=reference_available,
                reset_verifiable=reset_verifiable,
            )
        )
        previous_close = close_vnd
    return bars


def read_in_sample_assignments(path: Path) -> dict[str, list[date]]:
    if not path.exists():
        raise FileNotFoundError(f"Assignments not found: {path}")
    by_fold: dict[str, list[date]] = defaultdict(list)
    roles_by_key: dict[tuple[str, date], str] = {}
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = ASSIGNMENT_REQUIRED.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(
                f"Assignment file missing columns: {sorted(missing)}"
            )
        for row in reader:
            fold_id = row["fold_id"].strip()
            role = row["role"].strip()
            if role not in {"in_sample", "walk_forward_oos"}:
                raise ValueError(f"Unexpected assignment role: {role!r}")

            trading_date = date.fromisoformat(row["trading_date"])
            key = (fold_id, trading_date)
            previous_role = roles_by_key.get(key)
            if previous_role is not None:
                if previous_role != role:
                    raise ValueError(
                        "Fold/date assigned to both in-sample and OOS: "
                        f"{key}"
                    )
                raise ValueError(
                    f"Duplicate assignment key: {(fold_id, trading_date, role)}"
                )
            roles_by_key[key] = role
            if role == "in_sample":
                by_fold[fold_id].append(trading_date)

    if not by_fold:
        raise ValueError("No in-sample assignments found")
    for fold_id, dates in by_fold.items():
        if len(dates) != len(set(dates)):
            raise ValueError(f"Duplicate in-sample date in {fold_id}")
        by_fold[fold_id] = sorted(dates)
    return dict(sorted(by_fold.items()))


def select_fold_bars(
    all_bars: Sequence[DailyBar],
    fold_dates: Sequence[date],
    global_calendar: Sequence[date] | None = None,
) -> list[DailyBar]:
    by_date = {bar.trading_date: bar for bar in all_bars}
    calendar = (
        list(global_calendar)
        if global_calendar is not None
        else [bar.trading_date for bar in all_bars]
    )
    global_index = {
        trading_date: index
        for index, trading_date in enumerate(calendar)
    }
    missing = set(fold_dates).difference(by_date)
    if missing:
        raise ValueError(
            "Fold dates missing from VCB development data: "
            + ", ".join(value.isoformat() for value in sorted(missing)[:10])
        )
    positions = [global_index[value] for value in fold_dates]
    if any(
        current != previous + 1
        for previous, current in zip(positions, positions[1:])
    ):
        raise ValueError(
            "Fold dates are not a contiguous VCB development-calendar slice"
        )

    bars = [by_date[value] for value in fold_dates]
    if any(
        current.trading_date <= previous.trading_date
        for previous, current in zip(bars, bars[1:])
    ):
        raise ValueError("Fold calendar is not strictly increasing")

    # Recompute the reset flag within the fold. The first row is deliberately
    # unverifiable because its prior close lies outside the fold; this keeps
    # even the corporate-action veto inside the in-sample boundary.
    fold_local: list[DailyBar] = []
    previous_close: int | None = None
    for bar in bars:
        reset_verifiable = (
            previous_close is not None and bar.reference_available
        )
        implied_reference = (
            (bar.ceiling_vnd + bar.floor_vnd) / 2.0
            if bar.reference_available
            else None
        )
        reference_reset = bool(
            reset_verifiable
            and abs(implied_reference / previous_close - 1.0) > 0.02
        )
        fold_local.append(
            replace(
                bar,
                reference_reset=reference_reset,
                reset_verifiable=reset_verifiable,
            )
        )
        previous_close = bar.close_vnd
    return fold_local


def true_range(current: DailyBar, previous_close_vnd: int) -> int:
    return max(
        current.high_vnd - current.low_vnd,
        abs(current.high_vnd - previous_close_vnd),
        abs(current.low_vnd - previous_close_vnd),
    )


def signal_feature(
    bars: Sequence[DailyBar],
    signal_index: int,
    config: Config,
) -> SignalFeature:
    if signal_index < config.sma_slow - 1:
        raise ValueError("Signal does not have 50-session warm-up")

    signal = bars[signal_index]
    window50 = bars[
        signal_index - config.sma_slow + 1 : signal_index + 1
    ]
    window20 = bars[
        signal_index - config.sma_fast + 1 : signal_index + 1
    ]
    sma50 = statistics.fmean(bar.close_vnd for bar in window50)
    sma20 = statistics.fmean(bar.close_vnd for bar in window20)
    return_5 = (
        signal.close_vnd
        / bars[signal_index - config.pullback_period].close_vnd
        - 1.0
    )
    return_10 = (
        signal.close_vnd
        / bars[signal_index - config.trend_return_period].close_vnd
        - 1.0
    )
    daily_range = signal.high_vnd - signal.low_vnd
    close_location = (
        (signal.close_vnd - signal.low_vnd) / daily_range
        if daily_range > 0
        else math.nan
    )
    atr_ranges = [
        true_range(bars[index], bars[index - 1].close_vnd)
        for index in range(
            signal_index - config.atr_period + 1,
            signal_index + 1,
        )
    ]
    atr14 = statistics.fmean(atr_ranges)
    atr_fraction = atr14 / signal.close_vnd
    recent_reference_reset = any(
        bar.reference_reset for bar in window50
    )
    unverified_reference_days = sum(
        not bar.reset_verifiable for bar in window50
    )

    failures: list[str] = []
    if not signal.close_vnd > sma50:
        failures.append("close_not_above_sma50")
    if not sma20 > sma50:
        failures.append("sma20_not_above_sma50")
    if not (
        config.pullback_return_min
        <= return_5
        <= config.pullback_return_max
    ):
        failures.append("five_session_pullback_outside_range")
    if not return_10 > config.trend_return_min:
        failures.append("ten_session_return_too_low")
    if not signal.close_vnd > bars[signal_index - 1].close_vnd:
        failures.append("no_positive_reversal_close")
    if daily_range <= 0:
        failures.append("zero_range_signal_bar")
    elif close_location < config.close_location_min:
        failures.append("close_location_too_low")
    if atr_fraction > config.atr_fraction_max:
        failures.append("atr_fraction_too_high")
    if recent_reference_reset:
        failures.append("reference_reset_in_feature_window")
    if unverified_reference_days:
        failures.append("unverified_reference_in_feature_window")

    return SignalFeature(
        as_of_date=signal.trading_date,
        sma20_vnd=sma20,
        sma50_vnd=sma50,
        return_5=return_5,
        return_10=return_10,
        close_location=close_location,
        atr14_vnd=atr14,
        atr_fraction=atr_fraction,
        recent_reference_reset=recent_reference_reset,
        unverified_reference_days=unverified_reference_days,
        eligible=not failures,
        failed_conditions=tuple(failures),
    )


def first_barrier_observation(
    bars: Sequence[DailyBar],
    entry_index: int,
    config: Config,
) -> tuple[str, date | None, int | None, bool | None]:
    entry = bars[entry_index].open_vnd
    target = entry * (1.0 + config.target_fraction)
    stop = entry * (1.0 - config.stop_fraction)
    for offset in range(config.maximum_horizon + 1):
        bar = bars[entry_index + offset]
        target_hit = bar.high_vnd >= target
        stop_hit = bar.low_vnd <= stop
        if target_hit and stop_hit:
            return (
                "both_hit_same_bar",
                bar.trading_date,
                offset,
                offset <= config.locked_sessions,
            )
        if target_hit:
            return (
                "target_first",
                bar.trading_date,
                offset,
                offset <= config.locked_sessions,
            )
        if stop_hit:
            return (
                "stop_first",
                bar.trading_date,
                offset,
                offset <= config.locked_sessions,
            )
    return "neither", None, None, None


def build_event(
    fold_id: str,
    bars: Sequence[DailyBar],
    signal_index: int,
    feature: SignalFeature,
    config: Config,
) -> dict[str, object]:
    entry_index = signal_index + 1
    entry_bar = bars[entry_index]
    entry_price = entry_bar.open_vnd
    signal_bar = bars[signal_index]
    event: dict[str, object] = {
        "event_id": (
            f"{config.ticker}|{signal_bar.trading_date.isoformat()}|"
            f"{entry_bar.trading_date.isoformat()}"
        ),
        "fold_id": fold_id,
        "ticker": config.ticker,
        "signal_date": signal_bar.trading_date,
        "entry_date": entry_bar.trading_date,
        "feature_as_of": feature.as_of_date,
        "entry_price_vnd": entry_price,
        "entry_price": vnd_to_quote(entry_price),
        "opening_gap": entry_price / signal_bar.close_vnd - 1.0,
        "sma20": vnd_to_quote(feature.sma20_vnd),
        "sma50": vnd_to_quote(feature.sma50_vnd),
        "return_5_signal": feature.return_5,
        "return_10_signal": feature.return_10,
        "close_location": feature.close_location,
        "atr14": vnd_to_quote(feature.atr14_vnd),
        "atr_fraction": feature.atr_fraction,
        "unverified_reference_days": feature.unverified_reference_days,
    }
    for horizon in HORIZONS:
        exit_bar = bars[entry_index + horizon]
        path = bars[entry_index : entry_index + horizon + 1]
        event[f"exit_date_t{horizon}"] = exit_bar.trading_date
        event[f"exit_close_t{horizon}"] = vnd_to_quote(
            exit_bar.close_vnd
        )
        event[f"gross_return_t{horizon}"] = (
            exit_bar.close_vnd / entry_price - 1.0
        )
        event[f"net_pnl_vnd_t{horizon}"] = exact_net_pnl(
            entry_price,
            exit_bar.close_vnd,
            config,
            cost_multiplier=1.0,
        )
        event[f"net_return_t{horizon}"] = exact_net_return(
            entry_price,
            exit_bar.close_vnd,
            config,
            cost_multiplier=1.0,
        )
        event[f"double_cost_net_pnl_vnd_t{horizon}"] = exact_net_pnl(
            entry_price,
            exit_bar.close_vnd,
            config,
            cost_multiplier=config.doubled_cost_multiplier,
        )
        event[f"double_cost_net_return_t{horizon}"] = exact_net_return(
            entry_price,
            exit_bar.close_vnd,
            config,
            cost_multiplier=config.doubled_cost_multiplier,
        )
        event[f"mfe_t{horizon}"] = (
            max(bar.high_vnd for bar in path) / entry_price - 1.0
        )
        event[f"mae_t{horizon}"] = (
            min(bar.low_vnd for bar in path) / entry_price - 1.0
        )

    locked_path = bars[
        entry_index : entry_index + config.locked_sessions + 1
    ]
    event["locked_mae"] = (
        min(bar.low_vnd for bar in locked_path) / entry_price - 1.0
    )
    barrier, barrier_date, offset, pre_settlement = (
        first_barrier_observation(bars, entry_index, config)
    )
    event["first_barrier"] = barrier
    event["barrier_date"] = barrier_date
    event["barrier_session_offset"] = offset
    event["barrier_pre_settlement"] = pre_settlement
    return event


def generate_fold_candidates(
    fold_id: str,
    bars: Sequence[DailyBar],
    config: Config,
) -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    dict[str, int],
]:
    candidates: list[dict[str, object]] = []
    quarantined: list[dict[str, object]] = []
    counts: Counter[str] = Counter(
        {
            "feature_dates_evaluated": 0,
            "features_with_unverified_reference_days": 0,
            "eligible_signals": 0,
            "purged_incomplete_t10": 0,
            "quarantined_forward_reference_reset": 0,
            "quarantined_forward_unverified_reference": 0,
            "valid_candidates": 0,
        }
    )

    for signal_index in range(config.sma_slow - 1, len(bars) - 1):
        counts["feature_dates_evaluated"] += 1
        feature = signal_feature(bars, signal_index, config)
        if feature.unverified_reference_days:
            counts["features_with_unverified_reference_days"] += 1
        if not feature.eligible:
            for reason in feature.failed_conditions:
                counts[f"signal_failure__{reason}"] += 1
            continue

        counts["eligible_signals"] += 1
        entry_index = signal_index + 1
        if entry_index + config.maximum_horizon >= len(bars):
            counts["purged_incomplete_t10"] += 1
            continue

        forward_window = bars[
            entry_index : entry_index + config.maximum_horizon + 1
        ]
        future_resets = [
            bar.trading_date
            for bar in forward_window
            if bar.reference_reset
        ]
        unverified_reference_dates = [
            bar.trading_date
            for bar in forward_window
            if not bar.reset_verifiable
        ]
        if future_resets or unverified_reference_dates:
            reasons: list[str] = []
            if future_resets:
                reasons.append("reference_reset_in_label_window")
                counts["quarantined_forward_reference_reset"] += 1
            if unverified_reference_dates:
                reasons.append("unverified_reference_in_label_window")
                counts["quarantined_forward_unverified_reference"] += 1
            quarantined.append(
                {
                    "fold_id": fold_id,
                    "ticker": config.ticker,
                    "signal_date": bars[signal_index].trading_date,
                    "entry_date": bars[entry_index].trading_date,
                    "reason": "|".join(reasons),
                    "reset_dates": "|".join(
                        value.isoformat() for value in future_resets
                    ),
                    "unverified_reference_dates": "|".join(
                        value.isoformat()
                        for value in unverified_reference_dates
                    ),
                }
            )
            continue

        event = build_event(
            fold_id, bars, signal_index, feature, config
        )
        if not (
            event["feature_as_of"] < event["entry_date"]
            and event["exit_date_t10"] <= bars[-1].trading_date
        ):
            raise AssertionError("Signal/label date boundary failed")
        candidates.append(event)

    counts["valid_candidates"] = len(candidates)
    return candidates, quarantined, dict(sorted(counts.items()))


def _critical_event_signature(event: dict[str, object]) -> tuple[object, ...]:
    # Every non-fold field must agree. This catches not only conflicting
    # labels, but also a subtle disagreement in independently recomputed
    # features within overlapping folds.
    return tuple(
        (field, event[field])
        for field in sorted(event)
        if field != "fold_id"
    )


def deduplicate_candidates(
    candidates: Sequence[dict[str, object]],
) -> list[dict[str, object]]:
    grouped: dict[date, list[dict[str, object]]] = defaultdict(list)
    for event in candidates:
        grouped[event["entry_date"]].append(event)  # type: ignore[index]

    unique: list[dict[str, object]] = []
    for entry_date in sorted(grouped):
        members = sorted(grouped[entry_date], key=lambda row: row["fold_id"])
        reference_signature = _critical_event_signature(members[0])
        if any(
            _critical_event_signature(member) != reference_signature
            for member in members[1:]
        ):
            raise ValueError(
                f"Overlapping folds disagree for event {entry_date}"
            )
        representative = members[0].copy()
        folds = sorted(str(member["fold_id"]) for member in members)
        representative["fold_memberships"] = "|".join(folds)
        representative["fold_membership_count"] = len(folds)
        representative.pop("fold_id", None)
        unique.append(representative)
    return unique


def deduplicate_quarantined(
    rows: Sequence[dict[str, object]],
) -> list[dict[str, object]]:
    grouped: dict[date, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[row["entry_date"]].append(row)  # type: ignore[index]

    unique: list[dict[str, object]] = []
    for entry_date in sorted(grouped):
        members = sorted(grouped[entry_date], key=lambda row: row["fold_id"])
        signatures = {
            tuple(
                (field, member.get(field))
                for field in QUARANTINED_FOLD_FIELDS
                if field != "fold_id"
            )
            for member in members
        }
        if len(signatures) != 1:
            raise ValueError(
                "Overlapping folds disagree on quarantine reason for "
                f"{entry_date}"
            )
        representative = members[0].copy()
        folds = sorted(str(member["fold_id"]) for member in members)
        representative["fold_memberships"] = "|".join(folds)
        representative["fold_membership_count"] = len(folds)
        representative.pop("fold_id", None)
        unique.append(representative)
    return unique


def select_non_overlapping_primary(
    unique_candidates: Sequence[dict[str, object]],
    global_calendar: Sequence[date],
    config: Config,
) -> list[dict[str, object]]:
    index_by_date = {
        trading_date: index
        for index, trading_date in enumerate(global_calendar)
    }
    selected: list[dict[str, object]] = []
    blocked_through = -1
    for event in sorted(
        unique_candidates, key=lambda row: row["entry_date"]
    ):
        entry_index = index_by_date[event["entry_date"]]  # type: ignore[index]
        if entry_index <= blocked_through:
            continue
        output = event.copy()
        output["primary_sequence"] = len(selected) + 1
        selected.append(output)
        blocked_through = entry_index + config.maximum_horizon
    return selected


def profit_factor(values: Sequence[float]) -> float | str | None:
    positive = sum(value for value in values if value > 0)
    negative = -sum(value for value in values if value < 0)
    if negative > 0:
        return positive / negative
    if positive > 0:
        return "infinity"
    return None


def numeric_at_least(
    value: float | str | None, threshold: float
) -> bool:
    if value == "infinity":
        return True
    return isinstance(value, (int, float)) and value >= threshold


def quantile(values: Sequence[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def describe_returns(
    events: Sequence[dict[str, object]], horizon: int
) -> dict[str, object]:
    net = [float(event[f"net_return_t{horizon}"]) for event in events]
    gross = [float(event[f"gross_return_t{horizon}"]) for event in events]
    doubled = [
        float(event[f"double_cost_net_return_t{horizon}"])
        for event in events
    ]
    net_pnl_vnd = [
        float(event[f"net_pnl_vnd_t{horizon}"]) for event in events
    ]
    doubled_net_pnl_vnd = [
        float(event[f"double_cost_net_pnl_vnd_t{horizon}"])
        for event in events
    ]
    mfe = [float(event[f"mfe_t{horizon}"]) for event in events]
    mae = [float(event[f"mae_t{horizon}"]) for event in events]
    if not net:
        return {
            "events": 0,
            "mean_gross_return": None,
            "mean_net_return": None,
            "median_net_return": None,
            "net_win_rate": None,
            "net_profit_factor": None,
            "doubled_cost_mean_net_return": None,
            "doubled_cost_profit_factor": None,
            "median_mfe": None,
            "median_mae": None,
        }
    return {
        "events": len(net),
        "mean_gross_return": statistics.fmean(gross),
        "mean_net_return": statistics.fmean(net),
        "median_net_return": statistics.median(net),
        "net_win_rate": sum(value > 0 for value in net) / len(net),
        "net_profit_factor": profit_factor(net_pnl_vnd),
        "doubled_cost_mean_net_return": statistics.fmean(doubled),
        "doubled_cost_profit_factor": profit_factor(
            doubled_net_pnl_vnd
        ),
        "median_mfe": statistics.median(mfe),
        "median_mae": statistics.median(mae),
    }


def build_fold_summary(
    primary_events: Sequence[dict[str, object]],
    fold_ids: Sequence[str],
    config: Config,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for fold_id in fold_ids:
        events = [
            event
            for event in primary_events
            if fold_id
            in str(event["fold_memberships"]).split("|")
        ]
        returns = [float(event["net_return_t5"]) for event in events]
        rows.append(
            {
                "fold_id": fold_id,
                "primary_events": len(events),
                "mean_net_return_t5": (
                    statistics.fmean(returns) if returns else None
                ),
                "median_net_return_t5": (
                    statistics.median(returns) if returns else None
                ),
                "win_rate_t5": (
                    sum(value > 0 for value in returns) / len(returns)
                    if returns
                    else None
                ),
                "profit_factor_t5": profit_factor(returns),
                "evaluable_for_stability": (
                    len(events) >= config.minimum_fold_events
                ),
            }
        )
    return rows


def gate(
    value: object,
    requirement: str,
    passed: bool,
) -> dict[str, object]:
    return {
        "value": value,
        "requirement": requirement,
        "passed": bool(passed),
    }


def evaluate_gates(
    primary_events: Sequence[dict[str, object]],
    fold_summary: Sequence[dict[str, object]],
    config: Config,
) -> dict[str, object]:
    stats = {
        f"t{horizon}": describe_returns(primary_events, horizon)
        for horizon in HORIZONS
    }
    t5 = stats["t5"]
    year_counts = Counter(
        event["entry_date"].year for event in primary_events  # type: ignore[union-attr]
    )
    years_with_minimum = sum(
        count >= config.minimum_events_per_year
        for count in year_counts.values()
    )
    locked_mae = [
        float(event["locked_mae"]) for event in primary_events
    ]
    locked_p10 = quantile(locked_mae, 0.10)
    evaluable_folds = [
        row for row in fold_summary if row["evaluable_for_stability"]
    ]
    positive_folds = sum(
        float(row["mean_net_return_t5"]) > 0
        for row in evaluable_folds
    )
    positive_fold_fraction = (
        positive_folds / len(evaluable_folds)
        if evaluable_folds
        else None
    )

    gates = {
        "sample_event_count": gate(
            len(primary_events),
            f">= {config.minimum_primary_events}",
            len(primary_events) >= config.minimum_primary_events,
        ),
        "sample_year_coverage": gate(
            {
                "year_counts": {
                    str(year): count
                    for year, count in sorted(year_counts.items())
                },
                "years_with_at_least_five": years_with_minimum,
            },
            (
                f">= {config.minimum_years} years with >= "
                f"{config.minimum_events_per_year} events"
            ),
            years_with_minimum >= config.minimum_years,
        ),
        "mean_net_return_t5": gate(
            t5["mean_net_return"],
            f">= {config.minimum_mean_net_t5:.4f}",
            (
                t5["mean_net_return"] is not None
                and float(t5["mean_net_return"])
                >= config.minimum_mean_net_t5
            ),
        ),
        "median_net_return_t5": gate(
            t5["median_net_return"],
            f"> {config.minimum_median_net_t5:.4f}",
            (
                t5["median_net_return"] is not None
                and float(t5["median_net_return"])
                > config.minimum_median_net_t5
            ),
        ),
        "net_win_rate_t5": gate(
            t5["net_win_rate"],
            f">= {config.minimum_win_rate_t5:.2f}",
            (
                t5["net_win_rate"] is not None
                and float(t5["net_win_rate"])
                >= config.minimum_win_rate_t5
            ),
        ),
        "net_profit_factor_t5": gate(
            t5["net_profit_factor"],
            f">= {config.minimum_profit_factor_t5:.2f}",
            numeric_at_least(
                t5["net_profit_factor"],
                config.minimum_profit_factor_t5,
            ),
        ),
        "doubled_cost_mean_t5": gate(
            t5["doubled_cost_mean_net_return"],
            f"> {config.minimum_doubled_mean_t5:.4f}",
            (
                t5["doubled_cost_mean_net_return"] is not None
                and float(t5["doubled_cost_mean_net_return"])
                > config.minimum_doubled_mean_t5
            ),
        ),
        "doubled_cost_profit_factor_t5": gate(
            t5["doubled_cost_profit_factor"],
            f"> {config.minimum_doubled_profit_factor_t5:.2f}",
            (
                t5["doubled_cost_profit_factor"] == "infinity"
                or (
                    isinstance(
                        t5["doubled_cost_profit_factor"],
                        (int, float),
                    )
                    and float(t5["doubled_cost_profit_factor"])
                    > config.minimum_doubled_profit_factor_t5
                )
            ),
        ),
        "fold_stability": gate(
            {
                "evaluable_folds": len(evaluable_folds),
                "positive_folds": positive_folds,
                "positive_fraction": positive_fold_fraction,
            },
            (
                f">= {config.minimum_positive_fold_fraction:.2f} positive "
                f"among folds with >= {config.minimum_fold_events} events"
            ),
            (
                positive_fold_fraction is not None
                and positive_fold_fraction
                >= config.minimum_positive_fold_fraction
            ),
        ),
        "locked_mae_p10": gate(
            locked_p10,
            f">= {config.minimum_locked_mae_p10:.2f}",
            (
                locked_p10 is not None
                and locked_p10 >= config.minimum_locked_mae_p10
            ),
        ),
    }

    sample_passed = (
        gates["sample_event_count"]["passed"]
        and gates["sample_year_coverage"]["passed"]
    )
    all_passed = all(item["passed"] for item in gates.values())
    if not sample_passed:
        status = "inconclusive_sample"
    elif all_passed:
        status = "passed_in_sample_edge"
    else:
        status = "rejected"

    return {
        "trial_id": TRIAL_ID,
        "status": status,
        "advance_to_execution_backtest": status == "passed_in_sample_edge",
        "primary_horizon": "T+5",
        "primary_events": len(primary_events),
        "horizon_statistics": stats,
        "locked_mae_p10": locked_p10,
        "barrier_counts": dict(
            sorted(
                Counter(
                    str(event["first_barrier"])
                    for event in primary_events
                ).items()
            )
        ),
        "gates": gates,
    }


def serialize_value(value: object) -> object:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        if math.isnan(value):
            return ""
        return f"{value:.10f}"
    if value is None:
        return ""
    return value


def write_csv(
    path: Path,
    rows: Sequence[dict[str, object]],
    fieldnames: Sequence[str],
) -> None:
    headers = list(fieldnames)
    unexpected = sorted(
        {
            key
            for row in rows
            for key in row
            if key not in headers
        }
    )
    if unexpected:
        raise ValueError(
            f"Unexpected output fields for {path.name}: {unexpected}"
        )
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {key: serialize_value(row.get(key)) for key in headers}
            )


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def development_hash(bars: Sequence[DailyBar]) -> str:
    payload = json.dumps(
        [asdict(bar) for bar in bars],
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return sha256_bytes(payload)


def result_fingerprint(
    fold_candidates: Sequence[dict[str, object]],
    quarantined_fold_rows: Sequence[dict[str, object]],
    quarantined_unique_events: Sequence[dict[str, object]],
    unique_candidates: Sequence[dict[str, object]],
    primary_events: Sequence[dict[str, object]],
    fold_summary: Sequence[dict[str, object]],
    gate_report: dict[str, object],
    source_hashes: dict[str, str],
    config: Config,
) -> str:
    payload = json.dumps(
        {
            "fold_candidates": fold_candidates,
            "quarantined_fold_rows": quarantined_fold_rows,
            "quarantined_unique_events": quarantined_unique_events,
            "unique_candidates": unique_candidates,
            "primary_events": primary_events,
            "fold_summary": fold_summary,
            "gate_report": gate_report,
            "source_hashes": source_hashes,
            "config": asdict(config),
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return sha256_bytes(payload)


def main() -> int:
    args = build_parser().parse_args()
    config = Config()
    config.validate()

    assignments = read_in_sample_assignments(args.assignments)
    if args.fold:
        if args.fold not in assignments:
            raise SystemExit(
                f"Unknown fold {args.fold!r}; "
                f"available={', '.join(assignments)}"
            )
        fold_ids = [args.fold]
    else:
        if not args.all_in_sample_folds:
            raise AssertionError("Explicit study scope was not selected")
        fold_ids = list(assignments)

    global_calendar = read_development_vcb_calendar(args.daily_data)
    selected_in_sample_dates = {
        trading_date
        for fold_id in fold_ids
        for trading_date in assignments[fold_id]
    }
    all_bars = read_development_vcb(
        args.daily_data,
        allowed_dates=selected_in_sample_dates,
    )

    fold_candidates: list[dict[str, object]] = []
    quarantined_fold_rows: list[dict[str, object]] = []
    audit_counts: dict[str, dict[str, int]] = {}
    for fold_id in fold_ids:
        bars = select_fold_bars(
            all_bars,
            assignments[fold_id],
            global_calendar,
        )
        candidates, excluded, counts = generate_fold_candidates(
            fold_id, bars, config
        )
        fold_candidates.extend(candidates)
        quarantined_fold_rows.extend(excluded)
        audit_counts[fold_id] = counts

    unique_candidates = deduplicate_candidates(fold_candidates)
    quarantined_unique_events = deduplicate_quarantined(
        quarantined_fold_rows
    )
    primary_events = select_non_overlapping_primary(
        unique_candidates,
        global_calendar,
        config,
    )
    fold_summary = build_fold_summary(primary_events, fold_ids, config)
    gate_report = evaluate_gates(primary_events, fold_summary, config)
    if args.fold:
        gate_report["diagnostic_gate_status"] = gate_report["status"]
        gate_report["status"] = "diagnostic_fold_only"
        gate_report["advance_to_execution_backtest"] = False
        gate_report["scope"] = "single_fold_in_sample_diagnostic"
    else:
        gate_report["scope"] = "pooled_all_in_sample_folds"

    script_path = Path(__file__).resolve()
    preregistration_path = (
        script_path.parent
        / "research_log"
        / "TRIAL3_VCB_CONFIRMED_PULLBACK.md"
    )
    source_hashes = {
        "script": sha256_file(script_path),
        "preregistration": sha256_file(preregistration_path),
        "selected_in_sample_vcb_rows": development_hash(all_bars),
        "vcb_development_calendar": sha256_bytes(
            json.dumps(
                [value.isoformat() for value in global_calendar],
                separators=(",", ":"),
            ).encode("utf-8")
        ),
        "fold_assignment_file": sha256_file(args.assignments),
    }
    run_payload = json.dumps(
        {
            "source_hashes": source_hashes,
            "config": asdict(config),
            "fold_ids": fold_ids,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    run_id = f"trial3_{sha256_bytes(run_payload)[:10]}"
    output_dir = args.output_dir / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    fingerprint = result_fingerprint(
        fold_candidates,
        quarantined_fold_rows,
        quarantined_unique_events,
        unique_candidates,
        primary_events,
        fold_summary,
        gate_report,
        source_hashes,
        config,
    )
    manifest_path = output_dir / "manifest.json"
    if manifest_path.exists():
        previous_manifest = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )
        previous_fingerprint = previous_manifest.get(
            "result_fingerprint_sha256"
        )
        if previous_fingerprint != fingerprint:
            raise RuntimeError(
                "Deterministic run directory already exists with a "
                "different result fingerprint"
            )

    output_paths = {
        "fold_candidates.csv": output_dir / "fold_candidates.csv",
        "quarantined_fold_rows.csv": (
            output_dir / "quarantined_fold_rows.csv"
        ),
        "quarantined_events.csv": output_dir / "quarantined_events.csv",
        "unique_candidates.csv": output_dir / "unique_candidates.csv",
        "primary_events.csv": output_dir / "primary_events.csv",
        "fold_summary.csv": output_dir / "fold_summary.csv",
        "gate_report.json": output_dir / "gate_report.json",
    }
    write_csv(
        output_paths["fold_candidates.csv"],
        fold_candidates,
        FOLD_CANDIDATE_FIELDS,
    )
    write_csv(
        output_paths["quarantined_fold_rows.csv"],
        quarantined_fold_rows,
        QUARANTINED_FOLD_FIELDS,
    )
    write_csv(
        output_paths["quarantined_events.csv"],
        quarantined_unique_events,
        QUARANTINED_UNIQUE_FIELDS,
    )
    write_csv(
        output_paths["unique_candidates.csv"],
        unique_candidates,
        UNIQUE_CANDIDATE_FIELDS,
    )
    write_csv(
        output_paths["primary_events.csv"],
        primary_events,
        PRIMARY_EVENT_FIELDS,
    )
    write_csv(
        output_paths["fold_summary.csv"],
        fold_summary,
        FOLD_SUMMARY_FIELDS,
    )
    output_paths["gate_report.json"].write_text(
        json.dumps(gate_report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    output_hashes = {
        name: sha256_file(path)
        for name, path in sorted(output_paths.items())
    }
    manifest = {
        "trial_id": TRIAL_ID,
        "run_id": run_id,
        "scope": gate_report["scope"],
        "folds": fold_ids,
        "role": "in_sample_only",
        "ticker": config.ticker,
        "primary_horizon": "T+5",
        "final_test_price_rows_parsed": False,
        "exclusive_walk_forward_oos_price_rows_parsed": False,
        "inputs": {
            "daily_data": str(args.daily_data.resolve()),
            "assignments": str(args.assignments.resolve()),
            "preregistration": str(preregistration_path),
            "output_base": str(args.output_dir.resolve()),
        },
        "counts": {
            "fold_candidates": len(fold_candidates),
            "quarantined_fold_rows": len(quarantined_fold_rows),
            "quarantined_unique_events": len(
                quarantined_unique_events
            ),
            "unique_candidates": len(unique_candidates),
            "primary_non_overlapping_events": len(primary_events),
        },
        "fold_audit_counts": audit_counts,
        "config": asdict(config),
        "profit_factor_definition": (
            "sum positive exact VND P&L / absolute sum negative exact "
            "VND P&L for one 100-share lot"
        ),
        "source_hashes": source_hashes,
        "output_hashes": output_hashes,
        "result_fingerprint_sha256": fingerprint,
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    t5 = gate_report["horizon_statistics"]["t5"]
    mean_net = t5["mean_net_return"]
    win_rate = t5["net_win_rate"]
    mean_text = (
        f"{100.0 * float(mean_net):.2f}%"
        if mean_net is not None
        else "n/a"
    )
    win_text = (
        f"{100.0 * float(win_rate):.1f}%"
        if win_rate is not None
        else "n/a"
    )
    print(
        f"{TRIAL_ID}: {gate_report['status']}; "
        f"primary_events={len(primary_events)}; "
        f"T+5 mean_net={mean_text}; "
        f"win_rate={win_text}; "
        f"output={output_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
