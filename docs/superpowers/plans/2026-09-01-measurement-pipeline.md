# Measurement Pipeline Implementation Plan (Plan 1 of 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A re-runnable Python pipeline that samples 7 suitability criteria onto an H3 res-10 grid for Raleigh County, WV (FIPS 54081) and publishes four validated artifacts: `cells_r10.parquet`, `parcel_cell_xwalk.parquet`, `parcels.parquet`, `parcels.geojson`.

**Architecture:** One CLI (`python -m hexbin_pipeline <stage> --fips 54081`) with independently re-runnable stages: `fetch` → `grid` → `measure` → `xwalk` → `validate`. Each measure module writes its own parquet to `data/work/<fips>/`; `validate` joins them, hard-gates on anomalies, and publishes to `data/processed/<fips>/`. Raw measurements only — no scores, no masks (those are derived in the app at score time). H3 indexing in EPSG:4326; all area/distance math in EPSG:26917.

**Tech Stack:** Python 3.12 (`py.exe`, fresh venv — no interpreter on this machine has the stack), geopandas + pyogrio, rasterio + rasterstats, h3 (v4 API), pyarrow, requests, pytest.

**Plan 2 (browser app)** is written after this plan executes, against the real artifacts.

**Reference:** spec at `docs/superpowers/specs/2026-09-01-suitability-mvp-design.md`; source endpoints and caveats in `docs/data-sources.md` — re-check endpoints before assuming a failed fetch is a code bug.

---

## File structure

```
hexbin/
  config/criteria.json                  # criteria registry (Task 2)
  pipeline/
    pyproject.toml                      # installable package + deps
    hexbin_pipeline/
      __init__.py
      __main__.py                       # python -m hexbin_pipeline
      cli.py                            # argparse dispatch
      paths.py                          # ROOT / data dir helpers
      grid.py                           # county boundary -> res-10 cell GeoDataFrame
      fetch.py                          # download helpers + SOURCES registry
      parcels.py                        # extract county parcels from statewide GDB
      xwalk.py                          # parcel<->cell overlap fractions
      validate.py                       # hard gate; publishes artifacts
      measure/
        __init__.py                     # module registry, run_all()
        common.py                       # pct_overlap, dist_to_nearest (vector helpers)
        rasters.py                      # slope raster build, zonal helpers
        slope.py  flood.py  water.py  roads.py
        transmission.py  mined.py  landcover.py
    tests/
      conftest.py                       # synthetic cell fixtures
      test_grid.py  test_common.py  test_rasters.py
      test_flood.py  test_xwalk.py  test_validate.py
  data/raw/<source>/                    # gitignored, never modified in place
  data/work/<fips>/                     # gitignored, per-stage intermediates
  data/processed/<fips>/                # gitignored, published artifacts
```

All commands below run from the repo root (`hexbin`) in Git Bash. `PY=.venv/Scripts/python.exe`.

---

### Task 1: Python environment

**Files:**
- Create: `pipeline/pyproject.toml`
- Create: `pipeline/hexbin_pipeline/__init__.py` (empty)
- Modify: `.gitignore`

- [ ] **Step 1: Create venv**

```bash
py -3 -m venv .venv
.venv/Scripts/python.exe --version   # expect Python 3.12.x
```

- [ ] **Step 2: Write `pipeline/pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "hexbin-pipeline"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "geopandas>=1.0",
  "pyogrio>=0.9",
  "rasterio>=1.3",
  "rasterstats>=0.19",
  "h3>=4.0",
  "pyarrow>=16",
  "duckdb>=1.0",
  "requests>=2.31",
  "pytest>=8.0",
]

[tool.setuptools.packages.find]
where = ["."]
include = ["hexbin_pipeline*"]
```

- [ ] **Step 3: Create empty `pipeline/hexbin_pipeline/__init__.py`, install editable**

```bash
.venv/Scripts/python.exe -m pip install -e pipeline
.venv/Scripts/python.exe -c "import geopandas, rasterio, rasterstats, h3, duckdb, pyarrow; print('env ok')"
```
Expected: `env ok`. If a wheel fails to build on Windows, report the exact error — do not swap in conda silently.

- [ ] **Step 4: Append to `.gitignore`**

```
.venv/
data/work/
data/processed/
__pycache__/
*.egg-info/
```

- [ ] **Step 5: Commit**

```bash
git add .gitignore pipeline/pyproject.toml pipeline/hexbin_pipeline/__init__.py
git commit -m "chore: pipeline package skeleton and venv config"
```

---

### Task 2: Criteria registry, paths, CLI skeleton

**Files:**
- Create: `config/criteria.json`
- Create: `pipeline/hexbin_pipeline/paths.py`
- Create: `pipeline/hexbin_pipeline/cli.py`
- Create: `pipeline/hexbin_pipeline/__main__.py`

- [ ] **Step 1: Write `config/criteria.json`**

Single source of truth shared with the app. Membership functions use the ESRI fuzzy forms (`small`: score = 1/(1+(x/midpoint)^spread), high score at small values; `large` is the inverse; `binary` passes the 0/1 value through; `lookup` maps categorical codes). NLCD class scores are first-pass defaults — tune later in the app, not here.

```json
{
  "criteria": [
    {"key": "slope", "label": "Slope", "column": "slope_mean_pct", "group": "Terrain",
     "membership": {"fn": "small", "midpoint": 8, "spread": 4}, "weight": 0.20, "confidence": "authoritative"},
    {"key": "flood", "label": "Flood risk", "column": "flood_pct_a_ae", "group": "Environment",
     "membership": {"fn": "small", "midpoint": 15, "spread": 3}, "weight": 0.15, "confidence": "authoritative"},
    {"key": "water", "label": "Water service", "column": "water_in_service", "group": "Infrastructure",
     "membership": {"fn": "binary"}, "weight": 0.20, "confidence": "per-feature"},
    {"key": "roads", "label": "Road access", "column": "road_dist_m", "group": "Infrastructure",
     "membership": {"fn": "small", "midpoint": 1500, "spread": 3}, "weight": 0.15, "confidence": "authoritative"},
    {"key": "transmission", "label": "Transmission proximity", "column": "transmission_dist_m", "group": "Infrastructure",
     "membership": {"fn": "small", "midpoint": 3000, "spread": 3}, "weight": 0.15, "confidence": "authoritative"},
    {"key": "landcover", "label": "Land cover", "column": "nlcd_mode", "group": "Environment",
     "membership": {"fn": "lookup", "table": {"11": 0.0, "21": 0.8, "22": 0.9, "23": 1.0, "24": 1.0,
       "31": 0.7, "41": 0.5, "42": 0.5, "43": 0.5, "52": 0.6, "71": 0.7, "81": 0.6, "82": 0.4,
       "90": 0.1, "95": 0.1}}, "weight": 0.15, "confidence": "authoritative"}
  ],
  "masks": [
    {"key": "floodway", "label": "FEMA floodway", "column": "floodway_pct", "predicate": "> 0"},
    {"key": "mined", "label": "Undermined area", "column": "mined_pct", "predicate": "> 0"},
    {"key": "slope_limit", "label": "Steep slope", "column": "slope_mean_pct", "predicate": "> {threshold}", "default_threshold": 15}
  ]
}
```

- [ ] **Step 2: Write `pipeline/hexbin_pipeline/paths.py`**

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
WORK = ROOT / "data" / "work"
PROCESSED = ROOT / "data" / "processed"
CRITERIA = ROOT / "config" / "criteria.json"


def raw_dir(source: str) -> Path:
    d = RAW / source
    d.mkdir(parents=True, exist_ok=True)
    return d


def work_dir(fips: str) -> Path:
    d = WORK / fips
    d.mkdir(parents=True, exist_ok=True)
    return d


def processed_dir(fips: str) -> Path:
    d = PROCESSED / fips
    d.mkdir(parents=True, exist_ok=True)
    return d


def grid_path(fips: str) -> Path:
    return work_dir(fips) / "grid.parquet"
```

- [ ] **Step 3: Write `pipeline/hexbin_pipeline/cli.py` and `__main__.py`**

```python
# cli.py
import argparse


