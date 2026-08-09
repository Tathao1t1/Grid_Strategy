# Pre-registration: Trial 12 causal grid-expectancy ticker selector

## Hypothesis

> The pooled grid fails because its expectancy differs across tickers and
> changes through time. A causal, shrinkage-adjusted selector using only grid
> campaigns completed before each rotation can improve the frozen grid enough
> to produce positive future portfolio expectancy.

Trial 12 does not globally select the positive Trial 11 tickers. Selection is
recomputed inside every historical rotation.

## Frozen grid

The common grid is fixed before selector results:

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

All Trial 11 signal, trend, cost, settlement, execution, cooldown and
corporate-action rules remain unchanged. Grid parameters are not optimized in
Trial 12.

## Rotations

- Selector optimization: `wf_01` through `wf_09`, January 2023–June 2024.
- Internal validation: `wf_10` through `wf_15`, July 2024–June 2025.
- Final OOS: July 2025–July 2026, accessible only after validation passes.

Each development rotation has its existing preceding 12-month training
calendar and non-overlapping two-month deployment.

## Historical campaign library

The frozen grid is hypothetically evaluated for every ticker through time.
For selector training:

- campaigns are made non-overlapping within ticker;
- every campaign must exit before the rotation begins;
- campaign entry and exit must fall inside the selected trailing lookback;
- corporate-action-contaminated campaigns are excluded;
- no future rotation outcome enters a score.

## Shrinkage score

For ticker i:

```text
shrunk_mean_i =
    n_i / (n_i + k) × mean_return_i
    + k / (n_i + k) × pooled_mean_return

score_i =
    shrunk_mean_i
    - downside_penalty × downside_semideviation_i
```

A ticker requires at least two completed trailing campaigns, positive score,
valid current data and sufficient liquidity. The top K scores are selected,
with at most one ticker per sector. No positive score means cash.

## Frozen selector search

Exactly 24 selector configurations are evaluated:

```text
lookback months       ∈ {6, 12}
shrinkage k           ∈ {5, 10}
downside penalty      ∈ {0.25, 0.50}
top K                 ∈ {1, 2, 3}
```

No grid or execution parameter changes.

## Control

Every rotation also runs the same frozen grid across the complete universe,
subject to the same three-position and sector constraints. Trial 12 must
outperform this unselected control, not merely make money.

## In-sample selector gates

Across `wf_01`–`wf_09`, a selector is eligible only when:

- all nine rotations are valid;
- at least 20 selected campaigns execute;
- total and median campaign P&L are positive;
- exact-VND profit factor >= 1.20;
- doubled-cost P&L is positive;
- P&L after removing the best campaign is positive;
- at least 60% of active rotations are profitable;
- no ticker contributes more than 40% of positive P&L;
- selected-strategy P&L exceeds control P&L.

Eligible selectors are ranked by selected-minus-control P&L, then selected
profit factor, doubled-cost P&L and canonical parameter JSON.

## Internal-validation gates

The single selected configuration runs unchanged on `wf_10`–`wf_15` and must:

- execute at least eight campaigns;
- have positive total and median P&L;
- have profit factor >= 1.00;
- have positive doubled-cost P&L;
- remain positive after removing its best campaign;
- have target gains cover other losses;
- outperform the complete-universe control;
- have worst campaign no worse than -1.5% of VND 100 million.

Only a full pass creates a final-OOS lock.

## Final OOS

If unlocked, the selector is recalculated prospectively every two calendar
months using only campaigns completed before that rotation. The locked
selector and grid then run once from 2025-07-14 through 2026-07-16.

