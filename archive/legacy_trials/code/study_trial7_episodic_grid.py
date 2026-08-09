#!/usr/bin/env python3
"""Trial 7 daily Stage-A confirmed episodic grid study."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
import tempfile
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Sequence

import study_trial6_mean_reversion as trial6
from study_trial5_rotation_grid import round_to_hsx_tick


TRIAL_ID = "TRIAL7-HSX-CONFIRMED-EPISODIC-GRID"
SCHEMA_VERSION = "trial7.v1"
TICKERS = trial6.TICKERS
SECTOR_BY_TICKER = trial6.SECTOR_BY_TICKER
FROZEN_CONFIG_SHA256 = (
    "9b0ea04549f7a1829a6502ae153dd2b5dc3ca4598f09a7a05d36ffa9c197bbbf"
)

CANDIDATE_FIELDS = (
    "trial_id", "fold_id", "ticker", "sector", "signal_date", "entry_date",
    "exit_date", "residual_z5", "residual_1", "market_return5",
    "atr20_fraction", "grid_step_fraction", "initial_buy_vnd",
    "initial_target_vnd", "lower_buy_vnd", "lower_target_vnd",
    "hard_lower_vnd", "lower_level_filled", "target_sale_count",
    "risk_exit", "gap_risk_exit", "time_exit", "buy_count", "sell_count",
    "normal_target_gain_vnd", "risk_time_loss_vnd", "net_pnl_vnd",
    "net_return", "double_cost_net_pnl_vnd", "double_cost_net_return",
    "selected", "selection_rank",
)
QUARANTINE_FIELDS = (
    "trial_id", "fold_id", "ticker", "signal_date", "entry_date", "reason",
    "reset_dates",
)
FOLD_FIELDS = (
    "trial_id", "fold_id", "valid", "candidate_count", "selected_episodes",
    "target_sales", "lower_level_fills", "net_pnl_vnd",
    "double_cost_net_pnl_vnd",
)


@dataclass(frozen=True)
class Config:
    universe: tuple[str, ...] = TICKERS
    residual_z_max: float = -0.75
    minimum_residual_rebound: float = 0.0
    minimum_market_return5: float = -0.05
    minimum_grid_step: float = 0.015
    maximum_grid_step: float = 0.030
    hard_lower_steps: int = 3
    maximum_horizon: int = 15
    quantity_per_level: int = 100
    maximum_levels: int = 2
    settlement_sessions: int = 2
    commission_rate: float = 0.0015
    sell_tax_rate: float = 0.0010
    execution_haircut: float = 0.0005
    doubled_cost_multiplier: float = 2.0
    maximum_concurrent_campaigns: int = 3
    cooldown_sessions: int = 5
    minimum_valid_folds: int = 15
    minimum_candidates: int = 75
    minimum_selected_episodes: int = 40
    minimum_target_sales: int = 15
    minimum_years: int = 3
    minimum_episodes_per_year: int = 5
    maximum_year_fraction: float = 0.55
    minimum_profit_factor: float = 1.20
    minimum_positive_active_fold_fraction: float = 0.60
    maximum_ticker_positive_pnl_fraction: float = 0.40

    def validate(self) -> None:
        if self.universe != TICKERS:
            raise ValueError("Trial 7 universe is frozen")
        if self.maximum_levels != 2 or self.quantity_per_level != 100:
            raise ValueError("Trial 7 uses two equal 100-share levels")
        if self.maximum_horizon != 15 or self.settlement_sessions != 2:
            raise ValueError("Trial 7 horizon and settlement are frozen")
        digest = trial6.sha256_bytes(trial6.canonical_json(asdict(self)))
        if FROZEN_CONFIG_SHA256 != "TO_BE_FROZEN" and digest != FROZEN_CONFIG_SHA256:
            raise ValueError("Trial 7 configuration differs from frozen v1")


@dataclass
class Lot:
    level: int
    buy_offset: int
    buy_price_vnd: int
    target_vnd: int
    acquisition_vnd: int
    double_acquisition_vnd: int
    sold: bool = False
    sale_price_vnd: int = 0
    sale_reason: str = ""
    sale_offset: int = 0


def acquisition_cash(price_vnd: int, config: Config, multiplier: float = 1.0) -> int:
    execution = round(price_vnd * (1 + config.execution_haircut * multiplier))
    notional = execution * config.quantity_per_level
    return notional + round(notional * config.commission_rate * multiplier)


def net_sale_cash(price_vnd: int, config: Config, multiplier: float = 1.0) -> int:
    execution = round(price_vnd * (1 - config.execution_haircut * multiplier))
    notional = execution * config.quantity_per_level
    return (
        notional
        - round(notional * config.commission_rate * multiplier)
        - round(notional * config.sell_tax_rate * multiplier)
    )


def make_lot(
    level: int, offset: int, buy_price: int, target: int, config: Config
) -> Lot:
    return Lot(
        level, offset, buy_price, target,
        acquisition_cash(buy_price, config),
        acquisition_cash(buy_price, config, config.doubled_cost_multiplier),
    )


def sell_lot(lot: Lot, price: int, reason: str, offset: int) -> None:
    lot.sold = True
    lot.sale_price_vnd = price
    lot.sale_reason = reason
    lot.sale_offset = offset


def simulate_episode(
    bars: Sequence[trial6.DailyBar],
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
    step = min(max(atr_fraction, config.minimum_grid_step), config.maximum_grid_step)
    initial_buy = path[0].open_vnd
    initial_target = round_to_hsx_tick(initial_buy * (1 + step), "sell")
    lower_buy = round_to_hsx_tick(initial_buy / (1 + step), "buy")
    lower_target = round_to_hsx_tick(initial_buy, "sell")
    hard_lower = round_to_hsx_tick(
        initial_buy / ((1 + step) ** config.hard_lower_steps), "sell"
    )
    lots = [make_lot(0, 0, initial_buy, initial_target, config)]
    lower_filled = False
    lower_reclaim_pending = False
    shutdown = False
    gap_risk = False
    risk_price = 0
    risk_trigger_offset = -1
    final_offset = config.maximum_horizon
    final_reason = "time_exit"

    for offset, bar in enumerate(path):
        if shutdown:
            for lot in lots:
                if not lot.sold and offset >= lot.buy_offset + config.settlement_sessions:
                    sell_lot(lot, bar.open_vnd, "locked_risk_exit", offset)
            if all(lot.sold for lot in lots):
                final_offset, final_reason = offset, "risk_exit"
                break
            continue

        if bar.open_vnd <= hard_lower:
            shutdown, gap_risk = True, True
            risk_price, risk_trigger_offset = bar.open_vnd, offset
        elif bar.low_vnd <= hard_lower:
            shutdown = True
            risk_price, risk_trigger_offset = hard_lower, offset

        if shutdown:
            for lot in lots:
                if not lot.sold and offset >= lot.buy_offset + config.settlement_sessions:
                    sell_lot(lot, risk_price, "risk_exit", offset)
            if all(lot.sold for lot in lots):
                final_offset, final_reason = offset, "risk_exit"
                break
            continue

        if (
            lower_reclaim_pending
            and not lower_filled
            and bar.open_vnd <= initial_buy
        ):
            lots.append(make_lot(1, offset, bar.open_vnd, lower_target, config))
            lower_filled = True
            lower_reclaim_pending = False

        if (
            not lower_filled
            and bar.low_vnd <= lower_buy
            and bar.close_vnd > lower_buy
            and bar.close_vnd > bar.open_vnd
        ):
            lower_reclaim_pending = True

        for lot in lots:
            if (
                not lot.sold
                and offset >= lot.buy_offset + config.settlement_sessions
                and bar.high_vnd >= lot.target_vnd
            ):
                sell_lot(lot, lot.target_vnd, "target", offset)
        if lots and all(lot.sold for lot in lots):
            final_offset, final_reason = offset, "all_targets"
            break

        if offset == config.maximum_horizon:
            for lot in lots:
                if not lot.sold:
                    sell_lot(lot, bar.close_vnd, "time_exit", offset)

    sale_cash = sum(net_sale_cash(lot.sale_price_vnd, config) for lot in lots)
    acquisition = sum(lot.acquisition_vnd for lot in lots)
    double_sale_cash = sum(
        net_sale_cash(lot.sale_price_vnd, config, config.doubled_cost_multiplier)
        for lot in lots
    )
    double_acquisition = sum(lot.double_acquisition_vnd for lot in lots)
    pnl = sale_cash - acquisition
    double_pnl = double_sale_cash - double_acquisition
    normal_gain = sum(
        net_sale_cash(lot.sale_price_vnd, config) - lot.acquisition_vnd
        for lot in lots if lot.sale_reason == "target"
    )
    other_pnl = sum(
        net_sale_cash(lot.sale_price_vnd, config) - lot.acquisition_vnd
        for lot in lots if lot.sale_reason != "target"
    )
    return {
        "entry_date": path[0].trading_date.isoformat(),
        "exit_date": path[final_offset].trading_date.isoformat(),
        "grid_step_fraction": step,
        "initial_buy_vnd": initial_buy,
        "initial_target_vnd": initial_target,
        "lower_buy_vnd": lower_buy,
        "lower_target_vnd": lower_target,
        "hard_lower_vnd": hard_lower,
        "lower_level_filled": lower_filled,
        "target_sale_count": sum(lot.sale_reason == "target" for lot in lots),
        "risk_exit": shutdown,
        "gap_risk_exit": gap_risk,
        "time_exit": any(lot.sale_reason == "time_exit" for lot in lots),
        "buy_count": len(lots),
        "sell_count": sum(lot.sold for lot in lots),
        "normal_target_gain_vnd": normal_gain,
        "risk_time_loss_vnd": min(other_pnl, 0),
        "net_pnl_vnd": pnl,
        "net_return": pnl / acquisition,
        "double_cost_net_pnl_vnd": double_pnl,
        "double_cost_net_return": double_pnl / double_acquisition,
        "risk_trigger_offset": risk_trigger_offset,
        "episode_reason": final_reason,
    }, ()


def generate_candidates(
    fold: trial6.Fold,
    daily: dict[str, list[trial6.DailyBar]],
    calendar: Sequence[date],
    config: Config,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    date_index = {value: index for index, value in enumerate(calendar)}
    allowed = set(fold.oos_dates)
    feature_config = trial6.Config()
    candidates: list[dict[str, object]] = []
    quarantine: list[dict[str, object]] = []
    for signal_date in fold.oos_dates:
        index = date_index[signal_date]
        entry_index = index + 1
        end_index = entry_index + config.maximum_horizon
        if (
            entry_index >= len(calendar)
            or end_index >= len(calendar)
            or calendar[entry_index] not in allowed
            or calendar[end_index] not in allowed
        ):
            continue
        for ticker in config.universe:
            features, reasons = trial6.feature_vector(
                ticker, index, daily, feature_config
            )
            if features is None or reasons:
                continue
            bars = daily[ticker]
            if (
                float(features["residual_z5"]) > config.residual_z_max
                or float(features["residual_1"]) <= config.minimum_residual_rebound
                or bars[index].close_vnd <= bars[index - 1].close_vnd
                or float(features["market_return5"]) <= config.minimum_market_return5
            ):
                continue
            episode, resets = simulate_episode(
                bars, entry_index, float(features["atr20_fraction"]), config
            )
            if episode is None:
                quarantine.append({
                    "trial_id": TRIAL_ID,
                    "fold_id": fold.fold_id,
                    "ticker": ticker,
                    "signal_date": signal_date.isoformat(),
                    "entry_date": calendar[entry_index].isoformat(),
                    "reason": "forward_reference_reset",
                    "reset_dates": "|".join(value.isoformat() for value in resets),
                })
                continue
            candidates.append({
                "trial_id": TRIAL_ID,
                "fold_id": fold.fold_id,
                "ticker": ticker,
                "sector": SECTOR_BY_TICKER[ticker],
                "signal_date": signal_date.isoformat(),
                "residual_z5": features["residual_z5"],
                "residual_1": features["residual_1"],
                "market_return5": features["market_return5"],
                "atr20_fraction": features["atr20_fraction"],
                **episode,
                "selected": False,
                "selection_rank": "",
            })
    return candidates, quarantine


def select_episodes(
    candidates: list[dict[str, object]],
    calendar: Sequence[date],
    config: Config,
) -> list[dict[str, object]]:
    indices = {value: index for index, value in enumerate(calendar)}
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
            if date.fromisoformat(str(row["exit_date"])) >= entry_date
        ]
        tickers = {str(row["ticker"]) for row in active}
        sectors = {str(row["sector"]) for row in active}
        slots = config.maximum_concurrent_campaigns - len(active)
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
            if slots <= 0:
                break
            ticker, sector = str(row["ticker"]), str(row["sector"])
            if ticker in tickers or sector in sectors:
                continue
            if current <= cooldown.get(ticker, -1):
                continue
            rank += 1
            row["selected"] = True
            row["selection_rank"] = rank
            selected.append(row)
            active.append(row)
            tickers.add(ticker)
            sectors.add(sector)
            cooldown[ticker] = (
                indices[date.fromisoformat(str(row["exit_date"]))]
                + config.cooldown_sessions
            )
            slots -= 1
    return selected


def profit_factor(values: Sequence[int]) -> float | str | None:
    gains = sum(value for value in values if value > 0)
    losses = -sum(value for value in values if value < 0)
    if losses == 0:
        return "Infinity" if gains > 0 else None
    return gains / losses


def pf_at_least(value: object, threshold: float) -> bool:
    return value == "Infinity" or (
        isinstance(value, (int, float)) and value >= threshold
    )


def evaluate(
    fold_rows: Sequence[dict[str, object]],
    candidates: Sequence[dict[str, object]],
    selected: Sequence[dict[str, object]],
    config: Config,
) -> dict[str, object]:
    pnls = [int(row["net_pnl_vnd"]) for row in selected]
    double_pnls = [int(row["double_cost_net_pnl_vnd"]) for row in selected]
    years = Counter(str(row["entry_date"])[:4] for row in selected)
    by_fold: dict[str, int] = defaultdict(int)
    by_ticker_positive: dict[str, int] = defaultdict(int)
    for row in selected:
        by_fold[str(row["fold_id"])] += int(row["net_pnl_vnd"])
        if int(row["net_pnl_vnd"]) > 0:
            by_ticker_positive[str(row["ticker"])] += int(row["net_pnl_vnd"])
    positive_pool = sum(by_ticker_positive.values())
    max_ticker_fraction = (
        max(by_ticker_positive.values(), default=0) / positive_pool
        if positive_pool else 0.0
    )
    normal_gains = sum(max(int(row["normal_target_gain_vnd"]), 0) for row in selected)
    risk_time_losses = -sum(min(int(row["risk_time_loss_vnd"]), 0) for row in selected)
    lower_pnl = sum(
        int(row["net_pnl_vnd"]) for row in selected
        if bool(row["lower_level_filled"])
    )
    target_sales = sum(int(row["target_sale_count"]) for row in selected)
    sample = {
        "valid_folds": sum(bool(row["valid"]) for row in fold_rows)
        >= config.minimum_valid_folds,
        "activation_candidates": len(candidates) >= config.minimum_candidates,
        "selected_episodes": len(selected) >= config.minimum_selected_episodes,
        "ordinary_target_sales": target_sales >= config.minimum_target_sales,
        "year_distribution": (
            sum(value >= config.minimum_episodes_per_year for value in years.values())
            >= config.minimum_years
        ),
        "year_concentration": (
            bool(selected)
            and max(years.values(), default=0) / len(selected)
            <= config.maximum_year_fraction
        ),
    }
    economics = {
        "positive_total_pnl": sum(pnls) > 0,
        "positive_median_pnl": bool(pnls) and statistics.median(pnls) > 0,
        "profit_factor": pf_at_least(profit_factor(pnls), config.minimum_profit_factor),
        "positive_active_fold_fraction": (
            bool(by_fold)
            and sum(value > 0 for value in by_fold.values()) / len(by_fold)
            >= config.minimum_positive_active_fold_fraction
        ),
        "target_gains_cover_risk_time_losses": normal_gains >= risk_time_losses,
        "positive_doubled_cost_pnl": sum(double_pnls) > 0,
        "doubled_cost_profit_factor": pf_at_least(profit_factor(double_pnls), 1.0),
        "positive_after_best_removed": (
            bool(pnls) and sum(pnls) - max(pnls) > 0
        ),
        "ticker_concentration": (
            positive_pool > 0
            and max_ticker_fraction <= config.maximum_ticker_positive_pnl_fraction
        ),
        "positive_lower_level_episodes": (
            any(bool(row["lower_level_filled"]) for row in selected)
            and lower_pnl > 0
        ),
    }
    if not all(sample.values()):
        status = "inconclusive_sample"
    elif not all(economics.values()):
        status = "rejected_development"
    else:
        status = "passed_development_screen"
    return {
        "trial_id": TRIAL_ID,
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "advance_to_minute_stage_b": status == "passed_development_screen",
        "final_test_used": False,
        "sample_gates": sample,
        "economic_gates": economics,
        "sensitivity_sample_diagnostics": {
            "at_least_30_selected": len(selected) >= 30,
            "at_least_20_selected": len(selected) >= 20,
            "decision_effect": "none",
        },
        "metrics": {
            "valid_folds": sum(bool(row["valid"]) for row in fold_rows),
            "activation_candidates": len(candidates),
            "selected_episodes": len(selected),
            "ordinary_target_sales": target_sales,
            "lower_level_fills": sum(bool(row["lower_level_filled"]) for row in selected),
            "year_counts": dict(sorted(years.items())),
            "total_net_pnl_vnd": sum(pnls),
            "median_net_pnl_vnd": statistics.median(pnls) if pnls else None,
            "profit_factor": profit_factor(pnls),
            "normal_target_gains_vnd": normal_gains,
            "risk_time_losses_vnd": risk_time_losses,
            "double_cost_total_pnl_vnd": sum(double_pnls),
            "double_cost_profit_factor": profit_factor(double_pnls),
            "best_removed_total_pnl_vnd": sum(pnls) - max(pnls) if pnls else 0,
            "maximum_ticker_positive_pnl_fraction": max_ticker_fraction,
            "lower_level_episode_pnl_vnd": lower_pnl,
            "risk_exit_episodes": sum(bool(row["risk_exit"]) for row in selected),
            "gap_risk_exit_episodes": sum(bool(row["gap_risk_exit"]) for row in selected),
            "time_exit_episodes": sum(bool(row["time_exit"]) for row in selected),
        },
    }


def write_csv(path: Path, rows: Iterable[dict[str, object]], fields: Sequence[str]) -> None:
    with path.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_study(
    daily_path: Path,
    assignments_path: Path,
    preregistration_path: Path,
    output_root: Path,
    config: Config | None = None,
) -> Path:
    config = config or Config()
    config.validate()
    daily, calendar, final_range = trial6.read_development_daily(
        daily_path, config.universe
    )
    folds = trial6.read_folds(assignments_path)
    candidates: list[dict[str, object]] = []
    quarantine: list[dict[str, object]] = []
    fold_rows: list[dict[str, object]] = []
    for fold in folds:
        fold_candidates, fold_quarantine = generate_candidates(
            fold, daily, calendar, config
        )
        candidates.extend(fold_candidates)
        quarantine.extend(fold_quarantine)
        fold_rows.append({
            "trial_id": TRIAL_ID,
            "fold_id": fold.fold_id,
            "valid": True,
            "candidate_count": len(fold_candidates),
            "selected_episodes": 0,
            "target_sales": 0,
            "lower_level_fills": 0,
            "net_pnl_vnd": 0,
            "double_cost_net_pnl_vnd": 0,
        })
    selected = select_episodes(candidates, calendar, config)
    by_fold: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in selected:
        by_fold[str(row["fold_id"])].append(row)
    for row in fold_rows:
        chosen = by_fold[str(row["fold_id"])]
        row["selected_episodes"] = len(chosen)
        row["target_sales"] = sum(int(item["target_sale_count"]) for item in chosen)
        row["lower_level_fills"] = sum(bool(item["lower_level_filled"]) for item in chosen)
        row["net_pnl_vnd"] = sum(int(item["net_pnl_vnd"]) for item in chosen)
        row["double_cost_net_pnl_vnd"] = sum(
            int(item["double_cost_net_pnl_vnd"]) for item in chosen
        )
    report = evaluate(fold_rows, candidates, selected, config)
    identity = {
        "trial_id": TRIAL_ID,
        "schema_version": SCHEMA_VERSION,
        "config": asdict(config),
        "daily_development_sha256": file_sha(daily_path),
        "assignments_sha256": file_sha(assignments_path),
        "preregistration_sha256": file_sha(preregistration_path),
        "implementation_sha256": file_sha(Path(__file__)),
        "trial6_dependency_sha256": file_sha(Path(trial6.__file__)),
        "trial5_dependency_sha256": file_sha(
            Path(__file__).with_name("study_trial5_rotation_grid.py")
        ),
        "final_test_range_detected_but_not_parsed": [
            final_range[0].isoformat(), final_range[1].isoformat()
        ],
    }
    run_id = "trial7_" + trial6.sha256_bytes(trial6.canonical_json(identity))[:10]
    output = output_root / run_id
    if output.exists():
        raise FileExistsError(f"Create-only Trial 7 output exists: {output}")
    output_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="trial7_", dir=output_root) as temporary:
        directory = Path(temporary)
        write_csv(directory / "activation_candidates.csv", candidates, CANDIDATE_FIELDS)
        write_csv(directory / "selected_episodes.csv", selected, CANDIDATE_FIELDS)
        write_csv(directory / "quarantined_candidates.csv", quarantine, QUARANTINE_FIELDS)
        write_csv(directory / "fold_summary.csv", fold_rows, FOLD_FIELDS)
        write_json(directory / "gate_report.json", report)
        artifacts = {
            path.name: file_sha(path) for path in sorted(directory.iterdir())
        }
        write_json(directory / "manifest.json", {
            **identity, "run_id": run_id, "artifacts": artifacts
        })
        directory.rename(output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--development-walk-forward", action="store_true")
    parser.add_argument("--daily", type=Path, default=Path("data_algotradeDB_split.csv"))
    parser.add_argument(
        "--assignments", type=Path,
        default=Path("data/trial5_splits_rotation/walk_forward_date_assignments.csv"),
    )
    parser.add_argument(
        "--preregistration", type=Path,
        default=Path("research_log/TRIAL7_EPISODIC_GRID_PREREGISTRATION.md"),
    )
    parser.add_argument(
        "--output-root", type=Path, default=Path("data/trial7_episodic_grid")
    )
    args = parser.parse_args()
    if not args.development_walk_forward:
        raise SystemExit("Only --development-walk-forward is supported")
    output = run_study(
        args.daily, args.assignments, args.preregistration, args.output_root
    )
    print(output)
    print((output / "gate_report.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
