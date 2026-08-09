# Pre-registration: Trial 11 optimized trend-conditioned pullback grid

## Research objective

Trial 11 is the canonical assessed experiment:

```text
hypothesis
→ in-sample parameter optimization
→ frozen internal validation
→ configuration lock
→ one final out-of-sample run, only if validation passes
```

Trials 1–10 are hypothesis formation. Their repeated use of development data
means Trial 11's internal results are not fully independent. The final-test
period remains the only untouched confirmation sample.

## Hypothesis

> A temporary long grid has positive net expectancy when it buys a
> stock-specific short-term pullback inside a positive medium-term ticker and
> market trend, uses cost-aware spacing, limits inventory to two equal lots and
> exits when the supporting trend fails.

The grid is an execution and payoff mechanism. It does not attempt to average
down during a structural decline.

## Data partitions

Observed global trading sessions are divided once:

| Partition | Dates | Use |
|---|---|---|
| In-sample optimization | 2022-01-04 through 2024-06-28 | Parameter search |
| Internal validation | 2024-07-01 through 2025-07-11 | One-time development check |
| Final OOS | 2025-07-14 through 2026-07-16 | One frozen confirmation |

The final OOS is not numerically parsed during optimization or validation.
Trial 11 advances to it only if every internal-validation gate passes.

## Point-in-time signal

For entry at the official open on T, all calculations end at T-1.

Fixed conditions:

- close[T-1] > SMA50[T-1];
- SMA20[T-1] > SMA50[T-1];
- latest one-session residual return > 0;
- close[T-1] > close[T-2];
- median 60-session traded value >= VND 10 billion;
- ATR20 / close is positive and <= 5%;
- the latest 60 reference-price observations are valid and contain no reset.

The residual uses Trial 6's leave-one-out equal-weight market proxy.

Optimized signal conditions:

- leave-one-out market 20-session return > `market_return20_min`;
- residual z5 <= `residual_z_max`.

## Grid

At T open:

```text
g = clamp(spacing_atr_multiplier × ATR20 / close[T-1], 1.5%, 4.0%)
B0 = T open
U0 = B0 × (1 + g)
B1 = B0 / (1 + g)
U1 = B0
H  = B0 / (1 + g) ** stop_steps
```

- B0 buys one 100-share lot at T open.
- B1 is either disabled or one additional 100-share lot.
- B1 requires a completed touch/reclaim followed by next-session entry.
- No increasing quantity, repeated reset or downward re-anchor is allowed.
- Derived prices use modeled HSX tick rounding.

## Exits and execution

- Each lot becomes sellable on the second following observed session.
- A settled lot sells at its target after a daily high reaches it.
- Target touches before settlement do not sell.
- An opening gap through H exits settled shares at the adverse open.
- An intraday H touch exits settled shares at H.
- Locked shares exit at the first open on or after settlement.
- Prior-session close <= SMA50 or market-return20 <= 0 triggers trend exit.
- All remaining inventory exits at the frozen maximum horizon.
- No buy may occur too late to settle before the time exit.

Costs:

```text
buy commission       0.15%
sell commission      0.15%
sell tax             0.10%
execution haircut    0.05% per side
```

A doubled-cost diagnostic doubles every listed friction.

## Portfolio construction

- Maximum three concurrent campaigns
- Maximum one active ticker per frozen sector
- Five-session ticker cooldown after exit
- Rank candidates by most negative residual z5, strongest one-day residual
  rebound, then ticker
- Empty capacity remains cash

Selection is chronological and does not inspect campaign P&L.

## Frozen parameter search

The Cartesian search contains 216 configurations:

```text
market_return20_min       ∈ {0.00, 0.02}
residual_z_max            ∈ {-0.50, -0.75, -1.00}
spacing_atr_multiplier    ∈ {0.75, 1.00, 1.25}
lower_level_enabled       ∈ {false, true}
stop_steps                ∈ {2, 3}
maximum_horizon           ∈ {10, 15, 20}
```

Quantity, costs, confirmation, trend averages, settlement and portfolio rules
are not optimized.

## In-sample optimization objective

Campaigns are grouped into calendar half-years. A configuration is eligible
for selection only when:

- at least 25 independent executed campaigns;
- total and median campaign P&L are positive;
- exact-VND profit factor >= 1.10;
- P&L remains positive after removing the best campaign;
- at least 60% of active half-years have positive aggregate P&L.

Eligible configurations are ranked by:

```text
robust_score =
    annualized campaign-return Sharpe
    - 0.50 × abs(worst campaign return)
    - 0.25 × abs(10th-percentile campaign return)
```

Then by doubled-cost P&L, ordinary P&L, campaign count and canonical parameter
JSON. If no configuration passes, Trial 11 stops without validation.

## Internal-validation gates

The single chosen configuration runs unchanged from 2024-07-01 through
2025-07-11. It advances only if:

- at least 10 independent executed campaigns;
- total P&L is positive;
- median P&L is positive;
- profit factor >= 1.00;
- doubled-cost P&L is positive;
- P&L after removing the best campaign is positive;
- target gains cover trend/risk/time losses;
- worst campaign is no worse than -1.5% of VND 100 million.

Failure freezes status `rejected_internal_validation`; final OOS stays locked.

## Final OOS

If validation passes:

1. write an immutable selected-configuration lock containing source, data,
   preregistration and parameter hashes;
2. execute 2025-07-14 through 2026-07-16 exactly once;
3. report the result regardless of sign;
4. prohibit every subsequent parameter change.

Final success requires:

- at least 10 campaigns;
- positive total and median P&L;
- profit factor >= 1.00;
- positive doubled-cost P&L;
- positive P&L after removing the best campaign;
- target gains covering other losses.

The benchmark is reported but is not an optimization target.

