# TASKS

Status: TODO | DOING (owner) | REVIEW | DONE
Claim a task by setting DOING (name) in a tiny commit on `dev`, then branch from `dev`.
Each task stays inside its scope. Fill "Delivery notes" when done (max 3 lines).

---
## T0 Contracts and skeleton: DONE (both)
Scope: schemas/, repo layout, mock ERP seed, data/demo/
Done when: schemas validate, `npm run seed` creates the SQLite DB, 10 demo requests exist.
Delivery notes: schemas in schemas/, DB at data/erp.db, demo files in data/demo/.

## T1 Router agent: DOING (matteo)
Scope: agents/router/
Depends on: T0
Done when: classifies the 10 demo requests with category accuracy >= 9/10; output validates
against schemas/router.json.
Delivery notes:

## T2 Extractor agent: DOING (teammate)
Scope: agents/extractor/
Depends on: T0
Done when: order documents produce valid schemas/extractor.json; missing fields are listed
in `missing_fields`, never invented.
Delivery notes:

## T3 Mock ERP tools: TODO
Scope: tools/
Depends on: T0
Done when: the 5 tools in SPEC.md work against SQLite with unit tests.
Delivery notes:

## T4 Actor agent + business rules: TODO
Scope: agents/actor/
Depends on: T2, T3
Done when: a clean order creates an order; the three business rules in SPEC.md trigger
the right outcome.
Delivery notes:

## T5 Responder + escalation: TODO
Scope: agents/responder/, agents/escalation/
Depends on: T4
Done when: every outcome has a reply draft; escalations validate against
schemas/escalation.json and appear in the queue.
Delivery notes:

## T6 Orchestrator and trace log: TODO
Scope: orchestrator/
Depends on: T1, T2, T4
Done when: one command runs a request through all agents and writes trace events
(schemas/trace_event.json) to data/trace.jsonl.
Delivery notes:

## T7 Web UI (inbox, live trace, escalation queue): TODO
Scope: web/
Depends on: T6 (can start with fake trace data)
Done when: demo path is visible end-to-end in the browser.
Delivery notes:

## T8 Demo prep: TODO
Scope: docs/, data/demo/
Depends on: T7
Done when: demo script written, backup screen recording saved, pitch slides (max 5).
Delivery notes: