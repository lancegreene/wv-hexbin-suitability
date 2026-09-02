# Data Sources

Verified as of September 2026. Re-check endpoints before assuming a
failed fetch is a code bug.

The four discovery-required endpoints (water, transmission, mined, NLCD) were
resolved on **2026-09-01** and are wired into `pipeline/hexbin_pipeline/fetch.py`.
Each is marked **RESOLVED** below with its live URL and the verified result for
Raleigh County (FIPS 54081). Do not re-discover these — read the section first.

## Base

**Parcels — WV GIS Technical Center / WV Property Tax Division**
- REST: `https://services.wvgis.wvu.edu/arcgis/rest/services/Planning_Cadastre/WV_Parcels/MapServer`
- Also served by WVDOT at `https://gis.transportation.wv.gov/arcgis/rest/services/Economic/FeatureServer/5`
- Viewer: https://www.mapwv.gov/parcel/ · https://www.mapwv.gov/assessment/
- Key fields: Parcel Identifier (County-District-Map-ParcelPrefix-ParcelSuffix-SpecialID),
  CleanParcelID, GISPID, owner, legal description, county code.
- **MaxRecordCount is 1000.** Do not page the REST endpoint for bulk
  extraction — pull the county file from the WVGISTC clearinghouse.
- County-level digital parcel files vary in availability and currency.
- **MANUAL INPUT — the pipeline does not fetch parcels.** The statewide tax
  parcel geodatabase (`WV_WVGISTC_Tax_2025.gdb`, from the WVGISTC
  clearinghouse; a copy lives at `<download-dir>/WV_WVGISTC_Tax_2025.gdb.zip`)
  must be extracted into `data/raw/parcels/` before the `xwalk` stage.
  `parcels.py` fails with instructions if it is absent. Layer/field mapping
  and the pyogrio where/columns quirk are documented in
  `pipeline/hexbin_pipeline/parcels.py`'s header comment.

## Infrastructure

**Water service — EPA Community Water System Service Area Boundaries**
- https://www.epa.gov/ground-water-and-drinking-water/public-water-system-service-areas
- **RESOLVED 2026-09-01 — layer 0 ("Final"), polygons:**
  `https://services.arcgis.com/cJ9YHowT8TU7DUyn/arcgis/rest/services/Water_System_Boundaries/FeatureServer/0`
- Verified: **25 features** for the Raleigh County (54081) bbox. maxRecordCount 2000.
- Polygons, not lines. Score as point-in-polygon; no distance threshold
  needed. This is the highest-confidence infrastructure layer available.
- v2 (Sep 2025) raised authoritative-source coverage past half of all
  boundaries; v3 added ~80k non-community systems at parcel-level
  geography.
- **CONF_FIELD = `Model_Method`.** This is the authoritative-vs-modeled
  discriminator. Blank/empty = boundary derived from a real source
  (authoritative); non-empty = EPA-modeled estimate.
  - WV-wide values: `''` (authoritative), `Random Forest`, `Decision Tree`, `Parcel`.
  - Raleigh bbox: `''` × 15, `Random Forest` × 10.
  - `Confirmed` and `Verification_Status` exist but are **empty for every WV
    row** — do not use them as the confidence flag.
- Supporting attributes (correlate with `Model_Method`, useful for messaging):
  - `Data_Provider_Type`: `State Agency` (11), `Federal agency` (10), `Water Utility` (4)
  - `Feature_Type`: `Water Main`, `Lead service line inventory`, `Census Place`, `Parcel`, `''`
  - `Modification_Method`: e.g. `Water mains were buffered by 200 meters`,
    `Traced service area boundary from feature`, `Georeferenced`
  - Every `Random Forest` row is `Data_Provider_Type='Federal agency'` with
    blank `Feature_Type` — the modeled rows are EPA's own national fill-in.
- Geometry quirk: some polygons fail `is_valid` (self-intersections). Repair
  with `make_valid`/`buffer(0)` before overlay or the join will silently drop rows.

**Sewer — no authoritative layer exists. Proxy only.**
- EPA CWNS facility locations, or NPDES/ECHO POTW discharge points.
- Gives treatment plant location, NOT collection system extent. WV
  service is by PSD, mapped county-by-county at best.
- Score as proximity-to-POTW and label low-confidence. Do not present
  this as equivalent to the water layer.

**Transmission lines — EIA U.S. Energy Atlas**
- https://atlas.eia.gov/ — 69 kV to 765 kV, AC and DC.
- **RESOLVED 2026-09-01 — layer 0, polylines:**
  `https://services2.arcgis.com/FiaPA4ga0iQKduv3/arcgis/rest/services/US_Electric_Power_Transmission_Lines/FeatureServer/0`
