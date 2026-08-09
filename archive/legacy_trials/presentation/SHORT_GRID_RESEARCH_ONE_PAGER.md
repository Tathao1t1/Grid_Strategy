# Grid Trading Research: Short Presentation Guide

## 1. Original intuition

Grid trading should profit from repeated price oscillations in sideways stocks. I therefore started by trying to identify Vietnamese stocks that spent the most time moving sideways and experienced the fewest deep downward trends.

## 2. Initial hypothesis and implementation

I ranked a universe of ten stocks using rolling measures of price efficiency, trading range, volatility, trend direction, downside frequency, and liquidity. VCB and VPB were selected for the first implementation.

For each stock, I placed a geometric grid around the previous official close. The range was volatility-adjusted using ATR. The strategy bought below the centre and sold when the price returned toward higher grid levels, while respecting transaction costs, cash and inventory limits, T+2 settlement, and forced exits.

## 3. First failure: the forced-exit problem

The individual grid cycles could make money, but losses during downward trends were much larger than the small profits collected during sideways periods. Forced exits and accumulated inventory dominated the result.

The key weakness was therefore structural: a long-only grid repeatedly buys as price falls and becomes most exposed when the original mean-reversion assumption is failing.

## 4. Rotation hypothesis

I next expanded the strategy to the full stock universe. At each selection date, the algorithm:

1. identified the recent market condition;
2. ranked the most suitable sideways stocks;
3. traded one or two selected stocks for approximately one to two months;
4. closed the positions, settled the portfolio, and selected new stocks.

This improved diversification across opportunities, but it did not eliminate the same downside-inventory risk.

## 5. Mean-reversion and risk-management hypothesis

Later trials added stricter mean-reversion evidence and execution controls:

- market-adjusted stock residuals and short-horizon reversal signals;
- trend and severe-downtrend vetoes;
- ATR-based dynamic grids and per-fill profit targets;
- limited inventory, no unlimited averaging down, and time stops;
- realistic minute-level fills, fees, taxes, spread, liquidity, and T+2 settlement.

These changes either produced too few trades or still produced negative after-cost expectancy. Loosening the gates increased execution but also reintroduced more losing exposure.

## 6. Main finding and Type II error

It remains possible that the strategy is genuinely profitable and this research produced a false negative—a Type II error. However, the costs of the two possible errors are asymmetric:

- rejecting a profitable strategy means missing an opportunity;
- accepting a repeatedly negative, unhedged strategy means risking real capital.

The evidence therefore supports rejecting this long-only implementation for deployment, while acknowledging that quantitative research cannot completely eliminate false negatives.

## 7. Guidance requested

The next research question is not how to add another grid rule. I need professional guidance on:

- **Hedging:** Can stock exposure be hedged with a VN30 or VN-Index-related instrument, and how should hedge size, basis risk, futures margin, and T+2 settlement be modelled?
- **Exit design:** Should exits depend on residual breakdown, drawdown, time, inventory, or a combination—and how can the rule avoid converting many small wins into a few large losses?
- **Market-condition identification:** What evidence is sufficient to establish that a stock or market-adjusted residual is stationary and mean reverting before capital is committed?

The proposed next path is to research a hedged stock/index residual separately, first prove that a simple single-entry spread trade has positive after-cost expectancy, and only then test whether a grid improves it.

## Closing message

The research did not prove that every grid strategy is impossible. It showed that stock filtering, rotation, dynamic grids, mean-reversion filters, and hardened risk controls were not sufficient to overcome the negative convexity of this unhedged long-only design.