def main():
    p = argparse.ArgumentParser(prog="hexbin_pipeline",
                                description="WV parcel suitability measurement pipeline")
    p.add_argument("stage", choices=["fetch", "grid", "measure", "xwalk", "validate", "all"])
    p.add_argument("--fips", required=True, help="5-digit county FIPS, e.g. 54081")
    p.add_argument("--only", help="run a single measure module (slope|flood|water|roads|transmission|mined|landcover)")
    args = p.parse_args()

    # local imports so a broken module only breaks its own stage
    if args.stage in ("fetch", "all"):
        from . import fetch
        fetch.run(args.fips)
    if args.stage in ("grid", "all"):
        from . import grid
        grid.run(args.fips)
    if args.stage in ("measure", "all"):
        from . import measure
        measure.run_all(args.fips, only=args.only)
    if args.stage in ("xwalk", "all"):
        from . import xwalk
        xwalk.run(args.fips)
    if args.stage in ("validate", "all"):
        from . import validate
        validate.run(args.fips)
```

```python
# __main__.py
from .cli import main

main()
```

- [ ] **Step 4: Smoke-check the CLI errors cleanly (stages not written yet)**

```bash
.venv/Scripts/python.exe -m hexbin_pipeline grid --fips 54081
```
Expected: `ModuleNotFoundError`/`ImportError` naming `grid` — proves dispatch works. `--fips` omitted must exit 2 with usage text.

- [ ] **Step 5: Commit**

```bash
git add config/criteria.json pipeline/hexbin_pipeline/paths.py pipeline/hexbin_pipeline/cli.py pipeline/hexbin_pipeline/__main__.py
git commit -m "feat: criteria registry, paths, CLI dispatch"
```

---

### Task 3: Grid stage (TDD)

**Files:**
- Create: `pipeline/hexbin_pipeline/grid.py`
- Create: `pipeline/tests/conftest.py`
- Test: `pipeline/tests/test_grid.py`

- [ ] **Step 1: Write `pipeline/tests/conftest.py`** — shared synthetic fixtures

```python
import geopandas as gpd
import h3
import pytest
from shapely.geometry import Polygon

BECKLEY = (37.778, -81.188)  # lat, lng


def cells_from_h3(cell_ids):
    """Build a grid-style GeoDataFrame from explicit H3 cells (mirrors grid.cells_to_gdf)."""
    rows = []
    for c in cell_ids:
        ring = [(lng, lat) for lat, lng in h3.cell_to_boundary(c)]
        rows.append({"h3_index": c, "h3_r9": h3.cell_to_parent(c, 9),
                     "h3_r8": h3.cell_to_parent(c, 8), "geometry": Polygon(ring)})
    return gpd.GeoDataFrame(rows, crs="EPSG:4326")


@pytest.fixture
def seven_cells():
    """A res-10 cell near Beckley plus its 6 neighbors."""
    center = h3.latlng_to_cell(*BECKLEY, 10)
    return cells_from_h3(h3.grid_disk(center, 1))
```

- [ ] **Step 2: Write failing test `pipeline/tests/test_grid.py`**

```python
import h3
from shapely.geometry import Polygon

from hexbin_pipeline.grid import cells_for_boundary


def test_cells_cover_small_polygon():
    # ~1 km square near Beckley, EPSG:4326 (lng, lat order)
    poly = Polygon([(-81.19, 37.77), (-81.18, 37.77), (-81.18, 37.78), (-81.19, 37.78)])
    gdf = cells_for_boundary(poly)
    assert len(gdf) > 30  # ~1 km^2 at res 10 (~0.015 km^2/cell)
    assert set(gdf.columns) >= {"h3_index", "h3_r9", "h3_r8", "geometry"}
    assert gdf["h3_index"].is_unique
    row = gdf.iloc[0]
    assert h3.get_resolution(row.h3_index) == 10
    assert h3.cell_to_parent(row.h3_index, 9) == row.h3_r9
    assert h3.cell_to_parent(row.h3_index, 8) == row.h3_r8
    assert gdf.crs.to_epsg() == 4326
```

- [ ] **Step 3: Run to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest pipeline/tests/test_grid.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'hexbin_pipeline.grid'`

- [ ] **Step 4: Write `pipeline/hexbin_pipeline/grid.py`**

```python
import geopandas as gpd
import h3
from shapely.geometry import Polygon

from .paths import grid_path, raw_dir

UTM = "EPSG:26917"


def cells_to_gdf(cell_ids):
    rows = []
    for c in cell_ids:
        ring = [(lng, lat) for lat, lng in h3.cell_to_boundary(c)]
        rows.append({"h3_index": c, "h3_r9": h3.cell_to_parent(c, 9),
                     "h3_r8": h3.cell_to_parent(c, 8), "geometry": Polygon(ring)})
    return gpd.GeoDataFrame(rows, crs="EPSG:4326")


def cells_for_boundary(boundary_4326):
    """(Multi)Polygon in EPSG:4326 -> GeoDataFrame of covering res-10 cells."""
    shape = h3.geo_to_h3shape(boundary_4326.__geo_interface__)
    cell_ids = h3.h3shape_to_cells(shape, 10)
    if not cell_ids:
        raise RuntimeError("H3 polyfill returned 0 cells — boundary geometry or CRS is wrong")
    return cells_to_gdf(cell_ids)


def run(fips):
    counties = gpd.read_file(raw_dir("county") / "counties.zip")
    county = counties[counties["GEOID"] == fips]
    if len(county) != 1:
        raise RuntimeError(f"expected exactly 1 county with GEOID={fips}, found {len(county)} "
                           f"in {raw_dir('county') / 'counties.zip'}")
    # Buffer 500 m so edge parcels still get full cell coverage (boundary file is generalized)
    boundary = county.to_crs(UTM).buffer(500).to_crs("EPSG:4326").iloc[0]
    gdf = cells_for_boundary(boundary)
    dest = grid_path(fips)
    gdf.to_parquet(dest)
    print(f"grid: {len(gdf)} res-10 cells for {fips} -> {dest}")
    return dest
```

- [ ] **Step 5: Run tests, verify pass**

```bash
.venv/Scripts/python.exe -m pytest pipeline/tests/test_grid.py -v
```
Expected: PASS (1 test)

- [ ] **Step 6: Commit**

```bash
git add pipeline/tests/conftest.py pipeline/tests/test_grid.py pipeline/hexbin_pipeline/grid.py
git commit -m "feat: H3 res-10 grid stage with parent indexes"
```

---

### Task 4: Fetch helpers + deterministic sources

**Files:**
- Create: `pipeline/hexbin_pipeline/fetch.py`

Deterministic URLs go in now; four sources need endpoint discovery (Task 5). No unit tests for network code — the `validate` stage and loud runtime failures cover it.

- [ ] **Step 1: Write `pipeline/hexbin_pipeline/fetch.py`**

