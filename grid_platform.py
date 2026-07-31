#!/usr/bin/env python3
"""Reusable execution and account platform for the grid research.

The strategy layer may create and cancel orders, but it may not create fills
or directly edit cash and inventory.  This module owns:

* causal minute-snapshot order matching;
* board-lot, spread, displayed-depth and participation constraints;
* configurable commission, sell tax and adverse execution haircut;
* T+2 trading-session settlement for shares and sale proceeds;
* FIFO campaign-level cost basis and realized P&L;
* continuous account marking and reconciliation.

Prices and cash are represented as integer VND.  The default rates reproduce
the assumptions used in the earlier trials; they are research inputs, not
claims about every broker's current fee schedule.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
from enum import Enum
from typing import Iterable, Mapping


class PlatformError(RuntimeError):
    """Base exception for invalid platform operations."""


class SettlementUnavailable(PlatformError):
    """Raised when the supplied calendar does not contain the settlement day."""


class InsufficientCash(PlatformError):
    """Raised when a buy fill costs more than the account's available cash."""


class InsufficientSettledInventory(PlatformError):
    """Raised when a sell exceeds the currently sellable position."""


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"


class OrderStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


def money_cost(notional_vnd: int, rate: Decimal) -> int:
    """Round a proportional cost to the nearest VND."""
    if notional_vnd < 0 or rate < 0:
        raise ValueError("Notional and rate must be non-negative")
    return int(
        (Decimal(notional_vnd) * rate).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


def hsx_tick_vnd(price_vnd: int) -> int:
    """Frozen research tick schedule used by the existing HSX trials."""
    if price_vnd <= 0:
        raise ValueError("Price must be positive")
    if price_vnd < 10_000:
        return 10
    if price_vnd < 50_000:
        return 50
    return 100


def round_to_hsx_tick(price_vnd: Decimal | float | int, side: Side) -> int:
    """Round conservatively: buy prices down and sell prices up."""
    value = Decimal(str(price_vnd))
    if value <= 0:
        raise ValueError("Price must be positive")
    tick = hsx_tick_vnd(max(1, int(value)))
    rounding = ROUND_FLOOR if side is Side.BUY else ROUND_CEILING
    units = (value / Decimal(tick)).quantize(Decimal("1"), rounding=rounding)
    return int(units) * tick


@dataclass(frozen=True)
class FeeSchedule:
    """Broker and tax assumptions.

    Commission applies to both buys and sells.  Sell tax applies to gross
    sale notional, not to profit.
    """

    commission_rate: Decimal = Decimal("0.0015")
    sell_tax_rate: Decimal = Decimal("0.0010")

    def validate(self) -> None:
        if not Decimal("0") <= self.commission_rate < Decimal("0.1"):
            raise ValueError("Invalid commission rate")
        if not Decimal("0") <= self.sell_tax_rate < Decimal("0.1"):
            raise ValueError("Invalid sell-tax rate")

    def costs(self, side: Side, notional_vnd: int) -> tuple[int, int]:
        commission = money_cost(notional_vnd, self.commission_rate)
        sell_tax = (
            money_cost(notional_vnd, self.sell_tax_rate)
            if side is Side.SELL
            else 0
        )
        return commission, sell_tax


@dataclass(frozen=True)
class ExecutionPolicy:
    """Frozen order-matching assumptions for a backtest run."""

    board_lot: int = 100
    maximum_spread_bps: Decimal = Decimal("40")
    maximum_minute_participation: Decimal = Decimal("0.05")
    execution_haircut_bps: Decimal = Decimal("5")
    limit_penetration_ticks: int = 1
    allow_partial_fills: bool = False
    settlement_sessions: int = 2
    settlement_time: time = time(13, 0)

    def validate(self) -> None:
        if self.board_lot <= 0:
            raise ValueError("Board lot must be positive")
        if self.maximum_spread_bps <= 0:
            raise ValueError("Maximum spread must be positive")
        if not Decimal("0") < self.maximum_minute_participation <= Decimal("1"):
            raise ValueError("Minute participation must be in (0, 1]")
        if self.execution_haircut_bps < 0:
            raise ValueError("Execution haircut cannot be negative")
        if self.limit_penetration_ticks < 0:
            raise ValueError("Limit penetration cannot be negative")
        if self.settlement_sessions < 0:
            raise ValueError("Settlement sessions cannot be negative")


@dataclass(frozen=True)
class TradingCalendar:
    """Observed exchange sessions used for settlement calculations."""

    sessions: tuple[date, ...]

    def __post_init__(self) -> None:
        if not self.sessions:
            raise ValueError("Trading calendar cannot be empty")
        if tuple(sorted(set(self.sessions))) != self.sessions:
            raise ValueError("Trading sessions must be unique and sorted")

    def settlement_at(
        self,
        trade_date: date,
        policy: ExecutionPolicy,
    ) -> datetime:
        try:
            trade_index = self.sessions.index(trade_date)
        except ValueError as exc:
            raise SettlementUnavailable(
                f"Trade date {trade_date} is absent from the calendar"
            ) from exc
        settlement_index = trade_index + policy.settlement_sessions
        if settlement_index >= len(self.sessions):
            raise SettlementUnavailable(
                f"No T+{policy.settlement_sessions} session for {trade_date}"
            )
        return datetime.combine(
            self.sessions[settlement_index], policy.settlement_time
        )


@dataclass(frozen=True)
class MarketSnapshot:
    """Last observed level-one book and trading activity for one minute."""

    event_time: datetime
    ticker: str
    best_bid_vnd: int | None
    best_bid_quantity: int | None
    best_ask_vnd: int | None
    best_ask_quantity: int | None
    last_price_vnd: int | None
    matched_quantity: int

    def spread_bps(self) -> Decimal | None:
        if (
            self.best_bid_vnd is None
            or self.best_ask_vnd is None
            or self.best_bid_vnd <= 0
            or self.best_ask_vnd < self.best_bid_vnd
        ):
            return None
        midpoint = (
            Decimal(self.best_bid_vnd) + Decimal(self.best_ask_vnd)
        ) / Decimal(2)
        return (
            Decimal(10_000)
            * Decimal(self.best_ask_vnd - self.best_bid_vnd)
            / midpoint
        )


@dataclass
class Order:
    order_id: str
    ticker: str
    side: Side
    quantity: int
    order_type: OrderType
    submitted_at: datetime
    limit_price_vnd: int | None = None
    campaign_id: str = "default"
    status: OrderStatus = OrderStatus.OPEN
    filled_quantity: int = 0

    @property
    def remaining_quantity(self) -> int:
        return self.quantity - self.filled_quantity

    def validate(self, policy: ExecutionPolicy) -> None:
        if not self.order_id:
            raise ValueError("Order ID cannot be empty")
        if not self.ticker:
            raise ValueError("Ticker cannot be empty")
        if self.quantity <= 0 or self.quantity % policy.board_lot:
            raise ValueError(
                f"Order quantity must be a positive multiple of "
                f"{policy.board_lot}"
            )
        if self.order_type is OrderType.LIMIT:
            if self.limit_price_vnd is None or self.limit_price_vnd <= 0:
                raise ValueError("Limit order requires a positive limit price")
            tick = hsx_tick_vnd(self.limit_price_vnd)
            if self.limit_price_vnd % tick:
                raise ValueError("Limit price is not on the frozen HSX tick")
        elif self.limit_price_vnd is not None:
            raise ValueError("Market order cannot have a limit price")


@dataclass(frozen=True)
class Fill:
    order_id: str
    campaign_id: str
    ticker: str
    side: Side
    event_time: datetime
    quantity: int
    reference_book_price_vnd: int
    execution_price_vnd: int
    gross_notional_vnd: int
    commission_vnd: int
    sell_tax_vnd: int

    @property
    def execution_friction_vnd(self) -> int:
        if self.side is Side.BUY:
            per_share = max(
                0, self.execution_price_vnd - self.reference_book_price_vnd
            )
        else:
            per_share = max(
                0, self.reference_book_price_vnd - self.execution_price_vnd
            )
        return per_share * self.quantity


@dataclass(frozen=True)
class MatchResult:
    order_id: str
    reason: str
    fill: Fill | None = None


class MatchingEngine:
    """Convert eligible orders into conservative observable-book fills."""

    def __init__(
        self,
        policy: ExecutionPolicy,
        fees: FeeSchedule,
    ) -> None:
        policy.validate()
        fees.validate()
        self.policy = policy
        self.fees = fees

    def snapshot_capacity(self, snapshot: MarketSnapshot) -> int:
        raw = int(
            Decimal(max(0, snapshot.matched_quantity))
            * self.policy.maximum_minute_participation
        )
        return raw - raw % self.policy.board_lot

    def match(
        self,
        order: Order,
        snapshot: MarketSnapshot,
        available_minute_quantity: int | None = None,
        available_book_quantity: int | None = None,
    ) -> MatchResult:
        if order.status not in {
            OrderStatus.OPEN,
            OrderStatus.PARTIALLY_FILLED,
        }:
            return MatchResult(order.order_id, "order_not_open")
        if snapshot.ticker != order.ticker:
            return MatchResult(order.order_id, "wrong_ticker")
        # A strategy observing this snapshot may only trade on a later one.
        if snapshot.event_time <= order.submitted_at:
            return MatchResult(order.order_id, "not_yet_active")

        spread = snapshot.spread_bps()
        if spread is None:
            return MatchResult(order.order_id, "invalid_or_crossed_book")
        if spread > self.policy.maximum_spread_bps:
            return MatchResult(order.order_id, "spread_too_wide")

        if order.side is Side.BUY:
            book_price = snapshot.best_ask_vnd
            displayed = snapshot.best_ask_quantity
        else:
            book_price = snapshot.best_bid_vnd
            displayed = snapshot.best_bid_quantity
        if book_price is None or book_price <= 0:
            return MatchResult(order.order_id, "missing_book_price")

        if order.order_type is OrderType.LIMIT:
            assert order.limit_price_vnd is not None
            if order.side is Side.BUY and book_price > order.limit_price_vnd:
                return MatchResult(order.order_id, "limit_not_reached")
            if order.side is Side.SELL and book_price < order.limit_price_vnd:
                return MatchResult(order.order_id, "limit_not_reached")
            if snapshot.last_price_vnd is None:
                return MatchResult(order.order_id, "missing_last_trade")
            tick = hsx_tick_vnd(order.limit_price_vnd)
            penetration = tick * self.policy.limit_penetration_ticks
            if (
                order.side is Side.BUY
                and snapshot.last_price_vnd
                > order.limit_price_vnd - penetration
            ):
                return MatchResult(order.order_id, "limit_not_confirmed")
            if (
                order.side is Side.SELL
                and snapshot.last_price_vnd
                < order.limit_price_vnd + penetration
            ):
                return MatchResult(order.order_id, "limit_not_confirmed")

        minute_capacity = (
            self.snapshot_capacity(snapshot)
            if available_minute_quantity is None
            else available_minute_quantity
        )
        book_capacity = (
            displayed
            if available_book_quantity is None
            else available_book_quantity
        )
        if book_capacity is None:
            return MatchResult(order.order_id, "missing_displayed_quantity")
        capacity = min(max(0, minute_capacity), max(0, book_capacity))
        capacity -= capacity % self.policy.board_lot
        remaining = order.remaining_quantity
        if capacity < remaining and not self.policy.allow_partial_fills:
            return MatchResult(order.order_id, "insufficient_liquidity")
        fill_quantity = min(remaining, capacity)
        fill_quantity -= fill_quantity % self.policy.board_lot
        if fill_quantity <= 0:
            return MatchResult(order.order_id, "insufficient_liquidity")

        haircut = self.policy.execution_haircut_bps / Decimal(10_000)
        if order.side is Side.BUY:
            stressed = round_to_hsx_tick(
                Decimal(book_price) * (Decimal("1") + haircut),
                Side.SELL,
            )
            execution_price = (
                min(stressed, order.limit_price_vnd)
                if order.limit_price_vnd is not None
                else stressed
            )
        else:
            stressed = round_to_hsx_tick(
                Decimal(book_price) * (Decimal("1") - haircut),
                Side.BUY,
            )
            execution_price = (
                max(stressed, order.limit_price_vnd)
                if order.limit_price_vnd is not None
                else stressed
            )

        notional = execution_price * fill_quantity
        commission, sell_tax = self.fees.costs(order.side, notional)
        fill = Fill(
            order_id=order.order_id,
            campaign_id=order.campaign_id,
            ticker=order.ticker,
            side=order.side,
            event_time=snapshot.event_time,
            quantity=fill_quantity,
            reference_book_price_vnd=book_price,
            execution_price_vnd=execution_price,
            gross_notional_vnd=notional,
            commission_vnd=commission,
            sell_tax_vnd=sell_tax,
        )
        return MatchResult(order.order_id, "matched", fill)


@dataclass
class PositionLot:
    ticker: str
    campaign_id: str
    acquired_at: datetime
    tradeable_at: datetime
    remaining_quantity: int
    remaining_cost_vnd: int


@dataclass(frozen=True)
class PendingCash:
    campaign_id: str
    available_at: datetime
    amount_vnd: int


@dataclass(frozen=True)
class LedgerEntry:
    event_time: datetime
    event_type: str
    campaign_id: str
    ticker: str
    order_id: str
    quantity: int
    execution_price_vnd: int
    available_cash_change_vnd: int
    pending_cash_change_vnd: int
    commission_vnd: int
    sell_tax_vnd: int
    realized_pnl_vnd: int


@dataclass(frozen=True)
class AccountSnapshot:
    event_time: datetime
    available_cash_vnd: int
    pending_cash_vnd: int
    inventory_liquidation_value_vnd: int
    equity_vnd: int
    total_pnl_vnd: int
    realized_pnl_vnd: int
    unrealized_pnl_vnd: int
    total_commission_vnd: int
    total_sell_tax_vnd: int
    total_quantity_by_ticker: dict[str, int]
    settled_quantity_by_ticker: dict[str, int]


@dataclass
class Account:
    """One portfolio ledger shared by all sectors, tickers and grid campaigns."""

    initial_cash_vnd: int
    calendar: TradingCalendar
    policy: ExecutionPolicy
    fees: FeeSchedule
    available_cash_vnd: int = field(init=False)
    lots: list[PositionLot] = field(default_factory=list)
    pending_cash: list[PendingCash] = field(default_factory=list)
    ledger: list[LedgerEntry] = field(default_factory=list)
    realized_pnl_vnd: int = 0
    realized_pnl_by_campaign: dict[str, int] = field(default_factory=dict)
    total_commission_vnd: int = 0
    total_sell_tax_vnd: int = 0

    def __post_init__(self) -> None:
        if self.initial_cash_vnd <= 0:
            raise ValueError("Initial cash must be positive")
        self.policy.validate()
        self.fees.validate()
        self.available_cash_vnd = self.initial_cash_vnd

    def release_settlements(self, now: datetime) -> None:
        matured = [item for item in self.pending_cash if item.available_at <= now]
        for item in matured:
            self.available_cash_vnd += item.amount_vnd
            self.ledger.append(
                LedgerEntry(
                    event_time=now,
                    event_type="CASH_SETTLEMENT",
                    campaign_id=item.campaign_id,
                    ticker="",
                    order_id="",
                    quantity=0,
                    execution_price_vnd=0,
                    available_cash_change_vnd=item.amount_vnd,
                    pending_cash_change_vnd=-item.amount_vnd,
                    commission_vnd=0,
                    sell_tax_vnd=0,
                    realized_pnl_vnd=0,
                )
            )
        self.pending_cash = [
            item for item in self.pending_cash if item.available_at > now
        ]

    def total_quantity(
        self, ticker: str, campaign_id: str | None = None
    ) -> int:
        return sum(
            lot.remaining_quantity
            for lot in self.lots
            if lot.ticker == ticker
            and (campaign_id is None or lot.campaign_id == campaign_id)
        )

    def settled_quantity(
        self,
        ticker: str,
        now: datetime,
        campaign_id: str | None = None,
    ) -> int:
        return sum(
            lot.remaining_quantity
            for lot in self.lots
            if lot.ticker == ticker
            and lot.tradeable_at <= now
            and (campaign_id is None or lot.campaign_id == campaign_id)
        )

    def apply_fill(self, fill: Fill) -> int:
        """Apply one fill and return its realized P&L (zero for buys)."""
        self.release_settlements(fill.event_time)
        settlement_at = self.calendar.settlement_at(
            fill.event_time.date(), self.policy
        )
        self.total_commission_vnd += fill.commission_vnd
        self.total_sell_tax_vnd += fill.sell_tax_vnd

        if fill.side is Side.BUY:
            acquisition_cash = (
                fill.gross_notional_vnd + fill.commission_vnd
            )
            if acquisition_cash > self.available_cash_vnd:
                self.total_commission_vnd -= fill.commission_vnd
                raise InsufficientCash(
                    f"Buy requires {acquisition_cash:,} VND; only "
                    f"{self.available_cash_vnd:,} VND is available"
                )
            self.available_cash_vnd -= acquisition_cash
            self.lots.append(
                PositionLot(
                    ticker=fill.ticker,
                    campaign_id=fill.campaign_id,
                    acquired_at=fill.event_time,
                    tradeable_at=settlement_at,
                    remaining_quantity=fill.quantity,
                    remaining_cost_vnd=acquisition_cash,
                )
            )
            self.ledger.append(
                LedgerEntry(
                    event_time=fill.event_time,
                    event_type="BUY_FILL",
                    campaign_id=fill.campaign_id,
                    ticker=fill.ticker,
                    order_id=fill.order_id,
                    quantity=fill.quantity,
                    execution_price_vnd=fill.execution_price_vnd,
                    available_cash_change_vnd=-acquisition_cash,
                    pending_cash_change_vnd=0,
                    commission_vnd=fill.commission_vnd,
                    sell_tax_vnd=0,
                    realized_pnl_vnd=0,
                )
            )
            return 0

        sellable = self.settled_quantity(
            fill.ticker, fill.event_time, fill.campaign_id
        )
        if fill.quantity > sellable:
            self.total_commission_vnd -= fill.commission_vnd
            self.total_sell_tax_vnd -= fill.sell_tax_vnd
            raise InsufficientSettledInventory(
                f"Sell requires {fill.quantity} settled {fill.ticker} shares; "
                f"only {sellable} are available in campaign "
                f"{fill.campaign_id!r}"
            )

        remaining_to_sell = fill.quantity
        acquisition_cost = 0
        for lot in self.lots:
            if (
                remaining_to_sell <= 0
                or lot.ticker != fill.ticker
                or lot.campaign_id != fill.campaign_id
                or lot.tradeable_at > fill.event_time
            ):
                continue
            consumed = min(remaining_to_sell, lot.remaining_quantity)
            if consumed == lot.remaining_quantity:
                consumed_cost = lot.remaining_cost_vnd
            else:
                consumed_cost = int(
                    (
                        Decimal(lot.remaining_cost_vnd)
                        * Decimal(consumed)
                        / Decimal(lot.remaining_quantity)
                    ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
                )
            lot.remaining_quantity -= consumed
            lot.remaining_cost_vnd -= consumed_cost
            remaining_to_sell -= consumed
            acquisition_cost += consumed_cost
        self.lots = [lot for lot in self.lots if lot.remaining_quantity > 0]

        net_proceeds = (
            fill.gross_notional_vnd
            - fill.commission_vnd
            - fill.sell_tax_vnd
        )
        realized = net_proceeds - acquisition_cost
        self.pending_cash.append(
            PendingCash(fill.campaign_id, settlement_at, net_proceeds)
        )
        self.realized_pnl_vnd += realized
        self.realized_pnl_by_campaign[fill.campaign_id] = (
            self.realized_pnl_by_campaign.get(fill.campaign_id, 0) + realized
        )
        self.ledger.append(
            LedgerEntry(
                event_time=fill.event_time,
                event_type="SELL_FILL",
                campaign_id=fill.campaign_id,
                ticker=fill.ticker,
                order_id=fill.order_id,
                quantity=-fill.quantity,
                execution_price_vnd=fill.execution_price_vnd,
                available_cash_change_vnd=0,
                pending_cash_change_vnd=net_proceeds,
                commission_vnd=fill.commission_vnd,
                sell_tax_vnd=fill.sell_tax_vnd,
                realized_pnl_vnd=realized,
            )
        )
        return realized

    def mark(
        self,
        now: datetime,
        liquidation_prices_vnd: Mapping[str, int],
    ) -> AccountSnapshot:
        """Mark inventory at estimated net sale value and reconcile NAV."""
        self.release_settlements(now)
        pending = sum(item.amount_vnd for item in self.pending_cash)
        inventory_value = 0
        total_by_ticker: dict[str, int] = {}
        settled_by_ticker: dict[str, int] = {}
        for lot in self.lots:
            if lot.ticker not in liquidation_prices_vnd:
                raise KeyError(f"Missing liquidation price for {lot.ticker}")
            price = liquidation_prices_vnd[lot.ticker]
            if price <= 0:
                raise ValueError("Liquidation prices must be positive")
            gross = price * lot.remaining_quantity
            commission, sell_tax = self.fees.costs(Side.SELL, gross)
            inventory_value += gross - commission - sell_tax
            total_by_ticker[lot.ticker] = (
                total_by_ticker.get(lot.ticker, 0) + lot.remaining_quantity
            )
            if lot.tradeable_at <= now:
                settled_by_ticker[lot.ticker] = (
                    settled_by_ticker.get(lot.ticker, 0)
                    + lot.remaining_quantity
                )

        equity = self.available_cash_vnd + pending + inventory_value
        total_pnl = equity - self.initial_cash_vnd
        return AccountSnapshot(
            event_time=now,
            available_cash_vnd=self.available_cash_vnd,
            pending_cash_vnd=pending,
            inventory_liquidation_value_vnd=inventory_value,
            equity_vnd=equity,
            total_pnl_vnd=total_pnl,
            realized_pnl_vnd=self.realized_pnl_vnd,
            unrealized_pnl_vnd=total_pnl - self.realized_pnl_vnd,
            total_commission_vnd=self.total_commission_vnd,
            total_sell_tax_vnd=self.total_sell_tax_vnd,
            total_quantity_by_ticker=total_by_ticker,
            settled_quantity_by_ticker=settled_by_ticker,
        )


@dataclass(frozen=True)
class BrokerEvent:
    order_id: str
    reason: str
    fill: Fill | None = None
    realized_pnl_vnd: int = 0


class BacktestBroker:
    """Small order manager joining the matching engine to one account."""

    def __init__(
        self,
        initial_cash_vnd: int,
        calendar: TradingCalendar,
        policy: ExecutionPolicy | None = None,
        fees: FeeSchedule | None = None,
    ) -> None:
        self.policy = policy or ExecutionPolicy()
        self.fees = fees or FeeSchedule()
        self.matcher = MatchingEngine(self.policy, self.fees)
        self.account = Account(
            initial_cash_vnd,
            calendar,
            self.policy,
            self.fees,
        )
        self.orders: dict[str, Order] = {}

    def submit(self, order: Order) -> None:
        order.validate(self.policy)
        if order.order_id in self.orders:
            raise ValueError(f"Duplicate order ID: {order.order_id}")
        self.orders[order.order_id] = order

    def cancel(self, order_id: str) -> None:
        order = self.orders[order_id]
        if order.status not in {
            OrderStatus.OPEN,
            OrderStatus.PARTIALLY_FILLED,
        }:
            raise PlatformError(f"Cannot cancel order in {order.status} status")
        order.status = OrderStatus.CANCELLED

    def process_snapshot(self, snapshot: MarketSnapshot) -> list[BrokerEvent]:
        """Process open orders without reusing minute volume or book depth."""
        self.account.release_settlements(snapshot.event_time)
        remaining_minute = self.matcher.snapshot_capacity(snapshot)
        remaining_ask = max(0, snapshot.best_ask_quantity or 0)
        remaining_bid = max(0, snapshot.best_bid_quantity or 0)
        events: list[BrokerEvent] = []

        active_orders: Iterable[Order] = sorted(
            (
                order
                for order in self.orders.values()
                if order.status
                in {OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED}
            ),
            key=lambda order: (order.submitted_at, order.order_id),
        )
        for order in active_orders:
            book_capacity = (
                remaining_ask if order.side is Side.BUY else remaining_bid
            )
            result = self.matcher.match(
                order,
                snapshot,
                available_minute_quantity=remaining_minute,
                available_book_quantity=book_capacity,
            )
            if result.fill is None:
                events.append(BrokerEvent(order.order_id, result.reason))
                continue

            fill = result.fill
            if fill.side is Side.BUY:
                required = fill.gross_notional_vnd + fill.commission_vnd
                if required > self.account.available_cash_vnd:
                    events.append(
                        BrokerEvent(order.order_id, "insufficient_cash")
                    )
                    continue
            else:
                sellable = self.account.settled_quantity(
                    fill.ticker, fill.event_time, fill.campaign_id
                )
                if fill.quantity > sellable:
                    events.append(
                        BrokerEvent(
                            order.order_id,
                            "insufficient_settled_inventory",
                        )
                    )
                    continue

            realized = self.account.apply_fill(fill)
            order.filled_quantity += fill.quantity
            order.status = (
                OrderStatus.FILLED
                if order.remaining_quantity == 0
                else OrderStatus.PARTIALLY_FILLED
            )
            remaining_minute -= fill.quantity
            if fill.side is Side.BUY:
                remaining_ask -= fill.quantity
            else:
                remaining_bid -= fill.quantity
            events.append(
                BrokerEvent(order.order_id, "matched", fill, realized)
            )
        return events
