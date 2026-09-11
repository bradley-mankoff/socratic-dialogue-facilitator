## Destination

Buildable spec for a self-hosted (this Mac on-only) Socratic dialogue facilitator — single board toggling async/live, silent facilitator, auto canonical defs + on-demand counterexamples, 2-D canvas summary — ready to hand to `/to-spec` then Piyaz tickets. Fixture X for all prototypes: Justice (Republic Book I).

## Notes

- Domain: Target (X), Board (canonical + claimed defs), Active definition (single def under elenchus), Counterexample shapes (3a IS-X-but-fails-def / 3b fits-def-but-is-NOT-X), Iteration chain, Canvas (post-dialogue 2-D summary, interactive + static export).
- Skills every session consults: `/grilling` + `/domain-modeling` for grilling tickets; `/research` subagents for research tickets; `/prototype` for canvas/board fidelity questions; `/ask-matt` to route when unsure.
- Standing preferences: self-host free while this Mac is on; multi-party URL ideally; live = real-time voice transcription + search layer; async = persistent board over days; facilitator never speaks verbally in live mode; auto-populate canonicals, counterexamples on demand only; highly-cited informal defs (no Plato corpus rebuild, no famous-philosopher privileging); Justice/Rep I as test fixture; open-source canvas libs over inventing pan/zoom.
- Tracker: wayfinder map lives local-markdown (`.scratch/socratic-facilitator/`). Implementation tickets go to Piyaz later (blocked: Piyaz OAuth refresh 500 on 2026-09-11 — human re-auth via `/mcp add` + project create, then re-`projectify.py --tracker piyaz --project <KEY>`).

## Decisions so far

<!-- one line per closed ticket: gist + link; decision lives in ticket -->

## Not yet specified

<!-- in-scope fog too coarse to ticket; graduates as frontier advances -->

- Transcription engine pick (local free vs API) and interruption UX in live mode.
- Search provider + ranking for highly-cited informal definitions; dedup + cite policy.
- Persistence model for board across async/live toggles (file, sqlite, crash recovery).
- Trust model on LAN/shared URL (no auth v1 vs minimal token).
- Canvas export fidelity (PNG/SVG fidelity, layout stability).

## Out of scope

<!-- beyond destination; never graduates; closed tickets stay linked here -->

- Rebuilding a Plato corpus or anchoring old dialogues (test fixture Justice excepted).
- Privileging famous-philosopher definitions over highly-cited informal ones.
- Always-on cloud hosting, multi-tenant auth, paid tunnels as the default path.
- Inventing interactive pan/zoom from scratch (adopt OSS).