```python
import json
import math

import requests

from .paths import raw_dir

TIMEOUT = 120

# Verified deterministic sources. Discovery-required sources are added by Task 5.
COUNTY_URL = "https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_county_500k.zip"
ROADS_URL = "https://www2.census.gov/geo/tiger/TIGER2024/ROADS/tl_2024_{fips}_roads.zip"
DEM_URL = "https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/13/TIFF/current/{t}/USGS_13_{t}.tif"
NFHL_LAYER = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28"

# Filled in by Task 5 endpoint discovery:
WATER_LAYER = None         # EPA Community Water System service area boundaries (polygons)
TRANSMISSION_LAYER = None  # EIA Energy Atlas transmission lines
MINED_LAYER = None         # WVDEP TAGIS / WVGES underground mining polygons
NLCD_WCS = None            # MRLC NLCD land cover coverage endpoint


def download_file(url, dest):
    if dest.exists() and dest.stat().st_size > 0:
        print(f"fetch: {dest.name} already present ({dest.stat().st_size:,} bytes), skipping")
        return dest
    print(f"fetch: GET {url}")
    r = requests.get(url, timeout=TIMEOUT, stream=True)
    r.raise_for_status()
    tmp = dest.with_suffix(dest.suffix + ".part")
    with open(tmp, "wb") as f:
        for chunk in r.iter_content(1 << 20):
            f.write(chunk)
    if tmp.stat().st_size == 0:
        tmp.unlink()
        raise RuntimeError(f"fetch: {url} returned an empty file — check the endpoint "
                           f"(see docs/data-sources.md)")
    tmp.rename(dest)
    print(f"fetch: wrote {dest} ({dest.stat().st_size:,} bytes)")
    return dest


def fetch_arcgis_layer(layer_url, dest, where="1=1", bbox_4326=None):
    """Page an ArcGIS REST layer to GeoJSON. bbox_4326 = (minx, miny, maxx, maxy)."""
    if dest.exists() and dest.stat().st_size > 0:
        print(f"fetch: {dest.name} already present, skipping")
        return dest
    params = {"where": where, "outFields": "*", "f": "geojson", "outSR": 4326,
              "resultOffset": 0}
    if bbox_4326:
        params.update(geometry=",".join(str(v) for v in bbox_4326), geometryType="esriGeometryEnvelope",
                      inSR=4326, spatialRel="esriSpatialRelIntersects")
    features = []
    while True:
        r = requests.get(f"{layer_url}/query", params=params, timeout=TIMEOUT)
        r.raise_for_status()
        page = r.json()
        if "error" in page:
            raise RuntimeError(f"fetch: {layer_url} error: {page['error']} — check the endpoint")
        feats = page.get("features", [])
        features.extend(feats)
        print(f"fetch: {dest.name} page at offset {params['resultOffset']}: {len(feats)} features")
        if not page.get("properties", {}).get("exceededTransferLimit") and len(feats) < 1000:
            break
        if not feats:
            break
        params["resultOffset"] += len(feats)
    if not features:
        raise RuntimeError(f"fetch: 0 features from {layer_url} where={where} — wrong layer, "
                           f"wrong filter, or moved endpoint (see docs/data-sources.md)")
    dest.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    print(f"fetch: wrote {len(features)} features -> {dest}")
    return dest


def dem_tiles(bounds):
    """1-degree n##w### tile names covering (minx, miny, maxx, maxy) in EPSG:4326."""
    minx, miny, maxx, maxy = bounds
    return sorted({f"n{lat + 1:02d}w{abs(lon):03d}"
                   for lat in range(math.floor(miny), math.ceil(maxy))
                   for lon in range(math.floor(minx), math.ceil(maxx))})


def county_bounds(fips):
    import geopandas as gpd
    counties = gpd.read_file(raw_dir("county") / "counties.zip")
    county = counties[counties["GEOID"] == fips]
    if len(county) != 1:
        raise RuntimeError(f"county GEOID={fips} not found in boundary file")
    return tuple(county.total_bounds)  # (minx, miny, maxx, maxy)


def run(fips):
    download_file(COUNTY_URL, raw_dir("county") / "counties.zip")
    bounds = county_bounds(fips)
    print(f"fetch: {fips} bounds {bounds}")

    download_file(ROADS_URL.format(fips=fips), raw_dir("roads") / f"roads_{fips}.zip")
    for t in dem_tiles(bounds):
        download_file(DEM_URL.format(t=t), raw_dir("dem") / f"USGS_13_{t}.tif")
    fetch_arcgis_layer(NFHL_LAYER, raw_dir("nfhl") / f"nfhl_{fips}.geojson", bbox_4326=bounds)

    missing = [name for name, url in [("WATER_LAYER", WATER_LAYER),
                                      ("TRANSMISSION_LAYER", TRANSMISSION_LAYER),
                                      ("MINED_LAYER", MINED_LAYER), ("NLCD_WCS", NLCD_WCS)] if url is None]
    if missing:
        raise RuntimeError(f"fetch: endpoints not yet configured: {missing} — "
                           f"complete endpoint discovery (plan Task 5) before running "
                           f"the full fetch stage")
    fetch_arcgis_layer(WATER_LAYER, raw_dir("water") / f"water_{fips}.geojson", bbox_4326=bounds)
    fetch_arcgis_layer(TRANSMISSION_LAYER, raw_dir("transmission") / f"transmission_{fips}.geojson",
                       bbox_4326=bounds)
    fetch_arcgis_layer(MINED_LAYER, raw_dir("mined") / f"mined_{fips}.geojson", bbox_4326=bounds)
    fetch_nlcd(fips, bounds)


def fetch_nlcd(fips, bounds):
    """Clipped NLCD land cover GeoTIFF for the county bbox. NLCD_WCS set by Task 5."""
    dest = raw_dir("nlcd") / f"nlcd_{fips}.tif"
    if dest.exists() and dest.stat().st_size > 0:
        print(f"fetch: {dest.name} already present, skipping")
        return dest
    raise RuntimeError("fetch_nlcd: implemented during endpoint discovery (plan Task 5) — "
                       "the request format depends on which MRLC endpoint is live")
```

- [ ] **Step 2: Run the deterministic part**

```bash
.venv/Scripts/python.exe -m hexbin_pipeline fetch --fips 54081
```
Expected: county zip (~10 MB), roads zip, 2+ DEM tiles (~400 MB each — this is the slow download), NFHL geojson with feature counts printed, then `RuntimeError: endpoints not yet configured: ['WATER_LAYER', ...]`. That error is the correct stopping point for this task.

- [ ] **Step 3: Also run the grid stage now that the boundary exists**

```bash
.venv/Scripts/python.exe -m hexbin_pipeline grid --fips 54081
```
Expected: `grid: N res-10 cells for 54081 -> data/work/54081/grid.parquet` with N in the 70,000–120,000 range. Outside that range → stop and investigate before continuing.

- [ ] **Step 4: Commit**

```bash
git add pipeline/hexbin_pipeline/fetch.py
git commit -m "feat: fetch stage with deterministic sources (county, roads, DEM, NFHL)"
```

---

### Task 5: Endpoint discovery (water, transmission, mined, NLCD)

**Files:**
- Modify: `pipeline/hexbin_pipeline/fetch.py` (the four `None` constants + `fetch_nlcd`)
- Modify: `docs/data-sources.md` (record resolved URLs + discovery date)

This task is investigative by design; the concrete deliverable is four working URLs. For each source, follow the trail in `docs/data-sources.md`:

- [ ] **Step 1: Water** — start at the EPA CWS service-area page (see data-sources.md), find the ArcGIS REST FeatureServer layer (WebFetch/browser the page; EPA GeoPlatform hosts it). Verify with a bbox query returning polygons for Raleigh County. Note the field that distinguishes authoritative vs modeled boundaries — record its name in data-sources.md; `water.py` (Task 8) reads it as `CONF_FIELD`.

- [ ] **Step 2: Transmission** — from https://atlas.eia.gov/, open the transmission-lines item, copy its FeatureServer/0 URL, verify a bbox query returns line features with a voltage field.

- [ ] **Step 3: Mined areas** — list WVDEP TAGIS services: `curl "https://tagis.dep.wv.gov/arcgis/rest/services?f=json"`. Find the underground/abandoned mine lands polygon layer (WVGES mined-out areas is the fallback — data-sources.md). Verify a bbox query returns polygons for Raleigh County (coalfield country — zero features means the wrong layer, not a clean county).

- [ ] **Step 4: NLCD** — determine the live MRLC endpoint for clipped land-cover download (WCS GetCoverage or their REST ImageServer `exportImage` with `f=image&format=tiff`). Implement `fetch_nlcd` accordingly: request the county bbox in EPSG:4326, save GeoTIFF, verify it opens in rasterio with integer class codes (11–95) and covers the county bounds. Replace the `raise RuntimeError` body with the working implementation.

- [ ] **Step 5: Set the four constants in `fetch.py`, run full fetch**

```bash
.venv/Scripts/python.exe -m hexbin_pipeline fetch --fips 54081
```
Expected: all sources print non-zero feature/byte counts; exit 0. Any source returning 0 features must raise, not pass.

