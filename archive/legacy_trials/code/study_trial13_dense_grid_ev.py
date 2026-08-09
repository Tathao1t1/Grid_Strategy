#!/usr/bin/env python3
"""Trial 13 dense, causal expected-value ranker for a frozen grid."""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import statistics
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Sequence

import study_trial6_mean_reversion as trial6
import study_trial11_trend_grid as trial11
import study_trial12_ticker_selector as trial12


TRIAL_ID = "TRIAL13-DENSE-CAUSAL-GRID-EV"
IS_FOLDS = trial12.IS_FOLDS
VALIDATION_FOLDS = trial12.VALIDATION_FOLDS
GRID = trial12.GRID
BASE = trial12.BASE
FEATURE_NAMES = (
    "residual_z5",
    "residual_1",
    "residual_slope20",
    "downside_semivol20",
    "residual_ar1_20",
    "market_return20",
    "close_minus_sma50_fraction",
    "sma20_minus_sma50_fraction",
    "atr20_fraction",
    "log_median_value60",
)


@dataclass(frozen=True)
class ModelConfig:
    ridge_penalty: int
    risk_penalty: float
    score_buffer: float
    top_k: int

    def key(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class RidgeModel:
    means: tuple[float, ...]
    scales: tuple[float, ...]
    weights: tuple[float, ...]

    def predict(self, values: Sequence[float]) -> float:
        standardized = [
            (value - mean) / scale
            for value, mean, scale in zip(values, self.means, self.scales)
        ]
        return self.weights[0] + sum(
            weight * value
            for weight, value in zip(self.weights[1:], standardized)
        )


SEARCH_FIELDS = (
    "rank", "eligible", "parameter_json", "ridge_penalty", "risk_penalty",
    "score_buffer", "top_k", "selected_campaigns", "selected_pnl_vnd",
    "control_pnl_vnd", "incremental_pnl_vnd", "median_pnl_vnd",
    "profit_factor", "double_cost_pnl_vnd", "best_removed_pnl_vnd",
    "positive_active_fold_fraction", "maximum_ticker_positive_fraction",
    "entry_years", "maximum_year_fraction", "score_quintile_spread",
)
SELECTED_FIELDS = (
    "fold_id", "predicted_net_return", "predicted_downside", "model_score",
    *trial11.CAMPAIGN_FIELDS,
)
FOLD_FIELDS = (
    "partition", "fold_id", "train_observations", "deployment_observations",
    "selected_campaigns", "selected_pnl_vnd", "control_campaigns",
    "control_pnl_vnd", "score_quintile_spread",
)
MODEL_FIELDS = (
    "partition", "fold_id", "ridge_penalty", "train_observations",
    *tuple(f"return_{name}" for name in ("intercept", *FEATURE_NAMES)),
    *tuple(f"downside_{name}" for name in ("intercept", *FEATURE_NAMES)),
)


def model_space() -> list[ModelConfig]:
    return [
        ModelConfig(*values)
        for values in itertools.product(
            (10, 100, 1000),
            (0.00, 0.25, 0.50),
            (0.000, 0.001),
            (1, 2, 3),
        )
    ]


def feature_values(row: dict[str, object]) -> list[float]:
    return [float(row[name]) for name in FEATURE_NAMES]


def build_dense_feature_cache(
    daily: dict[str, list[trial6.DailyBar]],
    calendar: Sequence[date],
    trend_features: dict[tuple[str, int], trial11.Feature],
) -> dict[tuple[str, int], dict[str, float]]:
    permissive = trial6.Config(candidate_residual_z_max=100.0)
    result: dict[tuple[str, int], dict[str, float]] = {}
    for index in range(60, len(calendar)):
        for ticker in trial11.TICKERS:
            raw, reasons = trial6.feature_vector(
                ticker, index, daily, permissive
            )
            blocking = [
                reason for reason in reasons
                if reason != "residual_not_low_enough"
            ]
            trend = trend_features.get((ticker, index))
            if raw is None or blocking or trend is None or not trend.valid:
                continue
            bars = daily[ticker]
            close = bars[index].close_vnd
            sma20 = statistics.mean(
                bar.close_vnd for bar in bars[index - 19:index + 1]
            )
            sma50 = statistics.mean(
                bar.close_vnd for bar in bars[index - 49:index + 1]
            )
            values = {
                "residual_z5": float(raw["residual_z5"]),
                "residual_1": float(raw["residual_1"]),
                "residual_slope20": float(raw["residual_slope20"]),
                "downside_semivol20": float(raw["downside_semivol20"]),
                "residual_ar1_20": float(raw["residual_ar1_20"]),
                "market_return20": float(trend.market_return20),
                "close_minus_sma50_fraction": (close - sma50) / sma50,
                "sma20_minus_sma50_fraction": (sma20 - sma50) / sma50,
                "atr20_fraction": float(raw["atr20_fraction"]),
                "log_median_value60": float(raw["log_median_value60"]),
            }
            if all(math.isfinite(value) for value in values.values()):
                result[(ticker, index)] = values
    return result


def generate_observations(
    fold: trial6.Fold,
    allowed_dates: Sequence[date],
    partition: str,
    daily: dict[str, list[trial6.DailyBar]],
    calendar: Sequence[date],
    dense_features: dict[tuple[str, int], dict[str, float]],
    trend_features: dict[tuple[str, int], trial11.Feature],
) -> list[dict[str, object]]:
    allowed = set(allowed_dates)
    indices = {value: index for index, value in enumerate(calendar)}
    observations: list[dict[str, object]] = []
    for signal_date in allowed_dates:
        signal_index = indices[signal_date]
        entry_index = signal_index + 1
        end_index = entry_index + GRID.maximum_horizon
        if (
            entry_index >= len(calendar)
            or end_index >= len(calendar)
            or calendar[entry_index] not in allowed
            or calendar[end_index] not in allowed
        ):
            continue
        for ticker in trial11.TICKERS:
            values = dense_features.get((ticker, signal_index))
            if values is None:
                continue
            campaign = trial11.simulate_campaign(
                ticker, signal_index, end_index, daily, trend_features,
                GRID, BASE, partition,
            )
            if campaign is None:
                continue
            observations.append({
                "fold_id": fold.fold_id,
                **campaign,
                **values,
                "predicted_net_return": "",
                "predicted_downside": "",
                "model_score": "",
            })
    return observations


def fit_ridge(
    rows: Sequence[dict[str, object]],
    target: Sequence[float],
    penalty: float,
) -> RidgeModel:
    if not rows or len(rows) != len(target):
        raise ValueError("Ridge rows and target must be non-empty and aligned")
    matrix = [feature_values(row) for row in rows]
    width = len(FEATURE_NAMES)
    means = tuple(
        statistics.mean(row[column] for row in matrix)
        for column in range(width)
    )
    scales = tuple(
        max(
            math.sqrt(trial6.variance([row[column] for row in matrix])),
            1e-12,
        )
        for column in range(width)
    )
    design = [
        [1.0] + [
            (value - means[column]) / scales[column]
            for column, value in enumerate(row)
        ]
        for row in matrix
    ]
    size = width + 1
    gram = [[0.0] * size for _ in range(size)]
    rhs = [0.0] * size
    for row, outcome in zip(design, target):
        for left in range(size):
            rhs[left] += row[left] * outcome
            for right in range(size):
                gram[left][right] += row[left] * row[right]
    for column in range(1, size):
        gram[column][column] += penalty
    weights = tuple(trial6.solve_linear_system(gram, rhs))
    return RidgeModel(means, scales, weights)


def fit_and_score(
    train_rows: Sequence[dict[str, object]],
    deployment_rows: Sequence[dict[str, object]],
    penalty: int,
) -> tuple[list[dict[str, object]], RidgeModel, RidgeModel]:
    returns = [float(row["campaign_return"]) for row in train_rows]
    downside = [max(-value, 0.0) for value in returns]
    return_model = fit_ridge(train_rows, returns, penalty)
    downside_model = fit_ridge(train_rows, downside, penalty)
    scored: list[dict[str, object]] = []
    for source in deployment_rows:
        row = dict(source)
        values = feature_values(row)
        row["predicted_net_return"] = return_model.predict(values)
        row["predicted_downside"] = max(
            downside_model.predict(values), 0.0
        )
        scored.append(row)
    return scored, return_model, downside_model


def score_rows(
    rows: Sequence[dict[str, object]], config: ModelConfig
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for source in rows:
        row = dict(source)
        row["model_score"] = (
            float(row["predicted_net_return"])
            - config.risk_penalty * float(row["predicted_downside"])
        )
        result.append(row)
    return result


def select_campaigns(
    rows: Sequence[dict[str, object]],
    calendar: Sequence[date],
    config: ModelConfig,
) -> list[dict[str, object]]:
    indices = {value: index for index, value in enumerate(calendar)}
    by_entry: dict[date, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        if (
            float(row["predicted_net_return"]) > 0
            and float(row["model_score"]) > config.score_buffer
        ):
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
        available = BASE.maximum_concurrent - len(active)
        opened = 0
        ranked = sorted(
            by_entry[entry_date],
            key=lambda row: (
                -float(row["model_score"]),
                -float(row["predicted_net_return"]),
                str(row["ticker"]),
            ),
        )
        for row in ranked:
            if available <= 0 or opened >= config.top_k:
                break
            ticker = str(row["ticker"])
            sector = str(row["sector"])
            if ticker in active_tickers or sector in active_sectors:
                continue
            if current <= cooldown.get(ticker, -1):
                continue
            selected.append(row)
            active.append(row)
            active_tickers.add(ticker)
            active_sectors.add(sector)
            exit_index = indices[date.fromisoformat(str(row["exit_date"]))]
            cooldown[ticker] = exit_index + BASE.cooldown_sessions
            available -= 1
            opened += 1
    return selected


def quintile_spread(rows: Sequence[dict[str, object]]) -> float | None:
    if len(rows) < 10:
        return None
    ranked = sorted(rows, key=lambda row: float(row["model_score"]))
    size = max(1, len(ranked) // 5)
    low = statistics.mean(
        float(row["campaign_return"]) for row in ranked[:size]
    )
    high = statistics.mean(
        float(row["campaign_return"]) for row in ranked[-size:]
    )
    return high - low


def model_record(
    partition: str,
    fold_id: str,
    penalty: int,
    train_count: int,
    return_model: RidgeModel,
    downside_model: RidgeModel,
) -> dict[str, object]:
    return {
        "partition": partition,
        "fold_id": fold_id,
        "ridge_penalty": penalty,
        "train_observations": train_count,
        **{
            f"return_{name}": value
            for name, value in zip(
                ("intercept", *FEATURE_NAMES), return_model.weights
            )
        },
        **{
            f"downside_{name}": value
            for name, value in zip(
                ("intercept", *FEATURE_NAMES), downside_model.weights
            )
        },
    }


def evaluate_configuration(
    config: ModelConfig,
    folds: Sequence[trial6.Fold],
    predictions: dict[tuple[int, str], list[dict[str, object]]],
    train_counts: dict[str, int],
    controls: dict[str, list[dict[str, object]]],
    calendar: Sequence[date],
    partition: str,
) -> tuple[
    dict[str, object],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
]:
    selected: list[dict[str, object]] = []
    all_scored: list[dict[str, object]] = []
    fold_rows: list[dict[str, object]] = []
    active_fold_pnls: list[int] = []
    for fold in folds:
        scored = score_rows(
            predictions[(config.ridge_penalty, fold.fold_id)], config
        )
        chosen = select_campaigns(scored, calendar, config)
        selected.extend(chosen)
        all_scored.extend(scored)
        selected_pnl = sum(int(row["net_pnl_vnd"]) for row in chosen)
        control_pnl = sum(
            int(row["net_pnl_vnd"]) for row in controls[fold.fold_id]
        )
        if chosen:
            active_fold_pnls.append(selected_pnl)
        fold_rows.append({
            "partition": partition,
            "fold_id": fold.fold_id,
            "train_observations": train_counts[fold.fold_id],
            "deployment_observations": len(scored),
            "selected_campaigns": len(chosen),
            "selected_pnl_vnd": selected_pnl,
            "control_campaigns": len(controls[fold.fold_id]),
            "control_pnl_vnd": control_pnl,
            "score_quintile_spread": quintile_spread(scored),
        })
    pnls = [int(row["net_pnl_vnd"]) for row in selected]
    doubles = [int(row["double_cost_pnl_vnd"]) for row in selected]
    years = Counter(str(row["entry_date"])[:4] for row in selected)
    ticker_positive: dict[str, int] = defaultdict(int)
    for row in selected:
        if int(row["net_pnl_vnd"]) > 0:
            ticker_positive[str(row["ticker"])] += int(row["net_pnl_vnd"])
    positive_pool = sum(ticker_positive.values())
    control_pnl = sum(
        int(row["net_pnl_vnd"])
        for fold in folds for row in controls[fold.fold_id]
    )
    pf = trial11.profit_factor(pnls)
    metrics = {
        "valid_folds": len(folds),
        "selected_campaigns": len(selected),
        "selected_pnl_vnd": sum(pnls),
        "control_pnl_vnd": control_pnl,
        "incremental_pnl_vnd": sum(pnls) - control_pnl,
        "median_pnl_vnd": statistics.median(pnls) if pnls else None,
        "profit_factor": pf,
        "double_cost_pnl_vnd": sum(doubles),
        "best_removed_pnl_vnd": sum(pnls) - max(pnls) if pnls else 0,
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
        "score_quintile_spread": quintile_spread(all_scored),
        "target_gains_vnd": sum(
            int(row["normal_target_gain_vnd"]) for row in selected
        ),
        "other_losses_vnd": sum(
            int(row["other_loss_vnd"]) for row in selected
        ),
        "worst_pnl_vnd": min(pnls) if pnls else None,
        "active_folds": len(active_fold_pnls),
    }
    return metrics, selected, fold_rows, all_scored


def in_sample_eligible(metrics: dict[str, object]) -> bool:
    pf = metrics["profit_factor"]
    return (
        int(metrics["valid_folds"]) == 9
        and int(metrics["selected_campaigns"]) >= 30
        and int(metrics["entry_years"]) >= 3
        and float(metrics["maximum_year_fraction"]) <= 0.50
        and int(metrics["selected_pnl_vnd"]) > 0
        and metrics["median_pnl_vnd"] is not None
        and float(metrics["median_pnl_vnd"]) > 0
        and (pf == "Infinity" or isinstance(pf, float) and pf >= 1.20)
        and int(metrics["double_cost_pnl_vnd"]) > 0
        and int(metrics["best_removed_pnl_vnd"]) > 0
        and float(metrics["positive_active_fold_fraction"]) >= 0.60
        and float(metrics["maximum_ticker_positive_fraction"]) <= 0.40
        and metrics["score_quintile_spread"] is not None
        and float(metrics["score_quintile_spread"]) > 0
        and int(metrics["incremental_pnl_vnd"]) > 0
    )


def validation_gates(metrics: dict[str, object]) -> dict[str, bool]:
    pf = metrics["profit_factor"]
    return {
        "minimum_15_campaigns": int(metrics["selected_campaigns"]) >= 15,
        "positive_total_pnl": int(metrics["selected_pnl_vnd"]) > 0,
        "positive_median_pnl": (
            metrics["median_pnl_vnd"] is not None
            and float(metrics["median_pnl_vnd"]) > 0
        ),
        "profit_factor_at_least_1": (
            pf == "Infinity" or isinstance(pf, float) and pf >= 1.0
        ),
        "positive_doubled_cost_pnl": int(metrics["double_cost_pnl_vnd"]) > 0,
        "positive_after_best_removed": int(
            metrics["best_removed_pnl_vnd"]
        ) > 0,
        "positive_score_quintile_spread": (
            metrics["score_quintile_spread"] is not None
            and float(metrics["score_quintile_spread"]) > 0
        ),
        "target_gains_cover_other_losses": (
            int(metrics["target_gains_vnd"])
            >= int(metrics["other_losses_vnd"])
        ),
        "outperforms_control": int(metrics["incremental_pnl_vnd"]) > 0,
        "worst_loss_within_1_5pct_nav": (
            metrics["worst_pnl_vnd"] is not None
            and int(metrics["worst_pnl_vnd"]) >= -1_500_000
        ),
    }


def prepare_predictions(
    folds: Sequence[trial6.Fold],
    daily: dict[str, list[trial6.DailyBar]],
    calendar: Sequence[date],
    dense_features: dict[tuple[str, int], dict[str, float]],
    trend_features: dict[tuple[str, int], trial11.Feature],
    partition: str,
) -> tuple[
    dict[tuple[int, str], list[dict[str, object]]],
    dict[str, int],
    list[dict[str, object]],
]:
    predictions: dict[tuple[int, str], list[dict[str, object]]] = {}
    train_counts: dict[str, int] = {}
    model_rows: list[dict[str, object]] = []
    for fold in folds:
        train = generate_observations(
            fold, fold.train_dates, f"{partition}_train", daily, calendar,
            dense_features, trend_features,
        )
        deployment = generate_observations(
            fold, fold.oos_dates, partition, daily, calendar,
            dense_features, trend_features,
        )
        if len(train) < 30:
            raise ValueError(
                f"{fold.fold_id} has only {len(train)} dense train rows"
            )
        train_counts[fold.fold_id] = len(train)
        for penalty in (10, 100, 1000):
            scored, return_model, downside_model = fit_and_score(
                train, deployment, penalty
            )
            predictions[(penalty, fold.fold_id)] = scored
            model_rows.append(model_record(
                partition, fold.fold_id, penalty, len(train),
                return_model, downside_model,
            ))
    return predictions, train_counts, model_rows


def controls_for_folds(
    folds: Sequence[trial6.Fold],
    daily: dict[str, list[trial6.DailyBar]],
    calendar: Sequence[date],
    trend_features: dict[tuple[str, int], trial11.Feature],
    partition: str,
) -> dict[str, list[dict[str, object]]]:
    return trial12.controls_for_folds(
        folds, daily, calendar, trend_features, partition
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
    assignment_path = Path(
        "data/trial5_splits_rotation/walk_forward_date_assignments.csv"
    )
    daily, calendar, final_range = trial6.read_development_daily(
        daily_path, trial11.TICKERS
    )
    folds = trial6.read_folds(assignment_path)
    fold_by_id = {fold.fold_id: fold for fold in folds}
    is_folds = [fold_by_id[value] for value in IS_FOLDS]
    validation_folds = [fold_by_id[value] for value in VALIDATION_FOLDS]
    trend_features = trial11.build_feature_cache(daily, calendar)
    dense_features = build_dense_feature_cache(
        daily, calendar, trend_features
    )
    predictions, train_counts, is_model_rows = prepare_predictions(
        is_folds, daily, calendar, dense_features, trend_features, "in_sample"
    )
    controls = controls_for_folds(
        is_folds, daily, calendar, trend_features, "in_sample_control"
    )
    search_rows: list[dict[str, object]] = []
    results: dict[str, tuple] = {}
    for config in model_space():
        metrics, selected, fold_rows, scored = evaluate_configuration(
            config, is_folds, predictions, train_counts, controls, calendar,
            "in_sample",
        )
        eligible = in_sample_eligible(metrics)
        search_rows.append({
            "rank": "",
            "eligible": eligible,
            "parameter_json": config.key(),
            **asdict(config),
            **{field: metrics[field] for field in SEARCH_FIELDS if field in metrics},
        })
        results[config.key()] = (metrics, selected, fold_rows, scored)
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
        chosen = ModelConfig(
            int(chosen_row["ridge_penalty"]),
            float(chosen_row["risk_penalty"]),
            float(chosen_row["score_buffer"]),
            int(chosen_row["top_k"]),
        )
        is_metrics, is_selected, is_fold_rows, _ = results[chosen.key()]
        val_predictions, val_train_counts, val_model_rows = prepare_predictions(
            validation_folds, daily, calendar, dense_features, trend_features,
            "internal_validation",
        )
        val_controls = controls_for_folds(
            validation_folds, daily, calendar, trend_features,
            "internal_validation_control",
        )
        val_metrics, val_selected, val_fold_rows, _ = evaluate_configuration(
            chosen, validation_folds, val_predictions, val_train_counts,
            val_controls, calendar, "internal_validation",
        )
        gates = validation_gates(val_metrics)
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
        status = "no_in_sample_model"
    report = {
        "trial_id": TRIAL_ID,
        "status": status,
        "model_configurations": len(search_rows),
        "eligible_in_sample_configurations": len(eligible_rows),
        "selected_configuration": asdict(chosen) if chosen else None,
        "selected_in_sample_metrics": is_metrics,
        "internal_validation_metrics": val_metrics,
        "internal_validation_gates": gates,
        "advance_to_final_oos": bool(gates) and all(gates.values()),
        "final_test_used": False,
        "final_test_range_detected_but_not_parsed": [
            final_range[0].isoformat(), final_range[1].isoformat()
        ],
    }
    write_csv(output_dir / "model_optimization.csv", search_rows, SEARCH_FIELDS)
    write_csv(output_dir / "selected_is_campaigns.csv", is_selected, SELECTED_FIELDS)
    write_csv(output_dir / "selected_is_folds.csv", is_fold_rows, FOLD_FIELDS)
    write_csv(output_dir / "is_models.csv", is_model_rows, MODEL_FIELDS)
    write_csv(
        output_dir / "validation_campaigns.csv", val_selected, SELECTED_FIELDS
    )
    write_csv(output_dir / "validation_folds.csv", val_fold_rows, FOLD_FIELDS)
    write_csv(output_dir / "validation_models.csv", val_model_rows, MODEL_FIELDS)
    report_path = output_dir / "development_report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if report["advance_to_final_oos"] and chosen:
        prereg = Path(
            "research_log/TRIAL13_DENSE_GRID_EV_PREREGISTRATION.md"
        )
        lock = {
            "trial_id": TRIAL_ID,
            "configuration": asdict(chosen),
            "grid": asdict(GRID),
            "base": asdict(BASE),
            "implementation_sha256": file_sha(Path(__file__)),
            "trial11_dependency_sha256": file_sha(Path(trial11.__file__)),
            "trial12_dependency_sha256": file_sha(Path(trial12.__file__)),
            "preregistration_sha256": file_sha(prereg),
            "daily_input_sha256": file_sha(daily_path),
            "assignments_sha256": file_sha(assignment_path),
            "development_report_sha256": file_sha(report_path),
        }
        (output_dir / "FINAL_OOS_CONFIG_LOCK.json").write_text(
            json.dumps(lock, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return report


def final_training_fold(
    rotation: trial6.Fold,
    calendar: Sequence[date],
) -> trial6.Fold:
    start = rotation.oos_dates[0]
    history_start = trial12.add_months(start, -12)
    train_dates = tuple(
        value for value in calendar if history_start <= value < start
    )
    return trial6.Fold(rotation.fold_id, train_dates, rotation.oos_dates)


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
    assignment_path = Path(
        "data/trial5_splits_rotation/walk_forward_date_assignments.csv"
    )
    prereg = Path("research_log/TRIAL13_DENSE_GRID_EV_PREREGISTRATION.md")
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    expected = {
        "implementation_sha256": file_sha(Path(__file__)),
        "trial11_dependency_sha256": file_sha(Path(trial11.__file__)),
        "trial12_dependency_sha256": file_sha(Path(trial12.__file__)),
        "preregistration_sha256": file_sha(prereg),
        "daily_input_sha256": file_sha(daily_path),
        "assignments_sha256": file_sha(assignment_path),
        "development_report_sha256": file_sha(
            development_dir / "development_report.json"
        ),
    }
    for field, value in expected.items():
        if lock.get(field) != value:
            raise ValueError(f"Final lock mismatch: {field}")
    if lock.get("grid") != asdict(GRID) or lock.get("base") != asdict(BASE):
        raise ValueError("Frozen grid/base mismatch")
    config = ModelConfig(**lock["configuration"])
    daily, calendar = trial11.read_all_daily_for_final(daily_path)
    trend_features = trial11.build_feature_cache(daily, calendar)
    dense_features = build_dense_feature_cache(
        daily, calendar, trend_features
    )
    rotations = [
        final_training_fold(rotation, calendar)
        for rotation in trial12.final_rotations(calendar)
    ]
    predictions, train_counts, model_rows = prepare_predictions(
        rotations, daily, calendar, dense_features, trend_features, "final_oos"
    )
    controls = controls_for_folds(
        rotations, daily, calendar, trend_features, "final_control"
    )
    metrics, selected, fold_rows, _ = evaluate_configuration(
        config, rotations, predictions, train_counts, controls, calendar,
        "final_oos",
    )
    gates = validation_gates(metrics)
    report = {
        "trial_id": TRIAL_ID,
        "status": "passed_final_oos" if all(gates.values()) else "failed_final_oos",
        "final_test_used": True,
        "configuration": asdict(config),
        "metrics": metrics,
        "final_gates": gates,
    }
    output_dir.mkdir(parents=True)
    write_csv(output_dir / "final_campaigns.csv", selected, SELECTED_FIELDS)
    write_csv(output_dir / "final_folds.csv", fold_rows, FOLD_FIELDS)
    write_csv(output_dir / "final_models.csv", model_rows, MODEL_FIELDS)
    (output_dir / "final_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


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
            "data/trial13_dense_grid_ev/development"
        )
        print(json.dumps(optimize_validate(output), indent=2, sort_keys=True))
    else:
        output = args.output_dir or Path("data/trial13_dense_grid_ev/final")
        print(json.dumps(run_final_oos(
            Path("data/trial13_dense_grid_ev/development"), output
        ), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
