from __future__ import annotations

import math
import unittest
from datetime import date, timedelta

from study_trial6_mean_reversion import (
    FEATURE_NAMES,
    Config,
    DailyBar,
    campaign_label,
    feature_vector,
    fit_logistic,
    select_campaigns,
)


def sessions(start: date, count: int) -> list[date]:
    result: list[date] = []
    current = start
    while len(result) < count:
        if current.weekday() < 5:
            result.append(current)
        current += timedelta(days=1)
    return result


def bar(day: date, ticker: str, close: int, *, open_: int | None = None,
        high: int | None = None, low: int | None = None,
        reset: bool = False) -> DailyBar:
    opening = close if open_ is None else open_
    return DailyBar(
        day, ticker, opening,
        max(opening, close) + 100 if high is None else high,
        min(opening, close) - 100 if low is None else low,
        close, close + 7_000, close - 7_000, 1_000_000, True, reset,
    )


class BarrierTests(unittest.TestCase):
    def test_downside_wins_ambiguous_daily_bar(self) -> None:
        config = Config()
        dates = sessions(date(2024, 1, 2), 11)
        bars = [bar(day, "VCB", 100_000) for day in dates]
        bars[0] = bar(
            dates[0], "VCB", 100_000, open_=100_000,
            high=103_000, low=97_000,
        )
        label, resets = campaign_label(bars, 0, 0.02, config)
        self.assertFalse(resets)
        self.assertEqual(label["exit_reason"], "downside_touch")
        self.assertFalse(label["target_first"])

    def test_gap_stop_executes_at_adverse_open(self) -> None:
        config = Config()
        dates = sessions(date(2024, 1, 2), 11)
        bars = [bar(day, "VCB", 100_000) for day in dates]
        bars[1] = bar(
            dates[1], "VCB", 94_000, open_=94_000,
            high=95_000, low=93_000,
        )
        label, _ = campaign_label(bars, 0, 0.02, config)
        self.assertEqual(label["exit_reason"], "downside_gap")
        self.assertEqual(label["exit_price_vnd"], 94_000)
        self.assertTrue(label["gap_down_exit"])

    def test_forward_reset_quarantines_label(self) -> None:
        config = Config()
        dates = sessions(date(2024, 1, 2), 11)
        bars = [bar(day, "VCB", 100_000) for day in dates]
        bars[4] = bar(dates[4], "VCB", 100_000, reset=True)
        label, resets = campaign_label(bars, 0, 0.02, config)
        self.assertIsNone(label)
        self.assertEqual(resets, (dates[4],))


class ModelTests(unittest.TestCase):
    def test_logistic_model_learns_ordering(self) -> None:
        config = Config(
            maximum_model_iterations=10_000,
            convergence_tolerance=1e-7,
        )
        features = [[float(value)] for value in range(-20, 21)]
        labels = [int(value > 0) for value in range(-20, 21)]
        model = fit_logistic(features, labels, config)
        self.assertTrue(model.converged)
        self.assertLess(model.probability([-10.0]), model.probability([10.0]))


class CausalityTests(unittest.TestCase):
    def test_future_mutation_does_not_change_features(self) -> None:
        config = Config(candidate_residual_z_max=100.0)
        dates = sessions(date(2023, 1, 2), 75)
        universe = {}
        for number, ticker in enumerate(config.universe):
            universe[ticker] = [
                bar(day, ticker, 50_000 + number * 2_000 + index * (20 + number))
                for index, day in enumerate(dates)
            ]
        before, reasons_before = feature_vector("VCB", 65, universe, config)
        changed = {ticker: list(rows) for ticker, rows in universe.items()}
        for ticker in config.universe:
            changed[ticker][66] = bar(dates[66], ticker, 10_000)
        after, reasons_after = feature_vector("VCB", 65, changed, config)
        self.assertEqual(reasons_before, reasons_after)
        self.assertEqual(before, after)
        self.assertEqual(tuple(before), FEATURE_NAMES)
        self.assertTrue(all(math.isfinite(value) for value in before.values()))


class SelectionTests(unittest.TestCase):
    def row(self, ticker: str, sector: str, entry: str, exit_: str,
            ev: float, probability: float) -> dict[str, object]:
        return {
            "ticker": ticker,
            "sector": sector,
            "entry_date": entry,
            "exit_date": exit_,
            "estimated_ev_vnd": ev,
            "predicted_probability": probability,
            "selected": False,
            "selection_rank": "",
        }

    def test_sector_cap_and_positive_ev(self) -> None:
        calendar = sessions(date(2024, 1, 2), 20)
        entry = calendar[0].isoformat()
        exit_ = calendar[3].isoformat()
        rows = [
            self.row("VCB", "banks", entry, exit_, 300, 0.8),
            self.row("MBB", "banks", entry, exit_, 250, 0.7),
            self.row("FPT", "technology", entry, exit_, 200, 0.7),
            self.row("HPG", "materials", entry, exit_, -1, 0.9),
        ]
        selected = select_campaigns(rows, calendar, Config())
        self.assertEqual({row["ticker"] for row in selected}, {"VCB", "FPT"})
        self.assertFalse(rows[1]["selected"])
        self.assertFalse(rows[3]["selected"])


if __name__ == "__main__":
    unittest.main()