- [ ] **Step 6: Record resolved URLs and discovery date in `docs/data-sources.md`, commit**

```bash
git add pipeline/hexbin_pipeline/fetch.py docs/data-sources.md
git commit -m "feat: resolve water/transmission/mined/NLCD endpoints, complete fetch stage"
```

---

### Task 6: Vector measurement helpers (TDD)

**Files:**
- Create: `pipeline/hexbin_pipeline/measure/__init__.py` (stub for now)
- Create: `pipeline/hexbin_pipeline/measure/common.py`
- Test: `pipeline/tests/test_common.py`

- [ ] **Step 1: Create `pipeline/hexbin_pipeline/measure/__init__.py`** containing only a docstring (`"""Measure modules; registry added in Task 8."""`) so imports resolve.

- [ ] **Step 2: Write failing tests `pipeline/tests/test_common.py`**

```python
import geopandas as gpd
import pytest
from shapely.geometry import LineString, box

from hexbin_pipeline.measure.common import UTM, dist_to_nearest, pct_overlap


def test_pct_overlap_full_and_none(seven_cells):
    # Polygon = exact footprint of cell 0 -> that cell ~100%, at least one other cell ~0
    target = seven_cells.iloc[[0]]
    polys = gpd.GeoDataFrame(geometry=[target.geometry.iloc[0]], crs="EPSG:4326")
    pct = pct_overlap(seven_cells, polys)
    assert pct.loc[target.h3_index.iloc[0]] == pytest.approx(100, abs=1)
    assert pct.min() == pytest.approx(0, abs=1)
    assert len(pct) == len(seven_cells)


def test_pct_overlap_empty_polys_returns_zeros(seven_cells):
    empty = gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    pct = pct_overlap(seven_cells, empty)
    assert (pct == 0).all()


def test_dist_to_nearest(seven_cells):
    # Line 1000 m east of cell 0's centroid, in UTM
    cent = seven_cells.iloc[[0]].to_crs(UTM).geometry.centroid.iloc[0]
    line = LineString([(cent.x + 1000, cent.y - 5000), (cent.x + 1000, cent.y + 5000)])
    lines = gpd.GeoDataFrame(geometry=[line], crs=UTM).to_crs("EPSG:4326")
    dist = dist_to_nearest(seven_cells, lines)
    assert dist.loc[seven_cells.h3_index.iloc[0]] == pytest.approx(1000, abs=15)
```

- [ ] **Step 3: Run to verify failure**

```bash
.venv/Scripts/python.exe -m pytest pipeline/tests/test_common.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'hexbin_pipeline.measure.common'`

- [ ] **Step 4: Write `pipeline/hexbin_pipeline/measure/common.py`**

```python
import geopandas as gpd
import pandas as pd

UTM = "EPSG:26917"


def pct_overlap(cells, polys):
    """% of each cell's area covered by the union of polys.

    cells: grid GeoDataFrame (EPSG:4326, h3_index column). polys: any polygon
    GeoDataFrame. Returns Series indexed by h3_index, aligned to cells order.
    Empty polys -> zeros (caller decides whether empty input is legitimate).
    """
    order = cells["h3_index"]
    if polys.empty:
        print("pct_overlap: WARNING — empty polygon input, returning all zeros")
        return pd.Series(0.0, index=pd.Index(order, name="h3_index"))
    cells_m = cells.to_crs(UTM)[["h3_index", "geometry"]]
    polys_m = polys.to_crs(UTM)[["geometry"]].dissolve()  # dissolve: no double-counting overlaps
    inter = gpd.overlay(cells_m, polys_m, how="intersection", keep_geom_type=True)
    cell_area = cells_m.set_index("h3_index").area
    covered = inter.assign(a=inter.area).groupby("h3_index")["a"].sum()
    pct = (covered.reindex(cell_area.index, fill_value=0.0) / cell_area * 100.0)
    return pct.reindex(order)


def dist_to_nearest(cells, features):
    """Meters from each cell centroid to the nearest feature. Series indexed by h3_index."""
    if features.empty:
        raise RuntimeError("dist_to_nearest: empty feature input — a distance criterion "
                           "cannot be measured from nothing; check the fetch output")
    order = cells["h3_index"]
    cents = cells.to_crs(UTM)[["h3_index", "geometry"]].copy()
    cents["geometry"] = cents.geometry.centroid
    feats_m = features.to_crs(UTM)[["geometry"]]
    joined = gpd.sjoin_nearest(cents, feats_m, distance_col="dist_m")
    return joined.drop_duplicates("h3_index").set_index("h3_index")["dist_m"].reindex(order)
```

- [ ] **Step 5: Run tests, verify pass**

```bash
.venv/Scripts/python.exe -m pytest pipeline/tests/test_common.py -v
```
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add pipeline/hexbin_pipeline/measure/__init__.py pipeline/hexbin_pipeline/measure/common.py pipeline/tests/test_common.py
git commit -m "feat: vector measurement helpers (pct_overlap, dist_to_nearest)"
```

---

### Task 7: Raster helpers (TDD)

**Files:**
- Create: `pipeline/hexbin_pipeline/measure/rasters.py`
- Test: `pipeline/tests/test_rasters.py`

- [ ] **Step 1: Write failing tests `pipeline/tests/test_rasters.py`**

```python
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from hexbin_pipeline.measure.common import UTM
from hexbin_pipeline.measure.rasters import build_slope_raster, zonal_majority, zonal_mean, zonal_pct_above


def write_tif(path, arr, transform, crs=UTM, dtype="float32", nodata=None):
    with rasterio.open(path, "w", driver="GTiff", height=arr.shape[0], width=arr.shape[1],
                       count=1, dtype=dtype, crs=crs, transform=transform, nodata=nodata) as dst:
        dst.write(arr.astype(dtype), 1)


def test_slope_of_tilted_plane(tmp_path):
    # 10 m pixels, elevation rises 1 m per pixel eastward -> 10% slope
    arr = np.tile(np.arange(200, dtype="float32"), (200, 1))
    dem = tmp_path / "dem.tif"
    write_tif(dem, arr, from_origin(500000, 4200000, 10, 10))
    out = tmp_path / "slope.tif"
    build_slope_raster([dem], out)
    with rasterio.open(out) as src:
        center = src.read(1)[50:150, 50:150]
    assert np.nanmean(center) == pytest.approx(10.0, rel=0.05)


def test_zonal_helpers(seven_cells, tmp_path):
    cells_m = seven_cells.to_crs(UTM)
    minx, miny, maxx, maxy = cells_m.total_bounds
    w = int((maxx - minx) / 10) + 2
    h = int((maxy - miny) / 10) + 2
    transform = from_origin(minx, maxy, 10, 10)

    const = np.full((h, w), 7.0, dtype="float32")
    tif = tmp_path / "const.tif"
    write_tif(tif, const, transform)
    mean = zonal_mean(seven_cells, tif)
    assert mean.iloc[0] == pytest.approx(7.0, abs=0.01)
    assert (zonal_pct_above(seven_cells, tif, 5) > 99).all()
    assert (zonal_pct_above(seven_cells, tif, 10) < 1).all()

    cats = np.full((h, w), 42, dtype="int16")
    ctif = tmp_path / "cats.tif"
    write_tif(ctif, cats, transform, dtype="int16", nodata=-1)
    assert (zonal_majority(seven_cells, ctif) == 42).all()
```

- [ ] **Step 2: Run to verify failure**

```bash
.venv/Scripts/python.exe -m pytest pipeline/tests/test_rasters.py -v
```
Expected: FAIL — no module `rasters`

- [ ] **Step 3: Write `pipeline/hexbin_pipeline/measure/rasters.py`**

```python
import numpy as np
import pandas as pd
import rasterio
from rasterio.merge import merge
from rasterio.transform import array_bounds
from rasterio.warp import Resampling, calculate_default_transform, reproject
from rasterstats import zonal_stats

from .common import UTM


