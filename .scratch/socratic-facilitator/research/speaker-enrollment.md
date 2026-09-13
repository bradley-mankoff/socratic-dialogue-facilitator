# Speaker enrollment and voiceprint calibration — findings

Ticket 07 · 2026-09-13 · Fixture X: Justice (Republic Book I)

Standing prefs honored: free + self-hosted on this Mac (M1 Max, darwin arm64)
while it is on; no Plato corpus; highly-cited informal defs (n/a to this ticket).

Ticket 02 resolves live/verbal votes against enrolled voiceprints, with
post-hoc diarization labels as fallback. Ticket 05 decided the pipeline this
must plug into: faster-whisper local int8 live + pyannote
`speaker-diarization-community-1` post-hoc. Ticket 01 decided the substrate
guests join through: Cloudflare Quick Tunnel public HTTPS URL (fallback LAN).

## Recommendation (one path for the Justice fixture test)

**Enroll with `pyannote/wespeaker-voxceleb-resnet34-LM` through the already-required
`pyannote.audio` stack; per-speaker centroid = L2-normalized mean of sliding-window
(3 s / 1 s) embeddings over ~30 s of VAD-gated calibration speech; bind to
post-hoc diarization by cosine match of enrolled centroids against per-speaker
diarization centroids; anyone who skips calibration keeps their anonymous
`SPEAKER_XX` label (the 02 fallback, unchanged).**

Why this one: it is the same library and embedding family as the decided
diarization stack (05), so enrollment adds no second framework and no second
model download beyond what diarization already needs; it is the smallest
accurate option surveyed; its license (CC-BY-4.0, attribution only) is
compatible with a self-hosted free default. Details in §§1–6.

## 1. Options surveyed (primary sources)

| Option | Embedding | License | Size | VoxCeleb EER (lower = better) | Verdict |
|---|---|---|---|---|---|
| **pyannote/wespeaker-voxceleb-resnet34-LM** (ResNet34 r-vector, TSTP, large-margin finetune) | 256-d | **CC-BY-4.0** (follows VoxCeleb dataset license) | **6.63M params, 4.55G FLOPs** [≈27 MB fp32 checkpoint — INFERENCE from param count] | **0.723% vox1-O / 0.867% vox1-E / 1.532% vox1-H** (LM + AS-Norm) | **RECOMMENDED** — same `pyannote.audio` stack as 05's diarizer, smallest accurate model |
| SpeechBrain `spkrec-ecapa-voxceleb` (ECAPA-TDNN, attentive pooling, additive-margin softmax) | 192-d | **Apache-2.0** | **~89 MB repo; embedding checkpoint ~83 MB** (~20–22M params) | **0.80%** VoxCeleb1-test (cleaned) | Runner-up — best license, strong accuracy, but ~3x the weights + a second framework (SpeechBrain + torchaudio) beside pyannote.audio |
| Resemblyzer (GE2E LSTM speaker encoder, Real-Time Voice Cloning lineage) | 256-d, L2-normalized | **Apache-2.0** (repo LICENSE, Resemble.AI 2019) | **~1.4–2M params** (3×LSTM-256 + 256→256 linear; checkpoint tens of MB — INFERENCE) | **No published VoxCeleb EER**; demos show tight same-speaker clusters only | Fallback only — `pip install resemblyzer`, ~1000x-RT on old GPUs, but older generation, **best on English only** per README, no benchmarked error rate to set a threshold from |
| `pyannote/embedding` (legacy x-vector/SincNet-style) | 512-d class | **MIT** | Small (legacy) | ~2.8% VoxCeleb1 raw-cosine, no VAD/PLDA | Superseded in-stack by the wespeaker wrapper above; no reason to enroll with it |
| WebRTC VAD era (`py-webrtcvad`, energy/GMM frame classifiers) | none — outputs **voiced/unvoiced per 10–30 ms frame** | WebRTC BSD-style ("Other" on the mirror) | KBs | n/a (no identity) | **Rejected for enrollment**: "classifies a piece of audio data as being voiced or unvoiced" — speech-presence only, carries zero speaker identity, so it cannot produce a voiceprint. Rightful role is *gating* calibration capture (§3), same job Silero VAD already does inside faster-whisper (05) |

