"""SDF-5 durable homes: board registry, per-X canonical cache, meta log.

Layout under one data root (default ``store/``, gitignored — the home
``board.store.JsonlStore`` already documents):

````
store/registry.json                    boards + counter (small, atomic rewrite)
store/canonicals/<slug(x_norm)>.json   one ChainResult.to_dict() per X
store/<board_id>/journal.jsonl         SDF-2 verdict journal (machine-owned)
store/<board_id>/meta.jsonl            SDF-5 sidecar (server-owned)
````

Journals and sidecars share a board directory but never a file. That
separation is load-bearing: ``board.machine._apply`` raises on unknown event
types, so a single foreign line in ``journal.jsonl`` would permanently break
replay and SDF-18 resume. ``MetaLog`` therefore subclasses :class:`JsonlStore`
(identical fsync-per-append durability and torn-tail repair) with a different
filename rather than writing into the journal.
"""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
from typing import Callable

from board.store import JsonlStore
from dictionary.chain import DictionaryChain
from dictionary.normalize import normalize_x
from server.errors import DuplicateLabel, UnknownBoard
from server.model import (
    OPS_EVENT_TYPES,
    BoardRecord,
    make_board_id,
    next_label,
    now_iso,
    slug,
)

REGISTRY_FILENAME = "registry.json"
REGISTRY_VERSION = 1
DEFAULT_ROOT = Path("store")
CANONICALS_DIRNAME = "canonicals"
ALLOWED_MIRROR_FIELDS = ("mode", "medium", "status")


def registry_path(root: Path | str = DEFAULT_ROOT) -> Path:
    return Path(root) / REGISTRY_FILENAME


def canonicals_dir(root: Path | str = DEFAULT_ROOT) -> Path:
    return Path(root) / CANONICALS_DIRNAME


def canonical_path(x_norm: str, root: Path | str = DEFAULT_ROOT) -> Path:
    """Disk home for one X's snapshot (path-safe by construction).

    ``slug`` is lossy, so two different X's can want the same readable name
    (``"a b"`` and ``"a-b"`` both slug to ``a-b``). Callers must go through
    :meth:`CanonicalStore._path_for`, which detects a foreign owner and
    disambiguates rather than clobbering.
    """
    return canonicals_dir(root) / f"{slug(x_norm)}.json"


def creation_key(record: BoardRecord) -> tuple:
    """Stable "created order" sort key.

    ``created_at`` alone ties for boards minted inside one clock tick, and
    plain ``board_id`` order is alphabetic over the slug parts — so the
    zero-padded counter suffix is the authoritative tiebreaker.
    """
    serial = str(record.board_id).rpartition("--")[2]
    return (record.created_at, int(serial) if serial.isdigit() else 0,
            record.board_id)


