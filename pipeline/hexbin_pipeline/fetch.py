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


def _query(layer_url, params):
    """POST a /query request (POST avoids URL-length limits with objectId lists)."""
    r = requests.post(f"{layer_url}/query", data=params, timeout=TIMEOUT)
    r.raise_for_status()
    page = r.json()
    if "error" in page:
        raise RuntimeError(f"fetch: {layer_url} error: {page['error']} — check the endpoint")
    return page


def fetch_arcgis_layer(layer_url, dest, where="1=1", bbox_4326=None, chunk=200):
    """Fetch an ArcGIS REST layer to GeoJSON, chunked by OBJECTID.

    Chunked-by-id (not resultOffset paging) because some servers (FEMA NFHL)
    crash outright — HTTP 500 or connection reset — when a response page
    includes certain very large polygons. Failing chunks are bisected to
    isolate poison features; a single poison feature is retried with light
    server-side generalization before giving up loudly.
    """
    if dest.exists() and dest.stat().st_size > 0:
        print(f"fetch: {dest.name} already present, skipping")
        return dest
    spatial = {}
    if bbox_4326:
        spatial = {"geometry": ",".join(str(v) for v in bbox_4326),
                   "geometryType": "esriGeometryEnvelope", "inSR": 4326,
                   "spatialRel": "esriSpatialRelIntersects"}
    ids_resp = _query(layer_url, {"where": where, "returnIdsOnly": "true", "f": "json", **spatial})
    ids = ids_resp.get("objectIds") or []
    if not ids:
        raise RuntimeError(f"fetch: 0 features from {layer_url} where={where} — wrong layer, "
                           f"wrong filter, or moved endpoint (see docs/data-sources.md)")
    print(f"fetch: {dest.name}: {len(ids)} feature ids to retrieve")

    features = []

    def fetch_ids(id_batch, tolerance=None):
        params = {"objectIds": ",".join(str(i) for i in id_batch), "outFields": "*",
                  "outSR": 4326, "f": "geojson"}
        if tolerance is not None:
            params["maxAllowableOffset"] = tolerance
        try:
            page = _query(layer_url, params)
        except requests.exceptions.RequestException as exc:
            if len(id_batch) > 1:
                mid = len(id_batch) // 2
                fetch_ids(id_batch[:mid], tolerance)
                fetch_ids(id_batch[mid:], tolerance)
                return
            if tolerance is None:
                # One poison feature: retry once with ~1 m generalization,
                # negligible at res-10 cell scale (~120 m across)
                print(f"fetch: {dest.name}: objectid {id_batch[0]} failed raw, "
                      f"retrying generalized")
                fetch_ids(id_batch, tolerance=0.00001)
                return
            raise RuntimeError(f"fetch: {layer_url} objectid {id_batch[0]} unfetchable "
                               f"even generalized ({exc}) — investigate before proceeding; "
                               f"a silently missing feature would skew measurements") from exc
        features.extend(page.get("features", []))

    for i in range(0, len(ids), chunk):
        fetch_ids(ids[i:i + chunk])
        print(f"fetch: {dest.name}: {len(features)}/{len(ids)} features")

    if len(features) != len(ids):
        raise RuntimeError(f"fetch: {dest.name}: retrieved {len(features)} features but server "
                           f"listed {len(ids)} ids — partial download, not writing output")
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
