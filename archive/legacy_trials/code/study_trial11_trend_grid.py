#!/usr/bin/env python3
"""Trial 11 optimized trend-conditioned pullback grid."""

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
from study_trial5_rotation_grid import round_to_hsx_tick


TRIAL_ID = "TRIAL11-TREND-CONDITIONED-PULLBACK-GRID"
IS_START = date(2022, 1, 4)
IS_END = date(2024, 6, 28)
VALIDATION_START = date(2024, 7, 1)
VALIDATION_END = date(2025, 7, 11)
FINAL_START = date(2025, 7, 14)
FINAL_END = date(2026, 7, 16)
TICKERS = trial6.TICKERS
SECTORS = trial6.SECTOR_BY_TICKER
NAV_VND = 100_000_000


@dataclass(frozen=True)
class Parameters:
    market_return20_min: float
    residual_z_max: float
    spacing_atr_multiplier: float
    lower_level_enabled: bool
    stop_steps: int
    maximum_horizon: int

    def key(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class BaseConfig:
    quantity: int = 100
    minimum_spacing: float = 0.015
    maximum_spacing: float = 0.040
    settlement_sessions: int = 2
    cooldown_sessions: int = 5
    maximum_concurrent: int = 3
    commission_rate: float = 0.0015
    sell_tax_rate: float = 0.0010
    execution_haircut: float = 0.0005


@dataclass(frozen=True)
class Feature:
    index: int
    trading_date: date
    ticker: str
    residual_z5: float
    residual_1: float
    market_return20: float
    atr_fraction: float
    close_up: bool
    close_above_sma50: bool
    sma20_above_sma50: bool
    valid: bool


@dataclass
class Lot:
    name: str
    buy_offset: int
    buy_price: int
    target: int
    acquisition: int
    double_acquisition: int
    sold: bool = False
    sale_price: int = 0
    sale_reason: str = ""


SEARCH_FIELDS = (
    "rank", "eligible", "parameter_json", "market_return20_min",
    "residual_z_max", "spacing_atr_multiplier", "lower_level_enabled",
    "stop_steps", "maximum_horizon", "executed_campaigns", "total_pnl_vnd",
    "median_pnl_vnd", "profit_factor", "double_cost_pnl_vnd",
    "best_removed_pnl_vnd", "positive_halfyear_fraction", "worst_return",
    "p10_return", "campaign_return_sharpe", "robust_score",
)
CAMPAIGN_FIELDS = (
    "partition", "ticker", "sector", "signal_date", "entry_date", "exit_date",
    "residual_z5", "residual_1", "market_return20", "spacing_fraction",
    "lower_level_enabled", "lower_level_filled", "buy_count", "target_sales",
    "trend_exit", "risk_exit", "gap_exit", "time_exit", "net_pnl_vnd",
    "double_cost_pnl_vnd", "campaign_return", "normal_target_gain_vnd",
    "other_loss_vnd",
)


def parameter_space() -> list[Parameters]:
    return [
        Parameters(*values)
        for values in itertools.product(
            (0.00, 0.02),
            (-0.50, -0.75, -1.00),
            (0.75, 1.00, 1.25),
            (False, True),
            (2, 3),
            (10, 15, 20),
        )
    ]


def acquisition_cash(
    price: int, base: BaseConfig, multiplier: float = 1.0
) -> int:
    execution = round(price * (1 + base.execution_haircut * multiplier))
    notional = execution * base.quantity
    return notional + round(notional * base.commission_rate * multiplier)


def sale_cash(
    price: int, base: BaseConfig, multiplier: float = 1.0
) -> int:
    execution = round(price * (1 - base.execution_haircut * multiplier))
    notional = execution * base.quantity
    return (
        notional
        - round(notional * base.commission_rate * multiplier)
        - round(notional * base.sell_tax_rate * multiplier)
    )


def make_lot(
    name: str, offset: int, price: int, target: int, base: BaseConfig
) -> Lot:
    return Lot(
        name, offset, price, target,
        acquisition_cash(price, base),
        acquisition_cash(price, base, 2.0),
    )


def sell(lot: Lot, price: int, reason: str) -> None:
    lot.sold = True
    lot.sale_price = price
    lot.sale_reason = reason


def market_return(
    ticker: str,
    index: int,
    sessions: int,
    daily: dict[str, list[trial6.DailyBar]],
) -> float:
    others = [name for name in TICKERS if name != ticker]
    returns: list[float] = []
    for offset in range(index - sessions + 1, index + 1):
        returns.append(statistics.mean(
            daily[name][offset].close_vnd / daily[name][offset - 1].close_vnd - 1
            for name in others
        ))
    return sum(returns)


def build_feature_cache(
    daily: dict[str, list[trial6.DailyBar]],
    calendar: Sequence[date],
) -> dict[tuple[str, int], Feature]:
    cache: dict[tuple[str, int], Feature] = {}
    permissive = trial6.Config(candidate_residual_z_max=100.0)
    for index in range(60, len(calendar)):
        for ticker in TICKERS:
            features, reasons = trial6.feature_vector(
                ticker, index, daily, permissive
            )
            bars = daily[ticker]
            closes20 = [bar.close_vnd for bar in bars[index - 19:index + 1]]
            closes50 = [bar.close_vnd for bar in bars[index - 49:index + 1]]
            valid = (
                features is not None
                and not any(
                    reason not in ("residual_not_low_enough",)
                    for reason in reasons
                )
            )
            cache[(ticker, index)] = Feature(
                index=index,
                trading_date=calendar[index],
                ticker=ticker,
                residual_z5=(
                    float(features["residual_z5"]) if features else 0.0
                ),
                residual_1=(
                    float(features["residual_1"]) if features else 0.0
                ),
                market_return20=market_return(ticker, index, 20, daily),
                atr_fraction=(
                    float(features["atr20_fraction"]) if features else 0.0
                ),
                close_up=bars[index].close_vnd > bars[index - 1].close_vnd,
                close_above_sma50=(
                    bars[index].close_vnd > statistics.mean(closes50)
                ),
                sma20_above_sma50=(
                    statistics.mean(closes20) > statistics.mean(closes50)
                ),
                valid=valid,
            )
    return cache


def signal_passes(feature: Feature, params: Parameters) -> bool:
    return (
        feature.valid
        and feature.close_above_sma50
        and feature.sma20_above_sma50
        and feature.close_up
        and feature.residual_1 > 0
        and feature.market_return20 > params.market_return20_min
        and feature.residual_z5 <= params.residual_z_max
    )


def simulate_campaign(
    ticker: str,
    signal_index: int,
    partition_end_index: int,
    daily: dict[str, list[trial6.DailyBar]],
    features: dict[tuple[str, int], Feature],
    params: Parameters,
    base: BaseConfig,
    partition: str,
) -> dict[str, object] | None:
    bars = daily[ticker]
    entry_index = signal_index + 1
    end_index = entry_index + params.maximum_horizon
    if end_index > partition_end_index or end_index >= len(bars):
        return None
    path = bars[entry_index:end_index + 1]
    if any(not bar.reset_verifiable or bar.reference_reset for bar in path):
        return None
    feature = features[(ticker, signal_index)]
    spacing = min(
        max(
            params.spacing_atr_multiplier * feature.atr_fraction,
            base.minimum_spacing,
        ),
        base.maximum_spacing,
    )
    initial_buy = path[0].open_vnd
    initial_target = round_to_hsx_tick(initial_buy * (1 + spacing), "sell")
    lower_buy = round_to_hsx_tick(initial_buy / (1 + spacing), "buy")
    lower_target = round_to_hsx_tick(initial_buy, "sell")
    hard_lower = round_to_hsx_tick(
        initial_buy / ((1 + spacing) ** params.stop_steps), "sell"
    )
    lots = [
        make_lot("initial", 0, initial_buy, initial_target, base)
    ]
    lower_pending = False
    lower_filled = False
    shutdown = False
    trend_exit = False
    risk_exit = False
    gap_exit = False
    time_exit = False
    exit_offset = params.maximum_horizon

    for offset, bar in enumerate(path):
        prior_index = entry_index + offset - 1
        prior_feature = features.get((ticker, prior_index))
        if (
            offset > 0
            and (
                prior_feature is None
                or not prior_feature.valid
                or not prior_feature.close_above_sma50
                or prior_feature.market_return20 <= 0
            )
        ):
            shutdown = trend_exit = True

        if shutdown:
            for lot in lots:
                if not lot.sold and offset >= lot.buy_offset + base.settlement_sessions:
                    sell(lot, bar.open_vnd, "trend_exit")
            if all(lot.sold for lot in lots):
                exit_offset = offset
                break
            continue

        if (
            lower_pending
            and params.lower_level_enabled
            and not lower_filled
            and offset <= params.maximum_horizon - base.settlement_sessions
        ):
            lower_pending = False
            if bar.open_vnd <= lower_target:
                lots.append(
                    make_lot("lower", offset, bar.open_vnd, lower_target, base)
                )
                lower_filled = True

        if bar.open_vnd <= hard_lower:
            shutdown = risk_exit = gap_exit = True
            risk_price = bar.open_vnd
        elif bar.low_vnd <= hard_lower:
            shutdown = risk_exit = True
            risk_price = hard_lower
        else:
            risk_price = 0
        if shutdown:
            for lot in lots:
                if not lot.sold and offset >= lot.buy_offset + base.settlement_sessions:
                    sell(lot, risk_price, "risk_exit")
            if all(lot.sold for lot in lots):
                exit_offset = offset
                break
            continue

        for lot in lots:
            if (
                not lot.sold
                and offset >= lot.buy_offset + base.settlement_sessions
                and bar.high_vnd >= lot.target
            ):
                sell(lot, lot.target, "target")

        if (
            params.lower_level_enabled
            and not lower_filled
            and not lower_pending
            and bar.low_vnd <= lower_buy
            and bar.close_vnd > lower_buy
            and bar.close_vnd > bar.open_vnd
        ):
            lower_pending = True

        if all(lot.sold for lot in lots):
            exit_offset = offset
            break

        if offset == params.maximum_horizon:
            time_exit = any(not lot.sold for lot in lots)
            for lot in lots:
                if not lot.sold:
                    sell(lot, bar.close_vnd, "time_exit")

    pnl = sum(
        sale_cash(lot.sale_price, base) - lot.acquisition for lot in lots
    )
    double_pnl = sum(
        sale_cash(lot.sale_price, base, 2.0) - lot.double_acquisition
        for lot in lots
    )
    acquisition_total = sum(lot.acquisition for lot in lots)
    target_gain = sum(
        max(sale_cash(lot.sale_price, base) - lot.acquisition, 0)
        for lot in lots if lot.sale_reason == "target"
    )
    other_loss = -sum(
        min(sale_cash(lot.sale_price, base) - lot.acquisition, 0)
        for lot in lots if lot.sale_reason != "target"
    )
    return {
        "partition": partition,
        "ticker": ticker,
        "sector": SECTORS[ticker],
        "signal_date": bars[signal_index].trading_date.isoformat(),
        "entry_date": path[0].trading_date.isoformat(),
        "exit_date": path[exit_offset].trading_date.isoformat(),
        "residual_z5": feature.residual_z5,
        "residual_1": feature.residual_1,
        "market_return20": feature.market_return20,
        "spacing_fraction": spacing,
        "lower_level_enabled": params.lower_level_enabled,
        "lower_level_filled": lower_filled,
        "buy_count": len(lots),
        "target_sales": sum(lot.sale_reason == "target" for lot in lots),
        "trend_exit": trend_exit,
        "risk_exit": risk_exit,
        "gap_exit": gap_exit,
        "time_exit": time_exit,
        "net_pnl_vnd": pnl,
        "double_cost_pnl_vnd": double_pnl,
        "campaign_return": pnl / acquisition_total,
        "normal_target_gain_vnd": target_gain,
        "other_loss_vnd": other_loss,
    }


def select_campaigns(
    candidates: list[dict[str, object]],
    calendar: Sequence[date],
    base: BaseConfig,
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
        available = base.maximum_concurrent - len(active)
        for row in sorted(
            by_entry[entry_date],
            key=lambda item: (
                float(item["residual_z5"]),
                -float(item["residual_1"]),
                str(item["ticker"]),
            ),
        ):
            if available <= 0:
                break
            ticker, sector = str(row["ticker"]), str(row["sector"])
            if ticker in tickers or sector in sectors:
                continue
            if current <= cooldown.get(ticker, -1):
                continue
            selected.append(row)
            active.append(row)
            tickers.add(ticker)
            sectors.add(sector)
            cooldown[ticker] = (
                indices[date.fromisoformat(str(row["exit_date"]))]
                + base.cooldown_sessions
            )
            available -= 1
    return selected


def run_partition(
    start: date,
    end: date,
    partition: str,
    daily: dict[str, list[trial6.DailyBar]],
    calendar: Sequence[date],
    features: dict[tuple[str, int], Feature],
    params: Parameters,
    base: BaseConfig,
) -> list[dict[str, object]]:
    indices = {value: index for index, value in enumerate(calendar)}
    start_index, end_index = indices[start], indices[end]
    candidates: list[dict[str, object]] = []
    for signal_index in range(max(start_index, 60), end_index):
        if signal_index + 1 > end_index:
            continue
        for ticker in TICKERS:
            feature = features[(ticker, signal_index)]
            if not signal_passes(feature, params):
                continue
            row = simulate_campaign(
                ticker, signal_index, end_index, daily, features,
                params, base, partition,
            )
            if row is not None:
                candidates.append(row)
    return select_campaigns(candidates, calendar, base)


def profit_factor(pnls: Sequence[int]) -> float | str | None:
    gains = sum(value for value in pnls if value > 0)
    losses = -sum(value for value in pnls if value < 0)
    if losses == 0:
        return "Infinity" if gains else None
    return gains / losses


def quantile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return (
        ordered[lower] * (upper - position)
        + ordered[upper] * (position - lower)
    )


def summarize_search(
    rows: Sequence[dict[str, object]], params: Parameters
) -> dict[str, object]:
    pnls = [int(row["net_pnl_vnd"]) for row in rows]
    doubles = [int(row["double_cost_pnl_vnd"]) for row in rows]
    returns = [float(row["campaign_return"]) for row in rows]
    by_half: dict[str, int] = defaultdict(int)
    for row in rows:
        entry = date.fromisoformat(str(row["entry_date"]))
        key = f"{entry.year}-H{1 if entry.month <= 6 else 2}"
        by_half[key] += int(row["net_pnl_vnd"])
    positive_half_fraction = (
        sum(value > 0 for value in by_half.values()) / len(by_half)
        if by_half else 0.0
    )
    pf = profit_factor(pnls)
    return_sharpe = (
        statistics.mean(returns) / statistics.stdev(returns) * math.sqrt(len(returns))
        if len(returns) > 1 and statistics.stdev(returns) > 0 else 0.0
    )
    worst = min(returns) if returns else 0.0
    p10 = quantile(returns, 0.10)
    score = return_sharpe - 0.50 * abs(worst) - 0.25 * abs(p10)
    eligible = (
        len(rows) >= 25
        and sum(pnls) > 0
        and bool(pnls) and statistics.median(pnls) > 0
        and (
            pf == "Infinity"
            or isinstance(pf, float) and pf >= 1.10
        )
        and bool(pnls) and sum(pnls) - max(pnls) > 0
        and positive_half_fraction >= 0.60
    )
    return {
        "rank": "",
        "eligible": eligible,
        "parameter_json": params.key(),
        **asdict(params),
        "executed_campaigns": len(rows),
        "total_pnl_vnd": sum(pnls),
        "median_pnl_vnd": statistics.median(pnls) if pnls else None,
        "profit_factor": pf,
        "double_cost_pnl_vnd": sum(doubles),
        "best_removed_pnl_vnd": sum(pnls) - max(pnls) if pnls else 0,
        "positive_halfyear_fraction": positive_half_fraction,
        "worst_return": worst,
        "p10_return": p10,
        "campaign_return_sharpe": return_sharpe,
        "robust_score": score,
    }


def validation_report(
    rows: Sequence[dict[str, object]]
) -> dict[str, object]:
    pnls = [int(row["net_pnl_vnd"]) for row in rows]
    doubles = [int(row["double_cost_pnl_vnd"]) for row in rows]
    target = sum(int(row["normal_target_gain_vnd"]) for row in rows)
    other = sum(int(row["other_loss_vnd"]) for row in rows)
    pf = profit_factor(pnls)
    gates = {
        "minimum_10_campaigns": len(rows) >= 10,
        "positive_total_pnl": sum(pnls) > 0,
        "positive_median_pnl": bool(pnls) and statistics.median(pnls) > 0,
        "profit_factor_at_least_1": (
            pf == "Infinity" or isinstance(pf, float) and pf >= 1.0
        ),
        "positive_doubled_cost_pnl": sum(doubles) > 0,
        "positive_after_best_removed": (
            bool(pnls) and sum(pnls) - max(pnls) > 0
        ),
        "target_gains_cover_other_losses": target >= other,
        "worst_loss_within_1_5pct_nav": (
            bool(pnls) and min(pnls) >= -1_500_000
        ),
    }
    return {
        "status": (
            "passed_internal_validation"
            if all(gates.values()) else "rejected_internal_validation"
        ),
        "advance_to_final_oos": all(gates.values()),
        "gates": gates,
        "metrics": {
            "campaigns": len(rows),
            "total_pnl_vnd": sum(pnls),
            "median_pnl_vnd": statistics.median(pnls) if pnls else None,
            "profit_factor": pf,
            "double_cost_pnl_vnd": sum(doubles),
            "best_removed_pnl_vnd": sum(pnls) - max(pnls) if pnls else 0,
            "target_gains_vnd": target,
            "other_losses_vnd": other,
            "worst_pnl_vnd": min(pnls) if pnls else None,
            "ticker_pnl_vnd": group_pnl(rows, "ticker"),
        },
    }


def group_pnl(
    rows: Sequence[dict[str, object]], field: str
) -> dict[str, int]:
    grouped: dict[str, int] = defaultdict(int)
    for row in rows:
        grouped[str(row[field])] += int(row["net_pnl_vnd"])
    return dict(sorted(grouped.items()))


def write_csv(
    path: Path, rows: Sequence[dict[str, object]], fields: Sequence[str]
) -> None:
    with path.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_all_daily_for_final(
    path: Path,
) -> tuple[dict[str, list[trial6.DailyBar]], list[date]]:
    raw: dict[str, list[dict[str, str]]] = defaultdict(list)
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = trial6.DAILY_REQUIRED.difference(reader.fieldnames or ())
        if missing:
            raise ValueError(f"Daily input missing columns: {sorted(missing)}")
        for row in reader:
            ticker = row["tickersymbol"].strip().upper()
            if ticker not in TICKERS:
                continue
            if row["primary_split"].strip() not in ("development", "final_test"):
                raise ValueError("Unexpected primary split")
            if row["exchangeid"].strip().upper() != "HSX":
                raise ValueError("Non-HSX final input")
            if row["instrumenttype"].strip().lower() != "stock":
                raise ValueError("Non-stock final input")
            raw[ticker].append(row)
    result: dict[str, list[trial6.DailyBar]] = {}
    calendars: list[list[date]] = []
    for ticker in TICKERS:
        rows = sorted(raw[ticker], key=lambda row: row["datetime"])
        bars: list[trial6.DailyBar] = []
        previous_close: int | None = None
        seen: set[date] = set()
        for row in rows:
            trading_date = date.fromisoformat(row["datetime"][:10])
            if trading_date in seen:
                raise ValueError(f"Duplicate daily key: {ticker} {trading_date}")
            seen.add(trading_date)
            open_vnd = trial6.quote_to_vnd(row["open"])
            high_vnd = trial6.quote_to_vnd(row["high"])
            low_vnd = trial6.quote_to_vnd(row["low"])
            close_vnd = trial6.quote_to_vnd(row["close"])
            ceiling = trial6.optional_quote_to_vnd(row["ceiling"])
            floor = trial6.optional_quote_to_vnd(row["floor"])
            verifiable, reset = trial6.inferred_reference_reset(
                previous_close, ceiling, floor
            )
            bars.append(trial6.DailyBar(
                trading_date, ticker, open_vnd, high_vnd, low_vnd, close_vnd,
                ceiling, floor, int(float(row["matched_quantity"])),
                verifiable, reset,
            ))
            previous_close = close_vnd
        result[ticker] = bars
        calendars.append([bar.trading_date for bar in bars])
    if any(calendar != calendars[0] for calendar in calendars[1:]):
        raise ValueError("Full-data ticker calendars differ")
    calendar = calendars[0]
    if FINAL_START not in calendar or FINAL_END not in calendar:
        raise ValueError("Final OOS boundaries missing")
    return result, calendar


def optimize_validate(output_dir: Path) -> dict[str, object]:
    if output_dir.exists():
        raise FileExistsError(f"Create-only Trial 11 output exists: {output_dir}")
    output_dir.mkdir(parents=True)
    daily_path = Path("data_algotradeDB_split.csv")
    prereg = Path(
        "research_log/TRIAL11_TREND_CONDITIONED_GRID_PREREGISTRATION.md"
    )
    daily, calendar, final_range = trial6.read_development_daily(
        daily_path, TICKERS
    )
    if calendar[0] != IS_START or calendar[-1] != VALIDATION_END:
        raise ValueError("Unexpected development calendar boundaries")
    features = build_feature_cache(daily, calendar)
    base = BaseConfig()
    search_rows: list[dict[str, object]] = []
    campaigns_by_key: dict[str, list[dict[str, object]]] = {}
    for params in parameter_space():
        campaigns = run_partition(
            IS_START, IS_END, "in_sample", daily, calendar, features,
            params, base,
        )
        campaigns_by_key[params.key()] = campaigns
        search_rows.append(summarize_search(campaigns, params))
    eligible = [row for row in search_rows if bool(row["eligible"])]
    eligible.sort(
        key=lambda row: (
            -float(row["robust_score"]),
            -int(row["double_cost_pnl_vnd"]),
            -int(row["total_pnl_vnd"]),
            -int(row["executed_campaigns"]),
            str(row["parameter_json"]),
        )
    )
    for rank, row in enumerate(eligible, 1):
        row["rank"] = rank
    chosen_row = eligible[0] if eligible else None
    validation_rows: list[dict[str, object]] = []
    if chosen_row:
        chosen = Parameters(**{
            field: chosen_row[field]
            for field in asdict(next(iter(parameter_space())))
        })
        validation_rows = run_partition(
            VALIDATION_START, VALIDATION_END, "internal_validation",
            daily, calendar, features, chosen, base,
        )
        validation = validation_report(validation_rows)
    else:
        chosen = None
        validation = {
            "status": "no_in_sample_configuration",
            "advance_to_final_oos": False,
            "gates": {},
            "metrics": {},
        }
    report = {
        "trial_id": TRIAL_ID,
        "status": validation["status"],
        "final_test_used": False,
        "final_test_range_detected_but_not_parsed": [
            final_range[0].isoformat(), final_range[1].isoformat()
        ],
        "search_configurations": len(search_rows),
        "eligible_in_sample_configurations": len(eligible),
        "selected_parameters": asdict(chosen) if chosen else None,
        "selected_in_sample_metrics": chosen_row,
        "internal_validation": validation,
    }
    write_csv(output_dir / "optimization_results.csv", search_rows, SEARCH_FIELDS)
    if chosen:
        write_csv(
            output_dir / "selected_in_sample_campaigns.csv",
            campaigns_by_key[chosen.key()],
            CAMPAIGN_FIELDS,
        )
    else:
        write_csv(output_dir / "selected_in_sample_campaigns.csv", [], CAMPAIGN_FIELDS)
    write_csv(
        output_dir / "internal_validation_campaigns.csv",
        validation_rows,
        CAMPAIGN_FIELDS,
    )
    (output_dir / "development_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if validation["advance_to_final_oos"] and chosen:
        lock = {
            "trial_id": TRIAL_ID,
            "selected_parameters": asdict(chosen),
            "base_config": asdict(base),
            "development_report_sha256": file_sha(
                output_dir / "development_report.json"
            ),
            "implementation_sha256": file_sha(Path(__file__)),
            "preregistration_sha256": file_sha(prereg),
            "daily_input_sha256": file_sha(daily_path),
            "final_oos_start": FINAL_START.isoformat(),
            "final_oos_end": FINAL_END.isoformat(),
        }
        (output_dir / "FINAL_OOS_CONFIG_LOCK.json").write_text(
            json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return report


def run_final_oos(
    development_dir: Path,
    final_output_dir: Path,
) -> dict[str, object]:
    lock_path = development_dir / "FINAL_OOS_CONFIG_LOCK.json"
    if not lock_path.exists():
        raise PermissionError(
            "Final OOS is locked because internal validation did not pass"
        )
    if final_output_dir.exists():
        raise FileExistsError(
            f"Create-only final OOS output exists: {final_output_dir}"
        )
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    daily_path = Path("data_algotradeDB_split.csv")
    prereg = Path(
        "research_log/TRIAL11_TREND_CONDITIONED_GRID_PREREGISTRATION.md"
    )
    expected = {
        "implementation_sha256": file_sha(Path(__file__)),
        "preregistration_sha256": file_sha(prereg),
        "daily_input_sha256": file_sha(daily_path),
        "development_report_sha256": file_sha(
            development_dir / "development_report.json"
        ),
    }
    for field, value in expected.items():
        if lock.get(field) != value:
            raise ValueError(f"Final OOS lock mismatch: {field}")
    params = Parameters(**lock["selected_parameters"])
    base = BaseConfig(**lock["base_config"])
    daily, calendar = read_all_daily_for_final(daily_path)
    features = build_feature_cache(daily, calendar)
    campaigns = run_partition(
        FINAL_START, FINAL_END, "final_oos", daily, calendar, features,
        params, base,
    )
    diagnostic = validation_report(campaigns)
    required_gate_names = (
        "minimum_10_campaigns",
        "positive_total_pnl",
        "positive_median_pnl",
        "profit_factor_at_least_1",
        "positive_doubled_cost_pnl",
        "positive_after_best_removed",
        "target_gains_cover_other_losses",
    )
    passed = all(diagnostic["gates"][name] for name in required_gate_names)
    report = {
        "trial_id": TRIAL_ID,
        "status": "passed_final_oos" if passed else "failed_final_oos",
        "final_test_used": True,
        "selected_parameters": asdict(params),
        "final_gates": {
            name: diagnostic["gates"][name] for name in required_gate_names
        },
        "metrics": diagnostic["metrics"],
    }
    final_output_dir.mkdir(parents=True)
    write_csv(
        final_output_dir / "final_oos_campaigns.csv",
        campaigns,
        CAMPAIGN_FIELDS,
    )
    (final_output_dir / "final_oos_report.json").write_text(
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
        default=Path("data/trial11_trend_grid/development"),
    )
    args = parser.parse_args()
    if args.optimize_validate == args.final_oos:
        raise SystemExit("Choose exactly one of --optimize-validate or --final-oos")
    if args.optimize_validate:
        output_dir = args.output_dir or Path(
            "data/trial11_trend_grid/development"
        )
        report = optimize_validate(output_dir)
    else:
        output_dir = args.output_dir or Path(
            "data/trial11_trend_grid/final_oos"
        )
        report = run_final_oos(args.development_dir, output_dir)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
