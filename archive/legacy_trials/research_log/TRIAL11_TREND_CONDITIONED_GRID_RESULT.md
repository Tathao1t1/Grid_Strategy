# Trial 11 optimized trend-conditioned grid result

## Decision

- Status: `no_in_sample_configuration`
- Parameter configurations evaluated: 216
- Eligible in-sample configurations: 0
- Internal validation run: no
- Final OOS run: no
- Final OOS configuration lock created: no

Trial 11 followed the canonical assessed pipeline but stopped at the
predeclared in-sample gate. The final-test period remains untouched.

## Hypothesis tested

A temporary one- or two-level grid would buy confirmed short-term residual
pullbacks only when:

- the ticker remained above SMA50;
- SMA20 remained above SMA50;
- the leave-one-out market 20-session return was positive;
- the residual and closing price had started reversing.

The 216 configurations varied the market threshold, residual threshold, ATR
spacing, lower-level availability, downside steps and maximum duration.

## Search result

Across all 216 configurations:

```text
positive total in-sample P&L                 0
profit factor at least 1.10                  0
positive median campaign P&L               110
at least 25 campaigns                       132
```

Thus activity and median trade behavior were not sufficient. Tail exits and
costs made every configuration negative in aggregate.

## Best observed configuration

The least-negative configuration by total P&L was:

```json
{
  "market_return20_min": 0.02,
  "residual_z_max": -1.0,
  "spacing_atr_multiplier": 1.25,
  "lower_level_enabled": false,
  "stop_steps": 3,
  "maximum_horizon": 15
}
```

Its in-sample diagnostics were:

| Metric | Result |
|---|---:|
| Independent campaigns | 18 |
| Total P&L | -VND 135,289 |
| Median campaign P&L | +VND 35,512.5 |
| Profit factor | 0.8703 |
| Doubled-cost P&L | -VND 480,507 |
| P&L after best campaign removed | -VND 414,973 |
| Positive active half-years | 25% |

It failed sample, aggregate P&L, profit-factor, doubled-cost, best-removal and
temporal-stability requirements.

## Best-configuration ticker diagnostics

| Ticker | In-sample P&L |
|---|---:|
| SSI | +182,555 |
| VCB | +102,474 |
| MWG | +62,222 |
| MBB | +58,186 |
| HPG | -14,096 |
| VND | -137,602 |
| VPB | -189,072 |
| PNJ | -199,956 |

These values are diagnostics opened after the failed pooled search. Selecting
only the positive names now would be a new, post-result ticker-selection
hypothesis. Most positive ticker totals also contain only a few campaigns and
cannot be presented as independent evidence.

## Assessment interpretation

Trial 11 demonstrates the required research sequence:

1. **Hypothesis:** pullback mean reversion conditional on positive trend.
2. **In-sample implementation:** realistic grid, settlement and costs.
3. **Optimization:** one declared 216-configuration search.
4. **Gate decision:** no configuration met the in-sample requirements.
5. **Internal validation:** correctly not opened.
6. **Final OOS:** correctly remained locked.

This is a valid negative experimental result. It would be invalid to choose
the least-negative configuration, loosen its gates and call internal
validation or final OOS a confirmation.

## Reproduction

```bash
python3 -m unittest discover -s tests -p 'test*.py' -v
python3 study_trial11_trend_grid.py --optimize-validate
```

All 66 repository tests passed.