class BoardRegistry:
    """``(X, label) -> board`` map with an atomic single-file rewrite.

    The on-disk shape is exactly ``{"version","counter","boards"}``; the
    ``(x_norm, label)`` index is rebuilt in memory on load (no derived index
    on disk to drift).
    """

    def __init__(self, path: Path | str = registry_path(DEFAULT_ROOT)):
        self.path = Path(path)
        self.root = self.path.parent
        self.boards: dict[str, BoardRecord] = {}
        self.counter: int = 0
        self.load()

    # -- reads ---------------------------------------------------------------

    def get(self, x: str, label: str) -> BoardRecord | None:
        """Exact get by normalized ``(X, label)``."""
        xn, lab = normalize_x(x), normalize_x(label)
        for record in self.boards.values():
            if record.x_norm == xn and normalize_x(record.label) == lab:
                return record
        return None

    def by_id(self, board_id: str) -> BoardRecord | None:
        return self.boards.get(board_id)

    def boards_for(self, x: str) -> list[BoardRecord]:
        """Every board on this X, in creation order."""
        xn = normalize_x(x)
        rows = [r for r in self.boards.values() if r.x_norm == xn]
        return sorted(rows, key=creation_key)

    def labels_for(self, x: str) -> set[str]:
        return {r.label for r in self.boards_for(x)}

    def next_label(self, x: str, base: str | None = None) -> str:
        """Free label for ``x``; ``base`` defaults to the normalized X.

        Occupancy is judged on the normalized label because that is what
        :meth:`get` keys on — ``Justice`` and ``justice`` are one board.
        """
        taken = {normalize_x(lab) for lab in self.labels_for(x)}
        return next_label(taken,
                          base if base is not None else normalize_x(x))

    # -- writes --------------------------------------------------------------

    def reserve(self, *, x: str, x_title: str | None = None, label: str,
                mode: str = "participates",
                medium: str = "async") -> BoardRecord:
        """Mint and durably register a new board. Raises ``DuplicateLabel``
        when the ``(X, label)`` key is already taken."""
        if self.get(x, label) is not None:
            raise DuplicateLabel(f"board already open: {x!r} / {label!r}")
        self.counter += 1
        xn = normalize_x(x)
        record = BoardRecord(
            board_id=make_board_id(xn, label, self.counter),
            x=x,
            x_norm=xn,
            x_title=(x_title if x_title is not None else str(x).strip()),
            label=label,
            mode=mode,
            medium=medium,
            status="open",
            created_at=now_iso(),
        )
        self.boards[record.board_id] = record
        self.save()
        return record

    def mark(self, board_id: str, **fields) -> BoardRecord:
        """Mirror machine state onto the row. Only mode/medium/status."""
        record = self.boards.get(board_id)
        if record is None:
            raise UnknownBoard(f"unknown board: {board_id}")
        bad = sorted(set(fields) - set(ALLOWED_MIRROR_FIELDS))
        if bad:
            raise ValueError(f"registry mirrors only {ALLOWED_MIRROR_FIELDS}, "
                             f"not {bad}")
        for name, value in fields.items():
            setattr(record, name, value)
        self.save()
        return record

    def save(self) -> None:
        """Atomic rewrite: tmp file in the same dir + ``os.replace``."""
        payload = {
            "version": REGISTRY_VERSION,
            "counter": self.counter,
            "boards": {bid: r.to_dict() for bid, r in self.boards.items()},
        }
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        with open(tmp, "w") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)

    def load(self) -> None:
        """Read the registry; a missing or corrupt file means an empty map
        (the next ``save`` rewrites it cleanly rather than crashing)."""
        self.boards = {}
        self.counter = 0
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            boards = payload["boards"]
            if not isinstance(boards, dict):
                raise TypeError("registry boards must be a mapping")
            self.counter = int(payload.get("counter", 0))
            for bid, row in boards.items():
                record = BoardRecord.from_dict({**row, "board_id": bid})
                self.boards[record.board_id] = record
        except (ValueError, TypeError, KeyError, OSError):
            self.boards = {}
            self.counter = 0
        self.counter = max(self.counter, len(self.boards))


