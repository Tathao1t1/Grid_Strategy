from __future__ import annotations

import math
import tempfile
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path

import study_trial5_rotation_grid as trial5
import study_trial6_mean_reversion as trial6
import study_trial11_trend_grid as trial11
from study_trial18_market_equilibrium_grid import (
    TARGET_SPACE,
    config_by_name,
    market_adjusted_equilibrium,
    minimum_economic_target,
    one_cost_scenario,
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


def daily_fixture() -> tuple[
    dict[str, list[trial6.DailyBar]], list[date]
]:
    dates = sessions(date(2023, 1, 2), 70)
    result: dict[str, list[trial6.DailyBar]] = {}
    for ticker in trial11.TICKERS:
        bars: list[trial6.DailyBar] = []
        for index, day in enumerate(dates):
            market_price = 100_000 * (1.001 ** index)
            if ticker == "SSI" and index >= 65:
                market_price *= 0.99 ** (index - 64)
            price = int(round(market_price / 100)) * 100
            bars.append(trial6.DailyBar(
                day, ticker, price, price, price, price,
                None, None, 1_000_000, True, False,
            ))
        result[ticker] = bars
    return result, dates


def minute(
    day: date,
    clock: time,
    *,
    bid: int,
    ask: int,
    close: int,
    low: int,
    high: int,
) -> trial5.MinuteBar:
    return trial5.MinuteBar(
        datetime.combine(day, clock), day, "SSI",
        close, high, low, close, 10_000,
        bid, 1_000, ask, 1_000,
    )


class MarketEquilibriumGridTests(unittest.TestCase):
    def test_target_space_has_control_and_three_positive_floors(self) -> None:
        self.assertEqual(len(TARGET_SPACE), 4)
        self.assertFalse(TARGET_SPACE[0].eligible_to_advance)
        self.assertEqual(
            [value.minimum_net_profit_fraction for value in TARGET_SPACE[1:]],
            [0.005, 0.0075, 0.01],
        )

    def test_market_adjusted_equilibrium_detects_idiosyncratic_drop(self) -> None:
        daily, _ = daily_fixture()
        estimate = market_adjusted_equilibrium(
            "SSI", 69, daily, 0.02
        )
        current = daily["SSI"][69].close_vnd
        self.assertGreater(estimate.centre_vnd, current)
        self.assertGreater(estimate.beta, 0)
        self.assertTrue(estimate.capped)
        self.assertLessEqual(
            estimate.centre_vnd,
            math.ceil(current * 1.04 / 100) * 100,
        )

    def test_economic_target_meets_net_profit_after_normal_costs(self) -> None:
        fill = 100_000
        margin = 0.005
        target = minimum_economic_target(fill, margin)
        acquisition, _ = trial5.acquisition_cash(
            fill, 100, trial5.Config(), 1.0
        )
        proceeds, _, _ = trial5.net_sale_cash(
            target, 100, trial5.Config(), 1.0
        )
        self.assertGreaterEqual(
            proceeds - acquisition, math.ceil(acquisition * margin)
        )
        prior = target - trial5.hsx_tick_vnd(target)
        prior_proceeds, _, _ = trial5.net_sale_cash(
            prior, 100, trial5.Config(), 1.0
        )
        self.assertLess(
            prior_proceeds - acquisition, math.ceil(acquisition * margin)
        )

    def test_one_percent_floor_raises_target_and_waits_for_t_plus_two(
        self,
    ) -> None:
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
        fill = 98_800
        target = minimum_economic_target(fill, 0.01)
        minutes[dates[1]] = [minute(
            dates[1], time(14, 0), bid=target, ask=target + 100,
            close=target + 100, low=target - 100, high=target + 100,
        )]
        minutes[dates[2]] = [minute(
            dates[2], time(13, 1), bid=target, ask=target + 100,
            close=target + 100, low=target - 100, high=target + 100,
        )]
        result = one_cost_scenario(
            "SSI", dates[0] - timedelta(days=1), dates, minutes,
            100_000, 0.015, config_by_name("equilibrium_net_100"),
            {day: False for day in dates}, 1.0,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["target_sales"], 1)
        self.assertEqual(result["exit_date"], dates[2].isoformat())
        self.assertEqual(result["economic_target_adjustments"], 1)

    def test_preserved_veto_blocks_entry(self) -> None:
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
        result = one_cost_scenario(
            "SSI", dates[0] - timedelta(days=1), dates, minutes,
            100_000, 0.015, config_by_name("equilibrium_net_50"),
            {day: day == dates[0] for day in dates}, 1.0,
        )
        self.assertIsNone(result)

    def test_final_requires_validation_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(PermissionError):
                run_final_oos(root / "development", root / "final")


if __name__ == "__main__":
    unittest.main()
