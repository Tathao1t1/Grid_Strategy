---
title: "Long-Only Grid Trading for Vietnamese Equities"
subtitle: "Implementation, falsification and the decision not to deploy"
date: "Final presentation"
---

# Long-Only Grid Trading Research

## From ticker filtering to minute execution and risk-governed rejection

**Implementation status:** complete research prototype  
**Economic decision:** reject the tested long-only single-stock grid family  
**Validation status:** internal validation and final OOS remain locked

---

# 1. Requirement and research question

## Requirement

Implement a grid trading strategy for one or more liquid Vietnamese stocks.

## Initial intuition

1. Find stocks that frequently trade sideways.
2. Buy at lower grid levels.
3. Sell when price returns toward the centre.
4. Pause or exit when a downtrend appears.

## Research question that emerged

> Can a causal signal identify price paths that will complete enough
> after-cost grid cycles before long inventory experiences a gap, downtrend or
> forced exit?

The implementation requirement was achieved. The economic hypothesis was
tested and rejected.

---

# 2. Main finding: asymmetric decision costs

The strategy could be a false negative. Quantitative research cannot eliminate
a Type II error.

But the decision costs are asymmetric:

| Decision error | Consequence |
|---|---|
| Reject a genuinely profitable strategy | Miss an opportunity |
| Accept a negative-convexity strategy | Risk capital after repeatedly unfavorable evidence |

Therefore:

> Uncertainty about future profitability is not sufficient authorization to
> deploy. Positive expectancy must be demonstrated before accepting
> path-dependent inventory risk.

This is the central management finding.

---

# 3. Why a long-only grid is negatively convex

One completed cycle earns approximately one grid step minus costs.

During a persistent decline:

- inventory remains long;
- lower levels may add exposure;
- recent purchases may be locked by T+2;
- gaps and price limits prevent guaranteed stop execution;
- the loss expands beyond one grid step.

The recurring payoff was:

```text
many small completed-grid gains
<
fewer forced, gap, downtrend and time-exit losses + costs
```

Risk management reduced loss magnitude. It did not create positive
expectancy.

---

# 4. Data and research universe

## Initial ten-stock universe

```text
FPT, HPG, MBB, MWG, PNJ, SSI, TCB, VCB, VND, VPB
```

Trials 16–18 traded eight stocks after excluding FPT and PNJ. Those two
remained in the market-proxy calculation.

## Inputs

- Daily OHLCV, ceiling, floor and reference-price data
- Development/final split labels
- One-minute continuous-session OHLC and matched volume
- Last displayed bid/ask and available queue quantity
- Walk-forward date assignments

## Data safeguards

- Reject non-HSX or non-stock rows
- Enforce a common ticker calendar
- Quarantine unverifiable or detected reference resets
- Refuse labels crossing a partition boundary
- Reject final-test rows before parsing their price values

---

# 5. Original stock-filtering algorithm

The first multi-ticker selector used the previous 12 months to characterize
each stock in non-overlapping ten-session windows.

## Regime classification inputs

- Efficiency ratio: directional movement versus total path movement
- Ten-session price range
- Ten-session return
- Deep-downtrend frequency
- ATR20
- Median 60-session traded value

## Frozen eligibility concepts

- Sufficient history and valid windows
- Frequent oscillating or quiet sideways regimes
- Limited ordinary downtrend frequency
- Very limited deep-downtrend history
- Adequate favorable-regime frequency
- Median daily value of at least VND 10 billion
- One board lot must fit the stress budget
- No recent reset or deep-downtrend veto

The top eligible tickers were frozen for the next two-month deployment, then
reselected.

## Finding

The selector was safe but too sparse. Static pullback orders frequently never
filled; filled orders sometimes identified breakdowns rather than reversions.

---

# 6. Evolution of ticker and signal selection

| Research stage | Selection method | Finding |
|---|---|---|
| Historical regimes | Sideways/downtrend frequency | Too inactive |
| Confirmed pullback | Residual deviation plus reversal | Better timing, sparse or unstable |
| Pooled classifier | Target-before-downside probability | Enough trades, wrong OOS ordering |
| Ticker expectancy | Shrunk completed-campaign history | History too sparse |
| Dense EV ranker | Predicted return minus downside | Directional ranking, weak economics |
| Grid-capture ranker | Target capture minus inventory loss | Selected tail did not generalize |
| Fair-value rules | Median or residual equilibrium discount | More trades, persistent repricing mistaken for discount |

Ticker filtering evolved from “which stock was historically sideways?” to:

> Which current stock-specific deviation has positive expected grid economics
> after costs and downside inventory risk?

---

# 7. Point-in-time feature engine

Every daily feature ended at the signal-session close.

## Market-adjusted residual

For ticker \(i\):

\[
\epsilon_{i,t}=r_{i,t}-\beta_i r_{market,t}
\]

