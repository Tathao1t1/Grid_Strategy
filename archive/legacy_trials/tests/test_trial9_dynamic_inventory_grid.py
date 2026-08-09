from __future__ import annotations

import unittest
from datetime import date, timedelta

import study_trial6_mean_reversion as trial6
from study_trial9_dynamic_inventory_grid import (
    Config,
    build_grid,
    inventory_adjusted_quantity,
)


def sessions(start: date, count: int) -> list[date]:
    result: list[date] = []
    current = start
    while len(result) < count:
        if current.weekday() < 5:
            result.append(current)
        current += timedelta(days=1)
    return result


def bars(count: int = 30) -> list[trial6.DailyBar]:
    dates = sessions(date(2024, 1, 2), count)
    return [
        trial6.DailyBar(
            day, "SSI", 100_000, 101_000, 99_000, 100_000,
            107_000, 93_000, 1_000_000, True, False,
        )
        for day in dates
    ]


class GridConstructionTests(unittest.TestCase):
    def test_dynamic_bounds_buffer_and_increasing_base_size(self) -> None:
        config = Config()
        center, lower, upper, hard_lower, ratio, levels = build_grid(
            bars(), 25, config
        )
        self.assertLess(hard_lower, lower)
        self.assertLess(lower, center)
        self.assertLess(center, upper)
        self.assertGreater(ratio, 0)
        self.assertEqual(
            [level.base_quantity for level in levels],
            [100, 200, 300],
        )
        self.assertEqual(
            [level.distance for level in levels],
            [0, 1, 2],
        )
        self.assertGreater(levels[0].buy_vnd, levels[2].buy_vnd)


class QuantityTests(unittest.TestCase):
    def test_inventory_skew_reduces_farther_order(self) -> None:
        config = Config(stress_budget_fraction=0.10)
        quantity, reduced, cancelled = inventory_adjusted_quantity(
            300, 300, [], 100_000, 99_000, config
        )
        self.assertEqual(quantity, 200)
        self.assertTrue(reduced)
        self.assertFalse(cancelled)

    def test_stress_budget_can_cancel_buy(self) -> None:
        quantity, reduced, cancelled = inventory_adjusted_quantity(
            100, 0, [], 100_000, 50_000, Config()
        )
        self.assertEqual(quantity, 0)
        self.assertTrue(reduced)
        self.assertTrue(cancelled)


if __name__ == "__main__":
    unittest.main()
