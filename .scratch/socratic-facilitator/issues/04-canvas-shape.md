# 04 — Canvas shape without inventing pan/zoom

Type: research
Status: resolved
Blocked by: 02

## Question

Survey open-source interactive pan/zoom 2-D canvas options adoptable by a tiny self-hosted app (no invented renderer): nodes = every attempted definition of X, edges = refuted-by labeled 3a/3b, active path highlighted, interactive pan/zoom + static image export (PNG/SVG). Compare 2–3 libs on license, bundle weight, touch support, export fidelity, persistence format. Recommend one for the Justice fixture summary. Blocked by 02 for node/edge semantics.

## Answer

Recommend **Cytoscape.js** (MIT, zero-dep, ~112 KB gzip): only surveyed lib with first-party static export (`cy.png()`/`cy.jpg()`) + JSON round-trip (`cy.json()`), built-in touch gestures and pan/zoom, framework-agnostic. vis-network (dual Apache-2.0/MIT, ~606 KB standalone) has no export API; React Flow (`@xyflow/react`, MIT) is React-only with no built-in export (official recipe pins third-party `html-to-image@1.11.11` due to upstream breakage). SVG caveat: only via GPL-3.0 third-party `cytoscape-svg` — flag before any distribution; PNG satisfies the requirement.
Findings: `.scratch/socratic-facilitator/research/canvas-shape.md` on branch `research/canvas-shape` (3-lib cited comparison + Justice fixture sketch).