def build_slope_raster(dem_paths, out_path, res=10.0):
    """Merge DEM tiles, reproject to UTM 17N at `res` m, write slope-percent GeoTIFF."""
    srcs = [rasterio.open(p) for p in dem_paths]
    mosaic, src_transform = merge(srcs)
    src_crs = srcs[0].crs
    src_nodata = srcs[0].nodata
    bounds = array_bounds(mosaic.shape[1], mosaic.shape[2], src_transform)
    dst_transform, w, h = calculate_default_transform(
        src_crs, UTM, mosaic.shape[2], mosaic.shape[1], *bounds, resolution=res)
    dem_utm = np.full((h, w), np.nan, dtype="float32")
    reproject(mosaic[0], dem_utm, src_transform=src_transform, src_crs=src_crs,
              dst_transform=dst_transform, dst_crs=UTM, src_nodata=src_nodata,
              dst_nodata=np.nan, resampling=Resampling.bilinear)
    for s in srcs:
        s.close()
    dy, dx = np.gradient(dem_utm, res)
    slope_pct = (np.hypot(dx, dy) * 100.0).astype("float32")
    with rasterio.open(out_path, "w", driver="GTiff", height=h, width=w, count=1,
                       dtype="float32", crs=UTM, transform=dst_transform,
                       nodata=np.nan, compress="deflate") as dst:
        dst.write(slope_pct, 1)
    print(f"rasters: slope raster {w}x{h} @ {res} m -> {out_path}")
    return out_path


def _cells_in_raster_crs(cells, raster_path):
    with rasterio.open(raster_path) as src:
        crs = src.crs
    return cells.to_crs(crs)


def zonal_mean(cells, raster_path):
    stats = zonal_stats(_cells_in_raster_crs(cells, raster_path).geometry, str(raster_path),
                       stats=["mean"], all_touched=True)
    return pd.Series([s["mean"] for s in stats], index=pd.Index(cells["h3_index"], name="h3_index"))


def zonal_pct_above(cells, raster_path, threshold):
    def pct_above(masked):
        n = masked.count()
        return float((masked > threshold).sum() / n * 100.0) if n else None
    stats = zonal_stats(_cells_in_raster_crs(cells, raster_path).geometry, str(raster_path),
                       stats=["count"], add_stats={"pct_above": pct_above}, all_touched=True)
    return pd.Series([s["pct_above"] for s in stats], index=pd.Index(cells["h3_index"], name="h3_index"))


def zonal_majority(cells, raster_path):
    stats = zonal_stats(_cells_in_raster_crs(cells, raster_path).geometry, str(raster_path),
                       stats=["majority"], categorical=False, all_touched=True)
    return pd.Series([s["majority"] for s in stats], index=pd.Index(cells["h3_index"], name="h3_index"))
```

- [ ] **Step 4: Run tests, verify pass**

```bash
.venv/Scripts/python.exe -m pytest pipeline/tests/test_rasters.py -v
```
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/hexbin_pipeline/measure/rasters.py pipeline/tests/test_rasters.py
git commit -m "feat: raster helpers (slope build, zonal mean/pct/majority)"
```

---

### Task 8: Flood module (TDD) + measure registry

Flood is the template module — fully test-driven. The other six (Tasks 9–10) reuse the same helpers and shape.

**Files:**
- Create: `pipeline/hexbin_pipeline/measure/flood.py`
- Modify: `pipeline/hexbin_pipeline/measure/__init__.py`
- Test: `pipeline/tests/test_flood.py`

- [ ] **Step 1: Write failing test `pipeline/tests/test_flood.py`**

```python
import geopandas as gpd
import pandas as pd

from hexbin_pipeline import paths
from hexbin_pipeline.measure import flood


def test_flood_columns_and_values(seven_cells, tmp_path, monkeypatch):
    fips = "99999"
    monkeypatch.setattr(paths, "RAW", tmp_path / "raw")
    monkeypatch.setattr(paths, "WORK", tmp_path / "work")

    seven_cells.to_parquet(paths.grid_path(fips))
    # AE zone exactly covering cell 0; no floodway anywhere
    nfhl = gpd.GeoDataFrame(
        {"FLD_ZONE": ["AE"], "ZONE_SUBTY": [None]},
        geometry=[seven_cells.geometry.iloc[0]], crs="EPSG:4326")
    nfhl.to_file(paths.raw_dir("nfhl") / f"nfhl_{fips}.geojson", driver="GeoJSON")

    dest = flood.run(fips)
    out = pd.read_parquet(dest)
    assert list(out.columns) == ["h3_index", "flood_pct_a_ae", "floodway_pct"]
    assert len(out) == 7
    row0 = out[out.h3_index == seven_cells.h3_index.iloc[0]].iloc[0]
    assert row0.flood_pct_a_ae > 95
    assert (out.floodway_pct == 0).all()
```

- [ ] **Step 2: Run to verify failure**

```bash
.venv/Scripts/python.exe -m pytest pipeline/tests/test_flood.py -v
```
Expected: FAIL — no module `flood`

- [ ] **Step 3: Write `pipeline/hexbin_pipeline/measure/flood.py`**

```python
import geopandas as gpd
import pandas as pd

from .. import paths
from .common import pct_overlap


def run(fips):
    cells = gpd.read_parquet(paths.grid_path(fips))
    nfhl = gpd.read_file(paths.raw_dir("nfhl") / f"nfhl_{fips}.geojson")
    a_ae = nfhl[nfhl["FLD_ZONE"].isin(["A", "AE"])]
    floodway = nfhl[nfhl["ZONE_SUBTY"].fillna("").str.upper().str.contains("FLOODWAY")]
    print(f"flood: {len(nfhl)} NFHL polys, {len(a_ae)} A/AE, {len(floodway)} floodway")
    out = pd.DataFrame({
        "h3_index": cells["h3_index"],
        "flood_pct_a_ae": pct_overlap(cells, a_ae).values,
        "floodway_pct": pct_overlap(cells, floodway).values,
    })
    dest = paths.work_dir(fips) / "measure_flood.parquet"
    out.to_parquet(dest, index=False)
    print(f"flood: wrote {len(out)} rows -> {dest}")
    return dest
```

Constraint: measure modules must call path helpers through the module (`paths.raw_dir(...)`), never `from ..paths import raw_dir`. Tests redirect data directories by monkeypatching `paths.RAW` / `paths.WORK`, which only works when the helpers are resolved on the `paths` module at call time. This applies to every measure module in Tasks 9–10 as well.

- [ ] **Step 4: Write the registry in `pipeline/hexbin_pipeline/measure/__init__.py`**

```python
"""Measure modules: each exposes run(fips) -> Path writing measure_<name>.parquet."""


def run_all(fips, only=None):
    from . import flood, landcover, mined, roads, slope, transmission, water
    modules = {"slope": slope, "flood": flood, "water": water, "roads": roads,
               "transmission": transmission, "mined": mined, "landcover": landcover}
    if only:
        if only not in modules:
            raise SystemExit(f"unknown measure module '{only}'; choose from {sorted(modules)}")
        modules = {only: modules[only]}
    for name, mod in modules.items():
        print(f"=== measure: {name} ===")
        mod.run(fips)
```

(The import inside `run_all` will fail until Tasks 9–10 create the remaining modules — that is expected; `--only flood` still cannot run until then. Test the flood module through pytest for now.)

- [ ] **Step 5: Run tests, verify pass**

```bash
.venv/Scripts/python.exe -m pytest pipeline/tests/test_flood.py -v
```
Expected: PASS (1 test)

- [ ] **Step 6: Commit**

```bash
git add pipeline/hexbin_pipeline/measure/flood.py pipeline/hexbin_pipeline/measure/__init__.py pipeline/tests/test_flood.py
git commit -m "feat: flood measure module and measure registry"
```

---

### Task 9: Polygon + point-in-polygon modules (water, mined)

Same shape as flood; helpers are already tested, so these get real-data smoke runs instead of new unit tests.

**Files:**
- Create: `pipeline/hexbin_pipeline/measure/water.py`
- Create: `pipeline/hexbin_pipeline/measure/mined.py`

- [ ] **Step 1: Write `pipeline/hexbin_pipeline/measure/mined.py`**

