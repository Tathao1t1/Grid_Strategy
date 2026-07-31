# Sector-Rotation Grid V1 — Development Result

## Original development decision

**Stop at development. Do not open the January–June 2025 internal OOS block.**

The selector-development, in-sample and optimization stages were run in their
reserved chronological blocks with zero selection/deployment overlap. The
2024 optimization gate failed because every tested grid configuration lost
money after modeled costs and the best configuration had profit factor below
one.

The July 2025 onward final holdout remains locked and was not numerically
parsed.

## Subsequent diagnostic authorization

After this decision was recorded, the user explicitly authorized opening the
January–June 2025 block once to diagnose the loss mechanism rather than to
claim performance confirmation. The frozen configuration was not changed.
The diagnostic result is documented in
`SECTOR_ROTATION_GRID_V1_DIAGNOSTIC_OOS_RESULT.md`.

The July 2025 onward final holdout remains locked.

## Frozen research sequence

| Stage | Dates | Use |
|---|---|---|
| Selector development | 2022-01-04–2022-12-30 | Select indicator horizon |
| In-sample trading | 2023-01-03–2023-12-29 | Test the initial hypothesis |
| Grid optimization | 2024-01-02–2024-12-31 | Select grid configuration |
| Internal OOS | 2025-01-02–2025-06-30 | Subsequently opened once for diagnosis |
| Final holdout | 2025-07-14 onward | Locked |

At every rotation:

```text
maximum feature date < first deployment date
```

The rotation audit recorded zero violations.

## Implemented selector

The study is limited to two sectors with at least two constituents:

- banks: MBB, TCB, VCB and VPB;
- securities: SSI and VND.

The selector uses:

- leave-one-out market-adjusted residual returns;
- residual efficiency ratio;
- residual amplitude after the modeled round-trip cost hurdle;
- observed reversal consistency;
- severe stock and market downtrend vetoes;
- daily traded-value and minute-spread liquidity gates.

Eligible tickers receive an equal-rank composite of low efficiency, high net
amplitude and high reversal consistency. A sector requires at least two
eligible tickers. The top sector and top two tickers are frozen for the next
calendar month.

Because no official VN-Index series exists in the repository, this version
uses an explicitly labelled equal-weight six-stock research proxy. It must not
be described as VN-Index performance.

## Selector-development result

| Horizon | Active rotations | Tickers evaluated | Median future quality | Positive fraction |
|---:|---:|---:|---:|---:|
| 20 sessions | 7 | 14 | 3.458% | 71.4% |
| 40 sessions | 4 | 8 | −1.857% | 50.0% |
| 60 sessions | 1 | 2 | −0.472% | 50.0% |

The frozen selector horizon was **20 sessions**. The market veto was excluded
only from this horizon-comparison calculation because the 2022 market veto
otherwise left too few observations; future downside still penalized selector
quality. The market veto remained active in all trading backtests.

## In-sample result: 2023

Starting capital was VND 1 billion.

| Metric | Result |
|---|---:|
| Net P&L | **+VND 618,617** |
| Net return | **+0.0619%** |
| Profit factor | **1.221** |
| Maximum drawdown | **−0.156%** |
| Completed sales | **83** |
| Active rotations | **7 of 12** |
| Equal-weight proxy return | **+33.34%** |
| Active return | **−33.28%** |

Account reconciliation:

```text
Gross trading P&L     +VND 2,000,000
Commission            -VND 1,035,293
Sell tax              -VND   346,090
-------------------------------------
Net realized P&L      +VND   618,617
Reconciliation error              0
```

The strategy was slightly profitable in absolute terms but dramatically
underperformed passive exposure during the strong benchmark year.

## Optimization result: 2024

The compact optimization varied:

- three or four geometric levels;
- 0.75, 1.00 or 1.25 ATR spacing multiplier;
- three or five independent 100-share cells per level.

All twelve configurations were negative. The least-negative configuration
used four levels, 0.75 ATR spacing and three cells per level.

| Metric | Best optimization result |
|---|---:|
| Net P&L | **−VND 677,936** |
| Net return | **−0.0678%** |
| Profit factor | **0.881** |
| Maximum drawdown | **−0.397%** |
| Completed sales | **137** |
| Active rotations | **10 of 12** |
| Equal-weight proxy return | **+11.19%** |
| Active return | **−11.26%** |

Account reconciliation:

```text
Gross trading P&L     +VND 1,430,000
Commission            -VND 1,580,431
Sell tax              -VND   527,505
-------------------------------------
Net realized P&L      -VND   677,936
Reconciliation error              0
```

The economic failure is clear: the grid produced positive gross trading P&L,
but that gross edge was smaller than commission and tax.

## Development gate

The pre-OOS gate required:

- positive in-sample return;
- positive optimization return;
- optimization profit factor above one;
- at least six active optimization rotations;
- exact account reconciliation.

The optimization return and profit-factor conditions failed. The code
therefore rejects the OOS command even when given the correct frozen
configuration hash.

## Charts

### In-sample

- `data/sector_rotation_grid/in_sample/charts/equity_vs_benchmark.svg`
- `data/sector_rotation_grid/in_sample/charts/drawdown.svg`
- `data/sector_rotation_grid/in_sample/charts/monthly_returns.svg`
- `data/sector_rotation_grid/in_sample/charts/pnl_attribution.svg`

### Optimization

- `data/sector_rotation_grid/optimization_best/charts/equity_vs_benchmark.svg`
- `data/sector_rotation_grid/optimization_best/charts/drawdown.svg`
- `data/sector_rotation_grid/optimization_best/charts/monthly_returns.svg`
- `data/sector_rotation_grid/optimization_best/charts/pnl_attribution.svg`
