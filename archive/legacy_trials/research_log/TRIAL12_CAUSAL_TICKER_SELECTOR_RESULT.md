# Trial 12 result: causal grid-expectancy ticker selector

## Decision

**Reject Trial 12 and keep the final out-of-sample period locked.**

No one of the 24 pre-registered selector configurations passed the in-sample
gates. Internal validation was therefore not run and no final-OOS lock was
created.

## What was tested

Trial 12 kept the Trial 11 grid fixed and changed only ticker selection. At
the start of each two-month rotation, every ticker was scored from grid
campaigns that had both entered and exited during the trailing 6 or 12 months.
The score shrank ticker mean return toward the pooled mean and penalized
downside semideviation. Only positive scores with at least two historical
campaigns were eligible.

The search contained exactly:

```text
lookback months       ∈ {6, 12}
shrinkage k           ∈ {5, 10}
downside penalty      ∈ {0.25, 0.50}
top K                 ∈ {1, 2, 3}
```

Selection used only information available before each rotation. The grid,
costs, T+2 settlement, stops, campaign horizon and execution model were not
optimized.

## In-sample result

| Measure | Result |
|---|---:|
| Selector configurations | 24 |
| Eligible configurations | **0** |
| Configurations with no executed campaign | 18 |
| Configurations with executed campaigns | 6 |
| Maximum selected campaigns | **2** |
| Best selected P&L | VND 0 from remaining in cash |
| Traded-configuration P&L | **−VND 294,990** |
| Traded-configuration median P&L | **−VND 147,495** |
| Traded-configuration profit factor | **0.00** |
| Traded-configuration doubled-cost P&L | **−VND 389,763** |
| All-universe control campaigns | 32 |
| All-universe control P&L | **−VND 256,518** |

The six configurations that traded all used:

- 12-month lookback;
- shrinkage `k = 5`;
- either downside penalty;
- any top-K value.

They made the same effective choices. VCB and PNJ qualified for `wf_08`, but
only VCB generated deployment signals. The two VCB campaigns lost VND 117,780
and VND 177,210. FPT qualified for `wf_09` but generated no campaign.

## Why the sample collapsed

The frozen historical library contained 57 non-overlapping campaigns: 32
were profitable, but aggregate P&L was **−VND 1,377,604**. The negative pooled
expectancy pulled shrinkage scores downward.

The 6-month history was usually too sparse and never produced an eligible
deployment ticker. The 12-month history produced positive admissible scores
only late in development. Even then, a selected ticker also had to generate a
new frozen-grid activation during the following two-month rotation. Those two
filters rarely overlapped.

This is not simply a rejection caused by ambitious advancement thresholds:
the most permissive executed variants had two losing campaigns, negative
median P&L, zero profit factor, negative doubled-cost P&L and underperformed
the all-universe control.

## Interpretation

Trial 12 rejects the hypothesis that recent ticker-level grid expectancy,
estimated from this short daily sample, is stable enough to select future
grid opportunities. The selector correctly avoided many losing control
campaigns, but its sparse positive history did not identify profitable future
campaigns.

Loosening only the final advancement gates cannot solve this result. A future
trial would need to change the information set or estimator—for example,
longer adjusted history, continuous pre-entry mean-reversion features, or a
cross-sectional ranking that does not require two rare completed grid
campaigns—while preserving causal selection and an untouched OOS period.

## Governance

- Internal validation (`wf_10`–`wf_15`): **not run**
- Final OOS (`2025-07-14`–`2026-07-16`): **not parsed or evaluated**
- Final lock: **not created**
- Decision: **do not claim profitability and do not deploy live**

## Reproduction

```bash
python3 study_trial12_ticker_selector.py --optimize-validate
python3 -m unittest discover -s tests
```

Primary outputs:

- `data/trial12_ticker_selector/development/development_report.json`
- `data/trial12_ticker_selector/development/selector_optimization.csv`

