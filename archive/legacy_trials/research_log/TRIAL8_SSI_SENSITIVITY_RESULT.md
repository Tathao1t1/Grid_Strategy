# Trial 8 SSI exploratory sensitivity result

## Decision

- Status: `no_exploratory_viable_variant`
- Variants: 3 gates × 3 lot sizes = 9
- Data: previously used development data
- Final test used: no
- Independent validation: no

Neither looser activation nor larger SSI orders produced a viable grid.

## Results at one 100-share lot per level

| Gate | Candidates | Independent episodes | Net P&L | Profit factor | Doubled-cost P&L | Worst episode |
|---|---:|---:|---:|---:|---:|---:|
| Strict | 14 | 8 | -314,655 | 0.587 | -499,874 | -560,864 |
| Moderate | 16 | 10 | -428,507 | 0.539 | -637,474 | -560,864 |
| Loose confirmation | 29 | 14 | -144,627 | 0.827 | -399,905 | -337,046 |

The loose-confirmation variant was the least unfavorable. It generated 14
independent episodes and 14 target sales, but still failed every core
profitability requirement.

## Lot-size sensitivity

Increasing quantity scaled P&L and risk approximately linearly:

| Gate | 100-share P&L | 200-share P&L | 300-share P&L |
|---|---:|---:|---:|
| Strict | -314,655 | -629,315 | -943,974 |
| Moderate | -428,507 | -857,020 | -1,285,531 |
| Loose confirmation | -144,627 | -289,261 | -433,888 |

Profit factors were effectively unchanged within each gate. Buying more does
not improve expectancy; it only magnifies the same payoff.

At 300 shares per level, the loose variant's worst episode lost
VND 1,011,140, breaching the exploratory 1% loss budget on VND 100 million.
The strict and moderate 200- and 300-share variants also breached that limit.

## Failure anatomy

The loose 100-share variant won 11 of 14 episodes, yet lost money:

```text
normal target gains     +VND 691,693
risk/time losses        -VND 836,320
net result              -VND 144,627
```

Calendar results:

| Year | Episodes | Net P&L |
|---|---:|---:|
| 2023 | 3 | +162,717 |
| 2024 | 8 | -62,257 |
| 2025 through development end | 3 | -245,087 |

Three risk exits caused the negative aggregate result. This repeats the
central grid failure: a high winning frequency conceals a poor loss
distribution.

## Implication

SSI should not be anchored as a profit-validated ticker. It can still be used
as the Monday engineering demonstration because:

- it generates understandable target cycles;
- the complete grid and settlement behavior can be shown;
- it illustrates why win rate is not sufficient.

For paper trading, retain 100 shares per level. Larger lots are unsupported.
The loose-confirmation rule may be monitored prospectively because it creates
more observations, but the present result does not establish an edge.

