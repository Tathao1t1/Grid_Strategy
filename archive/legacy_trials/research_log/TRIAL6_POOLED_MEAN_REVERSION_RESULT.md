# Trial 6 authoritative development result

## Decision

- Trial: `TRIAL6-HSX-POOLED-MEAN-REVERSION-EDGE`
- Authoritative run: `trial6_8c3b8f9a60`
- Scope: 15 chronological development walk-forward folds
- Status: `inconclusive_sample`
- Advance to minute-level Stage B: **no**
- Final-test data used: **no**

Trial 6 v1 solved Trial 5's activity problem but did not demonstrate a
predictive or economic edge. It must not be used live or repaired in place.

## Sample result

| Measure | Observed | Frozen requirement | Passed |
|---|---:|---:|:---:|
| Valid folds | 15 | 15 | Yes |
| Eligible OOS candidates | 505 | at least 100 | Yes |
| Selected non-overlapping campaigns | 62 | at least 60 | Yes |
| Selected target campaigns | 32 | at least 30 | Yes |
| Years with at least 10 campaigns | 2 | at least 3 | No |
| Largest year share | 59.68% | at most 45% | No |

The year counts were 23 campaigns in 2023, 37 in 2024 and two in 2025.
Therefore the frozen decision is `inconclusive_sample`, regardless of the
unfavorable descriptive economics.

## Predictive diagnostics

| Measure | Observed | Required | Passed |
|---|---:|---:|:---:|
| Model Brier score | 0.30370 | below base rate | No |
| Training-base-rate Brier | 0.25820 | comparison | — |
| Lowest probability quintile target rate | 63.37% | below highest | No |
| Highest probability quintile target rate | 49.50% | above lowest | No |

The model's ordering was directionally wrong out of sample. Candidates assigned
the lowest target probabilities reverted more frequently than candidates
assigned the highest probabilities.

## Economic diagnostics

| Measure | Observed | Frozen requirement |
|---|---:|---:|
| Total exact-VND P&L | -1,118,011 | positive |
| Median campaign P&L | +24,340.5 | positive |
| Profit factor | 0.6516 | at least 1.20 |
| Target gains | +2,090,668 | cover non-target losses |
| Non-target losses | -3,208,679 | no larger than target gains |
| Doubled-cost P&L | -2,401,452 | positive |
| Doubled-cost profit factor | 0.3664 | at least 1.00 |
| P&L after best campaign removed | -1,252,133 | positive |

Exit counts:

```text
target           32
downside touch   28
downside gap      2
time exit         0
```

The median was positive because slightly more than half the campaigns reached
their symmetric target. The aggregate still lost money because costs and
adverse gap/downside outcomes made the non-target loss pool materially larger
than target gains.

## Interpretation

Trial 6 demonstrates that sample sufficiency and risk control are separable
from signal quality:

1. A broad, pooled residual candidate definition generated enough raw and
   selected observations.
2. Sector caps, positive estimated EV and non-overlap rules did not starve the
   system.
3. The fitted feature relationship did not generalize chronologically.
4. Volatility-symmetric price barriers were economically asymmetric after
   costs and adverse gaps.
5. More execution did not repair the missing predictive edge.

No multi-level grid or minute-level Stage B should be implemented from this
model.

## Invalid pre-authoritative attempt

Run directory `trial6_dd27ee3bc4` is retained as an invalid implementation
artifact. A fixed-step numerical solver failed its convergence check in all
15 folds and produced no OOS predictions. The repair changed only the solver
used to reach the same preregistered L2-logistic optimum and added the
implementation source hash to the run identity. It did not change the
universe, data, features, labels, thresholds, selection rules or gates.

The invalid attempt is not an economic result and is not used in the decision.

## Reproduction

```bash
python3 -m unittest discover -s tests -p 'test*.py' -v
python3 study_trial6_mean_reversion.py --development-walk-forward
```

All 47 repository tests passed. A separate clean output-root execution
reproduced byte-identical hashes for all six result artifacts:

```text
fold_summary.csv            f51b28898003b1d1183ec4c945a5867d9686a0748acd6370a657686200d56a86
gate_report.json             585eca4bc06f23305cb0d279d413f3ec9ccac2653b4b624b8012870fe406e75e
model_parameters.csv         0c2167884d81754f1f86dbde40f3f1f617eb555df7e2d0586938d8f0d269053d
oos_candidates.csv           4d82b817b1a3ab920b25668d476da838e5e8fb15a0fc49f662e7f9aadc6bb7cd
quarantined_candidates.csv   a8fadde78c595a27baef622718e2e6babc0bde6b61b10ed20fcd01695f50969d
selected_campaigns.csv       f9f1751eb180cca54a2773a0dd4b843e63ad128be247a3ca4ecb17986e8c364a
```

## Research consequence

A successor should not tune Trial 6's z-score, barriers or logistic
regularization against these same outcomes. A genuinely new trial would need
new information or a materially different economic hypothesis, such as:

- adjusted VN-Index and sector-index residuals rather than the internal
  ten-stock proxy;
- older untouched history or a broader preregistered liquid universe to
  resolve the year-distribution failure;
- direct expected-P&L or survival/hazard estimation instead of target-first
  classification;
- an explicit reversal-state transition rather than a level-deviation model.

Those are possible new research programs, not post-result repairs to Trial 6.

