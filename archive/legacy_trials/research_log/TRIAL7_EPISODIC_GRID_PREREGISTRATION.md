# Pre-registration: TRIAL7-HSX-CONFIRMED-EPISODIC-GRID

## Research state

- Status: frozen before any Trial 7 outcome is calculated
- Scope: daily Stage-A development walk-forward study
- Universe: FPT, HPG, MBB, MWG, PNJ, SSI, TCB, VCB, VND, VPB
- Final test: locked; numeric final-test prices are not parsed
- Predecessor: Trial 6, which generated enough signals but failed to rank them

## Hypothesis

> After a broad relative-price deviation begins reversing, a temporary,
> two-level, equal-lot grid with a frozen centre, cost-aware spacing, no
> martingale sizing and a fixed expiry earns positive net campaign expectancy.

Trial 7 is rule-based. It does not refit Trial 6's failed logistic model.

## Walk-forward structure

Trial 7 reuses the 15 non-overlapping Trial 5/6 deployment folds. Training
dates provide point-in-time feature history; campaign outcomes are measured
only in the following two-month deployment. A complete T through T+15 path
must remain inside the deployment fold.

## Activation signal

For entry at the official open on T, all signal information ends at T-1:

- standardized five-session leave-one-out-market residual <= -0.75;
- latest one-session residual return > 0;
- close[T-1] > close[T-2];
- leave-one-out market five-session return > -5%;
- median 60-session traded value >= VND 10 billion;
- ATR20 / close is positive and <= 5%;
- latest 60 sessions contain no inferred or unverifiable reference reset.

The leave-one-out residual calculation is identical to Trial 6 and remains a
research proxy, not a claim of market neutrality.

## Frozen grid

At T open:

```text
g = clamp(ATR20 / close[T-1], 1.5%, 3.0%)
B0 = T open
U0 = B0 * (1 + g)
B1 = B0 / (1 + g)
U1 = B0
H  = B0 / (1 + g)^3
```

Every level is one 100-share lot. B0 is acquired once at T open. B1 is
optional and never larger than B0.
Derived order and boundary prices are rounded conservatively to modeled HSX
legal ticks.

B1 uses causal touch-then-reclaim behavior:

1. a completed session low touches B1;
2. that session closes above B1 and above its open;
3. on the next session, buy at the official open only when the open is no
   higher than B0 and no risk exit is active.

This deliberately avoids assuming an intraday low occurred before a later
reversal. Each level may be purchased and sold at most once; Trial 7 tests the
grid payoff, not repeated turnover.

## Settlement, costs and path ordering

Shares bought on T become sellable on the second following observed session.
The same applies independently to B1. Target touches before settlement do not
create a sale.

Within a daily bar, adverse events receive priority:

1. opening gap through H;
2. intraday touch of H;
3. lower-level touch/reclaim state update;
4. sale of settled inventory at U0 or U1.

If H triggers, new buys stop. Settled inventory exits at the adverse open
after a gap or at H after a touch. Locked shares exit at the next official
open on or after their settlement session. This daily model does not claim a
guaranteed minute fill.

Any remaining inventory exits at the T+15 close. A reference reset anywhere
from signal-feature history through campaign exit quarantines the candidate.

Exact cash P&L includes one 100-share lot and:

```text
buy commission       0.15%
sell commission      0.15%
sell tax             0.10%
execution haircut    0.05% per side
```

A doubled-cost diagnostic doubles every listed friction.

## Portfolio-style episode selection

All activation candidates are reported. Independent selected episodes use:

- at most three concurrent campaigns;
- at most one active ticker per frozen sector;
- no overlapping campaign in the same ticker;
- five sessions of ticker cooldown after exit;
- ranking by most negative residual z-score, then strongest one-day residual
  rebound, then ticker.

Selection never reads campaign outcomes.

## Sample policy

The primary sample gate is deliberately calibrated to the available
non-overlapping 2023 through June 2025 deployment history:

- all 15 folds valid;
- at least 75 activation candidates;
- at least 40 selected independent episodes;
- at least 15 ordinary target sales;
- all three entry years represented by at least five episodes;
- no year contributes more than 55% of selected episodes.

Failure produces `inconclusive_sample`.

The report also evaluates declared sensitivity floors of 30 and 20 selected
episodes. These are diagnostics only and can identify whether more untouched
history could make the hypothesis evaluable. They cannot change the Trial 7
decision or authorize Stage B.

## Economic gates

With adequate sample, every gate must pass:

1. total exact-VND campaign P&L is positive;
2. median campaign P&L is positive;
3. exact-VND campaign profit factor >= 1.20;
4. at least 60% of active folds have positive aggregate P&L;
5. ordinary target-sale gains cover risk- and time-exit losses;
6. doubled-cost total P&L is positive;
7. doubled-cost profit factor >= 1.00;
8. total P&L remains positive after removing the best episode;
9. no one ticker contributes more than 40% of positive P&L;
10. selected episodes with a B1 fill are profitable in aggregate.

Failure produces `rejected_development`. Passing produces
`passed_development_screen`, which permits a separately preregistered
minute-execution Stage B only.

## Prohibited response to results

After the authoritative result is opened, changing the residual threshold,
confirmation, grid spacing, number or size of levels, horizon, risk boundary,
settlement, costs, selection, or gates creates a new numbered trial.

In particular, an inconclusive result may not be converted into a pass by
loosening its gate. More untouched history, a broader preregistered universe,
or a new hypothesis is required.
