# Sector-Rotation Grid V1 — Diagnostic OOS Result

## Research status

The January–June 2025 internal OOS block was opened once after the development
gate had failed. Its purpose was **loss diagnosis, not performance
confirmation**.

The following remained unchanged from the 2024 optimization:

- 20-session selector horizon;
- four geometric grid levels;
- 0.75 ATR spacing multiplier;
- three independent 100-share cells per level;
- 45% maximum allocation to each of two selected tickers;
- execution, fee, tax, liquidity and T+2 assumptions.

The frozen configuration hash was:

```text
96d02d50e5df00582c5eba186202570f7b49bcf3d74bfec36e4aec8c5286e9ab
```

The July 2025 onward final holdout remains locked.

## OOS result

| Metric | Result |
|---|---:|
| Starting capital | VND 1,000,000,000 |
| Ending equity | VND 987,329,572 |
| Net P&L | **−VND 12,670,428** |
| Net return | **−1.267%** |
| Profit factor | **0.0267** |
| Maximum drawdown | **−1.267%** |
| Completed sales | 60 |
| Active rotations | 4 of 6 |
| Equal-weight proxy return | +13.393% |
| Active return | −14.660% |

There was no data leakage:

```text
selection/deployment overlap count = 0
all rotations flat and settled      = true
account reconciliation difference   = VND 0
```

## Account reconciliation

```text
Gross trading P&L     -VND 11,820,000
Commission            -VND    642,258
Sell tax              -VND    208,170
-------------------------------------
Net realized P&L      -VND 12,670,428
Reconciliation error               0
```

Execution friction was VND 505,000. It is already embedded in the execution
prices and therefore is not subtracted again in the reconciliation.

Unlike the 2024 optimization loss, the OOS failure was not primarily caused
by fees. Gross trading P&L was already strongly negative before commission
and tax.

## Loss by exit mechanism

| Exit type | Sales | Net P&L | Average |
|---|---:|---:|---:|
| Normal grid target | 12 | **+VND 347,841** | +VND 28,987 |
| Severe-risk exit | 48 | **−VND 13,018,269** | −VND 271,214 |

Every normal grid target was profitable, but every risk exit lost money.

The average risk-exit loss was approximately:

```text
VND 271,214 / VND 28,987 ≈ 9.36 times one average grid win
```

The strategy therefore required more than nine normal wins to recover one
average risk-exit loss before considering missed opportunity versus the
benchmark.

## Loss by rotation

| Rotation | Selected stocks | Net P&L | Mechanism |
|---|---|---:|---|
| January 2025 | VPB, MBB | −VND 2,789,463 | 24 risk exits |
| February 2025 | VPB, VCB | +VND 295,890 | 9 grid targets |
| March 2025 | MBB, VPB | +VND 51,951 | 3 grid targets |
| April 2025 | VCB, TCB | **−VND 10,228,806** | 24 risk exits |
| May 2025 | None | VND 0 | Market veto active |
| June 2025 | None | VND 0 | Market veto active |

April caused approximately 81% of the complete OOS loss.

In April:

- TCB grid purchases averaged approximately VND 26,550 and were liquidated
  around VND 23,900, losing VND 3.30 million;
- VCB grid purchases averaged approximately VND 59,575 and were liquidated
  around VND 54,025, losing VND 6.93 million.

The purchases occurred on 3–4 April. T+2 and market execution constraints
meant liquidation occurred on 8–9 April, after substantial further declines.

## Loss by ticker

| Ticker | Net P&L |
|---|---:|
| VCB | **−VND 6,670,830** |
| TCB | −VND 3,299,496 |
| MBB | −VND 2,191,209 |
| VPB | −VND 508,893 |

The loss was concentrated in the bank sector because every active OOS
rotation selected banks. No securities-sector rotation was activated.

## What the optimization already indicated

All twelve 2024 configurations lost money:

| Optimization statistic | Result |
|---|---:|
| Configurations tested | 12 |
| Profitable configurations | **0** |
| Best net P&L | −VND 677,936 |
| Worst net P&L | −VND 7,184,350 |

For the best 2024 configuration:

```text
Normal grid targets       +VND 5,020,256
Risk exits                -VND 4,801,767
Scheduled wind-downs      -VND   896,425
```

Gross trading P&L remained positive at VND 1.43 million, but commission and
tax were VND 2.11 million. Thus:

- in ordinary conditions, the gross grid edge was too small relative to
  transaction costs;
- in abrupt breakdowns, risk-exit losses overwhelmed the entire grid edge.

## Principal diagnosis

The selector identified recent residual oscillation but could not establish
that the next month would remain mean reverting.

The sequence was:

```text
Recent oscillation
        ↓
Ticker selected and grid activated
        ↓
Abrupt new downtrend begins after selection
        ↓
Multiple lower cells fill
        ↓
Inventory is locked by T+2 while price continues falling
        ↓
Risk exit becomes executable only after a larger loss
```

The market gate was not completely ineffective. It correctly held the
strategy in cash during May and June. Its weakness was timing: it reacted
after the April decline rather than predicting it before the grid accumulated
inventory.

## Economic conclusion

Three distinct findings are now visible:

1. **Small-win economics:** successful grid targets earned only about VND
   29,000 per 100-share cell after costs.
2. **Asymmetric loss:** an average risk exit lost about 9.36 times one target
   win.
3. **Lagging regime protection:** the severe-downtrend veto prevented later
   entries but could not protect inventory from a regime change beginning
   immediately after selection.

This is the same negative-convexity mechanism found in the previous research,
now reproduced in a clean selector/in-sample/optimization/OOS sequence.

## Diagnostic artifacts

### OOS charts

- `data/sector_rotation_grid/out_of_sample/charts/equity_vs_benchmark.svg`
- `data/sector_rotation_grid/out_of_sample/charts/drawdown.svg`
- `data/sector_rotation_grid/out_of_sample/charts/monthly_returns.svg`
- `data/sector_rotation_grid/out_of_sample/charts/pnl_attribution.svg`

### Loss-attribution charts

- `data/sector_rotation_grid/out_of_sample/diagnostics/pnl_by_purpose.svg`
- `data/sector_rotation_grid/out_of_sample/diagnostics/pnl_by_ticker.svg`
- `data/sector_rotation_grid/out_of_sample/diagnostics/pnl_by_level.svg`
- `data/sector_rotation_grid/optimization_diagnostics/configuration_net_pnl.svg`

### Tables

- `data/sector_rotation_grid/out_of_sample/diagnostics/pnl_by_purpose.csv`
- `data/sector_rotation_grid/out_of_sample/diagnostics/pnl_by_ticker.csv`
- `data/sector_rotation_grid/out_of_sample/diagnostics/pnl_by_level.csv`
- `data/sector_rotation_grid/out_of_sample/diagnostics/pnl_by_rotation.csv`
- `data/sector_rotation_grid/optimization_diagnostics/configuration_map.csv`
