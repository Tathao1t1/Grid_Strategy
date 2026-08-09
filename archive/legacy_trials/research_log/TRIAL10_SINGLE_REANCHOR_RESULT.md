# Trial 10 single-reanchor recovery-grid result

## Decision

- Status: `exploratory_not_preferred`
- Paired design: fixed-centre control versus single-reanchor recovery
- Independent validation: no
- Live authorization: no
- Final-test data used: no

No qualifying re-anchor occurred. The recovery logic correctly remained
inactive because lower-bound breaches did not subsequently demonstrate the
predeclared stabilization required to assume renewed mean reversion.

## Sample and activity

| Metric | Result |
|---|---:|
| Identical selected activations | 36 |
| Paired campaigns with a fill | 19 |
| Lower-bound breaches | 6 |
| Successful re-anchors | 0 |
| Recovery lots filled | 0 |
| Re-anchor stress cancellations | 0 |

The six breaches were MWG, FPT, TCB, HPG, VND and SSI campaigns. Every breach
progressed to the catastrophic boundary before satisfying the combination of:

- three elapsed sessions;
- three non-decreasing lows;
- two increasing closes;
- positive residual return;
- clear ticker and market downtrend checks.

Three breach campaigns had no inventory and therefore zero P&L. The filled FPT,
TCB and HPG breach campaigns lost money.

## Paired economics

Because no re-anchor was allowed, both variants were identical:

| Metric | Fixed control | Single re-anchor |
|---|---:|---:|
| Total P&L | -VND 1,434,073 | -VND 1,434,073 |
| Profit factor | 0.0498 | 0.0498 |
| Doubled-cost P&L | — | -VND 1,882,657 |
| Median campaign P&L | — | -VND 4,032 |
| Worst campaign | — | -VND 457,874 |
| Maximum inventory | — | 200 shares |

Recovery target gains were VND 98,944 while risk/time losses were
VND 1,441,833.

## Interpretation

Trial 10 answers the proposed question without moving the goalposts:

> Can the grid move lower after the price stabilizes and then wait for a
> recovery?

In these development paths, the required stabilization never appeared between
the lower-bound break and the catastrophic exit. Automatically re-anchoring
anyway would mean removing the central safety condition and assuming mean
reversion precisely when the observed evidence remained bearish.

This does not prove that a re-anchor can never work. It shows that under a
causal and risk-controlled definition, re-anchor opportunities were absent in
this sample.

## Research consequence

The honest choices are:

1. retain the stabilization rule and accept that re-anchors are rare;
2. collect substantially more untouched history;
3. use an external market/sector/fundamental anchor that can justify a new
   lower fair value;
4. define a separately numbered loose-reanchor stress test, explicitly
   acknowledging that it is an averaging-down strategy.

Loosening the stabilization rule after seeing zero re-anchors cannot validate
Trial 10. It would create a new hypothesis.

