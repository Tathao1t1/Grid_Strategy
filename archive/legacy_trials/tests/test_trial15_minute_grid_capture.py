from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path

import study_trial5_rotation_grid as trial5
from study_trial15_minute_grid_capture import (
    minute_space,
    one_cost_scenario,
    run_final_oos,
    settlement_at,
    usable_book,
)


def sessions(start: date, count: int) -> list[date]:
    values: list[date] = []
    current = start
    while len(values) < count:
        if current.weekday() < 5:
            values.append(current)
        current += timedelta(days=1)
    return values


def minute(
    day: date,
    clock: time,
    *,
    bid: int = 99_900,
    ask: int = 100_000,
    close: int = 100_000,
    low: int = 99_900,
    high: int = 100_000,
    quantity: int = 10_000,
    book_quantity: int = 1_000,
) -> trial5.MinuteBar:
    return trial5.MinuteBar(
        datetime.combine(day, clock), day, "SSI",
        close, high, low, close, quantity,
        bid, book_quantity, ask, book_quantity,
    )


class MinuteGridCaptureTests(unittest.TestCase):
    def test_frozen_search_has_48_unique_configurations(self) -> None:
        values = minute_space()
        self.assertEqual(len(values), 48)
        self.assertEqual(len({value.key() for value in values}), 48)

    def test_book_gate_enforces_participation(self) -> None:
        day = date(2024, 1, 2)
        self.assertTrue(usable_book(minute(day, time(9, 15)), "buy"))
        self.assertFalse(usable_book(
            minute(day, time(9, 15), quantity=1_000), "buy"
        ))

    def test_legacy_missing_queue_uses_participation_fallback(self) -> None:
        source = minute(date(2022, 8, 1), time(9, 15))
        legacy = trial5.MinuteBar(
            source.event_time, source.trading_date, source.ticker,
            source.open_vnd, source.high_vnd, source.low_vnd,
            source.close_vnd, source.matched_quantity,
            source.best_bid_vnd, None, source.best_ask_vnd, None,
        )
        self.assertTrue(usable_book(legacy, "buy"))
        self.assertTrue(usable_book(legacy, "sell"))

    def test_settlement_is_t_plus_two_at_1300(self) -> None:
        dates = sessions(date(2024, 1, 2), 10)
        self.assertEqual(
            settlement_at(dates, 0),
            datetime.combine(dates[2], time(13, 0)),
        )

    def test_target_before_settlement_cannot_complete_cycle(self) -> None:
        dates = sessions(date(2024, 1, 2), 10)
        minutes = {
            day: [minute(day, time(9, 15))]
            for day in dates
        }
        # A target-looking quote before T+2 must not sell the locked lot.
        minutes[dates[1]] = [minute(
            dates[1], time(14, 0), bid=102_000, ask=102_100,
            close=102_100, low=101_900, high=102_100,
        )]
        # The same executable quote after 13:00 on T+2 may complete it.
        minutes[dates[2]] = [minute(
            dates[2], time(13, 1), bid=102_000, ask=102_100,
            close=102_100, low=101_900, high=102_100,
        )]
        result = one_cost_scenario(
            "SSI", dates[0] - timedelta(days=1), dates, minutes,
            0.015, 1.0,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["target_sales"], 1)

    def test_final_requires_validation_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(PermissionError):
                run_final_oos(root / "development", root / "final")


if __name__ == "__main__":
    unittest.main()
