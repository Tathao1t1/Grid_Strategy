# Trial 17 result: fair-value reversal grid

## Decision

No Trial 17 variant passed the in-sample gates. Internal validation and the
locked final minute holdout remain unopened.

The redesign increased the selected sample and produced genuine grid cycles,
but the fair-value anchor and reclaim confirmation did not create positive
expectancy. The severe-downtrend veto materially reduced losses; it did not
reduce them enough for target-cycle gains to cover inventory losses.

Trial 17 is exploratory because its design followed observation of Trial 16.

## Frozen ablation

| Variant | Campaigns | Target campaigns | Net P&L | PF | Doubled-cost P&L |
|---|---:|---:|---:|---:|---:|
| Anchor + touch, one level | 61 | 18 | −VND 2,514,716 | 0.386 | −VND 3,208,795 |
| Anchor + reclaim, one level | 58 | 25 | −VND 2,529,894 | 0.359 | −VND 3,194,135 |
| Anchor + reclaim + veto, one level | 44 | 18 | −VND 1,501,888 | 0.390 | −VND 2,043,565 |
| Anchor + reclaim + veto, two levels | 48 | 24 | **−VND 1,479,791** | **0.492** | **−VND 2,158,550** |

No row was eligible. The two-level row is reported as the least-negative
diagnostic, not as a selected strategy.

## Least-negative diagnostic

| Metric | Result |
|---|---:|
| Campaigns | 48 |
| Target-completing campaigns | 24 |
| Median campaign P&L | −VND 17,386 |
| Net P&L | **−VND 1,479,791** |
| Profit factor | **0.492** |
| Target-cycle gains | +VND 1,291,084 |
| Forced/time losses | **−VND 3,227,432** |
| Grid-economic P&L | **−VND 1,936,348** |
| Doubled-cost P&L | **−VND 2,158,550** |
| P&L after best campaign removed | **−VND 1,788,547** |
| Annualized two-month-fold Sharpe | **−1.532** |
| Realized closed-campaign maximum drawdown | **VND 1,503,711 / 1.504%** |
| Worst campaign | −VND 204,365 |
| Positive active-fold fraction | 25% |
| Opportunity-score target-rate quintile spread | +3.70 percentage points |

The maximum drawdown is based on campaign-closure equity, not a
minute-marked portfolio curve.

## Ablation interpretation

### Fair-value reclaim

Reclaim confirmation increased target-completing campaigns from 18 to 25,
but it did not improve economics:

```text
touch-only P&L  = -VND 2,514,716
reclaim P&L     = -VND 2,529,894
```

The confirmation entered after price had rebounded above the passive grid
level. That improved target frequency but reduced the remaining distance to
the target after fees, spread and adverse execution.

### Severe-downtrend veto

Adding the veto improved nominal P&L by VND 1,028,006 relative to the
one-level reclaim variant and reduced forced/time losses by 39.2% relative to
the touch-only baseline. This is the only economically material improvement
in the ablation.

It still left VND 2,518,807 of forced/time losses against only VND 960,705 of
target-cycle gains in the one-level veto variant.

### Second grid level

The second level added four campaigns and six target-completing campaigns,
raising target gains to VND 1,291,084. It also increased forced/time losses to
VND 3,227,432. Net P&L improved by only VND 22,097, while doubled-cost P&L
worsened by VND 114,985.

The second level therefore added activity rather than robust edge.

## Ticker concentration

In the least-negative variant:

| Ticker | Campaigns | Target campaigns | Net P&L |
|---|---:|---:|---:|
| VPB | 8 | 4 | −VND 525,479 |
| VND | 4 | 0 | −VND 428,055 |
| SSI | 2 | 0 | −VND 402,103 |
| VCB | 8 | 3 | −VND 375,995 |
| HPG | 7 | 5 | −VND 70,546 |
| MWG | 7 | 3 | −VND 40,771 |
| MBB | 5 | 4 | +VND 31,527 |
| TCB | 7 | 5 | +VND 331,631 |

The problem was not one isolated ticker. Six of eight tickers lost money, and
the two securities tickers completed no target campaign.

## Hypothesis verdict

The preregistered primary target was at least a 50% reduction in forced/time
losses while retaining positive cycle gains. The least-negative variant
reduced those losses by only 22.1%; the strongest loss reduction was 39.2% in
the one-level veto variant. The hypothesis therefore failed.

The positive opportunity-score quintile spread shows weak directional
ordering, but a useful ranking relationship is not sufficient when the
underlying after-cost payoff remains negative.

## Governance

- In-sample eligible variants: **0 / 4**
- Internal validation: **not run**
- Final minute OOS: **not opened**
- Final lock: **not created**
- Live deployment: **not authorized**

