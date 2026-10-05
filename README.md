# Moneta

**A four-seat dark factory in Band Desktop, and the payments app it built.**

WeAreDevelopers x BAND "Dark Factory" hackathon · **Track: pocketful** · **Stages: 1 and 2**

One human message started the run. Four AI seats then planned, built, examined and used
the product on their own, and every stage was accepted only when two independent reviewers
passed the same commit.

## How to read this repository

| Path | What it is |
|---|---|
| [`FACTORY.md`](FACTORY.md) | The factory: seats, design choices, what it caught, cost and time, what stopped it, how to stand it up |
| [`mandates/`](mandates/) | One generic mandate per seat (`lead`, `builder`, `examiner`, `guest`), each naming its harness and model |
| `room.json` | The full Band room the factory worked in, downloaded unchanged |
| [`stage-1/`](stage-1/) | The JSON API: payments, requests, splits, settlements, idempotent writes, export/import |
| [`stage-2/`](stage-2/) | Stage 1 carried forward plus the browser product: balance and pay, activity, requests, splits, holds and captures, recovery from lost and stale responses |
| [`ledger/`](ledger/) | The lead's numbered requirement ledger per stage, written before any code |
| [`exam/`](exam/) | The examiner's black-box exams, committed after each stage was accepted |
| [`reports/`](reports/) | The lead's report for each accepted stage |

## Run a stage

Each stage folder is a complete service. From inside it:

```sh
docker build -t moneta-stage2 . && docker run --rm -p 8080:8080 -e PORT=8080 moneta-stage2
```

Then open http://localhost:8080 (stage 2) or `curl localhost:8080/health`.

## Result

| Stage | Accepted revision | Ledger | Reviews |
|---|---|---|---|
| 1 | `65f67c1` | 75 requirements | examiner: exam + shipped checks, default and isolated |
| 2 | `f87c6d5` | 60 requirements + stage-1 regression | examiner (API and browser) and guest (real Chrome, 375 px and 1280 px) |

On a fresh clone, BAND's harness in isolated mode reports `stage-1/` claiming stage 1 and
`stage-2/` claiming stage 2. The run stopped at the start of stage 3 when the Claude Pro
session limit was reached; [`FACTORY.md`](FACTORY.md) explains what happened and what we
would change.

## Team

IMPRINT (solo), [@imprint-hash](https://github.com/imprint-hash)
