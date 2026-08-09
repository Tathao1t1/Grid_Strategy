from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path

import study_trial5_rotation_grid as trial5
import study_trial6_mean_reversion as trial6
from study_trial17_fair_value_reversal_grid import (
    MECHANIC_SPACE,
    UNIVERSE,
    config_by_name,
    fair_value_centre,
    make_levels,
    normal_floor_stress_loss,
    one_cost_scenario,
    run_final_oos,
    severe_downtrend,
)


def sessions(start: date, count: int) -> list[date]:
    result: list[date] = []
    current = start
    while len(result) < count:
        if current.weekday() < 5:
            result.append(current)
        current += timedelta(days=1)
    return result


def minute(
    day: date,
    clock: time,
    *,
    bid: int,
    ask: int,
    close: int,
    low: int,
    high: int,
    quantity: int = 10_000,
) -> trial5.MinuteBar:
    return trial5.MinuteBar(
        datetime.combine(day, clock), day, "SSI",
        close, high, low, close, quantity,
        bid, 1_000, ask, 1_000,
    )


def feature(**overrides: float) -> dict[str, float]:
    result = {
        "market_return20": 0.01,
        "close_minus_sma50_fraction": 0.01,
        "atr20_fraction": 0.02,
        "residual_slope20": 0.001,
        "residual_1": 0.001,
    }
    result.update(overrides)
    return result


class FairValueReversalGridTests(unittest.TestCase):
    def test_frozen_ablation_has_four_cumulative_variants(self) -> None:
        self.assertEqual(len(MECHANIC_SPACE), 4)
        self.assertEqual(len({value.name for value in MECHANIC_SPACE}), 4)
        self.assertEqual(
            MECHANIC_SPACE[-1].name, "anchor_reclaim_veto_2"
        )
        self.assertEqual(MECHANIC_SPACE[-1].maximum_levels, 2)
        self.assertEqual(len(UNIVERSE), 8)

    def test_fair_value_is_prior_twenty_session_median(self) -> None:
        start = date(2024, 1, 2)
        dates = sessions(start, 20)
        bars = [
            trial6.DailyBar(
                day, "SSI", price, price, price, price,
                None, None, 1_000_000, True, False,
            )
            for day, price in zip(
                dates, range(90_000, 110_000, 1_000)
            )
        ]
        self.assertEqual(fair_value_centre(bars, 19), 99_500)

    def test_severe_veto_requires_two_of_three_conditions(self) -> None:
        self.assertFalse(severe_downtrend(feature(
            market_return20=-0.04,
        )))
        self.assertTrue(severe_downtrend(feature(
            market_return20=-0.04,
            close_minus_sma50_fraction=-0.03,
        )))
        self.assertTrue(severe_downtrend(feature(
            market_return20=-0.04,
            residual_slope20=-0.001,
            residual_1=-0.001,
        )))

    def test_geometric_levels_target_the_next_higher_cell(self) -> None:
        levels = make_levels(100_000, 0.02, 2)
        self.assertEqual(len(levels), 2)
        self.assertLess(levels[1].buy_limit_vnd, levels[0].buy_limit_vnd)
        self.assertEqual(
            levels[1].sell_target_vnd, levels[0].buy_limit_vnd + 100
        )
        self.assertEqual(levels[0].sell_target_vnd, 100_000)

    def test_reclaim_requires_a_later_minute_and_respects_t_plus_two(self) -> None:
        dates = sessions(date(2024, 1, 2), 7)
        minutes = {day: [] for day in dates}
        minutes[dates[0]] = [
            minute(
                dates[0], time(9, 15), bid=98_400, ask=98_500,
                close=98_400, low=98_400, high=98_500,
            ),
            minute(
                dates[0], time(9, 16), bid=98_600, ask=98_700,
                close=98_600, low=98_500, high=98_700,
            ),
        ]
        # A target quote before settlement cannot sell.
        minutes[dates[1]] = [minute(
            dates[1], time(14, 0), bid=100_000, ask=100_100,
            close=100_100, low=99_900, high=100_100,
        )]
        # The same quote after 13:00 on T+2 completes the cycle.
        minutes[dates[2]] = [minute(
            dates[2], time(13, 1), bid=100_000, ask=100_100,
            close=100_100, low=99_900, high=100_100,
        )]
        result = one_cost_scenario(
            "SSI", dates[0] - timedelta(days=1), dates, minutes,
            100_000, 0.015, config_by_name("anchor_reclaim_1"),
            {day: False for day in dates}, 1.0,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["entry_date"], dates[0].isoformat())
        self.assertEqual(result["exit_date"], dates[2].isoformat())
        self.assertEqual(result["target_sales"], 1)

    def test_hard_lower_shuts_down_before_entry(self) -> None:
        dates = sessions(date(2024, 1, 2), 7)
        minutes = {day: [] for day in dates}
        minutes[dates[0]] = [minute(
            dates[0], time(9, 15), bid=95_000, ask=95_100,
            close=95_000, low=95_000, high=95_100,
        )]
        result = one_cost_scenario(
            "SSI", dates[0] - timedelta(days=1), dates, minutes,
            100_000, 0.015, config_by_name("anchor_touch_1"),
            {day: False for day in dates}, 1.0,
        )
        self.assertIsNone(result)

    def test_floor_stress_budget_increases_with_price(self) -> None:
        self.assertGreater(
            normal_floor_stress_loss(120_000),
            normal_floor_stress_loss(60_000),
        )

    def test_final_requires_validation_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(PermissionError):
                run_final_oos(root / "development", root / "final")


if __name__ == "__main__":
    unittest.main()
