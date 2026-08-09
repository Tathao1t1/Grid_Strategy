#!/usr/bin/env python3
"""Trial 12 causal shrinkage ticker selector for a frozen grid."""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import statistics
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Sequence

import study_trial6_mean_reversion as trial6
import study_trial11_trend_grid as trial11


TRIAL_ID = "TRIAL12-CAUSAL-GRID-EXPECTANCY-SELECTOR"
IS_FOLDS = tuple(f"wf_{value:02d}" for value in range(1, 10))
VALIDATION_FOLDS = tuple(f"wf_{value:02d}" for value in range(10, 16))
GRID = trial11.Parameters(0.00, -0.50, 0.75, False, 3, 10)
BASE = trial11.BaseConfig()


@dataclass(frozen=True)
class Selector:
    lookback_months: int
    shrinkage_k: int
    downside_penalty: float
    top_k: int

    def key(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


SEARCH_FIELDS = (
    "rank", "eligible", "parameter_json", "lookback_months", "shrinkage_k",
    "downside_penalty", "top_k", "selected_campaigns", "selected_pnl_vnd",
    "control_pnl_vnd", "incremental_pnl_vnd", "median_pnl_vnd",
    "profit_factor", "double_cost_pnl_vnd", "best_removed_pnl_vnd",
    "positive_active_rotation_fraction", "maximum_ticker_positive_fraction",
)
ROTATION_FIELDS = (
    "partition", "fold_id", "rotation_start", "rotation_end",
    "selected_tickers", "eligible_tickers", "selected_campaigns",
    "selected_pnl_vnd", "selected_double_pnl_vnd", "control_campaigns",
    "control_pnl_vnd",
)
SCORE_FIELDS = (
    "partition", "fold_id", "as_of_date", "ticker", "history_start",
    "historical_campaigns", "ticker_mean_return", "pooled_mean_return",
    "shrunk_mean_return", "downside_semideviation", "score", "eligible",
    "selected_rank",
)


def selector_space() -> list[Selector]:
    return [
        Selector(*values)
        for values in itertools.product(
            (6, 12), (5, 10), (0.25, 0.50), (1, 2, 3)
        )
    ]


def add_months(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 + months
    year, month_zero = divmod(month_index, 12)
    month = month_zero + 1
    days = (31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
            31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    return date(year, month, min(value.day, days[month - 1]))


def generate_campaign_library(
    daily: dict[str, list[trial6.DailyBar]],
    calendar: Sequence[date],
    features: dict[tuple[str, int], trial11.Feature],
) -> list[dict[str, object]]:
    candidates_by_ticker: dict[str, list[dict[str, object]]] = defaultdict(list)
    end_index = len(calendar) - 1
    for signal_index in range(60, end_index):
        for ticker in trial11.TICKERS:
            feature = features[(ticker, signal_index)]
            if not trial11.signal_passes(feature, GRID):
                continue
            row = trial11.simulate_campaign(
                ticker, signal_index, end_index, daily, features,
                GRID, BASE, "historical_library",
            )
            if row is not None:
                candidates_by_ticker[ticker].append(row)
    indices = {value: index for index, value in enumerate(calendar)}
    library: list[dict[str, object]] = []
    for ticker, candidates in candidates_by_ticker.items():
        cooldown_until = -1
        for row in sorted(candidates, key=lambda item: str(item["entry_date"])):
            entry_index = indices[date.fromisoformat(str(row["entry_date"]))]
            if entry_index <= cooldown_until:
                continue
            library.append(row)
            cooldown_until = (
                indices[date.fromisoformat(str(row["exit_date"]))]
                + BASE.cooldown_sessions
            )
    return sorted(library, key=lambda row: (str(row["entry_date"]), str(row["ticker"])))


def score_tickers(
    selector: Selector,
    fold: trial6.Fold,
    library: Sequence[dict[str, object]],
    features: dict[tuple[str, int], trial11.Feature],
    calendar: Sequence[date],
    partition: str,
) -> tuple[list[str], list[dict[str, object]]]:
    rotation_start = fold.oos_dates[0]
    history_start = add_months(rotation_start, -selector.lookback_months)
    history = [
        row for row in library
        if history_start <= date.fromisoformat(str(row["entry_date"]))
        and date.fromisoformat(str(row["exit_date"])) < rotation_start
    ]
    pooled_returns = [float(row["campaign_return"]) for row in history]
    pooled_mean = statistics.mean(pooled_returns) if pooled_returns else 0.0
    date_index = {value: index for index, value in enumerate(calendar)}
    as_of_index = date_index[rotation_start] - 1
    scored: list[dict[str, object]] = []
    for ticker in trial11.TICKERS:
        ticker_rows = [row for row in history if row["ticker"] == ticker]
        returns = [float(row["campaign_return"]) for row in ticker_rows]
        count = len(returns)
        ticker_mean = statistics.mean(returns) if returns else 0.0
        downside = (
            math.sqrt(statistics.mean(min(value, 0.0) ** 2 for value in returns))
            if returns else 0.0
        )
        shrunk = (
            count / (count + selector.shrinkage_k) * ticker_mean
            + selector.shrinkage_k / (count + selector.shrinkage_k) * pooled_mean
        )
        score = shrunk - selector.downside_penalty * downside
        current = features.get((ticker, as_of_index))
        eligible = (
            count >= 2
            and score > 0
            and current is not None
            and current.valid
        )
        scored.append({
            "partition": partition,
            "fold_id": fold.fold_id,
            "as_of_date": calendar[as_of_index].isoformat(),
            "ticker": ticker,
            "history_start": history_start.isoformat(),
            "historical_campaigns": count,
            "ticker_mean_return": ticker_mean,
            "pooled_mean_return": pooled_mean,
            "shrunk_mean_return": shrunk,
            "downside_semideviation": downside,
            "score": score,
            "eligible": eligible,
            "selected_rank": "",
        })
    ranked = sorted(
        (row for row in scored if bool(row["eligible"])),
        key=lambda row: (-float(row["score"]), str(row["ticker"])),
    )
    selected: list[str] = []
    sectors: set[str] = set()
    for row in ranked:
        ticker = str(row["ticker"])
        sector = trial11.SECTORS[ticker]
        if sector in sectors:
            continue
        selected.append(ticker)
        sectors.add(sector)
        row["selected_rank"] = len(selected)
        if len(selected) == selector.top_k:
            break
    return selected, scored


def run_rotation(
    fold: trial6.Fold,
    tickers: Sequence[str],
    daily: dict[str, list[trial6.DailyBar]],
    calendar: Sequence[date],
    features: dict[tuple[str, int], trial11.Feature],
    partition: str,
) -> list[dict[str, object]]:
    if not tickers:
        return []
    date_index = {value: index for index, value in enumerate(calendar)}
    start_index = date_index[fold.oos_dates[0]]
    end_index = date_index[fold.oos_dates[-1]]
    candidates: list[dict[str, object]] = []
    for signal_index in range(max(start_index, 60), end_index):
        for ticker in tickers:
            feature = features[(ticker, signal_index)]
            if not trial11.signal_passes(feature, GRID):
                continue
            row = trial11.simulate_campaign(
                ticker, signal_index, end_index, daily, features,
                GRID, BASE, partition,
            )
            if row is not None:
                candidates.append(row)
    return trial11.select_campaigns(candidates, calendar, BASE)


def profit_factor(values: Sequence[int]) -> float | str | None:
    return trial11.profit_factor(values)


def evaluate_selector(
    selector: Selector,
    folds: Sequence[trial6.Fold],
    library: Sequence[dict[str, object]],
    controls: dict[str, list[dict[str, object]]],
    daily: dict[str, list[trial6.DailyBar]],
    calendar: Sequence[date],
    features: dict[tuple[str, int], trial11.Feature],
    partition: str,
) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    campaigns: list[dict[str, object]] = []
    rotation_rows: list[dict[str, object]] = []
    score_rows: list[dict[str, object]] = []
    rotation_pnls: list[int] = []
    active_rotation_pnls: list[int] = []
    for fold in folds:
        selected, scores = score_tickers(
            selector, fold, library, features, calendar, partition
        )
        score_rows.extend(scores)
        chosen = run_rotation(
            fold, selected, daily, calendar, features, partition
        )
        for row in chosen:
            row["fold_id"] = fold.fold_id
        campaigns.extend(chosen)
        control = controls[fold.fold_id]
        selected_pnl = sum(int(row["net_pnl_vnd"]) for row in chosen)
        control_pnl = sum(int(row["net_pnl_vnd"]) for row in control)
        rotation_pnls.append(selected_pnl)
        if chosen:
            active_rotation_pnls.append(selected_pnl)
        rotation_rows.append({
            "partition": partition,
            "fold_id": fold.fold_id,
            "rotation_start": fold.oos_dates[0].isoformat(),
            "rotation_end": fold.oos_dates[-1].isoformat(),
            "selected_tickers": "|".join(selected),
            "eligible_tickers": sum(bool(row["eligible"]) for row in scores),
            "selected_campaigns": len(chosen),
            "selected_pnl_vnd": selected_pnl,
            "selected_double_pnl_vnd": sum(
                int(row["double_cost_pnl_vnd"]) for row in chosen
            ),
            "control_campaigns": len(control),
            "control_pnl_vnd": control_pnl,
        })
    pnls = [int(row["net_pnl_vnd"]) for row in campaigns]
    doubles = [int(row["double_cost_pnl_vnd"]) for row in campaigns]
    control_total = sum(
        int(row["net_pnl_vnd"])
        for fold in folds for row in controls[fold.fold_id]
    )
    by_ticker_positive: dict[str, int] = defaultdict(int)
    for row in campaigns:
        if int(row["net_pnl_vnd"]) > 0:
            by_ticker_positive[str(row["ticker"])] += int(row["net_pnl_vnd"])
    positive_pool = sum(by_ticker_positive.values())
    concentration = (
        max(by_ticker_positive.values(), default=0) / positive_pool
        if positive_pool else 0.0
    )
    pf = profit_factor(pnls)
    metrics = {
        "selected_campaigns": len(campaigns),
        "selected_pnl_vnd": sum(pnls),
        "control_pnl_vnd": control_total,
        "incremental_pnl_vnd": sum(pnls) - control_total,
        "median_pnl_vnd": statistics.median(pnls) if pnls else None,
        "profit_factor": pf,
        "double_cost_pnl_vnd": sum(doubles),
        "best_removed_pnl_vnd": sum(pnls) - max(pnls) if pnls else 0,
        "positive_active_rotation_fraction": (
            sum(value > 0 for value in active_rotation_pnls)
            / len(active_rotation_pnls)
            if active_rotation_pnls else 0.0
        ),
        "maximum_ticker_positive_fraction": concentration,
        "target_gains_vnd": sum(
            int(row["normal_target_gain_vnd"]) for row in campaigns
        ),
        "other_losses_vnd": sum(
            int(row["other_loss_vnd"]) for row in campaigns
        ),
        "worst_pnl_vnd": min(pnls) if pnls else None,
        "active_rotations": len(active_rotation_pnls),
        "valid_rotations": len(folds),
    }
    return metrics, campaigns, rotation_rows, score_rows


def in_sample_eligible(metrics: dict[str, object]) -> bool:
    pf = metrics["profit_factor"]
    return (
        metrics["valid_rotations"] == 9
        and int(metrics["selected_campaigns"]) >= 20
        and int(metrics["selected_pnl_vnd"]) > 0
        and metrics["median_pnl_vnd"] is not None
        and float(metrics["median_pnl_vnd"]) > 0
        and (pf == "Infinity" or isinstance(pf, float) and pf >= 1.20)
        and int(metrics["double_cost_pnl_vnd"]) > 0
        and int(metrics["best_removed_pnl_vnd"]) > 0
        and float(metrics["positive_active_rotation_fraction"]) >= 0.60
        and float(metrics["maximum_ticker_positive_fraction"]) <= 0.40
        and int(metrics["incremental_pnl_vnd"]) > 0
    )


def validation_gates(metrics: dict[str, object]) -> dict[str, bool]:
    pf = metrics["profit_factor"]
    return {
        "minimum_8_campaigns": int(metrics["selected_campaigns"]) >= 8,
        "positive_total_pnl": int(metrics["selected_pnl_vnd"]) > 0,
        "positive_median_pnl": (
            metrics["median_pnl_vnd"] is not None
            and float(metrics["median_pnl_vnd"]) > 0
        ),
        "profit_factor_at_least_1": (
            pf == "Infinity" or isinstance(pf, float) and pf >= 1.0
        ),
        "positive_doubled_cost_pnl": int(metrics["double_cost_pnl_vnd"]) > 0,
        "positive_after_best_removed": int(metrics["best_removed_pnl_vnd"]) > 0,
        "target_gains_cover_other_losses": (
            int(metrics["target_gains_vnd"]) >= int(metrics["other_losses_vnd"])
        ),
        "outperforms_control": int(metrics["incremental_pnl_vnd"]) > 0,
        "worst_loss_within_1_5pct_nav": (
            metrics["worst_pnl_vnd"] is not None
            and int(metrics["worst_pnl_vnd"]) >= -1_500_000
        ),
    }


def controls_for_folds(
    folds: Sequence[trial6.Fold],
    daily: dict[str, list[trial6.DailyBar]],
    calendar: Sequence[date],
    features: dict[tuple[str, int], trial11.Feature],
    partition: str,
) -> dict[str, list[dict[str, object]]]:
    return {
        fold.fold_id: run_rotation(
            fold, trial11.TICKERS, daily, calendar, features, partition
        )
        for fold in folds
    }


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_csv(path: Path, rows: Sequence[dict[str, object]], fields: Sequence[str]) -> None:
    with path.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def optimize_validate(output_dir: Path) -> dict[str, object]:
    if output_dir.exists():
        raise FileExistsError(f"Create-only output exists: {output_dir}")
    output_dir.mkdir(parents=True)
    daily_path = Path("data_algotradeDB_split.csv")
    daily, calendar, final_range = trial6.read_development_daily(
        daily_path, trial11.TICKERS
    )
    folds = trial6.read_folds(
        Path("data/trial5_splits_rotation/walk_forward_date_assignments.csv")
    )
    fold_by_id = {fold.fold_id: fold for fold in folds}
    is_folds = [fold_by_id[value] for value in IS_FOLDS]
    validation_folds = [fold_by_id[value] for value in VALIDATION_FOLDS]
    features = trial11.build_feature_cache(daily, calendar)
    library = generate_campaign_library(daily, calendar, features)
    is_controls = controls_for_folds(
        is_folds, daily, calendar, features, "in_sample_control"
    )
    search_rows: list[dict[str, object]] = []
    result_by_key: dict[str, tuple] = {}
    for selector in selector_space():
        metrics, campaigns, rotations, scores = evaluate_selector(
            selector, is_folds, library, is_controls, daily, calendar,
            features, "in_sample",
        )
        eligible = in_sample_eligible(metrics)
        row = {
            "rank": "",
            "eligible": eligible,
            "parameter_json": selector.key(),
            **asdict(selector),
            **{field: metrics[field] for field in (
                "selected_campaigns", "selected_pnl_vnd", "control_pnl_vnd",
                "incremental_pnl_vnd", "median_pnl_vnd", "profit_factor",
                "double_cost_pnl_vnd", "best_removed_pnl_vnd",
                "positive_active_rotation_fraction",
                "maximum_ticker_positive_fraction",
            )},
        }
        search_rows.append(row)
        result_by_key[selector.key()] = (metrics, campaigns, rotations, scores)
    eligible_rows = [row for row in search_rows if bool(row["eligible"])]
    eligible_rows.sort(key=lambda row: (
        -int(row["incremental_pnl_vnd"]),
        -(float(row["profit_factor"]) if row["profit_factor"] != "Infinity" else 1e9),
        -int(row["double_cost_pnl_vnd"]),
        str(row["parameter_json"]),
    ))
    for rank, row in enumerate(eligible_rows, 1):
        row["rank"] = rank
    chosen_row = eligible_rows[0] if eligible_rows else None
    if chosen_row:
        chosen = Selector(**{
            field: chosen_row[field] for field in asdict(selector_space()[0])
        })
        is_metrics, is_campaigns, is_rotations, is_scores = result_by_key[chosen.key()]
        validation_controls = controls_for_folds(
            validation_folds, daily, calendar, features, "validation_control"
        )
        val_metrics, val_campaigns, val_rotations, val_scores = evaluate_selector(
            chosen, validation_folds, library, validation_controls,
            daily, calendar, features, "internal_validation",
        )
        gates = validation_gates(val_metrics)
        validation_status = (
            "passed_internal_validation"
            if all(gates.values()) else "rejected_internal_validation"
        )
    else:
        chosen = None
        is_metrics = {}
        is_campaigns = []
        is_rotations = []
        is_scores = []
        val_metrics = {}
        val_campaigns = []
        val_rotations = []
        val_scores = []
        gates = {}
        validation_status = "no_in_sample_selector"
    report = {
        "trial_id": TRIAL_ID,
        "status": validation_status,
        "selector_configurations": len(search_rows),
        "eligible_in_sample_selectors": len(eligible_rows),
        "selected_selector": asdict(chosen) if chosen else None,
        "selected_in_sample_metrics": is_metrics,
        "internal_validation_metrics": val_metrics,
        "internal_validation_gates": gates,
        "advance_to_final_oos": bool(gates) and all(gates.values()),
        "final_test_used": False,
        "final_test_range_detected_but_not_parsed": [
            final_range[0].isoformat(), final_range[1].isoformat()
        ],
    }
    write_csv(output_dir / "selector_optimization.csv", search_rows, SEARCH_FIELDS)
    write_csv(output_dir / "selected_is_rotations.csv", is_rotations, ROTATION_FIELDS)
    write_csv(output_dir / "selected_is_scores.csv", is_scores, SCORE_FIELDS)
    write_csv(
        output_dir / "selected_is_campaigns.csv",
        is_campaigns,
        ("fold_id",) + trial11.CAMPAIGN_FIELDS,
    )
    write_csv(output_dir / "validation_rotations.csv", val_rotations, ROTATION_FIELDS)
    write_csv(output_dir / "validation_scores.csv", val_scores, SCORE_FIELDS)
    write_csv(
        output_dir / "validation_campaigns.csv",
        val_campaigns,
        ("fold_id",) + trial11.CAMPAIGN_FIELDS,
    )
    report_path = output_dir / "development_report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if report["advance_to_final_oos"] and chosen:
        prereg = Path(
            "research_log/TRIAL12_CAUSAL_TICKER_SELECTOR_PREREGISTRATION.md"
        )
        lock = {
            "trial_id": TRIAL_ID,
            "selector": asdict(chosen),
            "grid": asdict(GRID),
            "base": asdict(BASE),
            "implementation_sha256": file_sha(Path(__file__)),
            "trial11_dependency_sha256": file_sha(Path(trial11.__file__)),
            "preregistration_sha256": file_sha(prereg),
            "daily_input_sha256": file_sha(daily_path),
            "development_report_sha256": file_sha(report_path),
        }
        (output_dir / "FINAL_OOS_CONFIG_LOCK.json").write_text(
            json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return report


def final_rotations(calendar: Sequence[date]) -> list[trial6.Fold]:
    final_dates = [
        value for value in calendar
        if trial11.FINAL_START <= value <= trial11.FINAL_END
    ]
    rotations: list[trial6.Fold] = []
    start = trial11.FINAL_START
    number = 1
    while start <= trial11.FINAL_END:
        boundary = add_months(start, 2)
        dates = tuple(
            value for value in final_dates
            if start <= value < boundary
        )
        if dates:
            rotations.append(trial6.Fold(
                f"final_{number:02d}", (), dates
            ))
            number += 1
        later = [value for value in final_dates if value >= boundary]
        if not later:
            break
        start = later[0]
    return rotations


def run_final_oos(
    development_dir: Path,
    output_dir: Path,
) -> dict[str, object]:
    lock_path = development_dir / "FINAL_OOS_CONFIG_LOCK.json"
    if not lock_path.exists():
        raise PermissionError(
            "Final OOS remains locked because internal validation did not pass"
        )
    if output_dir.exists():
        raise FileExistsError(f"Create-only final output exists: {output_dir}")
    daily_path = Path("data_algotradeDB_split.csv")
    prereg = Path(
        "research_log/TRIAL12_CAUSAL_TICKER_SELECTOR_PREREGISTRATION.md"
    )
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    expected = {
        "implementation_sha256": file_sha(Path(__file__)),
        "trial11_dependency_sha256": file_sha(Path(trial11.__file__)),
        "preregistration_sha256": file_sha(prereg),
        "daily_input_sha256": file_sha(daily_path),
        "development_report_sha256": file_sha(
            development_dir / "development_report.json"
        ),
    }
    for field, value in expected.items():
        if lock.get(field) != value:
            raise ValueError(f"Final lock mismatch: {field}")
    if lock.get("grid") != asdict(GRID) or lock.get("base") != asdict(BASE):
        raise ValueError("Frozen grid/base mismatch")
    selector = Selector(**lock["selector"])
    daily, calendar = trial11.read_all_daily_for_final(daily_path)
    features = trial11.build_feature_cache(daily, calendar)
    library = generate_campaign_library(daily, calendar, features)
    rotations = final_rotations(calendar)
    controls = controls_for_folds(
        rotations, daily, calendar, features, "final_control"
    )
    metrics, campaigns, rotation_rows, score_rows = evaluate_selector(
        selector, rotations, library, controls, daily, calendar,
        features, "final_oos",
    )
    gates = validation_gates(metrics)
    passed = all(gates.values())
    report = {
        "trial_id": TRIAL_ID,
        "status": "passed_final_oos" if passed else "failed_final_oos",
        "final_test_used": True,
        "selector": asdict(selector),
        "metrics": metrics,
        "final_gates": gates,
    }
    output_dir.mkdir(parents=True)
    write_csv(output_dir / "final_rotations.csv", rotation_rows, ROTATION_FIELDS)
    write_csv(output_dir / "final_scores.csv", score_rows, SCORE_FIELDS)
    write_csv(
        output_dir / "final_campaigns.csv",
        campaigns,
        ("fold_id",) + trial11.CAMPAIGN_FIELDS,
    )
    (output_dir / "final_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--optimize-validate", action="store_true")
    parser.add_argument("--final-oos", action="store_true")
    parser.add_argument(
        "--output-dir", type=Path,
        default=None,
    )
    parser.add_argument(
        "--development-dir", type=Path,
        default=Path("data/trial12_ticker_selector/development"),
    )
    args = parser.parse_args()
    if args.optimize_validate == args.final_oos:
        raise SystemExit("Choose --optimize-validate or --final-oos")
    if args.optimize_validate:
        output = args.output_dir or Path(
            "data/trial12_ticker_selector/development"
        )
        report = optimize_validate(output)
    else:
        output = args.output_dir or Path(
            "data/trial12_ticker_selector/final_oos"
        )
        report = run_final_oos(args.development_dir, output)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
