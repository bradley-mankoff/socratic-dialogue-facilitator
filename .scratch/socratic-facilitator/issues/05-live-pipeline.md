# 05 — Live transcription + definition-search pipeline

Type: research
Status: resolved
Blocked by: none

## Question

Survey free self-host-compatible paths for (a) real-time voice transcription in live mode (local engines vs free-tier APIs, Mac M1 Max fit, multi-speaker handling, latency) and (b) highly-cited informal definition search for arbitrary X (no Plato corpus, no philosopher privileging; dictionary + web, cite + dedup policy). Deliver one recommended transcription default + fallback, one search default + cite policy, and what runs unprompted (transcribe, canonical pull) vs on demand (counterexample search) per facilitator manners.

## Answer

Findings: `.scratch/socratic-facilitator/research/live-pipeline.md` on branch `research/live-pipeline`.
Gist: transcription default faster-whisper local CPU int8 (small.en live + Silero VAD, medium/large-v3-turbo async pass) with post-hoc pyannote speaker-diarization-community-1 relabel; fallback Apple on-device SFSpeechRecognizer, then opt-in AssemblyAI streaming. Search default Wiktionary Action API (live-verified: justice pageid 56878) + Free Dictionary API second vote (HTTP 522 observed — chain tolerates absence); lexicographic consensus as citation proxy, token-Jaccard dedup (~0.6), cite-every-def policy. Unprompted = VAD-gated transcription + dictionary canonical pull (all local/keyless); on-demand only = Brave/web counterexample search + cloud STT upgrade; philosopher lookups never unprompted.
