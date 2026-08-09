# Grid trading research: Trials 1–18 professional review brief

## Purpose of this document

This brief is intended for an independent quantitative trader, researcher or
execution specialist. The requested review is not “which parameter should be
changed next?” It is:

> Is the research implementation technically sound, is the negative result
> economically credible, and is there any defensible next research program
> that would not amount to further optimization on the same sample?

## Executive summary

Eighteen sequential trials investigated long-only grid and short-horizon
mean-reversion trading in liquid HOSE stocks. The work progressed from a
permanent averaging-down grid to settlement-aware one-lot campaigns, causal
pullback signals, cross-sectional models, minute bid/ask execution,
fair-value anchors and market-adjusted residual equilibria.

The recurring economic result was:

```text
many small completed-grid profits
<
fewer forced, gap, downtrend and time-exit inventory losses + costs
```

The strongest apparent positive results were either:

- based on too few observations;
- concentrated in one period or one campaign;
- caused by profitable non-grid exits rather than grid cycles; or
- negative under doubled costs or after removing the best campaign.

Trials 15–18 resolved the earlier daily-bar ambiguity with one-minute bid/ask
execution. Genuine grid cycles occurred, but none of the tested minute
strategies was profitable. Trial 18 produced 80 campaigns, lost money in
every active fold and every ticker, and had a profit factor of 0.300.

No trial passed the declared sequence required to open the locked final
out-of-sample period. No live deployment is authorized.

## Market, universe and data

Initial universe:

```text
FPT, HPG, MBB, MWG, PNJ, SSI, TCB, VCB, VND, VPB
```

Trials 16–18 excluded FPT and PNJ from execution but retained them in the
leave-one-out market proxy.

Main sources:

- daily OHLCV and ceiling/floor data;
- development/final split labels;
- one-minute continuous-session OHLC, matched volume and last bid/ask;
- displayed bid/ask quantity where available.

Important data limitations:

1. The daily stock prices are not a fully corporate-action-adjusted research
   series. The code detects and quarantines apparent reference-price resets.
2. The “market” in most residual features is an equal-weight leave-one-out
   proxy formed from the other stocks, not the official adjusted VN-Index or
   a sector index.
3. The minute files are one-minute aggregates, not raw ordered ticks. They do
   not reveal queue evolution or event order within a minute.
4. Displayed queue quantities are absent in the 2022 archive. Those rows use
   the declared 5% matched-minute participation fallback.

## Execution assumptions in the mature implementation

- 100-share board lots;
- displayed ask for purchases and displayed bid for sales;
- 5-bps adverse execution haircut per side;
- 0.15% commission per side;
- 0.10% sell tax;
- maximum displayed spread of 40 bps;
- order no larger than 5% of matched minute volume;
- displayed queue must cover the order when queue quantity exists;
- legal HSX tick rounding;
- shares and sale cash settle at 13:00 on T+2;
- no immediate sale of unsettled shares;
- normal and doubled-cost simulations;
- corporate-action/reset quarantine;
- chronological folds and a locked final holdout.

## Trial-by-trial summary

### Trial 1 — permanent two-ticker geometric grid

**Hypothesis:** A long-only VCB/VPB grid with weekly anchors, eight intervals,
base inventory, lower-level accumulation and regime exits could harvest
sideways oscillation.

**Material mechanics:** VCB and VPB; VND 1 billion; 30% base inventory; up to
80% invested; increasing exposure as price fell; bounds at anchor ±2 ATR;
T+2.5 inventory; fees, tax and volume participation.

**Result:** 14 folds completed safely; 13 lost money and 13 had negative
Sharpe. In `wf_01`, the strategy lost 7.09%: ordinary grid sales earned
VND 30.5 million while risk exits lost VND 101.4 million. Profit factor was
0.316 and maximum drawdown was 8.91%.

**Conclusion:** Permanently rejected. High win frequency concealed negative
convexity, large directional inventory and cost drag.

### Trial 2 — one-lot VCB risk-hardened grid

**Hypothesis:** Removing base inventory and averaging down would preserve a
small mean-reversion edge while controlling drawdown.

**Material mechanics:** VCB only; one 100-share lot; flat start; three-floor
settlement stress sizing; 20-session timeout; risk exit and cooldown.

