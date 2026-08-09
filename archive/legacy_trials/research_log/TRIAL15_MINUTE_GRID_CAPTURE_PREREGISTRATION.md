# Pre-registration: Trial 15 minute-executed grid capture

## Hypothesis

> Trial 14's daily OHLC labels could not resolve touch order or executable
> spreads. Dense prior-day features can rank genuine after-cost grid cycles
> when orders are simulated chronologically on the existing one-minute
> bid/ask and matched-volume archive.

Trial 15 changes the outcome and execution resolution. It does not select a
daily Trial 14 frontier configuration.

## Data and partitions

- Prior-day signals: `data_algotradeDB_split.csv`.
- Execution: monthly files in `data/minute_bars/`.
- In-sample optimization: `wf_01`–`wf_09`, January 2023–June 2024.
- Internal validation: `wf_10`–`wf_15`, July 2024–2025-07-11.
- Locked final minute OOS: 2025-07-14–2026-06-30.

July 2026 is excluded because representative rows were inspected during the
minute-data inventory audit. Final minute files are not opened by the
development command.

## Causal features

Trial 15 reuses Trial 13's ten point-in-time features. Every feature ends at
the signal-session close. A campaign can begin only from the next session.

Training and deployment labels must finish inside their own partition.
Signals in the final ten sessions of a partition are therefore purged.

## Minute grid

Each campaign is one repeated grid cell:

1. At the first eligible minute of the activation session, buy 100 shares at
   the displayed ask plus the modeled execution haircut.
2. Freeze the centre at that first execution price.
3. Set the target one grid step above the centre.
4. After a target sale, re-arm a 100-share buy at the frozen centre only after
   the sale cash settles.
5. Each repurchased lot targets the same upper level.
6. Stop creating new lots during the final two sessions.
7. Close remaining settled inventory by the end of session ten.

The grid step is:

```text
clamp(0.75 × ATR20 / close, 1.5%, 3.0%)
```

The catastrophic boundary is three grid steps below the centre. A touch
shuts down new orders. Shares still locked by T+2 are sold at the first
eligible minute after settlement.

## Execution assumptions

- Continuous morning and afternoon sessions only.
- 100-share board lots.
- Buy from displayed ask; sell to displayed bid.
- Additional 5-bps execution haircut on each side.
- 0.15% commission per side and 0.10% sell tax.
- Displayed spread must be no greater than 40 bps.
- When displayed book quantity is present, it must cover 100 shares.
- The order must be no more than 5% of matched minute quantity.
- Shares and sale cash settle at 13:00 on T+2.
- At most one state transition per grid campaign per minute.
- An order created by a fill cannot execute in that same minute.
- Missing usable exit liquidity invalidates the candidate rather than
  assuming a fill.

Normal and doubled-cost outcomes are simulated on the identical minute path.

### Pre-outcome data-quality amendment

The first implementation run stopped before generating any training label or
economic output because the 2022 archive contains bid/ask prices but has null
bid/ask queue quantities in every row. Queue quantities are complete from
January 2023 onward.

For 2022 rows with a valid bid/ask but missing queue quantity, eligibility
therefore falls back to the already declared 5% matched-minute participation
cap. When queue quantity is present, both queue coverage and the participation
cap remain mandatory. This amendment was recorded after a zero-label data
failure and before any Trial 15 P&L was calculated; the model, search and
economic gates are unchanged.

## Dense minute targets

For every eligible ticker-session:

```text
cycle_probability_target = 1 if at least one target sale completes
capture_return = after-cost target-sale gains / first-lot capital
forced_loss_return = non-target realized losses / first-lot capital
```

Profitable forced or time exits do not count as grid capture.

Three pooled ridge models predict cycle probability, capture return and forced
loss return. The ranking score is:

```text
minute_grid_score =
    predicted_capture_return
    - risk_penalty × predicted_forced_loss_return
```

## Frozen search

Exactly 48 configurations are evaluated:

```text
ridge penalty              ∈ {10, 100}
minimum cycle probability  ∈ {0.25, 0.40}
risk penalty               ∈ {1.00, 1.50}
score buffer               ∈ {0.000, 0.001}
top new campaigns per day  ∈ {1, 2, 3}
```

Selection permits at most three active campaigns, at most one active ticker
per sector, no same-ticker overlap, and a five-session cooldown.

## In-sample gates

A configuration advances only when:

- all nine models and minute partitions are valid;
- at least 20 independent campaigns execute;
- at least 10 campaigns complete a grid cycle;
- campaigns appear in both 2023 and 2024;
- neither year contains more than 75% of campaigns;
- total and median P&L are positive;
- profit factor is at least 1.20;
- doubled-cost P&L is positive;
- P&L remains positive after removing the best campaign;
- target-cycle gains exceed forced and time-exit losses;
- at least 60% of active folds are profitable;
- no ticker contributes more than 40% of positive P&L;
- top score-quintile cycle rate exceeds bottom score-quintile cycle rate.

Eligible configurations are ranked by P&L, profit factor, doubled-cost P&L
and canonical configuration JSON.

## Internal validation

The single selected configuration is refitted unchanged on `wf_10`–`wf_15`
and must:

- execute at least 10 campaigns and five cycle campaigns;
- have positive total and median P&L;
- have profit factor at least 1.00;
- remain positive under doubled costs and after best-campaign removal;
- have cycle gains cover forced/time losses;
- preserve a positive score-quintile cycle-rate spread;
- have no campaign worse than -1.5% of VND 100 million.

Only a complete pass creates a cryptographic final-OOS lock.
