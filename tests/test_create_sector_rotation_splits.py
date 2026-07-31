from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import date
from pathlib import Path

import create_sector_rotation_splits as splits


class SectorRotationSplitTests(unittest.TestCase):
    def write_fixture(self, path: Path) -> None:
        dates = (
            ("2022-12-30", "development"),
            ("2023-01-03", "development"),
            ("2023-12-29", "development"),
            ("2024-01-02", "development"),
            ("2024-12-31", "development"),
            ("2025-01-02", "development"),
            ("2025-06-30", "development"),
            ("2025-07-01", "development"),
            ("2025-07-14", "final_test"),
        )
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=("datetime", "tickersymbol", "primary_split"),
            )
            writer.writeheader()
            for trading_date, primary_split in dates:
                for ticker in ("SSI", "VCB"):
                    writer.writerow(
                        {
                            "datetime": trading_date,
                            "tickersymbol": ticker,
                            "primary_split": primary_split,
                        }
                    )

    def test_roles_are_disjoint_and_locked_period_stays_locked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "daily.csv"
            self.write_fixture(path)
            tickers = ("SSI", "VCB")
            boundaries = splits.Boundaries()
            roles = splits.read_roles(path, tickers, boundaries)
            audit = splits.audit_roles(roles, tickers, path, boundaries)
            self.assertEqual(
                roles[date(2022, 12, 30)], "selector_development"
            )
            self.assertEqual(roles[date(2023, 1, 3)], "in_sample")
            self.assertEqual(roles[date(2024, 1, 2)], "optimization")
            self.assertEqual(roles[date(2025, 1, 2)], "out_of_sample")
            self.assertEqual(roles[date(2025, 7, 1)], "unused_buffer")
            self.assertEqual(
                roles[date(2025, 7, 14)],
                "locked_final_test",
            )
            self.assertTrue(
                audit["selector_is_disjoint_from_all_trading_evaluation"]
            )
            self.assertEqual(audit["selector_trading_overlap_sessions"], 0)
            self.assertFalse(audit["locked_period_opened_by_this_script"])

    def test_incomplete_universe_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "daily.csv"
            self.write_fixture(path)
            with path.open(encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(
                    row
                    for row in rows
                    if not (
                        row["datetime"] == "2024-01-02"
                        and row["tickersymbol"] == "VCB"
                    )
                )
            with self.assertRaisesRegex(ValueError, "Incomplete universe"):
                splits.read_roles(
                    path, ("SSI", "VCB"), splits.Boundaries()
                )


if __name__ == "__main__":
    unittest.main()
