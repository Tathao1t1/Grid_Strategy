#!/usr/bin/env python3
"""Trial 18 market-adjusted equilibrium grid with per-fill target economics."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Sequence

import study_trial5_rotation_grid as trial5
import study_trial6_mean_reversion as trial6
import study_trial11_trend_grid as trial11
import study_trial13_dense_grid_ev as trial13
import study_trial15_minute_grid_capture as trial15
import study_trial17_fair_value_reversal_grid as trial17


TRIAL_ID = "TRIAL18-MARKET-EQUILIBRIUM-ECONOMIC-TARGET"
UNIVERSE = trial17.UNIVERSE
EXCLUDED = trial17.EXCLUDED
IS_FOLDS = trial17.IS_FOLDS
VALIDATION_FOLDS = trial17.VALIDATION_FOLDS
EXECUTION = trial17.EXECUTION
HORIZON_SESSIONS = trial17.HORIZON_SESSIONS
EQUILIBRIUM_BETA_SESSIONS = 60
EQUILIBRIUM_MEDIAN_SESSIONS = 20
MAXIMUM_CENTRE_ATR = 2.0
RECLAIM_FRACTION = 0.25
MAXIMUM_LEVELS = 2


@dataclass(frozen=True)
class TargetConfig:
    name: str
    minimum_net_profit_fraction: float
    eligible_to_advance: bool


@dataclass(frozen=True)
class EquilibriumEstimate:
    centre_vnd: int
    raw_centre_vnd: float
    beta: float
    residual_correction: float
    residual_ar1: float
    capped: bool


@dataclass
class EconomicLot:
    acquisition_vnd: int
    tradeable_at: datetime
    target_vnd: int
    stress_loss_vnd: int


@dataclass
class EconomicLevel:
    level_id: int
    buy_limit_vnd: int
    structural_target_vnd: int
    lot: EconomicLot | None = None
    touched_at: datetime | None = None
    rearm_after: datetime | None = None


TARGET_SPACE = (
    TargetConfig("equilibrium_control_0", 0.0000, False),
    TargetConfig("equilibrium_net_50", 0.0050, True),
    TargetConfig("equilibrium_net_75", 0.0075, True),
    TargetConfig("equilibrium_net_100", 0.0100, True),
)

CAMPAIGN_FIELDS = (
    "variant", "fold_id", "signal_date", "entry_date", "exit_date",
    "ticker", "sector", "equilibrium_centre_vnd",
    "raw_equilibrium_centre_vnd", "signal_close_vnd", "equilibrium_beta",
    "equilibrium_residual_correction", "equilibrium_residual_ar1",
    "equilibrium_capped", "spacing_fraction",
    "minimum_net_profit_fraction", "first_level",
    "maximum_inventory_shares", "filled_lots",
    "economic_target_adjustments", "mean_target_gross_distance",
    "target_sales", "net_pnl_vnd", "double_cost_pnl_vnd",
    "campaign_return", "normal_target_gain_vnd", "other_loss_vnd",
    "target_completion", "opportunity_score",
    "fair_value_discount_fraction", "crash_veto_triggered",
    "hard_lower_triggered", *trial13.FEATURE_NAMES,
)
SEARCH_FIELDS = (
    "rank", "eligible", "variant", "minimum_net_profit_fraction",
    "selected_campaigns", "selected_targets", "selected_pnl_vnd",
    "median_pnl_vnd", "profit_factor", "double_cost_pnl_vnd",
    "best_removed_pnl_vnd", "target_gains_vnd", "other_losses_vnd",
    "grid_economic_pnl_vnd", "positive_active_fold_fraction",
    "maximum_ticker_positive_fraction", "entry_years",
    "maximum_year_fraction", "target_rate_quintile_spread",
    "annualized_fold_sharpe", "realized_maximum_drawdown_vnd",
    "realized_maximum_drawdown_fraction", "worst_pnl_vnd",
    "economic_target_adjustment_rate", "mean_target_gross_distance",
    "median_equilibrium_beta", "median_equilibrium_residual_ar1",
    "equilibrium_cap_fraction",
)
FOLD_FIELDS = trial17.FOLD_FIELDS


def config_by_name(name: str) -> TargetConfig:
    return next(value for value in TARGET_SPACE if value.name == name)


def market_adjusted_equilibrium(
    ticker: str,
    signal_index: int,
    daily: dict[str, list[trial6.DailyBar]],
    atr_fraction: float,
) -> EquilibriumEstimate:
    if signal_index < EQUILIBRIUM_BETA_SESSIONS:
        raise ValueError("Market equilibrium requires 60 prior returns")
    start = signal_index - EQUILIBRIUM_BETA_SESSIONS
    ticker_returns: list[float] = []
    market_returns: list[float] = []
    others = [value for value in trial11.TICKERS if value != ticker]
    for index in range(start + 1, signal_index + 1):
        ticker_returns.append(math.log(
            daily[ticker][index].close_vnd
            / daily[ticker][index - 1].close_vnd
        ))
        market_returns.append(statistics.mean(
            math.log(
                daily[other][index].close_vnd
                / daily[other][index - 1].close_vnd
            )
            for other in others
        ))
    market_variance = trial6.variance(market_returns)
    beta = (
        trial6.covariance(ticker_returns, market_returns)
        / market_variance
        if market_variance > 1e-15 else 0.0
    )
    residual_returns = [
        ticker_return - beta * market_return
        for ticker_return, market_return
        in zip(ticker_returns, market_returns)
    ]
    residual_path = [0.0]
    for value in residual_returns:
        residual_path.append(residual_path[-1] + value)
    equilibrium = statistics.median(
        residual_path[-EQUILIBRIUM_MEDIAN_SESSIONS:]
    )
    current = residual_path[-1]
    correction = equilibrium - current
    signal_close = daily[ticker][signal_index].close_vnd
    raw_centre = signal_close * math.exp(correction)
    maximum_centre = signal_close * (
        1 + MAXIMUM_CENTRE_ATR * atr_fraction
    )
    capped_centre = min(raw_centre, maximum_centre)
    centre = trial5.round_to_hsx_tick(capped_centre, "sell")
    recent_path = residual_path[-40:]
    left, right = recent_path[:-1], recent_path[1:]
    path_variance = trial6.variance(left)
    residual_ar1 = (
        trial6.covariance(left, right) / path_variance
        if path_variance > 1e-15 else 0.0
    )
    return EquilibriumEstimate(
        centre_vnd=centre,
        raw_centre_vnd=raw_centre,
        beta=beta,
        residual_correction=correction,
        residual_ar1=residual_ar1,
        capped=raw_centre > maximum_centre,
    )


def minimum_economic_target(
    fill_price_vnd: int,
    minimum_net_profit_fraction: float,
    quantity: int = 100,
) -> int:
    acquisition, _ = trial5.acquisition_cash(
        fill_price_vnd, quantity, EXECUTION, 1.0
    )
    required_cash = math.ceil(
        acquisition * (1 + minimum_net_profit_fraction)
    )
    retained_fraction = (
        1 - EXECUTION.commission_rate - EXECUTION.sell_tax_rate
    )
    approximate = required_cash / (quantity * retained_fraction)
    target = trial5.round_to_hsx_tick(approximate, "sell")
    while True:
        proceeds, _, _ = trial5.net_sale_cash(
            target, quantity, EXECUTION, 1.0
        )
        if proceeds >= required_cash:
            return target
        target += trial5.hsx_tick_vnd(target)


def make_levels(
    centre: int, spacing: float
) -> list[EconomicLevel]:
    result: list[EconomicLevel] = []
    for level_id in range(1, MAXIMUM_LEVELS + 1):
        buy = trial5.round_to_hsx_tick(
            centre / ((1 + spacing) ** level_id), "buy"
        )
        structural_target = trial5.round_to_hsx_tick(
            centre / ((1 + spacing) ** (level_id - 1)), "sell"
        )
        result.append(EconomicLevel(
            level_id, buy, structural_target
        ))
    return result


def _sell_lot(
    level: EconomicLevel,
    bar: trial5.MinuteBar,
    limit: int | None,
    cost_multiplier: float,
) -> int:
    assert level.lot is not None
    assert bar.best_bid_vnd is not None
    price = trial5._execution_sell_price(
        bar.best_bid_vnd, limit, EXECUTION, cost_multiplier
    )
    proceeds, _, _ = trial5.net_sale_cash(
        price, EXECUTION.board_lot, EXECUTION, cost_multiplier
    )
    return proceeds - level.lot.acquisition_vnd


def one_cost_scenario(
    ticker: str,
    signal_date: date,
    path_dates: Sequence[date],
    minutes: dict[date, list[trial5.MinuteBar]],
    centre: int,
    spacing: float,
    config: TargetConfig,
    session_veto: dict[date, bool],
    cost_multiplier: float,
) -> dict[str, object] | None:
    levels = make_levels(centre, spacing)
    hard_lower = trial5.round_to_hsx_tick(
        centre / ((1 + spacing) ** 3), "buy"
    )
    shutdown = False
    crash_triggered = False
    hard_lower_triggered = False
    target_sales = 0
    target_gains = 0
    other_losses = 0
    pnl = 0
    first_entry_date: date | None = None
    first_level: int | None = None
    last_sale_date: date | None = None
    maximum_inventory_shares = 0
    maximum_deployed_vnd = 0
    filled_lots = 0
    economic_adjustments = 0
    target_distance_sum = 0.0

    for day_index, trading_date in enumerate(path_dates):
        if session_veto.get(trading_date, True):
            shutdown = True
            crash_triggered = True
        for bar in minutes.get(trading_date, []):
            acted = False
            if (
                not shutdown
                and (
                    bar.low_vnd <= hard_lower
                    or (
                        bar.best_bid_vnd is not None
                        and bar.best_bid_vnd <= hard_lower
                    )
                )
            ):
                shutdown = True
                hard_lower_triggered = True

            for level in sorted(
                levels, key=lambda value: value.level_id, reverse=True
            ):
                lot = level.lot
                if (
                    lot is None
                    or lot.tradeable_at > bar.event_time
                    or not trial15.usable_book(
                        bar, "sell", EXECUTION.board_lot
                    )
                ):
                    continue
                reason = ""
                limit: int | None = None
                if shutdown:
                    reason = "risk_exit"
                elif (
                    bar.best_bid_vnd is not None
                    and bar.best_bid_vnd >= lot.target_vnd
                    and bar.close_vnd
                    >= lot.target_vnd
                    + trial5.hsx_tick_vnd(lot.target_vnd)
                ):
                    reason = "grid_target"
                    limit = lot.target_vnd
                if not reason:
                    continue
                realized = _sell_lot(
                    level, bar, limit, cost_multiplier
                )
                pnl += realized
                if reason == "grid_target" and realized > 0:
                    target_sales += 1
                    target_gains += realized
                elif realized < 0:
                    other_losses += -realized
                level.lot = None
                level.touched_at = None
                level.rearm_after = trial15.settlement_at(
                    path_dates, day_index
                )
                last_sale_date = trading_date
                acted = True
                break

            if acted or shutdown or day_index > len(path_dates) - 3:
                continue
            if any(
                level.lot is not None
                and level.lot.tradeable_at > bar.event_time
                for level in levels
            ):
                continue

            available: list[EconomicLevel] = []
            for level in levels:
                if level.lot is not None:
                    continue
                if (
                    level.rearm_after is not None
                    and bar.event_time <= level.rearm_after
                ):
                    continue
                touched = (
                    bar.low_vnd <= level.buy_limit_vnd
                    or (
                        bar.best_bid_vnd is not None
                        and bar.best_bid_vnd <= level.buy_limit_vnd
                    )
                )
                if touched and level.touched_at is None:
                    level.touched_at = bar.event_time
                if level.touched_at is None:
                    continue
                reclaim_cap = trial5.round_to_hsx_tick(
                    level.buy_limit_vnd
                    * (1 + RECLAIM_FRACTION * spacing),
                    "sell",
                )
                ready = (
                    bar.event_time > level.touched_at
                    and bar.close_vnd >= level.buy_limit_vnd
                    and bar.best_ask_vnd is not None
                    and bar.best_ask_vnd <= reclaim_cap
                    and trial15.usable_book(
                        bar, "buy", EXECUTION.board_lot
                    )
                )
                if ready:
                    available.append(level)
            if not available:
                continue

            level = max(available, key=lambda value: value.level_id)
            assert bar.best_ask_vnd is not None
            reclaim_cap = trial5.round_to_hsx_tick(
                level.buy_limit_vnd
                * (1 + RECLAIM_FRACTION * spacing),
                "sell",
            )
            price = trial5._execution_buy_price(
                bar.best_ask_vnd, reclaim_cap, EXECUTION, cost_multiplier
            )
            proposed_stress = trial17.normal_floor_stress_loss(
                price, EXECUTION.board_lot
            )
            active_stress = sum(
                existing.lot.stress_loss_vnd
                for existing in levels
                if existing.lot is not None
            )
            if (
                active_stress + proposed_stress
                > trial17.MAXIMUM_STRESS_LOSS_VND
            ):
                level.touched_at = None
                continue
            acquisition, _ = trial5.acquisition_cash(
                price, EXECUTION.board_lot, EXECUTION, cost_multiplier
            )
            economic_target = minimum_economic_target(
                price, config.minimum_net_profit_fraction,
                EXECUTION.board_lot,
            )
            target = max(
                level.structural_target_vnd, economic_target
            )
            if target > level.structural_target_vnd:
                economic_adjustments += 1
            filled_lots += 1
            target_distance_sum += target / price - 1
            level.lot = EconomicLot(
                acquisition,
                trial15.settlement_at(path_dates, day_index),
                target,
                proposed_stress,
            )
            level.touched_at = None
            if first_entry_date is None:
                first_entry_date = trading_date
                first_level = level.level_id
            current_inventory = sum(
                EXECUTION.board_lot
                for existing in levels if existing.lot is not None
            )
            current_deployed = sum(
                existing.lot.acquisition_vnd
                for existing in levels if existing.lot is not None
            )
            maximum_inventory_shares = max(
                maximum_inventory_shares, current_inventory
            )
            maximum_deployed_vnd = max(
                maximum_deployed_vnd, current_deployed
            )

    final_date = path_dates[-1]
    used_exit_times: set[datetime] = set()
    for level in sorted(
        levels, key=lambda value: value.level_id, reverse=True
    ):
        if level.lot is None:
            continue
        exit_bar = next(
            (
                bar
                for bar in reversed(minutes.get(final_date, []))
                if bar.event_time not in used_exit_times
                and bar.event_time >= level.lot.tradeable_at
                and trial15.usable_book(
                    bar, "sell", EXECUTION.board_lot
                )
            ),
            None,
        )
        if exit_bar is None:
            return None
        realized = _sell_lot(level, exit_bar, None, cost_multiplier)
        pnl += realized
        if realized < 0:
            other_losses += -realized
        used_exit_times.add(exit_bar.event_time)
        level.lot = None
        last_sale_date = final_date

    if first_entry_date is None or maximum_deployed_vnd <= 0:
        return None
    return {
        "entry_date": first_entry_date.isoformat(),
        "exit_date": (last_sale_date or first_entry_date).isoformat(),
        "first_level": first_level,
        "maximum_inventory_shares": maximum_inventory_shares,
        "maximum_deployed_vnd": maximum_deployed_vnd,
        "filled_lots": filled_lots,
        "economic_target_adjustments": economic_adjustments,
        "mean_target_gross_distance": (
            target_distance_sum / filled_lots if filled_lots else 0.0
        ),
        "target_sales": target_sales,
        "net_pnl_vnd": pnl,
        "normal_target_gain_vnd": target_gains,
        "other_loss_vnd": other_losses,
        "crash_veto_triggered": crash_triggered,
        "hard_lower_triggered": hard_lower_triggered,
    }


def simulate_campaign(
    ticker: str,
    signal_date: date,
    path_dates: Sequence[date],
    minutes: dict[date, list[trial5.MinuteBar]],
    estimate: EquilibriumEstimate,
    signal_close: int,
    feature: dict[str, float],
    config: TargetConfig,
    session_veto: dict[date, bool],
) -> dict[str, object] | None:
    spacing = min(
        EXECUTION.maximum_grid_step,
        max(
            EXECUTION.minimum_grid_step,
            0.75 * float(feature["atr20_fraction"]),
        ),
    )
    normal = one_cost_scenario(
        ticker, signal_date, path_dates, minutes,
        estimate.centre_vnd, spacing, config, session_veto, 1.0,
    )
    doubled = one_cost_scenario(
        ticker, signal_date, path_dates, minutes,
        estimate.centre_vnd, spacing, config, session_veto, 2.0,
    )
    if normal is None or doubled is None:
        return None
    capital = int(normal["maximum_deployed_vnd"])
    discount = (
        estimate.centre_vnd - signal_close
    ) / estimate.centre_vnd
    return {
        "variant": config.name,
        "signal_date": signal_date.isoformat(),
        "entry_date": normal["entry_date"],
        "exit_date": normal["exit_date"],
        "ticker": ticker,
        "sector": trial11.SECTORS[ticker],
        "equilibrium_centre_vnd": estimate.centre_vnd,
        "raw_equilibrium_centre_vnd": estimate.raw_centre_vnd,
        "signal_close_vnd": signal_close,
        "equilibrium_beta": estimate.beta,
        "equilibrium_residual_correction": estimate.residual_correction,
        "equilibrium_residual_ar1": estimate.residual_ar1,
        "equilibrium_capped": estimate.capped,
        "spacing_fraction": spacing,
        "minimum_net_profit_fraction":
            config.minimum_net_profit_fraction,
        "first_level": normal["first_level"],
        "maximum_inventory_shares":
            normal["maximum_inventory_shares"],
        "filled_lots": normal["filled_lots"],
        "economic_target_adjustments":
            normal["economic_target_adjustments"],
        "mean_target_gross_distance":
            normal["mean_target_gross_distance"],
        "target_sales": int(normal["target_sales"]),
        "net_pnl_vnd": int(normal["net_pnl_vnd"]),
        "double_cost_pnl_vnd": int(doubled["net_pnl_vnd"]),
        "campaign_return": int(normal["net_pnl_vnd"]) / capital,
        "normal_target_gain_vnd":
            int(normal["normal_target_gain_vnd"]),
        "other_loss_vnd": int(normal["other_loss_vnd"]),
        "target_completion": int(normal["target_sales"]) > 0,
        "opportunity_score": trial17.opportunity_score(
            feature, estimate.centre_vnd, signal_close
        ),
        "fair_value_discount_fraction": discount,
        "crash_veto_triggered":
            bool(normal["crash_veto_triggered"]),
        "hard_lower_triggered":
            bool(normal["hard_lower_triggered"]),
        **feature,
    }


def generate_fold_candidates(
    fold: trial6.Fold,
    minute_dir: Path,
    daily: dict[str, list[trial6.DailyBar]],
    calendar: Sequence[date],
    dense_features: dict[tuple[str, int], dict[str, float]],
    configs: Sequence[TargetConfig],
) -> dict[str, list[dict[str, object]]]:
    result = {config.name: [] for config in configs}
    allowed_dates = fold.oos_dates
    minute_fold = trial15.as_minute_fold(fold, allowed_dates)
    minutes, _ = trial5.load_fold_minutes(
        minute_dir, minute_fold, UNIVERSE
    )
    allowed = set(allowed_dates)
    indices = {value: index for index, value in enumerate(calendar)}
    for signal_date in allowed_dates:
        signal_index = indices[signal_date]
        path_dates = calendar[
            signal_index + 1:signal_index + 1 + HORIZON_SESSIONS
        ]
        if (
            len(path_dates) != HORIZON_SESSIONS
            or any(value not in allowed for value in path_dates)
        ):
            continue
        for ticker in UNIVERSE:
            feature = dense_features.get((ticker, signal_index))
            if feature is None or trial17.severe_downtrend(feature):
                continue
            ticker_bars = daily[ticker]
            if any(
                not ticker_bars[indices[value]].reset_verifiable
                or ticker_bars[indices[value]].reference_reset
                for value in path_dates
            ):
                continue
            if float(feature["residual_z5"]) > trial17.MINIMUM_RESIDUAL_Z5:
                continue
            signal_close = ticker_bars[signal_index].close_vnd
            estimate = market_adjusted_equilibrium(
                ticker, signal_index, daily,
                float(feature["atr20_fraction"]),
            )
            if signal_close >= estimate.centre_vnd:
                continue
            session_veto = {
                trading_date: trial17.severe_downtrend(
                    dense_features.get(
                        (ticker, indices[trading_date] - 1)
                    )
                )
                for trading_date in path_dates
            }
            for config in configs:
                row = simulate_campaign(
                    ticker, signal_date, path_dates, minutes[ticker],
                    estimate, signal_close, feature, config, session_veto,
                )
                if row is not None:
                    row["fold_id"] = fold.fold_id
                    result[config.name].append(row)
    return result


def load_partition_candidates(
    folds: Sequence[trial6.Fold],
    minute_dir: Path,
    daily: dict[str, list[trial6.DailyBar]],
    calendar: Sequence[date],
    dense_features: dict[tuple[str, int], dict[str, float]],
    configs: Sequence[TargetConfig],
) -> dict[tuple[str, str], list[dict[str, object]]]:
    result: dict[tuple[str, str], list[dict[str, object]]] = {}
    for fold in folds:
        generated = generate_fold_candidates(
            fold, minute_dir, daily, calendar, dense_features, configs
        )
        for config in configs:
            result[(config.name, fold.fold_id)] = generated[config.name]
    return result


def add_target_diagnostics(
    metrics: dict[str, object],
    selected: Sequence[dict[str, object]],
) -> None:
    fills = sum(int(row["filled_lots"]) for row in selected)
    adjustments = sum(
        int(row["economic_target_adjustments"]) for row in selected
    )
    metrics["economic_target_adjustment_rate"] = (
        adjustments / fills if fills else 0.0
    )
    metrics["mean_target_gross_distance"] = (
        sum(
            float(row["mean_target_gross_distance"])
            * int(row["filled_lots"])
            for row in selected
        ) / fills if fills else 0.0
    )
    metrics["median_equilibrium_beta"] = (
        statistics.median(
            float(row["equilibrium_beta"]) for row in selected
        ) if selected else None
    )
    metrics["median_equilibrium_residual_ar1"] = (
        statistics.median(
            float(row["equilibrium_residual_ar1"]) for row in selected
        ) if selected else None
    )
    metrics["equilibrium_cap_fraction"] = (
        sum(bool(row["equilibrium_capped"]) for row in selected)
        / len(selected) if selected else 0.0
    )


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_csv(
    path: Path,
    rows: Sequence[dict[str, object]],
    fields: Sequence[str],
) -> None:
    with path.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fields, extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(rows)


def optimize_validate(output_dir: Path) -> dict[str, object]:
    if output_dir.exists():
        raise FileExistsError(f"Create-only output exists: {output_dir}")
    output_dir.mkdir(parents=True)
    daily_path = Path("data_algotradeDB_split.csv")
    minute_dir = Path("data/minute_bars")
    assignment_path = Path(
        "data/trial5_splits_rotation/walk_forward_date_assignments.csv"
    )
    daily, calendar, final_range = trial6.read_development_daily(
        daily_path, trial11.TICKERS
    )
    folds = trial6.read_folds(assignment_path)
    fold_by_id = {fold.fold_id: fold for fold in folds}
    is_folds = [fold_by_id[value] for value in IS_FOLDS]
    validation_folds = [
        fold_by_id[value] for value in VALIDATION_FOLDS
    ]
    trend_features = trial11.build_feature_cache(daily, calendar)
    dense_features = trial13.build_dense_feature_cache(
        daily, calendar, trend_features
    )
    candidates = load_partition_candidates(
        is_folds, minute_dir, daily, calendar, dense_features,
        TARGET_SPACE,
    )
    results: dict[str, tuple[
        dict[str, object],
        list[dict[str, object]],
        list[dict[str, object]],
    ]] = {}
    search_rows: list[dict[str, object]] = []
    for config in TARGET_SPACE:
        metrics, selected, fold_rows = trial17.evaluate_variant(
            config, is_folds, candidates, calendar, "in_sample"
        )
        add_target_diagnostics(metrics, selected)
        results[config.name] = (metrics, selected, fold_rows)
        eligible = (
            config.eligible_to_advance
            and trial17.in_sample_eligible(metrics)
        )
        search_rows.append({
            "rank": "",
            "eligible": eligible,
            "variant": config.name,
            "minimum_net_profit_fraction":
                config.minimum_net_profit_fraction,
            **metrics,
        })
    eligible_rows = [
        row for row in search_rows if bool(row["eligible"])
    ]
    eligible_rows.sort(key=lambda row: (
        -int(row["selected_pnl_vnd"]),
        -(
            float(row["profit_factor"])
            if row["profit_factor"] != "Infinity" else 1e9
        ),
        -int(row["double_cost_pnl_vnd"]),
        str(row["variant"]),
    ))
    for rank, row in enumerate(eligible_rows, 1):
        row["rank"] = rank
    chosen = (
        config_by_name(str(eligible_rows[0]["variant"]))
        if eligible_rows else None
    )
    best_observed_row = max(
        search_rows,
        key=lambda row: (
            int(row["selected_pnl_vnd"]),
            int(row["double_cost_pnl_vnd"]),
            str(row["variant"]),
        ),
    )
    best_observed = config_by_name(
        str(best_observed_row["variant"])
    )
    all_campaigns: list[dict[str, object]] = []
    all_folds: list[dict[str, object]] = []
    for config in TARGET_SPACE:
        all_campaigns.extend(results[config.name][1])
        all_folds.extend(results[config.name][2])
    if chosen is not None:
        is_metrics, is_selected, is_fold_rows = results[chosen.name]
        validation_candidates = load_partition_candidates(
            validation_folds, minute_dir, daily, calendar,
            dense_features, (chosen,),
        )
        val_metrics, val_selected, val_fold_rows = (
            trial17.evaluate_variant(
                chosen, validation_folds, validation_candidates,
                calendar, "internal_validation",
            )
        )
        add_target_diagnostics(val_metrics, val_selected)
        gates = trial17.validation_gates(val_metrics)
        status = (
            "passed_internal_validation"
            if all(gates.values()) else "rejected_internal_validation"
        )
    else:
        is_metrics = {}
        is_selected = []
        is_fold_rows = []
        val_metrics = {}
        val_selected = []
        val_fold_rows = []
        gates = {}
        status = "no_in_sample_market_equilibrium_variant"
    best_metrics, best_selected, _ = results[best_observed.name]
    report = {
        "trial_id": TRIAL_ID,
        "exploratory_post_trial17_repair": True,
        "execution_universe": list(UNIVERSE),
        "excluded_tickers": list(EXCLUDED),
        "status": status,
        "target_variants": len(TARGET_SPACE),
        "eligible_in_sample_variants": len(eligible_rows),
        "selected_configuration": asdict(chosen) if chosen else None,
        "selected_in_sample_metrics": is_metrics,
        "best_observed_configuration": asdict(best_observed),
        "best_observed_in_sample_metrics": best_metrics,
        "internal_validation_metrics": val_metrics,
        "internal_validation_gates": gates,
        "advance_to_final_oos": bool(gates) and all(gates.values()),
        "final_test_used": False,
        "final_minute_holdout": [
            trial15.FINAL_START.isoformat(), trial15.FINAL_END.isoformat()
        ],
        "daily_final_range_detected_but_not_parsed": [
            final_range[0].isoformat(), final_range[1].isoformat()
        ],
        "drawdown_definition": (
            "realized closed-campaign equity; not minute mark-to-market"
        ),
    }
    write_csv(
        output_dir / "target_optimization.csv",
        search_rows, SEARCH_FIELDS,
    )
    write_csv(
        output_dir / "all_variant_is_campaigns.csv",
        all_campaigns, CAMPAIGN_FIELDS,
    )
    write_csv(
        output_dir / "all_variant_is_folds.csv",
        all_folds, FOLD_FIELDS,
    )
    write_csv(
        output_dir / "best_observed_is_campaigns.csv",
        best_selected, CAMPAIGN_FIELDS,
    )
    write_csv(
        output_dir / "selected_is_campaigns.csv",
        is_selected, CAMPAIGN_FIELDS,
    )
    write_csv(
        output_dir / "selected_is_folds.csv",
        is_fold_rows, FOLD_FIELDS,
    )
    write_csv(
        output_dir / "validation_campaigns.csv",
        val_selected, CAMPAIGN_FIELDS,
    )
    write_csv(
        output_dir / "validation_folds.csv",
        val_fold_rows, FOLD_FIELDS,
    )
    report_path = output_dir / "development_report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if report["advance_to_final_oos"] and chosen is not None:
        prereg = Path(
            "research_log/"
            "TRIAL18_MARKET_EQUILIBRIUM_ECONOMIC_TARGET_"
            "PREREGISTRATION.md"
        )
        lock = {
            "trial_id": TRIAL_ID,
            "configuration": asdict(chosen),
            "execution_universe": list(UNIVERSE),
            "implementation_sha256": file_sha(Path(__file__)),
            "trial17_dependency_sha256": file_sha(Path(trial17.__file__)),
            "preregistration_sha256": file_sha(prereg),
            "development_report_sha256": file_sha(report_path),
        }
        (output_dir / "FINAL_OOS_CONFIG_LOCK.json").write_text(
            json.dumps(lock, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return report


def run_final_oos(development_dir: Path, output_dir: Path) -> None:
    if not (development_dir / "FINAL_OOS_CONFIG_LOCK.json").exists():
        raise PermissionError(
            "Final minute OOS remains locked because validation did not pass"
        )
    raise NotImplementedError("Final Trial 18 run is not authorized")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--optimize-validate", action="store_true")
    parser.add_argument("--final-oos", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    if args.optimize_validate == args.final_oos:
        raise SystemExit("Choose exactly one mode")
    if args.optimize_validate:
        output = args.output_dir or Path(
            "data/trial18_market_equilibrium_grid/development"
        )
        print(json.dumps(
            optimize_validate(output), indent=2, sort_keys=True
        ))
    else:
        run_final_oos(
            Path("data/trial18_market_equilibrium_grid/development"),
            args.output_dir
            or Path("data/trial18_market_equilibrium_grid/final"),
        )


if __name__ == "__main__":
    main()