- Verified: **82 features** for the 54081 bbox, all `OWNER='APPALACHIAN POWER CO'`.
  `STATUS`: 81 `IN SERVICE`, 1 `NOT AVAILABLE`. `VOLTAGE`: mostly 46/69/138 kV,
  plus one 345 kV and one 765 kV row, and **17 rows with the `-999999` null
  sentinel** — filter it before any numeric use. `VOLT_CLASS` is populated even
  on sentinel rows (values seen: `UNDER 100`, `100-161`, `345`, `735 AND ABOVE`)
  — prefer it for binning.
- **Caveat — the layer is archived, not dead.** Item title is
  "U.S. Electric Power Transmission Lines (Archive)"; the description says
  "It will no longer be updated or maintained", data currency **09/30/2024**.
  It still serves queries normally. This is the HIFLD-derived layer the EIA
  Atlas displays, so it froze along with the 2025-08-26 HIFLD Open shutdown.
- **Discovery notes so this is not re-litigated:** EIA's own AGOL org
  (`FGr1D95XCGALKXqM`, services7) hosts 79 services and *none* are transmission
  lines — the Atlas pulls this layer from the Federal User Community org
  (`FiaPA4ga0iQKduv3`). A sort of all public "Electric Power Transmission Lines"
  feature services by modified-date returns only private/user copies of the same
  HIFLD extract; there is no maintained federal successor as of 2026-09-01.
  Treat vintage as a known limitation, same as substations.
- **Field quirk:** `VOLTAGE` uses **`-999999` as the null sentinel** (present in
  the Raleigh extract). Filter it out before any min/mean/threshold on voltage or
  it will wreck the statistic. `VOLT_CLASS` (`UNDER 100`, `100-161`, …) is
  populated even where `VOLTAGE` is the sentinel — prefer it for binning.

**Substations — archive only**
- EIA explicitly does not publish substation locations. HIFLD Open was
  shut down by DHS on 2025-08-26.
- HIFLD Next: https://hifld.publicenvirodata.org/
- SeerAI Parquet archive: https://source.coop/seerai/hifld — preferred,
  already Parquet on public object storage, reads straight into DuckDB.
- Data is frozen at shutdown. Treat vintage as a known limitation.

**Roads — WVDOT, or Census TIGER as fallback.** Weight distance by
functional class; an unimproved road is not site access.

**Broadband — FCC Broadband Data Collection / National Broadband Map.**

## Environmental

| Factor | Source | Measurement |
|---|---|---|
| Flood | FEMA NFHL | % cell in A/AE; floodway → mask |
| Slope | USGS 3DEP (WV has statewide lidar) | mean slope, % above threshold |
| Wetlands | USFWS NWI | % of cell |
| Land cover | NLCD / MRLC (see below) | categorical → suitability lookup |
| Soils | NRCS SSURGO | prime farmland, hydric, septic limitation |

**Land cover — MRLC Annual NLCD**
- **RESOLVED 2026-09-01 — Esri-hosted ImageServer (`exportImage`):**
  `https://di-nlcd.img.arcgis.com/arcgis/rest/services/USA_NLCD_Annual_LandCover/ImageServer`
- The constant is still named `NLCD_WCS` in `fetch.py` for continuity with the
  plan doc, but **the mechanism is ImageServer `exportImage`, not OGC WCS.**
  MRLC's own https://www.mrlc.gov/data-services-page publishes geoserver **WMS**
  for annual land cover (rendered images, not class codes) and WCS only for the
  1985–2023 *summary* products (change index / change count) — neither returns a
  clipped per-year thematic land-cover GeoTIFF. `.../geoserver/mrlc_download/wcs`
  GetCapabilities returns **404**. The ImageServer is the working path.
- Verified for 54081: **2275 × 2093 px, 30 m pixels, EPSG:5070, uint8, 100%
  classified**, 5,016,534 bytes. Classes present:
  11, 21, 22, 23, 24, 31, 41, 42, 43, 52, 71, 81, 82, 90, 95 (41 deciduous
  forest dominates — correct for southern WV).
- **The mosaic holds one raster per year, 1985–2024** (`Annual_NLCD_LndCov_YYYY_CU_C1V0`).
  A request with no `mosaicRule` returns the server's default slice — currently
  2024, but that is not contractual. `fetch_nlcd` pins
  `mosaicRule={"where":"Year=2024"}` so the vintage cannot drift between runs.
  Verified the rule is honoured: 1985, 2005 and 2024 return different rasters.
