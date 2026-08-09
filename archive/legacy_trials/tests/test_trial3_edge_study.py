from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from study_trial3_pullback_edge import (
    Config,
    DailyBar,
    acquisition_cash,
    build_fold_summary,
    build_event,
    deduplicate_candidates,
    describe_returns,
    evaluate_gates,
    exact_net_pnl,
    exact_net_return,
    first_barrier_observation,
    generate_fold_candidates,
    net_sale_cash,
    read_development_vcb,
    read_in_sample_assignments,
    select_fold_bars,
    select_non_overlapping_primary,
    signal_feature,
    write_csv,
)


def trading_dates(start: date, count: int) -> list[date]:
    result: list[date] = []
    current = start
    while len(result) < count:
        if current.weekday() < 5:
            result.append(current)
        current += timedelta(days=1)
    return result


def make_bar(
    trading_date: date,
    close_vnd: int,
    *,
    open_vnd: int | None = None,
    high_vnd: int | None = None,
    low_vnd: int | None = None,
    reset: bool = False,
    reference_available: bool = True,
) -> DailyBar:
    open_price = close_vnd if open_vnd is None else open_vnd
    high_price = (
        max(open_price, close_vnd) + 1_000
        if high_vnd is None
        else high_vnd
    )
    low_price = (
        min(open_price, close_vnd) - 1_000
        if low_vnd is None
        else low_vnd
    )
    return DailyBar(
        trading_date=trading_date,
        open_vnd=open_price,
        high_vnd=high_price,
        low_vnd=low_price,
        close_vnd=close_vnd,
        ceiling_vnd=(
            close_vnd + 7_000 if reference_available else None
        ),
        floor_vnd=(
            close_vnd - 7_000 if reference_available else None
        ),
        reference_reset=reset,
        reference_available=reference_available,
        reset_verifiable=reference_available,
    )


def qualifying_history(extra_sessions: int = 11) -> list[DailyBar]:
    dates = trading_dates(date(2024, 1, 2), 50 + extra_sessions)
    closes = [100_000 + index * 500 for index in range(44)]
    # At signal index 49: five-session return is -2.5%, but the last close
    # reverses upward. The longer trend remains positive.
    closes.extend([120_000, 118_500, 117_500, 116_500, 115_500, 117_000])
    bars = [make_bar(day, close) for day, close in zip(dates[:50], closes)]
    # The signal session closes in the upper 80% of its range, satisfying
    # the pre-registered reversal-quality condition.
    signal = bars[49]
    bars[49] = make_bar(
        signal.trading_date,
        signal.close_vnd,
        high_vnd=117_500,
        low_vnd=115_000,
    )
    bars.extend(make_bar(day, 117_000) for day in dates[50:])
    return bars


class CostTests(unittest.TestCase):
    def test_exact_one_lot_cashflows(self) -> None:
        config = Config()
        self.assertEqual(
            acquisition_cash(100_000, config, cost_multiplier=1.0),
            10_020_000,
        )
        self.assertEqual(
            net_sale_cash(103_000, config, cost_multiplier=1.0),
            10_269_100,
        )
        self.assertAlmostEqual(
            exact_net_return(
                100_000, 103_000, config, cost_multiplier=1.0
            ),
            249_100 / 10_020_000,
        )
        self.assertEqual(
            exact_net_pnl(
                100_000, 103_000, config, cost_multiplier=1.0
            ),
            249_100,
        )
        doubled = exact_net_return(
            100_000, 103_000, config, cost_multiplier=2.0
        )
        self.assertLess(doubled, 249_100 / 10_020_000)

    def test_profit_factor_uses_exact_vnd_pnl(self) -> None:
        events = [
            {
                "gross_return_t5": 0.11,
                "net_return_t5": 0.10,
                "net_pnl_vnd_t5": 100,
                "double_cost_net_return_t5": 0.05,
                "double_cost_net_pnl_vnd_t5": 50,
                "mfe_t5": 0.12,
                "mae_t5": -0.01,
            },
            {
                "gross_return_t5": -0.005,
                "net_return_t5": -0.01,
                "net_pnl_vnd_t5": -200,
                "double_cost_net_return_t5": -0.02,
                "double_cost_net_pnl_vnd_t5": -100,
                "mfe_t5": 0.01,
                "mae_t5": -0.03,
            },
        ]
        summary = describe_returns(events, 5)
        self.assertEqual(summary["net_profit_factor"], 0.5)
        self.assertEqual(summary["doubled_cost_profit_factor"], 0.5)