**Result:** Three positive and 12 negative folds. Median return was −0.1159%,
median Sharpe −0.244, and median PF 0.6845. Target gains were
VND 2.976 million versus VND 5.014 million of risk-exit losses. Every
doubled-cost fold lost money.

**Conclusion:** Rejected. Risk severity improved substantially, but safer
sizing did not create an edge.

### Trial 3 — confirmed VCB pullback event study

**Hypothesis:** A strict residual pullback followed by confirmation would
identify genuine VCB mean reversion before grid implementation.

**Result:** Only four independent T+5 events versus a required 30. Mean net
return was −0.1172%, median −0.2765%, win rate 50% and PF 0.8303.
Diagnostic T+3 and T+10 results were positive but could not be selected after
observation.

**Conclusion:** Inconclusive sample; did not advance.

### Trial 4 — simplified VCB pullback event study

**Hypothesis:** A simpler causal pullback definition would increase signal
frequency without eliminating the event-study edge.

**Result:** 23 independent T+5 events versus a required 40. Mean net return
was +0.5465% and PF 1.5497, including positive doubled-cost mean, but median
return was −0.6068% and win rate only 39.1%. The result was time-unstable:
2024 had 12 events with a negative mean, while 2022 supplied the strongest
winners.

**Conclusion:** Inconclusive and right-skewed. The positive mean was not
sufficiently distributed through time or observations.

### Trial 5 — ten-ticker rotation and one-cell grid

**Hypothesis:** Select historically sideways, liquid, low-downtrend tickers,
freeze the top two for each two-month deployment and trade a conservative
one-cell minute grid.

**Result:** Fourteen valid rotations, only six active rotations and four
completed target campaigns. Compounded return was −1.408%, annualized
two-month-fold Sharpe −0.975, PF 0.288 and doubled-cost return −1.584%.
Target gains were VND 568,359 versus VND 1,976,316 of forced/scheduled losses.

**Conclusion:** Inconclusive sample with unfavorable economics. The selector
and static entry were too inactive, while filled pullbacks included
breakdowns and gaps.

### Trial 6 — pooled causal residual mean-reversion model

**Hypothesis:** A pooled model across ten tickers could predict symmetric
target-before-downside outcomes and solve Trial 5's activity problem.

**Material mechanics:** Dense residual/volatility/liquidity features;
fold-fitted regularized logistic model; non-overlapping campaigns and sector
caps.

**Result:** 62 campaigns and 32 targets, but only two years met the annual
sample requirement. Total P&L was −VND 1,118,011, median P&L positive,
PF 0.652 and doubled-cost P&L −VND 2,401,452. The model's probability ordering
was reversed out of sample: its lowest predicted quintile reverted more often
than its highest.

**Conclusion:** Activity was solved; signal quality and payoff asymmetry were
not.

### Trial 7 — confirmed episodic two-level grid

**Hypothesis:** Temporary activation after residual and price reversal, with
one equal-sized lower lot, would avoid permanent grid exposure.

**Result:** 36 independent episodes and 25 target sales. Net P&L was
−VND 3,046,582, PF 0.347 and doubled-cost P&L −VND 3,953,879. Target gains of
VND 1,535,823 were overwhelmed by VND 4,666,485 of risk/time losses. The nine
episodes using the lower level lost VND 1,205,138.

**Conclusion:** Formally sample-inconclusive but economically rejected by the
preregistered relaxed-gate diagnostic. Confirmation did not repair the payoff.

### Trial 8 — SSI gate and quantity sensitivity

**Hypothesis:** SSI, the strongest Trial 7 diagnostic ticker, might support a
more active ticker-specific grid; larger quantities might improve delivery.

**Result:** The least-negative loose 100-share rule generated 14 episodes and
14 target sales but lost VND 144,627 with PF 0.827. It won 11 of 14 episodes;
three risk exits erased the gains. Increasing to 200 or 300 shares scaled
losses approximately linearly and breached the exploratory loss budget.

**Conclusion:** No viable SSI variant. Quantity changes exposure, not
expectancy.

### Trial 9 — dynamic bounds and increasing inventory

**Hypothesis:** SMA/ATR dynamic bounds, geometric levels, a lower buffer,
larger intended size toward extremes, inventory skew and deep-trend shutdown
could improve average entry while bounding risk.

