from __future__ import annotations

import csv
import json
import tempfile
import unittest
from dataclasses import asdict
from datetime import date, timedelta
from decimal import Decimal
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

    def test_grid_levels_use_geometric_atr_spacing(self) -> None:
        cutoff = date(2024, 1, 31)

        class StubData:
            bars_by_date = {
                cutoff: {
                    "MBB": strategy.DailyBar(
                        trading_date=cutoff,
                        ticker="MBB",
                        open_vnd=100_000,
                        high_vnd=102_000,
                        low_vnd=98_000,
                        close_vnd=100_000,
                        ceiling_vnd=107_000,
                        floor_vnd=93_000,
                        previous_close_vnd=100_000,
                        matched_quantity=1_000_000,
                        role="optimization",
                    )
                }
            }

            @staticmethod
            def atr_pct(ticker: str, value: date) -> float:
                if ticker != "MBB" or value != cutoff:
                    raise AssertionError("Unexpected ATR request")
                return 0.02

        selection = strategy.Selection(
            cutoff=cutoff,
            deployment_start=date(2024, 2, 1),
            deployment_end=date(2024, 2, 29),
            horizon=20,
            selected_sector="banks",
            selected_tickers=("MBB",),
            market_gate=False,
            market_gate_reasons=(),
            features=(),
        )
        config = strategy.GridConfig(
            levels=4,
            spacing_atr_multiplier=0.75,
            maximum_cells_per_level=3,
        )
        levels = strategy.make_levels(
            StubData(), selection, config, 1_000_000_000  # type: ignore[arg-type]
        )
        spacing = Decimal("0.015")
        expected_buys = {
            strategy.round_to_hsx_tick(
                Decimal("100000") / (Decimal("1") + spacing) ** index,
                strategy.Side.BUY,
            )
            for index in range(1, 5)
        }
        expected_targets = {
            strategy.round_to_hsx_tick(
                Decimal("100000") / (Decimal("1") + spacing) ** index,
                strategy.Side.SELL,
            )
            for index in range(0, 4)
        }
        self.assertEqual(len(levels), 12)
        self.assertEqual({level.buy_limit_vnd for level in levels}, expected_buys)
        self.assertEqual(
            {level.sell_target_vnd for level in levels}, expected_targets
        )

    def test_final_oos_authorization_is_hash_checked_and_one_time(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = {
                "grid_config": asdict(strategy.GridConfig()),
                "selector_horizon": 20,
                "development_gate": {
                    "passed": True,
                    "oos_authorized": True,
                },
            }
            digest = strategy.canonical_hash(payload)
            (root / "frozen_config.json").write_text(
                json.dumps({**payload, "frozen_config_sha256": digest}),
                encoding="utf-8",
            )
            daily = root / "daily.csv"
            daily.write_text("header\n", encoding="utf-8")
            assignments = root / "assignments.csv"
            start = date(2025, 7, 14)
            end = date(2026, 7, 16)
            middle = [start + timedelta(days=index) for index in range(1, 251)]
            final_dates = [start, *middle[:250], end]
            with assignments.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=("trading_date", "research_role"),
                )
                writer.writeheader()
                for value in final_dates:
                    writer.writerow(
                        {
                            "trading_date": value.isoformat(),
                            "research_role": "locked_final_test",
                        }
                    )
            manifest = strategy.authorize_final_oos_opening(
                root,
                digest,
                daily,
                assignments,
                allow_failed_gate=False,
            )
            self.assertTrue(manifest["hash_verified_before_final_numeric_load"])
            with self.assertRaisesRegex(RuntimeError, "already been opened"):
                strategy.authorize_final_oos_opening(
                    root,
                    digest,
                    daily,
                    assignments,
                    allow_failed_gate=False,
                )

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
