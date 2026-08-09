# Pre-registration: Trial 14 dense grid-capture ranker

## Hypothesis

> Trial 13 predicted general campaign return and could earn through trend
> exits without completing a grid target. A dense model that separately
> predicts normal grid-target capture and non-target inventory loss can select
> campaigns whose profits arise from the grid mechanism itself.

Trial 14 is a new target specification. It does not retune Trial 13's
net-return model after observing its frontier.

## Frozen trading engine

Trial 14 preserves the exact Trial 13 campaign engine:

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

The model replaces the entry gates. Quantity remains 100 shares, spacing is
1.5%–4.0%, shares settle T+2, and all fees, sell tax, execution haircuts,
trend shutdown, downside boundary, time exit and corporate-action quarantine
remain unchanged.

This frozen engine has one initial grid cell and therefore at most one normal
target completion per campaign. Testing more levels is deferred so that Trial
14 changes the prediction target without simultaneously changing execution.

## Dense observations

Trial 14 reuses Trial 13's causal ticker-session observations and continuous
features:

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

Every row has at least 60 prior sessions and a complete future campaign path
contained inside its own training or deployment partition. The final ten
training sessions are purged automatically. Model inputs end at the signal
close.

## Grid-specific targets

For each dense historical campaign, define:

```text
target_completion = 1 if a lot sells at its normal grid target, else 0

capture_return =
    after-cost normal_target_gain_vnd / acquisition_capital_vnd

inventory_loss_return =
    non-target other_loss_vnd / acquisition_capital_vnd
```

Profitable trend, risk or time exits do not enter `capture_return`. They may
contribute to realized portfolio P&L, but they cannot cause the model to
classify a campaign as successful grid capture.

## Models and score

Three deterministic pooled ridge models are fitted independently inside each
fold:

1. target-completion probability, clipped to `[0, 1]`;
2. expected after-cost grid-capture return, clipped at zero;
3. expected non-target inventory-loss return, clipped at zero.

The daily score is:

```text
grid_score =
    predicted_capture_return
    - risk_penalty × predicted_inventory_loss_return
```

A grid may open only when predicted target probability reaches the declared
minimum and `grid_score` exceeds the declared buffer.

## Frozen search

Exactly 48 configurations are tested on `wf_01`–`wf_09`:

```text
ridge penalty              ∈ {10, 100}
minimum target probability ∈ {0.30, 0.45}
risk penalty               ∈ {1.00, 1.50}
grid-score buffer          ∈ {0.000, 0.001}
top new grids per day      ∈ {1, 2, 3}
```

Selection is by descending grid score, subject to:

- at most three simultaneous campaigns;
- at most one active ticker per sector;
- no overlapping campaign in the same ticker;
- five-session cooldown after exit.

## Partitions

- In-sample optimization: `wf_01`–`wf_09`, January 2023–June 2024.
- Internal validation: `wf_10`–`wf_15`, July 2024–June 2025.
- Final OOS: 2025-07-14–2026-07-16, locked unless validation passes.

Every model is refitted using only the preceding training window. The
unchanged Trial 12 all-universe trend-grid remains the control.

## In-sample gates

A configuration is eligible only when:

- all nine folds have valid models;
- at least 20 independent campaigns execute;
- at least 10 campaigns complete a normal grid target;
- campaigns appear in both available entry years, 2023 and 2024;
- neither year contains more than 75% of campaigns;
- total and median campaign P&L are positive;
- profit factor is at least 1.20;
- doubled-cost P&L is positive;
- P&L remains positive after removing the best campaign;
- normal target gains exceed non-target losses;
- at least 60% of active folds are profitable;
- no ticker contributes more than 40% of positive P&L;
- the top grid-score quintile has a higher target-completion rate than the
  bottom quintile across all dense deployment observations;
- selected P&L exceeds the all-universe control.

Eligible configurations are ranked by selected-minus-control P&L, then profit
factor, doubled-cost P&L and canonical configuration JSON.

## Internal-validation gates

The single selected configuration is refitted and run unchanged on
`wf_10`–`wf_15`. It must:

- execute at least 10 campaigns;
- complete at least five normal grid targets;
- have positive total and median P&L;
- have profit factor at least 1.00;
- remain positive under doubled costs;
- remain positive after removing its best campaign;
- have normal target gains cover non-target losses;
- have a positive top-minus-bottom target-rate spread;
- outperform the control;
- have no campaign worse than -1.5% of VND 100 million.

Only a complete pass creates the final-OOS lock.

## Final OOS

If unlocked, the configuration is refitted every two calendar months using
only the trailing 12 months available before that rotation. The locked final
period is evaluated exactly once.