**Result:** 27 filled campaigns and 27 target sales. Net P&L was
−VND 6,247,404, PF 0.022, doubled-cost P&L −VND 7,887,797 and worst campaign
−VND 1,717,989. Target gains were only VND 343,052 versus
VND 6,465,267 of risk/time losses.

**Conclusion:** Increasing size toward extremes magnified exposure precisely
when mean reversion failed.

### Trial 10 — single lower re-anchor after stabilization

**Hypothesis:** After a lower-bound breach, the grid could move lower only
after causal stabilization and then wait for recovery.

**Result:** Nineteen filled paired campaigns and six lower-bound breaches,
but zero breaches met the declared stabilization conditions before
catastrophic shutdown. Fixed and re-anchor variants were identical:
−VND 1,434,073 with PF 0.0498.

**Conclusion:** A risk-controlled re-anchor was absent. Automatically moving
the grid lower would have removed the safety rule and become averaging down.

### Trial 11 — formal trend-conditioned optimization

**Hypothesis:** Grid only confirmed pullbacks while ticker and market trends
remained positive.

**Material mechanics:** 216 configurations varying market threshold, residual
threshold, ATR spacing, second level, stop distance and horizon; explicit
in-sample, conditional validation and final lock.

**Result:** Zero of 216 configurations had positive total P&L or PF above
1.10. The least-negative configuration had 18 campaigns, P&L −VND 135,289,
PF 0.870, and doubled-cost P&L −VND 480,507.

**Conclusion:** No in-sample configuration; validation and final OOS stayed
locked.

### Trial 12 — causal ticker-expectancy selector

**Hypothesis:** Recent ticker-level grid expectancy, shrunk toward the pooled
mean and penalized for downside, could select one or more profitable tickers
per rotation.

**Result:** Of 24 configurations, 18 stayed in cash. The six trading
configurations produced the same two VCB campaigns, losing VND 294,990 with
PF 0. The all-universe control lost VND 256,518.

**Conclusion:** Sparse completed-campaign history could not estimate stable
ticker expectancy.

### Trial 13 — dense expected-value ranker

**Hypothesis:** Replace rare campaign history with continuous point-in-time
features and predict exact after-cost campaign return and downside.

**Result:** All 54 configurations had a positive top-minus-bottom score
spread. Five had positive nominal P&L, but none reached PF 1.20, survived
doubled costs or stayed positive after its best campaign was removed. The
best made VND 36,994 from nine campaigns, all in one fold; none exited through
an ordinary target.

**Conclusion:** Features contained weak ranking information, but the selected
tail was concentrated, non-grid and not cost-robust.

### Trial 14 — dense grid-capture ranker

**Hypothesis:** Predict target probability, target-capture return and
inventory loss separately, then rank expected grid capture minus risk.

**Result:** All 48 configurations ranked target frequency directionally, but
every selected configuration realized zero normal grid targets. The best
nominal case made VND 131,694 from four campaigns with PF 1.585, but had a
negative median, doubled-cost loss of VND 16,379 and negative P&L after
removing its best campaign. Its gain came from non-grid trend exits.

**Conclusion:** Daily OHLC labels could not establish executable repeated-grid
economics. Minute execution was required.

### Trial 15 — minute-executed dense grid capture

**Hypothesis:** Chronological one-minute bid/ask execution would resolve daily
touch-order ambiguity and allow dense features to rank real grid cycles.

**Result:** Zero of 48 configurations was profitable. The least-negative
configuration selected 22 campaigns, 12 with grid cycles, and lost
VND 685,810 with PF 0.700. Target-cycle gains were VND 1,645,138 versus
VND 2,334,550 of forced/time losses. Doubled-cost P&L was
−VND 1,197,870, and score ordering was negative.

**Conclusion:** Grid crossings were real and executable, but negative
inventory convexity remained.

### Trial 16 — eight-ticker minute sensitivity

**Hypothesis:** FPT and PNJ might be degrading the minute strategy; remove
them from execution while preserving all other Trial 15 rules.

**Result:** No profitable configuration. The least-negative result had seven
campaigns and four cycles, losing VND 236,901 with PF 0.700. Target gains were
VND 699,890 versus VND 936,791 of forced/time losses.

