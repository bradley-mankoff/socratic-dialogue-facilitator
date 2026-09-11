# Live transcription + definition-search pipeline — findings

Ticket 05 · branch `research/live-pipeline` · 2026-09-11 · Fixture X: Justice (Republic Book I)

Standing prefs honored: free + self-hosted on this Mac (M1 Max, darwin arm64) while it is on;
no Plato corpus rebuild; no philosopher privileging; highly-cited informal defs.

## A. Real-time voice transcription (live mode)

### A1. Local engines surveyed (primary sources)

**OpenAI Whisper (model family, MIT code + weights).**
Six sizes; official table (A100-relative): tiny 39M (~1GB, ~10x), base 74M (~7x),
small 244M (~2GB, ~4x), medium 769M (~5GB, ~2x), large 1550M (~10GB, 1x),
turbo 809M (~6GB, ~8x, transcription-only — no translation task).
`.en` variants faster for English. Source: https://github.com/openai/whisper
(INCLUDES model-card.md; paper https://arxiv.org/abs/2212.04356).
Whisper itself is batch/file-oriented (30 s sliding window), not a streaming mic loop —
a streamer must be built around it.

**whisper.cpp (Metal backend, first-class Apple Silicon support).**
Ships a `stream` example for continuous mic input with tunable
`--step` (inference cadence, ~500 ms) / `--length` (audio context window, ~5 s),
plus no-speech threshold flags against silence hallucination.
M1 Max community Metal numbers: tiny ~45x, base ~30x, small ~22x, medium ~10x
real-time; large-v3-turbo often ~15–30x+ (one M1 Max 64 GB report: ~0.02–0.03 s
wall per 1 s audio). Practical streaming lag: small-class models ~200 ms;
large-v3-turbo hundreds of ms; large-v3 up to ~0.8–1.2 s depending on step/length.
Sources: https://github.com/ggml-org/whisper.cpp ;
benchmarks https://www.promptquorum.com/local-llms/apple-silicon-whisper-metal-benchmark ,
https://github.com/mundwerk-app/whisper-metal-benchmark .
Caveat: exact figures vary with version/quant/beam/thermals — treat as headroom
evidence (even medium is ~10x real-time on M1 Max), not latency guarantees.

**faster-whisper (CTranslate2 reimplementation, MIT).**
Up to 4x faster than openai/whisper at same accuracy with less memory; 8-bit
quantization on CPU and GPU; no FFmpeg system dep (PyAV-bundled decode);
**bundles Silero VAD** (`vad_filter=True`, conservative default drops >2 s
silences, tunable via `vad_parameters`); word-level timestamps; batched pipeline.
Official CPU bench (i7-12700K, small model, 13 min audio): int8 1m42s (~7.6x RT),
int8 batched 51s (~15x RT). GPU path needs NVIDIA CUDA/cuDNN — irrelevant on
this Mac; the CPU/int8 path is the Mac story. Source:
https://github.com/SYSTRAN/faster-whisper (benchmark table in README).

**WhisperX (BSD-2-Clause; word timestamps + diarization).**
faster-whisper backend + wav2vec2 forced alignment (word timestamps) + VAD
batching + speaker diarization via pyannote-audio; `--min/max_speakers` hints;
CPU runnable (`--device cpu --compute_type int8`, Mac-supported).
Stated limits (README "Limitations"): overlapping speech handled poorly;
diarization "far from perfect"; some numeric tokens unalignable.
**Batch/post-hoc tool, not a streaming loop** — diarization runs over a file.
Source: https://github.com/m-bain/whisperX ; paper https://arxiv.org/abs/2303.00747 .

**Apple SFSpeechRecognizer on-device (zero-dep, free).**
`supportsOnDeviceRecognition` gate + `requiresOnDeviceRecognition = true` keeps
audio on-device and offline; WWDC 2019 guidance: the server path's request
quotas (~1000 req/hr historically) and ~1-minute task cap **do not apply** to
pure on-device recognition; accuracy below server models; locale/device-gated
(check at runtime; missing models surface as errors e.g. 1101).
Sources: https://developer.apple.com/documentation/speech/sfspeechrecognizer ,
https://developer.apple.com/documentation/speech/sfspeechrecognitionrequest/requiresondevicerecognition .
Fits a native/Mac fallback with no downloads, no accounts, no network.

**VAD:** Silero VAD ships inside faster-whisper (`assets/silero_vad_v6.onnx`,
`t faster_whisper/vad.py`); WhisperX also offers Silero/pyannote VAD options.
VAD-gating the inference loop is what keeps silence from burning CPU and
hallucinating — non-optional for a live room.

### A2. Free-tier cloud APIs surveyed (fallback candidates only)

| Provider | Free tier (official pricing pages) | Self-host | Verdict |
|---|---|---|---|
| Deepgram | $200 signup credit, no card, no expiry; all public endpoints | Enterprise only (GPU/K8s, sales) | burn-down credit, then paid/min |
| AssemblyAI | $50 credits ≈ 185 h pre-recorded + 333 h streaming; 5 new streams/min free | Yes, same usage pricing, sales-engaged | most generous streaming allowance |
| Gladia | 50 € one-time (≈60–80 h) or 10 h/mo docs limit; 1 live concurrent free | Enterprise only | thinnest free live allowance |

Sources: https://deepgram.com/pricing ,
https://developers.deepgram.com/docs/self-hosted-deployment-environments ,
https://www.assemblyai.com/pricing , https://www.assemblyai.com/deployments/self-hosted ,
https://www.gladia.io/pricing , https://docs.gladia.io/chapters/limits-and-specifications/concurrency .
All three violate the standing "free while this Mac is on" pref as a *default*
(metered credits → paid; self-host = enterprise sales). Ranked fallback:
AssemblyAI (largest free streaming allowance) > Deepgram ($200 credit) > Gladia.

### A3. Multi-speaker handling

- Local: **pyannote.audio 4.x `speaker-diarization-community-1`** — CC-BY-4.0,
  gated Hugging Face download (accept terms + read token), then **fully local /
  offline** (`Pipeline.from_pretrained` on a cloned dir, no token, no net);
  exclusive (no-overlap) mode suits STT alignment; `num/min/max_speakers` hints.
  CPU works, GPU preferred. Sources: https://huggingface.co/pyannote/speaker-diarization-community-1 ,
  https://github.com/pyannote/pyannote-audio .
- WhisperX wires this together (`--diarize` → speaker-labeled segments) but is
  file-oriented: the live design is *stream rough transcript now, diarize +
  re-label segments post-hoc*.
- Cloud diarization exists (Deepgram/AssemblyAI add-ons, Recall.ai-style
  platform speaker streams) but is metered and contradicts the default.
- Honest limit, cited: overlapping speech is poorly handled by whisper/whisperX;
  in-room crosstalk will misattribute — the board must show speaker labels as
  provisional (cf. WhisperX Limitations, WhisperX README).

### A4. Recommendation — transcription

- **Default: faster-whisper, local, CPU int8.**
  - Live loop: `small.en` int8 + Silero VAD gate (~15x RT headroom on
    desktop-CPU-class silicon; M1 Max has far more headroom than the cited
    i7 bench) → sub-second partials.
  - Async/post-session pass: `medium` or `large-v3-turbo` for accuracy.
  - Why faster-whisper over whisper.cpp: Python-native (`pip install`,
    no build flags/ffmpeg), VAD + word timestamps built in, and it is the exact
    backend WhisperX expects — the diarization upgrade path needs no re-tooling.
  - Why not cloud default: metered credits + network dependency contradict the
    self-host-free standing pref.
- **Fallback chain (in order):**
  1. Apple on-device `SFSpeechRecognizer` (no downloads/accounts; lower accuracy).
  2. AssemblyAI free-tier streaming (opt-in, keyed, largest free allowance) —
     only when local accuracy demonstrably fails; never unprompted.
- **Diarization: pyannote `speaker-diarization-community-1`, post-hoc.**
  Download once (HF accept + token), run offline; align labels to VAD segments
  after the fact. Live loop stays single-stream; speaker tags backfill.

## B. Definition search for arbitrary X (highly-cited informal defs)

Constraint recap: no Plato corpus, no philosopher privileging; dictionary + web;
needs a cite + dedup policy. Key finding: **no single free API returns
"citation-ranked informal definitions"** — the ranking must be a local policy
over converging dictionary sources, with the web used only as corroboration.

### B1. Sources surveyed (primary sources)

- **Wiktionary Action API — DEFAULT, live-verified.**
  `https://en.wiktionary.org/w/api.php?action=query&…&titles=<X>` returned HTTP 200
  on 2026-09-11 from this Mac: `justice` = pageid 56878 with full wikitext
  (19,521 chars incl. etymology, senses, glosses) — parseable per-sense
  definitions with zero key, zero cost, no build. Terms: Wikimedia API Usage
  Guidelines v1.0 (2024-08-26) — correct User-Agent with contact, honor throttle
  signals, follow content licenses (CC BY-SA on republish), no circumvention;
  policy: https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_API_Usage_Guidelines .
- **Free Dictionary API (`dictionaryapi.dev`) — second dictionary vote.**
  No key, free ("free — and always will be"), `GET
  https://api.dictionaryapi.dev/api/v2/entries/en/<word>` → phonetics, origin,
  per-part-of-speech definitions + examples + synonyms/antonyms (shape verified
  against https://dictionaryapi.dev/ ). **Reliability flag:** live check from
  this Mac on 2026-09-11 returned HTTP 522 (origin unreachable) — design the
  chain to tolerate its absence; retry + fall through to Wiktionary parse.
- **Merriam-Webster Dictionary API — optional keyed third vote.**
  Free for non-commercial use, 1,000 queries/key/day, two reference APIs per
  registration; commercial/overage = paid license; branding/logo display
  required. Sources: https://dictionaryapi.com/ ,
  https://dictionaryapi.com/info/frequently-asked-questions .
  Cost is a key + attribution, not money — acceptable as an *optional* vote,
  not the default (keeps zero-signup default intact).
- **Brave Search API — on-demand web corroboration / counterexample search ONLY.**
  Credit model: $5/mo free credit ≈ 1,000 Search requests; **credit card
  required** (anti-fraud, spend-capped). Sources:
  https://api-dashboard.search.brave.com/documentation/pricing ,
  https://brave.com/search/api/ . The card requirement alone disqualifies it
  from the unprompted path; metered web search must never auto-fire per
  facilitator manners (see §D).
- **Considered and rejected as defaults:** ConceptNet 5 (CC BY-SA 4.0,
  https://conceptnet.io — relational graph, RelatedTo/Synonym edges, not
  dictionary glosses; no citation-count signal; API returned 502 from here on
  2026-09-11); Princeton WordNet offline (no citation signal at all);
  SEP/IEP (no API, and philosopher-privileging risk by construction).

### B2. Recommendation — search default + cite policy

- **Default chain for canonical pull (unprompted-safe, all keyless/local):**
  1. Wiktionary Action API senses for X (primary — structured, edited, referenced).
  2. Free Dictionary API glosses for X (second vote; skip on 5xx).
  3. Optional Merriam-Webster vote when a key is configured.
  Cache per-X (dictionary content is near-static); never re-pull mid-dialogue.
- **"Highly-cited" operationalized (no citation API exists, so converge):**
  score each candidate gloss by (i) cross-dictionary agreement — same normalized
  sense present in ≥2 independent sources ranks top; (ii) Wiktionary-side
  signals — sense order, usage notes, quotations count; (iii) on-demand web
  corroboration only when dictionaries disagree (Brave result overlap).
  Lexicographic consensus *is* the citation proxy; document the proxy openly.
- **Dedup policy:** normalize (lowercase → strip punctuation → lemmatize) →
  cluster senses at token-Jaccard ≥ ~0.6 (tune on fixture set) → keep one
  canonical gloss per cluster with the full source list attached; never show
  two wordings of one sense as rival definitions (that corrupts the board).
- **Cite policy (every board definition carries):** source name + article/entry
  URL + access date + license tag (Wiktionary: CC BY-SA; MW: logo/branding per
  their terms; dictionaryapi.dev: verify upstream license at build time and
  record it). No cite → not a canonical; facilitator-flagged claims stay
  visually distinct from sourced defs.

### B3. Fixture X = Justice — worked expectation

- Live-verified: Wiktionary `justice` (pageid 56878) parses to senses
  ("righteousness/equity" lineage from Latin *iūstitia*, per etymology) suitable
  as the canonical seed against Republic Book I moves (Cephalus →
  Polemarchus → Thrasymachus each *fail* it differently — the board's 3a/3b
  shapes attach to real senses, not straw).
- Expected chain output: Wiktionary primary senses + dictionaryapi.dev
  noun/verb glosses (when reachable) deduped to ~2–3 canonical glosses, each
  cited per §B2. Second fixture run should add a multi-word X (e.g.
  "civil disobedience") to prove the chain beyond single-word entries.

## C. What runs unprompted vs on demand

Per facilitator manners (silent facilitator; auto-canonicals; counterexamples
on demand only):

| Layer | Unprompted (automatic) | On demand only |
|---|---|---|
| Transcribe | mic → VAD-gated faster-whisper partials; post-hoc pyannote relabel | cloud STT upgrade (keyed, opt-in) |
| Canonical pull | dictionary chain (§B2) on each newly nominated X; cached | — |
| Counterexample search | NEVER (manners ban) | Brave/web search, facilitator-invoked or participant-requested |
| Philosopher/SEP lookup | NEVER (privileging ban) | explicit participant request only, labeled as one voice among many |

Metered or privileging-risk calls never fire without a deliberate trigger; the
unprompted path is fully local + keyless and therefore free forever.

## D. Open risks / build-time checks

1. `dictionaryapi.dev` reliability (HTTP 522 observed 2026-09-11) — chain must
   degrade to Wiktionary-only gracefully; add a third keyless vote if one exists.
2. ConceptNet/adjacent free APIs flaky from here (502) — do not depend on them.
3. pyannote needs a one-time HF account + terms acceptance (human step) before
   the offline clone; record token setup in build docs, never in repo.
4. Apple on-device fallback is locale/hardware-gated — check
   `supportsOnDeviceRecognition` at runtime, fail over audibly-invisible
   (log, don't interrupt the room).
5. Brave Search needs a credit card even for the free $5/mo — a human decision;
   keep it out of the default path regardless.
6. M1 Max latency figures are community benchmarks, not guarantees — first
   prototype must time `small.en` int8 streaming on THIS machine before
   committing to partial-refresh cadence.

## Sources (primary, in order of reliance)

Engine/model docs: https://github.com/openai/whisper ·
https://github.com/ggml-org/whisper.cpp · https://github.com/SYSTRAN/faster-whisper ·
https://github.com/m-bain/whisperX · https://arxiv.org/abs/2212.04356 ·
https://arxiv.org/abs/2303.00747 ·
https://developer.apple.com/documentation/speech/sfspeechrecognizer ·
https://developer.apple.com/documentation/speech/sfspeechrecognitionrequest/requiresondevicerecognition ·
https://huggingface.co/pyannote/speaker-diarization-community-1 ·
https://github.com/pyannote/pyannote-audio ·
Benchmarks: https://www.promptquorum.com/local-llms/apple-silicon-whisper-metal-benchmark ·
https://github.com/mundwerk-app/whisper-metal-benchmark ·
Pricing: https://deepgram.com/pricing ·
https://developers.deepgram.com/docs/self-hosted-deployment-environments ·
https://www.assemblyai.com/pricing · https://www.assemblyai.com/deployments/self-hosted ·
https://www.gladia.io/pricing · https://docs.gladia.io/chapters/limits-and-specifications/concurrency ·
Search/dictionary: https://dictionaryapi.dev/ ·
https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_API_Usage_Guidelines ·
https://dictionaryapi.com/ · https://dictionaryapi.com/info/frequently-asked-questions ·
https://api-dashboard.search.brave.com/documentation/pricing · https://brave.com/search/api/ ·
https://conceptnet.io ·
Live checks 2026-09-11 (this Mac): Wiktionary `justice` 200/pageid 56878/19,521 chars;
dictionaryapi.dev `justice` 522; ConceptNet `justice` 502.
