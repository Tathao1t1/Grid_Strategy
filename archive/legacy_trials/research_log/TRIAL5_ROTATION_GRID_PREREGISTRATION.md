# Pre-registration: TRIAL5-HSX-ROTATION-LONG-GRID

## Research state

- Pre-registration date: 2026-07-24
- Status: frozen before opening any Trial 5 deployment result
- Scope: development walk-forward only
- Final-test prices/outcomes inspected by Trial 5: no
- Starting capital: VND 100,000,000
- Research unit: one chronological two-month portfolio rotation

Trial 5 models the company workflow: select suitable tickers using the
preceding year, operate a grid for two months, exit, and select again. It is
not a permanent VCB strategy.

This is development research, not an independent confirmation. The ten-name
universe and several rules were developed after earlier experiments on the
same development period. A pass permits one separately controlled final
confirmation; it does not authorize live trading.

## Hypothesis

> A point-in-time selector can identify up to two liquid, oscillating HSX
> stocks without recent severe downtrends, and a settlement-aware one-cell
> long grid can earn stable net returns over the following two months.

The fixed universe is:

```text
FPT HPG MBB MWG PNJ SSI TCB VCB VND VPB
```

This creates survivorship and universe-selection limitations. Trial 5 makes
no claim about all stocks that were historically listed on HSX.

## Frozen walk-forward design

- Fifteen chronological folds: `wf_01` through `wf_15`.
- Each fold fits on the preceding 12 calendar months.
- Each fold deploys during the immediately following two calendar months.
- Deployment periods do not overlap.
- First deployment: 2023-01-03 through 2023-02-28.
- Last deployment: 2025-05-05 through 2025-06-30.
- The nine development sessions from 2025-07-01 through 2025-07-11 are unused.
- `final_test`, beginning 2025-07-14, is locked.

Earlier deployment periods may enter a later fold's training window because
they would be historical information by that later selection date. The
strategy code and thresholds do not change between folds.

Portfolio capital begins once at VND 100 million. A valid fold's ending cash
becomes the next fold's starting capital. All positions and pending sale cash
must be closed and settled before the rotation ends.

## Fold-local ticker selection

Ticker selection is recalculated independently at every training cutoff. The
global output from `select_tickers.py` is prohibited.

The preceding year is divided backward from the cutoff into non-overlapping
10-return-session blocks. Adjacent blocks share only their boundary close, so
each calculation contains 11 closing observations and exactly 10
close-to-close movements. The earliest incomplete block is discarded. For
each valid block:

```text
ER = abs(last close - first close)
     / sum(abs(close[i] - close[i-1]))

return = last close / first close - 1

range = (maximum high - minimum low) / first close
```

Labels are exclusive and applied in this order:

1. `deep_downtrend`: return is at or below -8%.
2. `oscillating_sideways`: ER below 0.35 and range at least 1.2%.
3. `quiet_sideways`: ER below 0.35 and range below 1.2%.
4. `uptrend`: ER at least 0.35 and positive return.
5. `downtrend`: every remaining valid block.

Blocks containing an inferred reference reset or unverifiable ceiling/floor
reference are excluded. A ticker is eligible only when:

- at least 20 valid blocks remain;
- oscillating-sideways share is at least 35%;
- downtrend plus deep-downtrend share is at most 25%;
- deep-downtrend share is at most 5%;
- oscillating-sideways plus uptrend share is at least 60%;
- the latest block is neither downtrend nor deep downtrend;
- no deep-downtrend block appears in the latest six blocks;
- median daily matched value over the latest 60 sessions is at least
  VND 10 billion;
- the latest ATR20/reference window is verifiable; and
- ATR20 divided by price is no greater than the 3% maximum grid step; and
- one 100-share board lot satisfies the frozen exposure and stress budgets.

Eligible tickers are ranked without a fitted score:

1. lowest deep-downtrend share;
2. lowest combined downtrend share;
3. highest oscillating-sideways share;
4. highest median range among oscillating blocks;
5. highest median daily matched value;
6. alphabetical symbol.

At most one ticker may be selected from each frozen sector group: banks
(`VCB TCB MBB VPB`), securities (`SSI VND`), consumer/retail (`MWG PNJ`),
technology (`FPT`), and materials (`HPG`). Select up to two tickers. If one
qualifies, the second capital slot remains cash; if none qualify, the whole
rotation remains cash.

Daily `matched_quantity` is used only for the selector's broad liquidity
screen and includes the source's full daily volume. Minute
`matched_quantity` covers the exported continuous-session matched events and
is used only for execution participation. These fields are not treated as
interchangeable.

