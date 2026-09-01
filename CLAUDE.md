# WV Parcel Suitability — Hex-Indexed Scoring

Multi-criteria site suitability scoring for West Virginia parcels, using H3
as a precomputed measurement grid.

@docs/data-sources.md

## Architecture

Two hard-separated stages. Do not collapse them.

1. **Measure** (slow, cached). Sample every criterion onto H3 cells once.
   Output: one Parquet table keyed on `h3_index`, one column per raw
   measurement. Re-run only when a source layer changes.
2. **Score** (fast, interactive). Pure arithmetic over the measurement
   table given a weight vector. Must stay fast enough to re-run on a
   slider drag. No spatial operations in this stage.

A third artifact joins them: `parcel_cell_xwalk` — `parcel_id`,
`h3_index`, `overlap_frac`. Parcel scores are the `overlap_frac`-weighted
mean of their cells.

## Scoring rules

- **Constraints are a multiplicative 0/1 mask applied after the weighted
  sum.** Never fold a hard exclusion into the weights. Current masks:
  FEMA floodway, slope above threshold, undermined area.
- Criteria normalize to 0–1 via fuzzy membership functions (Large, Small,
  Near, Gaussian), not plain linear rescale.
- Default aggregation is weighted linear combination. Keep a weighted
  geometric mean available as a config flag — WLC is fully compensatory
  and that is sometimes wrong.
- Every criterion carries a confidence flag. Modeled or proxy sources
  (sewer especially) must be distinguishable from authoritative ones in
  the output.

## Resolution

- Measure at H3 res 10 (~0.015 km², ~70–100k cells per WV county).
- Aggregate to res 9 and 8 with `cell_to_parent` for the screening view.
  Never re-measure at coarser resolutions.
- Urban parcels can be smaller than a res 10 cell. Where sub-parcel
  detail is needed, carry a res 12 index in the crosswalk rather than
  changing the base grid.

## Stack

- Python for the measurement stage: `h3`, `geopandas`, `rasterio`,
  `duckdb` (with the `spatial` and `h3` extensions).
- **No interpreter on this machine has this stack yet** (checked
  2026-09-01): `arcgispro-py3` has geopandas + pyarrow but lacks h3,
  duckdb, and rasterio; the `py.exe` 3.12 install has none of them.
  Set up a dedicated environment before writing measurement code —
  don't assume imports will resolve.
- DuckDB + Parquet as the storage layer. No PostGIS, no file geodatabase
  in the pipeline — GDB only as a source format to read from.
- Browser app: DuckDB-WASM + deck.gl `H3HexagonLayer`. Local-first, no
  server. Do not introduce a backend API.

## Conventions

- H3 indexing happens in EPSG:4326. All area and distance computation
  happens in EPSG:26917 (UTM 17N, NAD83). Reproject explicitly; never
  rely on an implicit CRS.
- H3 indexes are stored as strings, not uint64.
- One county per pipeline run during MVP. County FIPS is a required
  parameter, not a default.
- Raw downloads land in `data/raw/` and are never modified in place.
  `data/raw/` is gitignored; record provenance in `docs/data-sources.md`.

## Commands

- Pipeline env: `.venv/Scripts/python.exe` (repo-root venv; created via
  `py -3 -m venv .venv` + `pip install -e pipeline`)
- Run a stage: `.venv/Scripts/python.exe -m hexbin_pipeline <fetch|grid|measure|xwalk|validate|all> --fips 54081`
- Single measure module: `... measure --fips 54081 --only slope`
- Tests: `.venv/Scripts/python.exe -m pytest pipeline/tests -q`
- Published artifacts land in `data/processed/<fips>/`; intermediates in
  `data/work/<fips>/`; the measure stage is the slow one (~30 min/county,
  slope zonal passes dominate).

## Scope

MVP is a single county. Do not add statewide processing, additional
counties, or new criteria until the measurement schema has stopped
changing.
