# Sector-Rotation Grid Reimplementation Plan

## Research objective

Test whether a sector-rotation, long-only grid can outperform a pre-registered
benchmark after realistic execution costs, without allowing ticker-selection
data to leak into the trading evaluation.

This is a new research line. The July 2025 onward final holdout remains locked
while the platform, selector and optimization protocol are developed.

## Standard research sequence

### Phase 0 — Freeze the platform

Implement and test the execution/accounting platform before implementing a
new selector or grid:

- observable minute-book matching only;
- no same-snapshot signal and fill;
- configurable board lot, spread, depth and volume participation;
- configurable commission, sell tax and execution haircut;
- trading-session T+2 settlement;
- one cash and inventory ledger across all tickers;
- campaign-level realized P&L and continuous account NAV;
- no invented liquidation when the position cannot trade or settle.

The initial implementation is `grid_platform.py`.

### Phase 1 — Freeze chronological datasets

There are two different meanings of "selection data":

1. **Selector-development data** used to choose the selection formula,
   features and lookback. It must be completely separate from every trading
   backtest used to judge that formula.
2. **Point-in-time selection history** used by a frozen selector at a rotation
   date. It must end before the deployment begins. Reusing an earlier trading
   period as later historical information is causal, but it is not acceptable
   if the assessor requires literal dataset disjointness.

Use the strict interpretation for the main presentation:

```text
selector development  →  in-sample trading  →  optimization  →  OOS
no overlapping rows       no backward reuse       one final opening
```

Provisional chronological blocks, subject to a data-coverage audit:

| Purpose | Provisional dates | Permitted decisions |
|---|---|---|
| Selector development | 2022-01-04–2022-12-30 | Choose sector/ticker features and lookback |
| In-sample trading | 2023-01-03–2023-12-29 | Test the frozen economic hypothesis |
| Optimization/validation | 2024-01-02–2024-12-31 | Select grid and risk parameters |
| Internal OOS/pseudo-OOS | 2025-01-02–2025-06-30 | One frozen-code decision, but this era was examined in earlier research |
| Locked final holdout | 2025-07-14 onward | Candidate for one final test only after approval and complete freezing |

The 2025 first-half block is out of sample relative to newly frozen code, but
it is not a pristine research holdout because the researcher has already seen
evidence from that development era during earlier trials. Do not describe it
as fully independent. If the assessor requires a genuinely untouched OOS
result, either obtain new future data or obtain approval to open the locked
`final_test` once after the complete new protocol is sealed.

If rotation features must be recalculated using recent prices while preserving
literal disjointness, alternate observation-only and deployment blocks. Do
not trade a row that is also assigned to a selection window.

The split builder must publish a row-level audit with exactly one role per
date and fail if any selection/trading intersection is non-empty.

### Phase 2 — Form and pre-register the hypothesis

Proposed hypothesis:

> Sectors with high recent oscillation, sufficient after-cost amplitude and
> low directional efficiency are more suitable for a grid during the next
> fixed deployment window than the broad market or non-selected sectors.

The hypothesis must state:

- the sector universe and point-in-time membership rules;
- the selector features;
- the selection lookback;
- the rebalance/deployment horizon;
- the grid entry, spacing, levels, sizing and exit rules;
- the benchmark;
- all costs and settlement rules;
- the primary pass/fail statistic.

### Phase 3 — Justify the selector horizon

Do not keep the previous 10-session window merely because it was used before.
Treat horizon as a research parameter supported by an economic claim:

- 10 sessions: very responsive but noisy;
- 20 sessions: approximately one trading month;
- 40 sessions: more stable but slower to recognize regime changes;
- 60 sessions: approximately one quarter and may lag turning points.

Compare a small pre-registered set on selector-development data only. Evaluate
regime persistence, next-period grid-crossing opportunity, turnover and
stability. Choose one horizon before opening the trading in-sample block.

### Phase 4 — Define sector rotation

At every rotation:

1. score sectors using selection-only history available before deployment;
2. choose the top sector subject to liquidity and severe-downtrend vetoes;
3. choose one or more liquid representatives using a frozen rule;
4. freeze the selection for the deployment window;
5. route every grid order through `grid_platform.py`;
6. close and settle before the next deployment, or explicitly carry and mark
   inventory under a pre-registered rule.

Sector selection and ticker selection must be evaluated separately so that a
good result cannot be ambiguously attributed to either layer.

### Phase 5 — Capital and grid-capacity study

Capital must be a platform input, not a hard-coded trial identity. Increasing
capital does not itself improve percentage expectancy; it only permits more
board lots and grid levels. It can also increase market impact.

Before optimization, pre-register a capital/capacity study such as:

```text
VND 100m, VND 500m, VND 1bn
```

For each capital level report:

- number of affordable grid cells;
- maximum inventory and cash utilization;
- order size as a fraction of displayed depth and minute volume;
- net return, VND P&L and maximum drawdown;
- whether performance scales proportionally after costs.

Choose the smallest capital that can express the intended grid. Do not select
capital solely because it creates the largest historical VND profit.

### Phase 6 — Benchmark and account attribution

Use at least two frozen comparisons:

1. **Cash benchmark:** whether the strategy produced positive absolute
   after-cost return.
2. **Relevant passive benchmark:** buy-and-hold of the broad index proxy or
   a frozen sector proxy over exactly the same deployable capital and dates.

Optional diagnostic benchmarks:

- equal-weight buy-and-hold of the eligible stock universe;
- selected stocks held without a grid;
- the same grid without sector rotation.

All variants must share one account definition:

```text
NAV = available cash
    + pending sale cash
    + estimated net liquidation value of all inventory
```

Report separately:

- gross grid capture;
- realized grid losses;
- forced/time-exit losses;
- commission;
- sell tax;
- execution friction;
- unrealized inventory P&L;
- total account P&L;
- benchmark P&L and active return.

The components must reconcile exactly to the account result.

### Phase 7 — In-sample backtest

Run the frozen hypothesis on the in-sample trading block. The goal is not to
maximize profit but to verify:

- sufficient executions and rotations;
- economically correct P&L attribution;
- stable behavior across sectors and subperiods;
- no dependence on one ticker or one exit;
- positive gross edge large enough to plausibly cover costs.

If gross expectancy is negative, stop before optimization.

### Phase 8 — Optimization

Optimize only a compact, pre-registered parameter set, for example:

- deployment horizon;
- ATR grid spacing;
- number of grid levels;
- capital allocation per level;
- severe-downtrend veto;
- maximum inventory and time exit.

Use time-series validation inside the optimization block. Select parameters
by robust median performance and stability, not the single highest return.
Include doubled-cost and delayed-fill stress tests.

### Phase 9 — One out-of-sample test

Freeze code, parameters, hashes and pass/fail thresholds before loading OOS
prices. Open the OOS block once and report the complete result, including a
failure or an inconclusive sample.

Primary decision criteria should include:

- positive total account return after costs;
- positive active return versus the frozen benchmark;
- acceptable maximum drawdown;
- profit factor above one;
- adequate rotations and completed cycles;
- no single ticker or period explaining most of the profit.

## Immediate implementation order

1. Review and freeze `grid_platform.py` assumptions.
2. Complete its invariant and edge-case tests.
3. Build the disjoint split manifest and overlap audit.
4. Define sector membership and benchmark instruments.
5. Pre-register the selector-horizon experiment.
6. Implement sector selection without any grid logic.
7. Implement grid orders as a client of the frozen platform.
8. Run in-sample, then optimization, then one OOS test.
