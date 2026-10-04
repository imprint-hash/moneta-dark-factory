# Stage 3 requirement ledger

Source: pocketful/spec/stage-3.md. Stages 1-2 (ledgers stage-1.md, stage-2.md) continue to apply. Shipped stage-3 sample checks: test_a_payment_carries_an_instant, test_me_is_unchanged_without_as_of, test_as_of_in_the_future_is_the_current_balance, test_a_statement_closes_its_arithmetic, test_a_statement_walks_the_balance_forward, test_a_correction_changes_the_current_balance. Everything else is `[unchecked]`. Stage 3 has no screens.

## Timestamps
T1. "Every payment's `created_at` is an RFC 3339 instant with an offset ... Every endpoint returning a payment includes it. `GET /activity` retains its existing ordering by this field."
T2. "Seeded payments may supply `created_at`; omission uses reset time, before subsequent API-created payments." [unchecked]
T3. "A seeded `created_at` in the future gives `422 validation_failed` from `POST /_test/reset`, with no state change." [unchecked]
T4. "A fixture's `balance` remains the balance after all seeded payments. Loading those payments must not change that balance." [unchecked]

## GET /me as_of
M1. `as_of` optional RFC 3339 instant with offset; naive local time, bare date or empty value -> 422 `validation_failed`. [unchecked]
M2. Without temporal params, money fields unchanged and report current corrected values.
M3. With `as_of`, `balance` is balance after every payment of the caller with `created_at` at or before `as_of`, before every later one; payment at exactly `as_of` counts. [partly unchecked]
M4. `as_of` at/after latest payment -> current balance; before earliest payment -> opening balance (balance before anything moved). [unchecked for opening]
M5. Response carries `as_of` back exactly as given. [unchecked]

## GET /statement
ST1. `GET /statement?from&to&limit&offset`; `from`, `to` optional (from defaults to wallet opening, to to now); limit/offset as in /requests (422 on invalid); invalid instants 422. [unchecked]
ST2. Returns payments the caller sent or received in the half-open window `[from, to)`, oldest first, each with `payment`, `delta`, `balance_after`; plus `opening_balance`, `closing_balance`, `has_more`.
ST3. Order by `created_at` (effective_at once corrections) ascending, then payment id ascending. [unchecked for ties]
ST4. `opening_balance` is balance immediately before `from`; `closing_balance` balance immediately before `to`. [unchecked]
ST5. opening + all deltas in the full window = closing; sent payment negative delta, received positive.
ST6. Pagination never changes an entry's `balance_after` or the window's opening/closing; they describe the full window regardless of limit/offset. [unchecked]
ST7. Statement contains only payments the caller sent or received, even if others are public; feed visibility rules do not apply. [unchecked]

