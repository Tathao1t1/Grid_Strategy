# Trial 7 authoritative development result

## Decision

- Trial: `TRIAL7-HSX-CONFIRMED-EPISODIC-GRID`
- Run: `trial7_da36be41cf`
- Status: `inconclusive_sample`
- Advance to minute Stage B: **no**
- Final-test data used: **no**

Trial 7 came close to its episode-count gate but its descriptive economics
were strongly unfavorable. Loosening the sample gates cannot rescue it.

## Sample result

| Measure | Observed | Frozen requirement | Passed |
|---|---:|---:|:---:|
| Valid folds | 15 | 15 | Yes |
| Activation candidates | 67 | at least 75 | No |
| Independent selected episodes | 36 | at least 40 | No |
| Ordinary target sales | 25 | at least 15 | Yes |
| Entry years with at least 5 episodes | 3 | 3 | Yes |
| Largest year share | 44.44% | at most 55% | Yes |

Year counts were 16 episodes in 2023, 14 in 2024 and six in the first half of
2025. Unlike Trials 4 and 6, calendar concentration was not the problem.

## Economic diagnostics

Economics are descriptive because the frozen sample gate failed.

| Measure | Observed | Frozen requirement |
|---|---:|---:|
| Total net P&L | -VND 3,046,582 | positive |
| Median episode P&L | +VND 31,231 | positive |
| Profit factor | 0.3471 | at least 1.20 |
| Normal target gains | +VND 1,535,823 | cover other losses |
| Risk/time losses | -VND 4,666,485 | no larger than gains |
| Doubled-cost P&L | -VND 3,953,879 | positive |
| Doubled-cost profit factor | 0.2214 | at least 1.00 |
| P&L after best episode removed | -VND 3,305,597 | positive |

There were:

```text
13 risk-exit episodes
 3 opening-gap risk exits
 3 time-exit episodes
 9 episodes with the second grid level filled
```

The nine lower-level episodes lost VND 1,205,138 in aggregate. Thus the
second grid level reproduced the negative-convexity problem on a smaller
scale despite equal, rather than increasing, lot sizes.

Only MBB and SSI were profitable in aggregate, and MBB contributed just one
selected episode. Eight of the ten tickers lost money.

## Requested gate-loosening analysis

Trial 7 preregistered diagnostic floors of 30 and 20 selected episodes. Under
a hypothetical relaxed sample rule of:

```text
at least 60 activation candidates
at least 30 selected episodes
all other sample gates unchanged
```

every sample gate would pass. The result would then be
`rejected_development`, not passed:

- eight of ten economic gates fail;
- profit factor is far below one;
- doubled costs worsen the loss;
- target gains cover only 32.9% of risk/time losses;
- removing the best episode makes no material difference;
- second-level episodes lose money.

Therefore collecting four additional episodes to reach 40 cannot plausibly
change the research decision. Retaining `inconclusive_sample` preserves the
frozen rule, while the sensitivity result shows the hypothesis is
economically unattractive.

## Interpretation

The confirmation and temporary activation rules improved sample distribution
and produced many ordinary target sales. They did not change the grid payoff:

```text
many modest target gains
        versus
fewer, materially larger inventory losses
```

Settlement-aware locked inventory and opening gaps remain important. A
three-step hard-lower boundary is not a guaranteed loss boundary, and the
optional second level increases inventory precisely when the path is weakest.

Trial 7 should not proceed to minute execution and should not be retuned by
moving H, narrowing the grid, or weakening confirmation on these same
outcomes.

## Reproduction

```bash
python3 -m unittest discover -s tests -p 'test*.py' -v
python3 study_trial7_episodic_grid.py --development-walk-forward
```

All 52 repository tests passed. A clean second execution produced
byte-identical artifacts:

```text
activation_candidates.csv   058b7d87e32d31cee5278e43ddf40c895eab47949c3e5c5c2f57f0820fee1196
selected_episodes.csv       2c77f5113b0935df312422d75c390fdf0d03a2a2c87e3604f799cc345025f266
quarantined_candidates.csv  6ba07bb98915eabb05619d8da0c4bc89fe52f4d1d8751c90cf31cd428bd91346
fold_summary.csv             ceb5e12b8051fcfbc4241640801b8f3c0374b40ee8a1d31f01101f5c962c34db
gate_report.json             1f6beeb600c3c9f41b5a1f7e01a74c7747bfb7cdccb4e6509d0757f4f7ecefc3
```

