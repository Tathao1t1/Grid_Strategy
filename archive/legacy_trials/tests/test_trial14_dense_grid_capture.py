from __future__ import annotations

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import study_trial6_mean_reversion as trial6
from study_trial14_dense_grid_capture import (
    CaptureConfig,
    add_grid_targets,
    capture_space,
    run_final_oos,
    score_rows,
    select_campaigns,
    target_rate_quintile_spread,
)


def sessions(start: date, count: int) -> list[date]:
    values: list[date] = []
    current = start
    while len(values) < count:
        if current.weekday() < 5:
            values.append(current)
        current += timedelta(days=1)
    return values


def bar(day: date, ticker: str, price: int = 50_000) -> trial6.DailyBar:
    return trial6.DailyBar(
        day, ticker, price, price, price, price, None, None,
        1_000_000, True, False,
    )


class DenseGridCaptureTests(unittest.TestCase):
    def test_frozen_search_has_48_unique_configurations(self) -> None:
        values = capture_space()
        self.assertEqual(len(values), 48)
        self.assertEqual(len({value.key() for value in values}), 48)

    def test_profitable_trend_exit_is_not_grid_capture(self) -> None:
        calendar = sessions(date(2024, 1, 2), 2)
        daily = {"SSI": [bar(day, "SSI") for day in calendar]}
        rows = add_grid_targets([{
            "ticker": "SSI",
            "entry_date": calendar[1].isoformat(),
            "target_sales": 0,
            "normal_target_gain_vnd": 0,
            "other_loss_vnd": 0,
            "net_pnl_vnd": 100_000,
        }], daily, calendar)
        self.assertFalse(rows[0]["target_completion"])
        self.assertEqual(rows[0]["capture_return"], 0)
        self.assertEqual(rows[0]["inventory_loss_return"], 0)

    def test_score_penalizes_predicted_inventory_loss(self) -> None:
        source = [{
            "predicted_capture_return": 0.02,
            "predicted_inventory_loss_return": 0.01,
        }]
        scored = score_rows(
            source, CaptureConfig(10, 0.30, 1.50, 0.0, 1)
        )
        self.assertAlmostEqual(scored[0]["grid_score"], 0.005)

    def test_selection_requires_probability_and_positive_buffer(self) -> None:
        calendar = sessions(date(2024, 1, 2), 15)
        base = {
            "ticker": "SSI",
            "sector": "securities",
            "entry_date": calendar[2].isoformat(),
            "exit_date": calendar[5].isoformat(),
        }
        rows = [
            {
                **base,
                "predicted_target_probability": 0.29,
                "grid_score": 0.02,
            },
            {
                **base,
                "ticker": "FPT",
                "sector": "technology",
                "predicted_target_probability": 0.60,
                "grid_score": 0.0005,
            },
        ]
        selected = select_campaigns(
            rows, calendar, CaptureConfig(10, 0.30, 1.0, 0.001, 2)
        )
        self.assertEqual(selected, [])

    def test_target_rate_quintile_spread_uses_realized_targets(self) -> None:
        rows = [
            {"grid_score": float(index), "target_completion": index >= 8}
            for index in range(10)
        ]
        self.assertEqual(target_rate_quintile_spread(rows), 1.0)

    def test_final_requires_validation_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(PermissionError):
                run_final_oos(root / "development", root / "final")


if __name__ == "__main__":
    unittest.main()
