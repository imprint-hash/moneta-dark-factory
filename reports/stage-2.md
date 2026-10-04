# Stage 2 report

- Accepted revision: f87c6d572a4f9a6a00b4d29982cb4d831ebfba8a (stage-2/), accepted by @examiner and @guest at that same revision.
- Ledger coverage: stage-2 ledger has 69 lines (S1-S8, A1-A4, P1-P6, F1-F3, Q1-Q3, L1-L2, C1-C6, U1-U4, H1-H18, V1-V6) plus the 75 stage-1 lines as regression. Examiner: API exam 61/61 (stage-1 regression included), browser exam 13/13 (375px and desktop, upgrade from a real stage-1 build, lost response, refresh race), harness default and isolated. Guest: real-Chrome walk of every screen at 375px and 1280px, including slow, lost, refused and stale-data states. Builder: harness both modes plus own Playwright checks for C3-C6 and U2-U4.
- Rejections and what they changed:
  1. @examiner rejected 539880c (V5/C4): after a refused capture a delayed list refresh reset the typed capture amount (2 of 6 runs; capture then moved the wrong money). Fixed in f87c6d5 by keyed row reconciliation that keeps edited inputs; 15/15 repeat runs clean.
  2. Not rejections but guest polish applied before final: header truncation at 375px, friendlier expiry line beside the exact RFC 3339 text.
  3. Builder found and fixed on its own: Refresh button disabled itself during a refresh (broke latest-wins, C3).
- Open risks: guest minor notes left as is (blank gap beside avatar in desktop sidebar chip on /requests; friendly expiry line has no year/timezone; long state messages on phone). Upgrade tested with a real stage-1 export by examiner, and by builder with a reshaped export. State remains in memory only.
- Wall-clock: about 59 minutes from stage-2 dispatch to acceptance (3550 s at the last measure before acceptance).
- band usage: start of stage and end of stage both read total 4 input / 393 output, est. $0.10 (the usage archive did not reflect live seat usage), so no per-stage cost is available.
