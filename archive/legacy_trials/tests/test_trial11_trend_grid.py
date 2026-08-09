from __future__ import annotations

import unittest
import tempfile
from datetime import date, timedelta
from pathlib import Path

import study_trial6_mean_reversion as trial6
from study_trial11_trend_grid import (
    BaseConfig,
    Feature,
    Parameters,
    parameter_space,
    signal_passes,
    simulate_campaign,
    summarize_search,
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


def bar(
    day: date,
    ticker: str = "SSI",
    *,
    open_: int = 100_000,
    high: int = 101_000,
    low: int = 99_000,
    close: int = 100_000,
) -> trial6.DailyBar:
    return trial6.DailyBar(
        day, ticker, open_, high, low, close,
        close + 7_000, close - 7_000, 1_000_000, True, False,
    )


def feature(index: int, day: date, **changes: object) -> Feature:
    values = {
        "index": index,
        "trading_date": day,
        "ticker": "SSI",
        "residual_z5": -1.0,
        "residual_1": 0.01,
        "market_return20": 0.03,
        "atr_fraction": 0.02,
        "close_up": True,
        "close_above_sma50": True,
        "sma20_above_sma50": True,
        "valid": True,
    }
    values.update(changes)
    return Feature(**values)


class SearchTests(unittest.TestCase):
    def test_frozen_search_contains_216_configs(self) -> None:
        values = parameter_space()
        self.assertEqual(len(values), 216)
        self.assertEqual(len({item.key() for item in values}), 216)

    def test_signal_requires_trend_pullback_and_confirmation(self) -> None:
        params = Parameters(0.0, -0.75, 1.0, True, 3, 15)
        item = feature(60, date(2024, 1, 2))
        self.assertTrue(signal_passes(item, params))
        self.assertFalse(signal_passes(
            feature(60, date(2024, 1, 2), close_above_sma50=False),
            params,
        ))
        self.assertFalse(signal_passes(
            feature(60, date(2024, 1, 2), residual_1=-0.01),
            params,
        ))

    def test_optimizer_rejects_small_profitable_sample(self) -> None:
        params = Parameters(0.0, -0.75, 1.0, False, 3, 15)
        rows = [
            {
                "net_pnl_vnd": 100,
                "double_cost_pnl_vnd": 50,
                "campaign_return": 0.01,
                "entry_date": f"2023-01-{index + 2:02d}",
            }
            for index in range(5)
        ]
        self.assertFalse(summarize_search(rows, params)["eligible"])


class CampaignTests(unittest.TestCase):
    def test_initial_target_waits_for_t_plus_two(self) -> None:
        dates = sessions(date(2024, 1, 2), 90)
        bars = [bar(day) for day in dates]
        signal_index = 60
        entry = signal_index + 1
        for offset in range(16):
            bars[entry + offset] = bar(
                dates[entry + offset],
                high=103_000,
                low=99_000,
                close=101_000,
            )
        daily = {"SSI": bars}
        features = {
            ("SSI", index): feature(index, dates[index])
            for index in range(60, 90)
        }
        params = Parameters(0.0, -0.75, 1.0, False, 3, 15)
        result = simulate_campaign(
            "SSI", signal_index, 89, daily, features,
            params, BaseConfig(), "test",
        )
        self.assertEqual(result["target_sales"], 1)
        self.assertEqual(result["exit_date"], dates[entry + 2].isoformat())
        self.assertGreater(result["net_pnl_vnd"], 0)


class GovernanceTests(unittest.TestCase):
    def test_final_oos_requires_validation_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(PermissionError):
                run_final_oos(root / "development", root / "final")


if __name__ == "__main__":
    unittest.main()
