from __future__ import annotations

import unittest
from datetime import date, timedelta
from unittest.mock import patch

import study_trial6_mean_reversion as trial6
from study_trial10_single_reanchor import (
    Config,
    Level,
    initial_levels,
    recovery_stress_ok,
    simulate,
)


def sessions(start: date, count: int) -> list[date]:
    result: list[date] = []
    current = start
    while len(result) < count:
        if current.weekday() < 5:
            result.append(current)
        current += timedelta(days=1)
    return result


def make_bar(
    day: date,
    *,
    open_: int = 100_000,
    high: int = 101_000,
    low: int = 99_000,
    close: int = 100_000,
) -> trial6.DailyBar:
    return trial6.DailyBar(
        day, "SSI", open_, high, low, close,
        close + 7_000, close - 7_000, 1_000_000, True, False,
    )


class GridTests(unittest.TestCase):
    def test_initial_grid_has_two_equal_lots(self) -> None:
        dates = sessions(date(2024, 1, 2), 70)
        bars = [make_bar(day) for day in dates]
        center, lower, hard_lower, levels = initial_levels(
            bars, 60, Config()
        )
        self.assertLess(hard_lower, lower)
        self.assertLess(lower, center)
        self.assertEqual(len(levels), 2)
        self.assertEqual([level.quantity for level in levels], [100, 100])

    def test_recovery_stress_can_reject_additional_lot(self) -> None:
        self.assertFalse(recovery_stress_ok(
            [], 100_000, 50_000, Config()
        ))


class ReanchorStateTests(unittest.TestCase):
    def test_one_reanchor_preserves_campaign_accounting(self) -> None:
        dates = sessions(date(2024, 1, 2), 90)
        bars = [make_bar(day) for day in dates]
        signal_index = 60
        entry = signal_index + 1
        bars[entry] = make_bar(
            dates[entry], open_=98_500, high=100_000,
            low=98_000, close=99_500,
        )
        bars[entry + 1] = make_bar(
            dates[entry + 1], open_=99_000, high=100_000,
            low=98_500, close=99_500,
        )
        bars[entry + 2] = make_bar(
            dates[entry + 2], open_=95_000, high=96_000,
            low=93_000, close=94_000,
        )
        bars[entry + 3] = make_bar(
            dates[entry + 3], open_=91_500, high=95_000,
            low=91_000, close=93_000,
        )
        bars[entry + 4] = make_bar(
            dates[entry + 4], open_=93_000, high=95_000,
            low=92_500, close=94_000,
        )
        for offset in range(5, 21):
            bars[entry + offset] = make_bar(
                dates[entry + offset], open_=94_000,
                high=96_000, low=93_500, close=95_000,
            )
        daily = {"SSI": bars}
        initial = (
            100_000.0,
            95_000,
            85_000,
            [Level("initial_0", 99_000, 102_000, 100)],
        )
        recovery = (
            94_000.0,
            84_000,
            97_000,
            Level("recovery", 92_000, 94_000, 100),
        )
        with (
            patch(
                "study_trial10_single_reanchor.initial_levels",
                return_value=initial,
            ),
            patch(
                "study_trial10_single_reanchor.stabilized",
                return_value=True,
            ),
            patch(
                "study_trial10_single_reanchor.recovery_parameters",
                return_value=recovery,
            ),
            patch(
                "study_trial10_single_reanchor.recovery_stress_ok",
                return_value=True,
            ),
        ):
            result = simulate(
                "SSI", signal_index, daily, Config(), enable_reanchor=True
            )
        self.assertTrue(result["lower_bound_breached"])
        self.assertTrue(result["reanchored"])
        self.assertTrue(result["recovery_lot_filled"])
        self.assertEqual(result["profit_target_sales"], 2)
        self.assertIsInstance(result["net_pnl_vnd"], int)


if __name__ == "__main__":
    unittest.main()