```python
import geopandas as gpd
import pandas as pd

from .. import paths
from .common import pct_overlap


def run(fips):
    cells = gpd.read_parquet(paths.grid_path(fips))
    mined = gpd.read_file(paths.raw_dir("mined") / f"mined_{fips}.geojson")
    print(f"mined: {len(mined)} mining polygons")
    out = pd.DataFrame({
        "h3_index": cells["h3_index"],
        "mined_pct": pct_overlap(cells, mined).values,
    })
    dest = paths.work_dir(fips) / "measure_mined.parquet"
    out.to_parquet(dest, index=False)
    print(f"mined: wrote {len(out)} rows -> {dest}")
    return dest
```

- [ ] **Step 2: Write `pipeline/hexbin_pipeline/measure/water.py`**

`CONF_FIELD` is the authoritative-vs-modeled attribute identified during Task 5 endpoint discovery — set the constant from what data-sources.md now records.

```python
import geopandas as gpd
import pandas as pd

from .. import paths
from .common import UTM

CONF_FIELD = "SET_FROM_TASK5_DISCOVERY"  # e.g. "Method" — see docs/data-sources.md


def run(fips):
    cells = gpd.read_parquet(paths.grid_path(fips))
    cws = gpd.read_file(paths.raw_dir("water") / f"water_{fips}.geojson")
    if CONF_FIELD not in cws.columns:
        raise RuntimeError(f"water: confidence field '{CONF_FIELD}' not in CWS attributes "
                           f"{list(cws.columns)} — fix CONF_FIELD per docs/data-sources.md")
    print(f"water: {len(cws)} CWS polygons")
    cents = cells.to_crs(UTM)[["h3_index", "geometry"]].copy()
    cents["geometry"] = cents.geometry.centroid
    joined = gpd.sjoin(cents, cws.to_crs(UTM)[["geometry", CONF_FIELD]],
                       how="left", predicate="within").drop_duplicates("h3_index")
    out = pd.DataFrame({
        "h3_index": joined["h3_index"].values,
        "water_in_service": joined[CONF_FIELD].notna().astype("int8").values,
        "water_conf": joined[CONF_FIELD].fillna("none").astype(str).values,
    })
    dest = paths.work_dir(fips) / "measure_water.parquet"
    out.to_parquet(dest, index=False)
    print(f"water: wrote {len(out)} rows, {out.water_in_service.mean():.1%} in service -> {dest}")
    return dest
```

- [ ] **Step 3: Smoke-run both on real data** (Tasks 4–5 fetch and grid must be complete)

```bash
.venv/Scripts/python.exe -c "from hexbin_pipeline.measure import mined, water; mined.run('54081'); water.run('54081')"
```
Expected: both print row counts equal to the grid cell count; mined coverage is nonzero (Raleigh is coal country); water in-service fraction is plausibly 20–70%. All-zero mined or 0%/100% water → stop and investigate the source filter.

- [ ] **Step 4: Commit**

```bash
git add pipeline/hexbin_pipeline/measure/water.py pipeline/hexbin_pipeline/measure/mined.py
git commit -m "feat: water and mined measure modules"
```

---

### Task 10: Distance + raster modules (roads, transmission, slope, landcover)

**Files:**
- Create: `pipeline/hexbin_pipeline/measure/roads.py`
- Create: `pipeline/hexbin_pipeline/measure/transmission.py`
- Create: `pipeline/hexbin_pipeline/measure/slope.py`
- Create: `pipeline/hexbin_pipeline/measure/landcover.py`

- [ ] **Step 1: Write `roads.py`**

```python
import geopandas as gpd
import pandas as pd

from .. import paths
from .common import dist_to_nearest

# TIGER MTFCC: S1100 primary, S1200 secondary. MVP measures distance to improved
# roads only — functional-class weighting is a post-MVP refinement (spec).
IMPROVED = {"S1100", "S1200", "S1400"}


def run(fips):
    cells = gpd.read_parquet(paths.grid_path(fips))
    roads = gpd.read_file(paths.raw_dir("roads") / f"roads_{fips}.zip")
    improved = roads[roads["MTFCC"].isin(IMPROVED)]
    print(f"roads: {len(roads)} segments, {len(improved)} improved (MTFCC {sorted(IMPROVED)})")
    out = pd.DataFrame({
        "h3_index": cells["h3_index"],
        "road_dist_m": dist_to_nearest(cells, improved).values,
    })
    dest = paths.work_dir(fips) / "measure_roads.parquet"
    out.to_parquet(dest, index=False)
    print(f"roads: wrote {len(out)} rows, median dist {out.road_dist_m.median():.0f} m -> {dest}")
    return dest
```

- [ ] **Step 2: Write `transmission.py`** — identical shape:

```python
import geopandas as gpd
import pandas as pd

from .. import paths
from .common import dist_to_nearest


def run(fips):
    cells = gpd.read_parquet(paths.grid_path(fips))
    lines = gpd.read_file(paths.raw_dir("transmission") / f"transmission_{fips}.geojson")
    print(f"transmission: {len(lines)} line features")
    out = pd.DataFrame({
        "h3_index": cells["h3_index"],
        "transmission_dist_m": dist_to_nearest(cells, lines).values,
    })
    dest = paths.work_dir(fips) / "measure_transmission.parquet"
    out.to_parquet(dest, index=False)
    print(f"transmission: wrote {len(out)} rows, median dist {out.transmission_dist_m.median():.0f} m -> {dest}")
    return dest
```

Note: the fetch bbox clips transmission lines at the county envelope, so distances near the envelope edge are upper bounds. Acceptable for MVP screening; noted here so nobody debugs it as an error later.

- [ ] **Step 3: Write `slope.py`**

```python
import geopandas as gpd
import pandas as pd

from .. import paths
from .rasters import build_slope_raster, zonal_mean, zonal_pct_above


def run(fips):
    cells = gpd.read_parquet(paths.grid_path(fips))
    dems = sorted(paths.raw_dir("dem").glob("USGS_13_*.tif"))
    if not dems:
        raise RuntimeError("slope: no DEM tiles in data/raw/dem — run the fetch stage")
    slope_tif = paths.work_dir(fips) / "slope_pct.tif"
    if not slope_tif.exists():
        build_slope_raster(dems, slope_tif)
    out = pd.DataFrame({
        "h3_index": cells["h3_index"],
        "slope_mean_pct": zonal_mean(cells, slope_tif).values,
        "slope_pct_gt15": zonal_pct_above(cells, slope_tif, 15).values,
    })
    dest = paths.work_dir(fips) / "measure_slope.parquet"
    out.to_parquet(dest, index=False)
    print(f"slope: wrote {len(out)} rows, county mean slope {out.slope_mean_pct.mean():.1f}% -> {dest}")
    return dest
```

- [ ] **Step 4: Write `landcover.py`**

```python
import geopandas as gpd
import pandas as pd

from .. import paths
from .rasters import zonal_majority


def run(fips):
    cells = gpd.read_parquet(paths.grid_path(fips))
    tif = paths.raw_dir("nlcd") / f"nlcd_{fips}.tif"
    if not tif.exists():
        raise RuntimeError("landcover: missing NLCD raster — run the fetch stage")
    mode = zonal_majority(cells, tif)
    out = pd.DataFrame({
        "h3_index": cells["h3_index"],
        "nlcd_mode": pd.array(mode.values, dtype="Int16"),
    })
    dest = paths.work_dir(fips) / "measure_landcover.parquet"
    out.to_parquet(dest, index=False)
    print(f"landcover: wrote {len(out)} rows, classes {sorted(out.nlcd_mode.dropna().unique())} -> {dest}")
    return dest
```

- [ ] **Step 5: Run the full measure stage on real data**

```bash
.venv/Scripts/python.exe -m hexbin_pipeline measure --fips 54081
```
Expected: all 7 modules print row counts equal to grid cell count. Slope raster build is the slow step (minutes). Sanity: mean slope well above 10% (this is WV), NLCD classes dominated by 41/42/43 (forest).

