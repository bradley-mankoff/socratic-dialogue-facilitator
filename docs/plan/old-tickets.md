# The earlier factory's tickets for v1

The earlier factory cut `docs/plan/2026-09-13-spec-v3.md` into twenty tickets, SDF-1 to SDF-20, on 2026-09-13 and kept them in Piyaz, a tracker that is now retired. This file copies their text word for word from that session's log (2026-10-18), so nothing in the plan is lost. It is a record, not a status board: the Factory tracks work in Beads.

Eight were built and merged into `main` before the earlier factory stopped: SDF-1, 2, 3, 5, 6, 8, 9 and 16. On 2026-10-18 `python3 -m pytest -q` passed 325 tests on `main` (commit 4184605). The other twelve were never started. "Lights-on" marked a ticket whose result the Human judged by eye; "stories" are the spec's numbered user stories.

## SDF-1: Scaffold repo with green pytest gate (built, PR #1)

Lay out the repo (server, board logic, dictionary chain, voice, web UI homes) with pytest -q green from an empty suite. Establishes the gate every later slice must keep green. Spec SDF-N1, Testing Decisions.

Acceptance criteria:
- pytest -q passes on the empty suite
- Module homes exist for board logic, dictionary chain, voice, and web UI
- Gate command matches factory.json exactly

## SDF-2: Implement verdict predicates machine and durable store (built, PR #2)

Build the headless verdict core: handles, BoardCensus, Q freeze, integer refute predicate, standing view, tie rule with 1-human exception, re-vote, inactive freeze, mode-switch recompute, close freeze. Persists every mutation to local disk. Tested headlessly, no UI. Spec SDF-N1 predicates plus stories 16, 17, 21.

Acceptance criteria:
- Headless tests assert refute on strict census majority and fail on ties
- Tests assert CE census freeze with late-caster inclusion
- Tests assert mode-switch recompute and close freeze
- Every mutation persists; reload reconstructs identical state

Depends on: SDF-1.

## SDF-3: Implement dictionary chain over stubbed HTTP (built, PR #3)

Build the Wiktionary-first chain with Free Dictionary API second vote over injectable HTTP. Degrades to surviving sources on 5xx and returns the explicit empty state when all sources are down or X has no hit. Never merges distinct senses; case and whitespace normalization only. Spec SDF-N1 stories 8, 34, 35.

Acceptance criteria:
- Stubbed full convergence returns ranked senses with cites
- Stubbed dictionaryapi 522 still returns Wiktionary senses
- All sources down returns the explicit empty state, never blank consensus
- Justice virtue and institution senses stay distinct

Depends on: SDF-1.

## SDF-4: Render canonicals on board open (not built)

Board-open view pulls the chain and renders canonicals with source, link, access date, and license badges from cache. Human judges clarity and cite visibility. Spec SDF-N1 stories 8, 9, 10.

Acceptance criteria:
- Opening a board shows cached canonicals with all four cite fields
- Re-pull never rewrites displayed canonicals mid-dialogue
- Human accepts cite clarity and layout

Depends on: SDF-3.

## SDF-5: Implement board operations end to end (built, PR #4)

Open boards keyed by (X, label), choose mode per board, claim canonicals source-tagged or author originals, auto-activate the first claim, and create revision nodes. Covers stories 1 to 5, 11, 46. API plus minimal views; full UI lands in the board UI pass.

Acceptance criteria:
- Second board for same X opens with distinct label and shared cache
- First claim auto-activates; mode stored per board
- Revision creates a new node and never edits history

Depends on: SDF-2.

## SDF-6: Implement counterexamples and votes end to end (built, PR #5)

Allege labeled 3a and 3b counterexamples, cast ambient and explicit ballots with one-per-person dedup and explicit precedence, evaluate the integer predicate, render the live scoreboard, and run tiebreak-invoke governance. Covers stories 15 to 21. The bottleneck slice after the predicates machine.

Acceptance criteria:
- Alleged CE opens a ballot; majority of frozen census refutes
- Tie resolves not-refuted except decisive human in 1-human rooms
- Ambient plus explicit votes dedupe to one counted ballot each
- Scoreboard shows who voted what including invoked tiebreaks

Depends on: SDF-2.

## SDF-7: Implement carry tray and inactive freeze (not built)

Revision copies attached counterexamples into the visible tray as carried_unvoted; press attaches unvoted to the active node as a new Q and discard logs only. Nodes that lose active freeze with tallies intact. Tray items stay off verdicts and the canvas live path. Spec stories 13, 39.

Acceptance criteria:
- Revision carries CEs to the tray as unvoted
- Press opens a new ballot on the active node; discard logs
- Deactivated nodes reject further casts

Depends on: SDF-6.

## SDF-8: Implement governance questions and system log (built, PR #6)

Mode switches, Socrates swaps, active-claim switches, ingress selection, and close run as ordinary majority Qs with the facilitator-blind system log recording each event. Covers stories 4, 22, 43, 47. Close freezes tallies and snapshots the tray.

Acceptance criteria:
- Each governance move passes by majority and logs as a system event
- Log entries never render as facilitator contributions
- Close freezes tallies, snapshots carried_unresolved, ends input

Depends on: SDF-2.

## SDF-9: Implement roles and seats (built, PR #7)

Socrates seat never vacant with named-swap questions, defender equals active claimant, cede runs offer plus accept with both logged, leavers keep the seat until reassigned. Covers stories 22, 26, 27.

Acceptance criteria:
- Seat has an owner at all times including after tag-outs
- Cede without accept leaves defense unchanged
- Facilitator holds no seat and no ballot in Facilitates mode

