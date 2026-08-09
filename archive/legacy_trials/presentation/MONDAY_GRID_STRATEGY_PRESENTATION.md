---
title: "Long-Only Grid Trading for Vietnamese Equities"
subtitle: "Implementation, falsification and the decision not to deploy"
date: "Monday presentation"
---

# Risk-Capped Episodic Grid Trading

## Vietnamese equity market research prototype

**Recommendation:** reject the tested long-only single-stock grid family.
Preserve the old holdout, certify the infrastructure once, and treat any
hedged residual research as a separate program.

**Current status:** implementation complete; no live capital authorized.

## Main decision principle

A Type II error remains possible: the strategy might have been profitable in
another sample. But the costs of the two mistakes are asymmetric:

- rejecting a genuinely profitable strategy misses an opportunity;
- accepting a negative-convexity strategy risks capital after repeatedly
  unfavorable evidence.

Uncertainty is therefore not authorization to deploy.

<!--
Speaker note:
The deliverable is a complete and testable grid architecture. I will distinguish
the strategy design from the current evidence. The backtest does not support a
claim of proven profitability yet.
-->

---

# 1. Business requirement and research question

## Requirement

Develop a grid trading strategy for one or more liquid Vietnamese stocks.

## Correct research question

> Given today's information, is price likely to cross profitable grid levels
> before inventory reaches its downside boundary?

This is different from asking whether a ticker was historically sideways.

## Economic constraint

Modeled round-trip friction is approximately **0.50%**:

| Component | Rate |
|---|---:|
| Buy commission | 0.15% |
| Buy execution haircut | 0.05% |
| Sell commission | 0.15% |
| Sell tax | 0.10% |
| Sell execution haircut | 0.05% |

Grid spacing must be materially wider than transaction costs.

---

# 2. What six earlier trials established

| Trial | Main lesson |
|---|---|
| 1 | Permanent long grid accumulated the most inventory during declines |
| 2 | Smaller exposure reduced drawdown but did not create positive expectancy |
| 3 | Strong reversal confirmation produced only five independent events |
| 4 | Simpler pullback improved frequency, but median return stayed negative |
| 5 | Rotation generated only nine campaigns; forced losses were 3.48× target gains |
| 6 | Pooled prediction generated enough signals but ranked outcomes incorrectly |

## Repeating failure pattern

```text
many small profitable exits
             <
fewer large inventory and gap losses + costs
```

The next design must change inventory acquisition, not merely move the stop.

---

# 2B. Canonical assessed experiment

## Trial 11 research pipeline

```text
Hypothesis
→ 2022–June 2024 in-sample optimization
→ July 2024–July 2025 internal validation
→ July 2025–July 2026 final OOS
```

Hypothesis: buy a confirmed short-term residual pullback only while the ticker
and market remain in positive medium-term trends.

Optimization:

- 216 declared configurations
- market threshold, residual threshold and ATR spacing
- one versus two levels
- downside distance and campaign horizon
- exact costs and T+2 settlement

Advancement was automatic: validation could open only after the in-sample
economic gates passed.

---

# 2C. Trial 11 optimization result

| Measure | Result |
|---|---:|
| Configurations evaluated | 216 |
| Positive in-sample configurations | **0** |
| Configurations with PF ≥ 1.10 | **0** |
| Configurations with ≥25 campaigns | 132 |
| Configurations with positive median trade | 110 |

Least-negative configuration:

| Metric | Result |
|---|---:|
| Campaigns | 18 |
| Total P&L | −VND 135,289 |
| Median P&L | +VND 35,512.5 |
| Profit factor | 0.87 |
| Doubled-cost P&L | −VND 480,507 |

**Governance result:** internal validation and final OOS remained locked.

---

# 2D. Trial 12 causal ticker selection

## Hypothesis

Recent ticker-specific grid expectancy may be more stable than pooled grid
expectancy. Re-select tickers every two months using only completed prior
campaigns, with shrinkage toward the pooled mean and a downside penalty.

## Result

| Measure | Result |
|---|---:|
| Pre-registered selector configurations | 24 |
| Eligible in-sample configurations | **0** |
| Configurations that stayed in cash | 18 |
| Maximum campaigns in a configuration | **2** |
| P&L of configurations that traded | **−VND 294,990** |
| Profit factor | **0.00** |
| All-universe control P&L | −VND 256,518 |

