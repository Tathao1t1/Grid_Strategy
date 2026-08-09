# Pre-registration: Trial 16 eight-ticker minute sensitivity

## Status and limitation

Trial 16 is an **exploratory post-result sensitivity**, requested after the
Trial 15 result was observed. It must not be presented as an independent
confirmation of profitability.

The only intended change is to remove FPT and PNJ from ticker selection:

```text
execution universe =
    HPG, MBB, MWG, SSI, TCB, VCB, VND, VPB
```

FPT and PNJ remain in the leave-one-out market-proxy feature calculation so
the previously defined features do not change. They cannot generate training
labels, deployment candidates, positions or control campaigns.

## Frozen components

All Trial 15 components remain unchanged:

- one-minute bid/ask execution;
- repeated frozen grid cell;
- 100-share lots;
- 5% minute-volume participation;
- 40-bps spread ceiling;
- queue coverage when available and the documented 2022 fallback;
- commissions, tax and adverse execution;
- T+2 share and cash settlement at 13:00;
- ten-session campaign horizon;
- continuous feature set;
- three ridge targets;
- 48-configuration search;
- sector, overlap, concurrency and cooldown rules;
- in-sample and validation gates.

## Timeline

- Feature/training history begins: 2022-01-04.
- In-sample deployment: `wf_01`–`wf_09`,
  2023-01-03–2024-06-28.
- Conditional internal validation: `wf_10`–`wf_15`,
  2024-07-01–2025-07-11.
- Locked minute final OOS: 2025-07-14–2026-06-30.

Validation is calculated only if an eight-ticker configuration passes every
unchanged Trial 15 in-sample gate. July 2026 remains excluded.

