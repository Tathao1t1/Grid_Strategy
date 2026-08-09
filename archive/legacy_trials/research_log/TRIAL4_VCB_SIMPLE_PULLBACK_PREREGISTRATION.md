# Pre-registration: TRIAL4-VCB-SIMPLE-PULLBACK

## Research state

- Pre-registration date: 2026-07-23
- Status: frozen before any Trial 4 outcome is calculated
- Scope: VCB development/in-sample data only
- Trial 4 walk-forward OOS inspected: no
- Final holdout inspected: no
- Primary horizon: T+5
- Diagnostic horizon: T+3
- Research lot: 100 shares

Trial 4 is an exploratory development screen, not an independent confirmation.
It was designed after Trial 3 revealed that its signal was too rare on the
same development data. Trial 3 outcome values must not be used to choose Trial
4's horizon or acceptance thresholds. A Trial 4 development pass would permit
pre-registration of an untouched confirmation test; it would not authorize
live trading.

## Sealed authoritative inputs

Trial 4 v1 has one authoritative pooled development run. The production CLI
does not expose a single-fold outcome mode and refuses inputs whose contents
do not match these seals:

```text
daily split SHA-256
5fa014c90c729902c1eb9f9fc981aa4004dfb0ec58cc1bbea36c527d0c1f28ca

walk-forward assignment SHA-256
ecf89e6ec8b95d0ad1cc1d09c6b6a1c0b5a35e43531686fd1bc4d82fde8c135f

split-audit SHA-256
052aecc2c9e3a50525f3efaf396aba651532807606ed62fcc077489b760cf4d6

frozen Config SHA-256
52db3509e5711ff16867df3c3d99e1984236c5b5b3b325c25e48f2036b6ad1b8

production study source SHA-256
12345b2c02508384096227614d03182ef956dd7741df589c6974880a3aa9e276
```

The assignment must contain exactly `wf_01` through `wf_15`. A different path
is acceptable only when file contents match the sealed hash. Hashing the raw
daily file verifies its identity; final-test numeric fields are still skipped
before parsing and never enter features, labels or decisions.

The first successful pooled publication creates a decision lock containing
its run ID and result fingerprint. A later code, configuration or data variant
cannot silently replace the authoritative Trial 4 v1 result.

## Hypothesis

> While VCB remains above its long-term average, a moderate five-session
> pullback followed by one positive close predicts a cost-adjusted rebound
> over the next five trading sessions.

This is a minimal-signal falsification test. Removing Trial 3 filters should
increase opportunity count, but it may also admit weaker reversals and
high-volatility falling knives.

## Frozen T-1 signal

For a hypothetical entry on trading session `T`, calculate every condition
using data ending at `S = T-1`:

```text
close[S] > SMA50[S]

-6.0% <= close[S] / close[S-5] - 1 <= -0.5%

close[S] > close[S-1]
```

`SMA50[S]` contains the close on S and the preceding 49 VCB observations.
The pullback boundaries are inclusive; the two comparison conditions are
strict.

There are exactly three economic predicates. Trial 4 does not use:

- SMA20;
- a 10-session-return condition;
- ATR or another volatility filter;
- close location or candle shape;
- volume, spread or order-book data;
- a day-T opening-gap filter.

The opening gap is recorded as a diagnostic only. A zero-range signal bar is
allowed because candle location is not part of this hypothesis.

## Warm-up and corporate-action integrity

Each fold requires 51 consecutive in-sample VCB observations before a signal:

1. The earliest observation supplies the prior close needed to verify the
   next observation's implied reference.
2. The final 50 observations supply the SMA50 and complete feature/reset
   window.

Within the 50-observation feature window:

- any inferred reference reset invalidates the signal;
- missing ceiling/floor metadata or otherwise unverifiable reset status
  invalidates the signal.

From T through T+5:

- any inferred reset quarantines the label from all aggregates;
- any unverifiable reset status quarantines the label.

Forward quarantine is data-label protection, not an entry condition and not a
live-trading rule. Authoritative adjustment factors would be preferable to the
current greater-than-2% implied-reference reset heuristic.

## Entry, labels and costs

- T is the next observed VCB trading session after S.
- Research entry reference: official open on T.
- T+3 diagnostic exit reference: official close on T+3.
- T+5 primary exit reference: official close on T+5.
- T+5 must remain inside the same fold's in-sample calendar; otherwise the
  entire candidate is purged.