The 57-campaign historical library had 32 winners but lost VND 1.378 million
in aggregate. Shrinkage therefore rejected most ticker-months. The few
selected deployment signals were two VCB losses.

**Governance result:** validation and final OOS remained locked. The result is
both sample-inconclusive and economically adverse; merely lowering the pass
threshold would not make it profitable.

---

# 2E. Trial 13 dense expected-value model

## Materially different hypothesis

Replace rare completed-campaign history with every eligible ticker-session.
Fit pooled models to the exact after-cost grid return and downside, then rank
daily candidates by:

```text
predicted net return − risk penalty × predicted downside
```

## Result

| Measure | Result |
|---|---:|
| Dense deployment observations | 1,575 |
| Pre-registered model configurations | 54 |
| Positive score-quintile spread | **54 / 54** |
| Positive nominal-P&L configurations | 5 |
| Configurations with PF ≥ 1.20 | **0** |
| Positive under doubled costs | **0** |
| Positive after best trade removed | **0** |

Best nominal configuration: nine campaigns, +VND 36,994 and PF 1.098, but
−VND 260,554 under doubled costs. All nine occurred in one fold and exited
through trend shutdown; none captured a normal grid target.

**Conclusion:** continuous features improved ranking, but the executable edge
was too small, concentrated and cost-sensitive. Validation and final OOS
remained locked.

Protocol note: the declared three-entry-year in-sample gate was impossible
within the 2023–June 2024 deployment window. Removing it would not change the
decision because the independent P&L, sample, PF, doubled-cost and
best-trade-removed gates also failed.

---

# 2F. Trial 14: predict grid capture itself

## Hypothesis

Predict normal grid-target probability and after-cost capture separately from
non-target inventory loss. Profitable trend exits do not count as grid edge.

## Result

| Measure | Result |
|---|---:|
| Pre-registered configurations | 48 |
| Positive target-rate score spread | **48 / 48** |
| Selected-campaign range | 1–8 |
| Selected normal grid targets | **0** |
| Positive nominal-P&L configurations | 3 |
| Positive doubled-cost configurations | **0** |
| Positive grid target gains minus losses | **0** |

The best nominal configuration made +VND 131,694 with PF 1.585, but had only
four campaigns, a negative median, zero target captures, −VND 16,379 under
doubled costs and −VND 164,013 after removing its best campaign.

**Conclusion:** the model ranked target frequency across the full pool, but
the rare executable tail did not generalize. Its nominal gain came from
non-grid trend exits. Validation and final OOS remained locked.

---

# 2G. Trial 15: one-minute execution

## What changed

- Existing 2022–2025 one-minute bid/ask archive
- Chronological minute fills rather than daily OHLC touches
- Spread, displayed liquidity and 5% participation constraints
- T+2 settlement at 13:00
- Repeated frozen grid cell and no same-minute re-entry

## Result

| Measure | Result |
|---|---:|
| Pre-registered configurations | 48 |
| Positive configurations | **0** |
| Selected-campaign range | 6–22 |
| Cycle-campaign range | 1–12 |
| Positive score-quintile cycle spread | **0 / 48** |

Least-negative configuration:

| Metric | Result |
|---|---:|
| Campaigns / cycle campaigns | 22 / 12 |
| Median P&L | +VND 14,867 |
| Net P&L | **−VND 685,810** |
| Profit factor | **0.700** |
| Target-cycle gains | +VND 1,645,138 |
| Forced/time losses | **−VND 2,334,550** |
| Doubled-cost P&L | **−VND 1,197,870** |

**Conclusion:** minute data confirmed genuine executable crossings, but forced
inventory losses still exceeded accumulated cycle gains. Validation and the
July 2025–June 2026 minute holdout remained locked.

---

# 2H. Eight-ticker sensitivity

FPT and PNJ were removed from candidate selection after Trial 15. This is an
exploratory sensitivity, not an independent trial.

| Metric | 10 tickers | Excluding FPT/PNJ |
|---|---:|---:|
| Least-negative P&L | −VND 685,810 | **−VND 236,901** |
| Profit factor | 0.700 | **0.700** |
| Campaigns / cycle campaigns | 22 / 12 | 7 / 4 |
| Doubled-cost P&L | −VND 1,197,870 | −VND 464,725 |
| Target gains | +VND 1,645,138 | +VND 699,890 |
| Forced/time losses | −VND 2,334,550 | −VND 936,791 |

