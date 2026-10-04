# Stage 1 requirement ledger

Source: pocketful/spec/stage-1.md. `[unchecked]` = not exercised by the shipped sample checks.

R1. "The sum of wallet balances always equals the total seeded by the last `POST /_test/reset`." (also under splits/retries)
R2. "No wallet balance may be negative, including transiently." [unchecked]
R3. "A payment request may move money at most once." (concurrent pay of one request) [unchecked]
R4. "All amounts are exact integer counts of minor units." Money moves only between existing wallets.
R5. §2 Dockerfile + RUN.md build and start with no manual setup; no outbound network at run time; works with `-e PORT`; 50 concurrent requests, 2 vCPU/2 GiB.
R6. §3.1 "Listen on `0.0.0.0` using the `PORT` environment variable, default `8080`." [unchecked]
R7. §3.2 `GET /health -> 200 {"status":"ok"}` within 60 s.
R8. §3.3 `POST /_test/reset` -> 204, replaces all state; repeated resets work; no auth.
R9. §3.4 JSON responses `application/json; charset=utf-8`. [unchecked]
R10. §3.4 Timestamps RFC 3339 with explicit offset. [unchecked]
R11. §3.4 "Unknown fields in a request body are ignored" and unknown query parameters are ignored (query part [unchecked]).
R12. §3.4 IDs opaque strings of at most 64 characters. [unchecked]
R13. §4 Amounts must be integral numeric: `1000`, `1000.0`, `1e3` valid; booleans and strings are not (422). [unchecked for 1000.0/1e3]
R14. §4 Handle unique, `^[a-z0-9_]{1,20}$`, immutable; seeded from fixture.
R15. §4 Signup handle derived: local part lowercased, chars outside `[a-z0-9_]` -> `_`, truncated to 20.
R16. §4 Derived handle already taken -> 409 `handle_taken`, no account created.
R17. §4 New users start at balance 0 and can receive and be requested immediately.
R18. §4 Request may exceed payer's balance; stays pending; pay while short is 409 `insufficient_funds` and changes nothing; becomes payable once funded.
R19. §4 Visibility belongs to the payment, chosen by the payer when paying; requests carry no visibility and never appear in others' feeds.
R20. §4 `GET /activity` shows payments only; a payment appears iff public, or caller is sender or receiver. Private hidden from third parties, not from receiver.
R21. §4 `GET /requests` only where caller is requester or payer; splits are not feed items.
R22. §4 Amount max 1000000000; balances within ±2^53, exact arithmetic. [unchecked for large totals]
R23. §4 Fixture: seeded users log in with the given password immediately; `balance` is post-payments, not replayed; seeded payments/requests loaded.
R24. §4 Negative fixture balance -> 422 `validation_failed` from reset and nothing changes. [unchecked]
R25. §4 `minor_units` 0, 2, 3 (JPY, EUR, BHD) work.
R26. §5 Error body `{"error":{"code","message"}}` on every 4xx/5xx with specified status and code.
R27. §5 400 `malformed_request` for unparseable body or wrong JSON type field.
R28. §5 400 `missing_idempotency_key` when header absent or empty.
R29. §5 401 `unauthenticated` missing/malformed/unknown bearer token. [unchecked for malformed token]
R30. §5 403 `forbidden`; 404 `not_found` (no such resource or not visible).
R31. §5 422 `validation_failed`: invalid amount (strings, booleans), non-string note including null, bad visibility; omission selects defaults.
R32. §5 Integer query params plain decimal digits: `1e9`, `4.0`, `+4` -> 422. [unchecked]
R33. §5 `Idempotency-Key` 1..255 chars else 422; `limit` 1..200; `offset` >= 0, else 422.
R34. §5 No 5xx responses, including under concurrent load.
R35. §6 `POST /auth/signup` -> 201 `{user_id, display_name, token}`; `POST /auth/login` -> 200 same shape.
R36. §6 Email taken -> 409 `email_taken`; password < 8 chars -> 422; email not `local@domain` -> 422; wrong password/unknown email -> 401. [partly unchecked]
R37. §6 Every other endpoint requires bearer token except /health, /_test/*, signup, login.
R38. §6 Tokens never expire; multiple concurrent valid tokens per account. [unchecked]
R39. §6 Passwords stored with bcrypt/scrypt/argon2 or equivalent; never plaintext. [unchecked]
R40. §7 Five idempotent write paths: payments, requests, requests/{id}/pay, splits, settlements.
R41. §7 Key scoped per authenticated user; same key by two users does not interact.
R42. §7 Replay = same method, path and body; same key + body on different path is a fresh request.
R43. §7 First use 201; replay 200 with body identical as JSON value; different body -> 409 `idempotency_key_reuse`; key reused after a 4xx failure is a first use.
R44. §7 Body equality is parsed JSON value (key order, whitespace irrelevant). [unchecked]
R45. §7 Concurrent identical requests with unused key: exactly one 201, others 200 same body, effect once. [unchecked]
R46. §7 Successful replay returns the original response even after the resource changed/cancelled; no further state change. [unchecked for cancel case]
R47. §7 Already-claimed key resolved (409 reuse) before field validation or resource checks, once body is a JSON object and caller authenticated.
R48. §8 `GET /me` shape `{user_id, display_name, handle, balance, currency, minor_units}`.
R49. §8 `POST /payments` 201 shape (payment_id, from/to ids & handles, amount, currency, note, visibility, request_id null, created_at); note default "", visibility default public.
R50. §8 payments: balance below amount -> 409 `insufficient_funds`; amount <1/>1e9/non-integer -> 422; own handle -> 422 `self_payment`; note >200 chars -> 422; bad visibility -> 422; unknown handle -> 404.
R51. §8 Debit and credit atomic; failed payment leaves no trace.
R52. §8 Note stored verbatim (no trim/escape/normalise); unicode/emoji round-trip; 200 chars (counted as characters, emoji included) ok, 201 rejected.
R53. §8 `POST /requests` 201 shape (request_id, requester/payer ids and handles, amount, currency, note, status pending, payment_id null, created_at); payer balance not checked.
R54. §8 requests errors: amount range 422; own handle -> 422 `self_request`; note >200 -> 422; unknown handle -> 404.
R55. §8 `POST /requests/{id}/pay`: only payer; body `visibility` only, default public; 201 payment with `request_id` set; request becomes paid with `payment_id`.
R56. §8 pay errors: not pending -> 409 `request_not_pending`; short -> 409 `insufficient_funds`; non-payer -> 403; unknown -> 404.
R57. §8 Replay of successful pay returns 200 original payment even though request now paid; moves no money; `{}` vs `{"visibility":"public"}` is reuse.
R58. §8 decline: payer only, no key, 200 declined; twice -> 200; paid/cancelled -> 409 `request_not_pending`; non-payer 403.
R59. §8 cancel: requester only, no key, 200 cancelled; twice -> 200; paid/declined -> 409; non-requester 403.
R60. §8 `GET /requests` filters `direction` (incoming/outgoing/both), `status`; newest first; limit default 50, 1..200; offset; `has_more`; unknown direction/status -> 422.
R61. §8 `POST /splits` response shape (split_id, amount, currency, note, shares, requests, created_at); one pending request per participant except caller, in order, caller as requester.
R62. §8 splits: caller may be included or omitted; amount range 422; empty or duplicate handles -> 422; note >200 -> 422; unknown handle -> 404; solo-caller split valid with `requests: []`; no balance checks.
R63. §8 `GET /activity` `{payments, has_more}` newest first, limit/offset as requests; same-second order unspecified.
R64. §9 Equal split: whole units, sum exactly amount, differ by <=1, extras to first participants in given order (1000/3 -> 334,333,333; 1/3 -> 1,0,0; 10/3; 999/3; 5/5). Zero share still produces a request.
R65. §9 Conservation after any number of paid splits. 
R66. §10 `GET /_test/export` -> 200 `{track:"pocketful", format_version:1, state}`; `POST /_test/import` replaces state atomically -> 204; unchanged export accepted.
R67. §10 Import: missing fields / wrong track / wrong version / invalid state -> 422 and no change; invalid JSON per §5 (400). [unchecked]
R68. §10 Import is replacement not merge; idempotent when repeated; export is atomic read-only snapshot unaffected by later writes. [unchecked]
R69. §10 Preserved across import: accounts + hashed login, bearer tokens, currency, balances, payments, requests, permissions, idempotency records and original responses; ids/timestamps unchanged; failed keys remain reusable; receipts and retries still valid. [partly unchecked]
R70. §10 Import removes all previous destination data and credentials; reset clears imported state. [unchecked]
R71. §11 Fixture `settlement_operator_ids` (default []); operators may settle across any wallets but gain no access to others' requests/private activity. [unchecked]
R72. §11 `POST /settlements`: needs key; no token 401; non-operator 403; 1..32 transfers each with ordinary payment rules (note, visibility defaults); unknown handle 404; self-transfer 422 `self_payment`; bad shape 422; entry errors in input order before insufficient funds; unknown fields ignored. [mostly unchecked]
R73. §11 Affordable when every wallet's final net balance >= 0 (so chained transfers net); else 409 `insufficient_funds`; all-or-nothing; failed validation claims no key and creates no payment. [unchecked]
R74. §11 201 `{settlement_id, committed_at, payments}` in input order; each member an ordinary payment with `settlement_id`, null `request_id`, `created_at == committed_at`; non-members expose `settlement_id: null`; members follow normal feed visibility. [unchecked]
R75. §11 Settlement replay 200 with original complete response; operator permissions, membership and retry responses survive reset/import as specified. [unchecked]
