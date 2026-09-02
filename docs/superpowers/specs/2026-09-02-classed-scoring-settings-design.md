# Classed Scoring + Settings Panel (Phase A) — Design

2026-09-02. Approved via brainstorming. Phase A of two: this is app-only
and works against existing measurements. Phase B (network drive time to
highway access points → `hwy_drive_min` column) is a separate spec; its
column will be consumed by this feature's binning like any other.

## Decisions

| Question | Decision |
|---|---|
| Normalization scheme | Per-criterion choice: existing fuzzy curve OR ordered classes ("steps") with score + plain-English label per class |
| Tier scores | User tiers (2/1/0 etc.) normalize to 0–1 (2→1.0, 1→0.5, 0→0.0); compose with weights/masks unchanged |
| Units in UI | Slope edited in degrees (stored percent, `pct = tan(deg)·100`); distances in miles (stored meters). Raw stored value shown alongside. |
| Settings UI | Gear button → right-side drawer; left panel unchanged |
| Persistence | localStorage autosave of current config + named presets; JSON file export/import for sharing/committing |
| Registry defaults | Scoring defaults in `config/criteria.json` unchanged (calibrated curves stay); classes are runtime overrides. The only registry edit is the additive `unit` metadata field. The user's slope example becomes a saved preset created during live verification, not a new default. |

## Data model

`types.ts` additions:

```ts
interface Step { max?: number; score: number; label: string }
// ordered; exactly one catch-all (no max) which must be last

type NormalizationOverride =
  | { mode: 'curve' }                       // use registry membership
  | { mode: 'steps'; steps: Step[] };

// ScoringConfig gains:
normalization: Record<string, NormalizationOverride>; // criterion key -> override; absent key = curve
```

Registry entries gain a `unit` field (`"pct_slope" | "meters" | "binary" | "category"`)
so the settings UI knows which conversion/editor to offer. `binary` and
`category` criteria (water, landcover) do NOT offer steps mode in Phase A —
water is already 0/1 and NLCD lookup-table editing is out of scope.

Validation (loud, on config load and import): steps ascending by `max`,
exactly one catch-all last, scores within [0,1], ≥2 steps, finite bounds.

## SQL generation

`membershipSQL` gains the steps case:

```sql
(CASE WHEN col <= b1 THEN s1 WHEN col <= b2 THEN s2 ... ELSE s_catchall END)
```

Bounds are inclusive (`<=`), evaluated in order. Golden-tested at exact
boundary values. Everything downstream (weights, masks, crosswalk,
aggregation) is unchanged.

## Settings drawer

- Gear button (header, right side) toggles a right-side drawer (~360 px)
  over the map; map/table stay live behind it — edits re-score with the
  existing debounce.
- One section per numeric criterion: mode toggle (Curve / Classes). In
  Classes mode: an editable table — upper bound (in display units), score
  (0–1, with a 2/1/0-style quick-set), label text; add/remove class rows;
  catch-all row always present and last. In Curve mode: read-only summary
  of the registry function (midpoint/spread in display units).
- Invalid edits (non-ascending bounds, empty label) show inline errors and
  do NOT re-score until valid — never send broken SQL.

## Class labels surface in outputs

When a criterion is in steps mode: map tooltip and RankTable show the
class label (e.g. "roads: some grading") next to the 0–1 value, and the
CSV export gains `<key>_class` label columns for stepped criteria. GeoJSON
export inherits the same properties.

## Persistence

- `localStorage["hexbin.current.v1"]` — full ScoringConfig, autosaved
  (debounced) on every change; restored on load with validation — an
  invalid/stale blob is discarded with a console warning, never a crash.
- `localStorage["hexbin.presets.v1"]` — named full-config snapshots.
  Preset bar in the drawer: save-as (name prompt via inline input, not
  window.prompt), load, delete (with inline confirm).
- Export: downloads `<name>.suitability-preset.json`
  `{ format: "hexbin-preset-v1", name, savedAt, config }`. Import: file
  picker; validated with the same rules; rejects with a readable error
  listing what failed. Imported presets land in the preset list.
- Config restored from any source is reconciled against the registry:
  unknown criterion keys dropped with a warning, missing keys filled from
  defaults — presets survive future registry additions (e.g. Phase B's
  drive-time criterion).

## Testing

- Golden (node DuckDB): steps SQL at boundary values (== max is inside),
  catch-all, 3-class slope example vs hand-computed parcel score.
- Unit: step validation (rejects unordered/duplicate/no-catch-all),
  unit conversions (5° ↔ 8.75%, mile ↔ meters round-trip),
  preset serialize → import round-trip, reconciliation (unknown key
  dropped, missing key defaulted), corrupted-localStorage recovery.
- Live Chrome: drawer UX, live re-score on class edit, labels in
  tooltip/table, preset save/load/export/import, reload restores state.

## Out of scope (Phase A)

Phase B drive-time measurement; editing NLCD lookup or binary criteria;
editing weights/masks from the drawer (they stay in the left panel);
preset sync beyond files; registry default changes.