- [ ] **Step 6: Run whole test suite, then commit**

```bash
.venv/Scripts/python.exe -m pytest pipeline/tests -v
```
Expected: all tests pass.

```bash
git add pipeline/hexbin_pipeline/measure/roads.py pipeline/hexbin_pipeline/measure/transmission.py pipeline/hexbin_pipeline/measure/slope.py pipeline/hexbin_pipeline/measure/landcover.py
git commit -m "feat: roads, transmission, slope, landcover measure modules"
```

---

### Task 11: Parcels + crosswalk (TDD)

**Files:**
- Create: `pipeline/hexbin_pipeline/parcels.py`
- Create: `pipeline/hexbin_pipeline/xwalk.py`
- Test: `pipeline/tests/test_xwalk.py`

- [ ] **Step 1: Inspect the statewide parcel GDB** (already on disk)

```bash
mkdir -p data/raw/parcels
# Extract once; never modify in place
.venv/Scripts/python.exe -c "import zipfile; zipfile.ZipFile('<download-dir>/WV_WVGISTC_Tax_2025.gdb.zip').extractall('data/raw/parcels')"
.venv/Scripts/python.exe -c "import pyogrio, pathlib; gdb = next(pathlib.Path('data/raw/parcels').glob('*.gdb')); print(gdb); print(pyogrio.list_layers(gdb)); import geopandas as gpd; df = gpd.read_file(gdb, rows=5); print(df.columns.tolist()); print(df.head())"
```
From the output, record in a comment at the top of `parcels.py`: the layer name, the county-filter field + Raleigh's value (county code or name — data-sources.md says the parcel ID starts with a county code), and which ID field is unique (prefer `CleanParcelID`, fall back to `GISPID`).

- [ ] **Step 2: Write failing test `pipeline/tests/test_xwalk.py`** (tests the geometry logic, not the GDB read)

```python
import geopandas as gpd
import pytest
from shapely.ops import unary_union

from hexbin_pipeline.xwalk import build_xwalk


def test_overlap_fracs_sum_to_one(seven_cells):
    # Parcel = union of cells 0 and 1 -> two xwalk rows, fracs ~0.5 each, sum ~1
    parcel_geom = unary_union([seven_cells.geometry.iloc[0], seven_cells.geometry.iloc[1]])
    parcels = gpd.GeoDataFrame({"parcel_id": ["P1"]}, geometry=[parcel_geom], crs="EPSG:4326")
    xw = build_xwalk(seven_cells, parcels)
    assert set(xw.columns) == {"parcel_id", "h3_index", "overlap_frac"}
    p1 = xw[xw.parcel_id == "P1"]
    assert len(p1) == 2
    assert p1.overlap_frac.sum() == pytest.approx(1.0, abs=0.01)
    assert p1.overlap_frac.min() == pytest.approx(0.5, abs=0.05)
```

- [ ] **Step 3: Run to verify failure**

```bash
.venv/Scripts/python.exe -m pytest pipeline/tests/test_xwalk.py -v
```
Expected: FAIL — no module `xwalk`

- [ ] **Step 4: Write `pipeline/hexbin_pipeline/xwalk.py`**

```python
import geopandas as gpd

from . import paths
from .measure.common import UTM


def build_xwalk(cells, parcels):
    """parcel_id, h3_index, overlap_frac — fraction of the parcel's area in each cell."""
    cells_m = cells.to_crs(UTM)[["h3_index", "geometry"]]
    parcels_m = parcels.to_crs(UTM)[["parcel_id", "geometry"]]
    parcel_area = parcels_m.set_index("parcel_id").area
    inter = gpd.overlay(parcels_m, cells_m, how="intersection", keep_geom_type=True)
    inter["overlap_frac"] = inter.area / inter["parcel_id"].map(parcel_area)
    return inter[["parcel_id", "h3_index", "overlap_frac"]].reset_index(drop=True)


def run(fips):
    from .parcels import load_county_parcels
    cells = gpd.read_parquet(paths.grid_path(fips))
    parcels = load_county_parcels(fips)
    xw = build_xwalk(cells, parcels)
    covered = xw["parcel_id"].nunique()
    print(f"xwalk: {len(xw)} rows, {covered}/{len(parcels)} parcels have >=1 cell")
    dest = paths.work_dir(fips) / "parcel_cell_xwalk.parquet"
    xw.to_parquet(dest, index=False)

    # Parcel attribute + geometry outputs
    attrs = parcels.drop(columns="geometry")
    attrs.to_parquet(paths.work_dir(fips) / "parcels.parquet", index=False)
    simplified = parcels.to_crs(UTM)
    simplified["geometry"] = simplified.geometry.simplify(5)
    simplified.to_crs("EPSG:4326").to_file(paths.work_dir(fips) / "parcels.geojson", driver="GeoJSON")
    print(f"xwalk: wrote parcels.parquet ({len(attrs)} rows) and parcels.geojson")
    return dest
```

- [ ] **Step 5: Write `pipeline/hexbin_pipeline/parcels.py`** using the Step-1 findings (constants below are examples — set them from the actual inspection output):

```python
import geopandas as gpd
from pathlib import Path

from . import paths

# From GDB inspection (Task 11 Step 1) — adjust to actual layer/field names:
PARCEL_LAYER = "SET_FROM_INSPECTION"
COUNTY_FIELD = "SET_FROM_INSPECTION"
COUNTY_VALUE = {"54081": "SET_FROM_INSPECTION"}  # Raleigh's code/name in that field
ID_FIELD = "SET_FROM_INSPECTION"                  # CleanParcelID preferred, GISPID fallback
KEEP_FIELDS = ["SET_FROM_INSPECTION"]             # owner, acreage, district, etc.


def load_county_parcels(fips):
    gdb = next(Path(paths.raw_dir("parcels")).glob("*.gdb"))
    parcels = gpd.read_file(gdb, layer=PARCEL_LAYER,
                            where=f"{COUNTY_FIELD} = '{COUNTY_VALUE[fips]}'")
    if parcels.empty:
        raise RuntimeError(f"parcels: 0 features for {COUNTY_FIELD}={COUNTY_VALUE[fips]} — "
                           f"wrong filter value; re-run the inspection step")
    parcels = parcels.rename(columns={ID_FIELD: "parcel_id"})
    if not parcels["parcel_id"].is_unique:
        raise RuntimeError(f"parcels: {ID_FIELD} is not unique within county {fips} "
                           f"({parcels['parcel_id'].duplicated().sum()} dupes) — pick another ID field")
    keep = ["parcel_id"] + [f for f in KEEP_FIELDS if f in parcels.columns] + ["geometry"]
    parcels = parcels[keep]
    print(f"parcels: {len(parcels)} parcels for {fips}")
    return parcels
```

- [ ] **Step 6: Run tests, then the real xwalk stage**

```bash
.venv/Scripts/python.exe -m pytest pipeline/tests/test_xwalk.py -v
.venv/Scripts/python.exe -m hexbin_pipeline xwalk --fips 54081
```
Expected: test PASS; real run prints parcel count (tens of thousands for Raleigh), coverage near 100%, writes three files to `data/work/54081/`.

- [ ] **Step 7: Commit**

```bash
git add pipeline/hexbin_pipeline/parcels.py pipeline/hexbin_pipeline/xwalk.py pipeline/tests/test_xwalk.py
git commit -m "feat: county parcel extraction and parcel-cell crosswalk"
```

---

### Task 12: Validate stage (TDD)

**Files:**
- Create: `pipeline/hexbin_pipeline/validate.py`
- Test: `pipeline/tests/test_validate.py`

- [ ] **Step 1: Write failing tests `pipeline/tests/test_validate.py`**

