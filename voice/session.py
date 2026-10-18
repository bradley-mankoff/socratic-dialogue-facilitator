"""SDF-18 voice session: durable centroids, ephemeral live mics.

Two homes with opposite durability, because sleep/crash resume must drop
live mics and keep centroids (spec story 41):

* :class:`EnrollmentStore` — per-board enrollment centroids (the ~30 s
  calibration voiceprint binding a handle to a speaker), persisted as one
  JSON file per board with atomic rewrite + fsync. Survives sleep, crash,
  and restart. Keyed by handle_id; handles themselves stay journal-owned
  (this store never enrolls, never renames).
* :class:`LiveMics` — live mic/socket attachments, in-memory ONLY. There is
  deliberately no save/load: a process exit drops every mic, which IS the
  resume semantic. Guests re-attach on the current share URL after resume.

Stdlib only. No audio, no models, no network — the embedding pipeline
(SDF-11/12) reads and writes these shapes; this module owns durability.
"""

from __future__ import annotations

import json
import math
import os
import warnings
from pathlib import Path

VOICE_FILENAME = "voice.json"


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _clean_vector(vec) -> list[float] | None:
    """Finite-float vector, or None when the entry is not one.

    Never raises: the voice.json reader maps corrupt entries to None and
    skips them, so a hand-edited file degrades instead of tracebacks."""
    if not isinstance(vec, list) or not vec:
        return None
    clean = []
    for value in vec:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(number):
            return None
        clean.append(number)
    return clean


def _check_centroid(centroid) -> list[float]:
    if isinstance(centroid, (str, bytes)):
        raise ValueError("centroid must be a non-empty vector, not text")
    try:
        values = list(centroid)
    except TypeError:
        raise ValueError(
            f"centroid must be a non-empty vector, not {centroid!r}")
    clean = _clean_vector(values)
    if clean is None:
        raise ValueError(
            "centroid must be a non-empty vector of finite floats")
    return clean


class EnrollmentStore:
    """Durable per-board enrollment centroids."""

    def __init__(self, root: Path | str = Path("store")):
        self.root = Path(root)

    def path_for(self, board_id: str) -> Path:
        if not isinstance(board_id, str) or not board_id.strip():
            raise ValueError("board_id required")
        return self.root / board_id / VOICE_FILENAME

    def enroll(self, board_id: str, handle_id: str,
               centroid) -> dict[str, float]:
        """Bind ``handle_id`` to its calibration centroid (persisted)."""
        if not isinstance(handle_id, str) or not handle_id.strip():
            raise ValueError("handle_id required")
        stored = self.centroids(board_id)
        stored[handle_id] = _check_centroid(centroid)
        _atomic_write_json(self.path_for(board_id), {"centroids": stored})
        return {handle_id: stored[handle_id]}

    def centroid(self, board_id: str, handle_id: str) -> list[float] | None:
        return self.centroids(board_id).get(handle_id)

    def centroids(self, board_id: str) -> dict[str, list[float]]:
        path = self.path_for(board_id)
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            raw = payload.get("centroids", {})
            if not isinstance(raw, dict):
                return {}
            kept: dict[str, list[float]] = {}
            skipped = []
            for hid, vec in raw.items():
                clean = _clean_vector(vec)
                if clean is None:
                    skipped.append(str(hid))
                else:
                    kept[str(hid)] = clean
            if skipped:
                warnings.warn(
                    f"skipping non-vector centroid entries in {path}: "
                    f"{sorted(skipped)}")
            return kept
        except (ValueError, OSError):
            return {}

    def handles(self, board_id: str) -> list[str]:
        """Enrolled handle_ids, in enroll order (JSON preserves it)."""
        return list(self.centroids(board_id))


class LiveMics:
    """Ephemeral live-mic attachments. Memory only — never persisted."""

    def __init__(self) -> None:
        self._mics: dict[str, dict[str, str]] = {}

    def attach(self, board_id: str, handle_id: str, mic_id: str) -> str:
        if not isinstance(mic_id, str) or not mic_id.strip():
            raise ValueError("mic_id required")
        self._mics.setdefault(board_id, {})[handle_id] = mic_id
        return mic_id

    def active(self, board_id: str) -> dict[str, str]:
        return dict(self._mics.get(board_id, {}))

    def drop_board(self, board_id: str) -> int:
        """Drop every live mic on one board (sleep/crash resume)."""
        dropped = len(self._mics.get(board_id, {}))
        self._mics.pop(board_id, None)
        return dropped

    def drop_all(self) -> int:
        dropped = sum(len(mics) for mics in self._mics.values())
        self._mics.clear()
        return dropped


__all__ = ["VOICE_FILENAME", "EnrollmentStore", "LiveMics"]
