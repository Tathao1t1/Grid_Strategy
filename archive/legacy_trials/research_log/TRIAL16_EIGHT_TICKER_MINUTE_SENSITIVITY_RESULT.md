# Trial 16 result: eight-ticker minute sensitivity

## Decision

Removing FPT and PNJ reduced the least-negative nominal loss but did not
produce a profitable or sufficiently large sample. No configuration advanced
to validation.

Trial 16 is exploratory because the universe change was requested after Trial
15 outcomes were known.

## Universe and timeline

Execution universe:

```text
HPG, MBB, MWG, SSI, TCB, VCB, VND, VPB
```

FPT and PNJ remained only in the unchanged market-proxy feature. They could
not generate labels, candidates, positions or control campaigns.

- Training history begins: 2022-01-04.
- In-sample deployment: 2023-01-03–2024-06-28.
- Conditional validation: 2024-07-01–2025-07-11; not opened.
- Locked minute OOS: 2025-07-14–2026-06-30; not opened.
- Campaign horizon: ten trading sessions.

## Result

| Measure | Trial 15: 10 tickers | Trial 16: 8 tickers |
|---|---:|---:|
| Positive configurations | 0 / 48 | 0 / 48 |
| Campaign range | 6–22 | 3–12 |
| Cycle-campaign range | 1–12 | 1–5 |
| Positive score-quintile spread | 0 / 48 | 0 / 48 |
| Least-negative P&L | −VND 685,810 | **−VND 236,901** |
| Least-negative PF | 0.700 | **0.700** |

The least-negative eight-ticker configuration used:

```json
{
  "ridge_penalty": 100,
  "minimum_target_probability": 0.25,
  "risk_penalty": 1.0,
  "score_buffer": 0.001,
  "top_k": 1
}
```

| Metric | Result |
|---|---:|
| Campaigns | 7 |
| Cycle campaigns | 4 |
| Median campaign P&L | +VND 25,830 |
| Net P&L | **−VND 236,901** |
| Profit factor | **0.700** |
| Doubled-cost P&L | **−VND 464,725** |
| P&L after best campaign removed | **−VND 567,176** |
| Target-cycle gains | +VND 699,890 |
| Forced/time losses | **−VND 936,791** |
| Eight-ticker minute control | −VND 296,888 |

The strategy outperformed its control by VND 59,987, but both lost money.
Removing two tickers also reduced the already-small sample. It did not alter
the underlying approximately 0.70 profit factor or the negative
score-quintile cycle-rate spread.

## Interpretation

FPT and PNJ were not the sole cause of Trial 15's failure. Their exclusion
reduced exposure and loss magnitude, but target-cycle gains still failed to
cover forced/time inventory losses.

This sensitivity cannot support a profitable claim and should not be used to
justify further post-result ticker deletion.

## Governance

- Internal validation: **not run**
- Final minute OOS: **not opened**
- Final lock: **not created**
- Live deployment: **not authorized**

