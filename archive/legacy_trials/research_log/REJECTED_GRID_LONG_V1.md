# Rejected strategy record: GRID-LONG-V1

## Decision

- **Status:** permanently rejected; implementation deleted
- **Decision date:** 2026-07-23
- **Market:** HOSE equities
- **Tickers:** VCB and VPB
- **Research scope:** training data only
- **OOS/final holdout inspected:** no
- **Deleted implementation SHA-256:** `29d7c2782def1c0cee830b3ecedef6cbff5fc97328e255dd6c18a8cbc2b6dc80`

This record is intentionally retained so that a future implementation does not
repeat the same payoff structure under a different set of parameter names.

## Hypothesis that was rejected

A long-only geometric grid could earn repeated oscillation profits in VCB and
VPB while regime pauses, forced exits, cash reserves, and settlement-aware
inventory controls contained losses during downtrends.

### Frozen version-1 rules

- Previous official close as the weekly anchor
- Bounds at anchor plus/minus 2 × ATR(14)
- Eight geometric grid intervals
- ER(10) regime threshold of 0.35
- Deep-downtrend trigger: ten-session return at or below −8%
- Additional exit after two consecutive closes below the grid
- Per-ticker hard drawdown stop at −8%
- Equal capital between VCB and VPB
- 30% base inventory, 50% lower-grid buying, 20% cash reserve
- Maximum invested ratio of 80%
- Board lot of 100 shares
- Uniform T+2.5 stock availability in the principal experiment
- Sale cash unavailable until settlement
- Commission, sell tax, slippage, and minute-volume participation included

## Unchanged training-fold evidence

Each completed fold used the same rules. These are rolling twelve-month
training windows starting two months apart, so adjacent folds overlap by about
ten months and are not independent experiments.

| Fold | Net return | Sharpe | MDD | Profit factor | Cost drag | Time in market |
|---|---:|---:|---:|---:|---:|---:|
| wf_01 | −7.09% | −1.375 | −8.91% | 0.316 | 2.13% | 49.00% |
| wf_02 | −7.87% | −1.564 | −9.33% | 0.270 | 2.00% | 49.20% |
| wf_03 | −3.42% | −0.814 | −6.59% | 0.602 | 2.28% | 64.00% |
| wf_04 | −1.49% | −0.319 | −5.30% | 0.861 | 2.99% | 71.60% |
| wf_05 | −2.30% | −0.500 | −3.28% | 0.753 | 3.10% | 73.20% |
| wf_06 | −2.35% | −0.455 | −6.69% | 0.802 | 3.33% | 80.40% |
| wf_07 | −5.50% | −0.946 | −6.89% | 0.491 | 3.21% | 86.35% |
| wf_08 | −6.82% | −1.555 | −8.29% | 0.368 | 2.88% | 72.11% |
| wf_09 | −7.24% | −1.717 | −8.31% | 0.285 | 2.42% | 56.45% |
| wf_10 | blocked | blocked | blocked | blocked | blocked | blocked |
| wf_11 | −3.50% | −0.695 | −5.92% | 0.582 | 3.36% | 86.35% |
| wf_12 | −1.79% | −0.407 | −4.79% | 0.690 | 3.17% | 86.40% |
| wf_13 | −0.68% | −0.125 | −2.75% | 1.379 | 2.92% | 91.60% |
| wf_14 | +0.72% | +0.186 | −3.43% | 2.957 | 2.32% | 91.16% |
| wf_15 | −6.59% | −1.013 | −8.67% | 0.283 | 2.21% | 86.80% |

`wf_10` was correctly blocked by the corporate-action safety rule: VCB had an
unexplained reference-price reset on 2023-07-25 while 1,200 shares were held.
No result was inferred or included for that fold.

### Aggregate rejection evidence

- 14 folds completed safely.
- 13 of 14 completed folds lost money.
- 13 of 14 had a negative Sharpe ratio.
- 12 of 14 had profit factor below 1.
- Only `wf_14` was profitable, at just +0.72% with Sharpe 0.186.
- Annual transaction-cost drag was approximately 2.0%–3.4%.
- Multiple folds triggered permanent hard stops.

The overlap prevents treating these as fourteen independent observations, but
the repeated failure under changing start dates is sufficient to reject the
version-1 hypothesis.

## Clearest failure anatomy: wf_01

- Initial capital: VND 1,000,000,000
- Ending equity: VND 929,100,010.5
- Net P&L: **−VND 70,899,989.5**
- Normal grid-sell P&L: **+VND 30,498,838.5**
- Risk-exit P&L: **−VND 101,398,828.0**
- Transaction costs: **VND 21,264,989.5**
- Gross turnover: **9.677× initial capital**
- Winning-sell ratio: **70.90%**
- Maximum drawdown: **−8.91%**
- Drawdown peak/trough: 2022-04-06 / 2022-10-03
- Drawdown recovered by fold end: no
- VPB hard stop armed: 2022-05-09
- VCB hard stop armed: 2022-09-30

The high winning percentage concealed a strongly asymmetric payoff: many small
grid profits were overwhelmed by a smaller number of inventory liquidations.

## Mistake pattern to recognize in future

1. **Averaging down created negative convexity.** Exposure increased as price
   fell, so the strategy held the most inventory near the worst part of a
   persistent decline.
2. **Risk protection acted after inventory had accumulated.** The exit rules
   reduced further exposure but crystallized losses much larger than completed
   grid-cycle profits.
3. **T+2.5 made inventory risk path-dependent.** Recently purchased shares
   could not be sold during the period in which protection was most needed.
4. **The base inventory introduced permanent directional beta.** This weakened
   the claim that the strategy was mainly harvesting oscillation.
5. **Turnover transferred too much edge to friction.** Annual cost drag of
   roughly 2%–3.4% was too large relative to the available grid edge.
6. **Win rate was the wrong headline metric.** A 70.9% winning-sell rate
   coexisted with a 0.316 profit factor and a material capital loss.
7. **A good isolated window was not representative.** The single small positive
   fold did not compensate for consistent failure across the other windows.

## Mandatory gates for the next strategy

These gates must be specified before examining OOS results:

1. Draw the payoff diagram and quantify maximum inventory loss versus the net
   profit from one completed trading cycle.
2. Run a settlement stress case where every recent purchase remains
   untradeable throughout a sharp multi-session decline.
3. Set a transaction-cost and turnover budget before selecting grid spacing.
4. Require regime control to prevent inventory accumulation, rather than only
   triggering liquidation after the decline.
5. Report profit factor, risk-exit P&L, cost drag, and maximum drawdown alongside
   win rate.
6. Apply one unchanged specification across all training windows.
7. Require a positive median training return and Sharpe, median profit factor
   above 1, and no repeated breach of the predeclared drawdown limit.
8. Repeat the cost test with materially worse commission/slippage assumptions.
9. Treat every parameter revision as another research trial and record it.
10. Open OOS/final-holdout data only after the frozen training gates pass.

Changing only ATR length, grid count, bounds, or stop thresholds does not
constitute a new hypothesis. A successor must materially change how and when
inventory is acquired, or abandon the long-grid structure.

## Assets deliberately retained

- Original daily and minute market data
- Data extraction/backfill pipeline
- Ticker-selection work
- Walk-forward split definitions
- This rejected-strategy record

The simulator, guide, tests, generated trades, daily states, portfolio output,
metrics, manifest, and compiled caches were permanently deleted.