## Revisions and corrections
RV1. Every payment has a revision history; revision 1 has original amount, `effective_at = recorded_at = created_at`; seeded payment's supplied `created_at` is its original recorded/effective time. [unchecked]
RV2. "Opening balances equal seeded ending balances minus the net effect of original seeded payments. Corrections must not change those opening balances. New accounts open at zero." [unchecked]
RV3. `POST /payments/{payment_id}/corrections`: idempotency key required, only original sender; non-sender 403; unknown 404; no token 401. [unchecked]
RV4. Body fields all required: `expected_revision` positive int; `amount` integer 0..1e9 (0 reverses fully); `effective_at` RFC 3339 instant not later than now; `reason` string 1..200 chars. Invalid -> 422. [unchecked]
RV5. Correction changes neither parties nor visibility; appends immutable revision; 201 with `payment_id`, `revision`, `amount`, `effective_at`, server `recorded_at`, `reason`; recorded times for one payment strictly increase. [partly unchecked]
RV6. Stale expected revision -> 409 `stale_revision`; successful replay returns that original revision with 200 even after newer revisions; different body same key 409 `idempotency_key_reuse`. [unchecked]
RV7. Difference between previous and new amount moves between the same two wallets atomically: increase debits original sender, decrease debits original receiver. [partly unchecked]
RV8. Currently unaffordable debit -> 409 `insufficient_funds`; otherwise if any user's corrected balance is negative at any effective-time boundary -> 409 `historical_overdraft` (balances at a boundary include all movements at that instant). Either failure preserves balances, revisions, statements, idempotency state. [unchecked]
RV9. Sum of balances equals seeded total in every historical view. [unchecked]
RV10. Original payment and every original idempotent response unchanged; `GET /activity` shows the original payment; corrections are not new feed payments. [unchecked]
RV11. `GET /payments/{id}/revisions` -> `{"revisions":[...]}` in order incl. revision 1 (`reason: ""`); only the two parties (third party 404 even if public); no token 401. [unchecked]
RV12. `known_at` on `/me` and `/statement`: RFC 3339 with offset; per payment select latest revision recorded at or before `known_at` (none yet recorded -> contributes nothing); omission = everything known when the read begins; selected revisions applied by effective time; `as_of` inclusive; statement half-open; either may be in the future; invalid/empty -> 422; echo supplied `known_at` exactly. [unchecked]
RV13. Statement ordering by selected `effective_at` then payment id; entries keep `payment`, `delta`, `balance_after`, add selected `revision`, `effective_at`, `recorded_at`; `payment.amount` is the selected amount; zero-amount revisions still appear with zero delta; no correction counted alongside the revision it replaces; no corrections and no `known_at` -> previous behaviour. [unchecked]
RV14. A correction may move a payment into or out of a statement window. [unchecked]

## Snapshots
SN1. Every first `GET /statement` returns opaque `snapshot` token freezing selected revisions, window, balances, entries, default `to`. [unchecked]
SN2. `GET /statement?snapshot=<token>&limit&offset` pages that exact result even after payments/corrections; only limit/offset may accompany it, else 422 (`from`, `to`, `known_at`). [unchecked]
SN3. Unknown token, another user's token, token from before reset -> 404 `not_found`; tokens last until reset. [unchecked]
SN4. Paging changes neither balances nor entries; final partial page and offsets beyond the end report `has_more` correctly. Unrecognized query params ignored. [unchecked]
SN5. Snapshots unchanged during concurrent payments/corrections; concurrent corrections with the same expected revision cannot both succeed. [unchecked]

## Settlement and import history
SH1. Stage-1 settlements keep original receipts and privacy; each member's original revision uses its `committed_at` as effective_at and recorded_at. [unchecked]
SH2. Single-payment corrections of settlement members -> 422 `linked_payment_immutable`; correction of a capture -> 422 `linked_payment_immutable`. [unchecked]
SH3. Stage-3 service accepts exports from the same team's stage-1 or stage-2 service; the ledger imports and accounts for authorizations and captures. [unchecked]

## Historical holds
HH1. `GET /me?as_of=T&known_at=K`: all four money fields describe the same view; `balance = total`, `available = total - held`. [unchecked]
HH2. A hold starts at authorization creation; nonfinal capture reduces it at capture time; final capture, void or expiry release the remainder at that event's time; expiry takes effect at `expires_at`. Non-expiry events known at their server event time; once creation is known its expiry deadline is known. For queries beyond now an open hold expires at its deadline; without `as_of` use the instant the request began. [unchecked]
HH3. Authorizations expose `closed_at` (null while open; event time when closed). [unchecked]
HH4. Historical `total` follows effective/recorded-time rules; a correction is rejected with 409 `historical_overdraft` if it makes total or available negative at any past boundary under latest known revisions; current unaffordable debits take precedence as `insufficient_funds`. [unchecked]
HH5. Seeded open holds assumed created at reset unless `created_at` supplied; seeded closed holds need not reconstruct lifecycle. [unchecked]
HH6. `GET /statement` contains money movements only (authorization, release, expiry are not payments); captures appear exactly once with their links; old snapshots unchanged after any lifecycle action or correction. [unchecked]
