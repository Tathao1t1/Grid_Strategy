from __future__ import annotations

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import study_trial6_mean_reversion as trial6
import study_trial11_trend_grid as trial11
from study_trial13_dense_grid_ev import (
    FEATURE_NAMES,
    ModelConfig,
    final_training_fold,
    fit_ridge,
    generate_observations,
    model_space,
    run_final_oos,
    select_campaigns,
)


def sessions(start: date, count: int) -> list[date]:
    values: list[date] = []
    current = start
    while len(values) < count:
        if current.weekday() < 5:
            values.append(current)
        current += timedelta(days=1)
    return values


def feature_row(value: float, target: float = 0.0) -> dict[str, object]:
    row: dict[str, object] = {
        name: 0.0 for name in FEATURE_NAMES
    }
    row["residual_z5"] = value
    row["campaign_return"] = target
    return row


def campaign(
    ticker: str,
    sector: str,
    signal: date,
    entry: date,
    exit_date: date,
    score: float,
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "sector": sector,
        "signal_date": signal.isoformat(),
        "entry_date": entry.isoformat(),
        "exit_date": exit_date.isoformat(),
        "predicted_net_return": score,
        "predicted_downside": 0.0,
        "model_score": score,
    }


class DenseGridEVTests(unittest.TestCase):
    def test_frozen_search_has_54_unique_configurations(self) -> None:
        values = model_space()
        self.assertEqual(len(values), 54)
        self.assertEqual(len({value.key() for value in values}), 54)

    def test_ridge_prediction_uses_feature_direction(self) -> None:
        rows = [
            feature_row(-2.0),
            feature_row(-1.0),
            feature_row(1.0),
            feature_row(2.0),
        ]
        model = fit_ridge(rows, [-0.02, -0.01, 0.01, 0.02], 0.1)
        self.assertGreater(
            model.predict([2.0] + [0.0] * (len(FEATURE_NAMES) - 1)),
            model.predict([-2.0] + [0.0] * (len(FEATURE_NAMES) - 1)),
        )

    def test_selection_respects_sector_and_top_k(self) -> None:
        calendar = sessions(date(2024, 1, 2), 20)
        rows = [
            campaign("VCB", "banks", calendar[1], calendar[2], calendar[5], 0.03),
            campaign("MBB", "banks", calendar[1], calendar[2], calendar[4], 0.02),
            campaign("SSI", "securities", calendar[1], calendar[2], calendar[6], 0.01),
        ]
        selected = select_campaigns(
            rows, calendar, ModelConfig(10, 0.0, 0.0, 3)
        )
        self.assertEqual(
            [row["ticker"] for row in selected], ["VCB", "SSI"]
        )

    def test_final_training_dates_precede_rotation(self) -> None:
        calendar = sessions(date(2024, 7, 1), 400)
        oos = tuple(calendar[270:310])
        rotation = trial6.Fold("final_01", (), oos)
        prepared = final_training_fold(rotation, calendar)
        self.assertTrue(prepared.train_dates)
        self.assertLess(max(prepared.train_dates), min(prepared.oos_dates))
        self.assertTrue(set(prepared.train_dates).isdisjoint(prepared.oos_dates))

    def test_dense_labels_are_purged_at_partition_boundary(self) -> None:
        calendar = sessions(date(2024, 1, 2), 30)
        fold = trial6.Fold("test", tuple(calendar), ())
        dense = {
            (ticker, index): {name: 0.0 for name in FEATURE_NAMES}
            for ticker in trial11.TICKERS
            for index in range(len(calendar))
        }

        def fake_campaign(
            ticker: str, signal_index: int, *_args: object, **_kwargs: object
        ) -> dict[str, object]:
            return {
                "ticker": ticker,
                "signal_date": calendar[signal_index].isoformat(),
                "campaign_return": 0.0,
            }

        with patch(
            "study_trial13_dense_grid_ev.trial11.simulate_campaign",
            side_effect=fake_campaign,
        ):
            rows = generate_observations(
                fold, fold.train_dates, "test", {}, calendar, dense, {}
            )
        latest_signal = max(
            date.fromisoformat(str(row["signal_date"])) for row in rows
        )
        self.assertEqual(latest_signal, calendar[18])
        self.assertLess(latest_signal, calendar[-10])

    def test_final_requires_validation_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(PermissionError):
                run_final_oos(root / "development", root / "final")


if __name__ == "__main__":
    unittest.main()
