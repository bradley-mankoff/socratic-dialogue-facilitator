# 03 — Facilitator manners (auto vs on-demand)

Type: grilling
Status: resolved
Blocked by: 02

## Question

Lock facilitator behavior against the board model from 02: auto-populate canonical definitions of X on board creation; mark active definition automatically; counterexamples and deep search strictly on demand ("search", "counterexample", "put on board", "summarize"); never speak verbally in live mode. Define the live interruption budget (what it may write unprompted, when it must stay silent), and the async equivalents (digests, nudges). Blocked by 02 because manners hang on board semantics.

## Answer

Manners locked over live grilling 2026-09-13, building on 02 (as amended to two modes):
- Two modes: LLM Participates / LLM Facilitates. Mode chosen per board at creation, changeable by room agreement.
- LLM Participates: full participant like a human except the Socrates seat — offers counterexamples, defends claims, votes with transparent posted reasons, equal weight. When it holds the Socrates role it questions freely; teaching callouts labeled META (vs ELENCHUS challenges), capped so lessons don't drown the fight.
- LLM Facilitates: board-keeping + vote-tally + on-demand search/summarize only. No vote, no suggestions, no callouts, never Socrates.
- Staleness: every LLM contribution labeled with its type AND what it is responding to (the comment current when it started composing; may lag ~1 min). It keeps listening while composing and cuts itself off when its point goes moot.
- Scoreboard (who-voted-what, counts) kept current in both modes — plumbing, not participation.
- Async: no digests, no nudges (YAGNI — the visual board suffices for review). Only a mode/role change log auto-posts.
- Bypass hatch (from 02, unchanged): lost votes can't be bypassed in-mode; persuade a vote-change or switch mode.
