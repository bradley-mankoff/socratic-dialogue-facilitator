# 07 — Speaker enrollment and voiceprint calibration

Type: research
Status: resolved
Blocked by: none

## Question

Board semantics (02) resolves live/verbal votes against enrolled voiceprints with post-hoc diarization labels as fallback. Survey open-source voiceprint/speaker-enrollment options compatible with the decided pipeline (05: faster-whisper local int8, pyannote speaker-diarization-community-1 post-hoc): calibration UX (~30s enrollment speech per participant at live session start), embedding model license and size, match-accuracy expectations, web-mic feasibility for remote guests joining via the shared URL, and how enrollment identities bind to post-hoc diarization labels when someone skips calibration. Recommend one enrollment path for the Justice fixture test. Related: 05 (post-hoc-only call now superseded for enrolled speakers), 01 (tunnel URL guests use).

## Answer

Findings: `.scratch/socratic-facilitator/research/speaker-enrollment.md` on branch `research/enrollment` (merged to main).
Gist: enroll with pyannote/wespeaker-voxceleb-resnet34-LM (CC-BY-4.0, 6.63M params, EER 0.723% vox1-O) inside the already-required pyannote.audio stack — per-speaker centroid from ~30s VAD-gated calibration speech, cosine-matched against post-hoc diarization centroids with exclusive assignment. Runner-up SpeechBrain ECAPA (Apache-2.0, heavier + second framework); Resemblyzer fallback; webrtcvad rejected for identity (gating only). Remote guests capture mic over the Quick Tunnel HTTPS URL (secure context for getUserMedia); LAN plain-HTTP fallback is host-mic-only — not a bug. Skippers keep SPEAKER_XX labels. Justice fixture: 3 voices enroll via Thrasymachus-claim script, one friend optionally skips.
