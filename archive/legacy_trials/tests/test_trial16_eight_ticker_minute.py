from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

import study_trial11_trend_grid as trial11
from study_trial16_eight_ticker_minute import (
    EXCLUDED,
    UNIVERSE,
    run_final_oos,
)


class EightTickerMinuteTests(unittest.TestCase):
    def test_only_fpt_and_pnj_are_excluded(self) -> None:
        self.assertEqual(EXCLUDED, ("FPT", "PNJ"))
        self.assertEqual(len(UNIVERSE), 8)
        self.assertEqual(
            set(UNIVERSE),
            set(trial11.TICKERS).difference(EXCLUDED),
        )

    def test_requested_tickers_cannot_enter_execution_universe(self) -> None:
        self.assertNotIn("FPT", UNIVERSE)
        self.assertNotIn("PNJ", UNIVERSE)

    def test_declared_timeline_is_chronological(self) -> None:
        self.assertLess(date(2022, 1, 4), date(2023, 1, 3))
        self.assertLess(date(2024, 6, 28), date(2024, 7, 1))
        self.assertLess(date(2025, 7, 11), date(2025, 7, 14))

    def test_final_requires_validation_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(PermissionError):
                run_final_oos(root / "development", root / "final")


if __name__ == "__main__":
    unittest.main()
