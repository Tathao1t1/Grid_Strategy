# Trial 9 dynamic inventory-aware grid result

## Decision

- Status: `exploratory_not_viable`
- Independent validation: no
- Live authorization: no
- Final-test data used: no

Trial 9 implemented dynamic bounds, geometric spacing, a 0.75-ATR buffer,
increasing intended size toward lower extremes, inventory skew, a 1.5%-NAV
stress budget and deep-downtrend shutdowns. The increasing-size grid amplified
losses during the exact paths where mean reversion failed.

## Activity

| Metric | Result |
|---|---:|
| Activation candidates | 219 |
| Portfolio-selected campaigns | 65 |
| Campaigns with at least one fill | 27 |
| Target sales | 27 |
| Deep-trend shutdowns | 19 |
| Buffered-lower shutdowns | 20 |
| Maximum simultaneous campaign inventory | 500 shares |

The broad gate generated many activations, but static geometric levels often
did not fill before the campaign ended or shut down.

## Economics

| Metric | Result |
|---|---:|
| Total net P&L | -VND 6,247,404 |
| Median campaign P&L | -VND 11,558 |
| Profit factor | 0.0220 |
| Normal target gains | +VND 343,052 |
| Risk/time losses | -VND 6,465,267 |
| Doubled-cost P&L | -VND 7,887,797 |
| P&L after removing best campaign | -VND 6,296,791 |
| Worst campaign | -VND 1,717,989 |

Eleven executed campaigns made money and sixteen lost money. Unlike the
earlier grids, even the median campaign was negative.

## Distance-based inventory result

Campaign P&L conditional on using each distance was:

```text
nearest level used       -VND 3,263,685
middle level used        -VND 6,061,336
farthest level used      -VND 2,382,849
```

These conditional groups overlap when a campaign trades several levels, but
every group is negative. The farthest-level economic gate failed.

The clearest failure was MWG beginning 2025-03-21:

- bought 100, 200 and 300 shares across the three distances;
- completed two target sales;
- later entered both deep-trend and buffered-lower shutdown;
- gapped through the boundary;
- campaign P&L was -VND 1,717,989.

Two successful grid sales did not compensate for the remaining enlarged
inventory loss.

## Why the stress budget did not guarantee the loss

The pre-buy stress check values inventory at H. It reduced one order and
cancelled one order, but H is not an executable guarantee:

- prices can gap below H;
- locked shares must wait for T+2;
- different lots can settle at different times;
- the largest inventory may occur before a later shutdown.

Consequently, the worst realized campaign exceeded the nominal
VND 1.5 million stress allowance.

## Conclusion

The slide formula

```text
q_i = q_0 × r^i
```

is appropriate only when the probability of reversion remains stable as
distance increases. The development evidence shows the opposite: large
distance is also evidence of possible regime failure.

Inventory skew and trend shutdown are valuable controls, but they act after
some inventory has already accumulated. They cannot turn a negative
distance-conditioned expectancy into a positive one.

The implementation is useful for the Monday presentation as a controlled
demonstration of:

1. dynamic grid construction;
2. distance-based sizing;
3. inventory-aware scaling;
4. deep-trend shutdown;
5. why risk limits must dominate the quantity formula.

It should not be deployed with live capital.

