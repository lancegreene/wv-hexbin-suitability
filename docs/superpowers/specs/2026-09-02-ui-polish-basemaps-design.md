# UI Polish + Base Layers — Design

2026-09-02. Approved via brainstorming. Extends the merged MVP app
(`app/`); no scoring changes. Chrome placement: floating map cards
(option A) + sectioned panel cards (option B), per mockup selection.

## Decisions

| Question | Decision |
|---|---|
| Basemap source | Esri raster tiles: `World_Street_Map`, `World_Imagery` (+ `World_Boundaries_and_Places` labels overlay on imagery) |
| Default basemap | `none` — app still opens fully offline; tiles load only when switched |
| Controls placement | Basemap switcher + opacity: floating card top-right of map. Legend: floating card bottom-left. |
| Panel | Existing five groups become bordered section cards (CSS + small JSX wrappers; controls unchanged) |
| Header | Slim bar: title · "Raleigh County, WV (54081)" · counts (cells / parcels / shown) · Esri attribution right-aligned. Error banner + busy indicator dock beneath it. |
| County outline | Thin white line from a NEW pipeline artifact `county_boundary.geojson` |

## Config model additions

`ScoringConfig` gains display-only fields (no SQL impact):
- `basemap: 'none' | 'streets' | 'imagery'` (default `'none'`)
- `scoreOpacity: number` 0–1 (default `0.8`) — multiplies the alpha of the
  hex and parcel score layers so imagery reads through

Both covered by the default-config test.

## Layers (bottom → top)

1. `TileLayer` — Esri raster tiles per `basemap`; absent when `none`.
   Endpoints (raster tile scheme `/tile/{z}/{y}/{x}`):
   - streets: `https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer`
   - imagery: `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer`
   - labels overlay (imagery only): `https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer`
2. Score layer (existing `H3HexagonLayer` or `GeoJsonLayer`) with alpha
   scaled by `scoreOpacity`.
3. County outline — `GeoJsonLayer`, `county_boundary.geojson`, stroke only
   (white, ~1.5 px), not pickable.

## Pipeline change (small)

`validate.run` additionally publishes `county_boundary.geojson`: the
unbuffered county polygon from `load_county(fips)`, reprojected to
EPSG:4326, geometry-only. One `validate` re-run publishes it; no
re-measure. The app's startup HEAD-check list gains the file with the
same actionable error message pattern.

## Attribution

Esri tile usage requires attribution: header shows
"Basemap: Esri, Maxar, Earthstar Geographics" when a basemap is active
(dimmed/absent when `none`).

## Testing

- Unit: default-config values for `basemap`/`scoreOpacity`; existing 15
  tests unchanged.
- Live Chrome verification: basemap switching, opacity fade over imagery,
  legend/outline/header render, no console errors, offline start with
  `none`.

## Out of scope

Vector basemaps / MapLibre, offline tile caching, map-image export,
scale bar, any scoring or table changes.
