## Destination

Buildable spec for a self-hosted (this Mac on-only) Socratic dialogue facilitator — single board toggling async/live, silent facilitator, auto canonical defs + on-demand counterexamples, 2-D canvas summary — ready to hand to `/to-spec` then Piyaz tickets. Fixture X for all prototypes: Justice (Republic Book I).

## Notes

- Domain: Target (X), Board (canonical + claimed defs), Active definition (single def under elenchus), Counterexample shapes (3a IS-X-but-fails-def / 3b fits-def-but-is-NOT-X), Iteration chain, Canvas (post-dialogue 2-D summary, interactive + static export).
- Skills every session consults: `/grilling` + `/domain-modeling` for grilling tickets; `/research` subagents for research tickets; `/prototype` for canvas/board fidelity questions; `/ask-matt` to route when unsure.
- Standing preferences: self-host free while this Mac is on; multi-party URL ideally; live = real-time voice transcription + search layer; async = persistent board over days; facilitator never speaks verbally in live mode; auto-populate canonicals, counterexamples on demand only; highly-cited informal defs (no Plato corpus rebuild, no famous-philosopher privileging); Justice/Rep I as test fixture; open-source canvas libs over inventing pan/zoom.
- Tracker: wayfinder map lives local-markdown (`.scratch/socratic-facilitator/`). Factory migrated to Piyaz project **SDF** (2026-09-11); implementation tickets publish there.

## Decisions so far

<!-- one line per closed ticket: gist + link; decision lives in ticket -->
- [Free self-host URL while this Mac is on](issues/01-host-substrate.md) — default Cloudflare Quick Tunnel ($0, no account), fallback LAN + QR
- [Canvas shape without inventing pan/zoom](issues/04-canvas-shape.md) — adopt Cytoscape.js (MIT, first-party PNG export + JSON round-trip)
- [Live transcription + definition-search pipeline](issues/05-live-pipeline.md) — faster-whisper local int8 + Wiktionary-first chain with cite/dedup policy
- [Migrate factory to Piyaz](issues/06-piyaz-migration.md) — project SDF live, factory.json tracker=piyaz, dry-run passes
- [Board semantics for single toggleable board](issues/02-board-semantics.md) — modes renamed LLM-as-Socrates / LLM-as-participant / LLM-only-assists; universal-franchise majority votes; ambient tally; revision-by-new-node; toggle cut locked
- [Speaker enrollment and voiceprint calibration](issues/07-speaker-enrollment.md) — wespeaker resnet34-LM centroids (~30s calibration), tunnel-HTTPS mic for guests, SPEAKER_XX fallback

## Not yet specified

<!-- in-scope fog too coarse to ticket; graduates as frontier advances -->

- Persistence model for board across async/live toggles (file, sqlite, crash recovery).
- Trust model on LAN/shared URL (no auth v1 vs minimal token).

## Out of scope

<!-- beyond destination; never graduates; closed tickets stay linked here -->

- Rebuilding a Plato corpus or anchoring old dialogues (test fixture Justice excepted).
- Privileging famous-philosopher definitions over highly-cited informal ones.
- Always-on cloud hosting, multi-tenant auth, paid tunnels as the default path.
- Non-definitional claims (empirical predictions etc.) — future direction, beyond this spec
- Inventing interactive pan/zoom from scratch (adopt OSS).
