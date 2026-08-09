# Pre-registration: Trial 17 fair-value reversal grid

## Status

Trial 17 is an **exploratory post-Trial-16 redesign**. Its rules were chosen
after Trial 16 outcomes were observed, so even a successful internal
validation would not turn the development result into independent evidence.
The locked final minute holdout remains unopened unless every declared gate
passes.

## Hypothesis

> Trial 16 bought at an arbitrary first-minute centre and allowed T+2-locked
> inventory to absorb a falling market. A grid anchored to prior fair value,
> activated below that centre, and confirmed by an intraday reclaim can retain
> grid-cycle gains while reducing forced and time-exit losses.

The primary economic target is to reduce forced/time losses by at least 50%
relative to the fair-value touch-only ablation while retaining positive
after-cost cycle gains.

## Universe and partitions

Execution universe:

```text
HPG, MBB, MWG, SSI, TCB, VCB, VND, VPB
```

FPT and PNJ remain only in the leave-one-out market proxy. They cannot create
orders or positions.

- Feature history begins: 2022-01-04.
- In-sample mechanics comparison: `wf_01`–`wf_09`,
  2023-01-03–2024-06-28.
- Conditional internal validation: `wf_10`–`wf_15`,
  2024-07-01–2025-07-11.
- Locked minute final OOS: 2025-07-14–2026-06-30.

Every signal uses information available at its session close. Its executable
path begins on the next session and must finish inside the same partition.

## Fair-value pullback signal

The fixed campaign centre is the HSX-tick-rounded median of the ticker's last
20 daily closes, ending on the signal date. It is independent of the next
session's execution price and is never moved while inventory is held.

A pending campaign requires:

```text
residual_z5 <= -0.50
signal close < 20-session median centre
60-session median daily value >= VND 10 billion
ATR20 / close <= 5%
no unverified or detected reference-price reset
```

The causal ranking score is:

```text
opportunity_score =
    -residual_z5
    + (centre - signal_close) / (centre × ATR20_fraction)
```

No fitted prediction model is used. This isolates grid mechanics from Trial
16's negatively ordered ridge score.

## Grid geometry

The geometric step is unchanged:

```text
s = clamp(0.75 × ATR20 / close, 1.5%, 3.0%)
```

For level `i`:

```text
buy_i    = centre / (1 + s)^i
target_i = centre / (1 + s)^(i - 1)
```

The hard lower boundary remains three steps below the centre. A campaign lasts
at most seven trading sessions. No new lot may be bought during the final two
sessions.

Every lot is 100 shares. Maximum inventory is 100 shares in one-level
variants and 200 shares in the two-level variant. Quantity never increases
geometrically.

## Frozen four-variant ablation

Exactly four mechanics are compared:

| Variant | Reclaim | Crash veto | Levels |
|---|---:|---:|---:|
| `anchor_touch_1` | none | off | 1 |
| `anchor_reclaim_1` | 0.25 step | off | 1 |
| `anchor_reclaim_veto_1` | 0.25 step | on | 1 |
| `anchor_reclaim_veto_2` | 0.25 step | on | 2 |

Touch-only entry requires an executable ask at or below the buy level.

For reclaim entry, price must first touch the buy level. In a strictly later
minute, the close must return to or above the level and the executable ask,
including haircut, must remain below:

```text
buy_level × (1 + 0.25 × s)
```

When multiple levels are touched, the deeper eligible level has priority.
Only one state-changing action is permitted per campaign per minute.

## Severe-downtrend veto

The veto is active when at least two of the following are true:

1. leave-one-out market return over 20 sessions is at most -3%;
2. ticker close is at least one ATR below SMA50;
3. residual slope is negative and the most recent residual return is
   negative.

The signal-date veto cancels the pending campaign. During a campaign, the
state is recomputed only from information available before each session. A
trigger permanently disables new buys and sells settled inventory at the
first eligible minute. Unsettled shares wait until T+2.

## T+2-aware inventory rules

- Shares and sale cash settle at 13:00 on T+2.
- A new lot cannot be added while any existing lot is unsettled.
- A sold level cannot re-arm until its cash settles.
- Before each purchase, existing plus proposed inventory must lose no more
  than VND 1.5 million under two consecutive 7% floor sessions, including
  normal fees and tax.
- The grid is never re-anchored downward while inventory exists.
- Remaining settled inventory is liquidated by the end of session seven.

## Execution and costs

Trial 15/16 assumptions remain frozen:

- continuous-session one-minute bid/ask bars;
- 100-share board lots;
- displayed spread no greater than 40 bps;
- displayed queue covers the order when queue data exist;
- order no greater than 5% of matched minute volume;
- 0.15% commission per side;
- 0.10% sell tax;
- 5-bps adverse execution haircut per side;
- HSX tick rounding;
- normal and doubled-cost outcomes on the same price path.

## Portfolio selection

- Rank filled candidates by the causal opportunity score.
- Open at most two new campaigns on an entry date.
- Hold at most three simultaneous campaigns.
- No same-ticker overlap.
- At most two simultaneous campaigns from one sector.
- Two-session ticker cooldown after exit.

These rules replace Trial 16's one-per-sector and five-session cooldown, which
were sample constraints rather than direct tail-risk controls.

## In-sample gates

A variant advances only if:

- all nine in-sample folds are valid;
- at least 20 campaigns and 10 target-completing campaigns execute;
- campaigns occur in both 2023 and 2024 and neither year exceeds 75%;
- total and median P&L are positive;
- profit factor is at least 1.20;
- doubled-cost P&L is positive;
- P&L remains positive after removing the best campaign;
- target-cycle gains exceed forced/time losses;
- at least 60% of active folds are profitable;
- no ticker contributes more than 40% of positive P&L;
- highest opportunity-score quintile target rate exceeds the lowest quintile.

Eligible variants rank by total P&L, profit factor, doubled-cost P&L and
variant name. If none is eligible, validation remains unopened.

## Internal-validation gates

The single selected variant must have:

- at least 10 campaigns and five target-completing campaigns;
- positive total and median P&L;
- profit factor at least 1.00;
- positive doubled-cost P&L;
- positive P&L after removing its best campaign;
- target gains at least equal to forced/time losses;
- positive opportunity-score quintile spread;
- no campaign loss worse than VND 1.5 million.

Only a complete pass creates a cryptographic final-OOS lock.
