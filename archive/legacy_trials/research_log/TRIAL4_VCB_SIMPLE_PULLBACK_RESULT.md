# Trial result: TRIAL4-VCB-SIMPLE-PULLBACK

## Decision

- Run date: 2026-07-23
- Scope: one sealed pooled VCB development/in-sample run
- Status: `inconclusive_sample`
- Advance to untouched confirmation: no
- Advance to execution backtest: no
- Walk-forward OOS prices/outcomes used: no
- Final holdout prices used: no

Trial 4 materially increased signal frequency, but it did not reach the frozen
sample-size and year-distribution requirements. Its economic observations are
mixed and remain exploratory.

## Reproducible run

```bash
cd /Users/ttt/Grid_Trading_Strategy
.venv-backfill/bin/python study_trial4_simple_pullback.py \
  --all-in-sample-folds
```

- Run ID: `trial4_4a3fdcf798`
- Result fingerprint:
  `535d6d35eb09e0f4edd4ae1dfc9811cb9d7c914f68a4c914bdde461ea8c1d63e`
- Output directory:
  `data/trial4_simple_pullback/trial4_4a3fdcf798/`
- Decision lock:
  `research_log/TRIAL4_V1_DECISION_LOCK.json`
- Reproducibility: a second command invocation reused the identical locked
  run, and every manifest/artifact hash remained unchanged.

## Sample construction

| Stage | Rows/events |
|---|---:|
| Covered, label-capable entry sessions | 770 |
| Fold-level candidates | 156 |
| Unique candidates | 37 |
| T+5-non-overlapping primary events | 23 |
| Unique quarantined labels | 1 |

Trial 4 produced almost six times as many primary events as Trial 3, but still
fell short of the frozen minimum of 40.

## Frequency result

| Measure | Observed | Frozen requirement |
|---|---:|---:|
| Evaluable two-month blocks | 18 | at least 12 |
| Blocks containing a primary event | 11 | — |
| Two-month event coverage | 61.11% | at least 60% |
| Median inter-event gap | 12 sessions | diagnostic |
| 75th-percentile gap | 28.25 sessions | diagnostic |
| Maximum gap | 154 sessions | diagnostic |

The explicit two-month frequency gate passed. However, the 154-session maximum
gap shows that the signal can still remain inactive for a long regime.

## Primary T+5 economics

| Measure | Observed | Frozen requirement |
|---|---:|---:|
| Mean net return | +0.5465% | at least +0.50% |
| Median net return | -0.6068% | above 0% |
| Net win rate | 39.13% | at least 55% |
| Exact-VND profit factor | 1.5497 | at least 1.25 |
| Doubled-cost mean | +0.1449% | above 0% |
| Doubled-cost profit factor | 1.0332 | above 1.00 |
| Locked-MAE 10th percentile | -2.6499% | no worse than -5% |

The positive mean and profit factor came with a negative median and low win
rate. This is a right-skewed profile dependent on a minority of larger winners,
not a stable high-hit-rate rebound pattern.

## Distribution through time

| Entry year | Events | Mean T+5 net return |
|---|---:|---:|
| 2022 | 5 | +2.5456% |
| 2023 | 6 | +0.4138% |
| 2024 | 12 | -0.2202% |

Only one year reached eight events, versus the required three. The largest
year supplied 52.17% of the sample, slightly above the 50% concentration cap,
and that year had a negative mean. This instability prevents interpreting the
overall positive mean as a dependable edge.

## Diagnostic observations

T+3 was not allowed to drive the decision:

| Measure | T+3 diagnostic |
|---|---:|
| Mean net return | +0.3083% |
| Median net return | -0.6058% |
| Win rate | 43.48% |
| Exact-VND profit factor | 1.2764 |
| Doubled-cost mean | -0.0923% |

Through T+5, the +1.5% favorable barrier was observed first in 14 events, the
-3% adverse barrier first in 2, and neither in 7. These are path diagnostics,
not executable exit results.

## Research discipline

Do not:

- lower the 40-event requirement after seeing 23 events;
- replace T+5 with T+3;
- add a filter to remove the losing 2024 regime;
- open OOS/final data to rescue the trial;
- treat the positive mean as sufficient while ignoring the negative median,
  39% win rate and year instability.

The clean ways to resolve the hypothesis are to obtain older untouched VCB
history and rerun the frozen rules under a separately governed extension, or
pre-register a cross-ticker study with a common formula and correlation-aware
inference. Trial 4 v1 itself is now locked and cannot be revised.

