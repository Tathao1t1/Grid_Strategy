# Pre-registration: Trial 13 dense grid-EV ranker

## Hypothesis

> A pooled model trained on every eligible ticker-day can use continuous
> mean-reversion, breakout-hazard, grid-economics and liquidity features to
> rank the exact after-cost outcome of a frozen grid more reliably than Trial
> 12's sparse completed-campaign history.

Trial 13 tests a new information structure. It does not loosen Trial 12's
minimum-history rule after observing that trial's result.

## Frozen trading engine

The executed campaign is Trial 12's fixed Trial 11 grid:

```json
{
  "market_return20_min": 0.00,
  "residual_z_max": -0.50,
  "spacing_atr_multiplier": 0.75,
  "lower_level_enabled": false,
  "stop_steps": 3,
  "maximum_horizon": 10
}
```

The residual and market thresholds above are not entry gates in Trial 13.
They remain part of the frozen parameter identity, but the dense model
replaces Boolean activation. Grid spacing, quantity, horizon, T+2 settlement,
trend exit, downside boundary, costs, tax, adverse execution and
corporate-action quarantine remain unchanged.

## Dense observations and target

For each chronological fold, a row is created for every ticker-session with:

- at least 60 prior sessions;
- valid reference-price history;
- median 60-session traded value of at least VND 10 billion;
- finite ATR no greater than 5% of price;
- a complete ten-session future path contained entirely inside the row's
  training or deployment partition.

The label is the exact net campaign return from buying the frozen grid at the
next open and following the frozen campaign rules. Training labels therefore
include target, trend, risk, gap and time outcomes after all modeled costs.

The last ten sessions of every training window are automatically purged
because their labels would cross the deployment boundary.

## Continuous feature vector

All inputs end at the signal-session close:

```text
residual_z5
residual_1
residual_slope20
downside_semivol20
residual_ar1_20
market_return20
close_minus_sma50_fraction
sma20_minus_sma50_fraction
atr20_fraction
log_median_value60
```

The leave-one-out equal-weight return of the other nine stocks remains the
disclosed market proxy because adjusted VN-Index and sector-index history is
not present in the supplied sample.

No ticker identity is included. Parameters are pooled across all ten stocks.

## Model and score

Two deterministic ridge regressions are fitted separately inside each
fold's preceding training window:

1. expected exact net campaign return;
2. expected downside, where the target is
   `max(-net_campaign_return, 0)`.

Features are standardized using training-window moments only. The deployment
score is:

```text
score = predicted_net_return
        - risk_penalty × max(predicted_downside, 0)
```

Only rows with positive predicted net return and score above the declared
buffer can open a grid.

## Frozen search

Exactly 54 configurations are evaluated on `wf_01` through `wf_09`:

```text
ridge penalty       ∈ {10, 100, 1000}
risk penalty        ∈ {0.00, 0.25, 0.50}
score buffer        ∈ {0.000, 0.001}
top new grids/day   ∈ {1, 2, 3}
```

The highest scores are selected subject to:

- at most three simultaneous campaigns;
- at most one active ticker per sector;
- no overlapping campaign in the same ticker;
- five-session cooldown after exit.

Unused capacity remains cash. Position quantity is not optimized.

## Development partitions

- Selector optimization: `wf_01`–`wf_09`, January 2023–June 2024.
- Internal validation: `wf_10`–`wf_15`, July 2024–June 2025.
- Final OOS: 2025-07-14–2026-07-16, inaccessible unless validation passes.

Every fold refits both models using only that fold's preceding training
window. No model parameters or standardization moments carry backward from a
future fold.

## Control

Each deployment fold also runs the unchanged Trial 12 all-universe,
trend-conditioned grid control. Trial 13 must make money and outperform this
control.

## In-sample gates

A configuration is eligible only when:

- all nine folds have valid fitted models;
- at least 30 non-overlapping campaigns execute;
- campaigns span at least three entry years;
- no entry year contains more than 50% of campaigns;
- total and median campaign P&L are positive;
- profit factor is at least 1.20;
- doubled-cost P&L is positive;
- P&L remains positive after removing the best campaign;
- at least 60% of active folds are profitable;
- no ticker contributes more than 40% of positive P&L;
- the top score quintile has higher mean realized return than the bottom
  score quintile across dense deployment observations;
- selected P&L exceeds the all-universe control.

Eligible configurations are ranked by selected-minus-control P&L, then profit
factor, doubled-cost P&L and canonical parameter JSON.

## Internal-validation gates

The single chosen configuration is refitted and run unchanged on
`wf_10`–`wf_15`. It must:

- execute at least 15 campaigns;
- have positive total and median P&L;
- have profit factor at least 1.00;
- remain positive under doubled costs;
- remain positive after removing its best campaign;
- have positive top-minus-bottom score-quintile return spread;
- have target gains cover other losses;
- outperform the control;
- have no campaign worse than -1.5% of VND 100 million.

Only a complete pass creates a cryptographic final-OOS lock.

## Final OOS

If unlocked, the selected model configuration is refitted every two calendar
months using the trailing 12 months of data available before that rotation.
The final period is run once. Failure at either development stage leaves its
prices and outcomes numerically unread.