class SignalTests(unittest.TestCase):
    def test_signal_uses_only_completed_signal_bar(self) -> None:
        config = Config()
        bars = qualifying_history()
        feature = signal_feature(bars, 49, config)
        self.assertTrue(feature.eligible, feature.failed_conditions)
        self.assertEqual(feature.as_of_date, bars[49].trading_date)

        # Mutating entry day and all future prices cannot alter the signal.
        changed = list(bars)
        for index in range(50, len(changed)):
            changed[index] = make_bar(
                changed[index].trading_date, 50_000
            )
        self.assertEqual(feature, signal_feature(changed, 49, config))

    def test_zero_range_signal_bar_is_invalid(self) -> None:
        bars = qualifying_history()
        signal = bars[49]
        bars[49] = make_bar(
            signal.trading_date,
            signal.close_vnd,
            high_vnd=signal.close_vnd,
            low_vnd=signal.close_vnd,
        )
        feature = signal_feature(bars, 49, Config())
        self.assertFalse(feature.eligible)
        self.assertIn("zero_range_signal_bar", feature.failed_conditions)

    def test_unverifiable_reference_window_is_invalid(self) -> None:
        bars = qualifying_history()
        target = bars[20]
        bars[20] = make_bar(
            target.trading_date,
            target.close_vnd,
            reference_available=False,
        )
        feature = signal_feature(bars, 49, Config())
        self.assertFalse(feature.eligible)
        self.assertIn(
            "unverified_reference_in_feature_window",
            feature.failed_conditions,
        )


class LabelAndExcursionTests(unittest.TestCase):
    def test_trading_session_horizons_and_excursions(self) -> None:
        bars = qualifying_history()
        config = Config()
        feature = signal_feature(bars, 49, config)
        entry = 50

        # Neutralize the complete T..T+10 path first so only the explicitly
        # defined highs and lows below determine MFE and MAE.
        for index in range(entry, entry + 11):
            bars[index] = make_bar(
                bars[index].trading_date,
                100_000,
                high_vnd=101_000,
                low_vnd=99_000,
            )
        bars[entry] = make_bar(
            bars[entry].trading_date,
            100_000,
            open_vnd=100_000,
            high_vnd=102_000,
            low_vnd=99_000,
        )
        # T+3
        bars[entry + 1] = make_bar(
            bars[entry + 1].trading_date,
            101_000,
            high_vnd=106_000,
            low_vnd=97_000,
        )
        bars[entry + 3] = make_bar(
            bars[entry + 3].trading_date,
            103_000,
            high_vnd=104_000,
            low_vnd=100_000,
        )
        # T+5
        bars[entry + 4] = make_bar(
            bars[entry + 4].trading_date,
            104_000,
            high_vnd=108_000,
            low_vnd=96_000,
        )
        bars[entry + 5] = make_bar(
            bars[entry + 5].trading_date,
            105_000,
            high_vnd=106_000,
            low_vnd=101_000,
        )
        # T+10
        bars[entry + 8] = make_bar(
            bars[entry + 8].trading_date,
            101_000,
            high_vnd=110_000,
            low_vnd=90_000,
        )
        bars[entry + 10] = make_bar(
            bars[entry + 10].trading_date,
            98_000,
            high_vnd=99_000,
            low_vnd=97_000,
        )

        event = build_event("wf_test", bars, 49, feature, config)
        self.assertEqual(event["entry_date"], bars[50].trading_date)
        self.assertEqual(event["exit_date_t3"], bars[53].trading_date)
        self.assertEqual(event["exit_date_t5"], bars[55].trading_date)
        self.assertEqual(event["exit_date_t10"], bars[60].trading_date)
        self.assertAlmostEqual(event["gross_return_t3"], 0.03)
        self.assertAlmostEqual(event["gross_return_t5"], 0.05)
        self.assertAlmostEqual(event["gross_return_t10"], -0.02)
        self.assertAlmostEqual(event["mfe_t3"], 0.06)
        self.assertAlmostEqual(event["mae_t3"], -0.03)
        self.assertAlmostEqual(event["mfe_t5"], 0.08)
        self.assertAlmostEqual(event["mae_t5"], -0.04)
        self.assertAlmostEqual(event["mfe_t10"], 0.10)
        self.assertAlmostEqual(event["mae_t10"], -0.10)

    def test_same_bar_target_and_stop_is_ambiguous(self) -> None:
        bars = qualifying_history()
        entry = 50
        bars[entry] = make_bar(
            bars[entry].trading_date,
            100_000,
            open_vnd=100_000,
            high_vnd=102_000,
            low_vnd=96_000,
        )
        result = first_barrier_observation(bars, entry, Config())
        self.assertEqual(result[0], "both_hit_same_bar")
        self.assertTrue(result[3])


