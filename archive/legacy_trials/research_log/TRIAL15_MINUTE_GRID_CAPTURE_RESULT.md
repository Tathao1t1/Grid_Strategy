# Trial 15 result: minute-executed grid capture

## Decision

**Reject Trial 15. Internal validation and final minute OOS remain locked.**

Trial 15 used the existing one-minute bid/ask archive and generated genuine
grid target cycles, but none of the 48 pre-registered configurations made
money in sample.

## Execution implemented

Unlike Trials 6–14, Trial 15 did not infer execution from daily OHLC. Each
campaign was replayed chronologically through one-minute rows with:

- displayed bid and ask;
- matched minute volume and a 5% participation cap;
- a 40-bps maximum normal spread;
- displayed queue coverage when available;
- adverse execution haircut, commissions and sell tax;
- T+2 share and cash settlement at 13:00;
- no same-minute re-entry after a fill;
- a frozen repeated grid cell;
- catastrophic shutdown and ten-session expiry.

The 2022 archive lacks queue quantities. Before any economic output existed,
the pre-registration recorded a fallback to the already-declared 5% matched
volume cap for those legacy rows. Queue coverage remained mandatory from 2023
onward.

## Dense minute sample

| Fold | Training minute labels |
|---|---:|
| wf_01 | 298 |
| wf_02 | 561 |
| wf_03 | 952 |
| wf_04 | 1,334 |
| wf_05 | 1,526 |
| wf_06 | 1,528 |
| wf_07 | 1,393 |
| wf_08 | 1,221 |
| wf_09 | 1,188 |

Every label was generated twice on the same minute path under normal and
doubled costs.

## Search result

| Measure | Result |
|---|---:|
| Pre-registered configurations | 48 |
| Positive nominal-P&L configurations | **0** |
| Configurations with PF >= 1.20 | **0** |
| Positive doubled-cost configurations | **0** |
| Positive after best campaign removed | **0** |
| Selected-campaign range | 6–22 |
| Grid-cycle campaign range | 1–12 |
| Configurations with >=20 campaigns | 6 |
| Configurations with >=10 cycle campaigns | 6 |
| Positive score-quintile cycle spread | **0** |

The minute-derived models ranked future cycle completion in the wrong
direction out of sample. More selective score buffers reduced activity but
did not improve economics.

## Least-negative configuration

```json
{
  "ridge_penalty": 10,
  "minimum_target_probability": 0.25,
  "risk_penalty": 1.0,
  "score_buffer": 0.0,
  "top_k": 3
}
```

The `0.40` probability variant produced the same selected set.

| Metric | Result |
|---|---:|
| Campaigns | 22 |
| Campaigns completing a grid cycle | **12** |
| Median campaign P&L | +VND 14,867 |
| Net P&L | **−VND 685,810** |
| Profit factor | **0.700** |
| Doubled-cost P&L | **−VND 1,197,870** |
| P&L after best campaign removed | **−VND 1,016,085** |
| Target-cycle gains | +VND 1,645,138 |
| Forced/time losses | **−VND 2,334,550** |
| Grid economic P&L | **−VND 689,412** |
| Positive active-fold fraction | 25% |
| Score-quintile cycle-rate spread | −7.90 percentage points |
| Minute control P&L | −VND 606,678 |

The median was positive and more than half the campaigns completed a target,
but the remaining inventory exits were substantially larger. The selected
model also underperformed the causal minute-executed control by VND 79,132.

## Interpretation

Minute data resolves Trial 14's zero-target ambiguity. Grid crossings were
real and executable under the modeled spread, liquidity and settlement
constraints. The core negative-convexity problem nevertheless remained:

```text
many target-cycle gains
<
fewer forced/time inventory losses + costs
```

The continuous daily features that weakly ranked daily-bar targets did not
rank minute-executed cycles chronologically. This is evidence against the
specific signal-and-grid combination, not evidence that the minute archive
was unused or that targets never occurred.

## Data scope and governance

- Internal validation (`wf_10`–`wf_15`): **not run**
- Locked minute OOS (`2025-07-14`–`2026-06-30`): **not opened**
- July 2026: excluded because audit rows had previously been inspected
- Final lock: **not created**
- Live deployment: **not authorized**

These files are one-minute aggregates, not raw event-level ticks. They retain
minute OHLC, last bid/ask, volume, spread and event count, but cannot establish
queue evolution or event ordering inside one minute.

## Reproduction

```bash
python3 study_trial15_minute_grid_capture.py --optimize-validate
python3 -m unittest discover -s tests
```

Primary outputs:

- `data/trial15_minute_grid_capture/development/development_report.json`
- `data/trial15_minute_grid_capture/development/minute_optimization.csv`
- `data/trial15_minute_grid_capture/development/is_models.csv`