## Common one-cell geometric grid

The same formula applies to every ticker. At the training cutoff:

```text
A = final training close
g = clamp(ATR20 / A, 1.5%, 3.0%)

buy limit B = A / (1 + g)
sell target U = A
hard lower H = A / (1 + g)^3
```

Buy prices round down and sell prices round up to the modeled HSX tick
schedule. The grid has exactly one position per ticker. There is no descending
ladder and no averaging down.

Position size is the largest 100-share multiple satisfying both:

- acquisition cash is at most 15% of rotation-start portfolio NAV; and
- loss after three consecutive 7% floor moves, including modeled costs, is at
  most 1.5% of rotation-start NAV.

Therefore aggregate exposure is at most 30% of NAV and aggregate three-floor
stress is at most 3% when two tickers are selected.

Each of the three hypothetical 7% floor moves is rounded down separately to
the then-applicable HSX legal tick before the next move is applied. This avoids
understating the stress loss near tick-band boundaries.

Before a buy is accepted, its planned two-way turnover (buy notional plus
frozen target-sale notional) is reserved. Planned turnover for one ticker may
not exceed 60% of rotation-start portfolio NAV, so the two-ticker portfolio
may reserve at most 120% two-way turnover during one two-month rotation.
This is a hard execution budget, not a post-backtest diagnostic.

## T-1 entry gate

A buy order for session T is armed using rows ending at T-1 only:

```text
close[T-1] > SMA50[T-1]
10-session return through T-1 > -8%
ER10[T-1] < 0.35 OR 10-session return >= 0
close[T-1] > B
```

The latest 50 observations must have verifiable reference information and no
detected reset. The account must be flat at the start of T. A sale cannot
rearm a buy during the same session or while its proceeds are pending.
Re-evaluation begins no earlier than the first observed event at or after the
sale's T+2-afternoon cash settlement.

## Minute execution

Only observed sparse minute events can fill an order. No missing clock minute,
lunch interval, overnight interval, or book state is forward-filled.
The stored timestamp identifies the event-minute bucket, not an exact
sub-minute fill time; execution uses that bucket's final matched price and
last observed book together and never uses its earlier intraminute high/low
to validate a fill.

A normal buy requires:

- valid, non-crossed level-one bid/ask;
- spread no greater than 40 basis points;
- best ask at or below B;
- the last matched price of the event minute at least one legal tick below B;
- displayed ask size sufficient for the complete order; and
- order quantity no greater than 5% of that minute's matched quantity.

A normal target sale applies the symmetric bid, last-price penetration,
displayed size, spread, and participation requirements. Execution includes a
5-basis-point adverse haircut, subject to the resting order never filling at a
price worse than its limit.

## Costs, settlement, and tradeable quantity

```text
buy commission       0.15%
sell commission      0.15%
sell tax             0.10%
execution haircut    0.05% per side
board lot             100 shares
```

Shares bought on observed session T become `tradeable_quantity` at 13:00 on
the second following observed trading session. Sale proceeds become available
on the same T+2-afternoon schedule. Available cash, pending sale cash, total
quantity, tradeable quantity, and locked quantity are separate ledger fields.
End-of-day inventory is marked at estimated net liquidation value after the
same sell commission, tax, and execution haircut, not at an untouched close.

## Risk exits and rotation exit

Using information through the previous close, cancel new buys and permanently
deactivate that ticker for the rotation when:

- its 10-session return is at or below -8%;
- the previous close is at or below H; or
- its account equity is at least 5% below that account's high-water mark.

Tradeable inventory is then offered from the next qualifying observed minute.
Locked inventory waits for settlement. Risk and scheduled exits may ignore
the normal 40-basis-point spread cap, but still require a valid displayed bid
and the frozen size/participation constraints.

Separately, portfolio NAV has one continuous high-water mark beginning at
VND 100 million and persisting across rotations. If an end-of-day NAV is 5%
or more below that high-water mark, a permanent portfolio kill becomes
effective on the next observed session. It liquidates as settlement permits
and leaves every later rotation in cash. This decision uses only the prior
completed day's NAV.

New buys stop early enough for both shares and subsequent sale cash to settle.
Scheduled liquidation begins on the third-last observed session. Any open
position or pending sale cash remaining by 15:00 on the final session
invalidates the fold rather than inventing a fill. The explicit end-of-day
ledger clock may release a legitimate 13:00 settlement even when the sparse
event file's last trade occurred earlier; it never creates an execution.