**Conclusion:** Exploratory post-result sensitivity. Smaller total loss came
mainly from reduced activity; ticker deletion did not alter expectancy.

### Trial 17 — fair-value anchor and reversal grid

**Hypothesis:** Replace the first-minute centre with a prior 20-session median,
enter below it after touch/reclaim, preserve a severe-downtrend veto and cap a
second level with T+2-aware stress.

**Result:** The least-negative of four variants produced 48 campaigns and 24
target campaigns, losing VND 1,479,791 with PF 0.492. Sharpe was −1.532 and
realized closed-campaign MDD 1.504%. The veto reduced forced losses, but
target gains of VND 1,291,084 remained below VND 3,227,432 of other losses.

**Conclusion:** Reclaim improved target frequency but worsened entry price.
The veto helped, while the second level added activity rather than robust
edge.

### Trial 18 — market-adjusted equilibrium and economic target

**Hypothesis:** Use a 60-session beta-adjusted residual-price equilibrium
instead of a lagging raw-price median, and require every fill's target to earn
at least 0.50%–1.00% after normal costs.

**Result:** The least-negative variant produced 80 campaigns and 29 target
campaigns, losing VND 4,254,549 with PF 0.300. Sharpe was −3.688 and realized
closed-campaign MDD 4.255%. Target gains were VND 1,619,405 versus
VND 6,347,578 of forced/time losses. Every active fold and every ticker lost
money.

The existing geometric target already satisfied the 0.50% floor. A 1.00%
floor raised 33 of 103 fill targets, removed two target completions and left
total P&L effectively unchanged.

**Conclusion:** Market adjustment improved target-frequency ordering but did
not establish a stationary or economically mean-reverting spread.

## Research progression and interpretation

### Phase 1: inventory-risk discovery — Trials 1–2

Removing averaging down, permanent inventory and high exposure dramatically
reduced drawdown. It did not change the fact that risk exits cost more than
completed cycles.

### Phase 2: entry and grid-structure research — Trials 3–10

Confirmation, episodic activation, ticker anchoring, dynamic bounds,
inventory skew, increasing size and re-anchoring were tested. Strict rules
created too few observations; looser or larger implementations generated
enough trades but exposed the same negative payoff.

### Phase 3: formal daily-data selection — Trials 11–14

The research adopted explicit in-sample optimization, conditional validation
and locked final OOS. Continuous features sometimes ranked outcomes
directionally. The selected campaigns were not robust after costs and often
made money through non-grid exits rather than target cycles.

### Phase 4: minute execution — Trials 15–18

One-minute bid/ask replay confirmed that genuine target cycles existed.
Changing ticker universe, anchor, entry confirmation, crash veto, number of
levels, residual equilibrium and target economics did not produce positive
expectancy.

## Strong parts of the implementation

- Point-in-time feature construction and chronological deployment.
- Purging of labels that would cross partition boundaries.
- Explicit T+2 share and cash settlement.
- Bid/ask, tick, spread, queue and volume-participation constraints.
- Commission, tax, execution haircut and doubled-cost stress.
- Corporate-action/reference-reset quarantine.
- Sector, overlap, concurrency and cooldown controls.
- Best-campaign-removal and target-versus-forced-loss diagnostics.
- Create-only result directories and validation/final locks.
- Reproducible scripts, artifacts and 107 automated tests.

## Important limitations for independent review

1. **Adaptive research history:** The same development sample informed many
   later hypotheses. Trials 8–18 are increasingly post-result and cannot be
   treated as independent tests. Nominally profitable variants would require
   new data regardless of their in-sample statistics.
2. **No official adjusted benchmark:** Residuals use an internal stock proxy,
   not an adjusted VN-Index or sector series.
3. **Corporate actions:** Reset detection prevents obvious false trades but is
   not a substitute for fully adjusted historical prices.
4. **Minute aggregation:** The simulator cannot know bid/ask/last-trade event
   order or queue evolution inside a minute.
5. **Later-trial portfolio ledger:** Trials 15–18 simulate campaign execution
   individually and then impose overlap/concurrency rules. A reviewer should
   verify whether a single consolidated portfolio cash, settlement and
   aggregate-participation ledger is required. With small 100-share positions
   and VND 100 million nominal NAV this may not change results, but it is a
   modeling distinction.
