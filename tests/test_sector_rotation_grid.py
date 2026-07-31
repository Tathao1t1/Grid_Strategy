from __future__ import annotations

import csv
import json
import tempfile
import unittest
from dataclasses import asdict
from datetime import date
from pathlib import Path

import sector_rotation_grid as strategy


class SectorRotationUnitTests(unittest.TestCase):
    def test_efficiency_ratio_distinguishes_trend_from_oscillation(self) -> None:
        trending = strategy.efficiency_ratio([0.0, 0.1, 0.2, 0.3])
        oscillating = strategy.efficiency_ratio([0.0, 0.1, 0.0, 0.1])
        self.assertEqual(trending, 1.0)
        self.assertLess(oscillating, trending)

    def test_account_return_uses_initial_capital_not_first_daily_mark(self) -> None:
        rows = [
            {
                "equity_vnd": 990_000_000,
                "benchmark_equity_vnd": 1_000_000_000,
            },
            {
                "equity_vnd": 1_010_000_000,
                "benchmark_equity_vnd": 1_020_000_000,
            },
        ]
        metrics = strategy.strategy_daily_metrics(rows)
        self.assertAlmostEqual(metrics["net_return"], 0.01)
        self.assertAlmostEqual(metrics["benchmark_return"], 0.02)

    def test_final_test_numeric_poison_is_not_parsed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assignments = root / "assignments.csv"
            with assignments.open(
                "w", newline="", encoding="utf-8"
            ) as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=("trading_date", "research_role"),
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "trading_date": "2022-01-04",
                        "research_role": "selector_development",
                    }
                )
                writer.writerow(
                    {
                        "trading_date": "2025-07-14",
                        "research_role": "locked_final_test",
                    }
                )

            daily = root / "daily.csv"
            fields = (
                "datetime",
                "tickersymbol",
                "open",
                "high",
                "low",
                "close",
                "ceiling",
                "floor",
                "matched_quantity",
            )
            with daily.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                for ticker in strategy.TICKERS:
                    writer.writerow(
                        {
                            "datetime": "2022-01-04",
                            "tickersymbol": ticker,
                            "open": "10",
                            "high": "10.5",
                            "low": "9.5",
                            "close": "10",
                            "ceiling": "10.7",
                            "floor": "9.3",
                            "matched_quantity": "100000",
                        }
                    )
                    writer.writerow(
                        {
                            "datetime": "2025-07-14",
                            "tickersymbol": ticker,
                            "open": "LOCKED",
                            "high": "LOCKED",
                            "low": "LOCKED",
                            "close": "LOCKED",
                            "ceiling": "LOCKED",
                            "floor": "LOCKED",
                            "matched_quantity": "LOCKED",
                        }
                    )

            spreads = root / "spreads.csv"
            with spreads.open(
                "w", newline="", encoding="utf-8"
            ) as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=(
                        "trading_date",
                        "ticker",
                        "median_spread_bps",
                    ),
                )
                writer.writeheader()
                for ticker in strategy.TICKERS:
                    writer.writerow(
                        {
                            "trading_date": "2022-01-04",
                            "ticker": ticker,
                            "median_spread_bps": 10,
                        }
                    )

            data = strategy.DataStore(
                daily,
                assignments,
                spreads,
                root,
            )
            self.assertEqual(data.calendar, (date(2022, 1, 4),))

    def test_failed_development_gate_blocks_oos(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = {
                "grid_config": asdict(strategy.GridConfig()),
                "selector_horizon": 20,
                "development_gate": {
                    "passed": False,
                    "oos_authorized": False,
                },
            }
            digest = strategy.canonical_hash(payload)
            (root / "frozen_config.json").write_text(
                json.dumps(
                    {**payload, "frozen_config_sha256": digest}
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                RuntimeError, "OOS remains reserved"
            ):
                strategy.oos_run(None, root, digest)  # type: ignore[arg-type]
            self.assertFalse((root / "out_of_sample").exists())

    def test_diagnostic_grouping_attributes_exit_pnl(self) -> None:
        rows = [
            {
                "side": "SELL",
                "purpose": "grid_target",
                "realized_pnl_vnd": 30_000,
            },
            {
                "side": "SELL",
                "purpose": "risk_exit",
                "realized_pnl_vnd": -270_000,
            },
            {
                "side": "BUY",
                "purpose": "grid_buy",
                "realized_pnl_vnd": 0,
            },
        ]
        grouped = strategy.diagnostic_group_rows(rows, "purpose")
        observed = {
            row["purpose"]: row["net_pnl_vnd"] for row in grouped
        }
        self.assertEqual(observed["grid_target"], 30_000)
        self.assertEqual(observed["risk_exit"], -270_000)
        self.assertNotIn("grid_buy", observed)


if __name__ == "__main__":
    unittest.main()
