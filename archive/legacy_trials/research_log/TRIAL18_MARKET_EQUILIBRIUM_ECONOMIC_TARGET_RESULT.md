# Trial 18 result: market equilibrium and economic target

## Decision

No Trial 18 variant passed the in-sample gates. Internal validation and the
locked final minute holdout remain unopened.

The market-adjusted equilibrium generated a large, directionally ordered
sample, but its deviations did not revert profitably within the seven-session
grid horizon. Minimum economic target floors changed the target on some lots;
they could not repair losses caused by hard-lower, severe-veto and time exits.

Trial 18 is exploratory because its design followed observation of Trial 17.

## Frozen target-floor ablation

| Variant | Campaigns | Target campaigns | Net P&L | PF | Doubled-cost P&L |
|---|---:|---:|---:|---:|---:|
| Market-equilibrium control | 80 | 31 | −VND 4,254,550 | 0.297 | −VND 5,263,975 |
| Minimum 0.50% net target | 80 | 31 | −VND 4,254,550 | 0.297 | −VND 5,263,975 |
| Minimum 0.75% net target | 80 | 30 | −VND 4,264,525 | 0.298 | −VND 5,273,935 |
| Minimum 1.00% net target | 80 | 29 | **−VND 4,254,549** | **0.300** | **−VND 5,263,975** |

No row was eligible. The one-VND nominal difference in the 1.00% row is not
economically meaningful.

## Least-negative diagnostic

| Metric | Result |
|---|---:|
| Campaigns | 80 |
| Target-completing campaigns | 29 |
| Median campaign P&L | −VND 54,205 |
| Net P&L | **−VND 4,254,549** |
| Profit factor | **0.300** |
| Target-cycle gains | +VND 1,619,405 |
| Forced/time losses | **−VND 6,347,578** |
| Grid-economic P&L | **−VND 4,728,173** |
| Doubled-cost P&L | **−VND 5,263,975** |
| P&L after best campaign removed | **−VND 4,573,340** |
| Annualized two-month-fold Sharpe | **−3.688** |
| Realized closed-campaign maximum drawdown | **VND 4,254,549 / 4.255%** |
| Worst campaign | −VND 475,781 |
| Positive active-fold fraction | **0%** |
| Opportunity-score target-rate quintile spread | +26.92 percentage points |

The maximum drawdown is based on campaign-closure equity, not a
minute-marked portfolio curve.

## Economic-target diagnosis

The structural geometric target already exceeded the 0.50% after-cost floor
for every selected fill. Consequently, the zero and 0.50% variants were
identical.

| Minimum floor | Lots whose target increased | Mean gross target distance |
|---|---:|---:|
| 0.00% | 0 / 103 | 1.717% |
| 0.50% | 0 / 103 | 1.717% |
| 0.75% | 9 / 103 | 1.738% |
| 1.00% | 33 / 103 | 1.811% |

Increasing the target cannot improve a campaign that exits through the hard
lower boundary, severe-downtrend veto or time limit. It can also convert a
smaller executable target into a later time exit. The 1.00% floor removed two
target-completing campaigns and left total P&L effectively unchanged.

## Equilibrium diagnosis

The selected sample had:

- median market beta: 0.918;
- median residual-spread AR(1): 0.892;
- centre capped at two ATRs in only 10% of campaigns;
- 25 campaigns triggering the severe-downtrend veto;
- 31 campaigns touching the hard lower boundary;
- 19 campaigns reaching 200 shares.

The positive score-quintile spread shows that larger estimated equilibrium
discounts were associated with more target completions. Nevertheless, every
active fold lost money. Directional ordering did not translate into positive
payoff magnitude.

The residual-price construction treated displacement from the recent
residual median as equilibrium error. In practice, persistent idiosyncratic
repricing can create the same pattern. A short-window beta adjustment removes
broad market movement, but it does not prove that the remaining spread is
stationary or economically mean reverting.

## Ticker decomposition

For the least-negative 1.00% target floor:

| Ticker | Campaigns | Target campaigns | Net P&L |
|---|---:|---:|---:|
| VCB | 9 | 0 | −VND 1,566,660 |
| VND | 9 | 1 | −VND 715,715 |
| MWG | 6 | 3 | −VND 692,620 |
| VPB | 16 | 7 | −VND 518,044 |
| HPG | 13 | 7 | −VND 391,140 |
| TCB | 10 | 4 | −VND 286,872 |
| MBB | 8 | 3 | −VND 80,953 |
| SSI | 9 | 4 | −VND 2,545 |

Every ticker lost money. VCB alone contributed VND 1.567 million of loss and
completed no target campaign, but excluding it post-result would not repair
the broad eight-ticker failure.

## Hypothesis verdict

The hypothesis failed:

1. The beta-adjusted equilibrium increased execution from 48 Trial 17
   campaigns to 80, but it selected persistent repricing as well as temporary
   displacement.
2. The target floors protected nominal profit per completed target, but the
   strategy's problem remained the probability and size of non-target exits.
3. All active folds and all eight tickers lost money.

The result argues against further target widening. The next defensible
research question would have to establish residual-spread stationarity before
grid activation or change the loss distribution, rather than optimize the
profit target again.

## Governance

- In-sample eligible variants: **0 / 4**
- Internal validation: **not run**
- Final minute OOS: **not opened**
- Final lock: **not created**
- Live deployment: **not authorized**

