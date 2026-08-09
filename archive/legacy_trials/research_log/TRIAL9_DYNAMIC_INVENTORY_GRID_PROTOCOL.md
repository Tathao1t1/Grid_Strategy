# Trial 9 exploratory protocol: dynamic-bound inventory-aware grid

## Purpose and research status

Trial 9 implements the supplied grid-design slides:

- dynamic upper and lower bounds;
- a geometric percentage grid;
- an additional buffer outside the trading range;
- increasing intended quantities toward the lower extreme;
- inventory-aware order reduction;
- explicit recognition that deep declines may not mean-revert.

The development data have informed Trials 1–8. Trial 9 is therefore an
exploratory engineering and sensitivity study, not independent validation.
The final-test period remains locked.

## Universe and folds

The fixed ten-stock universe and 15 non-overlapping deployment folds remain:

```text
FPT HPG MBB MWG PNJ SSI TCB VCB VND VPB
```

Signals use data through T-1. A campaign path must remain inside its
two-month deployment fold.

## Dynamic range

While flat, every candidate session calculates:

```text
C = SMA20
L = C - 2 × ATR20
U = C + 2 × ATR20
H = L - 0.75 × ATR20
```

The centre and bounds are frozen when the campaign activates. They do not move
downward with an open position.

Six geometric intervals span L to U:

```text
r = (U / L) ** (1 / 6) - 1
G[j] = L × (1 + r) ** j, j = 0..6
```

The three levels immediately below C are long entry levels. Each lot targets
the next higher grid level. All prices use modeled HSX tick rounding.

## Activation

The broad activation is:

- residual z5 <= -0.50;
- residual return 1 > 0 OR close > previous close;
- market-proxy return 5 > -5%;
- ticker 10-session return > -8%;
- Trial 6 liquidity, ATR and reference-integrity checks pass.

This gate deliberately favors sample generation. The deep-downtrend system,
not additional stacked entry indicators, controls tail exposure.

## Distance and inventory-aware quantities

Intended quantity in board lots increases toward the lower extreme:

```text
base lots by distance from centre = ceil(1.5 ** i)
                                     = 1, 2, 3 lots
base shares                         = 100, 200, 300
```

Before a buy:

```text
I = current shares / 600
adjusted quantity = nearest board lot of base quantity × (1 - 0.5 × I)
```

The adjusted order is reduced further, in 100-share increments, until the
combined liquidation loss at H is no greater than 1.5% of a VND 100 million
portfolio. A zero result cancels the order.

Thus the system intends to buy more at greater deviations but never treats
the geometric quantity formula as permission to exceed its inventory or
stress budget.

## Fill and settlement rules

For each level:

1. a completed daily low touches the level;
2. that session closes above the level and above its open;
3. the level buys at the following open only if the open is no higher than
   the level's sell target and no shutdown is active.

Each level buys once. Purchased shares become sellable on the second following
observed session. A settled lot sells when the daily high reaches its next
upper grid level. Target touches before settlement do not create a sale.

Costs remain 0.15% commission per side, 0.10% sell tax and 0.05% adverse
execution per side. A doubled-cost diagnostic is retained.

## Deep-downtrend and reversion-failure shutdown

Using information available before each new session, cancel every unfilled buy
and enter shutdown when any condition holds:

- ticker 10-session return <= -8%;
- market-proxy five-session return <= -5%;
- residual z5 <= -2 and latest residual return < 0;
- previous close is below H.

An intraday low or opening gap through H also triggers shutdown. Settled
inventory exits at H or the adverse gap open. Locked inventory exits at the
first open on or after settlement. No new centre is calculated until flat.

Every campaign expires after 15 sessions.

## Portfolio episode selection

- At most three simultaneous campaigns
- At most one active ticker per sector
- Five-session ticker cooldown
- Rank by most negative residual z5, then strongest residual rebound

## Exploratory screen

The report requires at least 30 executed campaigns for an exploratory economic
assessment. A candidate configuration is interesting only if:

- net and median campaign P&L are positive;
- campaign profit factor >= 1.20;
- doubled-cost P&L is positive;
- P&L remains positive after removing the best campaign;
- target gains cover risk/time losses;
- maximum campaign loss is no worse than 1.5% of VND 100 million;
- increasing-distance levels are profitable in aggregate.

Passing would justify prospective paper trading only.

