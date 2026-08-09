# Trial record: GRID-LONG-VCB-V2-RISK

## Status

- Research state: rejected by predeclared development gates
- Implementation state: permanently deleted on 2026-07-23
- First implementation date: 2026-07-23
- Fixed ticker: VCB
- Initial capital: VND 100,000,000
- Final holdout inspected for performance: no
- Previous rejected design: `REJECTED_GRID_LONG_V1.md`
- Deleted simulator SHA-256:
  `788e136a5c85bf1fee06d8727063235252e04aa78a541bd6d73289c4d7f5d83f`
- Deleted guide SHA-256:
  `4c3b7bae5b0b8bdf5ac4a12dd9e016183b8b63f61b4d6edf3dfc18695f2f7e0f`
- Deleted tests SHA-256:
  `8e5b06393feac530e47dc0f7ded134562d703740ea209a91c4c1cde69299e629`

## Material change from version 1

Version 1 increased inventory as price fell and held up to 80% directional
exposure. Version 2 starts flat, permits one 100-share lot, and cannot average
down. It sizes the order from an exact three-floor-session cash stress instead
of a desired capital allocation.

The 100-share constraint means version 2 is a single-cell mean-reversion
grid. This limitation is intentional; forcing a conventional multi-level
grid into a VND 100 million account would violate the declared risk budget.

## Frozen base settings

- 2% campaign settlement-stress budget
- 10% maximum position notional
- 5% high-water-mark portfolio kill switch
- One 100-share lot maximum
- No base inventory and no averaging down
- 1.5% or ATR14 arithmetic step, whichever is larger
- T-1 SMA20, return, ER10, ATR14, floor, and reference-reset entry vetoes
- Two-step campaign stop, 1% campaign-loss trigger, and 20-session time stop
- 20-session cooldown after a risk exit
- T+2 afternoon settlement model
- 5% minute-volume participation
- 40-bps entry/take-profit spread gate
- 0.15% commission, 0.10% sell tax, and 0.05% side-specific execution charge

The deleted implementation's frozen definitions are retained below.

## First-fold implementation smoke test

The specification above was frozen before running the first completed code
smoke test. The smoke test is not an acceptance result and will not be used
to tune thresholds.

`wf_01` in-sample result:

- Status: complete
- Period: 2022-01-04 to 2022-12-30
- Net return: -0.16117%
- Daily Sharpe: -0.4865
- Maximum drawdown: -0.3308%
- Profit factor: 0.6357
- Buys / sells: 5 / 5
- Normal take-profit P&L: +VND 109,300
- Risk-exit P&L: -VND 270,470
- Transaction costs: VND 201,170
- Gross turnover: 0.8046× initial capital
- Kill switch: not triggered
- Ending inventory: zero

Interpretation: risk severity and turnover were far lower than version 1, but
the economic hypothesis failed this first fold because risk-exit losses again
exceeded ordinary grid profit. No parameter is changed in response. The next
valid test is the unchanged specification across all in-sample folds,
followed by the predeclared acceptance gates.

## Predeclared training gates

- Positive median training-fold return and Sharpe
- Median profit factor above 1.10
- Aggregate risk-exit losses no larger than normal grid profits
- No fold maximum drawdown at or below -5%
- Cost drag below 1% of capital and below 35% of gross trading profit
- Positive doubled-cost median return and profit factor above 1
- No accounting, settlement, future-data, or corporate-action invariant breach

Failure of these gates rejects or redesigns the hypothesis without opening
the final holdout.

## Unchanged in-sample fold result

All fifteen rolling 12-month in-sample windows used the same code and
parameters. Adjacent windows overlap by about ten months, so they are
robustness views rather than fifteen independent experiments.

| Measurement | Base costs | Doubled commission/slippage |
|---|---:|---:|
| Positive / negative folds | 3 / 12 | 0 / 15 |
| Median net return | -0.1159% | -0.3103% |
| Median daily Sharpe | -0.2442 | -0.7554 |
| Median profit factor | 0.6845 | 0.3810 |
| Aggregate take-profit P&L | +VND 2,976,150 | +VND 2,158,670 |
| Aggregate risk-exit P&L | -VND 5,014,070 | -VND 7,018,330 |
| Aggregate modeled costs | VND 3,546,200 | VND 6,386,220 |
| Worst drawdown | -0.6149% | -0.7558% |
| Maximum admitted stress / capital | 1.9836% | 1.9986% |
| Buy / sell fills | 81 / 80 | 81 / 80 |
| Kill switches | 0 | 0 |

`wf_02` ended with one 100-share position. It is explicitly labeled
`complete_open_position`; terminal return uses net liquidation value. No
future price was used to close it.

The generated fold outputs and pre-audit outputs were permanently deleted
with the simulator. Their material aggregate results are preserved in this
record.

## Decision

The redesign successfully hardened loss magnitude:

- no averaging down;
- one-lot stress stayed below the 2% budget;
- worst observed drawdown stayed well below the 5% kill switch;
- no settlement, cash, quantity, future-data, or corporate-action invariant
  failed.

It did not create an economic edge:

- median return, Sharpe, and profit factor all failed;
- risk exits again cost more than completed grid cycles earned;
- modeled base costs consumed about 96.7% of aggregate gross realized profit;
- every doubled-cost fold lost money.

Therefore `GRID-LONG-VCB-V2-RISK` is rejected and did not advance to
walk-forward OOS or the final holdout. Only this rejection record is retained
as evidence that safer sizing alone does not repair a weak payoff hypothesis.
Any successor must be a materially new entry/exit hypothesis, not a threshold
tune of this version.
