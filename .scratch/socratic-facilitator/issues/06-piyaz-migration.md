# 06 — Migrate factory to Piyaz

Type: task
Status: open
Blocked by: none

## Question

Human-gated manual work unblocking `to-spec → to-tickets` in Piyaz: (1) human re-auths Piyaz in own session (`/mcp add` — OAuth refresh 500 on 2026-09-11, never invent login flow), (2) create Piyaz project for socratic-dialogue-facilitator (record KEY), (3) re-run `python3 ../omp-modes/projectify.py --tracker piyaz --project <KEY>` (preserves factory.json), (4) confirm `factory.py --once --dry-run` passes. Resolved when implementation tickets can publish to Piyaz. HITL because step 1–2 need the human.
