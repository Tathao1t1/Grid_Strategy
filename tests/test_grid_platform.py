from __future__ import annotations

import unittest
from datetime import date, datetime, time
from decimal import Decimal

from grid_platform import (
    BacktestBroker,
    ExecutionPolicy,
    FeeSchedule,
    InsufficientSettledInventory,
    MarketSnapshot,
    Order,
    OrderStatus,
    OrderType,
    Side,
    TradingCalendar,
)


SESSIONS = (
    date(2024, 1, 5),  # Friday
    date(2024, 1, 8),  # Monday
    date(2024, 1, 9),  # Tuesday
    date(2024, 1, 10),
    date(2024, 1, 11),
)


def snapshot(
    when: datetime,
    *,
    bid: int = 99_900,
    ask: int = 100_000,
    last: int = 99_900,
    bid_quantity: int = 10_000,
    ask_quantity: int = 10_000,
    matched_quantity: int = 10_000,
) -> MarketSnapshot:
    return MarketSnapshot(
        event_time=when,
        ticker="SSI",
        best_bid_vnd=bid,
        best_bid_quantity=bid_quantity,
        best_ask_vnd=ask,
        best_ask_quantity=ask_quantity,
        last_price_vnd=last,
        matched_quantity=matched_quantity,
    )


class MatchingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.broker = BacktestBroker(
            500_000_000,
            TradingCalendar(SESSIONS),
        )

    def test_order_cannot_fill_on_snapshot_that_created_it(self) -> None:
        when = datetime(2024, 1, 5, 9, 30)
        order = Order(
            "buy-1",
            "SSI",
            Side.BUY,
            100,
            OrderType.LIMIT,
            when,
            100_000,
        )
        self.broker.submit(order)
        events = self.broker.process_snapshot(snapshot(when))
        self.assertEqual(events[0].reason, "not_yet_active")
        self.assertEqual(order.status, OrderStatus.OPEN)

    def test_limit_fill_requires_book_touch_and_last_trade_confirmation(self) -> None:
        order = Order(
            "buy-1",
            "SSI",
            Side.BUY,
            100,
            OrderType.LIMIT,
            datetime(2024, 1, 5, 9, 29),
            100_000,
            "rotation-01",
        )
        self.broker.submit(order)
        no_confirmation = self.broker.process_snapshot(
            snapshot(datetime(2024, 1, 5, 9, 30), last=100_000)
        )
        self.assertEqual(no_confirmation[0].reason, "limit_not_confirmed")
        filled = self.broker.process_snapshot(
            snapshot(datetime(2024, 1, 5, 9, 31), last=99_900)
        )
        self.assertEqual(filled[0].reason, "matched")
        self.assertEqual(order.status, OrderStatus.FILLED)
        self.assertEqual(
            self.broker.account.total_quantity("SSI", "rotation-01"), 100
        )

    def test_full_fill_policy_rejects_insufficient_minute_capacity(self) -> None:
        order = Order(
            "buy-1",
            "SSI",
            Side.BUY,
            1_000,
            OrderType.LIMIT,
            datetime(2024, 1, 5, 9, 29),
            100_000,
        )
        self.broker.submit(order)
        # Five percent of 10,000 shares supports only 500 shares.
        events = self.broker.process_snapshot(
            snapshot(datetime(2024, 1, 5, 9, 30))
        )
        self.assertEqual(events[0].reason, "insufficient_liquidity")
        self.assertEqual(order.filled_quantity, 0)

    def test_spread_gate_is_applied_before_matching(self) -> None:
        order = Order(
            "buy-1",
            "SSI",
            Side.BUY,
            100,
            OrderType.MARKET,
            datetime(2024, 1, 5, 9, 29),
        )
        self.broker.submit(order)
        events = self.broker.process_snapshot(
            snapshot(
                datetime(2024, 1, 5, 9, 30),
                bid=99_000,
                ask=100_000,
            )
        )
        self.assertEqual(events[0].reason, "spread_too_wide")


class SettlementAndAccountTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calendar = TradingCalendar(SESSIONS)
        self.policy = ExecutionPolicy()
        self.fees = FeeSchedule()
        self.broker = BacktestBroker(
            500_000_000,
            self.calendar,
            self.policy,
            self.fees,
        )

    def buy_on_friday(self, campaign: str = "rotation-01") -> None:
        self.broker.submit(
            Order(
                "buy-1",
                "SSI",
                Side.BUY,
                100,
                OrderType.LIMIT,
                datetime(2024, 1, 5, 9, 29),
                100_000,
                campaign,
            )
        )
        events = self.broker.process_snapshot(
            snapshot(datetime(2024, 1, 5, 9, 30))
        )
        self.assertEqual(events[0].reason, "matched")

    def test_buy_cash_and_costs_reconcile_exactly(self) -> None:
        self.buy_on_friday()
        fill = self.broker.account.ledger[0]
        self.assertEqual(fill.event_type, "BUY_FILL")
        self.assertEqual(fill.commission_vnd, 15_000)
        self.assertEqual(fill.available_cash_change_vnd, -10_015_000)
        marked = self.broker.account.mark(
            datetime(2024, 1, 5, 15, 0), {"SSI": 100_000}
        )
        # Marking assumes a sale and therefore includes estimated exit costs.
        self.assertEqual(marked.inventory_liquidation_value_vnd, 9_975_000)
        self.assertEqual(marked.total_pnl_vnd, -40_000)
        self.assertEqual(marked.total_quantity_by_ticker["SSI"], 100)
        self.assertNotIn("SSI", marked.settled_quantity_by_ticker)

    def test_stock_cannot_be_sold_before_t_plus_two_afternoon(self) -> None:
        self.buy_on_friday()
        sell = Order(
            "sell-1",
            "SSI",
            Side.SELL,
            100,
            OrderType.MARKET,
            datetime(2024, 1, 8, 9, 29),
            campaign_id="rotation-01",
        )
        self.broker.submit(sell)
        monday = self.broker.process_snapshot(
            snapshot(
                datetime(2024, 1, 8, 9, 30),
                bid=101_000,
                ask=101_100,
                last=101_000,
            )
        )
        self.assertEqual(
            monday[-1].reason, "insufficient_settled_inventory"
        )
        before_settlement = self.broker.process_snapshot(
            snapshot(
                datetime(2024, 1, 9, 12, 59),
                bid=101_000,
                ask=101_100,
                last=101_000,
            )
        )
        self.assertEqual(
            before_settlement[-1].reason,
            "insufficient_settled_inventory",
        )
        after_settlement = self.broker.process_snapshot(
            snapshot(
                datetime(2024, 1, 9, 13, 1),
                bid=101_000,
                ask=101_100,
                last=101_000,
            )
        )
        self.assertEqual(after_settlement[-1].reason, "matched")

    def test_sale_cash_and_campaign_profit_remain_pending_until_t_plus_two(self) -> None:
        self.buy_on_friday()
        sell = Order(
            "sell-1",
            "SSI",
            Side.SELL,
            100,
            OrderType.MARKET,
            datetime(2024, 1, 9, 13, 0),
            campaign_id="rotation-01",
        )
        self.broker.submit(sell)
        events = self.broker.process_snapshot(
            snapshot(
                datetime(2024, 1, 9, 13, 1),
                bid=101_000,
                ask=101_100,
                last=101_000,
            )
        )
        fill = events[-1].fill
        assert fill is not None
        # Five-basis-point haircut rounds the sale from 101,000 to 100,900.
        self.assertEqual(fill.execution_price_vnd, 100_900)
        self.assertEqual(fill.commission_vnd, 15_135)
        self.assertEqual(fill.sell_tax_vnd, 10_090)
        self.assertEqual(events[-1].realized_pnl_vnd, 49_775)
        self.assertEqual(
            self.broker.account.realized_pnl_by_campaign["rotation-01"],
            49_775,
        )
        marked = self.broker.account.mark(
            datetime(2024, 1, 9, 15, 0), {}
        )
        self.assertEqual(marked.pending_cash_vnd, 10_064_775)
        self.assertEqual(marked.equity_vnd, 500_049_775)
        # Sale on Tuesday settles on Thursday, the second following session.
        settled = self.broker.account.mark(
            datetime(2024, 1, 11, 13, 1), {}
        )
        self.assertEqual(settled.pending_cash_vnd, 0)
        self.assertEqual(settled.available_cash_vnd, 500_049_775)

    def test_configurable_capital_and_fee_schedule(self) -> None:
        broker = BacktestBroker(
            1_000_000_000,
            self.calendar,
            ExecutionPolicy(
                execution_haircut_bps=Decimal("0"),
                limit_penetration_ticks=0,
                settlement_time=time(13, 0),
            ),
            FeeSchedule(
                commission_rate=Decimal("0.001"),
                sell_tax_rate=Decimal("0.001"),
            ),
        )
        self.assertEqual(broker.account.available_cash_vnd, 1_000_000_000)


if __name__ == "__main__":
    unittest.main()
