# Trial result: TRIAL3-VCB-CONFIRMED-PULLBACK

## Decision

- Run date: 2026-07-23
- Scope: pooled VCB in-sample folds only
- Status: `inconclusive_sample`
- Advance to execution backtest: no
- Walk-forward OOS prices/outcomes used: no
- Final holdout prices used: no

Trial 3 did not produce enough independent observations to judge the entry
hypothesis. This is not a pass, and the pre-registered decision rule classifies
it as inconclusive rather than rejected.

## Reproducible run

```bash
cd /Users/ttt/Grid_Trading_Strategy
.venv-backfill/bin/python study_trial3_pullback_edge.py \
  --all-in-sample-folds
```

- Run ID: `trial3_3a9cd51ad7`
- Result fingerprint:
  `ef299a3ceb3aa8ac0f654b10370319a0ff7a40bfb7ce7dfa0078321c2a8ba50d`
- Output directory:
  `data/trial3_pullback_edge/trial3_3a9cd51ad7/`
- Reproducibility check: two consecutive runs returned the same run ID,
  fingerprint, event count, T+5 mean and win rate.

## Sample construction

| Stage | Rows/events |
|---|---:|
| Fold-level candidates | 23 |
| Unique entry-date candidates | 5 |
| Primary T+10-non-overlapping events | 4 |
| Unique quarantined labels | 0 |

The four primary entries occurred in 2022, 2023 and 2024. No year contained
the required five events, and the total was far below the required 30.

## Primary T+5 result

| Measure | Observed | Frozen requirement |
|---|---:|---:|
| Independent events | 4 | at least 30 |
| Mean net return | -0.1172% | at least +0.50% |
| Median net return | -0.2765% | above 0% |
| Net win rate | 50.0% | at least 55% |
| Exact-VND profit factor | 0.8303 | at least 1.25 |
| Doubled-cost mean | -0.5161% | above 0% |
| Doubled-cost profit factor | 0.3379 | above 1.00 |
| Locked-MAE 10th percentile | -1.1221% | no worse than -5% |

The economic observations are descriptive only because the sample gate failed.
They must not be used to loosen the frozen entry thresholds.

## Diagnostic horizons

T+3 and T+10 were pre-registered diagnostics, not selectable alternatives:

| Horizon | Mean net return | Win rate | Exact-VND profit factor |
|---|---:|---:|---:|
| T+3 | +0.4763% | 75.0% | 5.2503 |
| T+5 (primary) | -0.1172% | 50.0% | 0.8303 |
| T+10 | +3.0319% | 75.0% | 18.0633 |

All four primary events observed the +1.5% favorable barrier before the -3%
adverse barrier. With only four observations, neither the diagnostic horizons
nor the barrier result establishes an edge. Selecting one of them now would be
post-result horizon/exit mining.

## Research discipline

Do not:

- open the walk-forward OOS or final holdout to rescue this trial;
- reduce the minimum event count;
- loosen signal thresholds and keep the Trial 3 label;
- promote the four-event diagnostics into an execution strategy.

A materially changed signal, horizon or exit rule must be pre-registered as a
new trial. The cleanest way to resolve Trial 3 itself is to obtain substantially
more untouched historical VCB data while keeping every rule fixed.

