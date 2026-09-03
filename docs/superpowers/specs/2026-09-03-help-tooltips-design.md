# Section Help Tooltips — Design

2026-09-03. Approved via brainstorming (style question: ⓘ hover tooltips).

- `app/src/helpText.ts` — all wording, keyed by section id. Plain-language
  condensations of the scoring math: weights (normalized, only ratios
  matter, weighted sum), constraints (multiply by 0; non-negotiable vs
  weights), shortlist, scoring (compensatory weighted sum vs
  non-compensatory geometric; geometric-as-audit-lens advice), display,
  normalization (curves vs classes), presets.
- `app/src/components/Help.tsx` — `<Help id="scoring"/>`: a ⓘ button
  (keyboard-focusable) with a CSS tooltip on hover/focus, dark card,
  ~280 px max width. Unknown id throws at render (loud, not blank).
- Placements: WeightPanel group headers (shared weights text), Constraints,
  Shortlist, Scoring, Display; SettingsDrawer criterion mode rows
  (normalization) and Presets.
- No behavior changes; verified by tsc/build + live Chrome. Out of scope:
  per-criterion data tooltips, docs pages.