The smaller universe reduced the loss magnitude but also reduced the sample.
It did not change the approximately 0.70 profit factor or make any
configuration profitable. Validation remained locked.

---

# 3. Episodic-grid architecture stage (Trial 7)

## Signal-activated episodic grid

```text
Ten-stock liquid universe
          ↓
Relative-price downside deviation
          ↓
Causal reversal confirmation
          ↓
Activate a temporary two-level grid
          ↓
Normal target / regime exit / time exit / catastrophic exit
          ↓
Cooldown and reassessment
```

Key design choices:

- operate on up to three qualified tickers rather than selecting one permanent
  “grid stock”;
- freeze the grid centre for each episode;
- use equal 100-share lots—never martingale sizing;
- permit at most one lower inventory level;
- expire every campaign after 15 sessions;
- size for gaps and settlement risk rather than assuming a guaranteed stop.

---

# 4. Activation signal

For entry at session **T**, all information ends at **T−1**.

## Setup

- Five-session stock residual z-score ≤ −0.75
- Residual is measured against the equal-weight return of the other nine stocks
- Median 60-session traded value ≥ VND 10 billion
- ATR20 / price ≤ 5%

## Reversal confirmation

- Latest one-session residual return > 0
- Close[T−1] > Close[T−2]
- Five-session market-proxy return > −5%

The strategy does not buy the first falling-price touch. It waits until the
relative deviation begins reversing.

> Production improvement: replace the internal market proxy with adjusted
> VN-Index and sector-index data.

---

# 5. Grid construction

At the activation-session open:

\[
g=\operatorname{clamp}(ATR20/Price,\;1.5\%,\;3.0\%)
\]

| Level | Buy | Sell target | Quantity |
|---|---:|---:|---:|
| Initial B0 | Activation open | B0 × (1 + g) | 100 shares |
| Lower B1 | B0 / (1 + g) | B0 | 100 shares |

Catastrophic boundary:

\[
H = \frac{B0}{(1+g)^3}
\]

All derived prices use modeled HSX tick rounding.

## Lower-level confirmation

1. A completed session touches B1.
2. That session closes above B1 and above its open.
3. B1 buys at the following session open, subject to the frozen price cap.

The second lot is not purchased merely because price continues falling.

---

# 6. Risk and operational controls

## Campaign controls

- Maximum inventory: 200 shares
- No increasing lot size
- No moving grid centre downward
- Maximum duration: 15 sessions
- Hard-lower shutdown after a three-step decline
- Five-session cooldown after exit

## Portfolio controls

- Maximum three simultaneous campaigns
- Maximum one active ticker per sector
- Rank by residual deviation and reversal strength
- Unused capacity remains cash

## Vietnam-specific execution

- 100-share board lots
- T+2 share availability modeled separately for every lot
- Locked shares cannot be sold at an early target or stop
- Opening gaps execute at the adverse open
- Corporate-action/reference resets quarantine the episode

---

# 7. Trial 7 development result

## Sample

| Metric | Result |
|---|---:|
| Valid walk-forward folds | 15 / 15 |
| Activation candidates | 67 |
| Independent selected episodes | 36 |
| Ordinary target sales | 25 |
| Entry-year distribution | 16 / 14 / 6 |

## Economics

| Metric | Result |
|---|---:|
| Net P&L | **−VND 3,046,582** |
| Median episode P&L | +VND 31,231 |
| Profit factor | **0.347** |
| Normal target gains | +VND 1,535,823 |
| Risk/time losses | **−VND 4,666,485** |
| Doubled-cost P&L | **−VND 3,953,879** |

**Decision:** do not advance this version to live trading or minute-level
execution.

---

# 7B. Slide-inspired increasing-size grid

## Implemented Trial 9 additions

- Dynamic bounds: SMA20 ± 2 ATR
- Six-interval geometric grid
- 0.75-ATR buffer below the lower bound
- Intended lower-level quantities: 100 / 200 / 300 shares
- Inventory adjustment: reduce buys as inventory rises
- Pre-buy loss stress limited to 1.5% of VND 100 million
- Deep-trend shutdown using ticker, market and residual evidence

## Result

| Metric | Result |
|---|---:|
| Executed campaigns | 27 |
| Net P&L | **−VND 6,247,404** |
| Profit factor | **0.022** |
| Target gains | +VND 343,052 |
| Risk/time losses | **−VND 6,465,267** |
| Worst campaign | **−VND 1,717,989** |

