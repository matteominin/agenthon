# DECISIONS

One entry per decision, 2-3 lines. Newest at the bottom. Do not reverse without discussing.

## D1: Mock integrations only
ERP, inbox and calendar are local (SQLite + JSON). Real OAuth/integrations would cost hours
and add failure points to the demo.

## D2: Few agents, structured handoffs
Four roles (router, extractor, actor, responder). Agents exchange validated JSON only,
never free text, so each module can be built and tested independently.

## D3: Human-in-the-loop by default on uncertainty
Escalate when confidence < 0.75, data is missing, or a business rule fails.
An agent that knows when to stop is part of the pitch.

## D4: Trace log is a product feature
Every agent step is appended to data/trace.jsonl (schemas/trace_event.json).
The UI streams it. It is also our debugging tool.

## D5: Contracts change only by agreement
schemas/ is shared. A change needs a message to the teammate and a line here
with the date and reason.