class CanonicalStore:
    """Per-X canonical snapshots shared across every board on that X.

    Memory map first, disk second, chain third — so a fresh service over the
    same root renders an existing board with **zero** transport calls, and
    within one process the chain is asked at most once per X (its own
    in-memory cache is the backstop). First write wins: snapshots are
    immutable mid-dialogue (issue 02).
    """

    def __init__(self, home: Path | str = DEFAULT_ROOT,
                 chain: DictionaryChain | Callable[[], DictionaryChain] | None = None):
        self.home = Path(home)
        self._chain_arg = chain
        self._mem: dict[str, dict] = {}

    def _resolve_chain(self) -> DictionaryChain | None:
        """Chain object, or built on demand from a zero-arg factory.

        A service passes a bound method so the default (live-network) chain is
        constructed on the first real pull, never at import or construction.
        """
        chain = self._chain_arg
        if chain is None:
            return None
        if callable(chain):
            chain = chain()
            self._chain_arg = chain
        return chain

    def get(self, x: str) -> dict:
        """Snapshot dict for ``x`` (``ChainResult.to_dict()`` shape)."""
        xn = normalize_x(x)
        cached = self.cached(xn)
        if cached is not None:
            return cached
        chain = self._resolve_chain()
        if chain is None:
            from server.errors import NoCanonicals
            raise NoCanonicals(
                f"no cached canonicals for {x!r} and no dictionary chain")
        snapshot = chain.get(xn).to_dict()
        self._persist(xn, snapshot)
        return snapshot

    def _read(self, path: Path, x_norm: str) -> dict | None:
        """Load a snapshot file, refusing one that belongs to a different X."""
        if not path.exists():
            return None
        try:
            snapshot = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return None
        if not isinstance(snapshot, dict) or snapshot.get("x") != x_norm:
            # slug collision or a hand-edited file: never serve wrong data
            return None
        return snapshot

    def _path_for(self, x_norm: str) -> Path:
        """Readable path for this X, disambiguated on a slug collision.

        The readable name wins whenever it is free or already ours; a foreign
        owner pushes this X to a sibling carrying a digest of its real key,
        so no X can ever overwrite another X's first-write-wins snapshot.
        """
        primary = canonical_path(x_norm, self.home)
        if primary.exists() and self._read(primary, x_norm) is None:
            digest = hashlib.sha1(x_norm.encode("utf-8")).hexdigest()[:8]
            return primary.with_name(f"{primary.stem}-{digest}.json")
        return primary

    def cached(self, x: str) -> dict | None:
        """Memory then disk; never touches the chain or network."""
        xn = normalize_x(x)
        hit = self._mem.get(xn)
        if hit is not None:
            return hit
        snapshot = self._read(self._path_for(xn), xn)
        if snapshot is None:
            return None
        self._mem[xn] = snapshot
        return snapshot

    def _persist(self, x_norm: str, snapshot: dict) -> None:
        self._mem[x_norm] = snapshot
        path = self._path_for(x_norm)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w") as fh:
            json.dump(snapshot, fh, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)


class MetaLog(JsonlStore):
    """Append-only sidecar log of board *operations* (provenance + tray).

    Same durability as the verdict journal (fsync per append, torn-tail
    repair, ``read_all``) under a different filename, and its own per-board
    ``seq``. The machine never reads it; it never writes ``journal.jsonl``.
    """

    FILENAME = "meta.jsonl"

    def append_event(self, board_id: str, etype: str, payload: dict, *,
                     ts: str | None = None) -> dict:
        """Append one slice event; returns the stored envelope."""
        if etype not in OPS_EVENT_TYPES:
            raise ValueError(
                f"meta log holds only {OPS_EVENT_TYPES}, not {etype!r}")
        events = self.read_all(board_id)
        event = {
            "seq": len(events) + 1,
            "type": etype,
            "board_id": board_id,
            "ts": ts or now_iso(),
            "payload": dict(payload),
        }
        self.append(board_id, event)
        return event

    def read_events(self, board_id: str,
                    etype: str | None = None) -> list[dict]:
        """All sidecar events for a board, optionally filtered by type."""
        if etype is not None and etype not in OPS_EVENT_TYPES:
            raise ValueError(
                f"meta log holds only {OPS_EVENT_TYPES}, not {etype!r}")
        events = self.read_all(board_id)
        if etype is None:
            return events
        return [e for e in events if e.get("type") == etype]


__all__ = [
    "REGISTRY_FILENAME", "REGISTRY_VERSION", "DEFAULT_ROOT",
    "CANONICALS_DIRNAME", "ALLOWED_MIRROR_FIELDS",
    "registry_path", "canonicals_dir", "canonical_path", "creation_key",
    "BoardRegistry", "CanonicalStore", "MetaLog",
]
