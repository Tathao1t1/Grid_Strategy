# Final recommendation: reject the tested long-only grid family

## Recommendation

Present the full implementation and the decision not to deploy. SSI may be
used only as an engineering example, not as a profit-validated ticker.

The principal finding is decision-theoretic:

> A Type II error remains possible, but the costs are asymmetric. Rejecting a
> genuinely profitable strategy misses an opportunity; accepting a
> negative-convexity strategy risks capital after repeatedly unfavorable
> evidence.

## Final implemented strategy in one paragraph

Across eight liquid HSX stocks, estimate a 60-session beta-adjusted
residual-price equilibrium against the other stocks. When price is below that
centre and the severe-downtrend veto is off, wait for a lower grid level to be
touched and reclaimed in a later minute. Trade at most two 100-share levels
for seven sessions with 1.5–3.0% ATR-dependent spacing, per-fill after-cost
targets, T+2 inventory, sector caps, a two-floor stress budget and a
three-step catastrophic boundary. Never increase lot size geometrically or
move the centre downward while inventory is held.

## Why this was the final long-only form tested

- It satisfies the requirement to implement grid trading.
- It avoids a permanent, unlimited averaging-down structure.
- Wider spacing gives trades room beyond approximately 0.50% round-trip cost.
- Multiple small campaigns diversify opportunity and idiosyncratic risk.
- The implementation already includes settlement, fees, tax, gaps, legal
  ticks and corporate-action safety.

## Evidence

Trial 7 produced 36 independent episodes and 25 target sales, but lost
VND 3.047 million with a 0.347 profit factor. Risk and time exits lost
VND 4.666 million versus VND 1.536 million of target gains.

SSI was positive by VND 70,101 across four 2024 episodes, but became negative
under doubled costs. It is a case study and paper-trading candidate, not a
validated live strategy.

A broader SSI development-data sensitivity produced 14 independent episodes
under the loosest rule. Eleven were profitable, but aggregate P&L was
−VND 144,627 with a 0.83 profit factor. Increasing orders to 200 or 300 shares
scaled the losses rather than improving the edge. Retain 100 shares per level
for any operational demonstration.

A further multi-ticker implementation used dynamic SMA/ATR bounds, geometric
levels, a lower buffer, intended 100/200/300-share sizing, inventory skew and
deep-trend shutdown. It lost VND 6.247 million with a 0.022 profit factor.
This version is valuable as an engineering demonstration, but confirms that
distance-based size increases must never override a hard risk budget.

A paired single-reanchor experiment then tested 36 identical activations.
Six campaigns broke their lower bounds, but none produced the required
three-session stabilization before catastrophic shutdown. Consequently the
fixed and recovery variants were identical at −VND 1.434 million. Lowering
the centre automatically would require removing the downtrend protection.

## Final decision request

Approve:

1. rejection of the tested long-only single-stock grid family;
2. one frozen Trial 18 infrastructure/reproducibility rerun;
3. preservation of the old holdout;
4. acquisition of adjusted stock, index/sector and hedge-instrument data;
5. a separately preregistered stationarity-first hedged spread study.

Do not approve live or paper capital for the rejected long-only strategy.

## Canonical optimization result

Trial 11 formalized the assessed sequence with 2022–June 2024 in-sample
optimization, a locked July 2024–July 2025 internal validation and a final
July 2025–July 2026 OOS. None of 216 trend-conditioned grid configurations
produced positive aggregate in-sample P&L or profit factor above 1.10.
Accordingly, validation and final OOS correctly remained locked.

Trial 12 then kept the grid fixed and tested 24 causal ticker selectors. Each
two-month rotation used only completed prior grid campaigns, with shrinkage
and downside-risk adjustment. Eighteen configurations stayed in cash. The
other six all produced the same two VCB campaigns, losing VND 294,990 with a
0.00 profit factor, compared with −VND 256,518 for the all-universe control.
No selector passed in-sample, so validation and final OOS remained locked.
This result cannot be repaired by lowering the reporting threshold: the
executed sample was both insufficient and loss-making.

Trial 13 replaced sparse campaign history with 1,575 dense, point-in-time
deployment observations and predicted the exact after-cost grid return and
downside. All 54 model configurations ranked the top score quintile above the
bottom quintile, showing that the continuous features contained information.
Five configurations made a small nominal profit, but none reached PF 1.20,
none survived doubled costs, and none remained positive after removing its
best trade. The best made only VND 36,994 from nine campaigns concentrated in
one fold; all exited through trend shutdown rather than normal grid targets.
Validation and final OOS therefore remained locked.

Trial 14 directly predicted normal grid-target capture minus inventory loss.
Although all 48 configurations ranked target frequency directionally across
the full dense candidate pool, every selected strategy realized zero normal
grid targets. The best nominal case made VND 131,694 from four campaigns with
PF 1.585, but its median was negative, doubled-cost P&L was −VND 16,379 and
best-trade-removed P&L was −VND 164,013. Its gain came from non-grid trend
exits. This is not a profitable grid result, so validation and final OOS
remained locked.

Trial 15 then used the existing one-minute bid/ask archive with spread,
participation, queue, execution-cost and T+2 constraints. Its least-negative
configuration completed genuine grid cycles in 12 of 22 campaigns and had a
positive median, but lost VND 685,810 with PF 0.700. Target-cycle gains of
VND 1.645 million were outweighed by VND 2.335 million of forced/time losses;
doubled-cost P&L was −VND 1.198 million. None of 48 configurations was
positive, so validation and the July 2025–June 2026 minute holdout remained
locked.

An exploratory eight-ticker sensitivity then removed FPT and PNJ. The
least-negative result improved from −VND 685,810 to −VND 236,901, but PF
remained 0.700 and the sample fell to seven campaigns with four cycles.
Target gains of VND 699,890 remained below VND 936,791 of forced/time losses.
No configuration was profitable and validation remained locked.

Trial 17 replaced the arbitrary first-minute centre with a prior 20-session
median, required lower-grid activation, tested later-minute reclaim
confirmation, added a two-of-three severe-downtrend veto and capped a second
100-share level with a T+2-aware floor-stress budget. The least-negative
variant produced 48 campaigns and 24 target campaigns but lost
VND 1,479,791 with PF 0.492. The veto was useful—it reduced forced/time losses
by as much as 39.2%—but missed the preregistered 50% target, remained negative
under doubled costs and did not advance to validation.

Trial 18 replaced that lagging median with a 60-session beta-adjusted
residual-price equilibrium and required targets to preserve 0.50–1.00% profit
after normal fees and tax. The equilibrium produced 80 campaigns and a
strongly positive target-rate ranking spread, but all eight active folds and
all eight tickers lost money. The least-negative result was
−VND 4,254,549 with PF 0.300; target gains of VND 1.619 million were dominated
by VND 6.348 million of forced/time losses. Target widening did not address
the non-target-exit distribution, so validation remained locked.
