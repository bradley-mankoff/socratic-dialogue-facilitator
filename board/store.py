"""JsonlStore — append-only JSONL event journal with per-append durability.

One line per event, ``flush() + os.fsync()`` per append. A torn final line
(crash mid-write) is detected on read, truncated with a warning, and the
journal stays usable. ``load_state`` folds the journal through the same
reducer the live machine uses, so reload reconstructs identical state (AC4).

The on-disk data home is ``store/`` at repo root (gitignored) — data
directory, not a Python package. Tests use ``home=tmp_path``.
"""

from __future__ import annotations

import json
import os
import warnings
from pathlib import Path


class JsonlStore:
    """Durable per-mutation event store for one or many boards."""

    # Fused from panel c: single filename constant + board_dir helper so
    # callers need not hard-code the journal layout.
    FILENAME = "journal.jsonl"

    def __init__(self, home: Path | str = Path("store")):
        self.home = Path(home)

    def board_dir(self, board_id: str) -> Path:
        """Directory holding one board's journal (fused from c)."""
        return self.home / board_id

    def path_for(self, board_id: str) -> Path:
        return self.board_dir(board_id) / self.FILENAME

    def append(self, board_id: str, event: dict) -> int:
        """Append one event line, flush + fsync; returns its seq."""
        path = self.path_for(board_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._repair_tail(path)
        line = json.dumps(event, separators=(",", ":")) + "\n"
        with open(path, "a") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())
        return event["seq"]

    def read_all(self, board_id: str) -> list[dict]:
        """All events in file order. A torn final line is truncated (with a
        warning); corrupt non-final lines are skipped with a warning."""
        path = self.path_for(board_id)
        if not path.exists():
            return []
        raw = path.read_bytes()
        events: list[dict] = []
        good_end = 0
        for line in raw.splitlines(keepends=True):
            try:
                events.append(json.loads(line))
                good_end += len(line)
            except json.JSONDecodeError as exc:
                if good_end + len(line) >= len(raw):
                    warnings.warn(
                        f"torn journal tail in {path}, truncating: {exc}")
                    self._truncate(path, good_end)
                else:
                    warnings.warn(
                        f"corrupt journal line in {path}, skipping: {exc}")
                    good_end += len(line)
        return events

    def load_state(self, board_id: str):
        """Replay the journal into a BoardState (None when empty). Uses the
        machine's reducer, so reload identity is structural."""
        from board.machine import fold_events
        events = self.read_all(board_id)
        if not events:
            return None
        return fold_events(events)

    def journal_lines(self, board_id: str) -> int:
        """Count of durable mutation records (complete lines; fused from c)."""
        return len(self.read_all(board_id))

    # -- internals ----------------------------------------------------------

    @staticmethod
    def _truncate(path: Path, good_end: int) -> None:
        try:
            with open(path, "r+b") as fh:
                fh.truncate(good_end)
        except OSError:      # read-only media: keep the tail, skip on read
            pass

    @classmethod
    def _repair_tail(cls, path: Path) -> None:
        """Before appending, drop a torn final line so the journal stays
        clean (the last event is lost at most)."""
        try:
            size = path.stat().st_size
            if size == 0:
                return
            with open(path, "rb") as fh:
                fh.seek(size - 1)
                if fh.read(1) == b"\n":
                    return
            raw = path.read_bytes()
            last_nl = raw.rfind(b"\n")
            if last_nl < 0:
                cls._truncate(path, 0)
            else:
                cls._truncate(path, last_nl + 1)
        except OSError:
            pass