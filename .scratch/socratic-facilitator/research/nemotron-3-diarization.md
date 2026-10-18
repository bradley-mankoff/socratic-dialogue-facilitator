# Nemotron-3-Diarization — note for SDF (2026-09-25)

Source: Bradley via OpenClaw — https://huggingface.co/nvidia/Nemotron-3-Diarization
Relevant to: Ticket 05 live-pipeline, Ticket 07 speaker-enrollment

## What it is

- **nvidia/Nemotron-3-Diarization** — open-weight speaker diarization ("who spoke when").
- Released Sept 23, 2026. Commercial-ready.
- Up to 8 speakers. Streaming + offline from single checkpoint.
- Sortformer lineage: output channels ordered by first arrival; streaming uses Arrival-Order Speaker Cache (AOSC) + FIFO queue.
- Latency configs (input buffer): 0.32s ultra-low (recommended min) / 0.64s / 1.04s / 30.4s offline. Raw minimum 80ms. Output frame resolution in multiples of 10ms. Chunked inference = no max duration limit.

## Why it matters for SDF

- Current decisions: 05 = faster-whisper local int8 live + pyannote `speaker-diarization-community-1` post-hoc; 07 = wespeaker resnet34-LM centroids + SPEAKER_XX fallback.
- This is a potential alternative / complement to pyannote diarizer:
  - Streaming-native (AOSC) vs post-hoc-only — could give live speaker labels, not just post-hoc relabel.
  - 8-speaker cap fits fixture (3 people) with headroom.
  - Local run via NeMo-Speech.cpp: `nemo-speech diarize meeting.wav` / `nemo-speech transcribe meeting.wav --diarize --json`
- Demo: https://huggingface.co/spaces/nvidia/nemotron-diarization
- Blog: https://huggingface.co/blog/nvidia/nemotron-diarization

## Suggested next step (for factory, not now)

- When 05/07 come up for revisit: compare Nemotron-3 vs pyannote community-1 on fixture audio (3-person Justice slice) for accuracy, CPU on M1 Max, license fit for self-host free default. Check embedding compatibility with wespeaker centroids (likely different space — binding rule from 07 §5 still applies: enrollment and matching must use identical model space).
