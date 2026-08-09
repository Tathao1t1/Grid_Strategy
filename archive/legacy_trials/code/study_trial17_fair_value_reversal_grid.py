#!/usr/bin/env python3
"""Trial 17 fair-value-anchored, reversal-confirmed minute grid."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Sequence

import study_trial5_rotation_grid as trial5
import study_trial6_mean_reversion as trial6
import study_trial11_trend_grid as trial11
import study_trial13_dense_grid_ev as trial13
import study_trial15_minute_grid_capture as trial15
import study_trial16_eight_ticker_minute as trial16


TRIAL_ID = "TRIAL17-FAIR-VALUE-REVERSAL-GRID"
UNIVERSE = trial16.UNIVERSE
EXCLUDED = trial16.EXCLUDED
IS_FOLDS = trial15.IS_FOLDS
VALIDATION_FOLDS = trial15.VALIDATION_FOLDS
EXECUTION = trial15.EXECUTION
HORIZON_SESSIONS = 7
FAIR_VALUE_SESSIONS = 20
MINIMUM_RESIDUAL_Z5 = -0.50
MAXIMUM_STRESS_LOSS_VND = 1_500_000
MAXIMUM_CONCURRENT = 3
MAXIMUM_SAME_SECTOR = 2
TOP_NEW_PER_DAY = 2
COOLDOWN_SESSIONS = 2
NAV_VND = 100_000_000


@dataclass(frozen=True)
class MechanicConfig:
    name: str
    reclaim_fraction: float
    crash_veto: bool
    maximum_levels: int


@dataclass
class GridLot:
    acquisition_vnd: int
    tradeable_at: datetime
    target_vnd: int
    stress_loss_vnd: int


@dataclass
class GridLevel:
    level_id: int
    buy_limit_vnd: int
    sell_target_vnd: int
    lot: GridLot | None = None
    touched_at: datetime | None = None
    rearm_after: datetime | None = None


MECHANIC_SPACE = (
    MechanicConfig("anchor_touch_1", 0.00, False, 1),
    MechanicConfig("anchor_reclaim_1", 0.25, False, 1),
    MechanicConfig("anchor_reclaim_veto_1", 0.25, True, 1),
    MechanicConfig("anchor_reclaim_veto_2", 0.25, True, 2),
)

CAMPAIGN_FIELDS = (
    "variant", "fold_id", "signal_date", "entry_date", "exit_date",
    "ticker", "sector", "fair_value_centre_vnd", "signal_close_vnd",
    "spacing_fraction", "maximum_levels", "first_level",
    "maximum_inventory_shares", "target_sales", "net_pnl_vnd",
    "double_cost_pnl_vnd", "campaign_return", "normal_target_gain_vnd",
    "other_loss_vnd", "target_completion", "opportunity_score",
    "fair_value_discount_fraction", "crash_veto_triggered",
    "hard_lower_triggered", *trial13.FEATURE_NAMES,
)
FOLD_FIELDS = (
    "partition", "variant", "fold_id", "candidate_campaigns",
    "selected_campaigns", "selected_targets", "selected_pnl_vnd",
    "target_rate_quintile_spread",
)
SEARCH_FIELDS = (
    "rank", "eligible", "variant", "reclaim_fraction", "crash_veto",
    "maximum_levels", "selected_campaigns", "selected_targets",
    "selected_pnl_vnd", "median_pnl_vnd", "profit_factor",
    "double_cost_pnl_vnd", "best_removed_pnl_vnd", "target_gains_vnd",
    "other_losses_vnd", "grid_economic_pnl_vnd",
    "positive_active_fold_fraction", "maximum_ticker_positive_fraction",
    "entry_years", "maximum_year_fraction",
    "target_rate_quintile_spread", "annualized_fold_sharpe",
    "realized_maximum_drawdown_vnd",
    "realized_maximum_drawdown_fraction", "worst_pnl_vnd",
    "forced_loss_reduction_vs_touch", "target_gain_retention_vs_touch",
)


def config_by_name(name: str) -> MechanicConfig:
    return next(value for value in MECHANIC_SPACE if value.name == name)


def fair_value_centre(
    bars: Sequence[trial6.DailyBar], signal_index: int
) -> int:
    closes = [
        bar.close_vnd
        for bar in bars[
            signal_index - FAIR_VALUE_SESSIONS + 1:signal_index + 1
        ]
    ]
    if len(closes) != FAIR_VALUE_SESSIONS:
        raise ValueError("Fair-value centre requires 20 sessions")
    return trial5.round_to_hsx_tick(statistics.median(closes), "sell")


def severe_downtrend(feature: dict[str, float] | None) -> bool:
    if feature is None:
        return True
    flags = (
        float(feature["market_return20"]) <= -0.03,
        float(feature["close_minus_sma50_fraction"])
        <= -float(feature["atr20_fraction"]),
        float(feature["residual_slope20"]) < 0
        and float(feature["residual_1"]) < 0,
    )
    return sum(flags) >= 2


def opportunity_score(
    feature: dict[str, float], centre: int, signal_close: int
) -> float:
    discount = max(0.0, (centre - signal_close) / centre)
    return (
        -float(feature["residual_z5"])
        + discount / max(float(feature["atr20_fraction"]), 1e-9)
    )


def make_levels(
    centre: int, spacing: float, maximum_levels: int
) -> list[GridLevel]:
    result: list[GridLevel] = []
    for level_id in range(1, maximum_levels + 1):
        buy = trial5.round_to_hsx_tick(
            centre / ((1 + spacing) ** level_id), "buy"
        )
        target = trial5.round_to_hsx_tick(
            centre / ((1 + spacing) ** (level_id - 1)), "sell"
        )
        result.append(GridLevel(level_id, buy, target))
    return result


def normal_floor_stress_loss(entry_price: int, quantity: int = 100) -> int:
    floor_price = trial5.consecutive_floor_price(
        entry_price, 2, EXECUTION.stress_floor_limit_fraction
    )
    acquisition, _ = trial5.acquisition_cash(
        entry_price, quantity, EXECUTION, 1.0
    )
    proceeds, _, _ = trial5.net_sale_cash(
        floor_price, quantity, EXECUTION, 1.0
    )
    return max(0, acquisition - proceeds)


def _sell_lot(
    level: GridLevel,
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
    config: MechanicConfig,
    session_veto: dict[date, bool],
    cost_multiplier: float,
) -> dict[str, object] | None:
    levels = make_levels(centre, spacing, config.maximum_levels)
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

    for day_index, trading_date in enumerate(path_dates):
        if config.crash_veto and session_veto.get(trading_date, True):
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
                    and bar.best_bid_vnd >= level.sell_target_vnd
                    and bar.close_vnd
                    >= level.sell_target_vnd
                    + trial5.hsx_tick_vnd(level.sell_target_vnd)
                ):
                    reason = "grid_target"
                    limit = level.sell_target_vnd
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

            available_levels: list[GridLevel] = []
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
                if config.reclaim_fraction > 0:
                    cap = trial5.round_to_hsx_tick(
                        level.buy_limit_vnd
                        * (1 + config.reclaim_fraction * spacing),
                        "sell",
                    )
                    ready = (
                        bar.event_time > level.touched_at
                        and bar.close_vnd >= level.buy_limit_vnd
                        and bar.best_ask_vnd is not None
                        and bar.best_ask_vnd <= cap
                    )
                else:
                    cap = level.buy_limit_vnd
                    ready = (
                        bar.event_time >= level.touched_at
                        and bar.best_ask_vnd is not None
                        and bar.best_ask_vnd <= cap
                    )
                if (
                    ready
                    and trial15.usable_book(
                        bar, "buy", EXECUTION.board_lot
                    )
                ):
                    available_levels.append(level)

            if not available_levels:
                continue
            level = max(available_levels, key=lambda value: value.level_id)
            assert bar.best_ask_vnd is not None
            cap = trial5.round_to_hsx_tick(
                level.buy_limit_vnd
                * (1 + config.reclaim_fraction * spacing),
                "sell",
            )
            price = trial5._execution_buy_price(
                bar.best_ask_vnd, cap, EXECUTION, cost_multiplier
            )
            proposed_stress = normal_floor_stress_loss(
                price, EXECUTION.board_lot
            )
            active_stress = sum(
                existing.lot.stress_loss_vnd
                for existing in levels
                if existing.lot is not None
            )
            if active_stress + proposed_stress > MAXIMUM_STRESS_LOSS_VND:
                level.touched_at = None
                continue
            acquisition, _ = trial5.acquisition_cash(
                price, EXECUTION.board_lot, EXECUTION, cost_multiplier
            )
            level.lot = GridLot(
                acquisition,
                trial15.settlement_at(path_dates, day_index),
                level.sell_target_vnd,
                proposed_stress,
            )
            level.touched_at = None
            if first_entry_date is None:
                first_entry_date = trading_date
                first_level = level.level_id
            current_inventory = sum(
                EXECUTION.board_lot
                for existing in levels
                if existing.lot is not None
            )
            current_deployed = sum(
                existing.lot.acquisition_vnd
                for existing in levels
                if existing.lot is not None
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
        "exit_date": (
            last_sale_date or first_entry_date
        ).isoformat(),
        "first_level": first_level,
        "maximum_inventory_shares": maximum_inventory_shares,
        "maximum_deployed_vnd": maximum_deployed_vnd,
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
    centre: int,
    signal_close: int,
    feature: dict[str, float],
    config: MechanicConfig,
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
        ticker, signal_date, path_dates, minutes, centre, spacing,
        config, session_veto, 1.0,
    )
    doubled = one_cost_scenario(
        ticker, signal_date, path_dates, minutes, centre, spacing,
        config, session_veto, 2.0,
    )
    if normal is None or doubled is None:
        return None
    capital = int(normal["maximum_deployed_vnd"])
    discount = (centre - signal_close) / centre
    return {
        "variant": config.name,
        "signal_date": signal_date.isoformat(),
        "entry_date": normal["entry_date"],
        "exit_date": normal["exit_date"],
        "ticker": ticker,
        "sector": trial11.SECTORS[ticker],
        "fair_value_centre_vnd": centre,
        "signal_close_vnd": signal_close,
        "spacing_fraction": spacing,
        "maximum_levels": config.maximum_levels,
        "first_level": normal["first_level"],
        "maximum_inventory_shares": normal["maximum_inventory_shares"],
        "target_sales": int(normal["target_sales"]),
        "net_pnl_vnd": int(normal["net_pnl_vnd"]),
        "double_cost_pnl_vnd": int(doubled["net_pnl_vnd"]),
        "campaign_return": int(normal["net_pnl_vnd"]) / capital,
        "normal_target_gain_vnd": int(normal["normal_target_gain_vnd"]),
        "other_loss_vnd": int(normal["other_loss_vnd"]),
        "target_completion": int(normal["target_sales"]) > 0,
        "opportunity_score": opportunity_score(
            feature, centre, signal_close
        ),
        "fair_value_discount_fraction": discount,
        "crash_veto_triggered": bool(normal["crash_veto_triggered"]),
        "hard_lower_triggered": bool(normal["hard_lower_triggered"]),
        **feature,
    }


def generate_fold_candidates(
    fold: trial6.Fold,
    allowed_dates: Sequence[date],
    minute_dir: Path,
    daily: dict[str, list[trial6.DailyBar]],
    calendar: Sequence[date],
    dense_features: dict[tuple[str, int], dict[str, float]],
    configs: Sequence[MechanicConfig],
) -> dict[str, list[dict[str, object]]]:
    result = {config.name: [] for config in configs}
    if not allowed_dates:
        return result
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
            if feature is None:
                continue
            ticker_bars = daily[ticker]
            if any(
                not ticker_bars[indices[value]].reset_verifiable
                or ticker_bars[indices[value]].reference_reset
                for value in path_dates
            ):
                continue
            signal_close = ticker_bars[signal_index].close_vnd
            centre = fair_value_centre(ticker_bars, signal_index)
            if (
                float(feature["residual_z5"]) > MINIMUM_RESIDUAL_Z5
                or signal_close >= centre
            ):
                continue
            session_veto = {
                trading_date: severe_downtrend(
                    dense_features.get(
                        (ticker, indices[trading_date] - 1)
                    )
                )
                for trading_date in path_dates
            }
            for config in configs:
                if config.crash_veto and severe_downtrend(feature):
                    continue
                row = simulate_campaign(
                    ticker, signal_date, path_dates, minutes[ticker],
                    centre, signal_close, feature, config, session_veto,
                )
                if row is not None:
                    row["fold_id"] = fold.fold_id
                    result[config.name].append(row)
    return result


def select_campaigns(
    rows: Sequence[dict[str, object]], calendar: Sequence[date]
) -> list[dict[str, object]]:
    indices = {value: index for index, value in enumerate(calendar)}
    by_entry: dict[date, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        by_entry[date.fromisoformat(str(row["entry_date"]))].append(row)
    active: list[dict[str, object]] = []
    cooldown: dict[str, int] = {}
    selected: list[dict[str, object]] = []
    for entry_date in sorted(by_entry):
        current = indices[entry_date]
        active = [
            row for row in active
            if date.fromisoformat(str(row["exit_date"])) >= entry_date
        ]
        active_tickers = {str(row["ticker"]) for row in active}
        sector_counts = Counter(str(row["sector"]) for row in active)
        available = MAXIMUM_CONCURRENT - len(active)
        opened = 0
        ranked = sorted(
            by_entry[entry_date],
            key=lambda row: (
                -float(row["opportunity_score"]),
                float(row["residual_z5"]),
                str(row["ticker"]),
            ),
        )
        for row in ranked:
            if available <= 0 or opened >= TOP_NEW_PER_DAY:
                break
            ticker = str(row["ticker"])
            sector = str(row["sector"])
            if ticker in active_tickers:
                continue
            if sector_counts[sector] >= MAXIMUM_SAME_SECTOR:
                continue
            if current <= cooldown.get(ticker, -1):
                continue
            selected.append(row)
            active.append(row)
            active_tickers.add(ticker)
            sector_counts[sector] += 1
            cooldown[ticker] = (
                indices[date.fromisoformat(str(row["exit_date"]))]
                + COOLDOWN_SESSIONS
            )
            available -= 1
            opened += 1
    return selected


def quintile_spread(rows: Sequence[dict[str, object]]) -> float | None:
    if len(rows) < 10:
        return None
    ranked = sorted(rows, key=lambda row: float(row["opportunity_score"]))
    size = max(1, len(ranked) // 5)
    low = statistics.mean(
        float(bool(row["target_completion"])) for row in ranked[:size]
    )
    high = statistics.mean(
        float(bool(row["target_completion"])) for row in ranked[-size:]
    )
    return high - low


def profit_factor(pnls: Sequence[int]) -> float | str:
    gains = sum(value for value in pnls if value > 0)
    losses = -sum(value for value in pnls if value < 0)
    if losses == 0:
        return "Infinity" if gains > 0 else 0.0
    return gains / losses


def annualized_fold_sharpe(fold_pnls: Sequence[int]) -> float | None:
    returns = [value / NAV_VND for value in fold_pnls]
    if len(returns) < 2:
        return None
    deviation = statistics.stdev(returns)
    if deviation == 0:
        return None
    return statistics.mean(returns) / deviation * math.sqrt(6)


def realized_drawdown(
    selected: Sequence[dict[str, object]],
) -> tuple[int, float]:
    equity = NAV_VND
    peak = NAV_VND
    worst_vnd = 0
    worst_fraction = 0.0
    for row in sorted(
        selected,
        key=lambda value: (
            str(value["exit_date"]),
            str(value["ticker"]),
            str(value["entry_date"]),
        ),
    ):
        equity += int(row["net_pnl_vnd"])
        peak = max(peak, equity)
        drawdown_vnd = peak - equity
        drawdown_fraction = drawdown_vnd / peak
        worst_vnd = max(worst_vnd, drawdown_vnd)
        worst_fraction = max(worst_fraction, drawdown_fraction)
    return worst_vnd, worst_fraction


def evaluate_variant(
    config: MechanicConfig,
    folds: Sequence[trial6.Fold],
    candidates: dict[tuple[str, str], list[dict[str, object]]],
    calendar: Sequence[date],
    partition: str,
) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
    selected: list[dict[str, object]] = []
    fold_rows: list[dict[str, object]] = []
    active_fold_pnls: list[int] = []
    fold_pnls: list[int] = []
    all_candidates: list[dict[str, object]] = []
    for fold in folds:
        rows = candidates[(config.name, fold.fold_id)]
        chosen = select_campaigns(rows, calendar)
        pnl = sum(int(row["net_pnl_vnd"]) for row in chosen)
        fold_pnls.append(pnl)
        if chosen:
            active_fold_pnls.append(pnl)
        selected.extend(chosen)
        all_candidates.extend(rows)
        fold_rows.append({
            "partition": partition,
            "variant": config.name,
            "fold_id": fold.fold_id,
            "candidate_campaigns": len(rows),
            "selected_campaigns": len(chosen),
            "selected_targets": sum(
                bool(row["target_completion"]) for row in chosen
            ),
            "selected_pnl_vnd": pnl,
            "target_rate_quintile_spread": quintile_spread(rows),
        })
    pnls = [int(row["net_pnl_vnd"]) for row in selected]
    doubles = [int(row["double_cost_pnl_vnd"]) for row in selected]
    years = Counter(str(row["entry_date"])[:4] for row in selected)
    ticker_positive: dict[str, int] = defaultdict(int)
    for row in selected:
        if int(row["net_pnl_vnd"]) > 0:
            ticker_positive[str(row["ticker"])] += int(row["net_pnl_vnd"])
    positive_pool = sum(ticker_positive.values())
    target_gains = sum(
        int(row["normal_target_gain_vnd"]) for row in selected
    )
    other_losses = sum(int(row["other_loss_vnd"]) for row in selected)
    drawdown_vnd, drawdown_fraction = realized_drawdown(selected)
    metrics = {
        "valid_folds": len(folds),
        "selected_campaigns": len(selected),
        "selected_targets": sum(
            bool(row["target_completion"]) for row in selected
        ),
        "selected_pnl_vnd": sum(pnls),
        "median_pnl_vnd": statistics.median(pnls) if pnls else None,
        "profit_factor": profit_factor(pnls),
        "double_cost_pnl_vnd": sum(doubles),
        "best_removed_pnl_vnd": sum(pnls) - max(pnls) if pnls else 0,
        "target_gains_vnd": target_gains,
        "other_losses_vnd": other_losses,
        "grid_economic_pnl_vnd": target_gains - other_losses,
        "positive_active_fold_fraction": (
            sum(value > 0 for value in active_fold_pnls)
            / len(active_fold_pnls)
            if active_fold_pnls else 0.0
        ),
        "maximum_ticker_positive_fraction": (
            max(ticker_positive.values(), default=0) / positive_pool
            if positive_pool else 0.0
        ),
        "entry_years": len(years),
        "maximum_year_fraction": (
            max(years.values(), default=0) / len(selected)
            if selected else 0.0
        ),
        "target_rate_quintile_spread": quintile_spread(all_candidates),
        "annualized_fold_sharpe": annualized_fold_sharpe(fold_pnls),
        "realized_maximum_drawdown_vnd": drawdown_vnd,
        "realized_maximum_drawdown_fraction": drawdown_fraction,
        "worst_pnl_vnd": min(pnls) if pnls else None,
        "active_folds": len(active_fold_pnls),
    }
    return metrics, selected, fold_rows


def in_sample_eligible(metrics: dict[str, object]) -> bool:
    pf = metrics["profit_factor"]
    return (
        int(metrics["valid_folds"]) == 9
        and int(metrics["selected_campaigns"]) >= 20
        and int(metrics["selected_targets"]) >= 10
        and int(metrics["entry_years"]) >= 2
        and float(metrics["maximum_year_fraction"]) <= 0.75
        and int(metrics["selected_pnl_vnd"]) > 0
        and metrics["median_pnl_vnd"] is not None
        and float(metrics["median_pnl_vnd"]) > 0
        and (pf == "Infinity" or isinstance(pf, float) and pf >= 1.20)
        and int(metrics["double_cost_pnl_vnd"]) > 0
        and int(metrics["best_removed_pnl_vnd"]) > 0
        and int(metrics["grid_economic_pnl_vnd"]) > 0
        and float(metrics["positive_active_fold_fraction"]) >= 0.60
        and float(metrics["maximum_ticker_positive_fraction"]) <= 0.40
        and metrics["target_rate_quintile_spread"] is not None
        and float(metrics["target_rate_quintile_spread"]) > 0
    )


def validation_gates(metrics: dict[str, object]) -> dict[str, bool]:
    pf = metrics["profit_factor"]
    return {
        "minimum_10_campaigns": int(metrics["selected_campaigns"]) >= 10,
        "minimum_5_targets": int(metrics["selected_targets"]) >= 5,
        "positive_total_pnl": int(metrics["selected_pnl_vnd"]) > 0,
        "positive_median_pnl": (
            metrics["median_pnl_vnd"] is not None
            and float(metrics["median_pnl_vnd"]) > 0
        ),
        "profit_factor_at_least_1": (
            pf == "Infinity" or isinstance(pf, float) and pf >= 1.0
        ),
        "positive_doubled_cost_pnl": int(
            metrics["double_cost_pnl_vnd"]
        ) > 0,
        "positive_after_best_removed": int(
            metrics["best_removed_pnl_vnd"]
        ) > 0,
        "target_gains_cover_other_losses": int(
            metrics["grid_economic_pnl_vnd"]
        ) >= 0,
        "positive_score_quintile_spread": (
            metrics["target_rate_quintile_spread"] is not None
            and float(metrics["target_rate_quintile_spread"]) > 0
        ),
        "worst_loss_within_1_5pct_nav": (
            metrics["worst_pnl_vnd"] is not None
            and int(metrics["worst_pnl_vnd"]) >= -MAXIMUM_STRESS_LOSS_VND
        ),
    }


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


def load_partition_candidates(
    folds: Sequence[trial6.Fold],
    minute_dir: Path,
    daily: dict[str, list[trial6.DailyBar]],
    calendar: Sequence[date],
    dense_features: dict[tuple[str, int], dict[str, float]],
    configs: Sequence[MechanicConfig],
) -> dict[tuple[str, str], list[dict[str, object]]]:
    result: dict[tuple[str, str], list[dict[str, object]]] = {}
    for fold in folds:
        generated = generate_fold_candidates(
            fold, fold.oos_dates, minute_dir, daily, calendar,
            dense_features, configs,
        )
        for config in configs:
            result[(config.name, fold.fold_id)] = generated[config.name]
    return result


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
        MECHANIC_SPACE,
    )
    results: dict[str, tuple[
        dict[str, object],
        list[dict[str, object]],
        list[dict[str, object]],
    ]] = {}
    for config in MECHANIC_SPACE:
        results[config.name] = evaluate_variant(
            config, is_folds, candidates, calendar, "in_sample"
        )
    baseline = results["anchor_touch_1"][0]
    baseline_losses = int(baseline["other_losses_vnd"])
    baseline_gains = int(baseline["target_gains_vnd"])
    search_rows: list[dict[str, object]] = []
    for config in MECHANIC_SPACE:
        metrics = results[config.name][0]
        loss_reduction = (
            1 - int(metrics["other_losses_vnd"]) / baseline_losses
            if baseline_losses > 0 else None
        )
        gain_retention = (
            int(metrics["target_gains_vnd"]) / baseline_gains
            if baseline_gains > 0 else None
        )
        metrics["forced_loss_reduction_vs_touch"] = loss_reduction
        metrics["target_gain_retention_vs_touch"] = gain_retention
        search_rows.append({
            "rank": "",
            "eligible": in_sample_eligible(metrics),
            "variant": config.name,
            "reclaim_fraction": config.reclaim_fraction,
            "crash_veto": config.crash_veto,
            "maximum_levels": config.maximum_levels,
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
    best_observed = config_by_name(str(best_observed_row["variant"]))
    all_variant_campaigns: list[dict[str, object]] = []
    all_variant_folds: list[dict[str, object]] = []
    for config in MECHANIC_SPACE:
        all_variant_campaigns.extend(results[config.name][1])
        all_variant_folds.extend(results[config.name][2])
    if chosen is not None:
        is_metrics, is_selected, is_fold_rows = results[chosen.name]
        validation_candidates = load_partition_candidates(
            validation_folds, minute_dir, daily, calendar, dense_features,
            (chosen,),
        )
        val_metrics, val_selected, val_fold_rows = evaluate_variant(
            chosen, validation_folds, validation_candidates, calendar,
            "internal_validation",
        )
        gates = validation_gates(val_metrics)
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
        status = "no_in_sample_fair_value_variant"
    best_metrics, best_selected, _ = results[best_observed.name]
    report = {
        "trial_id": TRIAL_ID,
        "exploratory_post_trial16_redesign": True,
        "execution_universe": list(UNIVERSE),
        "excluded_tickers": list(EXCLUDED),
        "status": status,
        "mechanic_variants": len(MECHANIC_SPACE),
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
        output_dir / "mechanic_optimization.csv",
        search_rows, SEARCH_FIELDS,
    )
    write_csv(
        output_dir / "all_variant_is_campaigns.csv",
        all_variant_campaigns, CAMPAIGN_FIELDS,
    )
    write_csv(
        output_dir / "all_variant_is_folds.csv",
        all_variant_folds, FOLD_FIELDS,
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
            "TRIAL17_FAIR_VALUE_REVERSAL_GRID_PREREGISTRATION.md"
        )
        lock = {
            "trial_id": TRIAL_ID,
            "configuration": asdict(chosen),
            "execution_universe": list(UNIVERSE),
            "implementation_sha256": file_sha(Path(__file__)),
            "trial15_dependency_sha256": file_sha(Path(trial15.__file__)),
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
    raise NotImplementedError("Final Trial 17 run is not authorized")


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
            "data/trial17_fair_value_reversal_grid/development"
        )
        print(json.dumps(
            optimize_validate(output), indent=2, sort_keys=True
        ))
    else:
        run_final_oos(
            Path("data/trial17_fair_value_reversal_grid/development"),
            args.output_dir
            or Path("data/trial17_fair_value_reversal_grid/final"),
        )


if __name__ == "__main__":
    main()