6. **Drawdown definition:** Trials 17–18 report realized closed-campaign
   drawdown, not a minute-by-minute marked-to-market portfolio drawdown.
7. **Overlapping early folds:** Trials 1–2 used overlapping 12-month training
   windows as robustness views; they are not independent observations.
8. **Probability calibration:** Some later models use clipped ridge outputs
   as target “probabilities.” Their ranking may be useful, but they are not
   calibrated probabilistic forecasts.
9. **Residual stationarity:** Trial 18 estimates an equilibrium from a
   residual-price path but does not require formal stationarity or a stable
   hedge ratio. Market adjustment alone does not guarantee mean reversion.
10. **Long-only structural exposure:** Without a short hedge, the grid remains
    exposed to persistent idiosyncratic repricing and market beta while T+2
    can delay exits.

## Questions for the professional reviewer

1. Is a long-only single-stock grid structurally unsuitable under HOSE price
   limits, transaction costs and T+2 settlement?
2. Is the minute fill model conservative enough, or does one-minute
   aggregation create material optimistic or pessimistic bias?
3. Should later trials be rerun through one consolidated portfolio cash,
   settlement, exposure and minute-participation ledger?
4. Are the corporate-action reset rules sufficient for rejection evidence,
   or is fully adjusted OHLCV mandatory before drawing any conclusion?
5. Is the internal leave-one-out stock proxy acceptable, or should the work
   require adjusted VN-Index and sector-index data?
6. Is the target/forced-loss decomposition the right economic diagnostic?
   What ex-ante payoff ratio and hit rate would be required after all costs?
7. Would a stationarity-first, market-neutral stock/index or stock-pair spread
   be a materially better object for grid trading?
8. How should hedge-ratio stability, stationarity and mean-reversion half-life
   be estimated without introducing another large multiple-testing problem?
9. What sample size and nested validation scheme would be credible after
   eighteen adaptive development trials?
10. Is any further use of this development sample defensible beyond code
    verification, or should all economic research move to newly acquired
    untouched data?

## Requested audit

Please review:

- future-data leakage and partition purging;
- fill and queue realism;
- T+2 settlement and cash availability;
- gap and price-limit handling;
- corporate-action treatment;
- portfolio-level exposure and drawdown;
- model calibration and score construction;
- multiple testing and research degrees of freedom;
- whether the repeated negative-convexity finding is likely genuine;
- whether any new strategy should be treated as a separate market-neutral
  research program rather than Trial 19.

## Recommended files to share

- `research_log/TRIALS_1_TO_18_PROFESSIONAL_REVIEW_BRIEF.md`
- `research_log/REJECTED_GRID_LONG_V1.md`
- `research_log/REJECTED_GRID_LONG_V2.md`
- `research_log/TRIAL11_TREND_CONDITIONED_GRID_PREREGISTRATION.md`
- `research_log/TRIAL15_MINUTE_GRID_CAPTURE_PREREGISTRATION.md`
- `research_log/TRIAL15_MINUTE_GRID_CAPTURE_RESULT.md`
- `research_log/TRIAL17_FAIR_VALUE_REVERSAL_GRID_PREREGISTRATION.md`
- `research_log/TRIAL17_FAIR_VALUE_REVERSAL_GRID_RESULT.md`
- `research_log/TRIAL18_MARKET_EQUILIBRIUM_ECONOMIC_TARGET_PREREGISTRATION.md`
- `research_log/TRIAL18_MARKET_EQUILIBRIUM_ECONOMIC_TARGET_RESULT.md`
- `study_trial15_minute_grid_capture.py`
- `study_trial17_fair_value_reversal_grid.py`
- `study_trial18_market_equilibrium_grid.py`
- `tests/`
- the data dictionary/schema and split-generation script.

## Bottom-line review position

The implementation work increasingly isolated execution, risk and selection
questions, and the final negative result is more informative than the early
sparse trials. However, eighteen adaptive uses of the same development data
mean this sample should now be considered exhausted for economic discovery.

The present evidence supports rejecting this long-only single-stock grid
family, not claiming that every possible grid strategy is impossible. A
future program should use new untouched data and a materially different,
stationarity-first or hedged economic object.
