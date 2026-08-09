# Pre-registration: TRIAL6-HSX-POOLED-MEAN-REVERSION-EDGE

## Research state

- Status: frozen before any Trial 6 development outcome is calculated
- Scope: ten-stock development walk-forward data only
- Final-test period: locked and unavailable to the study
- Trial type: daily Stage-A edge study, not a minute execution backtest
- Predecessor: `TRIAL5-HSX-ROTATION-LONG-GRID`

## Decision inherited from Trial 5

Trial 5 produced only nine completed campaigns. Four target exits earned
VND 568,359 while five forced or scheduled exits lost VND 1,976,316. Its
selector and static first-touch entry therefore failed both the sample and
economic gates.

Trial 6 does not loosen Trial 5. It tests a different hypothesis before any
new grid simulator is built.

## Hypothesis

> A pooled, point-in-time model across the fixed ten-stock universe can rank
> temporary ticker-specific downside deviations so that the highest estimated
> net-EV one-cell campaigns have positive, sufficiently distributed
> out-of-sample expectancy after modeled costs and adverse gap execution.

Trial 6 predicts the campaign outcome rather than classifying a ticker as
historically sideways. It prohibits averaging down.

## Universe and chronological design

The frozen universe is:

```text
FPT HPG MBB MWG PNJ SSI TCB VCB VND VPB
```

The existing Trial 5 split is reused unchanged:

- preceding 12 calendar months: fit features, labels, scaler and model;
- following non-overlapping two months: untouched deployment predictions;
- 15 deployment folds from 2023-01-03 through 2025-06-30;
- final-test rows from 2025-07-14 through 2026-07-16 are rejected before
  numeric prices are parsed.

The last ten training sessions cannot start a training label. This purges
forward outcomes from the training/deployment boundary.

## Market residual

No external market or sector index is currently present in the sealed project
data. Trial 6 therefore uses a disclosed research proxy: for each ticker and
session, the market return is the equal-weight close-to-close return of the
other nine tickers.

For each feature date, beta is fitted by OLS with an intercept over the latest
60 completed return sessions. Residual returns over the latest 20 sessions use
that single point-in-time beta:

```text
residual return = ticker return - beta * leave-one-out market return
```

This is a relative-movement feature, not a claim of market neutrality.

## Broad candidate gate

Every condition uses information through T-1 for entry at the official open
on T:

- at least 61 completed daily observations exist;
- the latest 60 observations have verifiable reference-price fields and no
  inferred reset;
- median daily traded value over 60 sessions is at least VND 10 billion;
- ATR20 is positive and no greater than 5% of price;
- the standardized five-session residual return is at or below -0.75.

No SMA, RSI, ADX, efficiency-ratio, candlestick or reversal-confirmation gate
is used. Reversal and breakout measurements are continuous model features.

## Frozen model features

The pooled feature vector is:

1. five-session residual z-score;
2. one-session residual return;
3. five-session residual return;
4. twenty-session residual slope;
5. downside residual semivolatility;
6. residual AR(1) coefficient;
7. ticker five-session raw return;
8. leave-one-out market five-session return;
9. ATR20 divided by close;
10. log median daily traded value.

Missing or non-finite features make a date ineligible; they are never imputed
from future data.

Within every fold, features are standardized using training candidates only.
A deterministic L2-regularized pooled logistic regression is fitted to predict
whether the target is reached before the downside/time exit. The intercept is
not regularized. No ticker dummy or fitted sector parameter is used.

If the training labels contain fewer than 30 candidates, fewer than five
targets, fewer than five non-targets, or the optimizer fails, the fold is
invalid rather than silently falling back to a hand-built score.

## Campaign label

Entry is one 100-share research lot at the official open on T with a
five-basis-point adverse entry haircut.

Let:

```text
d = clamp(ATR20 / close[T-1], 1.5%, 3.0%)
target = entry * (1 + d)
downside boundary = entry * (1 - d)
maximum horizon = T through T+10
```

Prices are rounded to whole VND for the daily edge study. This is not a claim
of minute fillability.

For each session:

- an opening gap at or below the downside boundary exits at the adverse open;
- otherwise, a low touching the downside boundary exits at the boundary;
- an opening gap at or above the target receives only the target price;
- otherwise, a high touching the target exits at the target;
- if both intraday barriers are touched without an opening gap, the downside
  is assumed first;
- if neither barrier is reached, T+10 closes the campaign.

The label is one only for a target-first exit. All cash P&L includes:

```text
buy commission       0.15%
sell commission      0.15%
sell tax             0.10%
execution haircut    0.05% per side
```

The doubled-cost diagnostic doubles commissions, tax and both execution
haircuts. Any inferred reference reset from T through exit quarantines the
candidate.

## Estimated economic value and selection

For each fold, the training target rate is combined with model probabilities.
Mean exact-VND winning and non-winning training P&L define:

```text
estimated EV = p(target first) * mean training win P&L
             + (1 - p(target first)) * mean training non-win P&L
```

Only strictly positive estimated EV may be selected. Each deployment session
ranks available candidates by estimated EV, then probability, then ticker.

Portfolio-style research selection permits:

- at most three concurrent campaigns;
- at most one concurrent ticker per frozen sector group;
- no overlapping campaign in the same ticker;
- a five-session cooldown for a ticker after its prior campaign exits.

Selection uses the precomputed causal prediction but not the future outcome.
The future exit date is used only to release research capacity after a
campaign has already been selected.

## Frozen evaluation units

All eligible OOS candidates measure prediction quality. Selected,
non-overlapping campaigns measure economics. Multiple daily candidates inside
one open campaign are not counted as independent executed evidence.

Reported diagnostics include:

- candidate and selected-campaign counts;
- calendar-year and fold distribution;
- Brier score versus the fold training base-rate forecast;
- probability-decile outcome and P&L monotonicity;
- exact-VND net P&L, median P&L and profit factor;
- target, downside, time and gap-exit counts;
- doubled-cost economics;
- maximum concurrent campaigns;
- performance with the single best campaign removed.

## Decision gates

### Integrity and sample

1. All 15 deployment folds are valid.
2. At least 100 eligible OOS candidate events exist.
3. At least 60 selected non-overlapping campaigns exist.
4. At least 30 selected campaigns reach their target.
5. At least three entry calendar years each contain ten selected campaigns.
6. No one entry year contributes more than 45% of selected campaigns.

Failure is `inconclusive_sample`.

### Predictive and economic

With adequate sample, every gate must pass:

1. pooled OOS Brier score is lower than the pooled base-rate Brier score;
2. realized target rate in the highest probability quintile exceeds the
   lowest quintile;
3. total exact-VND net P&L is positive;
4. median selected-campaign net P&L is positive;
5. exact-VND profit factor is at least 1.20;
6. at least 60% of active folds have positive selected-campaign P&L;
7. target gains are at least as large as the absolute combined downside and
   time-exit losses;
8. doubled-cost total P&L is positive;
9. doubled-cost profit factor is at least 1.00;
10. total P&L remains positive after removing the single best campaign.

Failure is `rejected_development`. Passing is
`passed_development_screen`, which authorizes a separately preregistered
minute-level Trial 6 Stage B; it does not authorize live trading.

## Prohibited changes

After the first authoritative development result is opened, Trial 6 v1 may
not change the universe, folds, proxy, feature definitions, candidate
threshold, barriers, horizon, costs, model, selection rules or gates. Any such
change is a separately named and preregistered research trial.

