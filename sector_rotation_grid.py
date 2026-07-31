#!/usr/bin/env python3
"""Leakage-controlled bank/securities sector-rotation grid research.

Research sequence
-----------------
1. Develop and freeze the selector horizon on 2022 only.
2. Run the baseline in-sample strategy on 2023.
3. Optimize a compact grid parameter set on 2024 only.
4. Seal the configuration.
5. Open the January-June 2025 internal OOS block in a separate command.

The July 2025 onward ``final_test`` is never parsed by this module.

The repository does not contain an official VN-Index series.  Until one is
provided, market adjustment and chart benchmarking use an explicitly labelled
equal-weight proxy made from the six bank/securities stocks.  Stock residuals
use a leave-one-out version of that proxy.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import html
import json
import math
import statistics
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, time
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from grid_platform import (
    BacktestBroker,
    BrokerEvent,
    ExecutionPolicy,
    FeeSchedule,
    MarketSnapshot,
    Order,
    OrderStatus,
    OrderType,
    Side,
    TradingCalendar,
    hsx_tick_vnd,
    round_to_hsx_tick,
)


TRIAL_ID = "SECTOR-ROTATION-GRID-V1"
TICKERS = ("MBB", "SSI", "TCB", "VCB", "VND", "VPB")
SECTOR_BY_TICKER = {
    "MBB": "banks",
    "TCB": "banks",
    "VCB": "banks",
    "VPB": "banks",
    "SSI": "securities",
    "VND": "securities",
}
SECTORS = ("banks", "securities")
PRICE_MULTIPLIER = 1_000
HORIZON_CANDIDATES = (20, 40, 60)
INITIAL_CAPITAL_VND = 1_000_000_000
MINIMUM_DAILY_VALUE_VND = 10_000_000_000
MAXIMUM_SPREAD_BPS = 40.0
LATEST_20_RETURN_VETO = -0.08
LOOKBACK_DRAWDOWN_VETO = -0.15
MARKET_20_RETURN_VETO = -0.06
MARKET_60_DRAWDOWN_VETO = -0.12


@dataclass(frozen=True)
class DailyBar:
    trading_date: date
    ticker: str
    open_vnd: int
    high_vnd: int
    low_vnd: int
    close_vnd: int
    ceiling_vnd: int | None
    floor_vnd: int | None
    previous_close_vnd: int | None
    matched_quantity: int
    role: str

    @property
    def traded_value_vnd(self) -> int:
        return self.close_vnd * self.matched_quantity

    @property
    def reference_vnd(self) -> float | None:
        if self.ceiling_vnd is not None and self.floor_vnd is not None:
            return (self.ceiling_vnd + self.floor_vnd) / 2.0
        return (
            float(self.previous_close_vnd)
            if self.previous_close_vnd is not None
            else None
        )

    @property
    def adjusted_return(self) -> float:
        reference = self.reference_vnd
        return (
            self.close_vnd / reference - 1.0
            if reference is not None and reference > 0
            else 0.0
        )


@dataclass(frozen=True)
class SelectorFeature:
    cutoff: date
    ticker: str
    sector: str
    horizon: int
    beta: float
    efficiency_ratio: float
    residual_amplitude: float
    round_trip_hurdle: float
    net_amplitude: float
    reversal_rate: float
    reversal_events: int
    latest_20_return: float
    maximum_drawdown: float
    median_daily_value_vnd: float
    median_spread_bps: float
    eligible: bool
    exclusion_reasons: tuple[str, ...]
    score: float = 0.0


@dataclass(frozen=True)
class Selection:
    cutoff: date
    deployment_start: date
    deployment_end: date
    horizon: int
    selected_sector: str
    selected_tickers: tuple[str, ...]
    market_gate: bool
    market_gate_reasons: tuple[str, ...]
    features: tuple[SelectorFeature, ...]


@dataclass(frozen=True)
class GridConfig:
    levels: int = 4
    spacing_atr_multiplier: float = 1.0
    minimum_spacing: float = 0.008
    maximum_spacing: float = 0.025
    allocation_per_ticker: float = 0.45
    maximum_cells_per_level: int = 5
    maximum_selected_tickers: int = 2
    stop_buy_sessions_before_end: int = 9
    wind_down_sessions_before_end: int = 5

    def validate(self) -> None:
        if self.levels < 2 or self.levels > 8:
            raise ValueError("Grid levels must be between 2 and 8")
        if not 0 < self.minimum_spacing <= self.maximum_spacing < 0.1:
            raise ValueError("Invalid spacing limits")
        if self.spacing_atr_multiplier <= 0:
            raise ValueError("ATR multiplier must be positive")
        if not 0 < self.allocation_per_ticker < 0.5:
            raise ValueError("Per-ticker allocation must be below 50%")
        if not 1 <= self.maximum_cells_per_level <= 20:
            raise ValueError("Invalid maximum cells per level")
        if (
            self.allocation_per_ticker * self.maximum_selected_tickers
            >= 1.0
        ):
            raise ValueError("Grid must retain a cash reserve")
        if (
            self.stop_buy_sessions_before_end
            <= self.wind_down_sessions_before_end
        ):
            raise ValueError("New buys must stop before wind-down begins")


@dataclass
class LevelState:
    ticker: str
    month: str
    level_number: int
    cell_number: int
    buy_limit_vnd: int
    sell_target_vnd: int
    quantity: int
    campaign_id: str
    buy_order_id: str | None = None
    sell_order_id: str | None = None
    rearm_after: datetime | None = None
    disabled: bool = False
    disabled_reason: str = ""


@dataclass
class StrategyResult:
    role: str
    config: GridConfig
    horizon: int
    daily: list[dict[str, object]]
    rotations: list[dict[str, object]]
    fills: list[dict[str, object]]
    metrics: dict[str, object]


def quote_to_vnd(value: str) -> int:
    parsed = Decimal(value)
    return int(
        (parsed * PRICE_MULTIPLIER).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


def optional_quote_to_vnd(value: str) -> int | None:
    return quote_to_vnd(value) if value.strip() else None


def canonical_hash(value: object) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def quantile(values: Sequence[float], probability: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def cumulative_path(returns: Sequence[float]) -> list[float]:
    total = 0.0
    path = [0.0]
    for value in returns:
        total += math.log1p(max(value, -0.999999))
        path.append(total)
    return path


def efficiency_ratio(path: Sequence[float]) -> float:
    if len(path) < 2:
        return 1.0
    travelled = sum(
        abs(path[index] - path[index - 1])
        for index in range(1, len(path))
    )
    return abs(path[-1] - path[0]) / travelled if travelled else 1.0


def maximum_drawdown_from_returns(returns: Sequence[float]) -> float:
    wealth = 1.0
    high = 1.0
    worst = 0.0
    for value in returns:
        wealth *= 1.0 + value
        high = max(high, wealth)
        worst = min(worst, wealth / high - 1.0)
    return worst


def compounded_return(returns: Sequence[float]) -> float:
    wealth = 1.0
    for value in returns:
        wealth *= 1.0 + value
    return wealth - 1.0


def estimate_beta(stock: Sequence[float], market: Sequence[float]) -> float:
    if len(stock) != len(market) or len(stock) < 5:
        return 1.0
    market_mean = statistics.mean(market)
    stock_mean = statistics.mean(stock)
    variance = sum((value - market_mean) ** 2 for value in market)
    if variance <= 1e-12:
        return 1.0
    covariance = sum(
        (market[index] - market_mean) * (stock[index] - stock_mean)
        for index in range(len(stock))
    )
    # A clamp prevents one unstable short sample from dominating selection.
    return min(3.0, max(-1.0, covariance / variance))


def rank_percentiles(
    features: Sequence[SelectorFeature],
) -> list[SelectorFeature]:
    eligible = [feature for feature in features if feature.eligible]
    if not eligible:
        return list(features)

    def percentile(value: float, values: Sequence[float]) -> float:
        if len(values) == 1:
            return 1.0
        ordered = sorted(values)
        lower_count = sum(item < value for item in ordered)
        equal_count = sum(item == value for item in ordered)
        return (
            lower_count + 0.5 * max(0, equal_count - 1)
        ) / (len(ordered) - 1)

    er_values = [-feature.efficiency_ratio for feature in eligible]
    amplitude_values = [feature.net_amplitude for feature in eligible]
    reversal_values = [feature.reversal_rate for feature in eligible]
    scores = {
        feature.ticker: statistics.mean(
            (
                percentile(-feature.efficiency_ratio, er_values),
                percentile(feature.net_amplitude, amplitude_values),
                percentile(feature.reversal_rate, reversal_values),
            )
        )
        for feature in eligible
    }
    return [
        SelectorFeature(
            **{
                **asdict(feature),
                "score": scores.get(feature.ticker, 0.0),
            }
        )
        for feature in features
    ]


class DataStore:
    def __init__(
        self,
        daily_path: Path,
        assignments_path: Path,
        spread_cache_path: Path,
        minute_dir: Path,
    ) -> None:
        self.daily_path = daily_path
        self.assignments_path = assignments_path
        self.spread_cache_path = spread_cache_path
        self.minute_dir = minute_dir
        self.role_by_date = self._load_assignments()
        self.bars_by_ticker, self.bars_by_date = self._load_daily()
        self.calendar = tuple(sorted(self.bars_by_date))
        self.spread_by_ticker_date = self._load_or_build_spreads()

    def _load_assignments(self) -> dict[date, str]:
        result: dict[date, str] = {}
        with self.assignments_path.open(
            newline="", encoding="utf-8"
        ) as handle:
            for row in csv.DictReader(handle):
                result[date.fromisoformat(row["trading_date"])] = row[
                    "research_role"
                ]
        return result

    def _load_daily(
        self,
    ) -> tuple[dict[str, list[DailyBar]], dict[date, dict[str, DailyBar]]]:
        by_ticker: dict[str, list[DailyBar]] = defaultdict(list)
        by_date: dict[date, dict[str, DailyBar]] = defaultdict(dict)
        previous_close: dict[str, int] = {}
        with self.daily_path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                ticker = row["tickersymbol"].strip().upper()
                if ticker not in TICKERS:
                    continue
                trading_date = date.fromisoformat(row["datetime"])
                role = self.role_by_date.get(trading_date)
                # Numeric final-test values are deliberately never parsed.
                if role == "locked_final_test" or role is None:
                    continue
                bar = DailyBar(
                    trading_date=trading_date,
                    ticker=ticker,
                    open_vnd=quote_to_vnd(row["open"]),
                    high_vnd=quote_to_vnd(row["high"]),
                    low_vnd=quote_to_vnd(row["low"]),
                    close_vnd=quote_to_vnd(row["close"]),
                    ceiling_vnd=optional_quote_to_vnd(row["ceiling"]),
                    floor_vnd=optional_quote_to_vnd(row["floor"]),
                    previous_close_vnd=previous_close.get(ticker),
                    matched_quantity=int(row["matched_quantity"]),
                    role=role,
                )
                by_ticker[ticker].append(bar)
                by_date[trading_date][ticker] = bar
                previous_close[ticker] = bar.close_vnd
        for trading_date, rows in by_date.items():
            if set(rows) != set(TICKERS):
                raise ValueError(
                    f"Incomplete six-stock universe on {trading_date}"
                )
        return dict(by_ticker), dict(by_date)

    def _load_or_build_spreads(self) -> dict[tuple[str, date], float]:
        if not self.spread_cache_path.exists():
            self._build_spread_cache()
        result: dict[tuple[str, date], float] = {}
        with self.spread_cache_path.open(
            newline="", encoding="utf-8"
        ) as handle:
            for row in csv.DictReader(handle):
                result[
                    (row["ticker"], date.fromisoformat(row["trading_date"]))
                ] = float(row["median_spread_bps"])
        return result

    def _build_spread_cache(self) -> None:
        observations: dict[tuple[str, date], list[float]] = defaultdict(list)
        allowed_dates = set(self.calendar)
        for path in sorted(self.minute_dir.glob("minute_bars_*.csv.gz")):
            period = path.name.removeprefix("minute_bars_")[:7]
            if period > "2025_06":
                continue
            with gzip.open(
                path, "rt", newline="", encoding="utf-8"
            ) as handle:
                for row in csv.DictReader(handle):
                    ticker = row["tickersymbol"].strip().upper()
                    if ticker not in TICKERS:
                        continue
                    trading_date = date.fromisoformat(row["trading_date"])
                    if trading_date not in allowed_dates:
                        continue
                    value = row.get("average_spread_bps", "").strip()
                    if value:
                        observations[(ticker, trading_date)].append(
                            float(value)
                        )
        self.spread_cache_path.parent.mkdir(parents=True, exist_ok=True)
        with self.spread_cache_path.open(
            "w", newline="", encoding="utf-8"
        ) as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=(
                    "trading_date",
                    "ticker",
                    "median_spread_bps",
                ),
            )
            writer.writeheader()
            for (ticker, trading_date), values in sorted(
                observations.items(), key=lambda item: (item[0][1], item[0][0])
            ):
                writer.writerow(
                    {
                        "trading_date": trading_date.isoformat(),
                        "ticker": ticker,
                        "median_spread_bps": statistics.median(values),
                    }
                )

    def role_dates(self, role: str) -> list[date]:
        return [
            trading_date
            for trading_date in self.calendar
            if self.role_by_date[trading_date] == role
        ]

    def dates_through(self, cutoff: date, count: int) -> list[date]:
        eligible = [value for value in self.calendar if value <= cutoff]
        return eligible[-count:]

    def previous_date(self, value: date) -> date:
        index = self.calendar.index(value)
        if index == 0:
            raise ValueError("No previous trading date")
        return self.calendar[index - 1]

    def returns(
        self, ticker: str, dates: Sequence[date]
    ) -> list[float]:
        return [self.bars_by_date[value][ticker].adjusted_return for value in dates]

    def market_returns(
        self,
        dates: Sequence[date],
        exclude: str | None = None,
    ) -> list[float]:
        members = [ticker for ticker in TICKERS if ticker != exclude]
        return [
            statistics.mean(
                self.bars_by_date[value][ticker].adjusted_return
                for ticker in members
            )
            for value in dates
        ]

    def median_spread(
        self, ticker: str, dates: Sequence[date]
    ) -> float:
        values = [
            self.spread_by_ticker_date[(ticker, value)]
            for value in dates
            if (ticker, value) in self.spread_by_ticker_date
        ]
        return statistics.median(values) if values else math.inf

    def atr_pct(self, ticker: str, cutoff: date, sessions: int = 20) -> float:
        dates = self.dates_through(cutoff, sessions + 1)
        if len(dates) < sessions + 1:
            return 0.02
        ranges: list[float] = []
        for index in range(1, len(dates)):
            bar = self.bars_by_date[dates[index]][ticker]
            previous = self.bars_by_date[dates[index - 1]][ticker]
            true_range = max(
                bar.high_vnd - bar.low_vnd,
                abs(bar.high_vnd - previous.close_vnd),
                abs(bar.low_vnd - previous.close_vnd),
            )
            ranges.append(true_range / previous.close_vnd)
        return statistics.mean(ranges[-sessions:])

    def minute_snapshots(
        self,
        dates: Sequence[date],
        tickers: Sequence[str],
    ) -> list[MarketSnapshot]:
        requested_dates = set(dates)
        requested_tickers = set(tickers)
        periods = sorted({value.strftime("%Y_%m") for value in dates})
        snapshots: list[MarketSnapshot] = []
        for period in periods:
            path = self.minute_dir / f"minute_bars_{period}.csv.gz"
            if not path.exists():
                raise FileNotFoundError(path)
            with gzip.open(
                path, "rt", newline="", encoding="utf-8"
            ) as handle:
                for row in csv.DictReader(handle):
                    ticker = row["tickersymbol"].strip().upper()
                    if ticker not in requested_tickers:
                        continue
                    trading_date = date.fromisoformat(row["trading_date"])
                    if trading_date not in requested_dates:
                        continue
                    snapshots.append(
                        MarketSnapshot(
                            event_time=datetime.fromisoformat(row["minute"]),
                            ticker=ticker,
                            best_bid_vnd=optional_quote_to_vnd(
                                row["last_best_bid"]
                            ),
                            best_bid_quantity=(
                                int(Decimal(row["last_best_bid_quantity"]))
                                if row["last_best_bid_quantity"].strip()
                                else None
                            ),
                            best_ask_vnd=optional_quote_to_vnd(
                                row["last_best_ask"]
                            ),
                            best_ask_quantity=(
                                int(Decimal(row["last_best_ask_quantity"]))
                                if row["last_best_ask_quantity"].strip()
                                else None
                            ),
                            last_price_vnd=optional_quote_to_vnd(
                                row["matched_close"]
                            ),
                            matched_quantity=int(
                                Decimal(row["matched_quantity"])
                            ),
                        )
                    )
        snapshots.sort(key=lambda row: (row.event_time, row.ticker))
        return snapshots


class Selector:
    def __init__(self, data: DataStore, horizon: int) -> None:
        if horizon not in HORIZON_CANDIDATES:
            raise ValueError(f"Unsupported selector horizon: {horizon}")
        self.data = data
        self.horizon = horizon

    def feature(self, ticker: str, cutoff: date) -> SelectorFeature:
        dates = self.data.dates_through(cutoff, self.horizon)
        if len(dates) < self.horizon:
            raise ValueError("Insufficient selector history")
        stock_returns = self.data.returns(ticker, dates)
        market_returns = self.data.market_returns(dates, exclude=ticker)
        beta = estimate_beta(stock_returns, market_returns)
        residual_returns = [
            stock_returns[index] - beta * market_returns[index]
            for index in range(len(dates))
        ]
        residual_path = cumulative_path(residual_returns)
        er = efficiency_ratio(residual_path)
        amplitude = quantile(residual_path, 0.90) - quantile(
            residual_path, 0.10
        )
        median_spread = self.data.median_spread(ticker, dates)
        spread_fraction = (
            median_spread / 10_000 if math.isfinite(median_spread) else 1.0
        )
        # 0.40% commission/tax + 0.10% two-sided haircut + full spread.
        hurdle = 0.004 + 0.001 + spread_fraction
        net_amplitude = amplitude - hurdle

        successes = 0
        events = 0
        forward = min(5, max(1, self.horizon // 4))
        minimum_deviation = hurdle / 2.0
        for index in range(10, len(residual_path) - forward):
            centre = statistics.mean(residual_path[index - 10 : index])
            deviation = residual_path[index] - centre
            if abs(deviation) < minimum_deviation:
                continue
            future_move = (
                residual_path[index + forward] - residual_path[index]
            )
            events += 1
            if (
                deviation * future_move < 0
                and abs(future_move) >= minimum_deviation
            ):
                successes += 1
        reversal_rate = successes / events if events else 0.0

        latest_returns = stock_returns[-min(20, len(stock_returns)) :]
        latest_20 = compounded_return(latest_returns)
        max_drawdown = maximum_drawdown_from_returns(stock_returns)
        median_value = statistics.median(
            self.data.bars_by_date[value][ticker].traded_value_vnd
            for value in dates[-min(60, len(dates)) :]
        )
        reasons: list[str] = []
        if net_amplitude <= 0:
            reasons.append("amplitude_below_cost_hurdle")
        if latest_20 <= LATEST_20_RETURN_VETO:
            reasons.append("severe_latest_20_return")
        if max_drawdown <= LOOKBACK_DRAWDOWN_VETO:
            reasons.append("severe_lookback_drawdown")
        if median_value < MINIMUM_DAILY_VALUE_VND:
            reasons.append("insufficient_daily_value")
        if median_spread > MAXIMUM_SPREAD_BPS:
            reasons.append("spread_too_wide")
        if events == 0:
            reasons.append("no_reversal_events")

        return SelectorFeature(
            cutoff=cutoff,
            ticker=ticker,
            sector=SECTOR_BY_TICKER[ticker],
            horizon=self.horizon,
            beta=beta,
            efficiency_ratio=er,
            residual_amplitude=amplitude,
            round_trip_hurdle=hurdle,
            net_amplitude=net_amplitude,
            reversal_rate=reversal_rate,
            reversal_events=events,
            latest_20_return=latest_20,
            maximum_drawdown=max_drawdown,
            median_daily_value_vnd=median_value,
            median_spread_bps=median_spread,
            eligible=not reasons,
            exclusion_reasons=tuple(reasons),
        )

    def market_gate(self, cutoff: date) -> tuple[bool, tuple[str, ...]]:
        dates = self.data.dates_through(cutoff, 60)
        market = self.data.market_returns(dates)
        latest20 = compounded_return(market[-20:])
        drawdown60 = maximum_drawdown_from_returns(market)
        reasons: list[str] = []
        if latest20 <= MARKET_20_RETURN_VETO:
            reasons.append("market_latest_20_return_veto")
        if drawdown60 <= MARKET_60_DRAWDOWN_VETO:
            reasons.append("market_60_drawdown_veto")
        return bool(reasons), tuple(reasons)

    def select(
        self,
        cutoff: date,
        deployment_dates: Sequence[date],
        *,
        apply_market_gate: bool = True,
    ) -> Selection:
        if not deployment_dates or cutoff >= deployment_dates[0]:
            raise ValueError(
                "Selection cutoff must precede the deployment"
            )
        raw = [self.feature(ticker, cutoff) for ticker in TICKERS]
        features = rank_percentiles(raw)
        gate, gate_reasons = self.market_gate(cutoff)
        sector_scores: dict[str, float] = {}
        for sector in SECTORS:
            eligible = sorted(
                (
                    feature
                    for feature in features
                    if feature.sector == sector and feature.eligible
                ),
                key=lambda feature: (-feature.score, feature.ticker),
            )
            if len(eligible) >= 2:
                sector_scores[sector] = statistics.median(
                    feature.score for feature in eligible[:2]
                )
        selected_sector = ""
        selected_tickers: tuple[str, ...] = ()
        if sector_scores and (not gate or not apply_market_gate):
            selected_sector = sorted(
                sector_scores,
                key=lambda sector: (-sector_scores[sector], sector),
            )[0]
            selected_tickers = tuple(
                feature.ticker
                for feature in sorted(
                    (
                        feature
                        for feature in features
                        if feature.sector == selected_sector
                        and feature.eligible
                    ),
                    key=lambda feature: (-feature.score, feature.ticker),
                )[:2]
            )
        return Selection(
            cutoff=cutoff,
            deployment_start=deployment_dates[0],
            deployment_end=deployment_dates[-1],
            horizon=self.horizon,
            selected_sector=selected_sector,
            selected_tickers=selected_tickers,
            market_gate=gate,
            market_gate_reasons=gate_reasons,
            features=tuple(features),
        )


def month_groups(dates: Sequence[date]) -> list[list[date]]:
    grouped: dict[tuple[int, int], list[date]] = defaultdict(list)
    for value in dates:
        grouped[(value.year, value.month)].append(value)
    return [grouped[key] for key in sorted(grouped)]


def future_quality(
    data: DataStore,
    feature: SelectorFeature,
    future_dates: Sequence[date],
) -> float:
    stock = data.returns(feature.ticker, future_dates)
    market = data.market_returns(future_dates, exclude=feature.ticker)
    residual = [
        stock[index] - feature.beta * market[index]
        for index in range(len(future_dates))
    ]
    path = cumulative_path(residual)
    net_amplitude = (
        quantile(path, 0.90)
        - quantile(path, 0.10)
        - feature.round_trip_hurdle
    )
    oscillation = 1.0 - efficiency_ratio(path)
    drawdown = maximum_drawdown_from_returns(stock)
    severe_penalty = max(0.0, -drawdown - 0.10)
    return net_amplitude * oscillation - severe_penalty


def develop_selector_horizon(
    data: DataStore,
) -> tuple[int, list[dict[str, object]]]:
    dates = data.role_dates("selector_development")
    groups = month_groups(dates)
    rows: list[dict[str, object]] = []
    for horizon in HORIZON_CANDIDATES:
        selector = Selector(data, horizon)
        qualities: list[float] = []
        active = 0
        qualified = 0
        selections: list[str] = []
        for group_index in range(1, len(groups)):
            deployment = groups[group_index]
            cutoff = data.previous_date(deployment[0])
            if len(data.dates_through(cutoff, horizon)) < horizon:
                continue
            selection = selector.select(
                cutoff, deployment, apply_market_gate=False
            )
            if not selection.selected_tickers:
                continue
            active += 1
            selections.append("|".join(selection.selected_tickers))
            by_ticker = {
                feature.ticker: feature for feature in selection.features
            }
            ticker_qualities = [
                future_quality(
                    data, by_ticker[ticker], deployment
                )
                for ticker in selection.selected_tickers
            ]
            qualities.extend(ticker_qualities)
            qualified += sum(value > 0 for value in ticker_qualities)
        mean_quality = statistics.mean(qualities) if qualities else -math.inf
        median_quality = (
            statistics.median(qualities) if qualities else -math.inf
        )
        positive_fraction = (
            qualified / len(qualities) if qualities else 0.0
        )
        turnover = (
            sum(
                selections[index] != selections[index - 1]
                for index in range(1, len(selections))
            )
            / max(1, len(selections) - 1)
        )
        rows.append(
            {
                "horizon": horizon,
                "active_rotations": active,
                "evaluated_tickers": len(qualities),
                "mean_future_quality": mean_quality,
                "median_future_quality": median_quality,
                "positive_future_quality_fraction": positive_fraction,
                "selection_turnover_fraction": turnover,
            }
        )
    valid = [
        row
        for row in rows
        if int(row["active_rotations"]) >= 4
        and int(row["evaluated_tickers"]) >= 8
    ]
    if not valid:
        raise RuntimeError("No selector horizon produced an adequate sample")
    best = sorted(
        valid,
        key=lambda row: (
            -float(row["median_future_quality"]),
            -float(row["positive_future_quality_fraction"]),
            float(row["selection_turnover_fraction"]),
            -int(row["horizon"]),
        ),
    )[0]
    return int(best["horizon"]), rows


def market_order_id(
    month: str, ticker: str, level: int, counter: int, side: str
) -> str:
    return f"{month}-{ticker}-L{level}-{side}-{counter:04d}"


def make_levels(
    data: DataStore,
    selection: Selection,
    config: GridConfig,
    account_equity_vnd: int,
) -> list[LevelState]:
    levels: list[LevelState] = []
    month = selection.deployment_start.strftime("%Y-%m")
    for ticker in selection.selected_tickers:
        centre = data.bars_by_date[selection.cutoff][ticker].close_vnd
        atr = data.atr_pct(ticker, selection.cutoff)
        spacing = min(
            config.maximum_spacing,
            max(
                config.minimum_spacing,
                atr * config.spacing_atr_multiplier,
            ),
        )
        slot_cash = account_equity_vnd * config.allocation_per_ticker
        cash_per_level = slot_cash / config.levels
        for level_number in range(1, config.levels + 1):
            buy_limit = round_to_hsx_tick(
                Decimal(centre)
                / (Decimal("1") + Decimal(str(spacing))) ** level_number,
                Side.BUY,
            )
            sell_target = round_to_hsx_tick(
                Decimal(centre)
                / (
                    (Decimal("1") + Decimal(str(spacing)))
                    ** (level_number - 1)
                ),
                Side.SELL,
            )
            affordable_cells = int(cash_per_level // (buy_limit * 100))
            cells = min(
                affordable_cells, config.maximum_cells_per_level
            )
            for cell_number in range(1, cells + 1):
                levels.append(
                    LevelState(
                        ticker=ticker,
                        month=month,
                        level_number=level_number,
                        cell_number=cell_number,
                        buy_limit_vnd=buy_limit,
                        sell_target_vnd=sell_target,
                        quantity=100,
                        campaign_id=(
                            f"{month}:{ticker}:L{level_number}:"
                            f"C{cell_number}"
                        ),
                    )
                )
    return levels


def cancel_if_open(broker: BacktestBroker, order_id: str | None) -> None:
    if order_id is None:
        return
    order = broker.orders[order_id]
    if order.status in {OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED}:
        broker.cancel(order_id)


def strategy_daily_metrics(
    daily: Sequence[dict[str, object]],
) -> dict[str, float]:
    if not daily:
        return {
            "net_return": 0.0,
            "benchmark_return": 0.0,
            "active_return": 0.0,
            "maximum_drawdown": 0.0,
            "benchmark_maximum_drawdown": 0.0,
            "annualized_sharpe": 0.0,
        }
    equities = [float(row["equity_vnd"]) for row in daily]
    benchmarks = [float(row["benchmark_equity_vnd"]) for row in daily]

    def drawdown(values: Sequence[float]) -> float:
        high = values[0]
        worst = 0.0
        for value in values:
            high = max(high, value)
            worst = min(worst, value / high - 1.0)
        return worst

    returns = [
        equities[index] / equities[index - 1] - 1.0
        for index in range(1, len(equities))
    ]
    mean_return = statistics.mean(returns) if returns else 0.0
    standard_deviation = (
        statistics.stdev(returns) if len(returns) > 1 else 0.0
    )
    sharpe = (
        math.sqrt(252) * mean_return / standard_deviation
        if standard_deviation > 0
        else 0.0
    )
    return {
        "net_return": equities[-1] / INITIAL_CAPITAL_VND - 1.0,
        "benchmark_return":
            benchmarks[-1] / INITIAL_CAPITAL_VND - 1.0,
        "active_return": (
            equities[-1] / INITIAL_CAPITAL_VND
            - benchmarks[-1] / INITIAL_CAPITAL_VND
        ),
        "maximum_drawdown": drawdown(equities),
        "benchmark_maximum_drawdown": drawdown(benchmarks),
        "annualized_sharpe": sharpe,
    }


def simulate_role(
    data: DataStore,
    role: str,
    horizon: int,
    config: GridConfig,
) -> StrategyResult:
    config.validate()
    role_dates = data.role_dates(role)
    if role not in {"in_sample", "optimization", "out_of_sample"}:
        raise ValueError(f"Role cannot be traded: {role}")
    if not role_dates:
        raise ValueError(f"No dates for role {role}")

    policy = ExecutionPolicy(
        maximum_spread_bps=Decimal(str(MAXIMUM_SPREAD_BPS)),
        maximum_minute_participation=Decimal("0.05"),
        execution_haircut_bps=Decimal("5"),
        limit_penetration_ticks=1,
        allow_partial_fills=False,
    )
    calendar_dates = tuple(
        value
        for value in data.calendar
        if value <= data.role_dates("unused_buffer")[-1]
    )
    broker = BacktestBroker(
        INITIAL_CAPITAL_VND,
        TradingCalendar(calendar_dates),
        policy,
        FeeSchedule(),
    )
    selector = Selector(data, horizon)
    daily_rows: list[dict[str, object]] = []
    rotation_rows: list[dict[str, object]] = []
    fill_rows: list[dict[str, object]] = []
    order_map: dict[str, tuple[LevelState, str]] = {}
    order_counter = 0
    benchmark_equity = float(INITIAL_CAPITAL_VND)
    previous_benchmark_date: date | None = None

    def submit_buy(level: LevelState, submitted_at: datetime) -> None:
        nonlocal order_counter
        if level.disabled or level.buy_order_id or level.sell_order_id:
            return
        order_counter += 1
        order_id = market_order_id(
            level.month,
            level.ticker,
            level.level_number,
            order_counter,
            "B",
        )
        broker.submit(
            Order(
                order_id=order_id,
                ticker=level.ticker,
                side=Side.BUY,
                quantity=level.quantity,
                order_type=OrderType.LIMIT,
                submitted_at=submitted_at,
                limit_price_vnd=level.buy_limit_vnd,
                campaign_id=level.campaign_id,
            )
        )
        level.buy_order_id = order_id
        order_map[order_id] = (level, "buy")

    def submit_sell(
        level: LevelState,
        submitted_at: datetime,
        market: bool,
        purpose: str,
    ) -> None:
        nonlocal order_counter
        if level.sell_order_id is not None:
            return
        quantity = broker.account.total_quantity(
            level.ticker, level.campaign_id
        )
        if quantity <= 0:
            return
        order_counter += 1
        order_id = market_order_id(
            level.month,
            level.ticker,
            level.level_number,
            order_counter,
            "MX" if market else "S",
        )
        broker.submit(
            Order(
                order_id=order_id,
                ticker=level.ticker,
                side=Side.SELL,
                quantity=quantity,
                order_type=OrderType.MARKET if market else OrderType.LIMIT,
                submitted_at=submitted_at,
                limit_price_vnd=(
                    None if market else level.sell_target_vnd
                ),
                campaign_id=level.campaign_id,
            )
        )
        level.sell_order_id = order_id
        order_map[order_id] = (level, purpose)

    for deployment_dates in month_groups(role_dates):
        cutoff = data.previous_date(deployment_dates[0])
        selection = selector.select(cutoff, deployment_dates)
        # This is the core no-overlap invariant for every rotation.
        if selection.cutoff >= selection.deployment_start:
            raise RuntimeError("Selection/deployment overlap detected")

        mark_before = broker.account.mark(
            datetime.combine(cutoff, time(15, 0)),
            {
                ticker: data.bars_by_date[cutoff][ticker].close_vnd
                for ticker in TICKERS
                if broker.account.total_quantity(ticker) > 0
            },
        )
        if any(
            broker.account.total_quantity(ticker) > 0 for ticker in TICKERS
        ) or mark_before.pending_cash_vnd:
            raise RuntimeError(
                f"Prior rotation was not flat and settled by {cutoff}"
            )
        levels = make_levels(
            data, selection, config, mark_before.equity_vnd
        )
        state_by_ticker: dict[str, list[LevelState]] = defaultdict(list)
        for level in levels:
            state_by_ticker[level.ticker].append(level)
            submit_buy(level, datetime.combine(cutoff, time(15, 0)))

        stop_buy_date = deployment_dates[
            max(0, len(deployment_dates) - config.stop_buy_sessions_before_end)
        ]
        wind_down_date = deployment_dates[
            max(0, len(deployment_dates) - config.wind_down_sessions_before_end)
        ]
        snapshots = data.minute_snapshots(
            deployment_dates, selection.selected_tickers
        )
        snapshots_by_date: dict[date, list[MarketSnapshot]] = defaultdict(list)
        for snapshot in snapshots:
            snapshots_by_date[snapshot.event_time.date()].append(snapshot)
        risk_disabled: set[str] = set()

        for trading_date in deployment_dates:
            if previous_benchmark_date is not None:
                benchmark_return = statistics.mean(
                    data.bars_by_date[trading_date][ticker].adjusted_return
                    for ticker in TICKERS
                )
                benchmark_equity *= 1.0 + benchmark_return
            previous_benchmark_date = trading_date

            previous_date = data.previous_date(trading_date)
            for ticker in selection.selected_tickers:
                historical = data.dates_through(previous_date, 20)
                recent_return = compounded_return(
                    data.returns(ticker, historical)
                )
                ticker_levels = state_by_ticker[ticker]
                hard_lower = min(
                    level.buy_limit_vnd for level in ticker_levels
                ) - hsx_tick_vnd(
                    min(level.buy_limit_vnd for level in ticker_levels)
                )
                if (
                    recent_return <= LATEST_20_RETURN_VETO
                    or data.bars_by_date[previous_date][ticker].close_vnd
                    <= hard_lower
                ):
                    risk_disabled.add(ticker)

            wind_down = trading_date >= wind_down_date
            stop_buys = trading_date >= stop_buy_date
            for ticker, ticker_levels in state_by_ticker.items():
                disabled = ticker in risk_disabled or wind_down
                for level in ticker_levels:
                    if stop_buys or disabled:
                        cancel_if_open(broker, level.buy_order_id)
                        level.buy_order_id = None
                    if disabled:
                        level.disabled = True
                        level.disabled_reason = (
                            "risk_exit"
                            if ticker in risk_disabled
                            else "scheduled_wind_down"
                        )
                        cancel_if_open(broker, level.sell_order_id)
                        level.sell_order_id = None

            for snapshot in snapshots_by_date.get(trading_date, []):
                ticker_levels = state_by_ticker[snapshot.ticker]
                for level in ticker_levels:
                    if (
                        not stop_buys
                        and not level.disabled
                        and level.buy_order_id is None
                        and level.sell_order_id is None
                        and (
                            level.rearm_after is None
                            or snapshot.event_time > level.rearm_after
                        )
                    ):
                        submit_buy(level, snapshot.event_time)
                    if level.disabled:
                        submit_sell(
                            level,
                            snapshot.event_time,
                            market=True,
                            purpose=level.disabled_reason,
                        )

                events = broker.process_snapshot(snapshot)
                for event in events:
                    if event.fill is None or event.order_id not in order_map:
                        continue
                    level, purpose = order_map[event.order_id]
                    fill = event.fill
                    fill_rows.append(
                        {
                            "role": role,
                            "rotation": level.month,
                            "ticker": fill.ticker,
                            "sector": SECTOR_BY_TICKER[fill.ticker],
                            "campaign_id": fill.campaign_id,
                            "level": level.level_number,
                            "event_time": fill.event_time.isoformat(),
                            "side": fill.side.value,
                            "purpose": purpose,
                            "quantity": fill.quantity,
                            "reference_book_price_vnd":
                                fill.reference_book_price_vnd,
                            "execution_price_vnd":
                                fill.execution_price_vnd,
                            "gross_notional_vnd":
                                fill.gross_notional_vnd,
                            "commission_vnd": fill.commission_vnd,
                            "sell_tax_vnd": fill.sell_tax_vnd,
                            "execution_friction_vnd":
                                fill.execution_friction_vnd,
                            "realized_pnl_vnd":
                                event.realized_pnl_vnd,
                        }
                    )
                    if fill.side is Side.BUY:
                        level.buy_order_id = None
                        submit_sell(
                            level,
                            fill.event_time,
                            market=False,
                            purpose="grid_target",
                        )
                    else:
                        level.sell_order_id = None
                        level.rearm_after = broker.account.calendar.settlement_at(
                            fill.event_time.date(), policy
                        )

            end_time = datetime.combine(trading_date, time(15, 0))
            for ticker, ticker_levels in state_by_ticker.items():
                if ticker in risk_disabled or wind_down:
                    for level in ticker_levels:
                        submit_sell(
                            level,
                            end_time,
                            market=True,
                            purpose=level.disabled_reason,
                        )
            marks = {
                ticker: data.bars_by_date[trading_date][ticker].close_vnd
                for ticker in TICKERS
                if broker.account.total_quantity(ticker) > 0
            }
            account = broker.account.mark(end_time, marks)
            daily_rows.append(
                {
                    "role": role,
                    "trading_date": trading_date.isoformat(),
                    "equity_vnd": account.equity_vnd,
                    "available_cash_vnd": account.available_cash_vnd,
                    "pending_cash_vnd": account.pending_cash_vnd,
                    "inventory_liquidation_value_vnd":
                        account.inventory_liquidation_value_vnd,
                    "realized_pnl_vnd": account.realized_pnl_vnd,
                    "unrealized_pnl_vnd": account.unrealized_pnl_vnd,
                    "benchmark_equity_vnd": int(benchmark_equity),
                    "selected_sector": selection.selected_sector,
                    "selected_tickers": "|".join(
                        selection.selected_tickers
                    ),
                }
            )

        final_date = deployment_dates[-1]
        final_mark = broker.account.mark(
            datetime.combine(final_date, time(15, 0)),
            {
                ticker: data.bars_by_date[final_date][ticker].close_vnd
                for ticker in TICKERS
                if broker.account.total_quantity(ticker) > 0
            },
        )
        open_quantity = sum(
            broker.account.total_quantity(ticker) for ticker in TICKERS
        )
        rotation_rows.append(
            {
                "role": role,
                "cutoff": cutoff.isoformat(),
                "maximum_feature_date": cutoff.isoformat(),
                "deployment_start": deployment_dates[0].isoformat(),
                "deployment_end": deployment_dates[-1].isoformat(),
                "selection_deployment_overlap": False,
                "selected_sector": selection.selected_sector,
                "selected_tickers": "|".join(selection.selected_tickers),
                "market_gate": selection.market_gate,
                "market_gate_reasons": "|".join(
                    selection.market_gate_reasons
                ),
                "grid_levels_created": len(levels),
                "ending_equity_vnd": final_mark.equity_vnd,
                "ending_open_quantity": open_quantity,
                "ending_pending_cash_vnd": final_mark.pending_cash_vnd,
                "valid_flat_and_settled": (
                    open_quantity == 0 and final_mark.pending_cash_vnd == 0
                ),
            }
        )
        if open_quantity or final_mark.pending_cash_vnd:
            raise RuntimeError(
                f"Rotation ending {final_date} is not flat and settled: "
                f"open_quantity={open_quantity}, "
                f"pending_cash_vnd={final_mark.pending_cash_vnd}"
            )

    base = strategy_daily_metrics(daily_rows)
    sells = [row for row in fill_rows if row["side"] == "SELL"]
    profits = [
        int(row["realized_pnl_vnd"])
        for row in sells
        if int(row["realized_pnl_vnd"]) > 0
    ]
    losses = [
        -int(row["realized_pnl_vnd"])
        for row in sells
        if int(row["realized_pnl_vnd"]) < 0
    ]
    gross_trading_pnl = sum(
        (
            int(row["gross_notional_vnd"])
            if row["side"] == "SELL"
            else -int(row["gross_notional_vnd"])
        )
        for row in fill_rows
    )
    commission = broker.account.total_commission_vnd
    sell_tax = broker.account.total_sell_tax_vnd
    reconciliation_difference = (
        broker.account.realized_pnl_vnd
        - (gross_trading_pnl - commission - sell_tax)
    )
    metrics: dict[str, object] = {
        **base,
        "starting_capital_vnd": INITIAL_CAPITAL_VND,
        "ending_equity_vnd": (
            int(daily_rows[-1]["equity_vnd"])
            if daily_rows
            else INITIAL_CAPITAL_VND
        ),
        "rotations": len(rotation_rows),
        "active_rotations": sum(
            bool(row["selected_tickers"]) for row in rotation_rows
        ),
        "fills": len(fill_rows),
        "completed_sales": len(sells),
        "profit_factor": (
            sum(profits) / sum(losses)
            if losses
            else ("infinity" if profits else 0.0)
        ),
        "positive_realized_pnl_vnd": sum(profits),
        "negative_realized_pnl_vnd": -sum(losses),
        "gross_trading_pnl_vnd": gross_trading_pnl,
        "net_realized_pnl_vnd": broker.account.realized_pnl_vnd,
        "commission_vnd": commission,
        "sell_tax_vnd": sell_tax,
        "execution_friction_vnd": sum(
            int(row["execution_friction_vnd"]) for row in fill_rows
        ),
        "account_reconciliation_difference_vnd":
            reconciliation_difference,
        "benchmark_name":
            "equal_weight_bank_securities_proxy_gross",
        "all_rotations_flat_and_settled": all(
            bool(row["valid_flat_and_settled"])
            for row in rotation_rows
        ),
        "selection_deployment_overlap_count": sum(
            bool(row["selection_deployment_overlap"])
            for row in rotation_rows
        ),
    }
    return StrategyResult(
        role=role,
        config=config,
        horizon=horizon,
        daily=daily_rows,
        rotations=rotation_rows,
        fills=fill_rows,
        metrics=metrics,
    )


def optimization_space() -> list[GridConfig]:
    return [
        GridConfig(
            levels=levels,
            spacing_atr_multiplier=multiplier,
            allocation_per_ticker=allocation,
            maximum_cells_per_level=cells,
        )
        for levels in (3, 4)
        for multiplier in (0.75, 1.0, 1.25)
        for allocation in (0.45,)
        for cells in (3, 5)
    ]


def optimization_score(metrics: Mapping[str, object]) -> float:
    return (
        float(metrics["net_return"])
        + 0.50 * float(metrics["maximum_drawdown"])
        + 0.25 * float(metrics["active_return"])
    )


def write_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(rows[0])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def save_result(output_dir: Path, result: StrategyResult) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "daily_account.csv", result.daily)
    write_csv(output_dir / "rotations.csv", result.rotations)
    write_csv(output_dir / "fills.csv", result.fills)
    (output_dir / "metrics.json").write_text(
        json.dumps(result.metrics, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def line_chart_svg(
    series: Sequence[tuple[str, Sequence[float], str]],
    title: str,
    y_label: str,
    width: int = 1000,
    height: int = 520,
) -> str:
    margin_left, margin_right = 90, 30
    margin_top, margin_bottom = 70, 65
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom
    all_values = [value for _, values, _ in series for value in values]
    if not all_values:
        all_values = [0.0, 1.0]
    low, high = min(all_values), max(all_values)
    if math.isclose(low, high):
        low -= 1.0
        high += 1.0
    padding = (high - low) * 0.08
    low -= padding
    high += padding
    count = max(len(values) for _, values, _ in series)

    def x_at(index: int) -> float:
        return margin_left + plot_width * index / max(1, count - 1)

    def y_at(value: float) -> float:
        return margin_top + plot_height * (high - value) / (high - low)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#f5f8fc"/>',
        f'<text x="{margin_left}" y="38" font-family="Arial" '
        f'font-size="25" font-weight="700" fill="#16233a">'
        f'{html.escape(title)}</text>',
    ]
    for grid_index in range(6):
        value = low + (high - low) * grid_index / 5
        y = y_at(value)
        parts.extend(
            [
                f'<line x1="{margin_left}" y1="{y:.1f}" '
                f'x2="{width-margin_right}" y2="{y:.1f}" '
                'stroke="#d9e1ec" stroke-width="1"/>',
                f'<text x="{margin_left-12}" y="{y+4:.1f}" '
                'text-anchor="end" font-family="Arial" font-size="12" '
                f'fill="#52627a">{value:,.2f}</text>',
            ]
        )
    for label, values, color in series:
        points = " ".join(
            f"{x_at(index):.1f},{y_at(value):.1f}"
            for index, value in enumerate(values)
        )
        parts.append(
            f'<polyline points="{points}" fill="none" stroke="{color}" '
            'stroke-width="3" stroke-linejoin="round"/>'
        )
    legend_x = margin_left
    for label, _, color in series:
        parts.extend(
            [
                f'<line x1="{legend_x}" y1="{height-25}" '
                f'x2="{legend_x+25}" y2="{height-25}" '
                f'stroke="{color}" stroke-width="4"/>',
                f'<text x="{legend_x+33}" y="{height-20}" '
                'font-family="Arial" font-size="13" fill="#33445d">'
                f'{html.escape(label)}</text>',
            ]
        )
        legend_x += 230
    parts.append(
        f'<text x="22" y="{height/2}" transform="rotate(-90 22 '
        f'{height/2})" font-family="Arial" font-size="13" '
        f'fill="#52627a">{html.escape(y_label)}</text>'
    )
    parts.append("</svg>")
    return "\n".join(parts)


def bar_chart_svg(
    labels: Sequence[str],
    values: Sequence[float],
    title: str,
    y_label: str,
    width: int = 1000,
    height: int = 520,
) -> str:
    margin_left, margin_right = 100, 30
    margin_top, margin_bottom = 70, 90
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom
    low = min(0.0, min(values, default=0.0))
    high = max(0.0, max(values, default=1.0))
    if math.isclose(low, high):
        high = low + 1.0
    padding = (high - low) * 0.1
    low -= padding
    high += padding

    def y_at(value: float) -> float:
        return margin_top + plot_height * (high - value) / (high - low)

    zero_y = y_at(0.0)
    slot = plot_width / max(1, len(values))
    bar_width = slot * 0.62
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#f5f8fc"/>',
        f'<text x="{margin_left}" y="38" font-family="Arial" '
        f'font-size="25" font-weight="700" fill="#16233a">'
        f'{html.escape(title)}</text>',
        f'<line x1="{margin_left}" y1="{zero_y:.1f}" '
        f'x2="{width-margin_right}" y2="{zero_y:.1f}" '
        'stroke="#73829a" stroke-width="1.5"/>',
    ]
    for index, (label, value) in enumerate(zip(labels, values)):
        x = margin_left + slot * index + (slot - bar_width) / 2
        y = min(zero_y, y_at(value))
        bar_height = abs(y_at(value) - zero_y)
        color = "#00a88f" if value >= 0 else "#d94f5c"
        parts.extend(
            [
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width:.1f}" '
                f'height="{max(1, bar_height):.1f}" fill="{color}" rx="3"/>',
                f'<text x="{x+bar_width/2:.1f}" y="{height-55}" '
                'text-anchor="middle" font-family="Arial" font-size="12" '
                f'fill="#33445d">{html.escape(label)}</text>',
                f'<text x="{x+bar_width/2:.1f}" '
                f'y="{y-7 if value >= 0 else y+bar_height+16:.1f}" '
                'text-anchor="middle" font-family="Arial" font-size="11" '
                f'fill="#33445d">{value:,.2f}</text>',
            ]
        )
    parts.append(
        f'<text x="22" y="{height/2}" transform="rotate(-90 22 '
        f'{height/2})" font-family="Arial" font-size="13" '
        f'fill="#52627a">{html.escape(y_label)}</text>'
    )
    parts.append("</svg>")
    return "\n".join(parts)


def generate_charts(result: StrategyResult, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    equity = [
        float(row["equity_vnd"]) / INITIAL_CAPITAL_VND * 100
        for row in result.daily
    ]
    benchmark = [
        float(row["benchmark_equity_vnd"]) / INITIAL_CAPITAL_VND * 100
        for row in result.daily
    ]
    cash = [100.0] * len(equity)
    (output_dir / "equity_vs_benchmark.svg").write_text(
        line_chart_svg(
            (
                ("Grid strategy", equity, "#0066cc"),
                ("Equal-weight proxy", benchmark, "#f28e2b"),
                ("Cash", cash, "#64748b"),
            ),
            f"{result.role.replace('_', ' ').title()}: Equity vs Benchmark",
            "Indexed equity (start = 100)",
        ),
        encoding="utf-8",
    )

    def drawdown(values: Sequence[float]) -> list[float]:
        high = values[0] if values else 1.0
        result_values: list[float] = []
        for value in values:
            high = max(high, value)
            result_values.append((value / high - 1.0) * 100)
        return result_values

    (output_dir / "drawdown.svg").write_text(
        line_chart_svg(
            (
                ("Grid strategy", drawdown(equity), "#0066cc"),
                ("Equal-weight proxy", drawdown(benchmark), "#f28e2b"),
            ),
            f"{result.role.replace('_', ' ').title()}: Drawdown",
            "Drawdown (%)",
        ),
        encoding="utf-8",
    )

    monthly: dict[str, list[float]] = defaultdict(list)
    for row in result.daily:
        monthly[str(row["trading_date"])[:7]].append(
            float(row["equity_vnd"])
        )
    month_labels = list(monthly)
    month_returns: list[float] = []
    previous = float(INITIAL_CAPITAL_VND)
    for month in month_labels:
        end = monthly[month][-1]
        month_returns.append((end / previous - 1.0) * 100)
        previous = end
    (output_dir / "monthly_returns.svg").write_text(
        bar_chart_svg(
            month_labels,
            month_returns,
            f"{result.role.replace('_', ' ').title()}: Monthly Returns",
            "Return (%)",
        ),
        encoding="utf-8",
    )

    attribution_labels = (
        "Gross trading",
        "Commission",
        "Sell tax",
        "Net realized",
    )
    attribution_values = (
        float(result.metrics["gross_trading_pnl_vnd"]) / 1_000_000,
        -float(result.metrics["commission_vnd"]) / 1_000_000,
        -float(result.metrics["sell_tax_vnd"]) / 1_000_000,
        float(result.metrics["net_realized_pnl_vnd"]) / 1_000_000,
    )
    (output_dir / "pnl_attribution.svg").write_text(
        bar_chart_svg(
            attribution_labels,
            attribution_values,
            f"{result.role.replace('_', ' ').title()}: P&L Attribution",
            "VND million",
        ),
        encoding="utf-8",
    )


def diagnostic_group_rows(
    fills: Sequence[Mapping[str, object]],
    field: str,
) -> list[dict[str, object]]:
    grouped: dict[str, list[int]] = defaultdict(list)
    for row in fills:
        if row["side"] != "SELL":
            continue
        grouped[str(row[field])].append(int(row["realized_pnl_vnd"]))
    output: list[dict[str, object]] = []
    for key, values in sorted(grouped.items()):
        gains = sum(value for value in values if value > 0)
        losses = -sum(value for value in values if value < 0)
        output.append(
            {
                field: key,
                "completed_sales": len(values),
                "winning_sales": sum(value > 0 for value in values),
                "losing_sales": sum(value < 0 for value in values),
                "net_pnl_vnd": sum(values),
                "average_pnl_vnd": (
                    statistics.mean(values) if values else 0.0
                ),
                "profit_factor": (
                    gains / losses
                    if losses
                    else ("infinity" if gains else 0.0)
                ),
            }
        )
    return output


def write_loss_diagnostics(
    result: StrategyResult,
    output_dir: Path,
) -> dict[str, object]:
    diagnostic_dir = output_dir / "diagnostics"
    diagnostic_dir.mkdir(parents=True, exist_ok=True)
    group_fields = ("purpose", "ticker", "sector", "level", "rotation")
    grouped_results: dict[str, list[dict[str, object]]] = {}
    for field in group_fields:
        rows = diagnostic_group_rows(result.fills, field)
        grouped_results[field] = rows
        write_csv(diagnostic_dir / f"pnl_by_{field}.csv", rows)

    transaction_costs = (
        int(result.metrics["commission_vnd"])
        + int(result.metrics["sell_tax_vnd"])
    )
    gross_trading = int(result.metrics["gross_trading_pnl_vnd"])
    purpose_pnl = {
        str(row["purpose"]): int(row["net_pnl_vnd"])
        for row in grouped_results["purpose"]
    }
    ticker_pnl = {
        str(row["ticker"]): int(row["net_pnl_vnd"])
        for row in grouped_results["ticker"]
    }
    rotation_pnl = {
        str(row["rotation"]): int(row["net_pnl_vnd"])
        for row in grouped_results["rotation"]
    }
    diagnosis: list[str] = []
    if gross_trading <= 0:
        diagnosis.append("no_positive_gross_grid_edge")
    elif transaction_costs >= gross_trading:
        diagnosis.append("positive_gross_edge_smaller_than_fees_and_tax")
    if purpose_pnl.get("risk_exit", 0) < 0:
        diagnosis.append("risk_exits_destroyed_value")
    if purpose_pnl.get("scheduled_wind_down", 0) < 0:
        diagnosis.append("scheduled_wind_down_destroyed_value")
    if ticker_pnl:
        worst_ticker = min(ticker_pnl, key=ticker_pnl.get)
    else:
        worst_ticker = ""
    if rotation_pnl:
        worst_rotation = min(rotation_pnl, key=rotation_pnl.get)
    else:
        worst_rotation = ""

    summary: dict[str, object] = {
        "role": result.role,
        "gross_trading_pnl_vnd": gross_trading,
        "commission_plus_tax_vnd": transaction_costs,
        "net_realized_pnl_vnd": int(
            result.metrics["net_realized_pnl_vnd"]
        ),
        "execution_friction_vnd": int(
            result.metrics["execution_friction_vnd"]
        ),
        "cost_to_positive_gross_edge": (
            transaction_costs / gross_trading
            if gross_trading > 0
            else None
        ),
        "pnl_by_exit_purpose_vnd": purpose_pnl,
        "worst_ticker": worst_ticker,
        "worst_ticker_pnl_vnd": ticker_pnl.get(worst_ticker, 0),
        "worst_rotation": worst_rotation,
        "worst_rotation_pnl_vnd": rotation_pnl.get(
            worst_rotation, 0
        ),
        "diagnostic_flags": diagnosis,
        "account_reconciliation_difference_vnd": int(
            result.metrics["account_reconciliation_difference_vnd"]
        ),
    }
    (diagnostic_dir / "diagnostic_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    for field in ("purpose", "ticker", "level"):
        rows = grouped_results[field]
        if not rows:
            continue
        (diagnostic_dir / f"pnl_by_{field}.svg").write_text(
            bar_chart_svg(
                [str(row[field]) for row in rows],
                [
                    float(row["net_pnl_vnd"]) / 1_000_000
                    for row in rows
                ],
                (
                    f"{result.role.replace('_', ' ').title()}: "
                    f"Net P&L by {field.replace('_', ' ').title()}"
                ),
                "VND million",
            ),
            encoding="utf-8",
        )
    return summary


def write_optimization_diagnostics(
    rows: Sequence[Mapping[str, object]],
    output_root: Path,
) -> None:
    diagnostic_dir = output_root / "optimization_diagnostics"
    diagnostic_dir.mkdir(parents=True, exist_ok=True)
    chart_labels = [f"C{index + 1}" for index in range(len(rows))]
    net_values = [
        (
            int(row["ending_equity_vnd"])
            - int(row["starting_capital_vnd"])
        )
        / 1_000_000
        for row in rows
    ]
    (diagnostic_dir / "configuration_net_pnl.svg").write_text(
        bar_chart_svg(
            chart_labels,
            net_values,
            "2024 Optimization: Net P&L of Every Configuration",
            "VND million",
        ),
        encoding="utf-8",
    )
    mapping = [
        {
            "chart_label": chart_labels[index],
            "levels": row["levels"],
            "spacing_atr_multiplier": row[
                "spacing_atr_multiplier"
            ],
            "maximum_cells_per_level": row[
                "maximum_cells_per_level"
            ],
            "net_pnl_vnd": (
                int(row["ending_equity_vnd"])
                - int(row["starting_capital_vnd"])
            ),
            "profit_factor": row["profit_factor"],
            "completed_sales": row["completed_sales"],
        }
        for index, row in enumerate(rows)
    ]
    write_csv(diagnostic_dir / "configuration_map.csv", mapping)
    summary = {
        "configurations_tested": len(rows),
        "profitable_configurations": sum(
            float(row["net_return"]) > 0 for row in rows
        ),
        "best_net_pnl_vnd": max(
            (
                int(row["ending_equity_vnd"])
                - int(row["starting_capital_vnd"])
            )
            for row in rows
        ),
        "worst_net_pnl_vnd": min(
            (
                int(row["ending_equity_vnd"])
                - int(row["starting_capital_vnd"])
            )
            for row in rows
        ),
        "interpretation": (
            "Loss is parameter-robust within the pre-registered search space"
            if not any(float(row["net_return"]) > 0 for row in rows)
            else "At least one configuration was profitable"
        ),
    }
    (diagnostic_dir / "optimization_diagnostic_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def development_run(data: DataStore, output_root: Path) -> str:
    output_root.mkdir(parents=True, exist_ok=True)
    best_horizon, horizon_rows = develop_selector_horizon(data)
    write_csv(output_root / "selector_horizon_results.csv", horizon_rows)
    selector_lock = {
        "trial_id": TRIAL_ID,
        "selector_development_role": "selector_development",
        "selector_development_last_date": "2022-12-30",
        "selected_horizon": best_horizon,
        "candidate_horizons": list(HORIZON_CANDIDATES),
        "selection_rule": (
            "equal_rank_residual_efficiency_net_amplitude_reversal"
        ),
    }
    (output_root / "selector_lock.json").write_text(
        json.dumps(selector_lock, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    baseline = GridConfig()
    in_sample = simulate_role(data, "in_sample", best_horizon, baseline)
    save_result(output_root / "in_sample", in_sample)
    generate_charts(in_sample, output_root / "in_sample" / "charts")
    write_loss_diagnostics(in_sample, output_root / "in_sample")

    optimization_rows: list[dict[str, object]] = []
    best_config: GridConfig | None = None
    best_score = -math.inf
    for config in optimization_space():
        result = simulate_role(data, "optimization", best_horizon, config)
        score = optimization_score(result.metrics)
        row = {
            **asdict(config),
            **result.metrics,
            "optimization_score": score,
        }
        optimization_rows.append(row)
        if (
            result.metrics["all_rotations_flat_and_settled"]
            and int(result.metrics["selection_deployment_overlap_count"]) == 0
            and score > best_score
        ):
            best_score = score
            best_config = config
    if best_config is None:
        raise RuntimeError("No valid optimization configuration")
    write_csv(output_root / "optimization_results.csv", optimization_rows)
    write_optimization_diagnostics(optimization_rows, output_root)
    best_optimization = simulate_role(
        data, "optimization", best_horizon, best_config
    )
    save_result(output_root / "optimization_best", best_optimization)
    generate_charts(
        best_optimization, output_root / "optimization_best" / "charts"
    )
    write_loss_diagnostics(
        best_optimization, output_root / "optimization_best"
    )

    frozen = {
        "trial_id": TRIAL_ID,
        "schema_version": "sector_rotation_grid.v1",
        "selector_horizon": best_horizon,
        "grid_config": asdict(best_config),
        "initial_capital_vnd": INITIAL_CAPITAL_VND,
        "tickers": list(TICKERS),
        "sectors": list(SECTORS),
        "benchmark":
            "equal_weight_bank_securities_proxy_gross",
        "execution_policy": {
            "board_lot": 100,
            "maximum_spread_bps": MAXIMUM_SPREAD_BPS,
            "maximum_minute_participation": 0.05,
            "execution_haircut_bps": 5,
            "limit_penetration_ticks": 1,
            "settlement_sessions": 2,
            "settlement_time": "13:00:00",
        },
        "fees": {
            "commission_rate": 0.0015,
            "sell_tax_rate": 0.0010,
        },
        "development_data_ends": "2024-12-31",
        "internal_oos_starts": "2025-01-02",
        "internal_oos_ends": "2025-06-30",
        "locked_final_test_opened": False,
    }
    development_gate_passed = (
        float(in_sample.metrics["net_return"]) > 0
        and float(best_optimization.metrics["net_return"]) > 0
        and float(best_optimization.metrics["profit_factor"]) > 1.0
        and int(best_optimization.metrics["active_rotations"]) >= 6
        and int(
            best_optimization.metrics[
                "account_reconciliation_difference_vnd"
            ]
        ) == 0
    )
    frozen["development_gate"] = {
        "passed": development_gate_passed,
        "requirements": {
            "positive_in_sample_return": True,
            "positive_optimization_return": True,
            "optimization_profit_factor_above_one": True,
            "minimum_active_optimization_rotations": 6,
            "zero_account_reconciliation_difference_vnd": True,
        },
        "oos_authorized": development_gate_passed,
    }
    digest = canonical_hash(frozen)
    payload = {**frozen, "frozen_config_sha256": digest}
    (output_root / "frozen_config.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return digest


def oos_run(
    data: DataStore,
    output_root: Path,
    confirmation_hash: str,
    *,
    allow_failed_gate_for_diagnosis: bool = False,
) -> StrategyResult:
    frozen_path = output_root / "frozen_config.json"
    payload = json.loads(frozen_path.read_text(encoding="utf-8"))
    expected = payload.pop("frozen_config_sha256")
    observed = canonical_hash(payload)
    if expected != observed or confirmation_hash != expected:
        raise RuntimeError("Frozen configuration confirmation failed")
    if (
        not payload["development_gate"]["oos_authorized"]
        and not allow_failed_gate_for_diagnosis
    ):
        raise RuntimeError(
            "Development gate failed; OOS remains reserved and cannot run"
        )
    if (output_root / "out_of_sample").exists():
        raise RuntimeError("OOS output already exists; refusing to rerun")
    config = GridConfig(**payload["grid_config"])
    result = simulate_role(
        data,
        "out_of_sample",
        int(payload["selector_horizon"]),
        config,
    )
    save_result(output_root / "out_of_sample", result)
    generate_charts(result, output_root / "out_of_sample" / "charts")
    diagnostic_summary = write_loss_diagnostics(
        result, output_root / "out_of_sample"
    )
    summary = {
        "trial_id": TRIAL_ID,
        "frozen_config_sha256": expected,
        "oos_opened_once": True,
        "opened_after_failed_development_gate": (
            not payload["development_gate"]["passed"]
        ),
        "opening_purpose": (
            "loss_diagnosis_not_performance_confirmation"
            if not payload["development_gate"]["passed"]
            else "performance_confirmation"
        ),
        "locked_final_test_opened": False,
        "metrics": result.metrics,
        "loss_diagnostics": diagnostic_summary,
    }
    (output_root / "oos_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run leakage-controlled sector-rotation grid research."
    )
    parser.add_argument("stage", choices=("develop", "oos"))
    parser.add_argument(
        "--daily",
        type=Path,
        default=Path("data_algotradeDB_split.csv"),
    )
    parser.add_argument(
        "--assignments",
        type=Path,
        default=Path(
            "data/sector_rotation_splits/date_assignments.csv"
        ),
    )
    parser.add_argument(
        "--minute-dir",
        type=Path,
        default=Path("data/minute_bars"),
    )
    parser.add_argument(
        "--spread-cache",
        type=Path,
        default=Path(
            "data/sector_rotation_grid/cache/daily_spreads.csv"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/sector_rotation_grid"),
    )
    parser.add_argument(
        "--confirm-frozen-config",
        default="",
        help="Required exact SHA-256 printed by the develop stage.",
    )
    parser.add_argument(
        "--diagnostic-oos-after-failed-gate",
        action="store_true",
        help=(
            "Explicitly open internal OOS once for loss diagnosis even when "
            "the development performance gate failed."
        ),
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    data = DataStore(
        args.daily,
        args.assignments,
        args.spread_cache,
        args.minute_dir,
    )
    if args.stage == "develop":
        digest = development_run(data, args.output)
        frozen = json.loads(
            (args.output / "frozen_config.json").read_text(
                encoding="utf-8"
            )
        )
        gate_passed = bool(frozen["development_gate"]["passed"])
        print(
            json.dumps(
                {
                    "stage": "develop",
                    "frozen_config_sha256": digest,
                    "development_gate_passed": gate_passed,
                    "next_action": (
                        (
                            "python3 sector_rotation_grid.py oos "
                            f"--confirm-frozen-config {digest}"
                        )
                        if gate_passed
                        else "STOP: preserve OOS and revise the hypothesis"
                    ),
                },
                indent=2,
            )
        )
    else:
        if not args.confirm_frozen_config:
            raise SystemExit("--confirm-frozen-config is required")
        result = oos_run(
            data,
            args.output,
            args.confirm_frozen_config,
            allow_failed_gate_for_diagnosis=(
                args.diagnostic_oos_after_failed_gate
            ),
        )
        print(json.dumps(result.metrics, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
