from __future__ import annotations

import unittest
from datetime import date, timedelta

import study_trial6_mean_reversion as trial6
from study_trial7_episodic_grid import Config, select_episodes, simulate_episode


def sessions(start: date, count: int) -> list[date]:
    values: list[date] = []
    current = start
    while len(values) < count:
        if current.weekday() < 5:
            values.append(current)
        current += timedelta(days=1)
    return values


def bar(
    day: date,
    *,
    open_: int = 100_000,
    high: int = 100_500,
    low: int = 99_500,
    close: int = 100_000,
    reset: bool = False,
) -> trial6.DailyBar:
    return trial6.DailyBar(
        day, "VCB", open_, high, low, close, close + 7_000, close - 7_000,
        1_000_000, True, reset,
    )


class EpisodeTests(unittest.TestCase):
    def test_target_before_settlement_does_not_sell(self) -> None:
        dates = sessions(date(2024, 1, 2), 16)
        bars = [bar(day) for day in dates]
        bars[0] = bar(dates[0], high=103_000)
        bars[1] = bar(dates[1], high=103_000)
        bars[2] = bar(dates[2], high=103_000)
        result, resets = simulate_episode(bars, 0, 0.02, Config())
        self.assertFalse(resets)
        self.assertEqual(result["target_sale_count"], 1)
        self.assertEqual(result["exit_date"], dates[2].isoformat())

    def test_lower_level_requires_next_session_reclaim_entry(self) -> None:
        dates = sessions(date(2024, 1, 2), 16)
        bars = [bar(day) for day in dates]
        bars[1] = bar(
            dates[1], open_=97_500, high=99_500, low=97_000, close=99_000
        )
        bars[2] = bar(
            dates[2], open_=99_500, high=100_500, low=99_000, close=100_000
        )
        bars[4] = bar(
            dates[4], open_=100_000, high=103_000, low=99_500, close=102_000
        )
        result, _ = simulate_episode(bars, 0, 0.02, Config())
        self.assertTrue(result["lower_level_filled"])
        self.assertEqual(result["buy_count"], 2)
        self.assertEqual(result["target_sale_count"], 2)

    def test_gap_risk_waits_for_locked_inventory(self) -> None:
        dates = sessions(date(2024, 1, 2), 16)
        bars = [bar(day) for day in dates]
        bars[1] = bar(
            dates[1], open_=90_000, high=91_000, low=89_000, close=90_000
        )
        bars[2] = bar(
            dates[2], open_=88_000, high=89_000, low=87_000, close=88_000
        )
        result, _ = simulate_episode(bars, 0, 0.02, Config())
        self.assertTrue(result["risk_exit"])
        self.assertTrue(result["gap_risk_exit"])
        self.assertEqual(result["exit_date"], dates[2].isoformat())
        self.assertLess(result["net_pnl_vnd"], 0)

    def test_reference_reset_quarantines_path(self) -> None:
        dates = sessions(date(2024, 1, 2), 16)
        bars = [bar(day) for day in dates]
        bars[7] = bar(dates[7], reset=True)
        result, resets = simulate_episode(bars, 0, 0.02, Config())
        self.assertIsNone(result)
        self.assertEqual(resets, (dates[7],))


class SelectionTests(unittest.TestCase):
    def row(
        self, ticker: str, sector: str, entry: str, exit_: str,
        residual_z: float, rebound: float,
    ) -> dict[str, object]:
        return {
            "ticker": ticker,
            "sector": sector,
            "entry_date": entry,
            "exit_date": exit_,
            "residual_z5": residual_z,
            "residual_1": rebound,
            "selected": False,
            "selection_rank": "",
        }

    def test_ranking_and_sector_cap(self) -> None:
        calendar = sessions(date(2024, 1, 2), 20)
        entry, exit_ = calendar[0].isoformat(), calendar[3].isoformat()
        rows = [
            self.row("VCB", "banks", entry, exit_, -2.0, 0.01),
            self.row("MBB", "banks", entry, exit_, -1.5, 0.02),
            self.row("FPT", "technology", entry, exit_, -1.0, 0.01),
        ]
        chosen = select_episodes(rows, calendar, Config())
        self.assertEqual({row["ticker"] for row in chosen}, {"VCB", "FPT"})
        self.assertFalse(rows[1]["selected"])


if __name__ == "__main__":
    unittest.main()
