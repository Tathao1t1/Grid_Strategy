# Trial 14 result: dense grid-capture ranker

## Decision

**Reject Trial 14. Internal validation and final OOS remain locked.**

None of the 48 pre-registered configurations passed the in-sample gates. Most
importantly, none of their selected campaigns completed a normal grid target.

## What was tested

Trial 14 retained Trial 13's dense, point-in-time feature rows but replaced
general return prediction with three grid-specific targets:

1. probability of completing the normal grid target;
2. expected after-cost normal target capture;
3. expected non-target inventory loss.

The selection score was predicted capture minus a declared multiple of
predicted inventory loss. Profitable trend exits could contribute to reported
portfolio P&L, but could not count as predicted or realized grid capture.

## Dense target availability

Normal targets were not absent from the deployment universe:

| Fold | Dense observations | Normal targets | Target rate |
|---|---:|---:|---:|
| wf_01 | 206 | 41 | 19.9% |
| wf_02 | 293 | 43 | 14.7% |
| wf_03 | 272 | 143 | 52.6% |
| wf_04 | 144 | 112 | 77.8% |
| wf_05 | 146 | 28 | 19.2% |
| wf_06 | 0 | 0 | — |
| wf_07 | 121 | 94 | 77.7% |
| wf_08 | 261 | 129 | 49.4% |
| wf_09 | 132 | 23 | 17.4% |

The issue was prospective selection, not a complete absence of historical
target events.

## Search result

| Measure | Result |
|---|---:|
| Configurations | 48 |
| Positive target-rate quintile spread | **48 / 48** |
| Selected-campaign range | 1–8 |
| Configurations with at least 20 campaigns | **0** |
| Selected normal targets | **0 for every configuration** |
| Positive nominal-P&L configurations | 3 |
| Configurations with PF >= 1.20 | 3 |
| Positive doubled-cost P&L | **0** |
| Positive after best trade removed | **0** |
| Positive grid target gains minus other losses | **0** |

The score ranked normal-target frequency directionally across all dense
observations, but the small positive-score tail chosen for execution did not
generalize chronologically.

## Best nominal configuration

```json
{
  "ridge_penalty": 100,
  "minimum_target_probability": 0.45,
  "risk_penalty": 1.0,
  "score_buffer": 0.0,
  "top_k": 1
}
```

| Metric | Result |
|---|---:|
| Campaigns | 4 |
| Normal grid targets | **0** |
| Net P&L | **+VND 131,694** |
| Median P&L | −VND 6,926 |
| Profit factor | 1.585 |
| Doubled-cost P&L | **−VND 16,379** |
| P&L after best campaign removed | **−VND 164,013** |
| Normal target gains | **VND 0** |
| Non-target losses | VND 225,002 |
| Maximum ticker positive contribution | 82.9% |
| Entry years | 1 |

Three of the four campaigns exited through trend shutdown; the other suffered
a non-target loss. The positive aggregate came primarily from one profitable
FPT trend exit. It is not evidence of profitable grid capture.

## Interpretation

Trial 14 separates statistical ranking from executable grid economics:

- the continuous features contained information about target frequency across
  the full candidate pool;
- the model's rare positive predicted grid-EV observations were poorly
  calibrated across time;
- ordinary target opportunities did not survive the combined probability,
  capture and inventory-loss decision rule;
- nominal profits again came from non-grid exits and were not robust to costs
  or removal of the best observation.

Loosening the sample or robustness gates would not repair the central result:
there were zero realized normal targets in every selected strategy.

## Research consequence

The supplied daily bars are now the limiting research medium. A genuine grid
depends on intraday touch order, repeated crossings, queue position and fill
quality. Daily OHLC cannot identify those mechanics reliably.

A defensible successor requires new information rather than another threshold
search on these outcomes:

- minute or tick data;
- adjusted VN-Index and sector-index residuals;
- a multi-crossing label with conservative intraday order sequencing;
- realistic spread, queue and partial-fill modeling.

Without those inputs, further optimization on the same daily sample would
primarily increase overfitting risk.

## Governance

- Internal validation (`wf_10`–`wf_15`): **not run**
- Final OOS (`2025-07-14`–`2026-07-16`): **not evaluated**
- Final lock: **not created**
- Live deployment: **not authorized**

## Reproduction

```bash
python3 study_trial14_dense_grid_capture.py --optimize-validate
python3 -m unittest discover -s tests
```

Primary outputs:

- `data/trial14_dense_grid_capture/development/development_report.json`
- `data/trial14_dense_grid_capture/development/capture_optimization.csv`
- `data/trial14_dense_grid_capture/development/is_models.csv`