Increasing quantity toward the extreme magnified exposure precisely when a
large deviation was becoming a regime break. Inventory skew and shutdown
reduced some orders but acted too late to create positive expectancy.

---

# 8. SSI case study and sensitivity

SSI was the strongest repeat candidate in Trial 7:

| Entry | Outcome | Net P&L |
|---|---|---:|
| 2024-03-25 | Initial target | +VND 90,787 |
| 2024-05-07 | Initial target | +VND 91,807 |
| 2024-07-19 | Risk exit | −VND 201,716 |
| 2024-08-05 | Two grid targets | +VND 89,223 |

Summary:

- 3 wins from 4 episodes
- Total: +VND 70,101
- Profit factor: 1.35
- Doubled-cost result: **−VND 15,379**
- All observations occurred in 2024

## Interpretation

SSI is appropriate only as an engineering demonstration. Four episodes do not
establish a ticker-specific edge, and the later pooled evidence does not
authorize prospective capital deployment under this long-only design.

## Broader SSI development-data check

| Gate | Independent episodes | Net P&L | Profit factor |
|---|---:|---:|---:|
| Strict | 8 | −VND 314,655 | 0.59 |
| Moderate | 10 | −VND 428,507 | 0.54 |
| Loose confirmation | 14 | −VND 144,627 | 0.83 |

The loosest rule won 11 of 14 episodes but still lost money because three risk
exits exceeded the accumulated target gains. Buying 200 or 300 shares simply
multiplied both gains and losses.

---

# 8B. Can the grid re-anchor lower?

## Trial 10 paired experiment

The same 36 activations were run as:

1. a fixed-centre control;
2. a single-reanchor recovery grid.

After a lower-bound break, recovery required three non-decreasing lows, two
increasing closes, a positive residual and clear ticker/market trend checks.

| Metric | Result |
|---|---:|
| Filled paired campaigns | 19 |
| Lower-bound breaches | 6 |
| Qualified re-anchors | **0** |
| Control P&L | −VND 1,434,073 |
| Recovery P&L | −VND 1,434,073 |

Every lower-bound breach reached catastrophic shutdown without establishing
causal stabilization. Automatically moving the centre lower would therefore
remove the exact condition intended to distinguish mean reversion from a
downtrend.

---

# 9. Implemented deliverable

## What is ready

- Reproducible signal and grid specification
- Daily settlement-aware Stage-A simulator
- Fifteen chronological walk-forward folds
- Corporate-action quarantine
- Exact fee/tax accounting
- Automated tests for settlement, gaps, lower-level confirmation and sector caps
- Causal ticker selector with a create-only validation/OOS lock
- Dense, point-in-time expected-return/downside models with purged labels

## What should be presented honestly

> We implemented a controlled grid strategy and identified the remaining
> economic failure: occasional inventory losses still dominate ordinary grid
> gains. The system is ready for independent infrastructure audit and
> presentation, not capital deployment.

This is stronger than presenting an overfit positive result.

---

# 10. Separate future research program

## Phase 1 — data improvement

- Obtain corporate-action-adjusted OHLCV
- Add adjusted VN-Index and sector indices
- Obtain older untouched history so ticker selection is not estimated from
  only a handful of completed campaigns

## Phase 2 — clean infrastructure certification

- Reproduce frozen Trial 18 once in a clean output environment
- Verify code, input, configuration and output hashes
- Reconcile trades, fees, taxes, inventory and settlement
- Do not change parameters or open the old holdout

## Phase 3 — new hedged research

- Use new adjusted stock, index/sector and hedge-instrument data
- Establish spread stationarity and hedge-ratio stability first
- Test one entry and one exit before introducing any grid
- Use one marked-to-market stock/futures portfolio ledger

## Advancement gates for any separate strategy

- At least 20–30 independent SSI episodes or 60 diversified episodes
- Positive median P&L
- Profit factor ≥ 1.20
- Positive doubled-cost P&L
- Risk/time losses no greater than grid gains
- Positive result after removing the best episode

Trial 12 shows why sample size is an advancement condition, not a cosmetic
gate: its only two selected campaigns both lost money.

Trial 13 shows that a statistically directionally useful ranker is still not
enough: the selected tail must remain profitable after costs, across folds,
and after removing its best campaign.

