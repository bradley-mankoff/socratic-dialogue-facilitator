# SDF-3 dictionary chain — fused synthesis (a+b+c)

Wiktionary-first chain with Free Dictionary API second vote over injectable
HTTP (stdlib `urllib` only). Degrades to surviving sources on 5xx /
transport failure; explicit empty state when all sources are down
(`all_sources_unavailable`) or X has no hit (`no_hit`); never merges
distinct senses; case + whitespace normalization only.

## Canonical choices (and why)

* **Core = panel a.** Pure `consensus(x, pulled_at, source_results)` with the
  §6 same-source skip + Jaccard ≥ 0.6 single-best attachment (ties → earliest),
  one vote per (source, sense), within-source exact-dedup, ranking
  `(-agreement, -stability, article order)`. The §6 bullet read literally
  ("new Sense for first gloss of a source") would strand the Free Dictionary's
  first gloss as an anchor and break the canonical AC1 example (`V` with two
  cites, order `[V, P, I, T]`); candidate-based attachment is required, and
  the same-source invariant is unchanged. Punctuation stays in tokens
  (`"law"` ≠ `"law."`); the 0.6 boundary is pinned against the fixture numbers.
* **Modularity + aliases = panel b.** `dictionary/http.py`, `dedupe.py`,
  `wiktionary.py`, `free_dict.py`, `merriam_webster.py`, `sources_util.py`
  are thin re-exports over the canonical modules, so `Transport`/`Fetch`,
  `get`/`lookup`, `reset_cache`/`clear_cache`, `build_default_chain`/
  `default_sources`, hyphen/underscore source spellings, and
  `unavailable~down` / `no_entry~no_hit` synonyms all interoperate.
  `is_empty` is a callable bool satisfying both `is_empty()` and `is_empty`.
  Wiktionary `pageid` (56878) is captured into `Cite.pageid`; the canonical
  cite URL stays the article URL (`.../wiki/justice`), with
  `wiktionary_curid_url(pageid)` available for the `?curid=` form.
* **Hardening = panel c.** Every chain return runs
  `ChainResult.check_invariant()` (ok ⇒ senses + complete cites; empty ⇒ zero
  senses + reason + `consensus is None`). `degraded`, `render()`,
  `stability_for` (3/2/1), `search()` alias, and punct-only `"!!!"` → explicit
  empty without spending the network (blank/whitespace still raises).
  Panel c's exact-text `rank_senses` is kept as a Jaccard-safe grouping helper;
  the chain ranks by agreement (the citation proxy), never by merging wording.

## Verification

```
pytest -q
grep -rnE "import (requests|httpx|aiohttp|urllib3)" dictionary/  # → no hits
```

No test touches the live network (autouse `urlopen` guard in
`tests/conftest.py`; the only socket use is the skippable 127.0.0.1 loopback
transport test).
