# Glossary — socratic-dialogue-facilitator

Project words. They mean what the v1 spec (docs/plan/2026-09-13-spec-v3.md, Epic description) says. Factory words (Idea, Spec, Epic, Bead, Workflow, Run, Human gate, Decision) mean what the Factory glossary says.

- **Target (X)**: the concept under definition (fixture: Justice, Republic Book I). One board per (X, label).
- **Board**: the shared room for one Target X with a distinct label; identity is (X, label).
- **Active definition**: the single definition under elenchus, front-center; counterexamples attach to it.
- **Counterexample shapes 3a / 3b**: 3a is IS-X-but-fails-the-definition; 3b fits-the-definition-but-is-NOT-X.
- **Iteration chain**: revision history as new version nodes, never edits; superseded nodes freeze with tallies intact.
- **Canvas**: closing 2-D summary — attempt nodes, labeled refutation edges, highlighted active chain; PNG-only export.
- **Handle**: unique board-local identity string. Voiceprint enrollment, provisional labels, and async names all bind to handles.
- **Census**: for a question Q, BoardCensus(Q.openedAt) plus handles that subsequently cast on Q.
- **Q**: every majority question — counterexamples, mode switches, Socrates swaps, active-claim switches, ingress selection, tiebreak invocations, board close.
- **Standing**: a counterexample view — stands-ballots outnumber rebutted-ballots; 0–0 is not standing.
- **Refuted**: node-level verdict — some attached counterexample is standing AND 2 × stands > |Census| (strict majority).
- **Tray**: visible carry of unresolved counterexamples from a superseded node as carried_unvoted; press re-opens as a new Q on the active node, discard is system-logged.
- **Socrates seat**: the never-vacant questioner role, held by a human or (Participates mode only) the facilitator.
- **META / ELENCHUS**: teaching callouts (labeled META, quota-capped) versus challenges (ELENCHUS strikes).
- **Ingress**: live audio path per session — HostMic XOR GuestTabs, exactly one; switching is governance.
