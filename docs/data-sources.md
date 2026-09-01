# Data Sources

Verified as of September 2026. Re-check endpoints before assuming a
failed fetch is a code bug.

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

## Infrastructure

**Water service — EPA Community Water System Service Area Boundaries**
- https://www.epa.gov/ground-water-and-drinking-water/public-water-system-service-areas
- Polygons, not lines. Score as point-in-polygon; no distance threshold
  needed. This is the highest-confidence infrastructure layer available.
- v2 (Sep 2025) raised authoritative-source coverage past half of all
  boundaries; v3 added ~80k non-community systems at parcel-level
  geography. Check the attribute table for whether each WV boundary is
  authoritative or modeled and propagate that into the confidence flag.

**Sewer — no authoritative layer exists. Proxy only.**
- EPA CWNS facility locations, or NPDES/ECHO POTW discharge points.
- Gives treatment plant location, NOT collection system extent. WV
  service is by PSD, mapped county-by-county at best.
- Score as proximity-to-POTW and label low-confidence. Do not present
  this as equivalent to the water layer.

**Transmission lines — EIA U.S. Energy Atlas**
- https://atlas.eia.gov/ — 69 kV to 765 kV, AC and DC. Still live and
  federally maintained.

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
| Land cover | NLCD / MRLC | categorical → suitability lookup |
| Soils | NRCS SSURGO | prime farmland, hydric, septic limitation |

## WV-specific

**Mined-out areas and abandoned mine lands**
- WV Geological and Economic Survey (WVGES) and WVDEP TAGIS.
- WVDEP TAGIS also publishes lidar coverage status for the state.
- Underground mine workings drive subsidence risk across much of WV.
  This is a constraint layer, not a criterion, and it is the layer a
  generic national model would omit.
