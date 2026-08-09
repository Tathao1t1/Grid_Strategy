from __future__ import annotations

import csv
import gzip
import tempfile
import unittest
import json
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path

import study_trial5_rotation_grid as trial5


def daily_bar(
    trading_date: date,
    ticker: str = "FPT",
    close_vnd: int = 100_000,
    *,
    high_vnd: int | None = None,
    low_vnd: int | None = None,
) -> trial5.DailyBar:
    return trial5.DailyBar(
        trading_date=trading_date,
        ticker=ticker,
        open_vnd=close_vnd,
        high_vnd=high_vnd or close_vnd + 1_000,
        low_vnd=low_vnd or close_vnd - 1_000,
        close_vnd=close_vnd,
        ceiling_vnd=int(close_vnd * 1.07),
        floor_vnd=int(close_vnd * 0.93),
        matched_quantity=1_000_000,
        reset_verifiable=True,
        reference_reset=False,
    )


def minute_bar(
    event_time: datetime,
    *,
    ticker: str = "FPT",
    matched_open: int = 100_000,
    matched_high: int = 100_000,
    matched_low: int = 100_000,
    matched_close: int = 100_000,
    best_bid: int = 99_900,
    best_ask: int = 100_000,
    quantity: int = 10_000,
) -> trial5.MinuteBar:
    return trial5.MinuteBar(
        event_time=event_time,
        trading_date=event_time.date(),
        ticker=ticker,
        open_vnd=matched_open,
        high_vnd=matched_high,
        low_vnd=matched_low,
        close_vnd=matched_close,
        matched_quantity=quantity,
        best_bid_vnd=best_bid,
        best_bid_quantity=10_000,
        best_ask_vnd=best_ask,
        best_ask_quantity=10_000,
    )


class PriceCostAndGridTests(unittest.TestCase):
    def test_quote_units_and_hsx_ticks(self) -> None:
        self.assertEqual(trial5.quote_to_vnd("70.35"), 70_350)
        self.assertEqual(trial5.hsx_tick_vnd(9_990), 10)
        self.assertEqual(trial5.hsx_tick_vnd(20_000), 50)
        self.assertEqual(trial5.hsx_tick_vnd(70_000), 100)
        self.assertEqual(trial5.round_to_hsx_tick(70_355, "buy"), 70_300)
        self.assertEqual(trial5.round_to_hsx_tick(70_355, "sell"), 70_400)

    def test_exact_vnd_cashflows(self) -> None:
        config = trial5.Config()
        acquisition, buy_commission = trial5.acquisition_cash(
            70_000, 100, config
        )
        sale, sell_commission, sell_tax = trial5.net_sale_cash(
            71_000, 100, config
        )
        self.assertEqual(buy_commission, 10_500)
        self.assertEqual(acquisition, 7_010_500)
        self.assertEqual(sell_commission, 10_650)
        self.assertEqual(sell_tax, 7_100)
        self.assertEqual(sale, 7_082_250)

    def test_three_floor_stress_rounds_each_session(self) -> None:
        self.assertEqual(
            trial5.consecutive_floor_price(70_000, 3, 0.07),
            56_200,
        )
        # Rounding only once after compounding would produce 56,300 and
        # therefore understate the modeled loss by one HSX tick.
        self.assertEqual(
            trial5.round_to_hsx_tick(70_000 * (0.93 ** 3), "buy"),
            56_300,
        )

    def test_grid_is_one_cell_and_respects_risk_caps(self) -> None:
        config = trial5.Config()
        train_dates = tuple(
            date(2024, 1, 1) + timedelta(days=index) for index in range(50)
        )
        oos_dates = tuple(
            date(2024, 3, 1) + timedelta(days=index) for index in range(10)
        )
        fold = trial5.Fold("wf_01", train_dates, oos_dates)
        levels, rows = trial5.create_grid(
            fold,
            "FPT",
            {"atr20_pct": 0.02},
            100_000,
            50_000_000,
            config,
        )
        self.assertEqual(len(levels), 1)
        self.assertLess(levels[0].buy_limit_vnd, 100_000)
        self.assertEqual(levels[0].sell_target_vnd, 100_000)
        acquisition, _ = trial5.acquisition_cash(
            levels[0].buy_limit_vnd, levels[0].quantity, config
        )
        self.assertLessEqual(acquisition, 15_000_000)
        self.assertLess(int(rows[0]["lower_bound_vnd"]), levels[0].buy_limit_vnd)


