# Pre-registration: Trial 18 market equilibrium and economic target

## Status

Trial 18 is an **exploratory post-Trial-17 repair**. Its design uses knowledge
of Trial 17's loss decomposition. Development results cannot be presented as
independent confirmation, and the locked final minute holdout remains
unopened unless every declared gate passes.

## Hypothesis

> A centre estimated from a beta-adjusted residual-price equilibrium will
> distinguish ticker-specific displacement from a lagging raw-price median.
> Requiring every filled lot's target to preserve a minimum after-cost profit
> will prevent reclaim confirmation from consuming the intended grid edge.

## Universe and partitions

Execution universe:

```text
HPG, MBB, MWG, SSI, TCB, VCB, VND, VPB
```

FPT and PNJ remain in the leave-one-out market proxy but cannot create
positions.

- In-sample mechanics comparison: `wf_01`–`wf_09`,
  2023-01-03–2024-06-28.
- Conditional internal validation: `wf_10`–`wf_15`,
  2024-07-01–2025-07-11.
- Locked minute final OOS: 2025-07-14–2026-06-30.

## Causal market-adjusted equilibrium

For each ticker and signal date, use the preceding 60 daily log returns. The
leave-one-out market return is the equal-weight mean log return of the other
nine stocks:

```text
m_t = mean(log(P_j,t / P_j,t-1)), j != ticker
```

Estimate:

```text
beta = cov(r_ticker, m) / var(m)
epsilon_t = r_ticker,t - beta × m_t
S_k = cumulative sum of epsilon through k
```

The residual-price equilibrium is the median of the final 20 values of the
60-session cumulative residual path:

```text
S_equilibrium = median(S[-20:])
raw_centre = signal_close × exp(S_equilibrium - S_current)
```

To prevent unstable short-window beta estimates from creating an arbitrarily
distant target, the upward correction is capped at two ATR20 values:

```text
centre = min(raw_centre, signal_close × (1 + 2 × ATR20_fraction))
```

The centre is rounded to a legal HSX sell tick, calculated only from
signal-close information, frozen for the campaign and never moved while
inventory is held.

The residual-spread AR(1) coefficient is recorded for diagnosis but is not a
hard gate.

## Signal and severe-downtrend veto

A pending campaign requires:

```text
residual_z5 <= -0.50
signal close < market-adjusted equilibrium centre
60-session median daily value >= VND 10 billion
ATR20 / close <= 5%
no unverified or detected reference-price reset
```

Trial 17's severe-downtrend veto is preserved unchanged. Entry is prohibited
when at least two are true:

1. leave-one-out market return over 20 sessions is at most -3%;
2. ticker close is at least one ATR below SMA50;
3. residual slope and most recent residual return are both negative.

The same veto is recomputed from prior-session information during the
campaign. A trigger permanently cancels new buys and exits settled inventory
at the first executable minute.

The causal opportunity score remains:

```text
-residual_z5
+ (centre - signal_close) / (centre × ATR20_fraction)
```

No fitted selection model is used.

## Grid and execution

Trial 17's least-negative mechanics remain fixed:

- seven-session maximum campaign;
- geometric step `clamp(0.75 × ATR20 / close, 1.5%, 3.0%)`;
- two 100-share lower levels;
- deeper touched level receives priority;
- touch followed by a strictly later reclaim;
- reclaim cap of 0.25 grid step above the buy level;
- no new lot while any held lot is unsettled;
- no new buys in the final two sessions;
- hard shutdown three grid steps below the centre;
- two-floor aggregate stress loss no greater than VND 1.5 million;
- maximum three simultaneous campaigns;
- maximum two simultaneous campaigns from one sector;
- two-session ticker cooldown.

Commission, tax, spread, queue, matched-volume participation, 5-bps adverse
execution, HSX ticks and T+2 settlement remain unchanged from Trials 15–17.

## Per-fill economic target

After the actual buy execution price is known, calculate the normal-cost
acquisition cash `A`, including 0.15% buy commission.

For minimum net profit fraction `g`, find the lowest legal HSX target price
`T_economic` whose normal-cost sale cash, after 0.15% sell commission and
0.10% sell tax, satisfies:

```text
net_sale_cash(T_economic) - A >= g × A
```

The lot's frozen target is:

```text
max(next structural grid level, T_economic)
```

Targets never move downward after a fill. Normal and doubled-cost simulations
use the same formula and price path; the doubled-cost result remains a stress
test rather than a target chosen to rescue stressed profitability.

## Frozen target-margin ablation

Exactly four target floors are evaluated:

| Variant | Minimum net profit after normal costs | Eligible to advance |
|---|---:|---:|
| `equilibrium_control_0` | 0.00% | No; diagnostic control |
| `equilibrium_net_50` | 0.50% | Yes |
| `equilibrium_net_75` | 0.75% | Yes |
| `equilibrium_net_100` | 1.00% | Yes |

The zero-floor control measures the centre change separately. It cannot be
selected even if profitable.

## In-sample and validation gates

The Trial 17 gates remain unchanged. An eligible positive-margin variant must
have:

- nine valid in-sample folds;
- at least 20 campaigns and 10 target-completing campaigns;
- observations in both 2023 and 2024, with neither year above 75%;
- positive total and median P&L;
- profit factor at least 1.20;
- positive doubled-cost and best-campaign-removed P&L;
- target gains greater than forced/time losses;
- at least 60% positive active folds;
- no ticker above 40% of positive P&L;
- positive top-minus-bottom opportunity-score quintile target-rate spread.

The single best eligible variant advances to internal validation. Validation
requires at least 10 campaigns, five target campaigns, positive total,
median, doubled-cost and best-removed P&L, profit factor at least 1.00, target
gains covering other losses, positive score spread and no campaign below
−VND 1.5 million.

Only a complete validation pass creates a final-OOS lock.