```python
import geopandas as gpd
import pandas as pd
import pytest

from hexbin_pipeline import paths, validate


@pytest.fixture
def staged(seven_cells, tmp_path, monkeypatch):
    fips = "99999"
    monkeypatch.setattr(paths, "WORK", tmp_path / "work")
    monkeypatch.setattr(paths, "PROCESSED", tmp_path / "processed")
    seven_cells.to_parquet(paths.grid_path(fips))
    idx = seven_cells["h3_index"]
    full = pd.DataFrame({
        "h3_index": idx, "slope_mean_pct": 12.0, "slope_pct_gt15": 30.0,
        "flood_pct_a_ae": 0.0, "floodway_pct": 0.0, "water_in_service": 1,
        "water_conf": "authoritative", "road_dist_m": 500.0,
        "transmission_dist_m": 2000.0, "mined_pct": 0.0, "nlcd_mode": 41,
    })
    full.to_parquet(paths.work_dir(fips) / "measure_all.parquet", index=False)
    pd.DataFrame({"parcel_id": ["P1"], "h3_index": [idx.iloc[0]], "overlap_frac": [1.0]}) \
        .to_parquet(paths.work_dir(fips) / "parcel_cell_xwalk.parquet", index=False)
    pd.DataFrame({"parcel_id": ["P1"]}).to_parquet(paths.work_dir(fips) / "parcels.parquet", index=False)
    (paths.work_dir(fips) / "parcels.geojson").write_text('{"type":"FeatureCollection","features":[]}')
    return fips


def test_clean_run_publishes(staged):
    validate.run(staged)
    out = pd.read_parquet(paths.processed_dir(staged) / "cells_r10.parquet")
    assert len(out) == 7
    assert "slope_mean_pct" in out.columns and "h3_r8" in out.columns


def test_missing_column_halts(staged):
    p = paths.work_dir(staged) / "measure_all.parquet"
    pd.read_parquet(p).drop(columns=["mined_pct"]).to_parquet(p, index=False)
    with pytest.raises(SystemExit):
        validate.run(staged)


def test_excess_nulls_halt(staged):
    p = paths.work_dir(staged) / "measure_all.parquet"
    df = pd.read_parquet(p)
    df.loc[:, "road_dist_m"] = None
    df.to_parquet(p, index=False)
    with pytest.raises(SystemExit):
        validate.run(staged)
```

- [ ] **Step 2: Run to verify failure**

```bash
.venv/Scripts/python.exe -m pytest pipeline/tests/test_validate.py -v
```
Expected: FAIL — no module `validate`

- [ ] **Step 3: Write `pipeline/hexbin_pipeline/validate.py`**

```python
import json
import shutil

import geopandas as gpd
import pandas as pd

from . import paths

MAX_NULL_FRAC = 0.01
MAX_UNCOVERED_PARCEL_FRAC = 0.005


def run(fips):
    problems = []
    grid = gpd.read_parquet(paths.grid_path(fips))
    cells = grid[["h3_index", "h3_r9", "h3_r8"]].copy()

    measure_files = sorted(paths.work_dir(fips).glob("measure_*.parquet"))
    if not measure_files:
        raise SystemExit("validate: no measure_*.parquet files — run the measure stage")
    for p in measure_files:
        df = pd.read_parquet(p)
        before = len(cells)
        cells = cells.merge(df, on="h3_index", how="left", validate="one_to_one")
        print(f"validate: joined {p.name} ({len(df)} rows, {len(df.columns) - 1} columns)")
        if len(cells) != before:
            problems.append(f"{p.name}: join changed row count {before} -> {len(cells)}")

    registry = json.loads(paths.CRITERIA.read_text())
    expected = ({c["column"] for c in registry["criteria"]}
                | {m["column"] for m in registry["masks"]})
    missing = expected - set(cells.columns)
    if missing:
        problems.append(f"columns in criteria.json but not measured: {sorted(missing)}")

    for col in cells.columns.drop(["h3_index", "h3_r9", "h3_r8"]):
        frac = cells[col].isna().mean()
        if frac > MAX_NULL_FRAC:
            problems.append(f"{col}: {frac:.1%} null (max {MAX_NULL_FRAC:.0%})")

    xw_path = paths.work_dir(fips) / "parcel_cell_xwalk.parquet"
    pq_path = paths.work_dir(fips) / "parcels.parquet"
    gj_path = paths.work_dir(fips) / "parcels.geojson"
    for p in (xw_path, pq_path, gj_path):
        if not p.exists() or p.stat().st_size == 0:
            problems.append(f"missing or empty artifact: {p.name}")
    if xw_path.exists() and pq_path.exists():
        xw = pd.read_parquet(xw_path)
        parcels = pd.read_parquet(pq_path)
        uncovered = 1 - xw["parcel_id"].nunique() / max(len(parcels), 1)
        if uncovered > MAX_UNCOVERED_PARCEL_FRAC:
            problems.append(f"{uncovered:.1%} of parcels have no cells (max {MAX_UNCOVERED_PARCEL_FRAC:.1%})")
        bad_frac = xw[(xw.overlap_frac <= 0) | (xw.overlap_frac > 1.001)]
        if len(bad_frac):
            problems.append(f"{len(bad_frac)} xwalk rows with overlap_frac outside (0, 1]")

    if problems:
        print("validate: FAILED — artifacts NOT published:")
        for p in problems:
            print(f"  - {p}")
        raise SystemExit(1)

    out = paths.processed_dir(fips)
    cells.to_parquet(out / "cells_r10.parquet", index=False)
    shutil.copy2(xw_path, out / "parcel_cell_xwalk.parquet")
    shutil.copy2(pq_path, out / "parcels.parquet")
    shutil.copy2(gj_path, out / "parcels.geojson")
    print(f"validate: OK — {len(cells)} cells, {len(cells.columns)} columns published to {out}")
```

- [ ] **Step 4: Run tests, verify pass**

```bash
.venv/Scripts/python.exe -m pytest pipeline/tests/test_validate.py -v
```
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/hexbin_pipeline/validate.py pipeline/tests/test_validate.py
git commit -m "feat: validate stage — hard gate before publishing artifacts"
```

---

### Task 13: Full county run + provenance

**Files:**
- Modify: `docs/data-sources.md` (run log)
- Modify: `CLAUDE.md` (pipeline run commands)

- [ ] **Step 1: Full pipeline end-to-end** (fetch/grid/measure already ran — `all` verifies idempotent skip + runs xwalk/validate fresh)

```bash
.venv/Scripts/python.exe -m hexbin_pipeline all --fips 54081
```
Expected: fetch prints "already present, skipping" lines; validate ends `validate: OK — ... published to data/processed/54081`.

- [ ] **Step 2: Eyeball the published artifacts with DuckDB**

```bash
.venv/Scripts/python.exe -c "import duckdb; con = duckdb.connect(); print(con.sql(\"SELECT count(*) cells, avg(slope_mean_pct) slope, avg(water_in_service) water, avg(mined_pct) mined FROM 'data/processed/54081/cells_r10.parquet'\")); print(con.sql(\"SELECT count(*) FROM 'data/processed/54081/parcel_cell_xwalk.parquet'\"))"
```
Expected: plausible county-level numbers (steep mean slope, nonzero mined). Record the summary numbers in `docs/data-sources.md` under a "54081 run log" heading with today's date.

- [ ] **Step 3: Full test suite green**

```bash
.venv/Scripts/python.exe -m pytest pipeline/tests -v
```
Expected: all tests pass.

- [ ] **Step 4: Add a "Commands" section to `CLAUDE.md`**

```markdown
## Commands

- Pipeline env: `.venv/Scripts/python.exe` (repo-root venv; `pip install -e pipeline`)
- Run a stage: `.venv/Scripts/python.exe -m hexbin_pipeline <fetch|grid|measure|xwalk|validate|all> --fips 54081`
- Single measure module: `... measure --fips 54081 --only slope`
- Tests: `.venv/Scripts/python.exe -m pytest pipeline/tests -v`
```

- [ ] **Step 5: Commit**

```bash
git add docs/data-sources.md CLAUDE.md
git commit -m "docs: 54081 run log and pipeline commands"
```

---

## Out of scope for this plan (Plan 2: browser app)

Vite + React + TS app, `buildScoreQuery`, membership-function SQL, WeightPanel/MapView/RankTable, CSV/GeoJSON export, vitest golden test. Planned after this plan's artifacts exist.
