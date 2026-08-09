---
title: "Grid Trading for Vietnamese Equities"
subtitle: "From sideways-stock intuition to a risk-governed rejection"
date: "Short presentation"
---

# Grid Trading for Vietnamese Equities

## My implementation journey and the questions that remain

**Requirement:** implement a grid strategy for one or more Vietnamese stocks  
**Result:** complete implementation, but no evidence supporting live
long-only deployment

---

# 1. Original intuition and hypothesis

## Intuition

Some liquid stocks appear to spend more time moving sideways than trending
strongly downward. A grid could repeatedly buy low and sell higher inside
those ranges.

## Initial hypothesis

> If I select the stocks with the most frequent sideways conditions and the
> least deep-downtrend history, then a long-only grid should earn enough
> repeated cycle profits to cover fees and occasional exits.

My first selected stocks were **VCB and VPB**.

---

# 2. My original stock-filtering algorithm

For each ticker, I divided the previous history into ten-session windows.

## Sideways and risk measurements

- Efficiency ratio: net movement divided by total path movement
- Ten-session trading range
- Uptrend and downtrend frequency
- Deep-downtrend frequency
- ATR20 as a volatility measure
- Median 60-session traded value
- Corporate-action/reference-price validity

## Selection logic

```text
Frequent oscillating/quiet sideways windows
+ adequate liquidity
+ acceptable volatility
− frequent downtrends
− deep-downtrend history
= ticker score
```

The highest-ranked stocks became the grid universe.

---

# 3. First implementation: grid VCB and VPB

## Grid placement

- Previous official close as the weekly centre
- Dynamic range: centre ± 2 ATR14
- Eight geometric grid intervals
- Buy at lower levels and sell one step higher
- 100-share board lots
- 30% base inventory
- 50% capital reserved for lower-grid buying
- 20% cash reserve
- Maximum invested ratio of 80%

## Execution modeled

- Commission, sell tax and adverse execution
- Minute-volume participation
- T+2/T+2.5 inventory and cash settlement
- Downtrend pause, hard stop and forced liquidation

---

# 4. First failure: forced exits dominated grid profits

The grid produced many profitable sales, but accumulated its largest inventory
during persistent declines.

Example from the first major fold:

| Component | Result |
|---|---:|
| Normal grid-sale P&L | +VND 30.5 million |
| Risk-exit P&L | **−VND 101.4 million** |
| Net return | **−7.09%** |
| Profit factor | **0.316** |

Across the first design, 13 of 14 valid folds lost money.

## Lesson

> The problem was not simply where to place the forced exit. The strategy had
> already accumulated negatively convex long inventory before the exit could
> act.

---

# 5. Second idea: rotate between tickers

I stopped assuming that one ticker would always be appropriate for grid
trading.

## Rotation algorithm

```text
Previous 12 months
→ classify each ticker's market conditions
→ rank the ten-stock universe
→ select up to two tickers
→ freeze them for the next two months
→ close and settle
→ reselect
```

The intention was:

1. identify the current sideways regime;
2. trade temporarily for one to two months;
3. switch ticker when its regime changed.

## Result

The rules became safer but too inactive:

- 14 valid rotations
- only six active rotations
- only four completed targets
- compounded return: **−1.408%**
- profit factor: **0.288**

Static pullback levels often did not fill; when they did, some were breakdowns
rather than reversions.

---

# 6. Third idea: require mean-reversion evidence

I changed from historical sideways selection to current relative-price
displacement.

## Market-adjusted signal

\[
\epsilon_{i,t}=r_{i,t}-\beta_i r_{market,t}
\]

The market proxy was the equal-weight return of the other stocks.

## Mean-reversion features

- Five-day residual z-score
- Latest residual return
- Residual slope and autocorrelation
- Downside residual volatility
- Market return
- Close versus SMA50
- SMA20 versus SMA50
- ATR and liquidity

## Entry concept

```text
Ticker-specific downside deviation
→ residual begins reversing
→ price confirms the reversal
→ activate a temporary grid
```

