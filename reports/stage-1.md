# Stage 1 report

- Accepted revision: 65f67c1f9bf91688fa374f1b2a58e9767e2ef0f3 (stage-1/), accepted by @examiner. Stage 1 has no screens, so @guest was not involved.
- Ledger coverage: 75 requirements (R1-R75). Builder checked all against code and the shipped harness (147/147, default and `--mode isolated`). Examiner's independent black-box exam (46 test groups) covered R1-R75 including every `[unchecked]` line; examiner also ran the harness in both modes, with the image on a no-outbound network.
- Rejections: none against the product. Examiner's first exam run had 2 failures, both bugs in the exam, fixed before acceptance.
- Work items: item 1 cc5d3cb (skeleton, auth, payments, idempotency, export/import), item 2 af93564 (requests, splits), item 3 65f67c1 (settlements).
- Open risks: scrypt n=4096 chosen for fast resets (weaker than defaults); state is in-memory only (permitted); an empty POST body is 400 and an integral float matches the int in replay comparison (both spec-ambiguous choices).
- Wall-clock: about 19 minutes from dispatch to acceptance (1117 s at the last measure before acceptance).
- `band usage daily` at start: total 4 input / 393 output, est. $0.10. At end: `band usage` reported no change in the totals (the archive appears to lag live seat usage), so per-stage cost cannot be given more precisely than "not yet reflected in band usage".
