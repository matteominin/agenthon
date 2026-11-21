# SPEC: RequestDesk (example)

## Problem
A small B2B distributor receives 100+ emails a day (orders, quote requests, invoice questions,
complaints), often with PDF attachments. Two people read, retype data into the ERP and reply.
It is slow (~8 min per request), error-prone, and urgent requests get buried.

## Solution in one sentence
A team of agents reads each inbound request, extracts data from the attached document,
executes the safe actions in the ERP, drafts the reply, and hands anything uncertain to a human.

## Demo flow
1. A request arrives in the mock inbox (`data/demo/inbox/*.json` + attachment text/PDF).
2. Router: classify category and urgency.
3. Extractor: pull structured data from the document.
4. Actor: validate against the mock ERP (SQLite), run tools (create order, open ticket).
5. Responder: draft the reply to the customer.
6. If confidence < 0.75, data is missing, or a business rule fails: escalate to a human
   with summary + reason. The UI shows the live agent trace and the escalation queue.

## Agents and tools
| Agent     | Input                  | Output schema          |
|-----------|------------------------|------------------------|
| Router    | request                | schemas/router.json    |
| Extractor | request + document     | schemas/extractor.json |
| Actor     | extractor output       | schemas/action_result.json |
| Responder | action result          | plain reply draft (string), stored in action_result |
| (any)     | uncertainty            | schemas/escalation.json |

Tools (mock): `lookup_customer(vat_id)`, `check_stock(sku)`, `create_order(customer_id, lines)`,
`open_ticket(customer_id, summary, priority)`, `save_draft(request_id, text)`.

## Priorities
- P0: one order request goes end-to-end (router -> extractor -> actor -> reply).
- P1: escalation to human, live trace UI, quote requests and invoice questions.
- P2: complaints, extra edge cases, metrics panel (time saved, % handled autonomously).

## Business rules (examples)
- Order total > 5,000 EUR: always escalate (needs approval).
- Unknown customer VAT id: escalate, never create a customer automatically.
- SKU not in catalog or out of stock: do not create the order; explain in the reply draft.

## Out of scope
Real email/ERP integration, authentication, multi-language support, cloud deployment.

## Demo data
`data/demo/`: 10 requests: 4 clean orders, 2 quote requests, 1 invoice question,
1 complaint, 1 order with missing quantity, 1 out-of-scope request.

## Success metric (for the pitch)
Average handling time per request and % resolved without a human.