"""Board operations home (SDF-5): open boards, claim, revise, view.

Public surface downstream builds on:

* :class:`BoardService` — the API (``open_board``, ``claim_canonical``,
  ``claim_original``, ``revise``, ``view``, ``machine`` escape hatch).
* :class:`BoardRecord` / :class:`ClaimResult` / :class:`OpenResult` /
  :class:`ClaimProvenance` — data shapes (all JSON round-trip exact).
* :class:`BoardRegistry` / :class:`CanonicalStore` / :class:`MetaLog` — the
  three durable homes under one data root (``store/``).
* :mod:`server.views` — pure board projections for the SDF-10 UI.
* :mod:`server.errors` — this slice's errors plus the re-exported SDF-2
  machine errors.

``board/`` and ``dictionary/`` are used unchanged: the verdict machine is the
only mutator of verdict state, and the dictionary chain owns canonical
retrieval and its per-X cache.
"""

from board.machine import (  # noqa: F401  (re-exported for callers)
    BoardClosed,
    NoBoard,
    NodeFrozen,
    UnknownHandle,
    UnknownNode,
    UnknownQuestion,
    VerdictError,
)
from server.errors import (
    BlankClaim,
    BoardOpError,
    ClaimAlreadyActive,
    DuplicateLabel,
    EmptyCanonicals,
    NoActiveClaim,
    NoCanonicals,
    UnknownBoard,
    UnknownSense,
)
from server.model import (
    CLAIM_RECORDED,
    CLAIM_REVISED,
    OPS_EVENT_TYPES,
    SOURCE_TAG,
    TRAY_NAME,
    BoardRecord,
    ClaimProvenance,
    ClaimResult,
    OpenResult,
    make_board_id,
    next_label,
    now_iso,
    slug,
)
from server.service import BoardService
from server.store import (
    DEFAULT_ROOT,
    REGISTRY_FILENAME,
    BoardRegistry,
    CanonicalStore,
    MetaLog,
    canonicals_dir,
    registry_path,
)
from server.views import (
    board_view,
    boards_view,
    canonicals_view,
    node_view,
    question_view,
)

__all__ = [
    # service
    "BoardService",
    # data shapes
    "BoardRecord", "ClaimProvenance", "ClaimResult", "OpenResult",
    # durable homes
    "BoardRegistry", "CanonicalStore", "MetaLog", "DEFAULT_ROOT",
    "REGISTRY_FILENAME", "registry_path", "canonicals_dir",
    # constants + helpers
    "CLAIM_RECORDED", "CLAIM_REVISED", "OPS_EVENT_TYPES", "TRAY_NAME",
    "SOURCE_TAG", "slug", "make_board_id", "next_label", "now_iso",
    # views
    "board_view", "boards_view", "canonicals_view", "node_view",
    "question_view",
    # errors (slice + re-exported machine errors)
    "BoardOpError", "UnknownBoard", "NoCanonicals", "EmptyCanonicals",
    "UnknownSense", "NoActiveClaim", "ClaimAlreadyActive", "BlankClaim",
    "DuplicateLabel", "BoardClosed", "NoBoard", "NodeFrozen", "VerdictError",
    "UnknownHandle", "UnknownNode", "UnknownQuestion",
]
