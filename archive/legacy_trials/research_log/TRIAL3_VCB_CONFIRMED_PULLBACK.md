# Pre-registration: TRIAL3-VCB-CONFIRMED-PULLBACK

## Research state

- Status: pre-registered; in-sample edge study only
- Pre-registration date: 2026-07-23
- Fixed ticker: VCB
- Initial execution reference: one 100-share lot
- Walk-forward OOS inspected: no
- Final holdout inspected: no
- Predecessor: `REJECTED_GRID_LONG_V2.md`

Trial 3 is not another grid backtest. It asks one narrower question:

> After a moderate pullback in an established VCB uptrend, does a confirmed
> reversal predict a sufficiently large T+5 return after realistic costs?

T+5 is the only primary horizon. T+3 and T+10 are diagnostics. Trial 3 may
not choose the best-looking horizon after the results are known.

## Frozen T-1 signal

For hypothetical entry on trading session `T`, every condition is calculated
using data ending at `T-1`:

```text
close[T-1] > SMA50[T-1]
SMA20[T-1] > SMA50[T-1]

-5% <= close[T-1] / close[T-6] - 1 <= -1%
close[T-1] / close[T-11] - 1 > -7%

close[T-1] > close[T-2]
(close[T-1] - low[T-1]) / (high[T-1] - low[T-1]) >= 0.60

ATR14[T-1] / close[T-1] <= 3%
```

A zero-range signal bar is invalid. There is no day-T gap filter in this
trial. The opening gap is recorded only as a diagnostic.

The economic interpretation is:

1. Long-term direction remains positive.
2. VCB has experienced a meaningful but controlled pullback.
3. The latest completed session provides initial evidence of recovery.
4. Volatility is not extreme.

## Entry and labels

- `T` is the next observed VCB trading session, not the next calendar day.
- Research entry reference: official open on `T`.
- T+3/T+5/T+10 exit references: official close on the corresponding future
  trading session.
- T+10 must remain inside the same fold's in-sample dates. Otherwise the
  entire event is purged.
- Opening and closing prices are research labels, not guaranteed executable
  auction fills.

Exact modeled costs:

```text
buy commission       0.15%
sell commission      0.15%
sell tax             0.10%
slippage each side   0.05%
```

The doubled-cost diagnostic doubles commission and slippage but does not
double the statutory sell-tax assumption.

Profit factor is frozen as conventional cash profit factor for the specified
one-lot experiment:

```text
profit factor =
    sum of positive exact VND trade P&L
    / absolute sum of negative exact VND trade P&L
```

It is not calculated from normalized percentage returns.

For each horizon `h`:

```text
net_return[h] =
    net sale proceeds at close[T+h]
    / total acquisition cash at open[T]
    - 1

MFE[h] = max(high from T through T+h) / open[T] - 1
MAE[h] = min(low from T through T+h) / open[T] - 1
```

`locked_MAE` is the minimum low from T through T+2 relative to the entry
price. It is a path-risk proxy while stock may not yet be sellable, not an
assumed executable stop.

The study also records which 1.5% favorable or 3% adverse barrier was observed
first through T+10. If both occur in the same daily bar before either was
previously observed, the result is `both_hit_same_bar`; no favorable ordering
is invented. Any hit on T+2 is conservatively marked as occurring within the
settlement-day uncertainty window because daily OHLC cannot identify whether
it occurred before or after afternoon settlement.

## Corporate-action treatment

- An inferred reference reset in the preceding 50-session feature window
  invalidates the signal.
- A reset from T through T+10 quarantines the label from all aggregates.
- If the reset cannot be verified because ceiling or floor metadata is
  unavailable anywhere in the feature or label window, the signal/label is
  excluded under the same zero-tolerance data-quality rule.
- The forward reset is a data-label integrity exclusion, never an entry rule.
- The reset heuristic compares the ceiling/floor implied reference with the
  previous official close. Authoritative corporate-action factors would be
  preferable.
- Reset flags are recomputed within each fold. Its first row is deliberately
  marked unverifiable because the prior close is outside the fold; therefore
  it cannot enter a valid 50-session feature window.

## Leakage and overlap controls

- Only `primary_split=development` VCB prices on dates selected as
  `role=in_sample` for the requested study scope are parsed.
- Walk-forward OOS metadata is read only to validate that roles do not
  overlap; OOS prices and outcomes are not parsed for the requested scope.
- Indicators are built only from that fold's in-sample rows.
- A 50-session warm-up is required inside each fold.
- Each fold must be a contiguous slice of the VCB development calendar, so a
  missing assignment cannot silently redefine T+5 or T+10.
- Every feature date is strictly earlier than its entry date.
- Every T+10 label remains inside the same in-sample fold.
- OOS and final-test prices cannot supply features or labels.

Because the 12-month folds overlap, pooled fold events are not independent.
The primary sample:

1. deduplicates candidates by entry date;
2. sorts them chronologically;
3. accepts the earliest candidate;
4. suppresses later candidates through that event's T+10;
5. repeats.

Fold membership is retained only as a stability diagnostic.

## Frozen acceptance gates

Trial 3 advances to an execution backtest only if every gate passes:

1. At least 30 valid, unique, T+10-non-overlapping events.
2. At least three calendar years contain at least five primary events each.
3. Primary T+5 mean net return is at least +0.50%.
4. Primary T+5 median net return is positive.
5. Primary T+5 net win rate is at least 55%.
6. Primary T+5 profit factor is at least 1.25.
7. Doubled-cost T+5 mean remains positive.
8. Doubled-cost T+5 profit factor remains above 1.00.
9. T+5 mean is positive in at least 70% of fold slices containing at least
   five primary events.
10. The 10th percentile of `locked_MAE` is no worse than -5%.

Fewer than 30 primary events produces `inconclusive_sample`, not a pass.
Adequate sample size with any failed economic/risk gate produces `rejected`.
No threshold may be loosened after reading the results; doing so would define
a separate Trial 4.
