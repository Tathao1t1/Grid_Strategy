# Trial 3: VCB confirmed-pullback edge study

This study validates the new entry hypothesis before any execution backtester
is built. It uses VCB in-sample data only. T+5 is the frozen primary outcome;
T+3 and T+10 are diagnostics.

## Reproducible commands

Run every command from the project directory:

```bash
cd /Users/ttt/Grid_Trading_Strategy
```

Create the VCB-only fold manifest:

```bash
.venv-backfill/bin/python create_strategy_splits.py \
  --tickers VCB \
  --train-months 12 \
  --oos-months 2 \
  --output-dir data/trial3_splits_vcb
```

Run tests:

```bash
.venv-backfill/bin/python -m unittest discover -s tests -v
```

Run all in-sample folds:

```bash
.venv-backfill/bin/python study_trial3_pullback_edge.py \
  --all-in-sample-folds
```

The script does not implement or accept an OOS/final-test role.

To diagnose one fold without making a research decision:

```bash
.venv-backfill/bin/python study_trial3_pullback_edge.py \
  --fold wf_01
```

A single-fold run always reports `diagnostic_fold_only` and cannot advance
the hypothesis.

## Outputs

Each deterministic run writes to:

```text
data/trial3_pullback_edge/<run_id>/
```

Read the files in this order:

1. `gate_report.json`: authoritative hypothesis status and frozen gates.
2. `primary_events.csv`: unique, chronological events purged through T+10.
3. `fold_summary.csv`: non-independent fold stability slices.
4. `manifest.json`: scope, inputs, assumptions, hashes and fingerprint.

Supporting audit files:

- `fold_candidates.csv`: repeated fold-level candidate rows. Do not calculate
  the pooled edge from this file.
- `quarantined_fold_rows.csv`: repeated fold-level invalid-label rows.
- `quarantined_events.csv`: invalid labels deduplicated across folds.
- `unique_candidates.csv`: candidates deduplicated across overlapping folds

## How to read the values

- Return, MFE, MAE, gap, and ATR-fraction columns are decimals: `0.01` means
  1%, while `-0.03` means -3%.
- `entry_price` and indicator prices use the database quote unit;
  `entry_price_vnd` and `*_pnl_vnd_*` use Vietnamese dong.
- T+h means h observed VCB trading sessions after entry, not calendar days.
- Profit factor uses exact VND P&L for one 100-share lot. `infinity` means
  positive P&L and no losing event in that sample.
- A blank CSV value means unavailable, not zero.
- `both_hit_same_bar` means the daily high crossed the favorable barrier and
  the daily low crossed the adverse barrier on the same bar, so order is
  unknowable.
- T+2 barrier observations are conservatively inside the settlement-day
  uncertainty window; daily data cannot locate the hit within that day.

Study statuses:

- `passed_in_sample_edge`: every frozen gate passed; an execution backtest may
  be designed next.
- `rejected`: sample size was adequate, but at least one economic/risk gate
  failed.
- `inconclusive_sample`: the sample count or year coverage was inadequate.
- `diagnostic_fold_only`: a debug run, never a research decision.

The process exits with code 0 when computation succeeds, even when the
hypothesis is rejected or inconclusive. Use `status` and
`advance_to_execution_backtest` in `gate_report.json` for the decision.

Definitions, assumptions, and frozen gates are in
`research_log/TRIAL3_VCB_CONFIRMED_PULLBACK.md`. No threshold may be changed
after opening the pooled result; a changed hypothesis must be registered as a
new trial.

The frozen pooled in-sample result is recorded separately in
`research_log/TRIAL3_VCB_IN_SAMPLE_RESULT.md`.