Sources: wespeaker wrapper card https://huggingface.co/pyannote/wespeaker-voxceleb-resnet34-LM
(license, `Inference` whole/sliding API, `cdist` cosine usage);
upstream results + `register`/`recognize` enrollment API
https://huggingface.co/Wespeaker/wespeaker-voxceleb-resnet34-LM
(paper https://arxiv.org/pdf/2210.17016.pdf);
ECAPA card https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb
(license, 0.80% EER, `EncoderClassifier`/`SpeakerRecognition.verify_files` API;
file sizes per repo listing https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb/tree/main);
ECAPA paper ref `DBLP:conf/interspeech/DesplanquesTD20` via that card;
Resemblyzer https://github.com/resemble-ai/Resemblyzer
(voice-profile from "a few seconds of speech (5s–30s)", GE2E paper
https://arxiv.org/pdf/1710.10467.pdf);
legacy card https://huggingface.co/pyannote/embedding (MIT);
py-webrtcvad https://github.com/wiseman/py-webrtcvad (voiced/unvoiced framing).

Diarizer context (05's decided model, reused here):
`pyannote/speaker-diarization-community-1` —
https://huggingface.co/pyannote/speaker-diarization-community-1 —
CC-BY-4.0, gated HF download (accept terms + token), then fully local/offline.
Pipeline internals relied on in §5 (multi-stage segmentation → per-chunk
embedding → centroid-linkage/VBx clustering → `Annotation` + exclusive
annotation + per-speaker centroid array ordered by label):
https://github.com/pyannote/pyannote-audio/blob/main/src/pyannote/audio/pipelines/speaker_diarization.py ;
design report Bredin, INTERSPEECH 2023 (cited on the wespeaker card).

## 2. Calibration UX (~30 s per participant at session start)

Target shape, grounded in the closest thing to an official enrollment spec —
pyannote's own recurring-meetings identification tutorial
(https://www.pyannote.ai/blog/speaker-identification-system-recurring-meetings):
**one voiceprint per speaker; clip ≤ 30 s, target speaker only, normal speaking
style, language-agnostic; quality tip: ≥ 10 s uninterrupted clean speech**
(a prior-meeting segment works; for us, a live calibration read works).
Resemblyzer's README independently converges on the same window
("5s–30s" for a voice profile).

Proposed fixture flow (host + two friends, ~2 min total for 3 people):

1. **Prompt.** Each participant reads ~30 s aloud — fixture-flavored script,
   e.g. Thrasymachus's opening claim ("justice is the advantage of the
   stronger") plus one follow-up sentence, twice. Fixed text is fine:
   embeddings are text-independent at this duration, and a shared script keeps
   phonetic coverage comparable across speakers [INFERENCE — standard
   text-independent-speaker-recognition practice, not a cited claim].
2. **Capture.** Browser mic → `MediaRecorder` chunks (§4) → server decodes to
   16 kHz mono (both shortlisted models expect 16 kHz mono:
   ECAPA card states it explicitly; wespeaker takes 16 kHz mel input).
   Show a live level meter + voiced-seconds counter so the room sees progress.
3. **Quality gate (re-prompt, don't silently enroll junk).**
   VAD-gate (reuse Silero VAD already bundled with faster-whisper per 05) and
   require **≥ 10 s voiced** (the pyannote ≥10 s tip as a hard floor),
   single-speaker (one calibration at a time, others muted), plus cheap
   signal checks: reject fully-clipped or near-silent captures. On failure,
   say *why* ("only 4 s of speech detected — read it once more") and retry.
4. **Centroid.** Don't embed the 30 s blob as one vector: run the card's
   sliding-window mode (`duration=3.0, step=1.0`), L2-normalize, take the
   mean → one 256-d voiceprint per speaker. (Averaging short clean windows
   beats one long blob — pyannote cookbook practice; the card's own sliding
   example uses exactly 3.0 s / 1.0 s.)
5. **Store.** `speakers.json`-style map `{name: embedding}` per the tutorial's
   enrollment store — but **local file on the Mac, never a cloud voiceprint
   endpoint** (the tutorial's `/v1/voiceprint` + `/v1/identify` API is
   keyed/metered and violates the self-host pref; we copy its *protocol*,
   not its backend). Voiceprints persist across boards until a participant
   re-enrolls (mic change = re-enroll: the tutorial flags that switching
   laptop-mic → headset degrades matches).
6. **Skip is first-class.** Calibration is opt-in per participant; skippers go
   straight to the §5 fallback. The room sees enrolled ✓ vs guest `SPEAKER_XX`
   state on the board so vote attribution (§6) is never ambiguous.

## 3. License / size / accuracy, fixture-weighted

- **License.** CC-BY-4.0 (wespeaker) needs one thing Apache-2.0 doesn't: keep
  an attribution line (model + VoxCeleb source) in the app's about/docs.
  Operationally identical otherwise for a self-hosted free default — no
  account, no key, no gating on the embedding model itself. (Note: the
  *diarizer* `speaker-diarization-community-1` is separately gated — one-time
  HF accept + token, then offline — already accepted as 05's cost.)
- **Size.** 6.63M params / 4.55G FLOPs is the lightest benchmarked option
  here, ~3x smaller than ECAPA's ~89 MB repo; CPU inference on M1 Max is a
  non-issue (single-digit GFLOPs per window; enrollment is a one-time,
  non-streaming computation, unlike the live STT loop). No separate download
  if the diarization stack is already vendored — same `Model.from_pretrained`
  mechanism, same torch runtime.
- **Accuracy expectations (honest).** VoxCeleb EERs (~0.7–0.8%) are
  clean-benchmark verification numbers, **not** small-room identification
  accuracy — expect worse with laptop/phone mics, room reverb, and crosstalk.
  What transfers: the rank-order (wespeaker-LM ≈ ECAPA ≫ legacy/GE2E-LSTM)
  and the operational tips that actually move fixture accuracy —
  mic/environment consistency between enrollment and session, only expected
  speakers in the match set (absent-speaker voiceprints cause false matches),
  and a tuned match threshold (start ~50 on a 0–100 confidence scale per the
  tutorial, then adjust on fixture data). Overlapping speech misattributes —
  the cited WhisperX/05 limit — applies to vote segments too: board labels
  stay provisional (§6).

## 4. Guest-mic feasibility (remote friends on the 01 URL)

- **Quick Tunnel default: YES.** `getUserMedia()` requires a secure context —
  HTTPS, `file:///`, or `localhost` only; in insecure contexts
  `navigator.mediaDevices` is `undefined`
  (https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia,
  https://developer.mozilla.org/en-US/docs/Web/Security/Defenses/Secure_Contexts).
  The Quick Tunnel URL is public **HTTPS** (01 findings), so remote guests get
  a secure context with zero setup; capture via the standard
  `getUserMedia` → `MediaRecorder` (`start(timeslice)` chunking,
  `ondataavailable` Blob flow per
  https://developer.mozilla.org/en-US/docs/Web/API/MediaRecorder) →
  POST/WebSocket to the Mac, which decodes (Opus/WebM → 16 kHz mono WAV) and
  embeds. Note 01's constraint rides along: no SSE over Quick Tunnels —
  use WebSocket or polling for the upload/progress channel.
- **LAN fallback: mic breaks for guests.** Plain-`http://<lan-ip>` is *not* a
  secure context for remote devices (the `localhost`/loopback exception
  covers only the host's own browser), so phone/laptop guests get no
  `mediaDevices` and calibration capture fails — while the host's own
  `http://localhost` capture keeps working. Fixture rule: **if the session
  falls back to LAN + QR, enrollment becomes host-mic-only** (pass a
  handheld mic) or the room drops to post-hoc labels; don't debug
  "mic not working" on guest phones over plain HTTP — it's the platform,
  not a bug.
- **Permissions UX.** `getUserMedia` always prompts; the request must come
  from a top-level document of a valid origin (iframes need
  `allow="microphone"` + Permissions-Policy). One tap per guest, then
  calibration proceeds. [INFERENCE: verify iOS Safari chunk cadence on the
  fixture run — `MediaRecorder` timeslice behavior varies by browser; the
  upload protocol should tolerate irregular chunk sizes.]

## 5. Binding enrollment identities to post-hoc diarization labels

The diarizer outputs anonymous labels (`SPEAKER_00`, …) plus, per the pipeline
source, an exclusive (no-overlap) annotation and a **per-speaker centroid
array ordered by label** — the same embedding space as enrollment when both
use the wespeaker model. Binding = the tutorial's OSS-equivalent loop:

1. Post-hoc pass: `Pipeline.from_pretrained("pyannote/speaker-diarization-community-1")`
   over the session audio (with `num/min/max_speakers` hints when known —
   e.g. 3 for the fixture) → `diarization` Annotation + `speaker_embeddings`
   centroids.
2. Cosine-match each diarized centroid against the enrolled centroid store
   (the card's own `cdist(…, metric="cosine")` pattern); assign the best name
   above threshold, **exclusively** (one voiceprint → at most one diarized
   speaker; the tutorial's `matching.exclusive=true` default).
3. Below-threshold or skipped speakers keep `SPEAKER_XX` — exactly the 02
   fallback, and exactly the tutorial's `"match": null` unknown-speaker
   shape (`diarizationSpeaker` preserved alongside, so audit/re-enroll later
   is trivial: pull their clean segment from the recording and enroll
   post-hoc, which the tutorial explicitly blesses).
4. Align to transcript by segment overlap (tutorial §3 pattern: per-word
   speaker = max-overlap segment label) and render enrolled names vs
   `SPEAKER_XX` distinctly on the board.

Two binding rules that must survive into build: (a) **enrollment and runtime
matching MUST use the identical model object** — embeddings from different
models live in incomparable spaces, so cross-model cosine is meaningless
[INFERENCE from the geometry of learned embeddings, stated as a design rule];
(b) re-tune the match threshold on fixture data rather than shipping a magic
number — procedure: enroll 3 fixture voices, hold out a second clip each,
sweep the threshold, pick the point with no cross-speaker false accepts.

## 6. Justice fixture test path

1. Host serves board on this Mac; two friends join via Quick Tunnel HTTPS URL
   (01 default) — secure context confirmed (`window.isSecureContext` true).
2. Each of the 3 reads the calibration script (~30 s); server VAD-gates,
   builds three 256-d centroids, stores locally. One friend optionally
   skips → exercises the fallback.
3. Run the Republic Book I slice (Cephalus → Polemarchus → Thrasymachus moves
   as in 05's fixture); live faster-whisper partials unattributed, post-hoc
   pyannote relabel binds enrolled names / `SPEAKER_XX`.
4. Cast test verbal votes ("I stand with Thrasymachus"); resolve each vote
   segment against enrolled voiceprints per 02's universal-franchise tally,
   with the skipper's vote visibly attributed to their `SPEAKER_XX` label.
5. Pass criteria: both enrolled friends attributed correctly across segments;
   skipper stays stably anonymous (one label, not fragmented); threshold
   value + false-accept/false-reject counts recorded here for the build.

## Sources (primary, in order of reliance)

- Embedding/model cards: https://huggingface.co/pyannote/wespeaker-voxceleb-resnet34-LM ·
  https://huggingface.co/Wespeaker/wespeaker-voxceleb-resnet34-LM ·
  https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb ·
  https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb/tree/main ·
  https://huggingface.co/pyannote/embedding ·
  https://huggingface.co/pyannote/speaker-diarization-community-1
- Code/docs: https://github.com/pyannote/pyannote-audio/blob/main/src/pyannote/audio/pipelines/speaker_diarization.py ·
  https://github.com/resemble-ai/Resemblyzer ·
  https://github.com/wiseman/py-webrtcvad ·
  https://github.com/wenet-e2e/wespeaker/blob/master/docs/pretrained.md
- Papers: https://arxiv.org/pdf/2210.17016.pdf (WeSpeaker) ·
  https://arxiv.org/pdf/1710.10467.pdf (GE2E) ·
  Desplanques et al., ECAPA-TDNN, Interspeech 2020 (via ECAPA card) ·
  Bredin, pyannote.audio 2.1 pipeline, Interspeech 2023 (via wespeaker card)
- Enrollment protocol model: https://www.pyannote.ai/blog/speaker-identification-system-recurring-meetings
  (requirements, ≥10 s tip, threshold/exclusive/unknown guidance; cloud
  endpoints rejected for our backend, protocol adopted)
- Browser capture: https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia ·
  https://developer.mozilla.org/en-US/docs/Web/Security/Defenses/Secure_Contexts ·
  https://developer.mozilla.org/en-US/docs/Web/API/MediaRecorder
- Sibling context: `.scratch/socratic-facilitator/research/live-pipeline.md` (05 pipeline) ·
  `.scratch/socratic-facilitator/research/host-substrate.md` (01 substrate) ·
  `.scratch/socratic-facilitator/issues/02-board-semantics.md` (vote semantics)
