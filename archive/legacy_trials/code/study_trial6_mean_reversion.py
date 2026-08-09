#!/usr/bin/env python3
"""Trial 6 pooled, causal mean-reversion edge study.

This is a daily Stage-A study. It fits one regularized logistic model inside
each rolling training fold, predicts untouched two-month deployment
candidates, and selects non-overlapping positive-estimated-EV campaigns.
It cannot execute or numerically parse the locked final-test period.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import tempfile
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Sequence


TRIAL_ID = "TRIAL6-HSX-POOLED-MEAN-REVERSION-EDGE"
SCHEMA_VERSION = "trial6.v1"
TICKERS = ("FPT", "HPG", "MBB", "MWG", "PNJ", "SSI", "TCB", "VCB", "VND", "VPB")
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
FEATURE_NAMES = (
    "residual_z5",
    "residual_1",
    "residual_5",
    "residual_slope20",
    "downside_semivol20",
    "residual_ar1_20",
    "ticker_return5",
    "market_return5",
    "atr20_fraction",
    "log_median_value60",
)
PRICE_MULTIPLIER = 1_000
EXPECTED_FINAL_START = date(2025, 7, 14)
EXPECTED_FINAL_END = date(2026, 7, 16)
FROZEN_CONFIG_SHA256 = (
    "74f3f16d30c150ebc02dcb776c88de42e5a102f32a3f44e465c97b2ede0fc8e7"
)

DAILY_REQUIRED = {
    "datetime", "tickersymbol", "open", "high", "low", "close", "ceiling",
    "floor", "matched_quantity", "exchangeid", "instrumenttype", "primary_split",
}
ASSIGNMENT_REQUIRED = {"fold_id", "trading_date", "role"}

CANDIDATE_FIELDS = (
    "trial_id", "fold_id", "sample_role", "ticker", "sector", "signal_date",
    "entry_date", "exit_date", "exit_reason", "exit_session_offset",
    "entry_price_vnd", "exit_price_vnd", "target_vnd", "downside_vnd",
    "grid_distance_fraction", "gap_down_exit", "target_first", "net_pnl_vnd",
    "net_return", "double_cost_net_pnl_vnd", "double_cost_net_return",
    *FEATURE_NAMES, "predicted_probability", "base_probability",
    "estimated_ev_vnd", "selected", "selection_rank",
)
QUARANTINE_FIELDS = (
    "trial_id", "fold_id", "sample_role", "ticker", "signal_date",
    "entry_date", "reason", "reset_dates",
)
FOLD_FIELDS = (
    "trial_id", "fold_id", "valid", "invalid_reason", "train_candidates",
    "train_targets", "oos_candidates", "selected_campaigns", "selected_targets",
    "selected_net_pnl_vnd", "selected_double_cost_net_pnl_vnd",
    "brier_score", "base_brier_score", "mean_train_win_pnl_vnd",
    "mean_train_nonwin_pnl_vnd", "model_iterations", "model_converged",
)


@dataclass(frozen=True)
class Config:
    universe: tuple[str, ...] = TICKERS
    beta_sessions: int = 60
    residual_sessions: int = 20
    candidate_residual_z_max: float = -0.75
    liquidity_sessions: int = 60
    minimum_median_daily_value_vnd: int = 10_000_000_000
    atr_sessions: int = 20
    maximum_atr_fraction: float = 0.05
    minimum_barrier_fraction: float = 0.015
    maximum_barrier_fraction: float = 0.030
    maximum_horizon: int = 10
    quantity: int = 100
    commission_rate: float = 0.0015
    sell_tax_rate: float = 0.0010
    execution_haircut: float = 0.0005
    doubled_cost_multiplier: float = 2.0
    l2_penalty: float = 1.0
    learning_rate: float = 0.05
    maximum_model_iterations: int = 4000
    convergence_tolerance: float = 1e-8
    minimum_train_candidates: int = 30
    minimum_train_class_count: int = 5
    maximum_concurrent_campaigns: int = 3
    cooldown_sessions: int = 5
    minimum_valid_folds: int = 15
    minimum_oos_candidates: int = 100
    minimum_selected_campaigns: int = 60
    minimum_selected_targets: int = 30
    minimum_years: int = 3
    minimum_campaigns_per_year: int = 10
    maximum_year_fraction: float = 0.45
    minimum_profit_factor: float = 1.20
    minimum_positive_active_fold_fraction: float = 0.60

    def validate(self) -> None:
        if self.universe != TICKERS:
            raise ValueError("Trial 6 universe is frozen")
        if self.maximum_horizon != 10 or self.quantity != 100:
            raise ValueError("Trial 6 horizon and research lot are frozen")
        if self.maximum_concurrent_campaigns != 3:
            raise ValueError("Trial 6 permits at most three campaigns")
        digest = sha256_bytes(canonical_json(asdict(self)))
        if FROZEN_CONFIG_SHA256 != "TO_BE_FROZEN" and digest != FROZEN_CONFIG_SHA256:
            raise ValueError("Trial 6 configuration differs from frozen v1")


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
    reset_verifiable: bool
    reference_reset: bool


@dataclass(frozen=True)
class Fold:
    fold_id: str
    train_dates: tuple[date, ...]
    oos_dates: tuple[date, ...]


@dataclass(frozen=True)
class LogisticModel:
    means: tuple[float, ...]
    scales: tuple[float, ...]
    weights: tuple[float, ...]
    iterations: int
    converged: bool

    def probability(self, features: Sequence[float]) -> float:
        standardized = [
            (value - mean) / scale
            for value, mean, scale in zip(features, self.means, self.scales)
        ]
        linear = self.weights[0] + sum(
            weight * value
            for weight, value in zip(self.weights[1:], standardized)
        )
        return sigmoid(linear)


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def quote_to_vnd(value: str | float) -> int:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"Invalid price: {value!r}")
    return int(round(number * PRICE_MULTIPLIER))


def optional_quote_to_vnd(value: str) -> int | None:
    return quote_to_vnd(value) if value.strip() else None


def inferred_reference_reset(
    previous_close: int | None, ceiling: int | None, floor: int | None
) -> tuple[bool, bool]:
    if previous_close is None:
        return True, False
    if ceiling is None or floor is None:
        return False, False
    reference = (ceiling + floor) / 2
    tolerance = max(100, previous_close * 0.002)
    return True, abs(reference - previous_close) > tolerance


def read_development_daily(
    path: Path, universe: Sequence[str] = TICKERS
) -> tuple[dict[str, list[DailyBar]], list[date], tuple[date, date]]:
    allowed = set(universe)
    raw: dict[str, list[dict[str, str]]] = defaultdict(list)
    final_dates: set[date] = set()
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = DAILY_REQUIRED.difference(reader.fieldnames or ())
        if missing:
            raise ValueError(f"Daily input missing columns: {sorted(missing)}")
        for row in reader:
            ticker = row["tickersymbol"].strip().upper()
            if ticker not in allowed:
                continue
            trading_date = date.fromisoformat(row["datetime"][:10])
            split = row["primary_split"].strip()
            if split == "final_test":
                final_dates.add(trading_date)
                continue
            if split != "development":
                raise ValueError(f"Unexpected primary_split {split!r}")
            if row["exchangeid"].strip().upper() != "HSX":
                raise ValueError(f"Non-HSX row: {ticker} {trading_date}")
            if row["instrumenttype"].strip().lower() != "stock":
                raise ValueError(f"Non-stock row: {ticker} {trading_date}")
            raw[ticker].append(row)
    if set(raw) != allowed:
        raise ValueError(f"Missing tickers: {sorted(allowed.difference(raw))}")
    result: dict[str, list[DailyBar]] = {}
    calendars: list[list[date]] = []
    for ticker in universe:
        rows = sorted(raw[ticker], key=lambda row: row["datetime"])
        bars: list[DailyBar] = []
        previous_close: int | None = None
        seen: set[date] = set()
        for row in rows:
            trading_date = date.fromisoformat(row["datetime"][:10])
            if trading_date in seen:
                raise ValueError(f"Duplicate daily key: {ticker} {trading_date}")
            seen.add(trading_date)
            open_vnd = quote_to_vnd(row["open"])
            high_vnd = quote_to_vnd(row["high"])
            low_vnd = quote_to_vnd(row["low"])
            close_vnd = quote_to_vnd(row["close"])
            if not low_vnd <= min(open_vnd, close_vnd) <= max(open_vnd, close_vnd) <= high_vnd:
                raise ValueError(f"Invalid OHLC: {ticker} {trading_date}")
            ceiling = optional_quote_to_vnd(row["ceiling"])
            floor = optional_quote_to_vnd(row["floor"])
            verifiable, reset = inferred_reference_reset(previous_close, ceiling, floor)
            bars.append(DailyBar(
                trading_date, ticker, open_vnd, high_vnd, low_vnd, close_vnd,
                ceiling, floor, int(float(row["matched_quantity"])), verifiable, reset,
            ))
            previous_close = close_vnd
        result[ticker] = bars
        calendars.append([bar.trading_date for bar in bars])
    if any(calendar != calendars[0] for calendar in calendars[1:]):
        raise ValueError("Ticker development calendars differ")
    if not final_dates:
        raise ValueError("Locked final-test rows were not detected")
    final_range = (min(final_dates), max(final_dates))
    if final_range != (EXPECTED_FINAL_START, EXPECTED_FINAL_END):
        raise ValueError(f"Unexpected final-test range: {final_range}")
    return result, calendars[0], final_range


def read_folds(path: Path) -> list[Fold]:
    grouped: dict[str, dict[str, list[date]]] = defaultdict(
        lambda: {"in_sample": [], "out_of_sample": []}
    )
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = ASSIGNMENT_REQUIRED.difference(reader.fieldnames or ())
        if missing:
            raise ValueError(f"Assignments missing columns: {sorted(missing)}")
        for row in reader:
            role = row["role"].strip()
            if role == "walk_forward_oos":
                role = "out_of_sample"
            if role not in ("in_sample", "out_of_sample"):
                raise ValueError(f"Unexpected role: {role}")
            grouped[row["fold_id"].strip()][role].append(
                date.fromisoformat(row["trading_date"])
            )
    folds = [
        Fold(fold_id, tuple(sorted(parts["in_sample"])), tuple(sorted(parts["out_of_sample"])))
        for fold_id, parts in sorted(grouped.items())
    ]
    if len(folds) != 15:
        raise ValueError(f"Expected 15 folds, found {len(folds)}")
    for fold in folds:
        if not fold.train_dates or not fold.oos_dates:
            raise ValueError(f"Empty fold component: {fold.fold_id}")
        if fold.train_dates[-1] >= fold.oos_dates[0]:
            raise ValueError(f"Non-causal fold: {fold.fold_id}")
    all_oos = [value for fold in folds for value in fold.oos_dates]
    if len(all_oos) != len(set(all_oos)):
        raise ValueError("Deployment folds overlap")
    return folds


def simple_returns(values: Sequence[int]) -> list[float]:
    return [values[index] / values[index - 1] - 1 for index in range(1, len(values))]


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def variance(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    center = mean(values)
    return sum((value - center) ** 2 for value in values) / len(values)


def covariance(left: Sequence[float], right: Sequence[float]) -> float:
    left_mean, right_mean = mean(left), mean(right)
    return sum(
        (a - left_mean) * (b - right_mean) for a, b in zip(left, right)
    ) / len(left)


def ols_beta(ticker_returns: Sequence[float], market_returns: Sequence[float]) -> float:
    denominator = variance(market_returns)
    return covariance(ticker_returns, market_returns) / denominator if denominator > 1e-15 else 0.0


def atr(bars: Sequence[DailyBar]) -> float:
    true_ranges: list[int] = []
    for index, bar in enumerate(bars):
        previous_close = bars[index - 1].close_vnd if index else bar.open_vnd
        true_ranges.append(max(
            bar.high_vnd - bar.low_vnd,
            abs(bar.high_vnd - previous_close),
            abs(bar.low_vnd - previous_close),
        ))
    return mean([float(value) for value in true_ranges])


def ar1(values: Sequence[float]) -> float:
    left, right = values[:-1], values[1:]
    denominator = variance(left)
    return covariance(left, right) / denominator if denominator > 1e-15 else 0.0


def feature_vector(
    ticker: str,
    index: int,
    bars_by_ticker: dict[str, list[DailyBar]],
    config: Config,
) -> tuple[dict[str, float] | None, tuple[str, ...]]:
    reasons: list[str] = []
    if index < config.beta_sessions:
        return None, ("insufficient_history",)
    ticker_bars = bars_by_ticker[ticker]
    window = ticker_bars[index - config.beta_sessions:index + 1]
    if any(not bar.reset_verifiable for bar in window[1:]):
        reasons.append("unverified_reference_window")
    if any(bar.reference_reset for bar in window[1:]):
        reasons.append("reference_reset_window")
    ticker_closes = [bar.close_vnd for bar in window]
    ticker_returns = simple_returns(ticker_closes)
    others = [name for name in config.universe if name != ticker]
    market_closes_by_day = [
        [bars_by_ticker[name][j].close_vnd for name in others]
        for j in range(index - config.beta_sessions, index + 1)
    ]
    market_returns = [
        mean([
            market_closes_by_day[j][k] / market_closes_by_day[j - 1][k] - 1
            for k in range(len(others))
        ])
        for j in range(1, len(market_closes_by_day))
    ]
    beta = ols_beta(ticker_returns, market_returns)
    residuals = [
        ticker_return - beta * market_return
        for ticker_return, market_return in zip(ticker_returns, market_returns)
    ]
    recent = residuals[-config.residual_sessions:]
    residual_vol = math.sqrt(variance(recent))
    residual_5 = sum(recent[-5:])
    residual_z5 = (
        residual_5 / (residual_vol * math.sqrt(5))
        if residual_vol > 1e-12 else 0.0
    )
    downside = [min(value, 0.0) for value in recent]
    slope_x = [float(value) for value in range(len(recent))]
    slope_denominator = variance(slope_x)
    residual_slope = (
        covariance(slope_x, recent) / slope_denominator
        if slope_denominator > 0 else 0.0
    )
    liquidity_bars = ticker_bars[index - config.liquidity_sessions + 1:index + 1]
    values = [bar.close_vnd * bar.matched_quantity for bar in liquidity_bars]
    median_value = statistics.median(values)
    atr_bars = ticker_bars[index - config.atr_sessions:index + 1]
    atr_fraction = atr(atr_bars) / ticker_bars[index].close_vnd
    if median_value < config.minimum_median_daily_value_vnd:
        reasons.append("insufficient_liquidity")
    if not 0 < atr_fraction <= config.maximum_atr_fraction:
        reasons.append("invalid_atr")
    if residual_z5 > config.candidate_residual_z_max:
        reasons.append("residual_not_low_enough")
    features = {
        "residual_z5": residual_z5,
        "residual_1": recent[-1],
        "residual_5": residual_5,
        "residual_slope20": residual_slope,
        "downside_semivol20": math.sqrt(mean([value * value for value in downside])),
        "residual_ar1_20": ar1(recent),
        "ticker_return5": sum(ticker_returns[-5:]),
        "market_return5": sum(market_returns[-5:]),
        "atr20_fraction": atr_fraction,
        "log_median_value60": math.log(median_value),
    }
    if any(not math.isfinite(value) for value in features.values()):
        reasons.append("non_finite_feature")
    return features, tuple(reasons)


def acquisition_cash(entry_vnd: int, config: Config, multiplier: float = 1.0) -> int:
    execution = round(entry_vnd * (1 + config.execution_haircut * multiplier))
    notional = execution * config.quantity
    commission = round(notional * config.commission_rate * multiplier)
    return notional + commission


def net_sale_cash(exit_vnd: int, config: Config, multiplier: float = 1.0) -> int:
    execution = round(exit_vnd * (1 - config.execution_haircut * multiplier))
    notional = execution * config.quantity
    commission = round(notional * config.commission_rate * multiplier)
    tax = round(notional * config.sell_tax_rate * multiplier)
    return notional - commission - tax


def campaign_label(
    bars: Sequence[DailyBar],
    entry_index: int,
    atr_fraction: float,
    config: Config,
) -> tuple[dict[str, object] | None, tuple[date, ...]]:
    end_index = entry_index + config.maximum_horizon
    if end_index >= len(bars):
        return None, ()
    path = bars[entry_index:end_index + 1]
    reset_dates = tuple(
        bar.trading_date for bar in path
        if not bar.reset_verifiable or bar.reference_reset
    )
    if reset_dates:
        return None, reset_dates
    entry = path[0].open_vnd
    distance = min(
        max(atr_fraction, config.minimum_barrier_fraction),
        config.maximum_barrier_fraction,
    )
    target = round(entry * (1 + distance))
    downside = round(entry * (1 - distance))
    exit_bar = path[-1]
    exit_price = exit_bar.close_vnd
    reason = "time_exit"
    offset = config.maximum_horizon
    gap_down = False
    for current_offset, bar in enumerate(path):
        if bar.open_vnd <= downside:
            exit_bar, exit_price, reason, offset = bar, bar.open_vnd, "downside_gap", current_offset
            gap_down = True
            break
        if bar.low_vnd <= downside:
            exit_bar, exit_price, reason, offset = bar, downside, "downside_touch", current_offset
            break
        if bar.open_vnd >= target:
            exit_bar, exit_price, reason, offset = bar, target, "target", current_offset
            break
        if bar.high_vnd >= target:
            exit_bar, exit_price, reason, offset = bar, target, "target", current_offset
            break
    cost = acquisition_cash(entry, config)
    pnl = net_sale_cash(exit_price, config) - cost
    double_cost = acquisition_cash(entry, config, 2.0)
    double_pnl = net_sale_cash(exit_price, config, 2.0) - double_cost
    return {
        "entry_date": path[0].trading_date.isoformat(),
        "exit_date": exit_bar.trading_date.isoformat(),
        "exit_reason": reason,
        "exit_session_offset": offset,
        "entry_price_vnd": entry,
        "exit_price_vnd": exit_price,
        "target_vnd": target,
        "downside_vnd": downside,
        "grid_distance_fraction": distance,
        "gap_down_exit": gap_down,
        "target_first": reason == "target",
        "net_pnl_vnd": pnl,
        "net_return": pnl / cost,
        "double_cost_net_pnl_vnd": double_pnl,
        "double_cost_net_return": double_pnl / double_cost,
    }, ()


def generate_candidates(
    fold: Fold,
    sample_role: str,
    allowed_dates: Sequence[date],
    bars_by_ticker: dict[str, list[DailyBar]],
    calendar: Sequence[date],
    config: Config,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    date_to_index = {value: index for index, value in enumerate(calendar)}
    allowed = set(allowed_dates)
    if sample_role == "train":
        label_allowed = allowed.difference(allowed_dates[-config.maximum_horizon:])
    else:
        label_allowed = allowed
    candidates: list[dict[str, object]] = []
    quarantine: list[dict[str, object]] = []
    for signal_date in allowed_dates:
        signal_index = date_to_index[signal_date]
        entry_index = signal_index + 1
        if signal_date not in label_allowed or entry_index >= len(calendar):
            continue
        entry_date = calendar[entry_index]
        end_index = entry_index + config.maximum_horizon
        if (
            entry_date not in allowed
            or end_index >= len(calendar)
            or calendar[end_index] not in allowed
        ):
            continue
        for ticker in config.universe:
            features, reasons = feature_vector(ticker, signal_index, bars_by_ticker, config)
            if features is None or reasons:
                continue
            label, reset_dates = campaign_label(
                bars_by_ticker[ticker], entry_index,
                float(features["atr20_fraction"]), config,
            )
            if label is None:
                quarantine.append({
                    "trial_id": TRIAL_ID,
                    "fold_id": fold.fold_id,
                    "sample_role": sample_role,
                    "ticker": ticker,
                    "signal_date": signal_date.isoformat(),
                    "entry_date": entry_date.isoformat(),
                    "reason": "forward_reference_reset" if reset_dates else "incomplete_horizon",
                    "reset_dates": "|".join(value.isoformat() for value in reset_dates),
                })
                continue
            row: dict[str, object] = {
                "trial_id": TRIAL_ID,
                "fold_id": fold.fold_id,
                "sample_role": sample_role,
                "ticker": ticker,
                "sector": SECTOR_BY_TICKER[ticker],
                "signal_date": signal_date.isoformat(),
                **label,
                **features,
                "predicted_probability": "",
                "base_probability": "",
                "estimated_ev_vnd": "",
                "selected": False,
                "selection_rank": "",
            }
            candidates.append(row)
    return candidates, quarantine


def sigmoid(value: float) -> float:
    if value >= 0:
        inverse = math.exp(-value)
        return 1 / (1 + inverse)
    exponent = math.exp(value)
    return exponent / (1 + exponent)


def fit_logistic(
    features: Sequence[Sequence[float]],
    labels: Sequence[int],
    config: Config,
) -> LogisticModel:
    if not features or len(features) != len(labels):
        raise ValueError("Features and labels must be non-empty and aligned")
    width = len(features[0])
    if any(len(row) != width for row in features):
        raise ValueError("Ragged feature matrix")
    means = tuple(mean([row[column] for row in features]) for column in range(width))
    scales = tuple(
        max(math.sqrt(variance([row[column] for row in features])), 1e-12)
        for column in range(width)
    )
    matrix = [
        [1.0] + [
            (value - means[column]) / scales[column]
            for column, value in enumerate(row)
        ]
        for row in features
    ]
    weights = [0.0] * (width + 1)
    prior = min(max(mean([float(value) for value in labels]), 1e-6), 1 - 1e-6)
    weights[0] = math.log(prior / (1 - prior))
    converged = False
    iteration = 0
    for iteration in range(1, config.maximum_model_iterations + 1):
        gradients = [0.0] * len(weights)
        hessian = [[0.0] * len(weights) for _ in weights]
        for row, label in zip(matrix, labels):
            probability = sigmoid(sum(weight * value for weight, value in zip(weights, row)))
            error = probability - label
            for column, value in enumerate(row):
                gradients[column] += error * value
                for other_column, other_value in enumerate(row):
                    hessian[column][other_column] += (
                        probability * (1 - probability) * value * other_value
                    )
        for column in range(1, len(weights)):
            gradients[column] += config.l2_penalty * weights[column]
            hessian[column][column] += config.l2_penalty
        changes = solve_linear_system(hessian, gradients)
        maximum_change = max(abs(value) for value in changes)
        for column, change in enumerate(changes):
            weights[column] -= change
        if maximum_change < config.convergence_tolerance:
            converged = True
            break
    return LogisticModel(means, scales, tuple(weights), iteration, converged)


def solve_linear_system(
    matrix: Sequence[Sequence[float]], vector: Sequence[float]
) -> list[float]:
    """Solve Ax=b with deterministic partial-pivot Gaussian elimination."""
    size = len(vector)
    augmented = [list(row) + [float(value)] for row, value in zip(matrix, vector)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-14:
            raise ValueError("Singular logistic Hessian")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            if factor == 0:
                continue
            augmented[row] = [
                value - factor * pivot_value
                for value, pivot_value in zip(augmented[row], augmented[column])
            ]
    return [augmented[row][-1] for row in range(size)]


def feature_values(row: dict[str, object]) -> list[float]:
    return [float(row[name]) for name in FEATURE_NAMES]


def select_campaigns(
    candidates: list[dict[str, object]],
    calendar: Sequence[date],
    config: Config,
) -> list[dict[str, object]]:
    calendar_index = {value: index for index, value in enumerate(calendar)}
    by_entry: dict[date, list[dict[str, object]]] = defaultdict(list)
    for row in candidates:
        if float(row["estimated_ev_vnd"]) > 0:
            by_entry[date.fromisoformat(str(row["entry_date"]))].append(row)
    active: list[dict[str, object]] = []
    cooldown_until: dict[str, int] = {}
    selected: list[dict[str, object]] = []
    for entry_date in sorted(by_entry):
        current_index = calendar_index[entry_date]
        active = [
            row for row in active
            if date.fromisoformat(str(row["exit_date"])) >= entry_date
        ]
        active_tickers = {str(row["ticker"]) for row in active}
        active_sectors = {str(row["sector"]) for row in active}
        slots = config.maximum_concurrent_campaigns - len(active)
        ranked = sorted(
            by_entry[entry_date],
            key=lambda row: (
                -float(row["estimated_ev_vnd"]),
                -float(row["predicted_probability"]),
                str(row["ticker"]),
            ),
        )
        rank = 0
        for row in ranked:
            if slots <= 0:
                break
            ticker, sector = str(row["ticker"]), str(row["sector"])
            if ticker in active_tickers or sector in active_sectors:
                continue
            if current_index <= cooldown_until.get(ticker, -1):
                continue
            rank += 1
            row["selected"] = True
            row["selection_rank"] = rank
            selected.append(row)
            active.append(row)
            active_tickers.add(ticker)
            active_sectors.add(sector)
            exit_index = calendar_index[date.fromisoformat(str(row["exit_date"]))]
            cooldown_until[ticker] = exit_index + config.cooldown_sessions
            slots -= 1
    return selected


def profit_factor(pnls: Sequence[int]) -> float | str | None:
    gains = sum(value for value in pnls if value > 0)
    losses = -sum(value for value in pnls if value < 0)
    if losses == 0:
        return "Infinity" if gains > 0 else None
    return gains / losses


def brier(rows: Sequence[dict[str, object]], probability_field: str) -> float | None:
    if not rows:
        return None
    return mean([
        (float(row[probability_field]) - int(bool(row["target_first"]))) ** 2
        for row in rows
    ])


def numeric_pf_at_least(value: object, threshold: float) -> bool:
    return value == "Infinity" or (isinstance(value, (float, int)) and value >= threshold)


def quantile_target_rates(
    rows: Sequence[dict[str, object]]
) -> tuple[float | None, float | None]:
    if len(rows) < 5:
        return None, None
    ranked = sorted(rows, key=lambda row: float(row["predicted_probability"]))
    size = max(1, len(ranked) // 5)
    low, high = ranked[:size], ranked[-size:]
    return (
        mean([float(bool(row["target_first"])) for row in low]),
        mean([float(bool(row["target_first"])) for row in high]),
    )


def evaluate_gates(
    folds: Sequence[dict[str, object]],
    candidates: Sequence[dict[str, object]],
    selected: Sequence[dict[str, object]],
    config: Config,
) -> dict[str, object]:
    valid_folds = [row for row in folds if bool(row["valid"])]
    selected_pnls = [int(row["net_pnl_vnd"]) for row in selected]
    doubled_pnls = [int(row["double_cost_net_pnl_vnd"]) for row in selected]
    target_gains = sum(
        int(row["net_pnl_vnd"]) for row in selected
        if bool(row["target_first"]) and int(row["net_pnl_vnd"]) > 0
    )
    non_target_losses = -sum(
        int(row["net_pnl_vnd"]) for row in selected
        if not bool(row["target_first"]) and int(row["net_pnl_vnd"]) < 0
    )
    years = Counter(str(row["entry_date"])[:4] for row in selected)
    active_folds: dict[str, int] = defaultdict(int)
    for row in selected:
        active_folds[str(row["fold_id"])] += int(row["net_pnl_vnd"])
    low_rate, high_rate = quantile_target_rates(candidates)
    pooled_brier = brier(candidates, "predicted_probability")
    base_brier = brier(candidates, "base_probability")
    sample_gates = {
        "valid_folds": len(valid_folds) >= config.minimum_valid_folds,
        "oos_candidates": len(candidates) >= config.minimum_oos_candidates,
        "selected_campaigns": len(selected) >= config.minimum_selected_campaigns,
        "selected_targets": sum(bool(row["target_first"]) for row in selected)
        >= config.minimum_selected_targets,
        "year_distribution": (
            sum(count >= config.minimum_campaigns_per_year for count in years.values())
            >= config.minimum_years
        ),
        "year_concentration": (
            bool(selected) and max(years.values(), default=0) / len(selected)
            <= config.maximum_year_fraction
        ),
    }
    best_removed = (
        sum(selected_pnls) - max(selected_pnls) if selected_pnls else 0
    )
    economic_gates = {
        "brier_improvement": (
            pooled_brier is not None and base_brier is not None
            and pooled_brier < base_brier
        ),
        "probability_ranking": (
            low_rate is not None and high_rate is not None and high_rate > low_rate
        ),
        "positive_total_pnl": sum(selected_pnls) > 0,
        "positive_median_pnl": (
            bool(selected_pnls) and statistics.median(selected_pnls) > 0
        ),
        "profit_factor": numeric_pf_at_least(
            profit_factor(selected_pnls), config.minimum_profit_factor
        ),
        "positive_active_fold_fraction": (
            bool(active_folds)
            and sum(value > 0 for value in active_folds.values()) / len(active_folds)
            >= config.minimum_positive_active_fold_fraction
        ),
        "target_gains_cover_non_target_losses": target_gains >= non_target_losses,
        "positive_doubled_cost_pnl": sum(doubled_pnls) > 0,
        "doubled_cost_profit_factor": numeric_pf_at_least(
            profit_factor(doubled_pnls), 1.0
        ),
        "positive_after_best_removed": best_removed > 0,
    }
    if not all(sample_gates.values()):
        status = "inconclusive_sample"
    elif not all(economic_gates.values()):
        status = "rejected_development"
    else:
        status = "passed_development_screen"
    return {
        "trial_id": TRIAL_ID,
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "advance_to_minute_stage_b": status == "passed_development_screen",
        "final_test_used": False,
        "sample_gates": sample_gates,
        "economic_gates": economic_gates,
        "metrics": {
            "valid_folds": len(valid_folds),
            "oos_candidates": len(candidates),
            "selected_campaigns": len(selected),
            "selected_targets": sum(bool(row["target_first"]) for row in selected),
            "entry_year_counts": dict(sorted(years.items())),
            "brier_score": pooled_brier,
            "base_brier_score": base_brier,
            "lowest_quintile_target_rate": low_rate,
            "highest_quintile_target_rate": high_rate,
            "total_net_pnl_vnd": sum(selected_pnls),
            "median_net_pnl_vnd": (
                statistics.median(selected_pnls) if selected_pnls else None
            ),
            "profit_factor": profit_factor(selected_pnls),
            "target_gains_vnd": target_gains,
            "non_target_losses_vnd": non_target_losses,
            "double_cost_total_pnl_vnd": sum(doubled_pnls),
            "double_cost_profit_factor": profit_factor(doubled_pnls),
            "best_removed_total_pnl_vnd": best_removed,
            "exit_reasons": dict(sorted(Counter(
                str(row["exit_reason"]) for row in selected
            ).items())),
        },
    }


def write_csv(path: Path, rows: Iterable[dict[str, object]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def run_study(
    daily_path: Path,
    assignments_path: Path,
    output_root: Path,
    preregistration_path: Path,
    config: Config | None = None,
) -> Path:
    config = config or Config()
    config.validate()
    daily, calendar, final_range = read_development_daily(daily_path, config.universe)
    folds = read_folds(assignments_path)
    all_candidates: list[dict[str, object]] = []
    all_quarantine: list[dict[str, object]] = []
    fold_rows: list[dict[str, object]] = []
    model_rows: list[dict[str, object]] = []
    for fold in folds:
        train, train_quarantine = generate_candidates(
            fold, "train", fold.train_dates, daily, calendar, config
        )
        oos, oos_quarantine = generate_candidates(
            fold, "oos", fold.oos_dates, daily, calendar, config
        )
        all_quarantine.extend(train_quarantine + oos_quarantine)
        labels = [int(bool(row["target_first"])) for row in train]
        class_counts = Counter(labels)
        invalid_reason = ""
        if len(train) < config.minimum_train_candidates:
            invalid_reason = "insufficient_train_candidates"
        elif min(class_counts.get(0, 0), class_counts.get(1, 0)) < config.minimum_train_class_count:
            invalid_reason = "insufficient_train_class_count"
        model: LogisticModel | None = None
        if not invalid_reason:
            model = fit_logistic([feature_values(row) for row in train], labels, config)
            if not model.converged:
                invalid_reason = "model_not_converged"
        base_probability = mean([float(value) for value in labels]) if labels else 0.0
        win_pnls = [int(row["net_pnl_vnd"]) for row in train if bool(row["target_first"])]
        nonwin_pnls = [int(row["net_pnl_vnd"]) for row in train if not bool(row["target_first"])]
        mean_win = mean([float(value) for value in win_pnls]) if win_pnls else 0.0
        mean_nonwin = mean([float(value) for value in nonwin_pnls]) if nonwin_pnls else 0.0
        if model is not None and not invalid_reason:
            for row in oos:
                probability = model.probability(feature_values(row))
                row["predicted_probability"] = probability
                row["base_probability"] = base_probability
                row["estimated_ev_vnd"] = (
                    probability * mean_win + (1 - probability) * mean_nonwin
                )
            all_candidates.extend(oos)
            model_rows.append({
                "fold_id": fold.fold_id,
                "iterations": model.iterations,
                "converged": model.converged,
                "base_probability": base_probability,
                **{f"mean_{name}": value for name, value in zip(FEATURE_NAMES, model.means)},
                **{f"scale_{name}": value for name, value in zip(FEATURE_NAMES, model.scales)},
                "intercept": model.weights[0],
                **{f"weight_{name}": value for name, value in zip(FEATURE_NAMES, model.weights[1:])},
            })
        fold_oos = oos if not invalid_reason else []
        fold_rows.append({
            "trial_id": TRIAL_ID,
            "fold_id": fold.fold_id,
            "valid": not bool(invalid_reason),
            "invalid_reason": invalid_reason,
            "train_candidates": len(train),
            "train_targets": sum(labels),
            "oos_candidates": len(fold_oos),
            "selected_campaigns": 0,
            "selected_targets": 0,
            "selected_net_pnl_vnd": 0,
            "selected_double_cost_net_pnl_vnd": 0,
            "brier_score": brier(fold_oos, "predicted_probability") if fold_oos else "",
            "base_brier_score": brier(fold_oos, "base_probability") if fold_oos else "",
            "mean_train_win_pnl_vnd": mean_win,
            "mean_train_nonwin_pnl_vnd": mean_nonwin,
            "model_iterations": model.iterations if model else "",
            "model_converged": model.converged if model else False,
        })
    selected = select_campaigns(all_candidates, calendar, config)
    by_fold_selected: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in selected:
        by_fold_selected[str(row["fold_id"])].append(row)
    for fold_row in fold_rows:
        rows = by_fold_selected[str(fold_row["fold_id"])]
        fold_row["selected_campaigns"] = len(rows)
        fold_row["selected_targets"] = sum(bool(row["target_first"]) for row in rows)
        fold_row["selected_net_pnl_vnd"] = sum(int(row["net_pnl_vnd"]) for row in rows)
        fold_row["selected_double_cost_net_pnl_vnd"] = sum(
            int(row["double_cost_net_pnl_vnd"]) for row in rows
        )
    gate_report = evaluate_gates(fold_rows, all_candidates, selected, config)
    identity = {
        "trial_id": TRIAL_ID,
        "schema_version": SCHEMA_VERSION,
        "config": asdict(config),
        "daily_development_sha256": sha256_file(daily_path),
        "assignments_sha256": sha256_file(assignments_path),
        "preregistration_sha256": sha256_file(preregistration_path),
        "implementation_sha256": sha256_file(Path(__file__)),
        "final_test_range_detected_but_not_parsed": [
            final_range[0].isoformat(), final_range[1].isoformat(),
        ],
    }
    run_id = "trial6_" + sha256_bytes(canonical_json(identity))[:10]
    final_dir = output_root / run_id
    if final_dir.exists():
        raise FileExistsError(f"Create-only Trial 6 output already exists: {final_dir}")
    with tempfile.TemporaryDirectory(prefix="trial6_", dir=output_root) as temporary:
        temporary_dir = Path(temporary)
        write_csv(temporary_dir / "oos_candidates.csv", all_candidates, CANDIDATE_FIELDS)
        write_csv(temporary_dir / "selected_campaigns.csv", selected, CANDIDATE_FIELDS)
        write_csv(temporary_dir / "quarantined_candidates.csv", all_quarantine, QUARANTINE_FIELDS)
        write_csv(temporary_dir / "fold_summary.csv", fold_rows, FOLD_FIELDS)
        model_fields = tuple(model_rows[0]) if model_rows else ("fold_id",)
        write_csv(temporary_dir / "model_parameters.csv", model_rows, model_fields)
        write_json(temporary_dir / "gate_report.json", gate_report)
        artifact_hashes = {
            path.name: sha256_file(path)
            for path in sorted(temporary_dir.iterdir())
            if path.is_file()
        }
        manifest = {**identity, "run_id": run_id, "artifacts": artifact_hashes}
        write_json(temporary_dir / "manifest.json", manifest)
        temporary_dir.rename(final_dir)
    return final_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--development-walk-forward", action="store_true")
    parser.add_argument("--daily", type=Path, default=Path("data_algotradeDB_split.csv"))
    parser.add_argument(
        "--assignments", type=Path,
        default=Path("data/trial5_splits_rotation/walk_forward_date_assignments.csv"),
    )
    parser.add_argument(
        "--output-root", type=Path, default=Path("data/trial6_mean_reversion")
    )
    parser.add_argument(
        "--preregistration", type=Path,
        default=Path("research_log/TRIAL6_POOLED_MEAN_REVERSION_PREREGISTRATION.md"),
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if not args.development_walk_forward:
        raise SystemExit("Only --development-walk-forward is supported")
    args.output_root.mkdir(parents=True, exist_ok=True)
    output = run_study(
        args.daily, args.assignments, args.output_root, args.preregistration
    )
    print(output)
    print((output / "gate_report.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
