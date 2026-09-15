# SDF-16 — on-demand counterexample search and SEP path

Web counterexample search fires **only on a deliberate trigger**; the
Stanford Encyclopedia of Philosophy arrives **only as a labeled voice**
via link-out or a pasted excerpt. Never crawled, never fetched, never
unprompted. This package owns that boundary; `board/` and `dictionary/`
carry zero diff from SDF-3/SDF-5 ground truth, which is the proof that
the automatic path was not edited to reach it.

## Why Brave is on-demand-only (and never a chain source)

- **Manners (issue 03, amended by issue 05):** canonical definitions
  auto-populate at board creation; counterexamples and deep search are
  strictly on demand. A web engine inside the dictionary chain would fire
  on every `open_board` pull — the exact behavior the spec bans.
- **Metering:** the web API is keyed and metered. Canonical pulls happen
  implicitly (board open, cache miss); search triggers are explicit
  human acts. Mixing them turns a routine board open into a metered
  billing event.
- **Provenance hygiene:** canonicals are first-write-wins, verbatim,
  cite-backed dictionary senses. Web results are volatile, unlabeled
  page snippets. Merging them into `ChainResult.senses` would let
  `claim_canonical` serve a web hit as a canonical definition. The
  vocabulary here is deliberately disjoint (`kind="web-search"`,
  `source="brave-web"`, `canonical=False`, one-voice label) so the two
  cannot meet by shape accident.
- **Arming is explicit and structural:** the API key is a constructor
  argument only (`BraveSearchBackend(key)`); no env/config channel can
  silently arm the web path. No key → `NullSearchBackend`, and a service
  trigger without a provider refuses with `NoSearchProvider` **before
  any I/O**.

## The SEP path performs zero I/O by construction

`search/sep.py` shapes URLs and validates entries — it takes no
`transport`/`provider`/`fetch` parameter and imports no request
machinery. A participant either links out (`make_sep_link`, bare slugs
expand to `https://plato.stanford.edu/entries/<slug>/`) or pastes an
excerpt (`make_sep_paste`, stored verbatim, capped at 2000 chars, with
optional `speaker` attribution). Server-side fetching — even to
"validate" a link — would be a crawl of a philosopher source on a
semi-automatic path, which the spec forbids. Both forms are admitted as
`source="philosopher-sep"`, `canonical=False`: one voice among many,
never an anchor.

## Surface

- `errors.py` — `SearchError`, `MissingSearchKey` (construction-time),
  `NoSearchProvider` (trigger without provider), `BadSepSource` (SEP
  input shape/host/size).
- `model.py` — `WebHit`, `CounterexampleResult` (`ok | empty |
  unavailable` as data; failures never raise outward), `SepEntry`; all
  with exact `to_dict`/`from_dict` round trips.
- `backend.py` — `SearchTransport` seam (`get(url, *, headers)`),
  `HeaderUrllibTransport` (stdlib, one attempt, no retry; HTTP status is
  data, only connection failures raise), `BraveSearchBackend`
  (token in the `X-Subscription-Token` header, never the URL),
  `NullSearchBackend`, `parse_brave`, `build_default_search_backend`.
- `sep.py` — `sep_entry_url`, `sep_search_url`, `make_sep_link`,
  `make_sep_paste` (I/O-free).
- `service.py` — `search_counterexamples(x, *, provider, ...)`: the
  ONLY permitted caller of `provider.search`; plus `render_on_demand`,
  the pure fold used by `server.views.on_demand_view`.

Wiring: `BoardService(..., search_provider=None)` stores the provider
verbatim (never constructed in `server/`), and exposes
`search_counterexamples(board_id, *, triggered_by, ...)`,
`attach_sep(board_id, *, triggered_by, url=|excerpt=, speaker=,
citation=)`, `on_demand(board_id)` + `counterexamples(board_id)` alias.
Events land in the existing per-board `meta.jsonl` sidecar
(`search_recorded`, `sep_admitted`) — never the verdict journal, never
the canvas — and surface in `board_view` under the `on_demand` /
`counterexamples` section keys, structurally separate from `canonicals`.

## How the unprompted path is proven silent

`tests/test_sdf16_guards.py` runs five guards, and they must pass
as-written (failures are producer defects):

1. **Tripwire** — the full unprompted lifecycle (open, pull, claim,
   revise, allege, votes, tallies, views, sync, list) runs over a
   provider wired to a transport that raises on any call.
2. **Host allow-list** — the default canonical pull may touch only
   `en.wiktionary.org` / `api.dictionaryapi.dev` /
   `www.dictionaryapi.com`; no Brave, no `plato.stanford`.
3. **Marker scan** — `api.search.brave.com`, `search.brave`,
   `plato.stanford`, `X-Subscription-Token` appear in no `.py` under
   `board/`, `dictionary/`, `server/`.
4. **Structural I/O absence** — `sep.py` takes no transport-ish
   parameter (signature introspection) and imports no request machinery.
5. **Live gate** — the default transport under the autouse
   `no_live_network` guard raises instead of silently "succeeding".

No test touches the live network; the gate is `python3 -m pytest -q`.

## Fused-judge note (a+b+c synthesis)

Base: panel b (strictest validation — SEP host userinfo/suffix guards,
stripped URLs, non-blank X/excerpt/speaker checks, `clamp_limit` raising on
non-integers, clock-injectable `NullSearchBackend`, isolated transport
constants). Fused in from panel a: `default_query()` ownership, `!= 200`
strictness, `TypeError` on malformed JSON bodies, `self.engine` passthrough
on failures-as-data, defensive `kind`/`source_label` defaults in
`render_on_demand`, and the `triggered_by`/`requested_by` dual-kwarg alias
(stored under both keys). Compatibility shims for either panel spelling:
`ON_DEMAND_KIND`/`ON_DEMAND_LABEL` re-exported from both `search.model`
and `search.service`, `check_sep_url` public alias for `_require_sep_url`.
From panel c: the tier-table documentation discipline (unprompted paths may
read dictionary chain + journal + meta only; web fires on explicit trigger;
SEP is link-out/paste, never fetched) — but not c's divergent store/policy
surface, which would break the `search_counterexamples` / `attach_sep` /
`on_demand` contract downstream slices expect.