I also tested pooled prediction, ticker selection, expected-return ranking and
separate prediction of target capture versus inventory loss.

## Finding

The models sometimes ranked target frequency correctly, but the selected
trades still had negative after-cost expectancy.

---

# 7. Final hardened implementation

## Grid and entry

- Market-adjusted or rolling fair-value centre
- ATR-dependent geometric spacing of 1.5%–3.0%
- One or two fixed 100-share levels
- Touch a lower level, then reclaim it in a later minute
- No geometrically increasing quantity
- No downward re-anchoring while inventory is held
- Per-fill target must preserve minimum profit after costs

## Severe-downtrend veto

Disable new buying when at least two are true:

1. market 20-session return ≤ −3%;
2. ticker is at least one ATR below SMA50;
3. residual slope and latest residual return are negative.

## Risk and execution

- One-minute bid/ask simulation
- Maximum spread of 40 bps
- Maximum 5% minute-volume participation
- Queue coverage when available
- Commission, sell tax and adverse execution
- T+2 share and sale-cash settlement
- No adding while inventory is unsettled
- Two-floor aggregate stress budget
- Hard-lower shutdown and seven-session expiry
- Maximum three simultaneous campaigns
- Corporate-action/reset quarantine
- Doubled-cost stress test

---

# 8. What the mature trials found

| Trial | Main adjustment | Campaigns / targets | Net P&L | PF |
|---|---|---:|---:|---:|
| 15 | Minute-executed grid | 22 / 12 | −VND 685,810 | 0.700 |
| 16 | Remove FPT and PNJ | 7 / 4 | −VND 236,901 | 0.700 |
| 17 | Fair centre, reclaim and veto | 48 / 24 | −VND 1,479,791 | 0.492 |
| 18 | Market-adjusted equilibrium and economic targets | 80 / 29 | −VND 4,254,549 | 0.300 |

Trial 18:

- target gains: +VND 1.619 million;
- forced/time losses: −VND 6.348 million;
- every active fold lost money;
- every ticker lost money.

## Repeated finding

```text
many small completed-grid gains
<
fewer forced, gap, downtrend and time-exit losses + costs
```

---

# 9. Type II error and the decision

It remains possible that the strategy is a false negative and would make money
in a different out-of-sample regime. Quantitative research cannot eliminate a
Type II error.

But the decision costs are asymmetric:

| Error | Cost |
|---|---|
| Reject a genuinely profitable strategy | Miss an opportunity |
| Accept a negative-convexity strategy | Risk capital after repeatedly unfavorable evidence |

Therefore:

> I reject live long-only deployment. This does not prove that the strategy
> must lose in every future period; it means the evidence is insufficient to
> justify accepting its inventory risk.

The old holdout remains unopened.

---

# 10. Guidance I need

## 1. Hedging

- Should the next object be a stock/index or stock/sector residual?
- Which executable hedge is appropriate?
- How should the hedge ratio, futures margin, basis and contract roll be
  modeled?
- How should stock T+2 interact with the hedge?

## 2. Exit design

- Should exit be based on spread convergence rather than stock price?
- How should I combine statistical stop, time stop and portfolio loss limit?
- How should an exit operate while the stock leg remains unsettled?

## 3. Market-condition identification

- How should I prove that a residual is stationary?
- What half-life and structural-break tests are appropriate?
- Should the strategy use explicit trend/sideways regimes or continuous
  probabilities?
- What adjusted VN-Index and sector data are necessary?

## 4. Research sequence

My proposed next program is separate from the rejected long-only grid:

```text
new untouched adjusted data
→ prove spread stationarity
→ test one hedged entry and one exit after costs
→ implement one marked-to-market portfolio ledger
→ consider a grid only if the underlying spread trade is profitable
```

---

# Closing message

The project successfully implemented:

- ticker filtering;
- causal mean-reversion signals;
- dynamic grid construction;
- minute execution;
- Vietnamese fees, tax and T+2 settlement;
- portfolio and campaign risk controls;
- chronological validation locks.

The strongest contribution was preventing deployment of an intuitively
attractive but repeatedly unfavorable long-only strategy.

