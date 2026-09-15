"""SDF-16 — on-demand counterexample search and SEP path.

Everything in this package is *explicit-trigger only*: no automatic path
(``open_board`` pull, canonical claims, votes, tallies, views) may reach
any callable here. The vocabulary is deliberately disjoint from the
dictionary chain — ``kind="web-search"`` / ``kind="sep"``, ``canonical
False``, one-voice labels — so a web hit or SEP voice can never be
mistaken for a canonical definition.

Import order: ``errors`` → ``model`` → ``backend`` → ``sep`` →
``service``. ``search`` never imports ``server`` or ``board``.
"""

from search.errors import (
    BadSepSource,
    MissingSearchKey,
    NoSearchProvider,
    SearchError,
)
from search.model import (
    COUNTEREXAMPLES_SECTION_KIND,
    EXCERPT_MAX_CHARS,
    ON_DEMAND_KIND,
    ON_DEMAND_LABEL,
    ON_DEMAND_SECTION_LABEL,
    SEP_KIND,
    SEP_ORIGIN_LINK,
    SEP_ORIGIN_PASTE,
    SEP_SITE,
    SEP_SOURCE,
    SEP_SOURCE_LABEL,
    WEB_RESULT_LABEL,
    WEB_SEARCH_KIND,
    WEB_SOURCE,
    CounterexampleResult,
    SepEntry,
    WebHit,
    default_query,
)
from search.backend import (
    BRAVE_SEARCH_API,
    BRAVE_ENGINE,
    BraveSearchBackend,
    NullSearchBackend,
    SearchBackend,
    SearchTransport,
    HeaderUrllibTransport,
    brave_headers,
    brave_search_url,
    build_default_search_backend,
    clamp_limit,
    parse_brave,
)
from search.sep import (
    SEP_HOST,
    check_sep_url,
    make_sep_link,
    make_sep_paste,
    sep_entry_url,
    sep_search_url,
)
from search.service import (
    ON_DEMAND_KIND as SERVICE_ON_DEMAND_KIND,
    ON_DEMAND_LABEL as SERVICE_ON_DEMAND_LABEL,
    hit_view,
    render_on_demand,
    search_counterexamples,
)

__all__ = [
    # errors
    "SearchError", "MissingSearchKey", "NoSearchProvider", "BadSepSource",
    # model
    "WEB_SEARCH_KIND", "SEP_KIND", "WEB_SOURCE", "SEP_SOURCE",
    "SEP_SOURCE_LABEL", "SEP_ORIGIN_LINK", "SEP_ORIGIN_PASTE", "SEP_SITE",
    "EXCERPT_MAX_CHARS", "WEB_RESULT_LABEL",
    "WebHit", "CounterexampleResult", "SepEntry",
    "COUNTEREXAMPLES_SECTION_KIND", "ON_DEMAND_SECTION_LABEL",
    "ON_DEMAND_KIND", "ON_DEMAND_LABEL", "default_query",
    "SERVICE_ON_DEMAND_KIND", "SERVICE_ON_DEMAND_LABEL",
    # backend
    "BRAVE_SEARCH_API", "BRAVE_ENGINE",
    "SearchTransport", "HeaderUrllibTransport",
    "SearchBackend", "NullSearchBackend", "BraveSearchBackend",
    "build_default_search_backend", "brave_search_url", "brave_headers",
    "parse_brave", "clamp_limit",
    # sep
    "SEP_HOST", "sep_entry_url", "sep_search_url", "check_sep_url",
    "make_sep_link", "make_sep_paste",
    # service
    "render_on_demand", "hit_view",
    "search_counterexamples",
]