- Request in **EPSG:5070** (NLCD's native Albers), not 4326: a 4326 request
  yields degree-sized pixels and forces the server to resample categorical class
  codes. `interpolation=RSP_NearestNeighbor` is set for the same reason.
  Downstream zonal stats should reproject hex cells to the raster CRS.
- Service caps `size` at 20000 px/side. Raleigh needs 2275 × 2093, so a single
  request is fine; a much larger county would need tiling (`fetch_nlcd` raises
  with that instruction rather than quietly coarsening the resolution).
- No token or API key required.

## WV-specific

**Mined-out areas and abandoned mine lands**
- WV Geological and Economic Survey (WVGES) and WVDEP TAGIS.
- **RESOLVED 2026-09-01 — TAGIS "underground mining limits", layer 10, polygons:**
  `https://tagis.dep.wv.gov/arcgis/rest/services/WVDEP_enterprise/mining_reclamation/MapServer/10`
- Verified: **179 features** for the 54081 bbox. maxRecordCount 5000.
- Service directory: `https://tagis.dep.wv.gov/arcgis/rest/services?f=json`.
  Mining layers live under the `WVDEP_enterprise/mining_reclamation` MapServer;
  `WVDEP_enterprise/abandoned_mine_lands` is a separate service (AML inventory
  points/lines/polygons) and is **not** a substitute for mine workings.
- **Do not confuse with the permit-boundary layers in the same service**
  (7 = Revoked, 8 = Completely Released, 9 = Inspection status). Those are
  administrative permit outlines, not mined extent. Layer 10 is the mined-out
  extent layer.
- Underground mine workings drive subsidence risk across much of WV.
  This is a constraint layer, not a criterion, and it is the layer a
  generic national model would omit.
- **Attribute quirks (decide filtering deliberately in the mined module):**
  - Fields: `permit_id`, `mapdate`, `maptype`, `facility_name`, `operator`,
    `permittee`, `update_date`, `permit_seam`, `wvges_seam`, `comments`.
  - `permit_id` prefix is the permit type. Raleigh mix: **U** (underground) 105,
    **S** (surface) 64, **E** 4, **D** 2, **O** (haul road) 1, **Q** (quarry) 1,
    plus **2 rows with fully-null attributes** (`permit_id`, `facility_name`,
    `maptype`, `operator` all null) — geometry only. A `LIKE 'U%'` filter drops
    them; decide whether that is acceptable when the filter is written.
    The S-prefix rows are real entries in this layer — mined-out area is
    attributed to whichever permit authorised the extraction, and seam values
    like `HMinli_*` (highwall miner) / `SMinli_*` sit under surface permits.
    If the module wants strictly underground workings, filter on
    `permit_id LIKE 'U%'`; if it wants all mined-out ground, keep everything.
    Either is defensible — just do not assume the layer is already U-only.
  - `maptype` is the **source map** the polygon was digitised from, *not* the
    mining method. Coded domain `dmr_maptype`: `pr` proposal, `pd` proposal
    drainage, `rp` renewal progress, `fi` final, `is` inactive status,
    `sc` subsidence control plan, `dr` drainage, `ge` geologic, `ot` other,
    `na` not assigned, `aj` adjacent permit. Raleigh also contains values
    outside the published domain: `ep` (78), `' '` single space (8), null (10),
    `dw` (1), `S5` (1), and uppercase `EP` (1, distinct from `ep`).
  - Some polygons fail `is_valid`; repair before overlay.

## 54081 (Raleigh County) run log

**2026-09-01 — first full pipeline run.** All stages green; artifacts
published to `data/processed/54081/`.

| Metric | Value |
|---|---|
| Res-10 cells | 118,972 |
| Parcels | 60,683 (100% with >=1 cell; 63 without ParcelSummary attributes) |
| Crosswalk rows | 275,421 |
| County mean slope | 35.8% |
| Cells in CWS water service | 12.1% (9,152 authoritative / 5,227 modeled) |
| Cells with underground-mine coverage | 24,802 (20.8%) |
| Cells with A/AE flood coverage | 8,180; floodway 784 |
| Median distance to improved road | 272 m |
| Median distance to transmission | 2,109 m |
| Dominant NLCD class | 41 deciduous forest (76.2%) |
| Measure-stage wall time | ~27 min (grid to last measure module; slope zonal passes alone ~12.5 min) |

**2026-09-02 — browser app (Plan 2) implemented**; artifacts consumed unchanged.
Re-score latency ~1.4-1.6 s (60,683 parcels + hex agg per change); parcel-choropleth first paint ~30 s (19 MB GeoJSON parse).
