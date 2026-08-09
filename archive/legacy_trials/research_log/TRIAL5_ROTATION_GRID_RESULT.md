# Trial 5 authoritative development result

## Decision

- Trial: `TRIAL5-HSX-ROTATION-LONG-GRID`
- Run: `trial5_e1f38d5856`
- Date: 2026-07-24
- Scope: development walk-forward only
- Status: `inconclusive_sample`
- Advance to final confirmation: **no**
- Final-test data used: **no**

Trial 5 v1 did not satisfy its preregistered sample gates and its observed
economics were unfavorable. It must not be used live or repaired in place.
Any changed selector, entry, risk rule, parameter, or data treatment is a
separately preregistered Trial 6.

## Sample result

| Measure | Observed | Required | Passed |
|---|---:|---:|:---:|
| Valid two-month rotations | 14 / 15 | 15 | No |
| Active rotations | 6 / 15 | at least 10 | No |
| Completed grid-target campaigns | 4 | at least 30 | No |

Fold `wf_09` was invalid because the unadjusted source showed reference resets
in both selected tickers:

- TCB: 2024-05-21 and 2024-06-20
- HPG: 2024-05-23

The simulator correctly refused to treat those discontinuities as ordinary
tradable price movement.

## Economic diagnostics

Economic gates are descriptive because the sample gates already failed.

| Measure | Observed | Frozen requirement |
|---|---:|---:|
| Compounded net return | -1.4080% | positive |
| Annualized Sharpe from two-month folds | -0.9745 | at least 0.50 |
| Profitable valid rotations | 14.29% | at least 60% |
| Median rotation return | 0.00% | positive |
| Worst valid rotation | -0.7651% | no worse than -8% |
| Stitched maximum drawdown | -1.7490% | no worse than -5% |
| Realized-trade profit factor | 0.2876 | at least 1.20 |
| Doubled-cost compounded return | -1.5844% | positive |
| Doubled-cost profit factor | 0.2340 | at least 1.00 |
| Diagnostic benchmark compounded return | +1.5931% | not a gate |

The low portfolio drawdown does not rescue the hypothesis. Exposure was small
and average capital utilization was only 0.955%, so the strategy lost money
while taking little opportunity.

## Execution and payoff diagnosis

Across valid primary folds:

- gross two-way turnover: VND 119,270,000;
- modeled commission, tax, and execution friction: VND 372,957;
- maximum cost in one rotation: 0.1810% of starting NAV;
- modeled cost divided by positive pre-cost campaign profit: 50.74%;
- target-exit gains: VND 568,359 across four exits;
- forced/scheduled-exit losses: VND 1,976,316 across five exits;
- forced-loss / target-gain ratio: 3.48;
- settlement-locked risk-exit loss: VND 0.

The average target gain was about VND 142,090, while the average breakdown
loss was about VND 395,263. The observed target-hit rate was 4/9, or 44.4%.
With that payoff shape, the strategy needed a much higher target-hit rate to
break even.

The most severe example was HPG in `wf_14`: the campaign entered at VND
27,500, but a gap through the hard-lower area forced execution near VND
23,800, producing a realized campaign loss of about 13.8%. A prior-close stop
cannot guarantee its threshold price in a discontinuous market.

No observed realized loss was tagged to a risk trigger occurring while shares
were settlement-locked. This is not proof that T+2-afternoon risk is harmless;
it only means it was not the cause of this run's recorded forced losses.

## Why activity was too sparse

Five rotations selected no ticker. Three additional rotations selected
tickers but never obtained an entry:

| Fold | Ticker(s) | Armed sessions | Qualifying quote touches |
|---|---|---:|---:|
| `wf_03` | VPB | 7 | 0 |
| `wf_04` | PNJ | 35 | 0 |
| `wf_07` | SSI / MBB | 32 / 33 | 0 / 0 |

The fixed buy level sat below the market throughout those armed periods.
Therefore the system combined a strict historical selector with a static
pullback level that frequently never traded. When the level did trade, it
often identified continued weakness rather than a completed reversal.

The most frequent historical eligibility failures across the 150 fold/ticker
rows were:

1. excessive deep-downtrend history: 58;
2. one board lot exceeding the frozen stress budget: 37;
3. recent deep-downtrend veto: 37;
4. latest-regime veto: 36;
5. ATR above the maximum grid step: 34;
6. excessive total downtrend history: 26.

These counts are diagnostics, not permission to loosen thresholds after seeing
the result.

## Market-regime and settlement diagnostics

Two valid rotations were classified as broad-market downtrends. Their combined
strategy return was -0.7651%; one stayed fully in cash and the other lost
0.7651%. The portfolio-level 5% high-water kill never fired.

The zero settlement-locked loss, low utilization, and absence of a portfolio
kill show that Trial 5's hardened accounting and risk machinery worked as
designed. The entry/payoff hypothesis, not the ledger, failed to produce an
adequate sample or positive economics.

## Research conclusion

Trial 5 successfully implemented the intended process:

```text
point-in-time selection -> two-month deployment -> exit/settle -> reselection
```

But Trial 5 v1 does not support the claim that this selector plus a static
one-cell pullback grid has a tradable edge. The evidence points to three
problems:

1. the selector and entry combination is too inactive;
2. first-touch entries confuse mean-reverting pullbacks with breakdowns; and
3. small repeated targets are dominated by occasional gap losses and costs.

Before a Trial 6, corporate-action-adjusted daily data should be made
available. A new hypothesis should be preregistered rather than tuned in
place—most plausibly a causal reversal-confirmation entry, a prior-day
market-downtrend veto, and an explicit gap-risk treatment. Trial 5's locked
result remains the baseline.

## Reproduction and integrity

Command:

```bash
python3 study_trial5_rotation_grid.py --development-walk-forward
```

Authoritative output:

```text
data/trial5_rotation_grid/trial5_e1f38d5856
```

Key integrity values:

```text
result fingerprint
19923d4afb0b134796896eab250a006f52f1a9b54e0d07840a89440e5078f71c

manifest SHA-256
2b7239b155b20d3c13547e6c3fd7bd2ceaa8f2c6be7d97a2a3689c5d331a872e

gate_report.json SHA-256
141ffc5bee890af35cd2a24effc4f127fc0092ed0b1b28aa4e8534815af8bba6
```

A second execution reproduced the same locked result and validated every
published artifact hash.