The market proxy was the equal-weight return of the other stocks.

## Continuous features

- Standardized five-day residual displacement
- Latest one-day residual
- 20-day residual slope
- Downside residual semivolatility
- Residual AR(1)
- 20-day market return
- Close relative to SMA50
- SMA20 relative to SMA50
- ATR20 divided by price
- Log median 60-day traded value

These features supported rules, logistic classification and pooled ridge
ranking in different trials.

---

# 8. Final market-adjusted equilibrium

Trial 18 estimated the centre from 60 daily log returns.

\[
m_t=\operatorname{mean}_{j\neq i}
\left[\log(P_{j,t}/P_{j,t-1})\right]
\]

\[
\beta_i=\frac{\operatorname{cov}(r_i,m)}
{\operatorname{var}(m)},\qquad
\epsilon_{i,t}=r_{i,t}-\beta_i m_t
\]

The cumulative residual-price path was compared with its recent 20-session
median:

\[
C=P_t\exp(S_{equilibrium}-S_t)
\]

The upward correction was capped at two ATRs.

## Finding

The ranking became directionally strong, but market adjustment did not prove
that the residual spread was stationary. Persistent company-specific
repricing was still treated as a discount.

---

# 9. Grid construction

Grid spacing adapted to short-term volatility:

\[
g=\operatorname{clamp}(0.75\times ATR20/Price,\;1.5\%,\;3.0\%)
\]

For a geometric centre \(C\):

\[
L_i=\frac{C}{(1+g)^i}
\]

The mature implementation used:

- two lower levels;
- one 100-share lot per level;
- deeper touched level receives priority;
- no geometric increase in quantity;
- hard lower boundary three steps below the centre;
- centre frozen for the campaign;
- no downward re-anchoring while inventory exists.

All derived prices use legal HSX tick rounding.

---

# 10. Entry state machine

A daily signal created a pending campaign, not an immediate purchase.

```text
Valid point-in-time signal
        ↓
Severe-downtrend veto is off
        ↓
Price touches a lower grid level
        ↓
Strictly later minute reclaims the level
        ↓
Spread, queue, volume and stress checks pass
        ↓
Buy one 100-share lot
```

The reclaim price was capped at 0.25 grid step above the touched level.

## Severe-downtrend veto

Disable new purchases when at least two are true:

1. market-proxy 20-session return ≤ −3%;
2. ticker is at least one ATR below SMA50;
3. residual slope and latest residual return are both negative.

The state was recomputed causally before each later session.

---

# 11. Per-fill target economics

After the actual buy execution price, Trial 18 calculated acquisition cash
including buy commission.

For required net profit fraction \(q\), it found the lowest legal target \(T\)
such that:

\[
NetSaleCash(T)-AcquisitionCash
\geq q\times AcquisitionCash
\]

The lot target became:

\[
\max(\text{next structural grid level},\;T)
\]

Target floors tested:

```text
0.00%, 0.50%, 0.75%, 1.00% after normal costs
```

The existing structural target already cleared 0.50%. Increasing the target
to 1.00% changed 33 of 103 fills but did not improve total P&L.

---

# 12. Minute execution model

An order could execute only when:

- continuous morning or afternoon session;
- valid best bid and ask;
- spread no greater than 40 bps;
- displayed queue covers 100 shares when queue data exist;
- 100 shares are no more than 5% of matched minute volume;
- the lot is legally tradeable under T+2;
- available state permits the action;
- at most one campaign state transition occurs in the minute.

## Modeled friction

| Component | Rate |
|---|---:|
| Buy commission | 0.15% |
| Buy execution haircut | 0.05% |
| Sell commission | 0.15% |
| Sell tax | 0.10% |
| Sell execution haircut | 0.05% |

Every mature campaign was also simulated under doubled commission and
execution haircut.

---

# 13. Settlement and inventory accounting

## T+2 treatment

- Purchased shares become tradeable at 13:00 on T+2.
- Sale cash becomes reusable at 13:00 on T+2.
- Unsettled shares cannot be sold at a target or risk boundary.
- A sold level cannot re-arm before its cash settles.
- No new lot can be added while existing inventory is unsettled.

## Campaign expiry

- Mature campaigns lasted at most seven or ten sessions.
- No new buys were permitted in the final two sessions.
- Remaining settled inventory was liquidated at the final eligible minute.
- Missing executable exit liquidity invalidated the candidate rather than
  assuming a fill.

---

# 14. Risk-management hardening

