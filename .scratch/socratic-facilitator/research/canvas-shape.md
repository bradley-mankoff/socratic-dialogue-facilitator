# 04 — Canvas shape: pan/zoom 2-D canvas lib survey

Ticket: `.scratch/socratic-facilitator/issues/04-canvas-shape.md` · Branch: `research/canvas-shape`
Fixture X for all examples: **Justice (Republic Book I)**.
Given (not re-decided here): nodes = attempted definitions, edges = `refuted-by` labeled `3a`/`3b`
(edge-label semantics owned by ticket 02), active path highlighted.

## Recommendation

**Adopt Cytoscape.js for the Justice fixture summary canvas.**

It is the only surveyed lib with **first-party** static raster export (`cy.png()` /
`cy.jpg()`) plus JSON round-trip persistence (`cy.json()`), it is framework-agnostic
with zero dependencies and the smallest honest single-file weight (~112 KB gzip per its
own size snapshot), and it has built-in touch gestures and pan/zoom — so no renderer
is invented and no third-party export shim is required. PNG satisfies the ticket's
"static image export (PNG/SVG)" requirement. SVG export exists only via a GPL-3.0
third-party extension (see caveat below); do not promise vector export unless the
GPL flag is cleared.

## Comparison (2–3 libs, primary sources)

| Criterion | Cytoscape.js | vis-network | React Flow (`@xyflow/react` v12) |
|---|---|---|---|
| License | MIT (core + all first-party extensions) — [repo](https://github.com/cytoscape/cytoscape.js), [factsheet](https://js.cytoscape.org/#introduction/factsheet) | Dual Apache-2.0 **and** MIT (either) — [README license section](https://github.com/visjs/vis-network) | MIT — [repo](https://github.com/xyflow/xyflow) |
| Bundle weight (measured 2026-09-11) | Repo snapshot: UMD minified 365,007 B, gzipped 112,477 B — [`.size-snapshot.json`](https://github.com/cytoscape/cytoscape.js/blob/master/.size-snapshot.json). Spot-check `cytoscape@3.33.1/dist/cytoscape.min.js` via unpkg: 434,037 B raw / 136,283 B gzip | Standalone UMD min `vis-network@9.1.12`: 620,622 B raw / 148,826 B gzip (bundles deps, CSS auto-injected; peer/ESM builds smaller) — [docs on builds](https://visjs.github.io/vis-network/docs/network/), [unpkg file](https://unpkg.com/vis-network/standalone/) | `dist/esm/index.js` 233,341 B (gzip 52,449 B) + `style.css` 18,596 B, **excluding** peer deps `react>=17`, `react-dom>=17`, `zustand`, `@xyflow/system` — measured from [npm tarball](https://registry.npmjs.org/@xyflow/react/-/react-12.11.6.tgz). Dominant cost is the React prerequisite if the app isn't React-based |
| Framework fit for a tiny self-hosted app | Framework-agnostic, **zero external dependencies** — [factsheet](https://js.cytoscape.org/#introduction/factsheet) | Framework-agnostic (UMD script tag or ESM) — [docs](https://visjs.github.io/vis-network/docs/network/) | **React only** (plus Svelte sibling `@xyflow/svelte`) — [repo](https://github.com/xyflow/xyflow) |
| Touch support | "Abstracted and unified touch events" + "builtin support for standard gestures on both desktop and touch" — [factsheet](https://js.cytoscape.org/#introduction/factsheet) | Interaction module "handles mouse and touch events"; `dragView`/`zoomView`/`dragNodes`/`navigationButtons`/`clickToUse` — [interaction docs](https://visjs.github.io/vis-network/docs/network/interaction.html) | `panOnDrag` (incl. touch panning), `zoomOnPinch` default `true`, tap-to-connect via `connectOnClick`, dedicated touch example — [`<ReactFlow/>` API](https://reactflow.dev/api-reference/react-flow), [touch-device example](https://reactflow.dev/examples/interaction/touch-device) |
| PNG export fidelity | **First-party** `cy.png()` ("export the current graph view as a PNG image", base64 data URI droppable into `<img>`/download) + lossy `cy.jpg()`/`cy.jpeg()` (docs warn JPEG blurs edge lines) — [core/export docs](https://js.cytoscape.org/#core/export) | **No first-party export API** in the documented method reference (canvas methods are only `canvasToDOM`/`DOMtoCanvas`/`redraw`/`setSize`) — [method reference](https://visjs.github.io/vis-network/docs/network/). PNG only via manual `canvas.toDataURL()` on the underlying `<canvas>` (it "[uses] HTML canvas for rendering" — [docs](https://visjs.github.io/vis-network/docs/network/)); **no vector path** | **No built-in export.** Official recipe shells out to third-party `html-to-image`, pinned to `1.11.11` because later versions broke export ([open upstream issue](https://github.com/bubkoo/html-to-image/issues/516)) — [download-image example](https://reactflow.dev/examples/misc/download-image). DOM-serialization captures custom-node styling well but adds a fragile extra dependency |
| SVG export fidelity | Only via third-party `cytoscape-svg` (`cy.svg({full, scale, bg})`, canvas2svg replay; ~42 stars; known shape/style fidelity gaps) — [extension repo](https://github.com/kinimesi/cytoscape-svg). **License flag: GPL-3.0** — same page. Self-hosted use without distribution sidesteps GPL distribution obligations, but clear before any distribution | None (see above) | None first-party (see above) |
| Persistence format | `cy.json()` round-trips the init-format JSON (`elements` + `style` + positions); `ele.json()` per element; "fully serialisable and deserialisable via JSON" — [core/export docs](https://js.cytoscape.org/#core/export), [factsheet](https://js.cytoscape.org/#introduction/factsheet) | `vis.DataSet` dynamic binding + `getPositions()`/`storePositions()` write layout back into the dataset; `DataSet.get()` is plain JSON for DB/file; Gephi-JSON/DOT import — [method reference](https://visjs.github.io/vis-network/docs/network/) | `rfInstance.toObject()` → `{nodes, edges, viewport}` → `JSON.stringify` → localStorage/file; restore via `setNodes`/`setEdges`/`setViewport` — [save-and-restore example](https://reactflow.dev/examples/interaction/save-and-restore) |
| Adoption signal (stars at survey time) | ~11.2k — [repo](https://github.com/cytoscape/cytoscape.js) | ~3.6k — [repo](https://github.com/visjs/vis-network) | ~38.3k (monorepo incl. Svelte Flow) — [repo](https://github.com/xyflow/xyflow) |

## Why Cytoscape.js wins for this map

1. **Export is the deciding requirement.** The canvas must produce a static summary
   image. Cytoscape is the only candidate with a first-party, dependency-free answer
   (`cy.png()`); the other two require a canvas hack (vis-network) or a pinned,
   known-broken third-party lib (React Flow + `html-to-image@1.11.11`).
2. **Smallest honest weight for a tiny app** (~112 KB gzip, zero deps) vs ~145 KB gzip
   standalone for vis-network vs React Flow's React+ReactDOM+zustand prerequisite.
3. **No framework lock-in.** The facilitator's stack is undecided; Cytoscape works from
   a script tag or any bundler, and server-side PNG via Cytosnap remains an option later.
4. **Graph-native API matches the semantics**: selectors + stylesheets give the active
   path and `3a`/`3b` edge labels declaratively; `breadthfirst` layout fits an
   elenchus chain with zero custom layout code.
5. **License is clean** (MIT incl. first-party extensions). The one flag — GPL-3.0 on
   the optional SVG extension — only matters if vector export is later required *and*
   the app is distributed.

## Why not the others

- **vis-network**: fine renderer, pleasant API, liberal dual license — but no export
  API and the heaviest single file. It becomes the pick only if its physics-based
  auto-layout or edit-mode GUI outweighs the export need. They don't here.
- **React Flow**: best custom-node UX and viewport API — but React-only, no built-in
  export, and its official export recipe depends on a pinned workaround version with
  an open breakage issue. Revisit only if the app is already React-based *and*
  someone accepts the `html-to-image` risk.

## Justice fixture sketch (Cytoscape.js, no invented renderer)

```js
const cy = cytoscape({
  container: document.getElementById('cy'),
  elements: [
    { data: { id: 'ce-phalus', label: 'Justice = truth-telling + repaying debts (Cephalus)' } },
    { data: { id: 'polemarchus', label: 'Justice = benefit friends, harm enemies (Polemarchus)' } },
    { data: { id: 'thrasymachus', label: 'Justice = advantage of the stronger (Thrasymachus)' } },
    { data: { id: 'e1', source: 'ce-phalus', target: 'polemarchus', kind: '3a' } }, // label per 02
    { data: { id: 'e2', source: 'polemarchus', target: 'thrasymachus', kind: '3b' } },
  ],
  style: [
    { selector: 'node', style: { label: 'data(label)', 'text-wrap': 'wrap', 'text-max-width': 180 } },
    { selector: 'edge', style: { label: 'data(kind)', 'curve-style': 'bezier', 'target-arrow-shape': 'triangle' } },
    { selector: '.active-path', style: { 'line-color': '#c00', 'target-arrow-color': '#c00', 'border-width': 2 } },
  ],
  layout: { name: 'breadthfirst', directed: true, padding: 30 },
});
cy.$('#polemarchus, #e2').addClass('active-path'); // live definitional thread
const png64 = cy.png();                             // summary image, first-party
const persisted = JSON.stringify(cy.json());        // DB/file round-trip
```

## Sources (primary)

- Cytoscape.js repo (license/stars): <https://github.com/cytoscape/cytoscape.js>
- Cytoscape.js docs — factsheet (MIT, zero deps, touch gestures, JSON serialisation): <https://js.cytoscape.org/#introduction/factsheet>
- Cytoscape.js docs — `cy.png()` / `cy.jpg()` / `cy.json()`: <https://js.cytoscape.org/#core/export>
- Cytoscape.js size snapshot (bundle/gzip bytes): <https://github.com/cytoscape/cytoscape.js/blob/master/.size-snapshot.json>
- `cytoscape-svg` extension repo (API, GPL-3.0): <https://github.com/kinimesi/cytoscape-svg>
- vis-network repo (dual license, canvas rendering): <https://github.com/visjs/vis-network>
- vis-network network docs (builds, canvas rendering, method reference incl. `getPositions`/`storePositions`): <https://visjs.github.io/vis-network/docs/network/>
- vis-network interaction docs (touch, drag/zoom options): <https://visjs.github.io/vis-network/docs/network/interaction.html>
- xyflow repo (MIT, React/Svelte libs): <https://github.com/xyflow/xyflow>
- `<ReactFlow/>` API (`panOnDrag`, `zoomOnPinch`, viewport props): <https://reactflow.dev/api-reference/react-flow>
- React Flow download-image example (`html-to-image@1.11.11` pin): <https://reactflow.dev/examples/misc/download-image>
- React Flow save-and-restore example (`toObject()` persistence): <https://reactflow.dev/examples/interaction/save-and-restore>
- React Flow touch-device example: <https://reactflow.dev/examples/interaction/touch-device>
- `html-to-image` export breakage issue: <https://github.com/bubkoo/html-to-image/issues/516>
- Weighed artifacts 2026-09-11: `cytoscape@3.33.1/dist/cytoscape.min.js` (434,037 B / 136,283 B gzip),
  `vis-network@9.1.12/standalone/umd/vis-network.min.js` (620,622 B / 148,826 B gzip),
  `@xyflow/react@12.11.6` tarball `dist/esm/index.js` (233,341 B / 52,449 B gzip) + `style.css` (18,596 B)