- Opening/closing auction references are labels, not guaranteed fills.

Exact modeled costs:

```text
buy commission       0.15%
sell commission      0.15%
sell tax             0.10%
slippage each side   0.05%
```

The doubled-cost diagnostic doubles commission and slippage but not sell tax.
Profit factor uses exact VND P&L for one 100-share lot:

```text
profit factor =
    sum positive exact VND P&L
    / absolute sum negative exact VND P&L
```

For each horizon:

```text
net return =
    exact net sale cash / exact acquisition cash - 1

MFE =
    maximum high from T through T+h / open[T] - 1

MAE =
    minimum low from T through T+h / open[T] - 1
```

`locked_MAE` is the minimum low from T through T+2 relative to open[T]. It is
a conservative settlement-period path-risk diagnostic.

The study records which +1.5% favorable or -3% adverse barrier is observed
first through T+5. If both occur in the same daily bar before either was
previously observed, the outcome is `both_hit_same_bar`; ordering is not
invented.

## Leakage, deduplication and independence

- Numeric prices are parsed only for VCB development dates selected as
  in-sample for the requested scope.
- OOS assignment metadata may be checked for role conflicts, but OOS prices
  and outcomes are not parsed.
- Final-test rows are skipped before numeric price parsing.
- Indicators use only contiguous rows from the current fold.
- Every feature timestamp is strictly earlier than its entry timestamp.
- T+3 and T+5 remain inside the same in-sample fold.
- Future returns, excursions and barriers never alter signal eligibility.

Overlapping 12-month folds can produce the same entry repeatedly. The pooled
sample:

1. deduplicates by entry date;
2. requires every independently computed non-fold field to agree;
3. sorts unique candidates chronologically;
4. accepts the earliest event;
5. suppresses later entries through that event's T+5 inclusive;
6. permits the next entry from T+6 onward.

Only these T+5-non-overlapping primary events drive the decision. Fold rows
and fold summaries are diagnostics, not independent experiments.

## Frozen frequency definitions and gates

A standard two-month block is Jan-Feb, Mar-Apr, May-Jun, Jul-Aug, Sep-Oct or
Nov-Dec. It is evaluable when at least 30 possible entry sessions are covered
by the union of selected fold calendars after the 51-observation warm-up and
before the fold's T+5 boundary. Corporate-action failures can prevent actual
signals but do not remove an otherwise covered session from the denominator.

Trial 4 sample/frequency gates:

1. At least 40 unique, verified, T+5-non-overlapping primary events.
2. At least three entry calendar years contain at least eight primary events.
3. No single entry year contributes more than 50% of primary events.
4. At least 12 evaluable two-month blocks exist.
5. At least 60% of evaluable two-month blocks contain a primary event.

Inter-event trading-session gaps are reported but are not additional gates.

## Frozen economic and risk gates

With adequate sample and frequency, Trial 4 advances only if every gate passes:

1. T+5 mean net return is at least +0.50%.
2. T+5 median net return is positive.
3. T+5 net win rate is at least 55%.
4. T+5 exact-VND profit factor is at least 1.25.
5. Doubled-cost T+5 mean net return remains positive.
6. Doubled-cost exact-VND profit factor remains above 1.00.
7. Mean T+5 net return is positive in at least 75% of calendar years
   containing at least eight primary events.
8. The 10th percentile of `locked_MAE` is no worse than -5%.

Decision statuses:

- `inconclusive_sample`: a count, year-concentration or evaluable-block gate
  fails.
- `rejected_frequency`: sample gates pass but two-month coverage is below 60%.
- `rejected_edge`: sample/frequency passes but an economic or risk gate fails.
- `passed_development_screen`: every frozen gate passes. This permits only a
  separately pre-registered untouched confirmation test.

## Prohibited post-result changes

After the first pooled result is opened, Trial 4 may not:

- change the -6.0% or -0.5% pullback limits;
- replace T+5 with T+3;
- add a gap, volume, volatility or candle filter;
- change the SMA length, costs, overlap rule or acceptance gates;
- open OOS/final data to rescue an unfavorable or sparse result.

Any such change creates a separately numbered trial. Trial 4's same-data
relationship to Trial 3 and VCB's prior selection must remain disclosed.
