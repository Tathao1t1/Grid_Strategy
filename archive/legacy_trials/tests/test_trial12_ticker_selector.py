from __future__ import annotations

import unittest
import tempfile
from datetime import date, timedelta
from pathlib import Path

import study_trial6_mean_reversion as trial6
import study_trial11_trend_grid as trial11
from study_trial12_ticker_selector import (
    Selector,
    add_months,
    score_tickers,
    selector_space,
    final_rotations,
    run_final_oos,
)


def sessions(start: date, count: int) -> list[date]:
    result: list[date] = []
    current = start
    while len(result) < count:
        if current.weekday() < 5:
            result.append(current)
        current += timedelta(days=1)
    return result


def valid_feature(ticker: str, index: int, day: date) -> trial11.Feature:
    return trial11.Feature(
        index, day, ticker, -1.0, 0.01, 0.03, 0.02,
        True, True, True, True,
    )


class SelectorTests(unittest.TestCase):
    def test_frozen_search_contains_24_selectors(self) -> None:
        values = selector_space()
        self.assertEqual(len(values), 24)
        self.assertEqual(len({item.key() for item in values}), 24)

    def test_month_arithmetic_is_calendar_based(self) -> None:
        self.assertEqual(add_months(date(2024, 3, 31), -1), date(2024, 2, 29))

    def test_future_campaign_cannot_enter_score(self) -> None:
        calendar = sessions(date(2023, 1, 2), 300)
        rotation_start = calendar[250]
        fold = trial6.Fold(
            "test",
            tuple(calendar[:250]),
            tuple(calendar[250:]),
        )
        features = {
            (ticker, 249): valid_feature(ticker, 249, calendar[249])
            for ticker in trial11.TICKERS
        }
        history_start = add_months(rotation_start, -12)
        library = [
            {
                "ticker": "SSI",
                "entry_date": history_start.isoformat(),
                "exit_date": calendar[200].isoformat(),
                "campaign_return": 0.02,
            },
            {
                "ticker": "SSI",
                "entry_date": calendar[100].isoformat(),
                "exit_date": calendar[210].isoformat(),
                "campaign_return": 0.03,
            },
            {
                "ticker": "SSI",
                "entry_date": calendar[245].isoformat(),
                "exit_date": calendar[255].isoformat(),
                "campaign_return": 10.0,
            },
        ]
        selected, scores = score_tickers(
            Selector(12, 5, 0.25, 1),
            fold, library, features, calendar, "test",
        )
        ssi = next(row for row in scores if row["ticker"] == "SSI")
        self.assertEqual(ssi["historical_campaigns"], 2)
        self.assertLess(ssi["ticker_mean_return"], 0.1)
        self.assertIn("SSI", selected)

    def test_final_rotations_are_non_overlapping(self) -> None:
        calendar = sessions(date(2025, 7, 14), 253)
        rotations = final_rotations(calendar)
        flattened = [value for fold in rotations for value in fold.oos_dates]
        self.assertEqual(len(flattened), len(set(flattened)))
        self.assertGreaterEqual(len(rotations), 5)

    def test_final_requires_validation_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(PermissionError):
                run_final_oos(root / "development", root / "final")


if __name__ == "__main__":
    unittest.main()
