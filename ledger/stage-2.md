# Stage 2 requirement ledger

Source: pocketful/spec/stage-2.md. Stage-1 ledger (R1-R75) continues to apply. `[unchecked]` = not exercised by the shipped sample checks (test_sample.py, test_ui.py).

## Screens and shared routes
S1. "The following screens must be reachable by URL": `/`, `/requests`, `/split`, `/signup`, `/login`; other screens reachable through the UI.
S2. "Return the UI for `Accept: text/html`; API requests without that header receive JSON." (/requests, and /authorizations)
S3. Product direction: calm coherent consumer finance look; one visual system (type, spacing, colour, controls, feedback); primary actions identifiable. (guest-reviewed) [unchecked]
S4. "Available funds must be the clearest monetary value once holds exist, with total and held funds visibly secondary." [unchecked]
S5. Available, held, pending, loading, successful, refused and uncertain states visually distinct. [unchecked]
S6. People/amounts/timestamps formatted for people; technical ids only where they help. [unchecked]
S7. Usable at 375 px and desktop without horizontal page scrolling; labelled inputs; visible keyboard focus; sufficient contrast; empty/loading/error states; consistent navigation. [unchecked]
S8. Product direction (task file): dark navy-to-black bg with soft blue glow, white sans type, rounded cards; periwinkle #6E8CF0 for money in/primary actions, coral #E06A7A for money out; home has large balance card with available biggest, contact avatar row with initials+handles and Add button, feed rows with round coloured icon/who/when/amount/public-private tag; split as highlight with live per-participant shares with initials; every state its own colour and plain words; bottom nav on phones, side menu on desktop. [unchecked]

## Signup/login
A1. Testids `signup-email`, `signup-password`, `signup-display-name`, `signup-submit`, `login-email`, `login-password`, `login-submit`.
A2. `auth-error` present only when there is an error (bad login shows it).
A3. `current-user` visible on every screen when signed in, text contains display name; `current-handle` text exactly the handle (no @). 
A4. `logout-button` logs out.

## Balance and pay `/`
P1. `wallet-balance` text exactly formatted amount (`100.00 EUR`; `1200 JPY` for 0 minor units, no sign), `data-amount` = minor units.
P2. `pay-handle`, `pay-amount` (decimal string), `pay-note`, `pay-visibility` (select, values `public`/`private`), `pay-submit`.
P3. Decimal input: `15.00` and `15` submit 1500; `15.5` -> 1550; nonnumeric or more than minor_units decimals shows form error element without sending a request (`15.005` rejected, not rounded). Applies to pay, authorize, split amounts. [partly unchecked]
P4. `pay-error` when payment refused incl. insufficient funds.
P5. Pay form keeps values after success; resubmitting unchanged sends no new payment (balance falls once, one feed item, `pay-error` absent); changing a field makes the next submission a new payment (new key); retries follow §7.
P6. `request-handle`, `request-amount`, `request-note`, `request-submit`, `request-error` form works. [unchecked]

## Feed `/`
F1. `activity-list` container, children newest first in DOM.
F2. `activity-item-{payment_id}` with `data-visibility`; `activity-parties-{id}` contains both handles; `activity-amount-{id}` exact formatted amount; `activity-note-{id}` exact note, present even when empty.
F3. `empty-activity` shown instead of list when nothing visible. Third-party doesn't see private payments.

## Requests `/requests`
Q1. `incoming-list`, `outgoing-list`, `request-item-{id}` with `data-status`, `request-amount-{id}` exact formatted.
Q2. `request-pay-{id}` and `request-decline-{id}` only on pending incoming; `request-cancel-{id}` only on pending outgoing; they work.
Q3. `request-error` when pay/decline/cancel refused; `empty-requests` when both lists empty.

## Split `/split`
L1. `split-amount`, `split-handles` (comma separated, ordered), `split-note`, `split-submit`, `split-error`.
L2. `split-preview` with one `split-share-{handle}` per participant, exact formatted share, computed before posting by stage-1 §9 rule; preview equals submitted shares; handle order respected.

## Refresh and competing clients
C1. "After any successful action, the balance, the feed and the request lists on the same page must show the new state without a manual reload. Navigation must wait for the write to succeed before it refreshes the data."
C2. `wallet-refresh` button on `/` refreshes balance and feed without clearing the pay form. [partly unchecked]
C3. "Latest refresh wins": a delayed earlier read must not overwrite a later refresh, even if responses arrive out of order (also for available/held). [unchecked]
C4. Payment refused because another client spent the balance: show `pay-error`, refresh balance/feed, preserve all pay inputs. [unchecked]
C5. Request cancelled elsewhere while pay button visible: refused pay shows `request-error` and refreshes list so the stale pay button disappears. [unchecked]
C6. Lost response to POST /payments (even after commit): show `pay-uncertain` (nonempty), not `pay-error`; unchanged form retryable with same key and body; successful retry clears error/uncertain elements, refreshes balance/feed, money moves exactly once. [unchecked]

