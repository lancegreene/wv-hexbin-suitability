# WV Parcel Suitability MVP — Design

2026-09-01. Approved via brainstorming session. Governing constraints live in
`CLAUDE.md` (two-stage architecture, scoring rules, H3 conventions); this spec
records the MVP-specific decisions and component design.

## Decisions

| Question | Decision |
|---|---|
| Audience | Internal — Lance (personal project). Rough edges acceptable. |
| Output | Exportable ranked parcel shortlist with per-criterion breakdown (CSV + GeoJSON). |
| County | Raleigh County, WV — FIPS 54081. |
| Criteria set | Pattern-proving core, 7 layers (below). |
| App layout | Sliders left, map center, ranked table docked bottom. |
| App stack | Vite + React + TypeScript SPA; deck.gl; DuckDB-WASM. No backend. |

## MVP criteria (pattern-proving core)

Chosen so every measurement pattern appears once; later criteria reuse a
pattern without schema churn.

| Criterion | Source | Pattern | Columns |
|---|---|---|---|
| Slope | USGS 3DEP | raster zonal + mask input | `slope_mean_pct`, `slope_pct_gt15` |
| Flood | FEMA NFHL | % overlay + mask input | `flood_pct_a_ae`, `floodway_pct` |
| Water service | EPA CWS boundaries | point-in-polygon + confidence | `water_in_service`, `water_conf` |
| Roads | WVDOT (TIGER fallback) | distance-to-line | `road_dist_m` |
| Transmission | EIA Energy Atlas | distance-to-line | `transmission_dist_m` |
| Mined areas | WVDEP TAGIS / WVGES | mask input | `mined_pct` |
| Land cover | NLCD | categorical lookup | `nlcd_mode` |

Deferred to post-MVP: sewer proxy, substations, wetlands, soils, broadband,
res-12 sub-parcel crosswalk, saved weight scenarios, additional counties.

## Repo structure

```
hexbin/
  config/criteria.json     # criteria registry — single source of truth
  pipeline/                # Python measurement stage
  app/                     # Vite + React + TS browser app
  data/raw/                # downloads, gitignored, never modified in place
  data/processed/          # published parquet artifacts
  docs/
```

## Data artifacts (pipeline → app contract)

1. **`cells_r10.parquet`** — one row per H3 res-10 cell covering the county.
   Raw measurements only (columns above), plus `h3_index` (string) and
   precomputed parents `h3_r9`, `h3_r8` so coarse views are a `GROUP BY` —
   no H3 math in the browser.
2. **`parcel_cell_xwalk.parquet`** — `parcel_id, h3_index, overlap_frac`.
   Res 10 only for MVP.
3. **`parcels.parquet`** — `parcel_id`, acreage, owner, district, etc.
4. **`parcels.geojson`** — simplified geometry, map rendering only.

**Raw in, masks derived at score time.** The parquet never stores scores or
masks. Masks are SQL predicates over raw columns (`floodway_pct > 0`,
`slope_mean_pct > threshold`, `mined_pct > 0`), so the slope threshold is an
app knob, not a pipeline re-run.

## Criteria registry — `config/criteria.json`

One entry per criterion: source column, a normalization spec — fuzzy
membership function + params (Large / Small / Near / Gaussian; e.g. roads =
Small, midpoint 1500 m) or, for `nlcd_mode`, a categorical class→score
lookup table — default weight, group (Infrastructure / Environment / Terrain), confidence
level. Pipeline reads it to know which columns to produce; app reads it to
build sliders and generate scoring SQL. Adding a criterion = one pipeline
module + one JSON entry; no app code changes.

## Pipeline

One CLI, county FIPS required, stages independently re-runnable:

`fetch` → `grid` → `measure` → `xwalk` → `validate`

- **fetch** — download each source to `data/raw/<source>/`, record provenance.
- **grid** — H3 res-10 cell set covering the county boundary. Indexing in
  EPSG:4326; all measurement in EPSG:26917 (explicit reprojection).
- **measure** — one module per criterion, each writing its columns to the
  cells table.
- **xwalk** — parcel↔cell overlap fractions via geopandas overlay
  (implemented with gpd.overlay rather than DuckDB spatial — same result,
  avoids the spatial extension in the pipeline; DuckDB remains in the stack
  for artifact sanity queries and the browser app).
- **validate** — hard gate before artifacts are published to
  `data/processed/`: cell counts, coverage %, null audit. Halts loudly on
  anomalies; zero-feature results never pass silently.

Environment: fresh `py -3 -m venv` venv with `h3`, `geopandas`, `rasterio`,
`duckdb`, `pyarrow`. No arcpy. (No interpreter on this machine currently has
this stack — see CLAUDE.md.)

## Browser app

Shared state: one **scoring config** object — weights, mask toggles, slope
threshold, WLC ↔ geometric-mean switch, display resolution (8/9/10),
hex/parcel display mode.

- **`WeightPanel`** (left) — slider per criterion from the registry, grouped,
  normalized weight shown. Mask checkboxes (floodway, mined, slope with
  editable threshold), aggregation switch, resolution picker. Low-confidence
  criteria carry a visible badge.
- **`MapView`** (center) — deck.gl `H3HexagonLayer` (cell scores at chosen
  resolution) or `GeoJsonLayer` parcel choropleth, toggled. Hover tooltip
  shows per-criterion breakdown.
- **`RankTable`** (bottom dock) — all scored parcels sorted by score: rank,
  parcel ID, acreage, total, one 0–1 column per criterion, masked/why
  indicator. Row click → map zooms to parcel. Export CSV / Export GeoJSON
  buttons, both generated client-side.

**Scoring flow:** DuckDB-WASM fetches the parquet files over HTTP from the
Vite server at startup. `buildScoreQuery(config)` translates registry +
config into one SQL statement: membership expressions → weighted linear
combination (or geometric mean) → multiplicative 0/1 masks → crosswalk join
→ overlap-weighted parcel means. Slider changes debounced ~50 ms. No caching
layers or web workers unless profiling demands them.

## Error handling

- **Pipeline:** every stage prints counts of what it fetched/wrote. Zero
  features or zero coverage halts with a message naming the source URL to
  check (endpoints move — re-check before assuming a code bug).
- **App:** missing parquet file or registry column not present in the table →
  full-screen error naming the file/column; never render silent zeros.
  All-zero weight vector disables scoring with a visible notice.

## Testing

- **Pipeline (pytest):** membership functions vs hand-computed values; each
  measure module on a tiny synthetic fixture (few cells, known geometry).
  No live downloads in tests — `validate` covers real-data sanity.
- **App (vitest):** golden test — `buildScoreQuery` output executed against
  in-memory DuckDB with a 10-cell / 3-parcel fixture; known weights in,
  hand-computed ranking out. This one test protects the full scoring
  semantics.

## Success criterion

Adjust sliders for Raleigh County, watch the parcel ranking reorder
interactively, and export a defensible top-N shortlist (CSV + GeoJSON) whose
per-criterion values can be traced back to named sources.
