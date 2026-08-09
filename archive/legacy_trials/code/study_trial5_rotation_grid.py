#!/usr/bin/env python3
"""Trial 5: leakage-safe two-month ticker rotation and long-only grid.

The research unit is one two-month portfolio rotation:

* fit the selector and grid volatility on the preceding 12 calendar months;
* choose at most two tickers from the fixed ten-stock universe;
* freeze those choices and parameters for the next two months;
* run a long-only grid on sparse one-minute event bars;
* close and settle the portfolio before the next rotation.

The production command can read development walk-forward periods only. Rows
labelled ``final_test`` are rejected before any numeric price is parsed.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import os
import statistics
import tempfile
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, time
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
from pathlib import Path
from typing import Iterable, Sequence


TRIAL_ID = "TRIAL5-HSX-ROTATION-LONG-GRID"
SCHEMA_VERSION = "trial5.v1"
TICKERS = (
    "FPT",
    "HPG",
    "MBB",
    "MWG",
    "PNJ",
    "SSI",
    "TCB",
    "VCB",
    "VND",
    "VPB",
)
SECTOR_BY_TICKER = {
    "FPT": "technology",
    "HPG": "materials",
    "MBB": "banks",
    "MWG": "consumer_retail",
    "PNJ": "consumer_retail",
    "SSI": "securities",
    "TCB": "banks",
    "VCB": "banks",
    "VND": "securities",
    "VPB": "banks",
}
CANONICAL_FOLD_IDS = tuple(f"wf_{number:02d}" for number in range(1, 16))
EXPECTED_DEVELOPMENT_START = date(2022, 1, 4)
EXPECTED_FIRST_OOS = date(2023, 1, 3)
EXPECTED_LAST_OOS = date(2025, 6, 30)
EXPECTED_DEVELOPMENT_END = date(2025, 7, 11)
EXPECTED_FINAL_START = date(2025, 7, 14)
EXPECTED_FINAL_END = date(2026, 7, 16)
EXPECTED_FINAL_SESSIONS = 252
FROZEN_CONFIG_SHA256 = (
    "e304cef11f44fcee8c153d7a6fe9f04bcd185d88cb77e0e8cbb64ab9d0f5d9d1"
)
PRICE_MULTIPLIER = 1_000

DAILY_REQUIRED = {
    "datetime",
    "tickersymbol",
    "open",
    "high",
    "low",
    "close",
    "ceiling",
    "floor",
    "matched_quantity",
    "exchangeid",
    "instrumenttype",
    "primary_split",
}
ASSIGNMENT_REQUIRED = {"fold_id", "trading_date", "role"}
MINUTE_REQUIRED = {
    "minute",
    "trading_date",
    "tickersymbol",
    "market_session",
    "matched_open",
    "matched_high",
    "matched_low",
    "matched_close",
    "matched_quantity",
    "last_best_bid",
    "last_best_bid_quantity",
    "last_best_ask",
    "last_best_ask_quantity",
}

SELECTION_FIELDS = (
    "trial_id",
    "fold_id",
    "as_of_date",
    "rotation_start_nav_vnd",
    "tickersymbol",
    "observed_windows",
    "valid_windows",
    "excluded_reset_windows",
    "oscillating_sideways_pct",
    "quiet_sideways_pct",
    "uptrend_pct",
    "downtrend_pct",
    "deep_downtrend_pct",
    "favorable_pct",
    "latest_regime",
    "median_daily_value_vnd",
    "atr20_pct",
    "median_oscillating_range_pct",
    "eligible",
    "ineligibility_reasons",
    "selected_rank",
)
GRID_FIELDS = (
    "trial_id",
    "fold_id",
    "tickersymbol",
    "fit_end",
    "deployment_start",
    "deployment_end",
    "anchor_vnd",
    "grid_step_pct",
    "lower_bound_vnd",
    "upper_bound_vnd",
    "slot_capital_vnd",
    "reserve_fraction",
    "level_id",
    "buy_limit_vnd",
    "sell_target_vnd",
    "quantity",
)
TRADE_FIELDS = (
    "trial_id",
    "fold_id",
    "tickersymbol",
    "cost_scenario",
    "event_time",
    "side",
    "reason",
    "level_id",
    "quantity",
    "reference_book_price_vnd",
    "execution_price_vnd",
    "execution_friction_vnd",
    "settlement_locked_at_risk_trigger",
    "gross_notional_vnd",
    "commission_vnd",
    "sell_tax_vnd",
    "cash_change_vnd",
    "realized_pnl_vnd",
    "settlement_time",
    "total_quantity_after",
    "tradeable_quantity_after",
    "locked_quantity_after",
    "available_cash_after_vnd",
    "pending_cash_after_vnd",
)
ACCOUNT_DAILY_FIELDS = (
    "trial_id",
    "fold_id",
    "trading_date",
    "tickersymbol",
    "available_cash_vnd",
    "pending_cash_vnd",
    "inventory_liquidation_value_vnd",
    "account_equity_vnd",
    "total_quantity",
    "tradeable_quantity",
    "locked_quantity",
    "shutdown",
    "shutdown_reason",
)
PORTFOLIO_DAILY_FIELDS = (
    "trial_id",
    "fold_id",
    "trading_date",
    "portfolio_equity_vnd",
    "fold_return_to_date",
    "available_cash_vnd",
    "pending_cash_vnd",
    "inventory_liquidation_value_vnd",
    "total_quantity",
    "tradeable_quantity",
    "locked_quantity",
    "portfolio_kill_active",
)
FOLD_FIELDS = (
    "trial_id",
    "fold_id",
    "train_start",
    "train_end",
    "oos_start",
    "oos_end",
    "selected_tickers",
    "selected_count",
    "valid",
    "doubled_cost_valid",
    "portfolio_kill_triggered",
    "portfolio_kill_effective_date",
    "portfolio_high_water_end_vnd",
    "quarantine_reason",
    "starting_capital_vnd",
    "ending_capital_vnd",
    "net_return",
    "doubled_cost_return",
    "benchmark_return",
    "market_proxy_return",
    "market_regime",
    "maximum_drawdown",
    "average_capital_utilization",
    "maximum_capital_utilization",
    "buy_count",
    "sell_count",
    "completed_grid_cycles",
    "gross_turnover_vnd",
    "turnover_fraction",
    "modeled_cost_vnd",
    "modeled_cost_fraction",
    "settlement_locked_exit_loss_vnd",
    "realized_pnl_vnd",
    "profit_factor",
    "shutdown_count",
    "minimum_tradeable_quantity",
    "ending_total_quantity",
    "ending_pending_cash_vnd",
)
QUARANTINE_FIELDS = (
    "trial_id",
    "fold_id",
    "tickersymbol",
    "trading_date",
    "reason",
)


@dataclass(frozen=True)
class Config:
    universe: tuple[str, ...] = TICKERS
    train_months: int = 12
    deployment_months: int = 2
    selected_tickers_per_fold: int = 2
    initial_capital_vnd: int = 100_000_000

    regime_sessions: int = 10
    regime_step_sessions: int = 10
    er_threshold: float = 0.35
    minimum_range_pct: float = 0.012
    minimum_valid_regime_windows: int = 20
    minimum_oscillating_pct: float = 0.35
    maximum_downtrend_pct: float = 0.25
    deep_downtrend_return: float = -0.08
    maximum_deep_downtrend_pct: float = 0.05
    minimum_favorable_pct: float = 0.60
    liquidity_lookback_sessions: int = 60
    minimum_median_daily_value_vnd: int = 10_000_000_000
    atr_sessions: int = 20

    grid_levels: int = 1
    maximum_ticker_exposure_fraction: float = 0.15
    maximum_ticker_stress_loss_fraction: float = 0.015
    maximum_ticker_turnover_fraction: float = 0.60
    stress_floor_limit_fraction: float = 0.07
    minimum_grid_step: float = 0.015
    maximum_grid_step: float = 0.030
    board_lot: int = 100
    maximum_normal_spread_bps: float = 40.0
    maximum_minute_participation: float = 0.05
    maximum_skipped_minute_rows: int = 2

    commission_rate: float = 0.0015
    sell_tax_rate: float = 0.0010
    execution_haircut: float = 0.0005
    settlement_sessions: int = 2
    settlement_time: str = "13:00:00"
    wind_down_sessions: int = 3
    account_stop_drawdown: float = -0.05
    portfolio_kill_drawdown: float = -0.05
    market_downtrend_return: float = -0.05
    market_uptrend_return: float = 0.05

    minimum_valid_folds: int = 15
    minimum_active_folds: int = 10
    minimum_completed_campaigns: int = 30
    minimum_profitable_fold_fraction: float = 0.60
    minimum_median_fold_return: float = 0.0
    minimum_compounded_return: float = 0.0
    minimum_annualized_fold_sharpe: float = 0.50
    minimum_trade_profit_factor: float = 1.20
    minimum_maximum_drawdown: float = -0.05
    minimum_worst_fold_return: float = -0.08
    minimum_doubled_cost_compounded_return: float = 0.0
    minimum_doubled_cost_profit_factor: float = 1.0
    maximum_forced_loss_to_target_gain: float = 1.0
    maximum_modeled_cost_fraction_per_rotation: float = 0.01
    maximum_modeled_cost_to_gross_profit: float = 0.35

    def validate(self) -> None:
        if self.universe != TICKERS:
            raise ValueError("Trial 5 universe is frozen to the ten HSX tickers")
        if (
            self.train_months != 12
            or self.deployment_months != 2
            or self.selected_tickers_per_fold != 2
        ):
            raise ValueError("Trial 5 uses 12-month fit / 2-month deployment / top 2")
        if self.initial_capital_vnd != 100_000_000:
            raise ValueError("Trial 5 initial portfolio must be VND 100 million")
        if self.grid_levels != 1:
            raise ValueError("Trial 5 deliberately prohibits averaging down")
        if not 0 < self.maximum_ticker_exposure_fraction < 0.5:
            raise ValueError("Invalid per-ticker exposure cap")
        if not 0 < self.maximum_ticker_turnover_fraction <= 1.0:
            raise ValueError("Invalid per-ticker turnover cap")
        if not 0 < self.maximum_modeled_cost_fraction_per_rotation < 0.1:
            raise ValueError("Invalid per-rotation modeled-cost cap")
        if not 0 < self.maximum_modeled_cost_to_gross_profit < 1:
            raise ValueError("Invalid modeled-cost-to-gross-profit cap")
        if self.settlement_sessions != 2 or self.settlement_time != "13:00:00":
            raise ValueError("Trial 5 models T+2 afternoon settlement")
        payload = canonical_json(asdict(self))
        digest = sha256_bytes(payload)
        if FROZEN_CONFIG_SHA256 != "TO_BE_FROZEN" and digest != FROZEN_CONFIG_SHA256:
            raise ValueError("Trial 5 configuration differs from frozen v1")


@dataclass(frozen=True)
class DailyBar:
    trading_date: date
    ticker: str
    open_vnd: int
    high_vnd: int
    low_vnd: int
    close_vnd: int
    ceiling_vnd: int | None
    floor_vnd: int | None
    matched_quantity: int
    reset_verifiable: bool = False
    reference_reset: bool = False


@dataclass(frozen=True)
class MinuteBar:
    event_time: datetime
    trading_date: date
    ticker: str
    open_vnd: int
    high_vnd: int
    low_vnd: int
    close_vnd: int
    matched_quantity: int
    best_bid_vnd: int | None
    best_bid_quantity: int | None
    best_ask_vnd: int | None
    best_ask_quantity: int | None


@dataclass(frozen=True)
class Fold:
    fold_id: str
    train_dates: tuple[date, ...]
    oos_dates: tuple[date, ...]


@dataclass
class Lot:
    level_id: int
    quantity: int
    acquisition_cash_vnd: int
    target_vnd: int
    tradeable_at: datetime
    risk_triggered_while_locked: bool = False


@dataclass
class Level:
    level_id: int
    buy_limit_vnd: int
    sell_target_vnd: int
    quantity: int
    lot: Lot | None = None
    rearm_after: datetime | None = None


@dataclass
class PendingCash:
    amount_vnd: int
    available_at: datetime


@dataclass
class AccountResult:
    valid: bool
    quarantine_reason: str
    ending_equity_vnd: int
    trades: list[dict[str, object]]
    daily_states: list[dict[str, object]]
    grid_rows: list[dict[str, object]]
    shutdown: bool
    completed_cycles: int
    ending_quantity: int
    ending_pending_cash_vnd: int


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def quote_to_vnd(value: str | float | Decimal) -> int:
    parsed = Decimal(str(value))
    if not parsed.is_finite() or parsed <= 0:
        raise ValueError(f"Invalid positive price: {value!r}")
    return int(
        (parsed * PRICE_MULTIPLIER).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


def optional_quote_to_vnd(value: str) -> int | None:
    return quote_to_vnd(value) if value.strip() else None


def money_cost(notional_vnd: int, rate: float) -> int:
    return int(
        (Decimal(notional_vnd) * Decimal(str(rate))).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


def acquisition_cash(
    price_vnd: int, quantity: int, config: Config, multiplier: float = 1.0
) -> tuple[int, int]:
    notional = price_vnd * quantity
    commission = money_cost(
        notional, config.commission_rate * multiplier
    )
    return notional + commission, commission


def net_sale_cash(
    price_vnd: int, quantity: int, config: Config, multiplier: float = 1.0
) -> tuple[int, int, int]:
    notional = price_vnd * quantity
    commission = money_cost(
        notional, config.commission_rate * multiplier
    )
    sell_tax = money_cost(notional, config.sell_tax_rate)
    return notional - commission - sell_tax, commission, sell_tax


def hsx_tick_vnd(price_vnd: int) -> int:
    if price_vnd < 10_000:
        return 10
    if price_vnd < 50_000:
        return 50
    return 100


def round_to_hsx_tick(price_vnd: float, side: str) -> int:
    approximate = max(1, int(price_vnd))
    tick = hsx_tick_vnd(approximate)
    ratio = Decimal(str(price_vnd)) / Decimal(tick)
    rounding = ROUND_FLOOR if side == "buy" else ROUND_CEILING
    return int(ratio.quantize(Decimal("1"), rounding=rounding)) * tick


def consecutive_floor_price(
    start_price_vnd: int,
    sessions: int,
    floor_limit_fraction: float,
) -> int:
    """Apply each HSX floor move and legal-tick rounding sequentially."""
    price = start_price_vnd
    multiplier = Decimal("1") - Decimal(str(floor_limit_fraction))
    for _ in range(sessions):
        price = round_to_hsx_tick(
            Decimal(price) * multiplier,
            "buy",
        )
    return price


def inferred_reference_reset(
    previous_close_vnd: int,
    ceiling_vnd: int | None,
    floor_vnd: int | None,
) -> tuple[bool, bool]:
    if ceiling_vnd is None or floor_vnd is None:
        return False, False
    implied_reference = (ceiling_vnd + floor_vnd) / 2.0
    return abs(implied_reference / previous_close_vnd - 1.0) > 0.02, True


def read_daily_development(
    path: Path,
    universe: Sequence[str],
    *,
    enforce_frozen_calendar: bool = True,
) -> tuple[dict[str, list[DailyBar]], list[date], tuple[date, date]]:
    allowed = set(universe)
    by_ticker: dict[str, list[DailyBar]] = defaultdict(list)
    final_by_ticker: dict[str, list[date]] = defaultdict(list)
    seen: set[tuple[str, date]] = set()
    seen_final: set[tuple[str, date]] = set()

    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = DAILY_REQUIRED.difference(reader.fieldnames or ())
        if missing:
            raise ValueError(f"Daily input missing columns: {sorted(missing)}")
        for row in reader:
            ticker = row["tickersymbol"].strip().upper()
            if ticker not in allowed:
                continue
            trading_date = date.fromisoformat(row["datetime"])
            split = row["primary_split"].strip()
            if split == "final_test":
                # Deliberately skip before parsing any final-test numeric field.
                key = (ticker, trading_date)
                if key in seen_final:
                    raise ValueError(f"Duplicate final-test key: {key}")
                seen_final.add(key)
                final_by_ticker[ticker].append(trading_date)
                continue
            if split != "development":
                raise ValueError(f"Unexpected primary_split: {split!r}")
            if (
                row["exchangeid"].strip().upper() != "HSX"
                or row["instrumenttype"].strip().lower() != "stock"
            ):
                raise ValueError(
                    f"Universe row is not an HSX stock: {ticker} {trading_date}"
                )

            key = (ticker, trading_date)
            if key in seen:
                raise ValueError(f"Duplicate daily key: {key}")
            seen.add(key)
            open_vnd = quote_to_vnd(row["open"])
            high_vnd = quote_to_vnd(row["high"])
            low_vnd = quote_to_vnd(row["low"])
            close_vnd = quote_to_vnd(row["close"])
            if high_vnd < max(open_vnd, low_vnd, close_vnd):
                raise ValueError(f"Invalid daily high: {key}")
            if low_vnd > min(open_vnd, close_vnd):
                raise ValueError(f"Invalid daily low: {key}")
            quantity = int(Decimal(row["matched_quantity"]))
            if quantity < 0:
                raise ValueError(f"Negative daily quantity: {key}")
            by_ticker[ticker].append(
                DailyBar(
                    trading_date=trading_date,
                    ticker=ticker,
                    open_vnd=open_vnd,
                    high_vnd=high_vnd,
                    low_vnd=low_vnd,
                    close_vnd=close_vnd,
                    ceiling_vnd=optional_quote_to_vnd(row["ceiling"]),
                    floor_vnd=optional_quote_to_vnd(row["floor"]),
                    matched_quantity=quantity,
                )
            )

    if set(by_ticker) != allowed:
        raise ValueError(
            f"Missing development tickers: {sorted(allowed.difference(by_ticker))}"
        )
    calendars: dict[str, list[date]] = {}
    for ticker, rows in by_ticker.items():
        rows.sort(key=lambda bar: bar.trading_date)
        flagged: list[DailyBar] = []
        previous: DailyBar | None = None
        for bar in rows:
            if previous is None:
                flagged.append(
                    replace(bar, reset_verifiable=False, reference_reset=False)
                )
            else:
                reset, verified = inferred_reference_reset(
                    previous.close_vnd, bar.ceiling_vnd, bar.floor_vnd
                )
                flagged.append(
                    replace(
                        bar,
                        reset_verifiable=verified,
                        reference_reset=reset,
                    )
                )
            previous = bar
        by_ticker[ticker] = flagged
        calendars[ticker] = [bar.trading_date for bar in flagged]

    first_calendar = calendars[universe[0]]
    for ticker in universe[1:]:
        if calendars[ticker] != first_calendar:
            raise ValueError(f"Development calendar mismatch for {ticker}")
    if set(final_by_ticker) != allowed:
        raise ValueError("A locked final_test partition is required")
    first_final_calendar = sorted(final_by_ticker[universe[0]])
    for ticker in universe[1:]:
        if sorted(final_by_ticker[ticker]) != first_final_calendar:
            raise ValueError(f"Final-test calendar mismatch for {ticker}")
    final_range = (first_final_calendar[0], first_final_calendar[-1])
    if enforce_frozen_calendar and (
        final_range != (EXPECTED_FINAL_START, EXPECTED_FINAL_END)
        or len(first_final_calendar) != EXPECTED_FINAL_SESSIONS
    ):
        raise ValueError("Locked final-test calendar differs from Trial 5")
    if first_calendar[-1] >= final_range[0]:
        raise ValueError("Development and final-test dates overlap")
    return by_ticker, first_calendar, final_range


def development_daily_hash(
    daily: dict[str, list[DailyBar]], universe: Sequence[str]
) -> str:
    """Hash only parsed development rows; locked final bytes are excluded."""
    payload = [
        {
            "trading_date": bar.trading_date.isoformat(),
            "ticker": bar.ticker,
            "open_vnd": bar.open_vnd,
            "high_vnd": bar.high_vnd,
            "low_vnd": bar.low_vnd,
            "close_vnd": bar.close_vnd,
            "ceiling_vnd": bar.ceiling_vnd,
            "floor_vnd": bar.floor_vnd,
            "matched_quantity": bar.matched_quantity,
            "reset_verifiable": bar.reset_verifiable,
            "reference_reset": bar.reference_reset,
        }
        for ticker in universe
        for bar in daily[ticker]
    ]
    return sha256_bytes(canonical_json(payload))


def read_folds(path: Path) -> list[Fold]:
    roles: dict[str, dict[str, list[date]]] = defaultdict(
        lambda: defaultdict(list)
    )
    seen: set[tuple[str, date]] = set()
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = ASSIGNMENT_REQUIRED.difference(reader.fieldnames or ())
        if missing:
            raise ValueError(f"Assignments missing columns: {sorted(missing)}")
        for row in reader:
            fold_id = row["fold_id"].strip()
            trading_date = date.fromisoformat(row["trading_date"])
            role = row["role"].strip()
            if role not in {"in_sample", "walk_forward_oos"}:
                raise ValueError(f"Unexpected assignment role: {role!r}")
            key = (fold_id, trading_date)
            if key in seen:
                raise ValueError(f"Fold date has conflicting/duplicate role: {key}")
            seen.add(key)
            roles[fold_id][role].append(trading_date)

    if tuple(sorted(roles)) != CANONICAL_FOLD_IDS:
        raise ValueError("Trial 5 requires exactly wf_01 through wf_15")
    folds: list[Fold] = []
    used_oos: set[date] = set()
    for fold_id in CANONICAL_FOLD_IDS:
        train = tuple(sorted(roles[fold_id]["in_sample"]))
        oos = tuple(sorted(roles[fold_id]["walk_forward_oos"]))
        if not train or not oos or train[-1] >= oos[0]:
            raise ValueError(f"Invalid chronology in {fold_id}")
        if used_oos.intersection(oos):
            raise ValueError(f"Overlapping OOS dates in {fold_id}")
        used_oos.update(oos)
        folds.append(Fold(fold_id, train, oos))
    return folds


def month_start(value: date) -> date:
    return date(value.year, value.month, 1)


def add_months(value: date, months: int) -> date:
    total = value.year * 12 + value.month - 1 + months
    return date(total // 12, total % 12 + 1, 1)


def validate_fold_calendars(folds: Sequence[Fold], calendar: Sequence[date]) -> None:
    if (
        not calendar
        or calendar[0] != EXPECTED_DEVELOPMENT_START
        or calendar[-1] != EXPECTED_DEVELOPMENT_END
        or folds[0].oos_dates[0] != EXPECTED_FIRST_OOS
        or folds[-1].oos_dates[-1] != EXPECTED_LAST_OOS
    ):
        raise ValueError("Trial 5 absolute development boundaries differ")
    positions = {value: index for index, value in enumerate(calendar)}
    first_training_boundary = month_start(calendar[0])
    for fold_index, fold in enumerate(folds):
        train_boundary = add_months(
            first_training_boundary,
            fold_index * 2,
        )
        oos_boundary = add_months(train_boundary, 12)
        oos_end_boundary = add_months(oos_boundary, 2)
        expected_train = tuple(
            value
            for value in calendar
            if train_boundary <= value < oos_boundary
        )
        expected_oos = tuple(
            value
            for value in calendar
            if oos_boundary <= value < oos_end_boundary
        )
        if fold.train_dates != expected_train or fold.oos_dates != expected_oos:
            raise ValueError(
                f"{fold.fold_id} differs from frozen 12m/2m calendar"
            )
        for dates, label in ((fold.train_dates, "train"), (fold.oos_dates, "oos")):
            try:
                indexes = [positions[value] for value in dates]
            except KeyError as exc:
                raise ValueError(
                    f"{fold.fold_id} {label} date outside development"
                ) from exc
            if indexes != list(range(indexes[0], indexes[-1] + 1)):
                raise ValueError(f"{fold.fold_id} {label} dates are not contiguous")
        if positions[fold.oos_dates[0]] != positions[fold.train_dates[-1]] + 1:
            raise ValueError(
                f"{fold.fold_id} OOS does not immediately follow training"
            )


def validate_split_audit(path: Path, config: Config) -> dict[str, object]:
    audit = json.loads(path.read_text(encoding="utf-8"))
    if tuple(audit.get("tickers", ())) != config.universe:
        raise ValueError("Split audit universe differs from Trial 5")
    policy = dict(audit.get("policy", {}))
    if (
        policy.get("train_months") != config.train_months
        or policy.get("oos_months") != config.deployment_months
        or policy.get("oos_windows_overlap") is not False
    ):
        raise ValueError("Split audit policy differs from Trial 5")
    walk_forward = dict(audit.get("walk_forward", {}))
    if (
        walk_forward.get("fold_count") != len(CANONICAL_FOLD_IDS)
        or walk_forward.get("first_oos_start")
        != EXPECTED_FIRST_OOS.isoformat()
        or walk_forward.get("last_oos_end")
        != EXPECTED_LAST_OOS.isoformat()
        or walk_forward.get("total_unique_oos_sessions") != 618
    ):
        raise ValueError("Split audit walk-forward differs from Trial 5")
    final_holdout = dict(audit.get("final_holdout", {}))
    if (
        final_holdout.get("status") != "LOCKED_DO_NOT_TUNE"
        or final_holdout.get("start") != EXPECTED_FINAL_START.isoformat()
        or final_holdout.get("end") != EXPECTED_FINAL_END.isoformat()
        or final_holdout.get("sessions") != EXPECTED_FINAL_SESSIONS
    ):
        raise ValueError("Final holdout is not marked locked")
    return audit


def efficiency_ratio(closes: Sequence[int]) -> float:
    path = sum(abs(current - prior) for prior, current in zip(closes, closes[1:]))
    return abs(closes[-1] - closes[0]) / path if path else 0.0


def classify_window(
    rows: Sequence[DailyBar], config: Config
) -> tuple[str, float, float, float]:
    if any(not row.reset_verifiable or row.reference_reset for row in rows):
        return "excluded_reference_reset", math.nan, math.nan, math.nan
    closes = [row.close_vnd for row in rows]
    er = efficiency_ratio(closes)
    period_return = closes[-1] / closes[0] - 1.0
    range_pct = (
        max(row.high_vnd for row in rows)
        - min(row.low_vnd for row in rows)
    ) / closes[0]
    if period_return <= config.deep_downtrend_return:
        regime = "deep_downtrend"
    elif er < config.er_threshold:
        regime = (
            "oscillating_sideways"
            if range_pct >= config.minimum_range_pct
            else "quiet_sideways"
        )
    elif period_return > 0:
        regime = "uptrend"
    else:
        regime = "downtrend"
    return regime, er, period_return, range_pct


def median(values: Sequence[float | int]) -> float:
    return float(statistics.median(values))


def calculate_atr_pct(rows: Sequence[DailyBar], sessions: int) -> float:
    if len(rows) < sessions + 1:
        raise ValueError("Insufficient ATR history")
    sample = rows[-(sessions + 1) :]
    if any(not row.reset_verifiable or row.reference_reset for row in sample[1:]):
        raise ValueError("ATR window contains unverifiable/reset reference")
    true_ranges: list[int] = []
    for previous, current in zip(sample, sample[1:]):
        true_ranges.append(
            max(
                current.high_vnd - current.low_vnd,
                abs(current.high_vnd - previous.close_vnd),
                abs(current.low_vnd - previous.close_vnd),
            )
        )
    return statistics.mean(true_ranges) / sample[-1].close_vnd


def fit_fold_selector(
    fold: Fold,
    daily: dict[str, list[DailyBar]],
    config: Config,
    portfolio_nav_vnd: int,
) -> tuple[list[dict[str, object]], list[str]]:
    by_ticker_date = {
        ticker: {bar.trading_date: bar for bar in rows}
        for ticker, rows in daily.items()
    }
    windows_reversed: list[tuple[date, ...]] = []
    observations = config.regime_sessions + 1
    end = len(fold.train_dates)
    while end >= observations:
        windows_reversed.append(
            fold.train_dates[end - observations : end]
        )
        end -= config.regime_step_sessions
    windows = list(reversed(windows_reversed))
    if not windows:
        raise ValueError(f"No regime windows in {fold.fold_id}")

    summaries: list[dict[str, object]] = []
    for ticker in config.universe:
        train_rows = [by_ticker_date[ticker][value] for value in fold.train_dates]
        regimes: list[str] = []
        returns: list[float] = []
        ranges: list[float] = []
        latest_regime = ""
        for window_dates in windows:
            rows = [by_ticker_date[ticker][value] for value in window_dates]
            regime, _, period_return, range_pct = classify_window(rows, config)
            regimes.append(regime)
            returns.append(period_return)
            ranges.append(range_pct)
            latest_regime = regime
        valid_indexes = [
            index
            for index, regime in enumerate(regimes)
            if regime != "excluded_reference_reset"
        ]
        valid_regimes = [regimes[index] for index in valid_indexes]
        if not valid_regimes:
            raise ValueError(f"No valid selector windows for {ticker}")
        counts = Counter(valid_regimes)
        total = len(valid_regimes)
        percentages = {
            name: counts[name] / total
            for name in (
                "oscillating_sideways",
                "quiet_sideways",
                "uptrend",
                "downtrend",
                "deep_downtrend",
            )
        }
        deep_count = counts["deep_downtrend"]
        deep_pct = deep_count / total
        favorable = (
            percentages["oscillating_sideways"] + percentages["uptrend"]
        )
        recent = train_rows[-config.liquidity_lookback_sessions :]
        median_value = median(
            [bar.close_vnd * bar.matched_quantity for bar in recent]
        )
        reasons: list[str] = []
        try:
            atr_pct = calculate_atr_pct(train_rows, config.atr_sessions)
        except ValueError:
            atr_pct = math.nan
            reasons.append("invalid_atr_reference_window")
        if not math.isnan(atr_pct):
            if atr_pct > config.maximum_grid_step:
                reasons.append("atr_above_maximum_grid_step")
            sizing_step = min(
                config.maximum_grid_step,
                max(config.minimum_grid_step, atr_pct),
            )
            sizing_buy = round_to_hsx_tick(
                train_rows[-1].close_vnd / (1.0 + sizing_step), "buy"
            )
            one_lot_cash, _ = acquisition_cash(
                sizing_buy, config.board_lot, config
            )
            sizing_stress_price = consecutive_floor_price(
                sizing_buy,
                3,
                config.stress_floor_limit_fraction,
            )
            sizing_stress_price = _execution_sell_price(
                sizing_stress_price, None, config
            )
            one_lot_stress_sale, _, _ = net_sale_cash(
                sizing_stress_price, config.board_lot, config
            )
            if (
                one_lot_cash
                > portfolio_nav_vnd
                * config.maximum_ticker_exposure_fraction
                or one_lot_cash - one_lot_stress_sale
                > portfolio_nav_vnd
                * config.maximum_ticker_stress_loss_fraction
            ):
                reasons.append("one_board_lot_exceeds_risk_budget")
        if total < config.minimum_valid_regime_windows:
            reasons.append("insufficient_valid_regime_windows")
        if percentages["oscillating_sideways"] < config.minimum_oscillating_pct:
            reasons.append("insufficient_oscillation_history")
        if (
            percentages["downtrend"] + percentages["deep_downtrend"]
            > config.maximum_downtrend_pct
        ):
            reasons.append("excess_downtrend_history")
        if deep_pct > config.maximum_deep_downtrend_pct:
            reasons.append("excess_deep_downtrend_history")
        if favorable < config.minimum_favorable_pct:
            reasons.append("insufficient_favorable_history")
        if latest_regime in {
            "downtrend",
            "deep_downtrend",
            "excluded_reference_reset",
        }:
            reasons.append("latest_regime_veto")
        if any(
            regimes[index] == "deep_downtrend"
            for index in range(max(0, len(regimes) - 6), len(regimes))
        ):
            reasons.append("recent_deep_downtrend_veto")
        if median_value < config.minimum_median_daily_value_vnd:
            reasons.append("insufficient_liquidity")

        oscillating_ranges = [
            ranges[index]
            for index in valid_indexes
            if regimes[index] == "oscillating_sideways"
        ]
        median_oscillating_range = (
            median(oscillating_ranges) if oscillating_ranges else 0.0
        )
        summaries.append(
            {
                "trial_id": TRIAL_ID,
                "fold_id": fold.fold_id,
                "as_of_date": fold.train_dates[-1],
                "rotation_start_nav_vnd": portfolio_nav_vnd,
                "tickersymbol": ticker,
                "observed_windows": len(windows),
                "valid_windows": total,
                "excluded_reset_windows": len(windows) - total,
                "oscillating_sideways_pct": percentages[
                    "oscillating_sideways"
                ],
                "quiet_sideways_pct": percentages["quiet_sideways"],
                "uptrend_pct": percentages["uptrend"],
                "downtrend_pct": percentages["downtrend"],
                "deep_downtrend_pct": deep_pct,
                "favorable_pct": favorable,
                "latest_regime": latest_regime,
                "median_daily_value_vnd": round(median_value),
                "atr20_pct": atr_pct,
                "median_oscillating_range_pct": median_oscillating_range,
                "eligible": not reasons,
                "ineligibility_reasons": "|".join(reasons),
                "selected_rank": "",
            }
        )

    eligible = sorted(
        (row for row in summaries if bool(row["eligible"])),
        key=lambda row: (
            float(row["deep_downtrend_pct"]),
            float(row["downtrend_pct"]) + float(row["deep_downtrend_pct"]),
            -float(row["oscillating_sideways_pct"]),
            -float(row["median_oscillating_range_pct"]),
            -float(row["median_daily_value_vnd"]),
            str(row["tickersymbol"]),
        ),
    )
    selected: list[dict[str, object]] = []
    used_sectors: set[str] = set()
    for row in eligible:
        sector = SECTOR_BY_TICKER[str(row["tickersymbol"])]
        if sector in used_sectors:
            continue
        selected.append(row)
        used_sectors.add(sector)
        if len(selected) == config.selected_tickers_per_fold:
            break
    ranks = {
        str(row["tickersymbol"]): rank
        for rank, row in enumerate(selected, start=1)
    }
    for row in summaries:
        row["selected_rank"] = ranks.get(str(row["tickersymbol"]), "")
    summaries.sort(
        key=lambda row: (
            0 if row["selected_rank"] != "" else 1,
            int(row["selected_rank"]) if row["selected_rank"] != "" else 999,
            float(row["deep_downtrend_pct"]),
            float(row["downtrend_pct"]) + float(row["deep_downtrend_pct"]),
            -float(row["oscillating_sideways_pct"]),
            str(row["tickersymbol"]),
        )
    )
    return summaries, [str(row["tickersymbol"]) for row in selected]


def month_keys(dates: Iterable[date]) -> list[str]:
    return sorted({f"{value.year:04d}_{value.month:02d}" for value in dates})


def minute_input_paths(minute_dir: Path, folds: Sequence[Fold]) -> list[Path]:
    keys = month_keys(value for fold in folds for value in fold.oos_dates)
    paths = [minute_dir / f"minute_bars_{key}.csv.gz" for key in keys]
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing minute files: {missing}")
    return paths


def composite_file_hash(paths: Sequence[Path]) -> str:
    return sha256_bytes(
        canonical_json(
            [
                {
                    "name": path.name,
                    "data_sha256": sha256_file(path),
                    "manifest_sha256": sha256_file(
                        path.with_suffix("").with_suffix(".json")
                    ),
                }
                for path in sorted(paths)
            ]
        )
    )


def validate_minute_manifests(
    paths: Sequence[Path], universe: Sequence[str]
) -> None:
    for path in paths:
        manifest_path = path.with_suffix("").with_suffix(".json")
        if not manifest_path.exists():
            raise FileNotFoundError(f"Missing minute manifest: {manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status") != "complete":
            raise ValueError(f"Incomplete minute month: {manifest_path}")
        if Path(str(manifest.get("file", ""))).name != path.name:
            raise ValueError(f"Minute manifest file mismatch: {manifest_path}")
        if set(manifest.get("requested_tickers", ())) != set(universe):
            raise ValueError(
                f"Minute manifest universe mismatch: {manifest_path}"
            )
        if manifest.get("missing_tickers") not in ([], None):
            raise ValueError(
                f"Minute manifest has missing tickers: {manifest_path}"
            )
        for field_name in (
            "duplicate_keys",
            "invalid_ohlc_rows",
            "invalid_quantity_rows",
        ):
            if int(manifest.get(field_name, -1)) != 0:
                raise ValueError(
                    f"Minute manifest reports {field_name}: {manifest_path}"
                )


def load_fold_minutes(
    minute_dir: Path, fold: Fold, selected: Sequence[str]
) -> tuple[dict[str, dict[date, list[MinuteBar]]], int]:
    selected_set = set(selected)
    allowed_dates = set(fold.oos_dates)
    grouped: dict[str, dict[date, list[MinuteBar]]] = defaultdict(
        lambda: defaultdict(list)
    )
    seen: set[tuple[str, datetime]] = set()
    skipped_missing = 0
    for key in month_keys(fold.oos_dates):
        path = minute_dir / f"minute_bars_{key}.csv.gz"
        with gzip.open(path, "rt", newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            missing = MINUTE_REQUIRED.difference(reader.fieldnames or ())
            if missing:
                raise ValueError(f"{path} missing columns: {sorted(missing)}")
            for row in reader:
                ticker = row["tickersymbol"].strip().upper()
                trading_date = date.fromisoformat(row["trading_date"])
                # Filter scope before parsing numeric values. This also protects
                # future/final rows in a month that straddles a boundary.
                if ticker not in selected_set or trading_date not in allowed_dates:
                    continue
                if row["market_session"].strip() not in {
                    "continuous_morning",
                    "continuous_afternoon",
                }:
                    raise ValueError(
                        f"Non-continuous minute row in scope: "
                        f"{ticker} {trading_date}"
                    )
                required_prices = (
                    row["matched_open"],
                    row["matched_high"],
                    row["matched_low"],
                    row["matched_close"],
                )
                if any(not value.strip() for value in required_prices):
                    skipped_missing += 1
                    continue
                event_time = datetime.fromisoformat(row["minute"])
                if event_time.date() != trading_date:
                    raise ValueError(
                        f"Minute/trading-date mismatch: {ticker} {event_time}"
                    )
                key_value = (ticker, event_time)
                if key_value in seen:
                    raise ValueError(f"Duplicate minute key: {key_value}")
                seen.add(key_value)
                open_vnd, high_vnd, low_vnd, close_vnd = (
                    quote_to_vnd(value) for value in required_prices
                )
                if high_vnd < max(open_vnd, low_vnd, close_vnd):
                    raise ValueError(f"Invalid minute high: {key_value}")
                if low_vnd > min(open_vnd, close_vnd):
                    raise ValueError(f"Invalid minute low: {key_value}")
                quantity = int(Decimal(row["matched_quantity"]))
                if quantity < 0:
                    raise ValueError(f"Negative minute quantity: {key_value}")
                bid_quantity = (
                    int(Decimal(row["last_best_bid_quantity"]))
                    if row["last_best_bid_quantity"].strip()
                    else None
                )
                ask_quantity = (
                    int(Decimal(row["last_best_ask_quantity"]))
                    if row["last_best_ask_quantity"].strip()
                    else None
                )
                if (
                    bid_quantity is not None
                    and bid_quantity < 0
                    or ask_quantity is not None
                    and ask_quantity < 0
                ):
                    raise ValueError(f"Negative book quantity: {key_value}")
                grouped[ticker][trading_date].append(
                    MinuteBar(
                        event_time=event_time,
                        trading_date=trading_date,
                        ticker=ticker,
                        open_vnd=open_vnd,
                        high_vnd=high_vnd,
                        low_vnd=low_vnd,
                        close_vnd=close_vnd,
                        matched_quantity=quantity,
                        best_bid_vnd=optional_quote_to_vnd(
                            row["last_best_bid"]
                        ),
                        best_bid_quantity=bid_quantity,
                        best_ask_vnd=optional_quote_to_vnd(
                            row["last_best_ask"]
                        ),
                        best_ask_quantity=ask_quantity,
                    )
                )
    for ticker in selected:
        for trading_date in fold.oos_dates:
            bars = grouped[ticker].get(trading_date, [])
            if not bars:
                raise ValueError(
                    f"No usable minute event for {ticker} {trading_date}"
                )
            bars.sort(key=lambda bar: bar.event_time)
    return grouped, skipped_missing


def settlement_datetime(
    event_date_index: int,
    oos_dates: Sequence[date],
    config: Config,
) -> datetime:
    settlement_index = event_date_index + config.settlement_sessions
    if settlement_index >= len(oos_dates):
        raise ValueError("Trade cannot settle inside deployment window")
    return datetime.combine(
        oos_dates[settlement_index],
        time.fromisoformat(config.settlement_time),
    )


def tradeable_quantity(levels: Sequence[Level], now: datetime) -> int:
    return sum(
        level.lot.quantity
        for level in levels
        if level.lot is not None and level.lot.tradeable_at <= now
    )


def total_quantity(levels: Sequence[Level]) -> int:
    return sum(
        level.lot.quantity for level in levels if level.lot is not None
    )


def create_grid(
    fold: Fold,
    ticker: str,
    fit_row: dict[str, object],
    anchor_vnd: int,
    slot_capital_vnd: int,
    config: Config,
) -> tuple[list[Level], list[dict[str, object]]]:
    atr_pct = float(fit_row["atr20_pct"])
    step = min(
        config.maximum_grid_step, max(config.minimum_grid_step, atr_pct)
    )
    portfolio_nav = slot_capital_vnd * config.selected_tickers_per_fold
    exposure_cap = portfolio_nav * config.maximum_ticker_exposure_fraction
    stress_loss_cap = (
        portfolio_nav * config.maximum_ticker_stress_loss_fraction
    )
    levels: list[Level] = []
    rows: list[dict[str, object]] = []
    level_id = 0
    buy_limit = round_to_hsx_tick(anchor_vnd / (1.0 + step), "buy")
    sell_target = round_to_hsx_tick(anchor_vnd, "sell")
    lower = round_to_hsx_tick(
        anchor_vnd / ((1.0 + step) ** 3), "buy"
    )
    per_lot_cash, _ = acquisition_cash(
        buy_limit, config.board_lot, config
    )
    stress_price = consecutive_floor_price(
        buy_limit,
        3,
        config.stress_floor_limit_fraction,
    )
    stress_price = _execution_sell_price(
        stress_price, None, config
    )
    stressed_sale, _, _ = net_sale_cash(
        stress_price, config.board_lot, config
    )
    stress_loss_per_lot = per_lot_cash - stressed_sale
    lots_by_exposure = int(exposure_cap // per_lot_cash)
    lots_by_stress = (
        int(stress_loss_cap // stress_loss_per_lot)
        if stress_loss_per_lot > 0
        else lots_by_exposure
    )
    quantity = (
        min(lots_by_exposure, lots_by_stress) * config.board_lot
    )
    levels.append(
        Level(
            level_id=level_id,
            buy_limit_vnd=buy_limit,
            sell_target_vnd=sell_target,
            quantity=quantity,
        )
    )
    rows.append(
        {
            "trial_id": TRIAL_ID,
            "fold_id": fold.fold_id,
            "tickersymbol": ticker,
            "fit_end": fold.train_dates[-1],
            "deployment_start": fold.oos_dates[0],
            "deployment_end": fold.oos_dates[-1],
            "anchor_vnd": anchor_vnd,
            "grid_step_pct": step,
            "lower_bound_vnd": lower,
            "upper_bound_vnd": sell_target,
            "slot_capital_vnd": slot_capital_vnd,
            "reserve_fraction": 1.0
            - (exposure_cap / slot_capital_vnd),
            "level_id": level_id,
            "buy_limit_vnd": buy_limit,
            "sell_target_vnd": sell_target,
            "quantity": quantity,
        }
    )
    return levels, rows


def _execution_buy_price(
    ask_vnd: int,
    limit_vnd: int,
    config: Config,
    cost_multiplier: float = 1.0,
) -> int:
    stressed = round_to_hsx_tick(
        ask_vnd
        * (1.0 + config.execution_haircut * cost_multiplier),
        "sell",
    )
    return min(limit_vnd, stressed)


def _execution_sell_price(
    bid_vnd: int,
    limit_vnd: int | None,
    config: Config,
    cost_multiplier: float = 1.0,
) -> int:
    stressed = round_to_hsx_tick(
        bid_vnd
        * (1.0 - config.execution_haircut * cost_multiplier),
        "buy",
    )
    return max(limit_vnd, stressed) if limit_vnd is not None else stressed


def spread_bps(bar: MinuteBar) -> float | None:
    if (
        bar.best_bid_vnd is None
        or bar.best_ask_vnd is None
        or bar.best_bid_vnd <= 0
        or bar.best_ask_vnd < bar.best_bid_vnd
    ):
        return None
    midpoint = (bar.best_bid_vnd + bar.best_ask_vnd) / 2.0
    return 10_000.0 * (bar.best_ask_vnd - bar.best_bid_vnd) / midpoint


def entry_gate(
    historical_rows: Sequence[DailyBar],
    buy_limit_vnd: int,
    config: Config,
) -> bool:
    """Return whether a buy order may be armed for the next session.

    ``historical_rows`` must end at T-1. Nothing from session T is accepted.
    """
    if len(historical_rows) < 50:
        return False
    reference_window = historical_rows[-50:]
    if any(
        not row.reset_verifiable or row.reference_reset
        for row in reference_window
    ):
        return False
    closes50 = [row.close_vnd for row in reference_window]
    if closes50[-1] <= statistics.mean(closes50):
        return False
    if len(historical_rows) < 11:
        return False
    closes11 = [row.close_vnd for row in historical_rows[-11:]]
    return10 = closes11[-1] / closes11[0] - 1.0
    if return10 <= config.deep_downtrend_return:
        return False
    if not (efficiency_ratio(closes11) < config.er_threshold or return10 >= 0):
        return False
    return closes11[-1] > buy_limit_vnd


def simulate_account(
    fold: Fold,
    ticker: str,
    fit_row: dict[str, object],
    daily_rows: Sequence[DailyBar],
    minutes: dict[date, list[MinuteBar]],
    slot_capital_vnd: int,
    config: Config,
    cost_multiplier: float = 1.0,
    cost_scenario: str = "primary",
    external_shutdown_date: date | None = None,
) -> AccountResult:
    by_date = {bar.trading_date: bar for bar in daily_rows}
    anchor = by_date[fold.train_dates[-1]].close_vnd
    levels, grid_rows = create_grid(
        fold, ticker, fit_row, anchor, slot_capital_vnd, config
    )
    if any(level.quantity < config.board_lot for level in levels):
        daily_states = [
            {
                "trial_id": TRIAL_ID,
                "fold_id": fold.fold_id,
                "trading_date": trading_date,
                "tickersymbol": ticker,
                "available_cash_vnd": slot_capital_vnd,
                "pending_cash_vnd": 0,
                "inventory_liquidation_value_vnd": 0,
                "account_equity_vnd": slot_capital_vnd,
                "total_quantity": 0,
                "tradeable_quantity": 0,
                "locked_quantity": 0,
                "shutdown": (
                    external_shutdown_date is not None
                    and trading_date >= external_shutdown_date
                ),
                "shutdown_reason": (
                    "portfolio_high_water_kill"
                    if external_shutdown_date is not None
                    and trading_date >= external_shutdown_date
                    else "risk_budget_below_one_board_lot"
                ),
            }
            for trading_date in fold.oos_dates
        ]
        return AccountResult(
            True,
            "",
            slot_capital_vnd,
            [],
            daily_states,
            grid_rows,
            False,
            0,
            0,
            0,
        )

    available_cash = slot_capital_vnd
    pending_cash: list[PendingCash] = []
    trades: list[dict[str, object]] = []
    daily_states: list[dict[str, object]] = []
    shutdown = False
    shutdown_reason = ""
    completed_cycles = 0
    planned_turnover_vnd = 0
    turnover_budget_vnd = int(
        slot_capital_vnd
        * config.selected_tickers_per_fold
        * config.maximum_ticker_turnover_fraction
    )
    previous_equity = slot_capital_vnd
    equity_high_water = slot_capital_vnd
    date_positions = {value: index for index, value in enumerate(fold.oos_dates)}
    wind_down_index = len(fold.oos_dates) - config.wind_down_sessions
    last_buy_index = wind_down_index - config.settlement_sessions

    def release_cash(now: datetime) -> None:
        nonlocal available_cash, pending_cash
        matured = [item for item in pending_cash if item.available_at <= now]
        available_cash += sum(item.amount_vnd for item in matured)
        pending_cash = [
            item for item in pending_cash if item.available_at > now
        ]

    def account_quantities(now: datetime) -> tuple[int, int, int]:
        total = total_quantity(levels)
        tradeable = tradeable_quantity(levels, now)
        return total, tradeable, total - tradeable

    def append_trade(
        *,
        bar: MinuteBar,
        side: str,
        reason: str,
        level: Level,
        reference_book_price_vnd: int,
        price_vnd: int,
        settlement_locked_at_risk_trigger: bool,
        gross: int,
        commission: int,
        sell_tax: int,
        cash_change: int,
        realized_pnl: int | str,
        settlement_at: datetime,
    ) -> None:
        total, tradeable, locked = account_quantities(bar.event_time)
        execution_friction = (
            max(0, price_vnd - reference_book_price_vnd) * level.quantity
            if side == "BUY"
            else max(0, reference_book_price_vnd - price_vnd)
            * level.quantity
        )
        trades.append(
            {
                "trial_id": TRIAL_ID,
                "fold_id": fold.fold_id,
                "tickersymbol": ticker,
                "cost_scenario": cost_scenario,
                "event_time": bar.event_time,
                "side": side,
                "reason": reason,
                "level_id": level.level_id,
                "quantity": level.quantity,
                "reference_book_price_vnd": reference_book_price_vnd,
                "execution_price_vnd": price_vnd,
                "execution_friction_vnd": execution_friction,
                "settlement_locked_at_risk_trigger": (
                    settlement_locked_at_risk_trigger
                ),
                "gross_notional_vnd": gross,
                "commission_vnd": commission,
                "sell_tax_vnd": sell_tax,
                "cash_change_vnd": cash_change,
                "realized_pnl_vnd": realized_pnl,
                "settlement_time": settlement_at,
                "total_quantity_after": total,
                "tradeable_quantity_after": tradeable,
                "locked_quantity_after": locked,
                "available_cash_after_vnd": available_cash,
                "pending_cash_after_vnd": sum(
                    item.amount_vnd for item in pending_cash
                ),
            }
        )

    for oos_index, trading_date in enumerate(fold.oos_dates):
        daily_bar = by_date[trading_date]
        if (
            external_shutdown_date is not None
            and trading_date >= external_shutdown_date
        ):
            shutdown = True
            shutdown_reason = "portfolio_high_water_kill"
        if not daily_bar.reset_verifiable or daily_bar.reference_reset:
            if not (shutdown and total_quantity(levels) == 0):
                reason = (
                    "unverifiable_reference"
                    if not daily_bar.reset_verifiable
                    else "corporate_action_reference_reset"
                )
                return AccountResult(
                    False,
                    reason,
                    previous_equity,
                    trades,
                    daily_states,
                    grid_rows,
                    shutdown,
                    completed_cycles,
                    total_quantity(levels),
                    sum(item.amount_vnd for item in pending_cash),
                )

        # All risk decisions for this session use information through T-1.
        historical_dates = list(fold.train_dates) + list(
            fold.oos_dates[:oos_index]
        )
        if oos_index > 0 and not shutdown:
            if len(historical_dates) >= config.regime_sessions + 1:
                recent_end = by_date[historical_dates[-1]].close_vnd
                recent_start = by_date[
                    historical_dates[-(config.regime_sessions + 1)]
                ].close_vnd
                if recent_end / recent_start - 1.0 <= config.deep_downtrend_return:
                    shutdown = True
                    shutdown_reason = "prior_close_deep_downtrend"
            if (
                previous_equity / equity_high_water - 1.0
                <= config.account_stop_drawdown
            ):
                shutdown = True
                shutdown_reason = "prior_close_account_drawdown"
            if by_date[fold.oos_dates[oos_index - 1]].close_vnd <= int(
                grid_rows[0]["lower_bound_vnd"]
            ):
                shutdown = True
                shutdown_reason = "prior_close_below_grid"

        wind_down = oos_index >= wind_down_index
        if wind_down and not shutdown_reason:
            shutdown_reason = "scheduled_rotation_exit"
        if shutdown:
            session_start = datetime.combine(trading_date, time(9, 0))
            for level in levels:
                if (
                    level.lot is not None
                    and level.lot.tradeable_at > session_start
                ):
                    level.lot.risk_triggered_while_locked = True

        flat_at_session_start = total_quantity(levels) == 0
        buy_armed = (
            flat_at_session_start
            and not shutdown
            and not wind_down
            and oos_index <= last_buy_index
            and entry_gate(
                [by_date[value] for value in historical_dates],
                levels[0].buy_limit_vnd,
                config,
            )
        )
        if (
            oos_index > wind_down_index
            and total_quantity(levels) > 0
        ):
            return AccountResult(
                False,
                "wind_down_did_not_complete_on_scheduled_session",
                previous_equity,
                trades,
                daily_states,
                grid_rows,
                shutdown,
                completed_cycles,
                total_quantity(levels),
                sum(item.amount_vnd for item in pending_cash),
            )

        for bar in minutes[trading_date]:
            release_cash(bar.event_time)
            available_bid = bar.best_bid_quantity or 0
            available_ask = bar.best_ask_quantity or 0
            current_spread = spread_bps(bar)
            participation_capacity = int(
                bar.matched_quantity * config.maximum_minute_participation
            )

            # Existing inventory is handled before new buys. Newly bought
            # shares can never be sold in this minute because of settlement.
            for level in levels:
                lot = level.lot
                if lot is None or lot.tradeable_at > bar.event_time:
                    continue
                exit_reason = ""
                limit: int | None = None
                if shutdown:
                    exit_reason = shutdown_reason
                elif wind_down:
                    exit_reason = "scheduled_rotation_exit"
                elif (
                    bar.best_bid_vnd is not None
                    and bar.best_bid_vnd >= level.sell_target_vnd
                    and bar.close_vnd
                    >= level.sell_target_vnd
                    + hsx_tick_vnd(level.sell_target_vnd)
                    and current_spread is not None
                    and current_spread <= config.maximum_normal_spread_bps
                ):
                    exit_reason = "grid_target"
                    limit = level.sell_target_vnd
                if (
                    not exit_reason
                    or bar.best_bid_vnd is None
                    or current_spread is None
                    or available_bid < lot.quantity
                    or participation_capacity < lot.quantity
                ):
                    continue
                execution_price = _execution_sell_price(
                    bar.best_bid_vnd,
                    limit,
                    config,
                    cost_multiplier,
                )
                proceeds, commission, sell_tax = net_sale_cash(
                    execution_price,
                    lot.quantity,
                    config,
                    cost_multiplier,
                )
                settlement_at = settlement_datetime(
                    oos_index, fold.oos_dates, config
                )
                pending_cash.append(PendingCash(proceeds, settlement_at))
                available_bid -= lot.quantity
                realized = proceeds - lot.acquisition_cash_vnd
                locked_at_risk_trigger = lot.risk_triggered_while_locked
                level.lot = None
                level.rearm_after = settlement_at
                if exit_reason == "grid_target":
                    completed_cycles += 1
                append_trade(
                    bar=bar,
                    side="SELL",
                    reason=exit_reason,
                    level=level,
                    reference_book_price_vnd=bar.best_bid_vnd,
                    price_vnd=execution_price,
                    settlement_locked_at_risk_trigger=(
                        locked_at_risk_trigger
                    ),
                    gross=execution_price * level.quantity,
                    commission=commission,
                    sell_tax=sell_tax,
                    cash_change=proceeds,
                    realized_pnl=realized,
                    settlement_at=settlement_at,
                )

            if (
                shutdown
                or wind_down
                or not buy_armed
                or oos_index > last_buy_index
            ):
                continue
            if (
                bar.best_ask_vnd is None
                or current_spread is None
                or current_spread > config.maximum_normal_spread_bps
            ):
                continue
            for level in levels:
                if (
                    level.lot is not None
                    or (
                        level.rearm_after is not None
                        and bar.event_time <= level.rearm_after
                    )
                    or bar.best_ask_vnd > level.buy_limit_vnd
                    or bar.close_vnd
                    > level.buy_limit_vnd
                    - hsx_tick_vnd(level.buy_limit_vnd)
                    or available_ask < level.quantity
                    or participation_capacity < level.quantity
                ):
                    continue
                execution_price = _execution_buy_price(
                    bar.best_ask_vnd,
                    level.buy_limit_vnd,
                    config,
                    cost_multiplier,
                )
                cash, commission = acquisition_cash(
                    execution_price,
                    level.quantity,
                    config,
                    cost_multiplier,
                )
                if cash > available_cash:
                    continue
                planned_round_trip = (
                    execution_price + level.sell_target_vnd
                ) * level.quantity
                if (
                    planned_turnover_vnd + planned_round_trip
                    > turnover_budget_vnd
                ):
                    continue
                available_cash -= cash
                available_ask -= level.quantity
                planned_turnover_vnd += planned_round_trip
                tradeable_at = settlement_datetime(
                    oos_index, fold.oos_dates, config
                )
                level.lot = Lot(
                    level_id=level.level_id,
                    quantity=level.quantity,
                    acquisition_cash_vnd=cash,
                    target_vnd=level.sell_target_vnd,
                    tradeable_at=tradeable_at,
                )
                append_trade(
                    bar=bar,
                    side="BUY",
                    reason="grid_buy",
                    level=level,
                    reference_book_price_vnd=bar.best_ask_vnd,
                    price_vnd=execution_price,
                    settlement_locked_at_risk_trigger=False,
                    gross=execution_price * level.quantity,
                    commission=commission,
                    sell_tax=0,
                    cash_change=-cash,
                    realized_pnl="",
                    settlement_at=tradeable_at,
                )

        last_bar = minutes[trading_date][-1]
        end_of_day = datetime.combine(trading_date, time(15, 0))
        release_cash(end_of_day)
        pending_value = sum(item.amount_vnd for item in pending_cash)
        inventory_value = 0
        for level in levels:
            if level.lot is not None:
                liquidation_price = _execution_sell_price(
                    daily_bar.close_vnd,
                    None,
                    config,
                    cost_multiplier,
                )
                liquidation, _, _ = net_sale_cash(
                    liquidation_price,
                    level.lot.quantity,
                    config,
                    cost_multiplier,
                )
                inventory_value += liquidation
        equity = available_cash + pending_value + inventory_value
        total, tradeable, locked = account_quantities(end_of_day)
        daily_states.append(
            {
                "trial_id": TRIAL_ID,
                "fold_id": fold.fold_id,
                "trading_date": trading_date,
                "tickersymbol": ticker,
                "available_cash_vnd": available_cash,
                "pending_cash_vnd": pending_value,
                "inventory_liquidation_value_vnd": inventory_value,
                "account_equity_vnd": equity,
                "total_quantity": total,
                "tradeable_quantity": tradeable,
                "locked_quantity": locked,
                "shutdown": shutdown or wind_down,
                "shutdown_reason": shutdown_reason,
            }
        )
        previous_equity = equity
        equity_high_water = max(equity_high_water, equity)

    ending_quantity = total_quantity(levels)
    ending_pending = sum(item.amount_vnd for item in pending_cash)
    valid = ending_quantity == 0 and ending_pending == 0
    reason = "" if valid else "unsettled_or_open_position_at_rotation_end"
    return AccountResult(
        valid=valid,
        quarantine_reason=reason,
        ending_equity_vnd=available_cash + ending_pending,
        trades=trades,
        daily_states=daily_states,
        grid_rows=grid_rows,
        shutdown=shutdown,
        completed_cycles=completed_cycles,
        ending_quantity=ending_quantity,
        ending_pending_cash_vnd=ending_pending,
    )


def benchmark_return(
    fold: Fold,
    selected: Sequence[str],
    minutes: dict[str, dict[date, list[MinuteBar]]],
    slot_capital_vnd: int,
    starting_capital_vnd: int,
    config: Config,
) -> float | None:
    remainder_cash = (
        starting_capital_vnd
        - slot_capital_vnd * config.selected_tickers_per_fold
    )
    total_end = slot_capital_vnd * (
        config.selected_tickers_per_fold - len(selected)
    ) + remainder_cash
    for ticker in selected:
        budget = (
            slot_capital_vnd
            * config.selected_tickers_per_fold
            * config.maximum_ticker_exposure_fraction
        )
        buy_choice: tuple[MinuteBar, int, int] | None = None
        for bar in minutes[ticker][fold.oos_dates[0]]:
            if bar.best_ask_vnd is None:
                continue
            current_spread = spread_bps(bar)
            if (
                current_spread is None
                or current_spread > config.maximum_normal_spread_bps
            ):
                continue
            price = round_to_hsx_tick(
                bar.best_ask_vnd * (1.0 + config.execution_haircut),
                "sell",
            )
            per_lot, _ = acquisition_cash(
                price, config.board_lot, config
            )
            quantity = int(budget // per_lot) * config.board_lot
            if (
                quantity >= config.board_lot
                and (bar.best_ask_quantity or 0) >= quantity
                and int(
                    bar.matched_quantity
                    * config.maximum_minute_participation
                )
                >= quantity
            ):
                buy_choice = (bar, price, quantity)
                break
        if buy_choice is None:
            return None
        buy_bar, buy_price, quantity = buy_choice
        sell_bar = next(
            (
                bar
                for bar in minutes[ticker][
                    fold.oos_dates[-config.wind_down_sessions]
                ]
                if (
                    bar.best_bid_vnd is not None
                    and spread_bps(bar) is not None
                    and spread_bps(bar)
                    <= config.maximum_normal_spread_bps
                    and (bar.best_bid_quantity or 0) >= quantity
                    and int(
                        bar.matched_quantity
                        * config.maximum_minute_participation
                    )
                    >= quantity
                )
            ),
            None,
        )
        if sell_bar is None:
            return None
        acquisition, _ = acquisition_cash(buy_price, quantity, config)
        sell_price = _execution_sell_price(
            sell_bar.best_bid_vnd, None, config
        )
        proceeds, _, _ = net_sale_cash(sell_price, quantity, config)
        total_end += slot_capital_vnd - acquisition + proceeds
    return total_end / starting_capital_vnd - 1.0


def maximum_drawdown(values: Sequence[float | int]) -> float | None:
    if not values:
        return None
    peak = float(values[0])
    worst = 0.0
    for value in values:
        numeric = float(value)
        peak = max(peak, numeric)
        worst = min(worst, numeric / peak - 1.0)
    return worst


def profit_factor(pnls: Sequence[float | int]) -> float | str | None:
    gains = sum(value for value in pnls if value > 0)
    losses = -sum(value for value in pnls if value < 0)
    if losses == 0:
        return "infinity" if gains > 0 else None
    return gains / losses


def detect_portfolio_kill(
    portfolio_daily: Sequence[dict[str, object]],
    fold_dates: Sequence[date],
    initial_high_water_vnd: int,
    drawdown_limit: float,
) -> tuple[bool, date | None, int]:
    """Detect an EOD breach and return the next-session effective date."""
    high_water = initial_high_water_vnd
    for index, row in enumerate(portfolio_daily):
        equity = int(row["portfolio_equity_vnd"])
        high_water = max(high_water, equity)
        if equity / high_water - 1.0 <= drawdown_limit:
            effective_date = (
                fold_dates[index + 1]
                if index + 1 < len(fold_dates)
                else None
            )
            return True, effective_date, high_water
    return False, None, high_water


def simulate_fold(
    fold: Fold,
    selection_rows: Sequence[dict[str, object]],
    selected: Sequence[str],
    daily: dict[str, list[DailyBar]],
    minutes: dict[str, dict[date, list[MinuteBar]]],
    config: Config,
    starting_capital_vnd: int,
    portfolio_high_water_vnd: int | None = None,
    portfolio_kill_active: bool = False,
) -> tuple[
    dict[str, object],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
]:
    slot_capital = (
        starting_capital_vnd // config.selected_tickers_per_fold
    )
    remainder_cash = (
        starting_capital_vnd
        - slot_capital * config.selected_tickers_per_fold
    )
    fit_by_ticker = {
        str(row["tickersymbol"]): row for row in selection_rows
    }
    initial_high_water = max(
        starting_capital_vnd,
        portfolio_high_water_vnd or starting_capital_vnd,
    )
    missing_slots = config.selected_tickers_per_fold - len(selected)

    def run_accounts(
        cost_multiplier: float,
        cost_scenario: str,
        external_shutdown_date: date | None,
    ) -> dict[str, AccountResult]:
        return {
            ticker: simulate_account(
                fold,
                ticker,
                fit_by_ticker[ticker],
                daily[ticker],
                minutes[ticker],
                slot_capital,
                config,
                cost_multiplier,
                cost_scenario,
                external_shutdown_date,
            )
            for ticker in selected
        }

    def combine_daily(
        results: dict[str, AccountResult],
        kill_effective_date: date | None,
    ) -> list[dict[str, object]]:
        account_rows = [
            row
            for ticker in selected
            for row in results[ticker].daily_states
        ]
        by_ticker_date = {
            (str(row["tickersymbol"]), row["trading_date"]): row
            for row in account_rows
        }
        combined: list[dict[str, object]] = []
        for trading_date in fold.oos_dates:
            selected_states = [
                by_ticker_date.get((ticker, trading_date))
                for ticker in selected
            ]
            if any(state is None for state in selected_states):
                break
            available_cash = (
                remainder_cash
                + slot_capital * missing_slots
                + sum(
                    int(state["available_cash_vnd"])  # type: ignore[index]
                    for state in selected_states
                )
            )
            pending_cash = sum(
                int(state["pending_cash_vnd"])  # type: ignore[index]
                for state in selected_states
            )
            inventory_value = sum(
                int(
                    state["inventory_liquidation_value_vnd"]  # type: ignore[index]
                )
                for state in selected_states
            )
            equity = available_cash + pending_cash + inventory_value
            combined.append(
                {
                    "trial_id": TRIAL_ID,
                    "fold_id": fold.fold_id,
                    "trading_date": trading_date,
                    "portfolio_equity_vnd": equity,
                    "fold_return_to_date": (
                        equity / starting_capital_vnd - 1.0
                    ),
                    "available_cash_vnd": available_cash,
                    "pending_cash_vnd": pending_cash,
                    "inventory_liquidation_value_vnd": inventory_value,
                    "total_quantity": sum(
                        int(state["total_quantity"])  # type: ignore[index]
                        for state in selected_states
                    ),
                    "tradeable_quantity": sum(
                        int(state["tradeable_quantity"])  # type: ignore[index]
                        for state in selected_states
                    ),
                    "locked_quantity": sum(
                        int(state["locked_quantity"])  # type: ignore[index]
                        for state in selected_states
                    ),
                    "portfolio_kill_active": (
                        kill_effective_date is not None
                        and trading_date >= kill_effective_date
                    ),
                }
            )
        return combined

    initial_external_shutdown = (
        fold.oos_dates[0] if portfolio_kill_active else None
    )
    normal_results = run_accounts(
        1.0, "primary", initial_external_shutdown
    )
    preliminary_daily = combine_daily(
        normal_results, initial_external_shutdown
    )
    kill_triggered = False
    kill_effective_date = initial_external_shutdown
    running_high_water = initial_high_water
    if not portfolio_kill_active:
        (
            kill_triggered,
            kill_effective_date,
            running_high_water,
        ) = detect_portfolio_kill(
            preliminary_daily,
            fold.oos_dates,
            initial_high_water,
            config.portfolio_kill_drawdown,
        )
    if kill_triggered and kill_effective_date is not None:
        normal_results = run_accounts(
            1.0, "primary", kill_effective_date
        )
    doubled_results = run_accounts(
        2.0,
        "doubled",
        (
            fold.oos_dates[0]
            if portfolio_kill_active
            else kill_effective_date
        ),
    )
    portfolio_daily = combine_daily(
        normal_results,
        (
            fold.oos_dates[0]
            if portfolio_kill_active
            else kill_effective_date
        ),
    )
    ending_high_water = max(
        [initial_high_water]
        + [int(row["portfolio_equity_vnd"]) for row in portfolio_daily]
    )

    quarantine: list[dict[str, object]] = []
    for ticker in selected:
        if not normal_results[ticker].valid:
            quarantine.append(
                {
                    "trial_id": TRIAL_ID,
                    "fold_id": fold.fold_id,
                    "tickersymbol": ticker,
                    "trading_date": "",
                    "reason": normal_results[ticker].quarantine_reason,
                }
            )

    normal_valid = all(result.valid for result in normal_results.values())
    doubled_valid = all(result.valid for result in doubled_results.values())
    valid = normal_valid
    ending = remainder_cash + slot_capital * missing_slots + sum(
        result.ending_equity_vnd for result in normal_results.values()
    )
    doubled_ending = remainder_cash + slot_capital * missing_slots + sum(
        result.ending_equity_vnd for result in doubled_results.values()
    )
    primary_trades = [
        trade
        for ticker in selected
        for trade in normal_results[ticker].trades
    ]
    doubled_trades = [
        trade
        for ticker in selected
        for trade in doubled_results[ticker].trades
    ]
    trades = primary_trades + doubled_trades
    grid_rows = [
        row
        for ticker in selected
        for row in normal_results[ticker].grid_rows
    ]
    account_daily = [
        row
        for ticker in selected
        for row in normal_results[ticker].daily_states
    ]

    sell_trades = [
        row
        for row in primary_trades
        if row["side"] == "SELL"
    ]
    realized_pnls = [int(row["realized_pnl_vnd"]) for row in sell_trades]
    settlement_locked_exit_loss = -sum(
        min(0, int(row["realized_pnl_vnd"]))
        for row in sell_trades
        if bool(row["settlement_locked_at_risk_trigger"])
    )
    gross_turnover = sum(
        int(row["gross_notional_vnd"]) for row in primary_trades
    )
    modeled_cost = sum(
        int(row["commission_vnd"])
        + int(row["sell_tax_vnd"])
        + int(row["execution_friction_vnd"])
        for row in primary_trades
    )
    market_returns: list[float] = []
    for ticker in config.universe:
        if ticker not in daily:
            continue
        ticker_by_date = {
            bar.trading_date: bar for bar in daily[ticker]
        }
        market_returns.append(
            ticker_by_date[fold.oos_dates[-1]].close_vnd
            / ticker_by_date[fold.train_dates[-1]].close_vnd
            - 1.0
        )
    if daily and len(market_returns) != len(config.universe):
        raise ValueError("Market proxy requires the complete fixed universe")
    market_proxy_return = (
        statistics.mean(market_returns) if market_returns else 0.0
    )
    if market_proxy_return <= config.market_downtrend_return:
        market_regime = "downtrend"
    elif market_proxy_return >= config.market_uptrend_return:
        market_regime = "uptrend"
    else:
        market_regime = "neutral"
    utilization = [
        int(row["inventory_liquidation_value_vnd"])
        / starting_capital_vnd
        for row in portfolio_daily
    ]
    benchmark = benchmark_return(
        fold,
        selected,
        minutes,
        slot_capital,
        starting_capital_vnd,
        config,
    )
    doubled_reasons = {
        f"doubled_cost:{result.quarantine_reason}"
        for result in doubled_results.values()
        if not result.valid
    }
    quarantine_reason = "|".join(
        sorted(
            {str(row["reason"]) for row in quarantine}.union(doubled_reasons)
        )
    )
    fold_row = {
        "trial_id": TRIAL_ID,
        "fold_id": fold.fold_id,
        "train_start": fold.train_dates[0],
        "train_end": fold.train_dates[-1],
        "oos_start": fold.oos_dates[0],
        "oos_end": fold.oos_dates[-1],
        "selected_tickers": "|".join(selected),
        "selected_count": len(selected),
        "valid": valid,
        "doubled_cost_valid": doubled_valid,
        "portfolio_kill_triggered": kill_triggered,
        "portfolio_kill_effective_date": (
            kill_effective_date if kill_effective_date is not None else ""
        ),
        "portfolio_high_water_end_vnd": ending_high_water,
        "quarantine_reason": quarantine_reason,
        "starting_capital_vnd": starting_capital_vnd,
        "ending_capital_vnd": ending if valid else "",
        "net_return": (
            ending / starting_capital_vnd - 1.0 if valid else ""
        ),
        "doubled_cost_return": (
            doubled_ending / starting_capital_vnd - 1.0
            if valid and doubled_valid
            else ""
        ),
        "benchmark_return": benchmark if benchmark is not None else "",
        "market_proxy_return": market_proxy_return,
        "market_regime": market_regime,
        "maximum_drawdown": (
            maximum_drawdown(
                [starting_capital_vnd]
                + [
                    int(row["portfolio_equity_vnd"])
                    for row in portfolio_daily
                ]
            )
            if valid
            else ""
        ),
        "average_capital_utilization": (
            statistics.mean(utilization) if utilization else 0.0
        ),
        "maximum_capital_utilization": max(utilization, default=0.0),
        "buy_count": sum(row["side"] == "BUY" for row in primary_trades),
        "sell_count": len(sell_trades),
        "completed_grid_cycles": sum(
            result.completed_cycles for result in normal_results.values()
        ),
        "gross_turnover_vnd": gross_turnover,
        "turnover_fraction": gross_turnover / starting_capital_vnd,
        "modeled_cost_vnd": modeled_cost,
        "modeled_cost_fraction": modeled_cost / starting_capital_vnd,
        "settlement_locked_exit_loss_vnd": settlement_locked_exit_loss,
        "realized_pnl_vnd": sum(realized_pnls),
        "profit_factor": profit_factor(realized_pnls),
        "shutdown_count": sum(
            result.shutdown for result in normal_results.values()
        ),
        "minimum_tradeable_quantity": min(
            (
                int(row["tradeable_quantity"])
                for row in portfolio_daily
            ),
            default=0,
        ),
        "ending_total_quantity": sum(
            result.ending_quantity for result in normal_results.values()
        ),
        "ending_pending_cash_vnd": sum(
            result.ending_pending_cash_vnd
            for result in normal_results.values()
        ),
    }
    return fold_row, trades, grid_rows, account_daily, portfolio_daily + quarantine


def compounded_return(values: Sequence[float]) -> float | None:
    if not values:
        return None
    wealth = 1.0
    for value in values:
        wealth *= 1.0 + value
    return wealth - 1.0


def annualized_sharpe(values: Sequence[float]) -> float | None:
    if len(values) < 2:
        return None
    standard_deviation = statistics.stdev(values)
    if standard_deviation == 0:
        return None
    return statistics.mean(values) / standard_deviation * math.sqrt(6.0)


def numeric_profit_factor_at_least(value: object, threshold: float) -> bool:
    if value == "infinity":
        return True
    return value is not None and float(value) >= threshold


def evaluate_gates(
    folds: Sequence[dict[str, object]],
    trades: Sequence[dict[str, object]],
    portfolio_daily: Sequence[dict[str, object]],
    config: Config,
) -> dict[str, object]:
    valid = [row for row in folds if bool(row["valid"])]
    returns = [float(row["net_return"]) for row in valid]
    doubled_valid = [
        row for row in valid if bool(row["doubled_cost_valid"])
    ]
    doubled = [
        float(row["doubled_cost_return"]) for row in doubled_valid
    ]
    benchmarks = [
        float(row["benchmark_return"])
        for row in valid
        if row["benchmark_return"] != ""
    ]
    valid_ids = {str(row["fold_id"]) for row in valid}
    active = [row for row in valid if int(row["buy_count"]) > 0]
    completed_campaigns = sum(
        int(row["completed_grid_cycles"]) for row in valid
    )
    profitable_fraction = (
        sum(value > 0 for value in returns) / len(returns)
        if returns
        else None
    )
    primary_trades = [
        row
        for row in trades
        if (
            row["cost_scenario"] == "primary"
            and str(row["fold_id"]) in valid_ids
        )
    ]
    realized_pnls = [
        int(row["realized_pnl_vnd"])
        for row in primary_trades
        if row["side"] == "SELL"
    ]
    doubled_realized_pnls = [
        int(row["realized_pnl_vnd"])
        for row in trades
        if (
            row["side"] == "SELL"
            and row["cost_scenario"] == "doubled"
            and str(row["fold_id"]) in valid_ids
        )
    ]
    trade_pf = profit_factor(realized_pnls)
    doubled_trade_pf = profit_factor(doubled_realized_pnls)
    primary_sell_trades = [
        row
        for row in trades
        if (
            row["side"] == "SELL"
            and row["cost_scenario"] == "primary"
            and str(row["fold_id"]) in valid_ids
        )
    ]
    target_gains = sum(
        max(0, int(row["realized_pnl_vnd"]))
        for row in primary_sell_trades
        if row["reason"] == "grid_target"
    )
    forced_exit_losses = -sum(
        min(0, int(row["realized_pnl_vnd"]))
        for row in primary_sell_trades
        if row["reason"] != "grid_target"
    )
    forced_loss_to_target_gain = (
        forced_exit_losses / target_gains
        if target_gains > 0
        else (0.0 if forced_exit_losses == 0 else "infinity")
    )
    modeled_cost = sum(
        int(row.get("commission_vnd", 0))
        + int(row.get("sell_tax_vnd", 0))
        + int(row.get("execution_friction_vnd", 0))
        for row in primary_trades
    )
    gross_turnover = sum(
        int(row.get("gross_notional_vnd", 0)) for row in primary_trades
    )
    pending_entry_cost: dict[tuple[str, str], int] = defaultdict(int)
    positive_gross_profit = 0
    for row in sorted(
        primary_trades,
        key=lambda value: (
            str(value["fold_id"]),
            str(value.get("tickersymbol", "")),
            str(value.get("event_time", "")),
        ),
    ):
        key = (str(row["fold_id"]), str(row.get("tickersymbol", "")))
        row_cost = (
            int(row.get("commission_vnd", 0))
            + int(row.get("sell_tax_vnd", 0))
            + int(row.get("execution_friction_vnd", 0))
        )
        if row["side"] == "BUY":
            pending_entry_cost[key] += row_cost
        elif row["side"] == "SELL":
            campaign_cost = pending_entry_cost.pop(key, 0) + row_cost
            gross_campaign_pnl = (
                int(row["realized_pnl_vnd"]) + campaign_cost
            )
            positive_gross_profit += max(0, gross_campaign_pnl)
    modeled_cost_to_gross_profit: float | str = (
        modeled_cost / positive_gross_profit
        if positive_gross_profit > 0
        else (0.0 if modeled_cost == 0 else "infinity")
    )
    maximum_fold_cost_fraction = max(
        (float(row.get("modeled_cost_fraction", 0.0)) for row in valid),
        default=0.0,
    )
    maximum_fold_turnover_fraction = max(
        (float(row.get("turnover_fraction", 0.0)) for row in valid),
        default=0.0,
    )
    downtrend_rotation_returns = [
        float(row["net_return"])
        for row in valid
        if row.get("market_regime") == "downtrend"
    ]

    stitched: list[float] = [1.0]
    capital = 1.0
    daily_by_fold: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in portfolio_daily:
        daily_by_fold[str(row["fold_id"])].append(row)
    for fold_row in valid:
        fold_id = str(fold_row["fold_id"])
        for row in sorted(
            daily_by_fold[fold_id], key=lambda value: str(value["trading_date"])
        ):
            stitched.append(
                capital
                * (
                    1.0
                    + float(row["fold_return_to_date"])
                )
            )
        capital *= 1.0 + float(fold_row["net_return"])
    path_drawdown = maximum_drawdown(stitched)
    aggregate_pf = trade_pf
    stats = {
        "folds_total": len(folds),
        "folds_valid": len(valid),
        "folds_active": len(active),
        "profitable_fold_fraction": profitable_fraction,
        "mean_fold_return": statistics.mean(returns) if returns else None,
        "median_fold_return": statistics.median(returns) if returns else None,
        "worst_fold_return": min(returns) if returns else None,
        "compounded_return": compounded_return(returns),
        "annualized_fold_sharpe": annualized_sharpe(returns),
        "maximum_drawdown": path_drawdown,
        "trade_profit_factor": aggregate_pf,
        "completed_grid_cycles": completed_campaigns,
        "doubled_cost_compounded_return": compounded_return(doubled),
        "doubled_cost_valid_folds": len(doubled_valid),
        "doubled_cost_trade_profit_factor": doubled_trade_pf,
        "target_exit_gains_vnd": target_gains,
        "forced_exit_losses_vnd": forced_exit_losses,
        "forced_loss_to_target_gain": forced_loss_to_target_gain,
        "gross_turnover_vnd": gross_turnover,
        "maximum_fold_turnover_fraction": maximum_fold_turnover_fraction,
        "modeled_cost_vnd": modeled_cost,
        "maximum_fold_modeled_cost_fraction": maximum_fold_cost_fraction,
        "positive_gross_trading_profit_vnd": positive_gross_profit,
        "modeled_cost_to_gross_profit": modeled_cost_to_gross_profit,
        "average_capital_utilization": (
            statistics.mean(
                float(row.get("average_capital_utilization", 0.0))
                for row in valid
            )
            if valid
            else None
        ),
        "maximum_capital_utilization": max(
            (
                float(row.get("maximum_capital_utilization", 0.0))
                for row in valid
            ),
            default=0.0,
        ),
        "settlement_locked_exit_loss_vnd": sum(
            int(row.get("settlement_locked_exit_loss_vnd", 0))
            for row in valid
        ),
        "market_downtrend_rotations": len(downtrend_rotation_returns),
        "market_downtrend_compounded_return": compounded_return(
            downtrend_rotation_returns
        ),
        "market_downtrend_worst_return": (
            min(downtrend_rotation_returns)
            if downtrend_rotation_returns
            else None
        ),
        "benchmark_compounded_return": compounded_return(benchmarks),
        "valid_fold_ids": sorted(valid_ids),
    }
    sample_gates = {
        "minimum_valid_folds": {
            "observed": len(valid),
            "required": config.minimum_valid_folds,
            "passed": len(valid) >= config.minimum_valid_folds,
        },
        "minimum_active_folds": {
            "observed": len(active),
            "required": config.minimum_active_folds,
            "passed": len(active) >= config.minimum_active_folds,
        },
        "minimum_completed_campaigns": {
            "observed": completed_campaigns,
            "required": config.minimum_completed_campaigns,
            "passed": completed_campaigns
            >= config.minimum_completed_campaigns,
        },
    }
    economic_gates = {
        "compounded_return_positive": {
            "observed": stats["compounded_return"],
            "required": config.minimum_compounded_return,
            "passed": stats["compounded_return"] is not None
            and float(stats["compounded_return"])
            > config.minimum_compounded_return,
        },
        "median_fold_return_positive": {
            "observed": stats["median_fold_return"],
            "required": config.minimum_median_fold_return,
            "passed": stats["median_fold_return"] is not None
            and float(stats["median_fold_return"])
            > config.minimum_median_fold_return,
        },
        "annualized_fold_sharpe": {
            "observed": stats["annualized_fold_sharpe"],
            "required": config.minimum_annualized_fold_sharpe,
            "passed": stats["annualized_fold_sharpe"] is not None
            and float(stats["annualized_fold_sharpe"])
            >= config.minimum_annualized_fold_sharpe,
        },
        "profitable_fold_fraction": {
            "observed": profitable_fraction,
            "required": config.minimum_profitable_fold_fraction,
            "passed": profitable_fraction is not None
            and profitable_fraction >= config.minimum_profitable_fold_fraction,
        },
        "trade_profit_factor": {
            "observed": aggregate_pf,
            "required": config.minimum_trade_profit_factor,
            "passed": numeric_profit_factor_at_least(
                aggregate_pf, config.minimum_trade_profit_factor
            ),
        },
        "maximum_drawdown": {
            "observed": path_drawdown,
            "required": config.minimum_maximum_drawdown,
            "passed": path_drawdown is not None
            and path_drawdown >= config.minimum_maximum_drawdown,
        },
        "worst_fold_return": {
            "observed": stats["worst_fold_return"],
            "required": config.minimum_worst_fold_return,
            "passed": stats["worst_fold_return"] is not None
            and float(stats["worst_fold_return"])
            >= config.minimum_worst_fold_return,
        },
        "doubled_cost_compounded_return_positive": {
            "observed": stats["doubled_cost_compounded_return"],
            "required": config.minimum_doubled_cost_compounded_return,
            "passed": stats["doubled_cost_compounded_return"] is not None
            and float(stats["doubled_cost_compounded_return"])
            > config.minimum_doubled_cost_compounded_return,
        },
        "doubled_cost_all_folds_valid": {
            "observed": len(doubled_valid),
            "required": len(valid),
            "passed": len(doubled_valid) == len(valid),
        },
        "doubled_cost_trade_profit_factor": {
            "observed": doubled_trade_pf,
            "required": config.minimum_doubled_cost_profit_factor,
            "passed": numeric_profit_factor_at_least(
                doubled_trade_pf,
                config.minimum_doubled_cost_profit_factor,
            ),
        },
        "forced_exit_loss_control": {
            "observed": forced_loss_to_target_gain,
            "required_maximum": config.maximum_forced_loss_to_target_gain,
            "passed": forced_loss_to_target_gain != "infinity"
            and float(forced_loss_to_target_gain)
            <= config.maximum_forced_loss_to_target_gain,
        },
        "modeled_cost_per_rotation": {
            "observed": maximum_fold_cost_fraction,
            "required_maximum": (
                config.maximum_modeled_cost_fraction_per_rotation
            ),
            "passed": maximum_fold_cost_fraction
            <= config.maximum_modeled_cost_fraction_per_rotation,
        },
        "modeled_cost_to_gross_profit": {
            "observed": modeled_cost_to_gross_profit,
            "required_maximum": config.maximum_modeled_cost_to_gross_profit,
            "passed": modeled_cost_to_gross_profit != "infinity"
            and float(modeled_cost_to_gross_profit)
            <= config.maximum_modeled_cost_to_gross_profit,
        },
    }
    if not all(gate["passed"] for gate in sample_gates.values()):
        status = "inconclusive_sample"
    elif not all(gate["passed"] for gate in economic_gates.values()):
        status = "rejected_development"
    else:
        status = "passed_development_screen"
    return {
        "schema_version": SCHEMA_VERSION,
        "trial_id": TRIAL_ID,
        "scope": "development_walk_forward_only",
        "status": status,
        "advance_to_final_confirmation": status
        == "passed_development_screen",
        "final_test_used": False,
        "independent_unit": "two_month_portfolio_rotation",
        "statistics": stats,
        "sample_gates": sample_gates,
        "economic_gates": economic_gates,
        "interpretation": (
            "Ticker rows and individual trades are correlated diagnostics; "
            "the 15 chronological portfolio rotations are the research sample."
        ),
    }


def apply_data_quality_gate(
    gate_report: dict[str, object],
    skipped_minute_rows: int,
    quarantined_folds: int,
    config: Config,
) -> None:
    gate_report["data_quality"] = {
        "minute_rows_skipped_for_missing_matched_ohlc": skipped_minute_rows,
        "maximum_allowed_skipped_minute_rows": (
            config.maximum_skipped_minute_rows
        ),
        "quarantined_folds": quarantined_folds,
    }
    if skipped_minute_rows > config.maximum_skipped_minute_rows:
        gate_report["status"] = "invalid_run"
        gate_report["advance_to_final_confirmation"] = False
        gate_report["data_quality"]["failure"] = (  # type: ignore[index]
            "skipped minute OHLC rows exceeded frozen maximum"
        )


def serialize(value: object) -> object:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, float):
        if math.isnan(value):
            return ""
        if math.isinf(value):
            return "infinity" if value > 0 else "-infinity"
        return format(value, ".12g")
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def write_csv(
    path: Path, rows: Sequence[dict[str, object]], fields: Sequence[str]
) -> None:
    allowed = set(fields)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields))
        writer.writeheader()
        for row in rows:
            extras = set(row).difference(allowed)
            missing = allowed.difference(row)
            if extras or missing:
                raise ValueError(
                    f"{path.name} schema mismatch extras={extras} missing={missing}"
                )
            writer.writerow({key: serialize(row[key]) for key in fields})


def output_schemas() -> dict[str, tuple[str, ...]]:
    return {
        "selection_audit.csv": SELECTION_FIELDS,
        "grid_parameters.csv": GRID_FIELDS,
        "trades.csv": TRADE_FIELDS,
        "account_daily.csv": ACCOUNT_DAILY_FIELDS,
        "portfolio_daily.csv": PORTFOLIO_DAILY_FIELDS,
        "fold_summary.csv": FOLD_FIELDS,
        "quarantined_folds.csv": QUARANTINE_FIELDS,
    }


def publish_lock(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    try:
        os.link(temporary, path)
    except FileExistsError as exc:
        raise RuntimeError(f"Decision lock already exists: {path}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def validate_published(
    directory: Path,
    fingerprint: str,
    expected_hashes: dict[str, str] | None = None,
    expected_manifest_hash: str | None = None,
) -> dict[str, object]:
    manifest_path = directory / "manifest.json"
    if not manifest_path.exists():
        raise RuntimeError(f"Missing manifest in {directory}")
    if (
        expected_manifest_hash is not None
        and sha256_file(manifest_path) != expected_manifest_hash
    ):
        raise RuntimeError("Published manifest hash differs from decision lock")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("result_fingerprint_sha256") != fingerprint:
        raise RuntimeError("Published result fingerprint differs")
    if (
        manifest.get("schema_version") != SCHEMA_VERSION
        or manifest.get("trial_id") != TRIAL_ID
    ):
        raise RuntimeError("Published manifest schema/trial differs")
    expected_artifacts = set(output_schemas()).union(
        {"gate_report.json"}
    )
    actual_files = {
        path.name for path in directory.iterdir() if path.is_file()
    }
    if actual_files != expected_artifacts.union({"manifest.json"}):
        raise RuntimeError("Published run has missing or unexpected artifacts")
    if set(dict(manifest.get("output_hashes", {}))) != expected_artifacts:
        raise RuntimeError("Manifest does not hash the exact artifact schema")
    hashes = expected_hashes or dict(manifest["output_hashes"])
    if (
        expected_hashes is not None
        and dict(manifest.get("output_hashes", {})) != expected_hashes
    ):
        raise RuntimeError("Manifest output hashes differ from decision lock")
    for filename, digest in hashes.items():
        path = directory / filename
        if not path.exists() or sha256_file(path) != digest:
            raise RuntimeError(f"Published artifact hash mismatch: {path}")
    return manifest


def validate_prerun_seal(
    path: Path,
    identity_hashes: dict[str, str],
) -> dict[str, object]:
    if not path.exists():
        raise FileNotFoundError(
            "Trial 5 pre-run seal is missing; do not calculate outcomes"
        )
    seal = json.loads(path.read_text(encoding="utf-8"))
    if seal.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Pre-run seal schema differs")
    if seal.get("trial_id") != TRIAL_ID:
        raise ValueError("Pre-run seal trial differs")
    if tuple(seal.get("fold_ids", ())) != CANONICAL_FOLD_IDS:
        raise ValueError("Pre-run seal fold list differs")
    sealed_hashes = {
        str(key): str(value)
        for key, value in dict(seal.get("identity_hashes", {})).items()
    }
    if sealed_hashes != identity_hashes:
        changed = sorted(
            key
            for key in set(sealed_hashes).union(identity_hashes)
            if sealed_hashes.get(key) != identity_hashes.get(key)
        )
        raise ValueError(
            f"Pre-run identity differs in: {', '.join(changed)}"
        )
    return seal


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run sealed Trial 5 development walk-forward rotation."
    )
    parser.add_argument(
        "--daily-data",
        type=Path,
        default=Path("data_algotradeDB_split.csv"),
    )
    parser.add_argument(
        "--assignments",
        type=Path,
        default=Path(
            "data/trial5_splits_rotation/walk_forward_date_assignments.csv"
        ),
    )
    parser.add_argument(
        "--split-audit",
        type=Path,
        default=Path("data/trial5_splits_rotation/split_audit.json"),
    )
    parser.add_argument(
        "--minute-dir", type=Path, default=Path("data/minute_bars")
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/trial5_rotation_grid"),
    )
    parser.add_argument(
        "--pre-run-seal",
        type=Path,
        default=Path("research_log/TRIAL5_V1_PRERUN_SEAL.json"),
    )
    parser.add_argument(
        "--development-walk-forward",
        action="store_true",
        help="Required; no final-test execution mode exists.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not args.development_walk_forward:
        raise SystemExit("Pass --development-walk-forward explicitly")
    config = Config()
    config.validate()

    split_audit = validate_split_audit(args.split_audit, config)
    daily, calendar, final_range = read_daily_development(
        args.daily_data, config.universe
    )
    folds = read_folds(args.assignments)
    validate_fold_calendars(folds, calendar)
    if any(value >= final_range[0] for fold in folds for value in fold.oos_dates):
        raise SystemExit("Fold assignment reaches the locked final_test period")
    if date.fromisoformat(
        str(dict(split_audit["final_holdout"])["start"])
    ) != final_range[0] or final_range[0] != EXPECTED_FINAL_START:
        raise SystemExit("Daily file and split audit disagree on holdout start")

    minute_paths = minute_input_paths(args.minute_dir, folds)
    validate_minute_manifests(minute_paths, config.universe)
    minute_hash = composite_file_hash(minute_paths)
    script_path = Path(__file__).resolve()
    prereg_path = (
        script_path.parent
        / "research_log"
        / "TRIAL5_ROTATION_GRID_PREREGISTRATION.md"
    )
    if not prereg_path.exists():
        raise SystemExit("Trial 5 preregistration is missing")
    identity_hashes = {
        "script": sha256_file(script_path),
        "preregistration": sha256_file(prereg_path),
        "development_daily_rows": development_daily_hash(
            daily, config.universe
        ),
        "assignments": sha256_file(args.assignments),
        "split_audit": sha256_file(args.split_audit),
        "minute_files_composite": minute_hash,
        "config": sha256_bytes(canonical_json(asdict(config))),
    }
    validate_prerun_seal(args.pre_run_seal, identity_hashes)

    all_selection: list[dict[str, object]] = []
    all_fold_rows: list[dict[str, object]] = []
    all_trades: list[dict[str, object]] = []
    all_grid_rows: list[dict[str, object]] = []
    all_account_daily: list[dict[str, object]] = []
    all_portfolio_daily: list[dict[str, object]] = []
    quarantines: list[dict[str, object]] = []
    skipped_minute_rows = 0
    current_capital_vnd = config.initial_capital_vnd
    portfolio_high_water_vnd = config.initial_capital_vnd
    portfolio_kill_active = False

    for fold in folds:
        selection_rows, selected = fit_fold_selector(
            fold,
            daily,
            config,
            current_capital_vnd,
        )
        all_selection.extend(selection_rows)
        minutes, skipped = load_fold_minutes(
            args.minute_dir, fold, selected
        )
        skipped_minute_rows += skipped
        fold_row, trades, grids, account_daily, mixed = simulate_fold(
            fold,
            selection_rows,
            selected,
            daily,
            minutes,
            config,
            current_capital_vnd,
            portfolio_high_water_vnd,
            portfolio_kill_active,
        )
        all_fold_rows.append(fold_row)
        all_trades.extend(trades)
        all_grid_rows.extend(grids)
        all_account_daily.extend(account_daily)
        for row in mixed:
            if "portfolio_equity_vnd" in row:
                all_portfolio_daily.append(row)
            else:
                quarantines.append(row)
        if bool(fold_row["valid"]):
            current_capital_vnd = int(fold_row["ending_capital_vnd"])
            portfolio_high_water_vnd = int(
                fold_row["portfolio_high_water_end_vnd"]
            )
            portfolio_kill_active = (
                portfolio_kill_active
                or bool(fold_row["portfolio_kill_triggered"])
            )

    gate_report = evaluate_gates(
        all_fold_rows, all_trades, all_portfolio_daily, config
    )
    apply_data_quality_gate(
        gate_report,
        skipped_minute_rows,
        sum(not bool(row["valid"]) for row in all_fold_rows),
        config,
    )

    result_payload = {
        "selection": all_selection,
        "grid": all_grid_rows,
        "trades": all_trades,
        "account_daily": all_account_daily,
        "portfolio_daily": all_portfolio_daily,
        "folds": all_fold_rows,
        "quarantines": quarantines,
        "gate_report": gate_report,
    }
    fingerprint = sha256_bytes(
        canonical_json(
            {
                "schema_version": SCHEMA_VERSION,
                "trial_id": TRIAL_ID,
                "identity_hashes": identity_hashes,
                "results": result_payload,
            }
        )
    )
    run_id = "trial5_" + sha256_bytes(
        canonical_json(
            {
                "schema_version": SCHEMA_VERSION,
                "trial_id": TRIAL_ID,
                "identity_hashes": identity_hashes,
                "fold_ids": CANONICAL_FOLD_IDS,
            }
        )
    )[:10]
    output_directory = args.output_dir / run_id
    lock_path = (
        script_path.parent
        / "research_log"
        / "TRIAL5_V1_DECISION_LOCK.json"
    )

    if lock_path.exists():
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        if (
            lock.get("run_id") != run_id
            or lock.get("result_fingerprint_sha256") != fingerprint
        ):
            raise SystemExit("Trial 5 v1 already has a different decision lock")
        locked_output_directory = Path(str(lock["output_dir"]))
        if not locked_output_directory.is_absolute():
            locked_output_directory = (
                script_path.parent / locked_output_directory
            )
        validate_published(
            locked_output_directory,
            fingerprint,
            {str(k): str(v) for k, v in dict(lock["output_hashes"]).items()},
            str(lock["manifest_sha256"]),
        )
        print(
            f"{TRIAL_ID}: {gate_report['status']}; "
            f"valid_folds={gate_report['statistics']['folds_valid']}; "
            f"output={locked_output_directory}"
        )
        return 0

    schemas = output_schemas()
    rows_by_file = {
        "selection_audit.csv": all_selection,
        "grid_parameters.csv": all_grid_rows,
        "trades.csv": all_trades,
        "account_daily.csv": all_account_daily,
        "portfolio_daily.csv": all_portfolio_daily,
        "fold_summary.csv": all_fold_rows,
        "quarantined_folds.csv": quarantines,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if output_directory.exists():
        raise SystemExit(
            "Refusing to trust an unlocked pre-existing Trial 5 output "
            f"directory: {output_directory}"
        )

    staging = Path(
        tempfile.mkdtemp(dir=args.output_dir, prefix=f".{run_id}.")
    )
    try:
        for filename, rows in rows_by_file.items():
            write_csv(staging / filename, rows, schemas[filename])
        (staging / "gate_report.json").write_text(
            json.dumps(gate_report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        output_hashes = {
            path.name: sha256_file(path)
            for path in sorted(staging.iterdir())
            if path.name != "manifest.json"
        }
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "trial_id": TRIAL_ID,
            "run_id": run_id,
            "scope": "development_walk_forward_only",
            "final_test_used": False,
            "fold_ids": list(CANONICAL_FOLD_IDS),
            "config": asdict(config),
            "identity_hashes": identity_hashes,
            "result_fingerprint_sha256": fingerprint,
            "output_hashes": output_hashes,
            "input_minute_files": [
                {
                    "name": path.name,
                    "data_sha256": sha256_file(path),
                    "manifest_sha256": sha256_file(
                        path.with_suffix("").with_suffix(".json")
                    ),
                }
                for path in minute_paths
            ],
        }
        (staging / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.rename(staging, output_directory)
    except Exception:
        for path in staging.iterdir():
            path.unlink(missing_ok=True)
        staging.rmdir()
        raise

    resolved_output_directory = output_directory.resolve()
    try:
        locked_output_reference = str(
            resolved_output_directory.relative_to(script_path.parent.resolve())
        )
    except ValueError:
        locked_output_reference = str(resolved_output_directory)
    publish_lock(
        lock_path,
        {
            "schema_version": SCHEMA_VERSION,
            "trial_id": TRIAL_ID,
            "run_id": run_id,
            "result_fingerprint_sha256": fingerprint,
            "output_dir": locked_output_reference,
            "identity_hashes": identity_hashes,
            "output_hashes": output_hashes,
            "manifest_sha256": sha256_file(
                output_directory / "manifest.json"
            ),
            "status": gate_report["status"],
        },
    )
    print(
        f"{TRIAL_ID}: {gate_report['status']}; "
        f"valid_folds={gate_report['statistics']['folds_valid']}; "
        f"active_folds={gate_report['statistics']['folds_active']}; "
        f"compounded_return={gate_report['statistics']['compounded_return']}; "
        f"output={output_directory}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