## Upgrade
U1. Stage-2 service accepts an export from the team's stage-1 service. [checked by sample]
U2. A browser signed in before export/import stays signed in. [unchecked]
U3. Existing pending requests remain payable through the request screen after import. [unchecked]
U4. A payment whose response was lost before export remains retryable after import with same body and key; UI recovers original payment and refreshes imported balance; form and pending retry identity survive upgrade (no reload). [unchecked]

## Authorizations and captures (API)
H1. Fixture: `authorization_ttl_seconds` (default 600; if supplied must be positive integer, else 422 [unchecked]); `authorizations` array (omission = empty); seeded fields id, from_user_id, to_user_id, amount, note, visibility, status (open/captured/voided/expired), expires_at.
H2. Seeded `balance` is total; available derived = total - seeded unexpired open holds; sum of seeded unexpired open holds > balance -> 422 `validation_failed` from reset, no change. [unchecked]
H3. `GET /me`: `balance == total`, adds `total`, `available`, `held`; no open holds: all agree, held 0, earlier behaviour unchanged.
H4. Sum of all wallet totals always equals seeded total; hold moves no money. `available` never negative; held funds cannot fund payments, authorizations or settlement net debits; captures may spend their own reserved money. [unchecked for settlements]
H5. Every 409 `insufficient_funds` (payments, request pay, settlements) evaluated against `available`. [unchecked]
H6. `POST /payments` stays immediate with no hold; paying a request immediate; POST /splits unchanged.
H7. Seven idempotent write paths (stage 1's five + authorizations + captures), same replay rules independently.
H8. `POST /authorizations`: key required; 201 body with authorization_id, from/to ids+handles, amount, captured_amount 0, currency, note, visibility, status open, expires_at = created_at + ttl, payment_id null, created_at (+ `remaining_amount`, `payment_ids`).
H9. authorize errors: available < amount 409 `insufficient_funds`; amount range/integer 422; own handle 422 `self_payment`; note/visibility 422; unknown handle 404. Open authorization never in `GET /activity`.
H10. `POST /authorizations/{id}/capture`: key required; only receiver (403 otherwise, including non-parties); body `amount` optional (default remaining), 201 payment in POST /payments shape with `authorization_id` set, `request_id` null, note/visibility copied from auth; payments not from authorizations carry `authorization_id: null`. Replay must send identical body (`{}` vs `{"amount":2000}` = reuse).
H11. Default capture is final: status `captured`, `captured_amount`, `payment_id`, releases uncaptured remainder immediately (capture 1500 of 2000 returns 500 to available at once); second capture after final -> 409 `authorization_not_open`. [partly unchecked]
H12. Extended mode `{"amount":700,"final":false}`: `final` boolean default true; remainder stays held and status stays `open`; capturing entire remainder closes it; final capture closes and releases remainder; `captured_amount` cumulative, `payment_id` latest, `payment_ids` all in order; every authorization response has `remaining_amount` (0 when closed). [unchecked]
H13. Capture errors: not open 409 `authorization_not_open`; `expires_at` <= now 409 `authorization_expired`; amount > remaining 422 `capture_exceeds_authorization`; amount <1 or non-integer 422 `validation_failed`; unknown 404. [unchecked]
H14. Cumulative captures never exceed authorized amount; each idempotent capture moves money once; closed hold cannot be captured again; concurrent captures safe. [unchecked]
H15. `POST /authorizations/{id}/void`: only payer (403 otherwise), no key, 200 `voided`, hold released; twice -> 200; captured/expired -> 409 `authorization_not_open`; void/expiry on a partially captured one releases only the remainder and keeps capture records. [partly unchecked]
H16. Expiry: `expires_at` at or before now = `expired`, holds nothing; reads and writes reflect expiry with no request at the deadline; `GET /authorizations` shows `expired`, `GET /me` available includes the released remainder. [unchecked]
H17. `GET /authorizations`: only caller's (payer or receiver); `direction` outgoing/incoming/both, `status` filter (clock-expired matches `expired` not `open`), newest first, limit/offset/has_more as /requests, invalid -> 422. [unchecked]
H18. Concurrent operations equivalent to some serial order; invariants hold at every read. [unchecked]

## Authorizations UI
V1. `/authorizations` route serves HTML for text/html else JSON.
V2. `wallet-available` formatted `available` with data-amount, presented as the headline number; `wallet-balance` = formatted total; `wallet-held` formatted held with data-amount, absent when held is zero.
V3. Authorise form `authorize-handle`, `authorize-amount`, `authorize-note`, `authorize-visibility`, `authorize-submit`; `authorize-error` on refusal incl. insufficient available. [unchecked]
V4. `authorization-list` (newest first), `authorization-item-{id}` with `data-status`, `authorization-amount-{id}`, `authorization-captured-{id}` (only when captured), `authorization-expires-{id}` (RFC 3339 expires_at). [unchecked]
V5. `authorization-capture-amount-{id}` (decimal input prefilled with remaining) and `authorization-capture-{id}` only on incoming open; `authorization-void-{id}` only on outgoing open; `authorization-error` on refused capture/void; `empty-authorizations`. [unchecked]
V6. UI reflects seeded and newly created holds; available shown as spending balance right after reset with open holds. [unchecked]
