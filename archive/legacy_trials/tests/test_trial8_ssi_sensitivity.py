from __future__ import annotations

import unittest

from study_trial8_ssi_sensitivity import Gate, activation_passes, summarize


class GateTests(unittest.TestCase):
    def test_moderate_gate_admits_less_extreme_deviation(self) -> None:
        features = {
            "residual_z5": -0.60,
            "residual_1": 0.01,
            "market_return5": 0.00,
        }
        self.assertFalse(activation_passes(
            features, True, Gate("strict", -0.75, "and")
        ))
        self.assertTrue(activation_passes(
            features, True, Gate("moderate", -0.50, "and")
        ))

    def test_loose_confirmation_uses_or_not_future_data(self) -> None:
        features = {
            "residual_z5": -0.60,
            "residual_1": -0.01,
            "market_return5": 0.00,
        }
        self.assertFalse(activation_passes(
            features, True, Gate("moderate", -0.50, "and")
        ))
        self.assertTrue(activation_passes(
            features, True, Gate("loose", -0.50, "or")
        ))


class SummaryTests(unittest.TestCase):
    def test_larger_quantity_does_not_invent_viability(self) -> None:
        base = {
            "target_sale_count": 1,
            "lower_level_filled": False,
            "normal_target_gain_vnd": 100,
            "risk_time_loss_vnd": 0,
            "modeled_max_inventory_notional_vnd": 10_000_000,
        }
        episodes = [
            {**base, "net_pnl_vnd": 100, "double_cost_net_pnl_vnd": 50},
            {
                **base,
                "target_sale_count": 0,
                "normal_target_gain_vnd": 0,
                "risk_time_loss_vnd": -300,
                "net_pnl_vnd": -300,
                "double_cost_net_pnl_vnd": -350,
            },
        ]
        row = summarize(Gate("x", -0.5, "and"), 300, episodes, episodes)
        self.assertEqual(row["status"], "exploratory_not_viable")
        self.assertLess(row["total_net_pnl_vnd"], 0)


if __name__ == "__main__":
    unittest.main()
