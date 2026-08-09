#!/usr/bin/env python3
"""Exploratory dynamic-bound, inventory-aware multi-level grid."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Sequence

import study_trial6_mean_reversion as trial6
import study_trial7_episodic_grid as trial7
from study_trial5_rotation_grid import round_to_hsx_tick


TRIAL_ID = "TRIAL9-DYNAMIC-INVENTORY-AWARE-GRID"
ACCOUNT_NAV_VND = 100_000_000
TICKERS = trial6.TICKERS


@dataclass(frozen=True)
class Config:
    center_sessions: int = 20
    atr_sessions: int = 20
    range_atr: float = 2.0
    buffer_atr: float = 0.75
    total_grid_intervals: int = 6
    buy_levels: int = 3
    quantity_growth: float = 1.5
    inventory_skew: float = 0.5
    board_lot: int = 100
    maximum_inventory_shares: int = 600
    stress_budget_fraction: float = 0.015
    maximum_horizon: int = 15
    settlement_sessions: int = 2
    residual_z_max: float = -0.50
    market_downtrend_return5: float = -0.05
    ticker_deep_downtrend_return10: float = -0.08
    residual_breakdown_z: float = -2.0
    cooldown_sessions: int = 5
    maximum_concurrent: int = 3
    commission_rate: float = 0.0015
    sell_tax_rate: float = 0.0010
    execution_haircut: float = 0.0005


@dataclass(frozen=True)
class GridLevel:
    level_id: int
    distance: int
    buy_vnd: int
    target_vnd: int
    base_quantity: int


@dataclass
class Lot:
    level_id: int
    distance: int
    quantity: int
    buy_offset: int
    buy_price_vnd: int
    target_vnd: int
    acquisition_vnd: int
    double_acquisition_vnd: int
    sold: bool = False
    sale_price_vnd: int = 0
    sale_reason: str = ""


RESULT_FIELDS = (
    "trial_id", "fold_id", "ticker", "sector", "signal_date", "entry_date",
    "exit_date", "residual_z5", "residual_1", "center_vnd", "lower_vnd",
    "upper_vnd", "hard_lower_vnd", "grid_ratio", "selected", "selection_rank",
    "executed", "buy_count", "sell_count", "target_sale_count",
    "maximum_inventory_shares", "maximum_inventory_notional_vnd",
    "distance_0_bought_shares", "distance_1_bought_shares",
    "distance_2_bought_shares", "stress_reduced_orders",
    "stress_cancelled_orders", "deep_trend_shutdown", "buffer_shutdown",
    "gap_shutdown", "time_exit", "normal_target_gain_vnd",
    "risk_time_loss_vnd", "net_pnl_vnd", "double_cost_net_pnl_vnd",
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


def build_grid(
    bars: Sequence[trial6.DailyBar], signal_index: int, config: Config
) -> tuple[float, int, int, int, float, list[GridLevel]]:
    history = bars[signal_index - config.center_sessions + 1:signal_index + 1]
    center = sum(bar.close_vnd for bar in history) / len(history)
    atr_history = bars[signal_index - config.atr_sessions:signal_index + 1]
    atr_value = trial6.atr(atr_history)
    lower_raw = center - config.range_atr * atr_value
    upper_raw = center + config.range_atr * atr_value
    if lower_raw <= 0 or upper_raw <= lower_raw:
        raise ValueError("Invalid dynamic range")
    lower = round_to_hsx_tick(lower_raw, "buy")
    upper = round_to_hsx_tick(upper_raw, "sell")
    hard_lower = round_to_hsx_tick(
        lower_raw - config.buffer_atr * atr_value, "sell"
    )
    ratio = (upper / lower) ** (1 / config.total_grid_intervals) - 1
    raw_grid = [
        lower * ((1 + ratio) ** index)
        for index in range(config.total_grid_intervals + 1)
    ]
    grid = [
        round_to_hsx_tick(value, "buy" if value < center else "sell")
        for value in raw_grid
    ]
    below = [index for index, value in enumerate(grid[:-1]) if value < center]
    selected_indices = below[-config.buy_levels:]
    levels: list[GridLevel] = []
    for distance, grid_index in enumerate(reversed(selected_indices)):
        lots = math.ceil(config.quantity_growth ** distance)
        levels.append(GridLevel(
            level_id=grid_index,
            distance=distance,
            buy_vnd=grid[grid_index],
            target_vnd=round_to_hsx_tick(grid[grid_index + 1], "sell"),
            base_quantity=lots * config.board_lot,
        ))
    return center, lower, upper, hard_lower, ratio, levels


def inventory_adjusted_quantity(
    base_quantity: int,
    current_quantity: int,
    lots: Sequence[Lot],
    prospective_price: int,
    hard_lower: int,
    config: Config,
) -> tuple[int, bool, bool]:
    inventory = current_quantity / config.maximum_inventory_shares
    raw = base_quantity * (1 - config.inventory_skew * inventory)
    quantity = int(math.floor(raw / config.board_lot + 0.5)) * config.board_lot
    quantity = min(quantity, config.maximum_inventory_shares - current_quantity)
    reduced = quantity < base_quantity
    budget = round(ACCOUNT_NAV_VND * config.stress_budget_fraction)
    while quantity >= config.board_lot:
        stressed_loss = sum(
            max(
                lot.acquisition_vnd
                - sale_cash(hard_lower, lot.quantity, config),
                0,
            )
            for lot in lots if not lot.sold
        )
        stressed_loss += max(
            acquisition(prospective_price, quantity, config)
            - sale_cash(hard_lower, quantity, config),
            0,
        )
        if stressed_loss <= budget:
            return quantity, reduced or quantity < base_quantity, False
        quantity -= config.board_lot
        reduced = True
    return 0, True, True


def sell(lot: Lot, price: int, reason: str) -> None:
    lot.sold = True
    lot.sale_price_vnd = price
    lot.sale_reason = reason


def deep_trend(
    ticker: str,
    prior_index: int,
    daily: dict[str, list[trial6.DailyBar]],
    config: Config,
) -> tuple[bool, dict[str, float] | None]:
    if prior_index < 60:
        return True, None
    feature_config = replace(trial6.Config(), candidate_residual_z_max=100.0)
    features, reasons = trial6.feature_vector(
        ticker, prior_index, daily, feature_config
    )
    if features is None or any(
        reason not in ("residual_not_low_enough",) for reason in reasons
    ):
        return True, features
    bars = daily[ticker]
    return (
        bars[prior_index].close_vnd / bars[prior_index - 10].close_vnd - 1
        <= config.ticker_deep_downtrend_return10
        or float(features["market_return5"]) <= config.market_downtrend_return5
        or (
            float(features["residual_z5"]) <= config.residual_breakdown_z
            and float(features["residual_1"]) < 0
        )
    ), features


def simulate(
    ticker: str,
    signal_index: int,
    daily: dict[str, list[trial6.DailyBar]],
    config: Config,
) -> dict[str, object] | None:
    bars = daily[ticker]
    entry_index = signal_index + 1
    end_index = entry_index + config.maximum_horizon
    if end_index >= len(bars):
        return None
    path = bars[entry_index:end_index + 1]
    if any(not bar.reset_verifiable or bar.reference_reset for bar in path):
        return None
    center, lower, upper, hard_lower, ratio, levels = build_grid(
        bars, signal_index, config
    )
    pending: set[int] = set()
    purchased: set[int] = set()
    lots: list[Lot] = []
    shutdown = False
    deep_shutdown = False
    buffer_shutdown = False
    gap_shutdown = False
    time_exit = False
    stress_reduced = 0
    stress_cancelled = 0
    maximum_shares = 0
    maximum_notional = 0
    distance_shares = defaultdict(int)
    final_offset = config.maximum_horizon

    for offset, bar in enumerate(path):
        prior_index = entry_index + offset - 1
        trend_stop, _ = deep_trend(ticker, prior_index, daily, config)
        if trend_stop:
            shutdown = deep_shutdown = True
        if bars[prior_index].close_vnd < hard_lower:
            shutdown = buffer_shutdown = True

        if not shutdown:
            for level in sorted(
                (item for item in levels if item.level_id in pending),
                key=lambda item: item.distance,
            ):
                if bar.open_vnd > level.target_vnd:
                    pending.remove(level.level_id)
                    continue
                current = sum(lot.quantity for lot in lots if not lot.sold)
                quantity, reduced, cancelled = inventory_adjusted_quantity(
                    level.base_quantity, current, lots, bar.open_vnd,
                    hard_lower, config,
                )
                stress_reduced += int(reduced)
                stress_cancelled += int(cancelled)
                pending.remove(level.level_id)
                purchased.add(level.level_id)
                if quantity == 0:
                    continue
                lots.append(Lot(
                    level.level_id, level.distance, quantity, offset,
                    bar.open_vnd, level.target_vnd,
                    acquisition(bar.open_vnd, quantity, config),
                    acquisition(bar.open_vnd, quantity, config, 2.0),
                ))
                distance_shares[level.distance] += quantity

        if bar.open_vnd <= hard_lower:
            shutdown = buffer_shutdown = gap_shutdown = True
            risk_price = bar.open_vnd
        elif bar.low_vnd <= hard_lower:
            shutdown = buffer_shutdown = True
            risk_price = hard_lower
        else:
            risk_price = 0

        if shutdown:
            for lot in lots:
                if not lot.sold and offset >= lot.buy_offset + config.settlement_sessions:
                    sell(lot, risk_price or bar.open_vnd, "risk_exit")
            if not lots or all(lot.sold for lot in lots):
                final_offset = offset
                break
            maximum_shares = max(
                maximum_shares, sum(lot.quantity for lot in lots if not lot.sold)
            )
            continue

        for lot in lots:
            if (
                not lot.sold
                and offset >= lot.buy_offset + config.settlement_sessions
                and bar.high_vnd >= lot.target_vnd
            ):
                sell(lot, lot.target_vnd, "target")

        for level in levels:
            if (
                level.level_id not in purchased
                and level.level_id not in pending
                and bar.low_vnd <= level.buy_vnd
                and bar.close_vnd > level.buy_vnd
                and bar.close_vnd > bar.open_vnd
            ):
                pending.add(level.level_id)

        open_quantity = sum(lot.quantity for lot in lots if not lot.sold)
        maximum_shares = max(maximum_shares, open_quantity)
        maximum_notional = max(maximum_notional, open_quantity * bar.close_vnd)

        if offset == config.maximum_horizon:
            time_exit = any(not lot.sold for lot in lots)
            for lot in lots:
                if not lot.sold:
                    sell(lot, bar.close_vnd, "time_exit")

    if not lots:
        net_pnl = double_pnl = normal_gain = other_pnl = 0
    else:
        net_pnl = sum(
            sale_cash(lot.sale_price_vnd, lot.quantity, config)
            - lot.acquisition_vnd for lot in lots
        )
        double_pnl = sum(
            sale_cash(lot.sale_price_vnd, lot.quantity, config, 2.0)
            - lot.double_acquisition_vnd for lot in lots
        )
        normal_gain = sum(
            sale_cash(lot.sale_price_vnd, lot.quantity, config)
            - lot.acquisition_vnd
            for lot in lots if lot.sale_reason == "target"
        )
        other_pnl = sum(
            sale_cash(lot.sale_price_vnd, lot.quantity, config)
            - lot.acquisition_vnd
            for lot in lots if lot.sale_reason != "target"
        )
    return {
        "entry_date": path[0].trading_date.isoformat(),
        "exit_date": path[final_offset].trading_date.isoformat(),
        "center_vnd": round(center),
        "lower_vnd": lower,
        "upper_vnd": upper,
        "hard_lower_vnd": hard_lower,
        "grid_ratio": ratio,
        "executed": bool(lots),
        "buy_count": len(lots),
        "sell_count": sum(lot.sold for lot in lots),
        "target_sale_count": sum(lot.sale_reason == "target" for lot in lots),
        "maximum_inventory_shares": maximum_shares,
        "maximum_inventory_notional_vnd": maximum_notional,
        "distance_0_bought_shares": distance_shares[0],
        "distance_1_bought_shares": distance_shares[1],
        "distance_2_bought_shares": distance_shares[2],
        "stress_reduced_orders": stress_reduced,
        "stress_cancelled_orders": stress_cancelled,
        "deep_trend_shutdown": deep_shutdown,
        "buffer_shutdown": buffer_shutdown,
        "gap_shutdown": gap_shutdown,
        "time_exit": time_exit,
        "normal_target_gain_vnd": max(normal_gain, 0),
        "risk_time_loss_vnd": min(other_pnl, 0),
        "net_pnl_vnd": net_pnl,
        "double_cost_net_pnl_vnd": double_pnl,
    }


def activation_candidates(
    folds: Sequence[trial6.Fold],
    daily: dict[str, list[trial6.DailyBar]],
    calendar: Sequence[date],
    config: Config,
) -> list[dict[str, object]]:
    indices = {value: index for index, value in enumerate(calendar)}
    feature_config = replace(
        trial6.Config(), candidate_residual_z_max=config.residual_z_max
    )
    rows: list[dict[str, object]] = []
    for fold in folds:
        allowed = set(fold.oos_dates)
        for signal_date in fold.oos_dates:
            index = indices[signal_date]
            if (
                index + 1 + config.maximum_horizon >= len(calendar)
                or calendar[index + 1 + config.maximum_horizon] not in allowed
            ):
                continue
            for ticker in TICKERS:
                features, reasons = trial6.feature_vector(
                    ticker, index, daily, feature_config
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
                    and ticker_return10
                    > config.ticker_deep_downtrend_return10
                ):
                    continue
                result = simulate(ticker, index, daily, config)
                if result is None:
                    continue
                rows.append({
                    "trial_id": TRIAL_ID,
                    "fold_id": fold.fold_id,
                    "ticker": ticker,
                    "sector": trial6.SECTOR_BY_TICKER[ticker],
                    "signal_date": signal_date.isoformat(),
                    "residual_z5": features["residual_z5"],
                    "residual_1": features["residual_1"],
                    "selected": False,
                    "selection_rank": "",
                    **result,
                })
    return rows


def select_campaigns(
    rows: list[dict[str, object]], calendar: Sequence[date], config: Config
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
        active_sectors = {str(row["sector"]) for row in active}
        available = config.maximum_concurrent - len(active)
        ranked = sorted(
            by_entry[entry_date],
            key=lambda row: (
                float(row["residual_z5"]),
                -float(row["residual_1"]),
                str(row["ticker"]),
            ),
        )
        rank = 0
        for row in ranked:
            if available <= 0:
                break
            ticker, sector = str(row["ticker"]), str(row["sector"])
            if ticker in active_tickers or sector in active_sectors:
                continue
            if current <= cooldown.get(ticker, -1):
                continue
            rank += 1
            row["selected"] = True
            row["selection_rank"] = rank
            selected.append(row)
            active.append(row)
            active_tickers.add(ticker)
            active_sectors.add(sector)
            cooldown[ticker] = (
                indices[date.fromisoformat(str(row["exit_date"]))]
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


def evaluate(
    candidates: Sequence[dict[str, object]],
    selected: Sequence[dict[str, object]],
) -> dict[str, object]:
    executed = [row for row in selected if bool(row["executed"])]
    pnls = [int(row["net_pnl_vnd"]) for row in executed]
    doubled = [int(row["double_cost_net_pnl_vnd"]) for row in executed]
    normal = sum(int(row["normal_target_gain_vnd"]) for row in executed)
    other_losses = -sum(int(row["risk_time_loss_vnd"]) for row in executed)
    distance_pnl: dict[int, int] = {}
    # Campaign P&L cannot be uniquely attributed when several levels coexist;
    # report campaign P&L conditional on each distance being used.
    for distance in range(3):
        distance_pnl[distance] = sum(
            int(row["net_pnl_vnd"]) for row in executed
            if int(row[f"distance_{distance}_bought_shares"]) > 0
        )
    economic = {
        "enough_executed_campaigns": len(executed) >= 30,
        "positive_total_pnl": sum(pnls) > 0,
        "positive_median_pnl": bool(pnls) and statistics.median(pnls) > 0,
        "profit_factor_at_least_1_20": (
            profit_factor(pnls) == "Infinity"
            or isinstance(profit_factor(pnls), float)
            and float(profit_factor(pnls)) >= 1.2
        ),
        "positive_doubled_cost_pnl": sum(doubled) > 0,
        "positive_after_best_removed": bool(pnls) and sum(pnls) - max(pnls) > 0,
        "target_gains_cover_other_losses": normal >= other_losses,
        "worst_loss_within_1_5pct_nav": (
            bool(pnls) and min(pnls) >= -1_500_000
        ),
        "farther_level_campaigns_profitable": distance_pnl[2] > 0,
    }
    return {
        "trial_id": TRIAL_ID,
        "status": (
            "exploratory_viable"
            if all(economic.values())
            else "exploratory_not_viable"
        ),
        "independent_validation": False,
        "live_authorization": False,
        "final_test_used": False,
        "gates": economic,
        "metrics": {
            "activation_candidates": len(candidates),
            "selected_campaigns": len(selected),
            "executed_campaigns": len(executed),
            "total_net_pnl_vnd": sum(pnls),
            "median_net_pnl_vnd": statistics.median(pnls) if pnls else None,
            "profit_factor": profit_factor(pnls),
            "double_cost_total_pnl_vnd": sum(doubled),
            "best_removed_total_pnl_vnd": sum(pnls) - max(pnls) if pnls else 0,
            "normal_target_gains_vnd": normal,
            "risk_time_losses_vnd": other_losses,
            "worst_campaign_pnl_vnd": min(pnls) if pnls else None,
            "target_sales": sum(int(row["target_sale_count"]) for row in executed),
            "deep_trend_shutdowns": sum(bool(row["deep_trend_shutdown"]) for row in selected),
            "buffer_shutdowns": sum(bool(row["buffer_shutdown"]) for row in selected),
            "stress_reduced_orders": sum(int(row["stress_reduced_orders"]) for row in executed),
            "stress_cancelled_orders": sum(int(row["stress_cancelled_orders"]) for row in executed),
            "maximum_inventory_shares": max(
                (int(row["maximum_inventory_shares"]) for row in executed),
                default=0,
            ),
            "distance_conditional_campaign_pnl_vnd": distance_pnl,
            "ticker_pnl_vnd": dict(sorted(_group_pnl(executed, "ticker").items())),
        },
    }


def _group_pnl(
    rows: Sequence[dict[str, object]], field: str
) -> dict[str, int]:
    result: dict[str, int] = defaultdict(int)
    for row in rows:
        result[str(row[field])] += int(row["net_pnl_vnd"])
    return result


def write_csv(path: Path, rows: Sequence[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def run(output_dir: Path) -> dict[str, object]:
    config = Config()
    daily, calendar, final_range = trial6.read_development_daily(
        Path("data_algotradeDB_split.csv"), TICKERS
    )
    folds = trial6.read_folds(
        Path("data/trial5_splits_rotation/walk_forward_date_assignments.csv")
    )
    candidates = activation_candidates(folds, daily, calendar, config)
    selected = select_campaigns(candidates, calendar, config)
    report = evaluate(candidates, selected)
    report["final_test_range_detected_but_not_parsed"] = [
        final_range[0].isoformat(), final_range[1].isoformat()
    ]
    report["config"] = config.__dict__
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "activation_candidates.csv", candidates)
    write_csv(output_dir / "selected_campaigns.csv", selected)
    (output_dir / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir", type=Path,
        default=Path("data/trial9_dynamic_inventory_grid"),
    )
    args = parser.parse_args()
    print(json.dumps(run(args.output_dir), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