Trial 14 strengthens that conclusion: an algorithmic grid result must contain
actual target captures. Positive P&L caused by trend exits is not evidence for
the proposed grid mechanism.

Trial 15 supplies that missing test. Actual minute-executed target cycles
occurred, but they still did not cover tail inventory losses and transaction
costs.

Trial 17 then tested the proposed structural repair directly. A prior
20-session median replaced the first-minute anchor; orders activated at lower
geometric levels; reclaim confirmation, a severe-downtrend veto, a second
fixed 100-share level and a two-floor T+2 risk budget were evaluated as a
four-step ablation. The least-negative version completed targets in 24 of 48
campaigns but lost VND 1.480 million with PF 0.492 and doubled-cost P&L of
−VND 2.159 million. The veto reduced forced losses, but the grid's after-cost
payoff remained negative. Validation and final OOS stayed locked.

---

# 10B. Trial 17 fair-value reversal grid

## Frozen mechanics ablation

| Variant | Campaigns | Target campaigns | Net P&L | PF |
|---|---:|---:|---:|---:|
| Fair anchor + touch | 61 | 18 | −VND 2,514,716 | 0.386 |
| Add reclaim | 58 | 25 | −VND 2,529,894 | 0.359 |
| Add severe-downtrend veto | 44 | 18 | −VND 1,501,888 | 0.390 |
| Add second capped level | 48 | 24 | **−VND 1,479,791** | **0.492** |

## What the ablation established

- Reclaim confirmation increased target frequency but entered at a worse
  price, leaving too little target distance after costs.
- The severe-downtrend veto was the only material improvement.
- The second level added executions and target sales but also added inventory
  loss; doubled-cost performance deteriorated.
- The least-negative variant had Sharpe −1.532 and a 1.504% realized
  closed-campaign maximum drawdown.
- Six of eight tickers lost money; this was not a single-ticker accident.

**Decision:** the fair-value/reversal hypothesis did not pass in-sample.
Internal validation and final OOS remain unopened.

---

# 10C. Trial 18 market-adjusted equilibrium

## Repair tested

- 60-session beta against the leave-one-out stock-market proxy
- Cumulative residual-price displacement from its recent 20-session median
- Centre correction capped at two ATRs
- Trial 17 severe-downtrend veto retained
- Per-fill target floor guaranteeing 0.50%, 0.75% or 1.00% profit after
  normal commission and sell tax

## Result

| Net target floor | Campaigns | Target campaigns | Net P&L | PF |
|---|---:|---:|---:|---:|
| Diagnostic control | 80 | 31 | −VND 4,254,550 | 0.297 |
| 0.50% | 80 | 31 | −VND 4,254,550 | 0.297 |
| 0.75% | 80 | 30 | −VND 4,264,525 | 0.298 |
| 1.00% | 80 | 29 | **−VND 4,254,549** | **0.300** |

The original structural target already cleared the 0.50% floor. Raising the
floor to 1.00% adjusted 33 of 103 fills but removed two completed targets and
did not improve total economics.

## Interpretation

- Opportunity-score target-rate spread improved to +26.9 percentage points.
- Target gains were VND 1.619 million.
- Forced/time losses were VND 6.348 million.
- All active folds and all eight tickers lost money.
- A beta-adjusted displacement can be persistent idiosyncratic repricing;
  market adjustment alone does not establish a stationary spread.

**Decision:** no variant advances. Further target widening is not supported.

## Management decision requested

Approve the rejection of the tested long-only strategy, one frozen
infrastructure rerun, and data acquisition for a separately preregistered
hedged residual study. Do not approve live deployment.

---

# Appendix: strategy pseudocode

```python
for session in trading_calendar:
    features = calculate_point_in_time_residual_features(session - 1)
    candidates = [
        ticker for ticker in universe
        if residual_z5[ticker] <= -0.75
        and residual_return_1[ticker] > 0
        and close[ticker][-1] > close[ticker][-2]
        and market_return_5 > -0.05
    ]

    for ticker in rank_with_sector_caps(candidates, max_positions=3):
        g = clamp(atr20[ticker] / close[ticker][-1], 0.015, 0.030)
        activate_grid(
            initial_lot=100,
            lower_lot=100,
            initial_target=1 + g,
            lower_level=1 / (1 + g),
            hard_lower=1 / (1 + g) ** 3,
            maximum_sessions=15,
        )
```