An unadjusted corporate-action/reference reset in a selected ticker's
deployment invalidates that fold. All 15 folds must remain valid for an
economic decision.

## Frozen diagnostics

Capital utilization is the end-of-day net liquidation value of open inventory
divided by that rotation's starting NAV. Both average and maximum utilization
are reported.

If a predefined risk shutdown occurs while purchased shares are still locked,
the lot is tagged. The report separately sums any loss ultimately realized on
those tagged exits. This is an operational exposure diagnostic, not a claim
that the entire later loss was caused by settlement.

Performance in broad down markets is also reported. For each rotation, the
market proxy is the equal-weight average close-to-close return of all ten
frozen-universe tickers from the final training close through the final
deployment close. A proxy return at or below -5% is labelled `downtrend`, at
or above +5% is `uptrend`, and otherwise `neutral`. This contemporaneous OOS
label is used only to break down performance; it never affects selection,
orders, sizing, or any decision gate.

## Benchmark and doubled-cost diagnostic

The diagnostic benchmark invests the same 15%-of-NAV exposure in each selected
ticker at the first qualifying ask: valid book, spread no greater than 40
basis points, sufficient displayed size, and no more than 5% participation.
It exits at the first similarly qualifying bid on the scheduled third-last
session so its cash can settle by rotation end. It is reported but is not a
decision gate.

The doubled-cost diagnostic repeats the same selections, grid levels and
quantities with commission and execution haircut doubled. Sell tax is
unchanged. It cannot replace the primary result.

## Frozen decision gates

The sample is the 15 two-month portfolio rotations, not 150 ticker rows and
not the individual trades.

Sample gates:

1. All 15 folds are valid.
2. At least 10 folds place a buy.
3. At least 30 ordinary grid campaigns reach their target.

If a sample gate fails, status is `inconclusive_sample`.

With adequate sample, every economic gate must pass:

1. Compounded net return is positive.
2. Median two-month return is positive.
3. Annualized Sharpe calculated from the 15 two-month returns is at least 0.50.
4. At least 60% of rotations are profitable.
5. Exact-VND realized-trade profit factor is at least 1.20.
6. Stitched daily maximum drawdown is no worse than -5%.
7. Worst two-month rotation is no worse than -8%.
8. Doubled-cost compounded return remains positive.
9. Exact-VND doubled-cost realized-trade profit factor remains at least 1.00.
10. Losses realized by risk or scheduled exits do not exceed gains realized
    by ordinary grid-target exits.
11. Modeled commission, sell tax, and execution friction are no more than 1%
    of starting NAV in every two-month rotation.
12. Those modeled costs are no more than 35% of positive pre-cost campaign
    profit across the development walk-forward.

Every doubled-cost fold must also complete its accounting successfully. A
doubled-cost diagnostic failure rejects robustness but does not invalidate or
rewrite the primary capital path.

Failure produces `rejected_development`. Passing every gate produces
`passed_development_screen`, which permits only a separately sealed final
confirmation.

## Bias and leakage controls

- The ten-name universe is disclosed and fixed.
- Selection occurs independently inside every training fold.
- Every selection and grid parameter timestamp is before deployment.
- The selected names and grid levels remain frozen for two months.
- Cash/no-trade rotations remain in the denominator.
- Sector diversification is fixed before results.
- OOS deployment periods do not overlap.
- Final-test rows are skipped before numeric daily parsing.
- Minute rows are filtered by selected ticker and allowed development date
  before numeric parsing.
- A minute row missing matched OHLC is skipped and counted; a selected
  ticker/session must still contain at least one usable observed event. At
  most two such selected-scope rows may be skipped across the authoritative
  run; three or more makes the run `invalid_run`.
- Legacy `validation_fold` is ignored.
- A pre-run seal must match the source, this preregistration, frozen
  configuration, canonical development-only daily rows, assignment file,
  split audit, and all required minute data/manifests before any deployment
  simulation begins. Locked final numeric bytes are deliberately excluded
  from identity.
- The first authoritative result creates a content-addressed run and
  create-only decision lock.

## Prohibited post-result changes

After the first authoritative run, do not change the selector, thresholds,
sector map, top-two rule, grid formula, risk sizing, entry gate, execution
requirements, settlement timing, costs, wind-down timing, gates, or fold
calendar. Do not remove cash rotations or losing tickers. Do not open
`final_test` to repair an unfavorable or sparse result.

Any such modification is a separately numbered Trial 6.
