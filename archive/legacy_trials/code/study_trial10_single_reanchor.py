#!/usr/bin/env python3
"""Paired fixed-centre versus single-reanchor recovery-grid study."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Sequence

import study_trial6_mean_reversion as trial6
import study_trial9_dynamic_inventory_grid as trial9
from study_trial5_rotation_grid import round_to_hsx_tick


TRIAL_ID = "TRIAL10-SINGLE-REANCHOR-RECOVERY-GRID"
TICKERS = trial6.TICKERS
NAV_VND = 100_000_000


@dataclass(frozen=True)
class Config:
    maximum_horizon: int = 20
    initial_levels: int = 2
    initial_quantity: int = 100
    recovery_quantity: int = 100
    maximum_inventory: int = 300
    settlement_sessions: int = 2
    range_atr: float = 2.0
    buffer_atr: float = 0.75
    grid_intervals: int = 6
    stabilization_sessions: int = 3
    stress_budget_fraction: float = 0.015
    incremental_stress_fraction: float = 0.005
    residual_z_max: float = -0.50
    market_downtrend_return5: float = -0.05
    ticker_downtrend_return10: float = -0.08
    residual_breakdown_z: float = -2.0
    maximum_concurrent: int = 3
    cooldown_sessions: int = 5
    commission_rate: float = 0.0015
    sell_tax_rate: float = 0.0010
    execution_haircut: float = 0.0005


@dataclass(frozen=True)
class Level:
    level_id: str
    buy_vnd: int
    target_vnd: int
    quantity: int


@dataclass
class Lot:
    level_id: str
    quantity: int
    buy_offset: int
    buy_price_vnd: int
    target_vnd: int
    acquisition_vnd: int
    double_acquisition_vnd: int
    sold: bool = False
    sale_price_vnd: int = 0
    sale_reason: str = ""


PAIRED_FIELDS = (
    "trial_id", "fold_id", "ticker", "sector", "signal_date", "entry_date",
    "residual_z5", "residual_1", "control_executed", "control_net_pnl_vnd",
    "control_double_pnl_vnd", "control_profit_target_sales",
    "control_risk_exit", "control_time_exit", "control_max_inventory",
    "reanchor_executed", "reanchor_net_pnl_vnd", "reanchor_double_pnl_vnd",
    "reanchor_profit_target_sales", "reanchor_risk_exit",
    "reanchor_time_exit", "reanchor_max_inventory", "lower_bound_breached",
    "reanchored", "recovery_lot_filled", "reanchor_stress_cancelled",
    "paired_improvement_vnd",
)


def acquisition(price: int, quantity: int, config: Config, multiplier: float = 1.0) -> int:
    executed = round(price * (1 + config.execution_haircut * multiplier))
    notional = executed * quantity
    return notional + round(notional * config.commission_rate * multiplier)


def sale_cash(price: int, quantity: int, config: Config, multiplier: float = 1.0) -> int:
    executed = round(price * (1 - config.execution_haircut * multiplier))
    notional = executed * quantity
    return (
        notional
        - round(notional * config.commission_rate * multiplier)
        - round(notional * config.sell_tax_rate * multiplier)
    )


def dynamic_grid(
    bars: Sequence[trial6.DailyBar],
    as_of_index: int,
    center_sessions: int,
    config: Config,
) -> tuple[float, int, int, int, float, list[int]]:
    center = statistics.mean(
        bar.close_vnd
        for bar in bars[as_of_index - center_sessions + 1:as_of_index + 1]
    )
    atr_value = trial6.atr(bars[as_of_index - 20:as_of_index + 1])
    lower_raw = center - config.range_atr * atr_value
    upper_raw = center + config.range_atr * atr_value
    lower = round_to_hsx_tick(lower_raw, "buy")
    upper = round_to_hsx_tick(upper_raw, "sell")
    hard_lower = round_to_hsx_tick(
        lower_raw - config.buffer_atr * atr_value, "sell"
    )
    ratio = (upper / lower) ** (1 / config.grid_intervals) - 1
    grid = [
        round_to_hsx_tick(
            lower * ((1 + ratio) ** index),
            "buy" if lower * ((1 + ratio) ** index) < center else "sell",
        )
        for index in range(config.grid_intervals + 1)
    ]
    return center, lower, upper, hard_lower, ratio, grid


def initial_levels(
    bars: Sequence[trial6.DailyBar], signal_index: int, config: Config
) -> tuple[float, int, int, list[Level]]:
    center, lower, _, hard_lower, _, grid = dynamic_grid(
        bars, signal_index, 20, config
    )
    below = [index for index, value in enumerate(grid[:-1]) if value < center]
    indices = list(reversed(below[-config.initial_levels:]))
    levels = [
        Level(
            f"initial_{number}",
            grid[index],
            round_to_hsx_tick(grid[index + 1], "sell"),
            config.initial_quantity,
        )
        for number, index in enumerate(indices)
    ]
    return center, lower, hard_lower, levels


def recovery_parameters(
    bars: Sequence[trial6.DailyBar], as_of_index: int, config: Config
) -> tuple[float, int, int, Level]:
    center, _, _, hard_lower, _, grid = dynamic_grid(
        bars, as_of_index, 5, config
    )
    below = [index for index, value in enumerate(grid[:-1]) if value < center]
    nearest = below[-1]
    level = Level(
        "recovery",
        grid[nearest],
        round_to_hsx_tick(center, "sell"),
        config.recovery_quantity,
    )
    upper_target = round_to_hsx_tick(grid[nearest + 1], "sell")
    return center, hard_lower, upper_target, level


def make_lot(level: Level, offset: int, price: int, config: Config) -> Lot:
    return Lot(
        level.level_id, level.quantity, offset, price, level.target_vnd,
        acquisition(price, level.quantity, config),
        acquisition(price, level.quantity, config, 2.0),
    )


def sell(lot: Lot, price: int, reason: str) -> None:
    lot.sold = True
    lot.sale_price_vnd = price
    lot.sale_reason = reason


def features_at(
    ticker: str,
    index: int,
    daily: dict[str, list[trial6.DailyBar]],
) -> dict[str, float] | None:
    feature_config = replace(trial6.Config(), candidate_residual_z_max=100.0)
    features, reasons = trial6.feature_vector(
        ticker, index, daily, feature_config
    )
    if features is None or any(
        reason not in ("residual_not_low_enough",) for reason in reasons
    ):
        return None
    return features


def downtrend_clear(
    ticker: str,
    index: int,
    daily: dict[str, list[trial6.DailyBar]],
    config: Config,
) -> tuple[bool, dict[str, float] | None]:
    features = features_at(ticker, index, daily)
    if features is None:
        return False, features
    bars = daily[ticker]
    ticker_return10 = bars[index].close_vnd / bars[index - 10].close_vnd - 1
    clear = (
        ticker_return10 > config.ticker_downtrend_return10
        and float(features["market_return5"]) > config.market_downtrend_return5
        and not (
            float(features["residual_z5"]) <= config.residual_breakdown_z
            and float(features["residual_1"]) < 0
        )
    )
    return clear, features


def stabilized(
    ticker: str,
    index: int,
    breach_index: int,
    daily: dict[str, list[trial6.DailyBar]],
    config: Config,
) -> bool:
    if index - breach_index < config.stabilization_sessions:
        return False
    bars = daily[ticker]
    lows = [bar.low_vnd for bar in bars[index - 2:index + 1]]
    closes = [bar.close_vnd for bar in bars[index - 2:index + 1]]
    clear, features = downtrend_clear(ticker, index, daily, config)
    return (
        clear
        and features is not None
        and lows[0] <= lows[1] <= lows[2]
        and closes[0] < closes[1] < closes[2]
        and float(features["residual_1"]) > 0
    )


def recovery_stress_ok(
    lots: Sequence[Lot],
    recovery_price: int,
    hard_lower: int,
    config: Config,
) -> bool:
    existing_loss = sum(
        max(
            lot.acquisition_vnd - sale_cash(hard_lower, lot.quantity, config),
            0,
        )
        for lot in lots if not lot.sold
    )
    recovery_loss = max(
        acquisition(recovery_price, config.recovery_quantity, config)
        - sale_cash(hard_lower, config.recovery_quantity, config),
        0,
    )
    return (
        existing_loss + recovery_loss
        <= NAV_VND * config.stress_budget_fraction
        and recovery_loss <= NAV_VND * config.incremental_stress_fraction
    )


def simulate(
    ticker: str,
    signal_index: int,
    daily: dict[str, list[trial6.DailyBar]],
    config: Config,
    enable_reanchor: bool,
) -> dict[str, object] | None:
    bars = daily[ticker]
    entry_index = signal_index + 1
    end_index = entry_index + config.maximum_horizon
    if end_index >= len(bars):
        return None
    path = bars[entry_index:end_index + 1]
    if any(not bar.reset_verifiable or bar.reference_reset for bar in path):
        return None
    center0, lower0, hard_lower0, levels = initial_levels(
        bars, signal_index, config
    )
    active_hard_lower = hard_lower0
    active_levels = list(levels)
    pending: set[str] = set()
    purchased: set[str] = set()
    lots: list[Lot] = []
    state = "ACTIVE"
    breach_index = -1
    lower_breached = False
    reanchored = False
    recovery_filled = False
    recovery_stress_cancelled = False
    risk_exit = False
    time_exit = False
    maximum_inventory = 0

    for offset, bar in enumerate(path):
        global_index = entry_index + offset
        prior_index = global_index - 1

        if state == "SHUTDOWN":
            for lot in lots:
                if not lot.sold and offset >= lot.buy_offset + config.settlement_sessions:
                    sell(lot, bar.open_vnd, "locked_risk_exit")
            if all(lot.sold for lot in lots):
                break
            continue

        if (
            enable_reanchor
            and state == "RECOVERY_WAIT"
            and stabilized(ticker, prior_index, breach_index, daily, config)
        ):
            center1, hard_lower1, upper_target, recovery_level = recovery_parameters(
                bars, prior_index, config
            )
            if center1 < center0:
                reanchored = True
                state = "RECOVERY"
                active_hard_lower = hard_lower1
                active_levels = [recovery_level]
                pending.clear()
                # Older inventory is offered first at the nearer recovery
                # centre; a second lot may use the first upper recovery level.
                unsold = sorted(
                    (lot for lot in lots if not lot.sold),
                    key=lambda lot: lot.buy_offset,
                )
                for number, lot in enumerate(unsold):
                    lot.target_vnd = (
                        round_to_hsx_tick(center1, "sell")
                        if number == 0 else upper_target
                    )

        if state in ("ACTIVE", "RECOVERY"):
            for level in list(active_levels):
                if level.level_id not in pending:
                    continue
                pending.remove(level.level_id)
                if offset > config.maximum_horizon - config.settlement_sessions:
                    purchased.add(level.level_id)
                    continue
                if bar.open_vnd > level.target_vnd:
                    purchased.add(level.level_id)
                    continue
                current_inventory = sum(
                    lot.quantity for lot in lots if not lot.sold
                )
                if current_inventory + level.quantity > config.maximum_inventory:
                    purchased.add(level.level_id)
                    continue
                if (
                    level.level_id == "recovery"
                    and not recovery_stress_ok(
                        lots, bar.open_vnd, active_hard_lower, config
                    )
                ):
                    recovery_stress_cancelled = True
                    purchased.add(level.level_id)
                    continue
                lots.append(make_lot(level, offset, bar.open_vnd, config))
                purchased.add(level.level_id)
                recovery_filled = recovery_filled or level.level_id == "recovery"

        if bar.open_vnd <= active_hard_lower:
            risk_price = bar.open_vnd
            risk_exit = True
        elif bar.low_vnd <= active_hard_lower:
            risk_price = active_hard_lower
            risk_exit = True
        else:
            risk_price = 0
        if risk_exit:
            state = "SHUTDOWN"
            pending.clear()
            for lot in lots:
                if not lot.sold and offset >= lot.buy_offset + config.settlement_sessions:
                    sell(lot, risk_price, "risk_exit")
            if all(lot.sold for lot in lots):
                break
            continue

        for lot in lots:
            if (
                not lot.sold
                and offset >= lot.buy_offset + config.settlement_sessions
                and bar.high_vnd >= lot.target_vnd
            ):
                sell(lot, lot.target_vnd, "target")

        if (
            enable_reanchor
            and state == "ACTIVE"
            and bar.close_vnd < lower0
        ):
            state = "RECOVERY_WAIT"
            breach_index = global_index
            lower_breached = True
            pending.clear()

        if state in ("ACTIVE", "RECOVERY"):
            for level in active_levels:
                if (
                    level.level_id not in purchased
                    and level.level_id not in pending
                    and bar.low_vnd <= level.buy_vnd
                    and bar.close_vnd > level.buy_vnd
                    and bar.close_vnd > bar.open_vnd
                ):
                    pending.add(level.level_id)

        maximum_inventory = max(
            maximum_inventory,
            sum(lot.quantity for lot in lots if not lot.sold),
        )
        if offset == config.maximum_horizon:
            time_exit = any(not lot.sold for lot in lots)
            for lot in lots:
                if not lot.sold:
                    sell(lot, bar.close_vnd, "time_exit")

    pnl = sum(
        sale_cash(lot.sale_price_vnd, lot.quantity, config)
        - lot.acquisition_vnd for lot in lots
    )
    double_pnl = sum(
        sale_cash(lot.sale_price_vnd, lot.quantity, config, 2.0)
        - lot.double_acquisition_vnd for lot in lots
    )
    normal_gain = sum(
        max(
            sale_cash(lot.sale_price_vnd, lot.quantity, config)
            - lot.acquisition_vnd,
            0,
        )
        for lot in lots if lot.sale_reason == "target"
    )
    other_loss = -sum(
        min(
            sale_cash(lot.sale_price_vnd, lot.quantity, config)
            - lot.acquisition_vnd,
            0,
        )
        for lot in lots if lot.sale_reason != "target"
    )
    return {
        "executed": bool(lots),
        "net_pnl_vnd": pnl,
        "double_pnl_vnd": double_pnl,
        "profit_target_sales": sum(lot.sale_reason == "target" for lot in lots),
        "normal_target_gain_vnd": normal_gain,
        "other_loss_vnd": other_loss,
        "risk_exit": risk_exit,
        "time_exit": time_exit,
        "max_inventory": maximum_inventory,
        "lower_bound_breached": lower_breached,
        "reanchored": reanchored,
        "recovery_lot_filled": recovery_filled,
        "reanchor_stress_cancelled": recovery_stress_cancelled,
    }


def activation_rows(
    folds: Sequence[trial6.Fold],
    daily: dict[str, list[trial6.DailyBar]],
    calendar: Sequence[date],
    config: Config,
) -> list[dict[str, object]]:
    indices = {value: index for index, value in enumerate(calendar)}
    signal_config = replace(
        trial6.Config(), candidate_residual_z_max=config.residual_z_max
    )
    candidates: list[dict[str, object]] = []
    for fold in folds:
        allowed = set(fold.oos_dates)
        for signal_date in fold.oos_dates:
            index = indices[signal_date]
            scheduled_end = index + 1 + config.maximum_horizon
            if (
                scheduled_end >= len(calendar)
                or calendar[scheduled_end] not in allowed
            ):
                continue
            for ticker in TICKERS:
                features, reasons = trial6.feature_vector(
                    ticker, index, daily, signal_config
                )
                if features is None or reasons:
                    continue
                bars = daily[ticker]
                close_up = bars[index].close_vnd > bars[index - 1].close_vnd
                ticker_return10 = (
                    bars[index].close_vnd / bars[index - 10].close_vnd - 1
                )
                if not (
                    float(features["residual_z5"]) <= config.residual_z_max
                    and (float(features["residual_1"]) > 0 or close_up)
                    and float(features["market_return5"])
                    > config.market_downtrend_return5
                    and ticker_return10 > config.ticker_downtrend_return10
                ):
                    continue
                candidates.append({
                    "trial_id": TRIAL_ID,
                    "fold_id": fold.fold_id,
                    "ticker": ticker,
                    "sector": trial6.SECTOR_BY_TICKER[ticker],
                    "signal_date": signal_date.isoformat(),
                    "entry_date": calendar[index + 1].isoformat(),
                    "scheduled_end": calendar[scheduled_end].isoformat(),
                    "signal_index": index,
                    "residual_z5": features["residual_z5"],
                    "residual_1": features["residual_1"],
                })
    # Fixed-horizon portfolio selection, independent of either future result.
    by_entry: dict[date, list[dict[str, object]]] = defaultdict(list)
    for row in candidates:
        by_entry[date.fromisoformat(str(row["entry_date"]))].append(row)
    active: list[dict[str, object]] = []
    cooldown: dict[str, int] = {}
    selected: list[dict[str, object]] = []
    for entry_date in sorted(by_entry):
        current = indices[entry_date]
        active = [
            row for row in active
            if date.fromisoformat(str(row["scheduled_end"])) >= entry_date
        ]
        tickers = {str(row["ticker"]) for row in active}
        sectors = {str(row["sector"]) for row in active}
        available = config.maximum_concurrent - len(active)
        for row in sorted(
            by_entry[entry_date],
            key=lambda item: (
                float(item["residual_z5"]),
                -float(item["residual_1"]),
                str(item["ticker"]),
            ),
        ):
            ticker, sector = str(row["ticker"]), str(row["sector"])
            if available <= 0:
                break
            if ticker in tickers or sector in sectors:
                continue
            if current <= cooldown.get(ticker, -1):
                continue
            selected.append(row)
            active.append(row)
            tickers.add(ticker)
            sectors.add(sector)
            cooldown[ticker] = (
                indices[date.fromisoformat(str(row["scheduled_end"]))]
                + config.cooldown_sessions
            )
            available -= 1
    return selected


def profit_factor(values: Sequence[int]) -> float | str | None:
    gains = sum(value for value in values if value > 0)
    losses = -sum(value for value in values if value < 0)
    if losses == 0:
        return "Infinity" if gains else None
    return gains / losses


def summarize(rows: Sequence[dict[str, object]]) -> dict[str, object]:
    paired = [
        row for row in rows
        if bool(row["control_executed"]) or bool(row["reanchor_executed"])
    ]
    control = [int(row["control_net_pnl_vnd"]) for row in paired]
    recovery = [int(row["reanchor_net_pnl_vnd"]) for row in paired]
    recovery_double = [int(row["reanchor_double_pnl_vnd"]) for row in paired]
    improvements = [
        int(row["paired_improvement_vnd"]) for row in paired
    ]
    recovery_target = sum(
        int(row["reanchor_normal_target_gain_vnd"]) for row in rows
    )
    recovery_other = sum(
        int(row["reanchor_other_loss_vnd"]) for row in rows
    )
    pf = profit_factor(recovery)
    gates = {
        "at_least_20_paired_campaigns": len(paired) >= 20,
        "improves_total_pnl": sum(recovery) > sum(control),
        "positive_total_pnl": sum(recovery) > 0,
        "positive_median_pnl": bool(recovery) and statistics.median(recovery) > 0,
        "profit_factor_at_least_1_20": (
            pf == "Infinity" or isinstance(pf, float) and pf >= 1.2
        ),
        "positive_doubled_cost_pnl": sum(recovery_double) > 0,
        "target_gains_cover_other_losses": recovery_target >= recovery_other,
        "positive_after_best_removed": (
            bool(recovery) and sum(recovery) - max(recovery) > 0
        ),
        "worst_loss_within_1_5pct_nav": (
            bool(recovery) and min(recovery) >= -1_500_000
        ),
    }
    return {
        "trial_id": TRIAL_ID,
        "status": (
            "exploratory_preferred"
            if all(gates.values()) else "exploratory_not_preferred"
        ),
        "independent_validation": False,
        "live_authorization": False,
        "final_test_used": False,
        "gates": gates,
        "metrics": {
            "selected_activations": len(rows),
            "paired_executed_campaigns": len(paired),
            "control_total_pnl_vnd": sum(control),
            "reanchor_total_pnl_vnd": sum(recovery),
            "paired_total_improvement_vnd": sum(improvements),
            "campaigns_improved": sum(value > 0 for value in improvements),
            "control_profit_factor": profit_factor(control),
            "reanchor_profit_factor": pf,
            "reanchor_median_pnl_vnd": (
                statistics.median(recovery) if recovery else None
            ),
            "reanchor_double_cost_pnl_vnd": sum(recovery_double),
            "lower_bound_breaches": sum(bool(row["lower_bound_breached"]) for row in rows),
            "successful_reanchors": sum(bool(row["reanchored"]) for row in rows),
            "recovery_lots_filled": sum(bool(row["recovery_lot_filled"]) for row in rows),
            "reanchor_stress_cancellations": sum(
                bool(row["reanchor_stress_cancelled"]) for row in rows
            ),
            "reanchor_target_gains_vnd": recovery_target,
            "reanchor_other_losses_vnd": recovery_other,
            "reanchor_worst_pnl_vnd": min(recovery) if recovery else None,
            "reanchor_best_removed_pnl_vnd": (
                sum(recovery) - max(recovery) if recovery else 0
            ),
            "reanchor_maximum_inventory": max(
                (int(row["reanchor_max_inventory"]) for row in rows),
                default=0,
            ),
        },
    }


def run(output_dir: Path) -> dict[str, object]:
    config = Config()
    daily, calendar, final_range = trial6.read_development_daily(
        Path("data_algotradeDB_split.csv"), TICKERS
    )
    folds = trial6.read_folds(
        Path("data/trial5_splits_rotation/walk_forward_date_assignments.csv")
    )
    activations = activation_rows(folds, daily, calendar, config)
    paired_rows: list[dict[str, object]] = []
    for activation in activations:
        ticker = str(activation["ticker"])
        signal_index = int(activation["signal_index"])
        control = simulate(
            ticker, signal_index, daily, config, enable_reanchor=False
        )
        recovery = simulate(
            ticker, signal_index, daily, config, enable_reanchor=True
        )
        if control is None or recovery is None:
            continue
        paired_rows.append({
            **activation,
            "control_executed": control["executed"],
            "control_net_pnl_vnd": control["net_pnl_vnd"],
            "control_double_pnl_vnd": control["double_pnl_vnd"],
            "control_profit_target_sales": control["profit_target_sales"],
            "control_normal_target_gain_vnd": control["normal_target_gain_vnd"],
            "control_other_loss_vnd": control["other_loss_vnd"],
            "control_risk_exit": control["risk_exit"],
            "control_time_exit": control["time_exit"],
            "control_max_inventory": control["max_inventory"],
            "reanchor_executed": recovery["executed"],
            "reanchor_net_pnl_vnd": recovery["net_pnl_vnd"],
            "reanchor_double_pnl_vnd": recovery["double_pnl_vnd"],
            "reanchor_profit_target_sales": recovery["profit_target_sales"],
            "reanchor_normal_target_gain_vnd": recovery["normal_target_gain_vnd"],
            "reanchor_other_loss_vnd": recovery["other_loss_vnd"],
            "reanchor_risk_exit": recovery["risk_exit"],
            "reanchor_time_exit": recovery["time_exit"],
            "reanchor_max_inventory": recovery["max_inventory"],
            "lower_bound_breached": recovery["lower_bound_breached"],
            "reanchored": recovery["reanchored"],
            "recovery_lot_filled": recovery["recovery_lot_filled"],
            "reanchor_stress_cancelled": recovery["reanchor_stress_cancelled"],
            "paired_improvement_vnd": (
                int(recovery["net_pnl_vnd"]) - int(control["net_pnl_vnd"])
            ),
        })
    report = summarize(paired_rows)
    report["final_test_range_detected_but_not_parsed"] = [
        final_range[0].isoformat(), final_range[1].isoformat()
    ]
    report["config"] = config.__dict__
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "paired_campaigns.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(
            handle, fieldnames=PAIRED_FIELDS, extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(paired_rows)
    (output_dir / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir", type=Path,
        default=Path("data/trial10_single_reanchor"),
    )
    args = parser.parse_args()
    print(json.dumps(run(args.output_dir), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