class BoundaryAndCorporateActionTests(unittest.TestCase):
    def test_incomplete_t10_is_purged(self) -> None:
        bars = qualifying_history(extra_sessions=5)
        candidates, _, counts = generate_fold_candidates(
            "wf_test", bars, Config()
        )
        self.assertEqual(candidates, [])
        self.assertGreaterEqual(counts["purged_incomplete_t10"], 1)

    def test_forward_reset_quarantines_label(self) -> None:
        bars = qualifying_history()
        target = bars[54]
        bars[54] = make_bar(
            target.trading_date,
            target.close_vnd,
            reset=True,
        )
        candidates, quarantined, counts = generate_fold_candidates(
            "wf_test", bars, Config()
        )
        self.assertEqual(candidates, [])
        self.assertGreaterEqual(
            counts["quarantined_forward_reference_reset"], 1
        )
        self.assertTrue(quarantined)

    def test_forward_unverified_reference_quarantines_label(self) -> None:
        bars = qualifying_history()
        target = bars[54]
        bars[54] = make_bar(
            target.trading_date,
            target.close_vnd,
            reference_available=False,
        )
        candidates, quarantined, counts = generate_fold_candidates(
            "wf_test", bars, Config()
        )
        self.assertEqual(candidates, [])
        self.assertEqual(
            counts["quarantined_forward_unverified_reference"], 1
        )
        self.assertTrue(quarantined)

    def test_final_test_prices_are_ignored_before_parsing(self) -> None:
        headers = [
            "datetime",
            "tickersymbol",
            "open",
            "high",
            "low",
            "close",
            "ceiling",
            "floor",
            "primary_split",
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "daily.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=headers)
                writer.writeheader()
                writer.writerow(
                    {
                        "datetime": "2024-01-02",
                        "tickersymbol": "VCB",
                        "open": "70",
                        "high": "71",
                        "low": "69",
                        "close": "70",
                        "ceiling": "74.9",
                        "floor": "65.1",
                        "primary_split": "development",
                    }
                )
                writer.writerow(
                    {
                        "datetime": "2025-07-14",
                        "tickersymbol": "VCB",
                        "open": "LOCKED",
                        "high": "LOCKED",
                        "low": "LOCKED",
                        "close": "LOCKED",
                        "ceiling": "LOCKED",
                        "floor": "LOCKED",
                        "primary_split": "final_test",
                    }
                )
            bars = read_development_vcb(path)
            self.assertEqual(len(bars), 1)
            self.assertEqual(bars[0].close_vnd, 70_000)

    def test_unselected_development_prices_are_not_parsed(self) -> None:
        headers = [
            "datetime",
            "tickersymbol",
            "open",
            "high",
            "low",
            "close",
            "ceiling",
            "floor",
            "primary_split",
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "daily.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=headers)
                writer.writeheader()
                writer.writerow(
                    {
                        "datetime": "2024-01-02",
                        "tickersymbol": "VCB",
                        "open": "70",
                        "high": "71",
                        "low": "69",
                        "close": "70",
                        "ceiling": "74.9",
                        "floor": "65.1",
                        "primary_split": "development",
                    }
                )
                writer.writerow(
                    {
                        "datetime": "2024-01-03",
                        "tickersymbol": "VCB",
                        "open": "LOCKED_OOS_PRICE",
                        "high": "LOCKED_OOS_PRICE",
                        "low": "LOCKED_OOS_PRICE",
                        "close": "LOCKED_OOS_PRICE",
                        "ceiling": "LOCKED_OOS_PRICE",
                        "floor": "LOCKED_OOS_PRICE",
                        "primary_split": "development",
                    }
                )
            bars = read_development_vcb(
                path,
                allowed_dates={date(2024, 1, 2)},
            )
            self.assertEqual(len(bars), 1)
            self.assertEqual(bars[0].close_vnd, 70_000)

    def test_oos_assignments_are_not_returned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "assignments.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["fold_id", "trading_date", "role"],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "fold_id": "wf_01",
                        "trading_date": "2024-01-02",
                        "role": "in_sample",
                    }
                )
                writer.writerow(
                    {
                        "fold_id": "wf_01",
                        "trading_date": "2024-01-03",
                        "role": "walk_forward_oos",
                    }
                )
            assignments = read_in_sample_assignments(path)
            self.assertEqual(
                assignments["wf_01"], [date(2024, 1, 2)]
            )

    def test_assignment_cannot_have_both_roles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "assignments.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["fold_id", "trading_date", "role"],
                )
                writer.writeheader()
                for role in ("in_sample", "walk_forward_oos"):
                    writer.writerow(
                        {
                            "fold_id": "wf_01",
                            "trading_date": "2024-01-02",
                            "role": role,
                        }
                    )
            with self.assertRaisesRegex(ValueError, "both in-sample and OOS"):
                read_in_sample_assignments(path)

    def test_fold_dates_must_be_contiguous(self) -> None:
        bars = qualifying_history()
        global_calendar = [bar.trading_date for bar in bars]
        with self.assertRaisesRegex(ValueError, "not a contiguous"):
            select_fold_bars(
                bars,
                [global_calendar[0], global_calendar[2]],
                global_calendar,
            )

    def test_raw_reference_reset_is_detected(self) -> None:
        headers = [
            "datetime",
            "tickersymbol",
            "open",
            "high",
            "low",
            "close",
            "ceiling",
            "floor",
            "primary_split",
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "daily.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=headers)
                writer.writeheader()
                for trading_date, ceiling, floor in (
                    ("2024-01-02", "107", "93"),
                    ("2024-01-03", "107", "93"),
                    ("2024-01-04", "110", "96"),
                ):
                    writer.writerow(
                        {
                            "datetime": trading_date,
                            "tickersymbol": "VCB",
                            "open": "100",
                            "high": "101",
                            "low": "99",
                            "close": "100",
                            "ceiling": ceiling,
                            "floor": floor,
                            "primary_split": "development",
                        }
                    )
            bars = read_development_vcb(path)
            self.assertFalse(bars[0].reset_verifiable)
            self.assertFalse(bars[1].reference_reset)
            self.assertTrue(bars[2].reference_reset)


class OverlapAndGateTests(unittest.TestCase):
    def test_overlapping_folds_count_same_event_once(self) -> None:
        bars = qualifying_history()
        feature = signal_feature(bars, 49, Config())
        event = build_event("wf_01", bars, 49, feature, Config())
        duplicate = event.copy()
        duplicate["fold_id"] = "wf_02"
        unique = deduplicate_candidates([event, duplicate])
        self.assertEqual(len(unique), 1)
        self.assertEqual(unique[0]["fold_membership_count"], 2)
        self.assertEqual(
            unique[0]["fold_memberships"], "wf_01|wf_02"
        )

    def test_overlapping_folds_must_agree_on_features(self) -> None:
        bars = qualifying_history()
        feature = signal_feature(bars, 49, Config())
        event = build_event("wf_01", bars, 49, feature, Config())
        disagreement = event.copy()
        disagreement["fold_id"] = "wf_02"
        disagreement["sma20"] = float(disagreement["sma20"]) + 0.001
        with self.assertRaisesRegex(
            ValueError, "Overlapping folds disagree"
        ):
            deduplicate_candidates([event, disagreement])

    def test_fold_stability_uses_configured_minimum(self) -> None:
        config = Config(minimum_fold_events=2)
        rows = build_fold_summary(
            [
                {
                    "fold_memberships": "wf_01",
                    "net_return_t5": 0.01,
                },
                {
                    "fold_memberships": "wf_01",
                    "net_return_t5": -0.005,
                },
            ],
            ["wf_01"],
            config,
        )
        self.assertTrue(rows[0]["evaluable_for_stability"])

    def test_primary_events_do_not_overlap_t10(self) -> None:
        calendar = trading_dates(date(2024, 1, 2), 30)
        candidates = [
            {"entry_date": calendar[0]},
            {"entry_date": calendar[5]},
            {"entry_date": calendar[11]},
        ]
        selected = select_non_overlapping_primary(
            candidates, calendar, Config()
        )
        self.assertEqual(
            [event["entry_date"] for event in selected],
            [calendar[0], calendar[11]],
        )

    def test_zero_event_result_is_inconclusive(self) -> None:
        fold_summary = [
            {
                "fold_id": "wf_01",
                "primary_events": 0,
                "mean_net_return_t5": None,
                "median_net_return_t5": None,
                "win_rate_t5": None,
                "profit_factor_t5": None,
                "evaluable_for_stability": False,
            }
        ]
        report = evaluate_gates([], fold_summary, Config())
        self.assertEqual(report["status"], "inconclusive_sample")
        self.assertFalse(report["advance_to_execution_backtest"])

    def test_empty_csv_keeps_its_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty.csv"
            write_csv(path, [], ["first", "second"])
            self.assertEqual(path.read_text(encoding="utf-8"), "first,second\n")


if __name__ == "__main__":
    unittest.main()
