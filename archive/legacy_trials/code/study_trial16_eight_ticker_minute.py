#!/usr/bin/env python3
"""Trial 16 exploratory eight-ticker sensitivity of Trial 15."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

import study_trial5_rotation_grid as trial5
import study_trial6_mean_reversion as trial6
import study_trial11_trend_grid as trial11
import study_trial13_dense_grid_ev as trial13
import study_trial14_dense_grid_capture as trial14
import study_trial15_minute_grid_capture as trial15


TRIAL_ID = "TRIAL16-EIGHT-TICKER-MINUTE-SENSITIVITY"
EXCLUDED = ("FPT", "PNJ")
UNIVERSE = tuple(
    ticker for ticker in trial11.TICKERS if ticker not in EXCLUDED
)


def generate_observations(
    fold: trial6.Fold,
    allowed_dates: Sequence,
    minute_dir: Path,
    daily: dict[str, list[trial6.DailyBar]],
    calendar: Sequence,
    dense_features: dict[tuple[str, int], dict[str, float]],
) -> list[dict[str, object]]:
    if not allowed_dates:
        return []
    minute_fold = trial15.as_minute_fold(fold, allowed_dates)
    minutes, _ = trial5.load_fold_minutes(
        minute_dir, minute_fold, UNIVERSE
    )
    allowed = set(allowed_dates)
    indices = {value: index for index, value in enumerate(calendar)}
    observations: list[dict[str, object]] = []
    for signal_date in allowed_dates:
        signal_index = indices[signal_date]
        path_dates = calendar[
            signal_index + 1:
            signal_index + 1 + trial15.HORIZON_SESSIONS
        ]
        if (
            len(path_dates) != trial15.HORIZON_SESSIONS
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
            row = trial15.simulate_minute_campaign(
                ticker, signal_date, path_dates, minutes[ticker], feature
            )
            if row is not None:
                row["fold_id"] = fold.fold_id
                observations.append(row)
    return observations


def prepare_predictions(
    folds: Sequence[trial6.Fold],
    minute_dir: Path,
    daily: dict[str, list[trial6.DailyBar]],
    calendar: Sequence,
    dense_features: dict[tuple[str, int], dict[str, float]],
    partition: str,
) -> tuple[
    dict[tuple[int, str], list[dict[str, object]]],
    dict[str, int],
    list[dict[str, object]],
    dict[str, list[dict[str, object]]],
]:
    predictions: dict[tuple[int, str], list[dict[str, object]]] = {}
    train_counts: dict[str, int] = {}
    model_rows: list[dict[str, object]] = []
    deployments: dict[str, list[dict[str, object]]] = {}
    for fold in folds:
        train = generate_observations(
            fold, fold.train_dates, minute_dir, daily, calendar,
            dense_features,
        )
        deployment = generate_observations(
            fold, fold.oos_dates, minute_dir, daily, calendar,
            dense_features,
        )
        if len(train) < 30:
            raise ValueError(
                f"{fold.fold_id} has only {len(train)} minute train rows"
            )
        train_counts[fold.fold_id] = len(train)
        deployments[fold.fold_id] = deployment
        for penalty in (10, 100):
            scored, target_model, capture_model, loss_model = (
                trial14.fit_and_score(train, deployment, penalty)
            )
            predictions[(penalty, fold.fold_id)] = scored
            model_rows.append(trial14.model_record(
                partition, fold.fold_id, penalty, len(train),
                target_model, capture_model, loss_model,
            ))
    return predictions, train_counts, model_rows, deployments


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
    is_folds = [fold_by_id[value] for value in trial15.IS_FOLDS]
    validation_folds = [
        fold_by_id[value] for value in trial15.VALIDATION_FOLDS
    ]
    trend_features = trial11.build_feature_cache(daily, calendar)
    dense_features = trial13.build_dense_feature_cache(
        daily, calendar, trend_features
    )
    predictions, train_counts, is_model_rows, deployments = (
        prepare_predictions(
            is_folds, minute_dir, daily, calendar, dense_features, "in_sample"
        )
    )
    controls = {
        fold.fold_id: trial15.control_campaigns(
            deployments[fold.fold_id], calendar
        )
        for fold in is_folds
    }
    search_rows: list[dict[str, object]] = []
    results: dict[str, tuple] = {}
    for config in trial15.minute_space():
        metrics, selected, fold_rows, scored = (
            trial14.evaluate_configuration(
                config, is_folds, predictions, train_counts, controls,
                calendar, "in_sample",
            )
        )
        eligible = trial14.in_sample_eligible(metrics)
        search_rows.append({
            "rank": "",
            "eligible": eligible,
            "parameter_json": config.key(),
            **asdict(config),
            **{
                field: metrics[field]
                for field in trial15.SEARCH_FIELDS if field in metrics
            },
        })
        results[config.key()] = (metrics, selected, fold_rows, scored)
    eligible_rows = [row for row in search_rows if bool(row["eligible"])]
    eligible_rows.sort(key=lambda row: (
        -int(row["selected_pnl_vnd"]),
        -(float(row["profit_factor"]) if row["profit_factor"] != "Infinity" else 1e9),
        -int(row["double_cost_pnl_vnd"]),
        str(row["parameter_json"]),
    ))
    for rank, row in enumerate(eligible_rows, 1):
        row["rank"] = rank
    chosen_row = eligible_rows[0] if eligible_rows else None
    if chosen_row:
        chosen = trial14.CaptureConfig(
            int(chosen_row["ridge_penalty"]),
            float(chosen_row["minimum_target_probability"]),
            float(chosen_row["risk_penalty"]),
            float(chosen_row["score_buffer"]),
            int(chosen_row["top_k"]),
        )
        is_metrics, is_selected, is_fold_rows, _ = results[chosen.key()]
        (
            val_predictions,
            val_train_counts,
            val_model_rows,
            val_deployments,
        ) = prepare_predictions(
            validation_folds, minute_dir, daily, calendar, dense_features,
            "internal_validation",
        )
        val_controls = {
            fold.fold_id: trial15.control_campaigns(
                val_deployments[fold.fold_id], calendar
            )
            for fold in validation_folds
        }
        val_metrics, val_selected, val_fold_rows, _ = (
            trial14.evaluate_configuration(
                chosen, validation_folds, val_predictions, val_train_counts,
                val_controls, calendar, "internal_validation",
            )
        )
        gates = trial14.validation_gates(val_metrics)
        status = (
            "passed_internal_validation"
            if all(gates.values()) else "rejected_internal_validation"
        )
    else:
        chosen = None
        is_metrics = {}
        is_selected = []
        is_fold_rows = []
        val_metrics = {}
        val_selected = []
        val_fold_rows = []
        val_model_rows = []
        gates = {}
        status = "no_in_sample_eight_ticker_model"
    report = {
        "trial_id": TRIAL_ID,
        "exploratory_post_result_sensitivity": True,
        "excluded_tickers": list(EXCLUDED),
        "execution_universe": list(UNIVERSE),
        "status": status,
        "minute_configurations": len(search_rows),
        "eligible_in_sample_configurations": len(eligible_rows),
        "selected_configuration": asdict(chosen) if chosen else None,
        "selected_in_sample_metrics": is_metrics,
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
    }
    write_csv(
        output_dir / "minute_optimization.csv",
        search_rows, trial15.SEARCH_FIELDS,
    )
    write_csv(
        output_dir / "selected_is_campaigns.csv",
        is_selected, trial15.MINUTE_FIELDS,
    )
    write_csv(
        output_dir / "selected_is_folds.csv",
        is_fold_rows, trial15.FOLD_FIELDS,
    )
    write_csv(output_dir / "is_models.csv", is_model_rows, trial15.MODEL_FIELDS)
    write_csv(
        output_dir / "validation_campaigns.csv",
        val_selected, trial15.MINUTE_FIELDS,
    )
    write_csv(
        output_dir / "validation_folds.csv",
        val_fold_rows, trial15.FOLD_FIELDS,
    )
    write_csv(
        output_dir / "validation_models.csv",
        val_model_rows, trial15.MODEL_FIELDS,
    )
    report_path = output_dir / "development_report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if report["advance_to_final_oos"] and chosen:
        prereg = Path(
            "research_log/"
            "TRIAL16_EIGHT_TICKER_MINUTE_SENSITIVITY_PREREGISTRATION.md"
        )
        lock = {
            "trial_id": TRIAL_ID,
            "configuration": asdict(chosen),
            "excluded_tickers": list(EXCLUDED),
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
    raise NotImplementedError("Final sensitivity run is not authorized")


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
            "data/trial16_eight_ticker_minute/development"
        )
        print(json.dumps(optimize_validate(output), indent=2, sort_keys=True))
    else:
        run_final_oos(
            Path("data/trial16_eight_ticker_minute/development"),
            args.output_dir or Path("data/trial16_eight_ticker_minute/final"),
        )


if __name__ == "__main__":
    main()