class SelectionAndCausalityTests(unittest.TestCase):
    def test_deep_downtrend_takes_priority_over_low_er(self) -> None:
        config = trial5.Config()
        start = date(2024, 1, 1)
        closes = [100_000, 99_000, 98_000, 97_000, 96_000,
                  95_000, 94_000, 93_000, 92_000, 91_000, 90_000]
        rows = [
            daily_bar(start + timedelta(days=index), close_vnd=value)
            for index, value in enumerate(closes)
        ]
        regime, _, period_return, _ = trial5.classify_window(rows, config)
        self.assertLessEqual(period_return, -0.08)
        self.assertEqual(regime, "deep_downtrend")

    def test_entry_gate_uses_only_rows_ending_t_minus_one(self) -> None:
        config = trial5.Config()
        start = date(2024, 1, 1)
        history = [
            daily_bar(
                start + timedelta(days=index),
                close_vnd=90_000 + index * 200,
            )
            for index in range(60)
        ]
        self.assertTrue(trial5.entry_gate(history, 98_000, config))
        future_crash = daily_bar(start + timedelta(days=60), close_vnd=50_000)
        # The T order receives history only through T-1, so a T crash cannot
        # alter the already-created order.
        self.assertTrue(trial5.entry_gate(history, 98_000, config))
        self.assertFalse(
            trial5.entry_gate(history + [future_crash], 98_000, config)
        )

    def test_final_numeric_poison_is_skipped_before_parsing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "daily.csv"
            fields = [
                "datetime",
                "tickersymbol",
                "open",
                "high",
                "low",
                "close",
                "ceiling",
                "floor",
                "matched_quantity",
                "exchangeid",
                "instrumenttype",
                "primary_split",
            ]
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                for ticker in trial5.TICKERS:
                    writer.writerow(
                        {
                            "datetime": "2024-01-02",
                            "tickersymbol": ticker,
                            "open": "10",
                            "high": "11",
                            "low": "9",
                            "close": "10",
                            "ceiling": "10.7",
                            "floor": "9.3",
                            "matched_quantity": "1000",
                            "exchangeid": "HSX",
                            "instrumenttype": "stock",
                            "primary_split": "development",
                        }
                    )
                    writer.writerow(
                        {
                            "datetime": "2025-01-02",
                            "tickersymbol": ticker,
                            "open": "LOCKED",
                            "high": "LOCKED",
                            "low": "LOCKED",
                            "close": "LOCKED",
                            "ceiling": "LOCKED",
                            "floor": "LOCKED",
                            "matched_quantity": "LOCKED",
                            "exchangeid": "LOCKED",
                            "instrumenttype": "LOCKED",
                            "primary_split": "final_test",
                        }
                    )
            daily_one, calendar, final_range = trial5.read_daily_development(
                path, trial5.TICKERS, enforce_frozen_calendar=False
            )
            self.assertEqual(calendar, [date(2024, 1, 2)])
            self.assertEqual(final_range[0], date(2025, 1, 2))
            first_hash = trial5.development_daily_hash(
                daily_one, trial5.TICKERS
            )
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "LOCKED", "DIFFERENT_FINAL_VALUE"
                ),
                encoding="utf-8",
            )
            daily_two, _, _ = trial5.read_daily_development(
                path, trial5.TICKERS, enforce_frozen_calendar=False
            )
            self.assertEqual(
                first_hash,
                trial5.development_daily_hash(daily_two, trial5.TICKERS),
            )


