# AGENTS.md

Project: [PROJECT NAME].
[IDEA DESCRIPTION]

Context: 12-hour hackathon, two developers working in parallel. Priority is a working demo.

## Read first
- `SPEC.md`: what we are building and priorities (P0 > P1 > P2).
- `TASKS.md`: task list, owners, status. Work only on the task I assign.
- `schemas/`: shared JSON contracts between agents. Source of truth for data shapes.
- `DECISIONS.md`: architecture decisions already made. Do not reverse them silently.
Read other files only when needed. Do not scan the whole repo.

## Workflow
1. Work only on the assigned task and only inside its scope (folders listed in TASKS.md).
2. Do not edit files outside the scope. If you must, stop and tell me why.
3. Do not change anything in `schemas/` without asking. They are contracts shared with my teammate.
4. When done: set the task status in TASKS.md and fill "Delivery notes" (max 3 lines:
   what was done, where, how to test it).
5. Non-obvious architecture decision: add one line to DECISIONS.md.

## Git
- Branch per task: `task/T<id>-<short-name>`. Never commit directly to `dev` or `main`.
- Commit small and often. Message format: `T<id>: short description`.
- Do NOT run `git push`, `git pull`, `git rebase`, `git merge`, `git reset --hard`,
  `git clean`, or switch/delete branches. I handle remote and integration myself.
- Do not rewrite history. Do not touch other people's branches.
- Never commit secrets, `.env`, API keys, or large generated files. Keep `.env.example` updated.

## Technical rules
- Data between agents is always JSON validated against a schema. No free-form text handoffs.
- Low confidence, missing data, or out-of-scope request: escalate to a human with a short
  summary and the reason. Never invent data.
- Every agent action is written to the trace log (agent, input, output, action, confidence).
  The UI shows this trace live.
- Keep the number of agents small (3-4). Prefer simple code over frameworks.
- Handle errors explicitly: timeouts, invalid model output (retry once, then escalate).

## Code rules
- Minimal changes. No refactors, renames, or reformatting that were not requested.
- Do not add dependencies without asking. Prefer the standard library and what is already installed.
- No dead code, no commented-out blocks, no TODOs left without a task id.
- Add or update tests for what you touch. Run only the tests for the code you changed.

## Environment
- You run inside a Docker container with full permissions. Stay inside `/home/dev/work`.
- Before destructive commands (`rm -rf`, bulk deletes, dropping databases), ask me.
- Do not install system packages unless I ask.
- Use `rg` and `fd` to search. Use quiet flags and `| tail -n 50` for long command output.

## Token economy
- Be concise. Do not repeat the diff or summarize what you changed unless I ask.
- Do not paste large files or long logs back to me.
- If the task is unclear, ask one short question instead of guessing and rewriting.

## Done means
- Works on the demo path with the test documents in `data/demo/`.
- Tests for the touched code pass.
- TASKS.md updated, delivery notes filled, work committed on the task branch.

## Commands
- install: `[fill in]`
- dev: `[fill in]`
- test: `[fill in]`
- lint: `[fill in]`