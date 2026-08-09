# Trial 10 exploratory protocol: single-reanchor recovery grid

## Research purpose

Trial 10 tests whether one controlled downward re-anchor improves the same
grid campaigns relative to a fixed-centre control.

This is an exploratory study on previously used development folds. It is not
independent confirmation, does not authorize live trading and does not read
numeric final-test prices.

## Paired design

Every selected activation is simulated twice:

1. `fixed_control`: original grid remains fixed until target, risk or time exit.
2. `single_reanchor`: a lower-bound breach pauses buys and may permit one
   recovery re-anchor after stabilization.

Campaign selection is frozen before either future path is evaluated. Each
selected activation reserves its portfolio slot for the full 20-session
horizon, ensuring both variants use identical signals.

## Activation and initial grid

The ten-stock universe and signal remain:

- residual z5 <= -0.50;
- residual return 1 > 0 OR close > previous close;
- market-proxy return 5 > -5%;
- ticker 10-session return > -8%;
- liquidity, ATR and reference history valid.

At T:

```text
C0 = SMA20
L0 = C0 - 2 ATR20
U0 = C0 + 2 ATR20
H0 = L0 - 0.75 ATR20
```

Six geometric intervals span L0 to U0. The two levels immediately below C0
are 100-share entry levels. A level requires a completed touch/reclaim and
then buys at the next open. Shares settle on T+2. Each lot initially targets
its next higher grid level.

Initial inventory is capped at 200 shares.

## Lower-bound break and pause

When a completed session closes below L0:

- cancel every unfilled initial buy;
- enter `RECOVERY_WAIT`;
- place no new buys;
- preserve existing sell targets;
- preserve all original purchases and P&L.

An opening gap or intraday low through H0 still triggers catastrophic
liquidation as settlement permits.

## Stabilization and single re-anchor

A re-anchor becomes eligible only after the lower-bound break when:

- at least three completed sessions have elapsed since the breach;
- the latest three lows are non-decreasing;
- the latest two closes are increasing;
- latest residual return is positive;
- ticker 10-session return is above -8%;
- market-proxy five-session return is above -5%;
- the proposed new centre is below C0.

Using information through T-1:

```text
C1 = SMA5
L1 = C1 - 2 ATR20
U1 = C1 + 2 ATR20
H1 = L1 - 0.75 ATR20
```

The recovery grid is frozen. Existing unsold lots receive inventory-reducing
targets at C1 and the first geometric level above C1. Targets may move lower,
but total campaign accounting never resets.

At most one additional 100-share recovery lot may buy at the first level below
C1 using touch/reclaim confirmation. Total inventory may never exceed
300 shares.

Before the recovery buy, liquidation of all inventory at H1 must fit within
1.5% of VND 100 million. The incremental recovery lot itself may add no more
than 0.5% of NAV stress. Otherwise it is cancelled.

Only one re-anchor is allowed. A second lower-bound failure cannot reset the
grid again.

## Deep-downtrend handling

During `RECOVERY_WAIT`, no re-anchor is allowed while any condition holds:

- ticker 10-session return <= -8%;
- market-proxy five-session return <= -5%;
- residual z5 <= -2 with negative latest residual return.

Existing settled inventory may still sell at its frozen upper levels.
Catastrophic H0 remains active until re-anchor. After re-anchor, H1 is active;
the stress test, not repeated resetting, limits the additional downside.

## Time, execution and costs

- Maximum campaign length: 20 observed sessions
- 100-share board lots
- T+2 share settlement
- adverse opening-gap liquidation
- conservative adverse-event-first daily path ordering
- 0.15% commission per side
- 0.10% sell tax
- 0.05% execution haircut per side
- doubled-cost diagnostic

All remaining shares exit at the T+20 close.

## Paired evaluation

At least 20 paired campaigns are required for an exploratory comparison.
Report:

- total and median P&L for both variants;
- paired P&L improvement;
- number and success of re-anchors;
- profit factor and doubled-cost P&L;
- target gains versus risk/time losses;
- worst campaign and maximum inventory;
- P&L after removing the best campaign;
- fraction of campaigns improved by re-anchoring.

The recovery design is `exploratory_preferred` only if:

- it improves aggregate P&L versus control;
- its own P&L and median P&L are positive;
- profit factor >= 1.20;
- doubled-cost P&L is positive;
- target gains cover other losses;
- P&L remains positive after removing the best campaign;
- worst campaign is no worse than -1.5% of NAV.

