# Glossary — socratic-dialogue-facilitator

Project words. They mean what the v1 spec (docs/plan/2026-09-13-spec-v3.md, Epic description) says. Factory words (Idea, Spec, Epic, Bead, Workflow, Run, Human gate, Decision) mean what the Factory glossary says.

- **Target (X)**: the concept under definition (fixture: Justice, Republic Book I). One board per Symposium.
- **Symposium**: the user-facing name for one dialogue (Human, 2026-10-19; replaces "board" and "room" on screen, and the room label is gone). A Symposium is its word plus its participants: the same word with different people is a different Symposium, and the same word with the same people has at most one open Symposium at a time; after it closes, a new one is numbered ("Justice, second symposium").
- **Board**: the code's name for a Symposium's state (the board-state machine and its store). Never shown on screen.
- **Host**: the participant who starts a Symposium, like the host of a party game. The host enters their own name and email, the word, the other participants and the facilitator's role, invites people, and holds certain settings and meta actions. Every other participant is invited by the host.
- **Participant**: a person in a Symposium, known by name and email. Email is identity (it replaces honor-system display names); everyone sees names, only the host sees emails.
- **Invitation link**: a personal link, emailed by the forum from its own Gmail account, that signs one participant straight into one Symposium. It carries no protection: whoever opens it is that participant, because nothing in a Symposium is private. A first visit opens the welcome page: the word, who else is in it, and three sentences on how it works.
- **Lobby**: the small "who is here" panel on a Symposium page, listing names and whether each person has joined yet, never emails. Display only, with no Begin button; it gains a real job with live video sessions.
- **Private message**: a message from one participant to one other, kept inside the forum and shown only to those two, without revealing either email.
- **Source note**: the small parenthetical after a dictionary definition, like "(Wiktionary)", linking to the entry. License and access date stay recorded but are not shown.
- **Active definition**: the single definition under elenchus, front-center; counterexamples attach to it.
- **Counterexample shapes 3a / 3b**: 3a is IS-X-but-fails-the-definition; 3b fits-the-definition-but-is-NOT-X.
- **Iteration chain**: revision history as new version nodes, never edits; superseded nodes freeze with tallies intact.
- **Canvas**: closing summary that walks the debate as a story — who offered each definition, who raised each challenge, how that lands on the map. Attempts as nodes, refutations as labeled edges, active chain highlighted. PNG-only export. Its graph allows cycles: a rejected counterexample returns the room to the earlier attempt it struck.
- **Attempt**: plain user-facing word for one definition node on the canvas (Attempt 1, Attempt 2, the live one marked active). Machine ids never show on screen.
- **Set aside**: plain user-facing word for the tray box on the canvas, carrying earlier counterexamples forward with a caption saying each can be reopened on the active attempt or dropped.
- **Handle**: unique board-local identity string, bound to a participant's email. Voiceprint enrollment and provisional labels (tabled with the voice stack) also bind to handles.
- **Census**: for a question Q, BoardCensus(Q.openedAt) plus handles that subsequently cast on Q.
- **Q**: every majority question — counterexamples, mode switches, Socrates swaps, active-claim switches, ingress selection, tiebreak invocations, board close.
- **Standing**: a counterexample view — stands-ballots outnumber rebutted-ballots; 0–0 is not standing.
- **Refuted**: node-level verdict — some attached counterexample is standing AND 2 × stands > |Census| (strict majority).
- **Tray**: visible carry of unresolved counterexamples from a superseded node as carried_unvoted; press re-opens as a new Q on the active node, discard is system-logged.
- **Socrates seat**: the never-vacant questioner role, held by a human or (Participates mode only) the facilitator.
- **META / ELENCHUS**: teaching callouts (labeled META, quota-capped) versus challenges (ELENCHUS strikes).
- **Ingress**: live audio path per session — HostMic XOR GuestTabs, exactly one; switching is governance.
