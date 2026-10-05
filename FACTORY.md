# Moneta: the factory

Moneta is a four-seat software factory that runs in one Band Desktop room. A human sends
one task per stage; the seats plan, build, examine and use the product until two
independent reviewers accept the same committed revision. Nothing in the seats' mandates
names a product, an endpoint, a field or an error code, so the same four mandates can be
pointed at any specification.

This repository is the run that built the `pocketful` track, stages 1 and 2.

## The seats

| Seat | Harness | Model | Owns | May never |
|---|---|---|---|---|
| `lead` | Claude Code | claude-sonnet-5-5 | the requirement ledger, work items, handoffs, stage reports | write product code |
| `builder` | Claude Code | claude-sonnet-5-5 | all product code, `Dockerfile`, `RUN.md` | read the examiner's exam, accept its own work |
| `examiner` | Claude Code | claude-sonnet-5-5 | a black-box exam written from the specification alone | edit product code |
| `guest` | Claude Code | claude-sonnet-5-5 | the first-time user's view of every screen, at 375 px and 1280 px | edit product code, read source to excuse a screen |

The full mandates are in [`mandates/`](mandates/).

## How a stage runs

1. **Ledger first.** `lead` reads the whole specification and commits `ledger/stage-N.md`:
   one numbered line per testable sentence, quoted, with every line the shipped sample
   checks do not exercise marked `[unchecked]`. Those lines are where hidden tests live,
   so they get named before any code exists.
2. **Exam before code.** `examiner` receives the specification and the ledger at the same
   moment `builder` receives its first work item, and writes its exam before seeing any
   code. The exam talks to the running container only through HTTP and a browser.
3. **Small work items.** `lead` divides the stage into items that fit in one turn and sends
   `builder` one at a time, each with the full specification pasted in, the ledger ids it
   covers, the absolute repository path and the checks to run.
4. **Two independent reviews of one revision.** When `builder` reports a commit, `examiner`
   builds the image itself (also with no outbound network), runs the shipped checks for
   every stage so far plus its exam, and reports each failure as a ledger id, the quoted
   requirement and the observed behaviour, never as test code. For stages with screens,
   `guest` builds the same revision and walks every task in real Chrome at phone and
   desktop widths, forcing slow, lost, refused and stale-data moments.
5. **Rejections go back unchanged.** `lead` forwards every rejection to `builder` as written.
   A stage is accepted only when both reviewers accept the same commit and the folder
   builds and starts from its own `Dockerfile` by following its `RUN.md`.
6. **Report.** `lead` commits `reports/stage-N.md`: accepted revision, ledger coverage,
   every rejection and what it changed, open risks and wall-clock time.

Each seat commits under its own name, so `git log` shows who did what.

## How the factory caught bad work

- **Stage 2, a real money bug.** After a refused capture of a hold, a delayed list refresh
  reset the amount the user had typed, so the next capture could move the wrong amount
  (2 of 6 runs). `examiner` rejected revision `539880c` against ledger lines V5/C4.
  `builder` fixed it in `f87c6d5` with keyed row reconciliation that keeps edited inputs;
  `examiner` re-ran it 15 times, all clean.
- **Stage 2, a race the builder found.** The Refresh button disabled itself during a
  refresh, which broke "latest response wins". `builder` found and fixed it before review.
- **Stage 2, usability.** `guest` sent back header truncation at 375 px and an expiry
  shown only as raw RFC 3339 text; both were fixed before acceptance.
- **Stage 1.** No product rejections. The examiner's first run had two failures, both bugs
  in the exam itself, fixed before acceptance: the exam is checked too.

## Results

| Stage | Ledger lines | Exam | Wall-clock, dispatch to acceptance | Shipped checks |
|---|---|---|---|---|
| 1 | 75 (28 `[unchecked]`) | 46 test groups | about 19 minutes | pass, default and isolated |
| 2 | 60 (33 `[unchecked]`) + stage-1 regression | 61 API + 13 browser checks | about 59 minutes | pass, default and isolated |

A fresh clone of this repository, run with
`python -m harness run --track pocketful --repo <clone> --all --mode isolated`, reports
`stage-1/: claims stage 1` and `stage-2/: claims stage 2`.

## Cost and time

- **Model spend:** the whole run (all four seats, stages 1 and 2 and the stage-3 ledger)
  used 267k output tokens, 559k cache-write and 21.2M cache-read tokens of Claude Sonnet.
  At list prices that is about **$12.45**, measured from the seats' session records.
  `band usage` did not reflect live seat usage during the run, so the seats could not
  report per-stage cost themselves.
- **Plan:** the seats ran on a Claude Pro subscription, not an API key.
- **Time:** about 78 minutes of factory time for stages 1 and 2, with one human message.
- **Machine:** one cloud VM, 2 vCPU and 7.6 GB RAM plus 4 GB swap; four seats, Docker
  builds and headless Chrome fit comfortably because seats are idle until mentioned.

## What stopped the run, and what we learned

The run stopped at the start of stage 3: `lead` had committed the stage-3 ledger (44
lines, 41 of them unchecked by the samples) when the Claude Pro **session limit** was
reached ("You've hit your session limit"). The limit resets after a few hours, but a seat
whose turn failed is not woken again until someone messages the room, and any human
message mid-run would be steering. We left the run as it was rather than nudge it.

What we would change:

- **Budget for the plan's window.** A toy run of the same factory (four stages) cost about
  $2.91; this specification cost about $6 per stage. A subscription window of a few hours
  covers about two stages of a specification this size. Use an API key, or dispatch one
  stage per fresh limit window.
- **Make the lead resilient to a failed turn.** A seat-level retry after a provider limit
  would let the run continue without a human message.

Things we tried while building the factory that failed:

- **Strict MCP isolation** (`--claude-strict-mcp-config`) also hid Band's own relay at
  runtime, so the first seat stopped when it needed a permission prompt.
- **Running Band's daemon as a login service** started an older daemon copy whose relay
  failed to load in every seat. Starting the daemon from Band Desktop fixed it.

## Stand it up yourself

1. Install Band Desktop (0.4.10 or newer), Claude Code, Docker and Python 3.12, and sign in
   to Band and to Claude Code.
2. Keep the coding agents away from personal connectors: set
   `"env": {"ENABLE_CLAUDEAI_MCP_SERVERS": "false"}` in `~/.claude/settings.json`. Do not use
   strict MCP mode; it hides Band's relay.
3. Create the four seats, each pointed at your result repository:

   ```sh
   band agent create --session factory-lead --name lead \
     --description "Plans each stage, keeps the requirement ledger, hands out work and writes the stage report. Never writes product code." \
     --cwd /abs/path/to/result --transport claude-code-cli --runtime-auth subscription \
     --runtime-model claude-sonnet-5-5 --claude-context-mode local_config \
     --instructions-file /abs/path/to/mandates/lead.md
   ```

   Repeat for `builder`, `examiner` and `guest` with their own description and mandate.
4. In Band Desktop, Home, Assign work: choose `lead`, and send one task that names the
   track, the specification paths, the absolute result repository path and the check
   command. Mention `@builder @examiner @guest`. Then send nothing else until the final
   report.
5. Download the room from the Band console (Download, full session) as `room.json`.