| Early weakness | Hardened implementation |
|---|---|
| Permanent base inventory | Start flat; activate temporarily |
| Increasing exposure downward | Fixed 100-share lots |
| Desired capital allocation | Explicit floor-session stress budget |
| Stop assumed executable | Bid/ask, gaps, limits and T+2 modeled |
| Unlimited campaign | Seven/ten-session expiry |
| Automatic re-anchor | Re-anchor prohibited while holding inventory |
| Trend protection after accumulation | Pre-entry and during-campaign veto |
| Corporate-action jump treated as return | Reset quarantine |
| Nominal cost assumption | Doubled-cost stress |
| One attractive backtest | Best-trade removal and fold stability gates |

Before each purchase, aggregate held plus proposed inventory had to remain
within a VND 1.5 million loss under two consecutive 7% floor sessions.

Risk controls reduced damage. They could not reverse the sign of expectancy.

---

# 15. Portfolio-selection layer

The later research ranked causal candidates and imposed:

- maximum three simultaneous campaigns;
- no same-ticker overlap;
- maximum two active tickers from one sector;
- top two new campaigns per entry day;
- ticker cooldown after exit;
- unused capacity remains cash.

## Important audit distinction

Trials 15–18 simulated campaigns individually and then imposed
overlap/concurrency rules. A production implementation should use one
consolidated ledger for:

- portfolio cash and pending settlement;
- continuous mark-to-market equity;
- aggregate exposure and participation;
- futures margin if a hedge is introduced.

---

# 16. Research and validation governance

```text
Hypothesis
→ preregistered implementation and search
→ in-sample chronological deployment folds
→ automatic advancement gates
→ conditional internal validation
→ locked final OOS
```

Advancement required sufficient campaigns, positive total and median P&L,
profit factor, doubled-cost survival, positive best-trade-removed P&L,
target gains covering other losses, temporal breadth and limited ticker
concentration.

No mature trial passed. Therefore:

- internal validation was not opened;
- final OOS remained locked;
- no live strategy was authorized.

The repository currently contains 107 automated tests.

---

# 17. Eighteen-trial progression

| Phase | Trials | Main implementation change | Finding |
|---|---:|---|---|
| Inventory control | 1–2 | Remove permanent inventory and averaging down | Lower drawdown, no edge |
| Signals and mechanics | 3–10 | Confirmation, episodic grids, sizing, re-anchor | Sparse when strict; loss-making when active |
| Formal daily optimization | 11–14 | Trend gates, ticker selector, dense models | Ranking information, no robust grid profit |
| Minute execution | 15–18 | Bid/ask, T+2, fair value, veto, target economics | Genuine cycles, still negative expectancy |

This was not one parameter search. Each numbered trial recorded a materially
changed hypothesis and its decision.

---

# 18. Mature minute results

| Trial | Campaigns / targets | Net P&L | PF | Main finding |
|---|---:|---:|---:|---|
| 15 | 22 / 12 | −VND 685,810 | 0.700 | Real grid cycles did not cover inventory exits |
| 16 | 7 / 4 | −VND 236,901 | 0.700 | Smaller universe reduced activity, not expectancy |
| 17 | 48 / 24 | −VND 1,479,791 | 0.492 | Veto helped; fair-value/reclaim still failed |
| 18 | 80 / 29 | −VND 4,254,549 | 0.300 | Market-adjusted ranking did not imply economic reversion |

Trial 18:

- Sharpe: −3.688
- realized closed-campaign MDD: 4.255%
- target gains: VND 1.619 million
- forced/time losses: VND 6.348 million
- every active fold and every ticker lost money

---

# 19. Interpretation of a possible Type II error

It remains possible that an untouched future period would be profitable.

But a profitable period could reflect:

- random sampling variation;
- a favorable regime;
- fewer severe repricing events;
- an unstable strategy whose sign changes through time.

Reliability does not mean claiming:

> “The strategy must lose in every future period.”

The reliable decision is:

> “The current evidence does not justify expecting positive after-cost
> returns, so accepting its inventory risk is not authorized.”

---

# 20. Final decision

## Reject

Long-only single-stock grid trading on this research path.

## Rerun once

Frozen Trial 18 only as a clean infrastructure and reproducibility audit—not
as another economic search.

## Preserve

Do not open the old holdout to rescue further long-only variants.

## Research separately

A hedged, stationarity-first stock/index residual using new untouched data.

## Scientific ordering

1. Prove residual stationarity and hedge-ratio stability.
2. Test one entry and one exit after all stock and hedge costs.
3. Implement one consolidated stock/futures portfolio ledger.
4. Consider a grid only if the underlying spread trade already has positive
   expectancy.

---

# 21. Contribution of the project

The strongest contribution is not a profitable equity curve.

It is a research and execution system that:

- implemented realistic Vietnamese-market constraints;
- separated signal quality from execution and risk;
- found a persistent negative-convexity failure;
- resisted opening the holdout after failed development results;
- prevented deployment of an intuitively attractive but repeatedly
  unfavorable strategy.

> Missing a possible opportunity is preferable to risking capital in a
> strategy whose positive expectancy has not been demonstrated.