class MinuteAndSettlementTests(unittest.TestCase):
    def test_minute_loader_filters_scope_before_numeric_parsing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            minute_dir = Path(directory)
            path = minute_dir / "minute_bars_2024_01.csv.gz"
            fields = sorted(trial5.MINUTE_REQUIRED)
            good = {
                "minute": "2024-01-02 09:15:00",
                "trading_date": "2024-01-02",
                "tickersymbol": "FPT",
                "market_session": "continuous_morning",
                "matched_open": "10",
                "matched_high": "10.1",
                "matched_low": "9.9",
                "matched_close": "10",
                "matched_quantity": "1000",
                "last_best_bid": "9.95",
                "last_best_bid_quantity": "1000",
                "last_best_ask": "10",
                "last_best_ask_quantity": "1000",
            }
            poison = dict(good)
            poison.update(
                {
                    "tickersymbol": "VCB",
                    "matched_open": "LOCKED",
                    "matched_high": "LOCKED",
                    "matched_low": "LOCKED",
                    "matched_close": "LOCKED",
                }
            )
            with gzip.open(path, "wt", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerow(good)
                writer.writerow(poison)
            fold = trial5.Fold(
                "wf_01",
                (date(2023, 1, 2),),
                (date(2024, 1, 2),),
            )
            grouped, skipped = trial5.load_fold_minutes(
                minute_dir, fold, ["FPT"]
            )
            self.assertEqual(skipped, 0)
            self.assertEqual(len(grouped["FPT"][date(2024, 1, 2)]), 1)

    def test_settlement_uses_observed_sessions_and_afternoon(self) -> None:
        config = trial5.Config()
        sessions = (
            date(2024, 1, 5),  # Friday, T
            date(2024, 1, 8),  # Monday, T+1
            date(2024, 1, 9),  # Tuesday, T+2
        )
        result = trial5.settlement_datetime(0, sessions, config)
        self.assertEqual(result, datetime(2024, 1, 9, 13, 0))

    def test_account_cannot_sell_before_t_plus_two_afternoon(self) -> None:
        config = trial5.Config()
        train_dates = tuple(
            date(2023, 1, 2) + timedelta(days=index)
            for index in range(60)
        )
        oos_dates = tuple(
            date(2023, 4, 1) + timedelta(days=index)
            for index in range(12)
        )
        fold = trial5.Fold("wf_01", train_dates, oos_dates)
        rows = [
            daily_bar(
                trading_date,
                close_vnd=54_000 + index * 100,
            )
            for index, trading_date in enumerate(train_dates)
        ]
        rows.extend(daily_bar(value, close_vnd=59_900) for value in oos_dates)
        minutes: dict[date, list[trial5.MinuteBar]] = {}
        for index, trading_date in enumerate(oos_dates):
            when = datetime.combine(trading_date, trial5.time(14, 0))
            if index == 0:
                bar = minute_bar(
                    when,
                    matched_open=58_700,
                    matched_high=58_800,
                    matched_low=58_600,
                    matched_close=58_600,
                    best_bid=58_600,
                    best_ask=58_700,
                )
            elif index in {1, 2, 5, 6}:
                bar = minute_bar(
                    when,
                    matched_open=60_000,
                    matched_high=60_100,
                    matched_low=59_900,
                    matched_close=60_000,
                    best_bid=60_000,
                    best_ask=60_100,
                )
            elif index in {3, 4}:
                bar = minute_bar(
                    when,
                    matched_open=58_700,
                    matched_high=58_800,
                    matched_low=58_600,
                    matched_close=58_600,
                    best_bid=58_600,
                    best_ask=58_700,
                )
            else:
                bar = minute_bar(
                    when,
                    matched_open=59_900,
                    matched_high=60_000,
                    matched_low=59_800,
                    matched_close=59_900,
                    best_bid=59_800,
                    best_ask=59_900,
                )
            minutes[trading_date] = [bar]
        result = trial5.simulate_account(
            fold,
            "FPT",
            {"atr20_pct": 0.02},
            rows,
            minutes,
            50_000_000,
            config,
        )
        self.assertTrue(result.valid)
        sides = [row["side"] for row in result.trades]
        self.assertEqual(sides, ["BUY", "SELL", "BUY", "SELL"])
        buy_time = result.trades[0]["event_time"]
        sell_time = result.trades[1]["event_time"]
        self.assertEqual(buy_time.date(), oos_dates[0])
        self.assertGreaterEqual(sell_time.date(), oos_dates[2])
        self.assertEqual(
            result.trades[0]["tradeable_quantity_after"], 0
        )
        # Sale proceeds and the cell itself remain unavailable until T+2
        # afternoon, despite ample reserve cash.
        self.assertGreater(result.trades[1]["pending_cash_after_vnd"], 0)
        self.assertEqual(result.trades[2]["event_time"].date(), oos_dates[4])
        self.assertEqual(result.trades[2]["cost_scenario"], "primary")
        self.assertTrue(
            all(set(row) == set(trial5.TRADE_FIELDS) for row in result.trades)
        )
        self.assertTrue(
            all(
                set(row) == set(trial5.ACCOUNT_DAILY_FIELDS)
                for row in result.daily_states
            )
        )

    def test_doubled_execution_haircut_is_adverse(self) -> None:
        config = trial5.Config()
        primary_buy = trial5._execution_buy_price(
            70_000, 71_000, config, 1.0
        )
        doubled_buy = trial5._execution_buy_price(
            70_000, 71_000, config, 2.0
        )
        primary_sell = trial5._execution_sell_price(
            70_000, None, config, 1.0
        )
        doubled_sell = trial5._execution_sell_price(
            70_000, None, config, 2.0
        )
        self.assertGreaterEqual(doubled_buy, primary_buy)
        self.assertLessEqual(doubled_sell, primary_sell)


class GovernanceAndGateTests(unittest.TestCase):
    def test_empty_csv_keeps_fixed_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty.csv"
            trial5.write_csv(path, [], trial5.QUARANTINE_FIELDS)
            self.assertEqual(
                path.read_text(encoding="utf-8").strip(),
                ",".join(trial5.QUARANTINE_FIELDS),
            )

    def test_decision_lock_is_create_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lock.json"
            trial5.publish_lock(path, {"run_id": "first"})
            with self.assertRaises(RuntimeError):
                trial5.publish_lock(path, {"run_id": "second"})

    def test_prerun_seal_rejects_changed_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "seal.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": trial5.SCHEMA_VERSION,
                        "trial_id": trial5.TRIAL_ID,
                        "fold_ids": list(trial5.CANONICAL_FOLD_IDS),
                        "identity_hashes": {"script": "old"},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                trial5.validate_prerun_seal(
                    path, {"script": "changed"}
                )

    def test_orphan_publication_cannot_be_trusted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "arbitrary.txt").write_text("x", encoding="utf-8")
            (path / "manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": trial5.SCHEMA_VERSION,
                        "trial_id": trial5.TRIAL_ID,
                        "result_fingerprint_sha256": "fingerprint",
                        "output_hashes": {},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(RuntimeError):
                trial5.validate_published(path, "fingerprint")

    def test_sample_gate_counts_rotations_not_ticker_rows(self) -> None:
        config = trial5.Config()
        folds = []
        for index in range(15):
            folds.append(
                {
                    "fold_id": f"wf_{index + 1:02d}",
                    "valid": True,
                    "doubled_cost_valid": True,
                    "net_return": 0.01,
                    "doubled_cost_return": 0.005,
                    "benchmark_return": 0.0,
                    "buy_count": 1,
                    "completed_grid_cycles": 3,
                }
            )
        trades = []
        for index in range(45):
            fold_id = f"wf_{index % 15 + 1:02d}"
            trades.append(
                {
                    "fold_id": fold_id,
                    "side": "SELL",
                    "reason": "grid_target",
                    "cost_scenario": "primary",
                    "realized_pnl_vnd": 100_000,
                }
            )
            trades.append(
                {
                    "fold_id": fold_id,
                    "side": "SELL",
                    "reason": "grid_target",
                    "cost_scenario": "doubled",
                    "realized_pnl_vnd": 50_000,
                }
            )
        daily = [
            {
                "fold_id": row["fold_id"],
                "trading_date": "2024-01-01",
                "fold_return_to_date": 0.01,
            }
            for row in folds
        ]
        report = trial5.evaluate_gates(folds, trades, daily, config)
        self.assertEqual(report["statistics"]["folds_total"], 15)
        self.assertEqual(
            report["sample_gates"]["minimum_valid_folds"]["observed"], 15
        )
        self.assertEqual(
            report["statistics"]["doubled_cost_trade_profit_factor"],
            "infinity",
        )

    def test_odd_carried_capital_is_not_lost_between_slots(self) -> None:
        config = trial5.Config()
        fold = trial5.Fold(
            "wf_01",
            (date(2023, 1, 2),),
            (date(2024, 1, 2), date(2024, 1, 3)),
        )
        fold_row, _, _, _, daily_rows = trial5.simulate_fold(
            fold,
            [],
            [],
            {},
            {},
            config,
            100_000_001,
        )
        self.assertEqual(fold_row["ending_capital_vnd"], 100_000_001)
        self.assertEqual(set(fold_row), set(trial5.FOLD_FIELDS))
        self.assertTrue(
            all(
                row["portfolio_equity_vnd"] == 100_000_001
                for row in daily_rows
            )
        )
        self.assertTrue(
            all(
                set(row) == set(trial5.PORTFOLIO_DAILY_FIELDS)
                for row in daily_rows
            )
        )

    def test_portfolio_kill_uses_next_session_and_persists(self) -> None:
        dates = (
            date(2024, 1, 2),
            date(2024, 1, 3),
            date(2024, 1, 4),
        )
        triggered, effective, high_water = trial5.detect_portfolio_kill(
            [
                {"portfolio_equity_vnd": 101_000_000},
                {"portfolio_equity_vnd": 95_000_000},
                {"portfolio_equity_vnd": 94_000_000},
            ],
            dates,
            100_000_000,
            -0.05,
        )
        self.assertTrue(triggered)
        self.assertEqual(effective, dates[2])
        self.assertEqual(high_water, 101_000_000)

        config = trial5.Config()
        fold = trial5.Fold("wf_02", (date(2023, 1, 2),), dates)
        fold_row, _, _, _, daily_rows = trial5.simulate_fold(
            fold,
            [],
            [],
            {},
            {},
            config,
            95_000_000,
            101_000_000,
            True,
        )
        self.assertTrue(fold_row["valid"])
        self.assertTrue(
            all(row["portfolio_kill_active"] for row in daily_rows)
        )

    def test_missing_minute_row_limit_is_exact(self) -> None:
        config = trial5.Config()
        allowed = {
            "status": "passed_development_screen",
            "advance_to_final_confirmation": True,
        }
        trial5.apply_data_quality_gate(allowed, 2, 0, config)
        self.assertEqual(allowed["status"], "passed_development_screen")

        rejected = {
            "status": "passed_development_screen",
            "advance_to_final_confirmation": True,
        }
        trial5.apply_data_quality_gate(rejected, 3, 0, config)
        self.assertEqual(rejected["status"], "invalid_run")
        self.assertFalse(rejected["advance_to_final_confirmation"])


if __name__ == "__main__":
    unittest.main()
