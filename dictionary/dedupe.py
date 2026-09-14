"""Panel-b import alias: consensus clustering lives in :mod:`dictionary.chain`.

``JACCARD_THRESHOLD`` is the single shared constant (research ticket 05);
:func:`cluster` is the cross-source-only attach rule (same-source never
merges, one vote per source per sense).
"""

from dictionary.chain import cluster, rank_senses
from dictionary.normalize import JACCARD_THRESHOLD

__all__ = ["JACCARD_THRESHOLD", "cluster", "rank_senses"]
