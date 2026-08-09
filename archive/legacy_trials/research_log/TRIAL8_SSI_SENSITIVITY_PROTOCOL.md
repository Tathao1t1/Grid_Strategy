# Trial 8 exploratory protocol: SSI gate and lot-size sensitivity

## Status and purpose

Trial 8 is an exploratory development-data sensitivity analysis requested
after Trial 7 was opened. It is not an independent validation and cannot
authorize live trading or unlock final-test data.

The objective is to answer:

1. Does a broader SSI activation rule produce enough independent episodes?
2. Does any broader rule retain positive economics after costs?
3. Does buying 200 or 300 shares change the edge, or merely scale risk?

## Data

- Ticker: SSI only
- Dates: all rows labelled `development`
- Final-test numeric prices: not parsed
- Candidate dates: deduplicated by calendar date
- Campaign paths: must finish inside development data
- Campaigns: non-overlapping, followed by a five-session cooldown

Because these dates have already informed earlier trials, results are
exploratory and selection-biased.

## Gate variants

All variants retain liquidity, ATR, reference-reset and market-proxy controls.

### Strict

```text
residual z5 <= -0.75
residual return 1 > 0
close > previous close
market-proxy return 5 > -5%
```

### Moderate

```text
residual z5 <= -0.50
residual return 1 > 0
close > previous close
market-proxy return 5 > -5%
```

### Loose confirmation

```text
residual z5 <= -0.50
(residual return 1 > 0 OR close > previous close)
market-proxy return 5 > -5%
```

The grid, settlement, costs, gap treatment, second-level confirmation,
three-step hard lower and 15-session expiry remain identical to Trial 7.

## Lot sizes

Each gate is run with equal per-level quantities of:

```text
100, 200 and 300 shares
```

Changing quantity cannot improve percentage expectancy in this daily model.
It is included to show exact VND reward and risk scaling. If economics are
equivalent, the smallest lot is preferred.

## Diagnostics

Each of the nine variants reports:

- candidate and independent episode count;
- target sales and lower-level fills;
- total and median net P&L;
- profit factor;
- doubled-cost P&L and profit factor;
- worst episode;
- P&L after removing the best episode;
- target gains versus risk/time losses;
- maximum modeled inventory notional;
- whether the worst episode exceeds 1% of VND 100 million.

## Exploratory viability screen

A variant is merely `exploratory_viable` when it has:

- at least 20 independent episodes;
- positive total and median P&L;
- profit factor at least 1.20;
- positive doubled-cost P&L;
- positive P&L after removing its best episode;
- target gains covering risk/time losses;
- worst episode no worse than -1% of VND 100 million.

Failure is `exploratory_not_viable`. Passing would justify a new
preregistered prospective trial, not live deployment.