Depends on: SDF-2.

## SDF-10: Build board web UI pass (not built)

Full board layout: single active definition front-center with counterexamples nearby, history pan over the same graph store, late-joiner replay of records plus open tallies, pinned initial response always visible. Human judges look and flow. Covers stories 7, 12, 14.

Acceptance criteria:
- Active definition renders front-center with nearby counterexamples
- History pan reaches superseded nodes with frozen tallies
- Late joiner sees records plus open tallies and can cast
- Human accepts layout and flow

Depends on: SDF-4, SDF-5, SDF-6, SDF-7, SDF-8, SDF-9.

## SDF-11: Build live capture pipeline over fixture audio (not built)

Voice-activity-gated capture through faster-whisper int8 emits confirmed transcript segments within 3s of segment end from fixture audio files. No word-streaming display by design. Feeds the transcript store the tally reads. Spec story 28.

Acceptance criteria:
- Fixture audio yields confirmed segments within 3s of activity end
- Silence gates capture instead of hallucinating
- No streaming partials path exists in the build

Depends on: SDF-5.

## SDF-12: Implement enrollment and live labels (not built)

30s calibration enrollment binds voice to handle via embedding centroid; live labels match by cosine with published threshold; below-threshold and overlaps stay provisional with full franchise; skippers keep stable provisional labels. Human speaks the script and judges the flow. Covers stories 29, 30, 31, 49.

Acceptance criteria:
- Calibration binds voice to handle and survives the session
- Weak matches and overlaps render provisional, never guessed
- Skip path yields a stable votable label
- Human completes enrollment and accepts the flow

Depends on: SDF-11.

## SDF-13: Implement post-hoc diarization relabel (not built)

After the session, the diarization pass backfills provisional segments with speaker labels and writes corrected transcripts without touching ballots already cast. Covers story 29 second half.

Acceptance criteria:
- Provisional segments relabel after the post-hoc pass
- Ballots cast under provisional labels keep attribution
- Pass runs fully offline after a one-time model fetch

Depends on: SDF-11.

## SDF-14: Implement ambient tally via fixtures (not built)

Transcript and timing fixtures drive vote events including explicit-beats-late-ambient and dedupe-by-speaker, giving the headless seam for ambient tally. Wires the brain classifier behind it. Covers stories 18, 19.

Acceptance criteria:
- Fixture with late ambient after explicit keeps the explicit ballot
- Same speaker twice yields one counted ballot
- Classifier retraction never demotes an explicit

Depends on: SDF-6, SDF-11.

## SDF-15: Implement facilitator voice modes (not built)

META versus ELENCHUS labeling with live quota one per defender turn and async quota one per revision node, extras dropped as moot; staleness quotes with quoted target ids; self-cut on moot; peer suggestions in Participates; transparent reasoned ballots. Covers stories 23, 24, 25, 26.

Acceptance criteria:
- Over-quota META drops as moot in both live and async
- Every facilitator post carries type plus quoted target
- Facilitator ballots post visible reasons at equal weight

Depends on: SDF-6, SDF-9.

## SDF-16: Implement on-demand search and SEP path (built, PR #8)

Web counterexample search fires only on deliberate trigger; SEP arrives via link-out or pasted excerpt labeled as one voice, never crawled and never unprompted. Covers stories 36, 37, 38.

Acceptance criteria:
- No web call fires without an explicit trigger
- SEP entry renders labeled via link or paste
- Unprompted paths never touch philosopher sources

Depends on: SDF-3, SDF-5.

## SDF-17: Build canvas interactive view and PNG export (not built)

Cytoscape graph over the board store: attempt nodes, labeled refutation edges, highlighted active chain, carried_unresolved off-path; pan and zoom plus PNG-only export with graph-JSON assertions. Human judges the read. Covers stories 39, 40.

Acceptance criteria:
- Justice fixture chain renders nodes, edges, and highlighted path
- PNG export matches the live chain; JSON assertions cover content
- Tray leftovers render carried_unresolved off-path
- Human accepts the read at a glance

Depends on: SDF-6, SDF-7.

## SDF-18: Implement share URLs and sleep resume (not built)

One-command Quick Tunnel share URL plus QR LAN fallback; board identity stays local with per-mutation persistence; sleep and crash resume drops live mics, keeps centroids, and rejoins guests on the current URL. Covers stories 41, 42.

Acceptance criteria:
- Share command yields a joinable URL; LAN fallback needs no third party
- Kill and restart reconstructs decided state exactly
- No stable public URL is promised without a named tunnel

Depends on: SDF-5.

## SDF-19: Build first-run experience and notices (not built)

Weight downloads progress visibly and name missing pieces including HF accept and token without blocking dictionaries; metered-use notice precedes metered boards; host can export recordings before auto-delete. Human runs first run and judges. Covers stories 44, 45, 52.

Acceptance criteria:
- Missing weight or token fails with its exact name
- Metered notice precedes any metered board
- Export preserves audio that auto-delete would remove
- Human completes first run and accepts the flow

Depends on: SDF-1, SDF-11.

## SDF-20: Write Mac acceptance script (not built)

Named script distinct from the repo gate: enroll voices, run the Republic-I fixture slice, bind labels, resolve test votes, export the PNG. Voice topology fixed to room mic until call paths exist. Covers story 50.

Acceptance criteria:
- Script runs end to end on the host Mac with fixtures
- Script output separates hardware results from pytest results
- pytest gate never executes hardware paths

Depends on: SDF-11, SDF-12, SDF-13, SDF-17.
