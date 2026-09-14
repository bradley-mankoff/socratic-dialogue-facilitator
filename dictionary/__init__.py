"""Dictionary chain (SDF-3): Wiktionary-first consensus over injectable HTTP.

Fused synthesis of three isolated implementations:

* Panel-a canonical core: pure :func:`chain.consensus` with the §6
  same-source skip + Jaccard ≥ 0.6 single-best attachment, hyphen vocab
  (``free-dictionary``), ``get`` + :func:`chain.build_default_chain`,
  revisions-wikitext parsing.
* Panel-b modularity: :mod:`dictionary.dedupe` / :mod:`dictionary.http` /
  per-adapter modules as re-export shims, ``lookup`` + ``clear_cache``,
  ``classify_status`` table, pageid cites, ``normalize_key``/``tokenize``
  aliases, callable-bool ``is_empty``.
* Panel-c hardening: :meth:`model.ChainResult.check_invariant` on every
  return, ``degraded`` / ``render`` / ``stability_for`` ranking tie-break,
  ``search`` alias, ``dict_stubs`` route-table helpers.

Import order (no cycles): model → transport → normalize → sources → chain.
"""

from dictionary.model import (
    CHAIN_STATES,
    EMPTY_REASONS,
    PRIMARY,
    SOURCES,
    SOURCE_PRIORITY,
    SOURCE_STATUSES,
    ChainResult,
    ChainState,
    Cite,
    EmptyReason,
    Sense,
    SourceMap,
    SourceName,
    SourceOutcome,
    SourceStatus,
    canonical_source,
    empty_result,
)
from dictionary.transport import (
    USER_AGENT,
    DEFAULT_TIMEOUT,
    DEFAULT_USER_AGENT,
    BadSourceResponse,
    DictionarySourceError,
    Fetch,
    HttpResponse,
    SourceUnavailable,
    Transport,
    TransportError,
    UrlLibFetch,
    UrllibTransport,
)
from dictionary.normalize import (
    JACCARD_THRESHOLD,
    gloss_tokens,
    jaccard,
    normalize_gloss,
    normalize_key,
    normalize_sense_text,
    normalize_term,
    normalize_text,
    normalize_x,
    tokenize,
)
from dictionary.sources import (
    FREE_DICT_PREFIX,
    FREE_DICTIONARY_API,
    FREE_DICTIONARY_LICENSE,
    MERRIAM_WEBSTER_API,
    MERRIAM_WEBSTER_ARTICLE,
    MERRIAM_WEBSTER_LICENSE,
    MERRIAM_WEBSTER_PREFIX,
    STABILITY,
    WIKTIONARY_API,
    WIKTIONARY_API_PREFIX,
    WIKTIONARY_ARTICLE,
    WIKTIONARY_LICENSE,
    DictionarySource,
    FreeDictionarySource,
    MerriamWebsterSource,
    RawSense,
    WiktionarySource,
    classify_status,
    free_dictionary_url,
    merriam_webster_cite_url,
    merriam_webster_url,
    parse_wikitext_senses,
    source_cite,
    stability_for,
    wiktionary_cite_url,
    wiktionary_curid_url,
    wiktionary_url,
)
from dictionary.chain import (
    DictionaryChain,
    SourceResult,
    build_default_chain,
    cluster,
    consensus,
    default_sources,
    distinct_sources,
    rank_senses,
)
from dictionary.dedupe import JACCARD_THRESHOLD as DEDUPE_THRESHOLD

__all__ = [
    "DictionaryChain",
    "SourceResult",
    "build_default_chain",
    "default_sources",
    "consensus",
    "cluster",
    "rank_senses",
    "distinct_sources",
]
