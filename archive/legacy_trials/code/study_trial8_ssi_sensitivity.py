#!/usr/bin/env python3
"""Exploratory SSI-only Trial 8 gate and lot-size sensitivity study."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Sequence

import study_trial6_mean_reversion as trial6
import study_trial7_episodic_grid as trial7


TRIAL_ID = "TRIAL8-SSI-EXPLORATORY-SENSITIVITY"
TICKER = "SSI"
ACCOUNT_NAV_VND = 100_000_000


@dataclass(frozen=True)
class Gate:
    name: str
    residual_z_max: float
    confirmation: str


GATES = (
    Gate("strict", -0.75, "and"),
    Gate("moderate", -0.50, "and"),
    Gate("loose_confirmation", -0.50, "or"),
)
LOT_SIZES = (100, 200, 300)

VARIANT_FIELDS = (
    "trial_id", "gate", "quantity_per_level", "activation_candidates",
    "independent_episodes", "ordinary_target_sales", "lower_level_fills",
    "total_net_pnl_vnd", "median_net_pnl_vnd", "profit_factor",
    "double_cost_total_pnl_vnd", "double_cost_profit_factor",
    "worst_episode_pnl_vnd", "best_removed_total_pnl_vnd",
    "normal_target_gains_vnd", "risk_time_losses_vnd",
    "maximum_inventory_notional_vnd", "worst_loss_exceeds_one_pct_nav",
    "status",
)
EPISODE_FIELDS = (
    "trial_id", "gate", "quantity_per_level", "signal_date", "entry_date",
    "exit_date", "residual_z5", "residual_1", "close_up",
    "market_return5", "grid_step_fraction", "lower_level_filled",
    "target_sale_count", "risk_exit", "gap_risk_exit", "time_exit",
    "net_pnl_vnd", "double_cost_net_pnl_vnd", "initial_buy_vnd",
    "lower_buy_vnd", "modeled_max_inventory_notional_vnd",
)


def pf(values: Sequence[int]) -> float | str | None:
    gains = sum(value for value in values if value > 0)
    losses = -sum(value for value in values if value < 0)
    if losses == 0:
        return "Infinity" if gains else None
    return gains / losses


def pf_at_least(value: object, threshold: float) -> bool:
    return value == "Infinity" or (
        isinstance(value, (int, float)) and value >= threshold
    )


def activation_passes(
    features: dict[str, float], close_up: bool, gate: Gate
) -> bool:
    residual_up = float(features["residual_1"]) > 0
    confirmation = (
        residual_up and close_up
        if gate.confirmation == "and"
        else residual_up or close_up
    )
    return (
        float(features["residual_z5"]) <= gate.residual_z_max
        and confirmation
        and float(features["market_return5"]) > -0.05
    )


def generate_gate_episodes(
    gate: Gate,
    quantity: int,
    daily: dict[str, list[trial6.DailyBar]],
    calendar: Sequence[date],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    bars = daily[TICKER]
    feature_config = replace(
        trial6.Config(), candidate_residual_z_max=gate.residual_z_max
    )
    grid_config = replace(trial7.Config(), quantity_per_level=quantity)
    candidates: list[dict[str, object]] = []
    for index in range(feature_config.beta_sessions, len(calendar) - grid_config.maximum_horizon - 1):
        features, reasons = trial6.feature_vector(
            TICKER, index, daily, feature_config
        )
        if features is None or reasons:
            continue
        close_up = bars[index].close_vnd > bars[index - 1].close_vnd
        if not activation_passes(features, close_up, gate):
            continue
        entry_index = index + 1
        episode, resets = trial7.simulate_episode(
            bars, entry_index, float(features["atr20_fraction"]), grid_config
        )
        if episode is None or resets:
            continue
        max_inventory = quantity * int(episode["initial_buy_vnd"])
        if bool(episode["lower_level_filled"]):
            max_inventory += quantity * int(episode["lower_buy_vnd"])
        candidates.append({
            "trial_id": TRIAL_ID,
            "gate": gate.name,
            "quantity_per_level": quantity,
            "signal_date": calendar[index].isoformat(),
            "residual_z5": features["residual_z5"],
            "residual_1": features["residual_1"],
            "close_up": close_up,
            "market_return5": features["market_return5"],
            "modeled_max_inventory_notional_vnd": max_inventory,
            **episode,
        })
    indices = {value: index for index, value in enumerate(calendar)}
    selected: list[dict[str, object]] = []
    cooldown_until = -1
    for row in sorted(candidates, key=lambda item: str(item["entry_date"])):
        entry_index = indices[date.fromisoformat(str(row["entry_date"]))]
        if entry_index <= cooldown_until:
            continue
        selected.append(row)
        cooldown_until = (
            indices[date.fromisoformat(str(row["exit_date"]))]
            + grid_config.cooldown_sessions
        )
    return candidates, selected


def summarize(
    gate: Gate,
    quantity: int,
    candidates: Sequence[dict[str, object]],
    episodes: Sequence[dict[str, object]],
) -> dict[str, object]:
    pnls = [int(row["net_pnl_vnd"]) for row in episodes]
    doubles = [int(row["double_cost_net_pnl_vnd"]) for row in episodes]
    normal_gains = sum(
        max(int(row["normal_target_gain_vnd"]), 0) for row in episodes
    )
    risk_losses = -sum(
        min(int(row["risk_time_loss_vnd"]), 0) for row in episodes
    )
    worst = min(pnls) if pnls else 0
    metrics = {
        "trial_id": TRIAL_ID,
        "gate": gate.name,
        "quantity_per_level": quantity,
        "activation_candidates": len(candidates),
        "independent_episodes": len(episodes),
        "ordinary_target_sales": sum(int(row["target_sale_count"]) for row in episodes),
        "lower_level_fills": sum(bool(row["lower_level_filled"]) for row in episodes),
        "total_net_pnl_vnd": sum(pnls),
        "median_net_pnl_vnd": statistics.median(pnls) if pnls else None,
        "profit_factor": pf(pnls),
        "double_cost_total_pnl_vnd": sum(doubles),
        "double_cost_profit_factor": pf(doubles),
        "worst_episode_pnl_vnd": worst,
        "best_removed_total_pnl_vnd": sum(pnls) - max(pnls) if pnls else 0,
        "normal_target_gains_vnd": normal_gains,
        "risk_time_losses_vnd": risk_losses,
        "maximum_inventory_notional_vnd": max(
            (int(row["modeled_max_inventory_notional_vnd"]) for row in episodes),
            default=0,
        ),
        "worst_loss_exceeds_one_pct_nav": worst < -0.01 * ACCOUNT_NAV_VND,
    }
    viable = (
        len(episodes) >= 20
        and sum(pnls) > 0
        and bool(pnls) and statistics.median(pnls) > 0
        and pf_at_least(metrics["profit_factor"], 1.20)
        and sum(doubles) > 0
        and metrics["best_removed_total_pnl_vnd"] > 0
        and normal_gains >= risk_losses
        and not metrics["worst_loss_exceeds_one_pct_nav"]
    )
    metrics["status"] = (
        "exploratory_viable" if viable else "exploratory_not_viable"
    )
    return metrics


def write_csv(path: Path, rows: Sequence[dict[str, object]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def run(output_dir: Path) -> dict[str, object]:
    daily, calendar, final_range = trial6.read_development_daily(
        Path("data_algotradeDB_split.csv"), trial6.TICKERS
    )
    variants: list[dict[str, object]] = []
    all_episodes: list[dict[str, object]] = []
    for gate in GATES:
        for quantity in LOT_SIZES:
            candidates, selected = generate_gate_episodes(
                gate, quantity, daily, calendar
            )
            variants.append(summarize(gate, quantity, candidates, selected))
            all_episodes.extend(selected)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "variant_summary.csv", variants, VARIANT_FIELDS)
    write_csv(output_dir / "selected_episodes.csv", all_episodes, EPISODE_FIELDS)
    viable = [row for row in variants if row["status"] == "exploratory_viable"]
    recommendation = None
    if viable:
        recommendation = min(
            viable,
            key=lambda row: (
                int(row["quantity_per_level"]),
                -int(row["double_cost_total_pnl_vnd"]),
            ),
        )
    report = {
        "trial_id": TRIAL_ID,
        "status": (
            "exploratory_candidate_found" if recommendation
            else "no_exploratory_viable_variant"
        ),
        "independent_validation": False,
        "live_authorization": False,
        "final_test_used": False,
        "final_test_range_detected_but_not_parsed": [
            final_range[0].isoformat(), final_range[1].isoformat()
        ],
        "variant_count": len(variants),
        "recommended_variant": recommendation,
    }
    (output_dir / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir", type=Path,
        default=Path("data/trial8_ssi_sensitivity"),
    )
    args = parser.parse_args()
    report = run(args.output_dir)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
