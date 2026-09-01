import json
import math

import requests

from .paths import raw_dir

TIMEOUT = 120
GENERALIZE_TOLERANCE_DEG = 0.00001  # ~1 m at this latitude; only used in EPSG:4326 requests

# Verified deterministic sources.
COUNTY_URL = "https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_county_500k.zip"
ROADS_URL = "https://www2.census.gov/geo/tiger/TIGER2024/ROADS/tl_2024_{fips}_roads.zip"
DEM_URL = "https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/13/TIFF/current/{t}/USGS_13_{t}.tif"
NFHL_LAYER = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28"

# Resolved by Task 5 endpoint discovery (2026-09-01). Provenance, verified
# feature counts and field-level caveats are in docs/data-sources.md.
WATER_LAYER = ("https://services.arcgis.com/cJ9YHowT8TU7DUyn/arcgis/rest/services/"
               "Water_System_Boundaries/FeatureServer/0")
TRANSMISSION_LAYER = ("https://services2.arcgis.com/FiaPA4ga0iQKduv3/arcgis/rest/services/"
                      "US_Electric_Power_Transmission_Lines/FeatureServer/0")
MINED_LAYER = ("https://tagis.dep.wv.gov/arcgis/rest/services/WVDEP_enterprise/"
               "mining_reclamation/MapServer/10")  # "underground mining limits" polygons
# Despite the name this is an Esri ImageServer (exportImage), not an OGC WCS —
# MRLC publishes Annual NLCD through geoserver WMS and this ImageServer, and only
# the ImageServer returns a clipped thematic GeoTIFF in one request.
NLCD_WCS = ("https://di-nlcd.img.arcgis.com/arcgis/rest/services/"
            "USA_NLCD_Annual_LandCover/ImageServer")

NLCD_YEAR = 2024      # latest slice in the 1985-2024 annual mosaic
NLCD_RES_M = 30       # native NLCD cell size; requesting anything else resamples classes
NLCD_SR = 5070        # NAD83 / Conus Albers — NLCD's native projection, square metre pixels
NLCD_MAX_PX = 20000   # service maxImageWidth/maxImageHeight
# NLCD legend codes (0 = outside-CONUS nodata). Anything else means the service
# handed back a rendered RGB image rather than the thematic raster.
NLCD_CLASSES = {11, 12, 21, 22, 23, 24, 31, 41, 42, 43, 51, 52,
                71, 72, 73, 74, 81, 82, 90, 95}


def download_file(url, dest):
    if dest.exists() and dest.stat().st_size > 0:
        print(f"fetch: {dest.name} already present ({dest.stat().st_size:,} bytes), skipping")
        return dest
    print(f"fetch: GET {url}")
    r = requests.get(url, timeout=TIMEOUT, stream=True)
    r.raise_for_status()
    tmp = dest.with_suffix(dest.suffix + ".part")
    with open(tmp, "wb") as f:
        for block in r.iter_content(1 << 20):
            f.write(block)
    if tmp.stat().st_size == 0:
        tmp.unlink()
        raise RuntimeError(f"fetch: {url} returned an empty file — check the endpoint "
                           f"(see docs/data-sources.md)")
    tmp.replace(dest)  # replace, not rename: a stale zero-byte dest must not crash the retry
    print(f"fetch: wrote {dest} ({dest.stat().st_size:,} bytes)")
    return dest


def _query(layer_url, params):
    """POST a /query request (POST avoids URL-length limits with objectId lists)."""
    r = requests.post(f"{layer_url}/query", data=params, timeout=TIMEOUT)
    r.raise_for_status()
    page = r.json()
    if "error" in page:
        raise RuntimeError(f"fetch: {layer_url} error: {page['error']} — check the endpoint "
                           f"(see docs/data-sources.md)")
    return page


def fetch_arcgis_layer(layer_url, dest, where="1=1", bbox_4326=None, chunk=200):
    """Fetch an ArcGIS REST layer to GeoJSON, chunked by OBJECTID.

    Chunked-by-id (not resultOffset paging) because some servers (FEMA NFHL)
    crash outright — HTTP 500 or connection reset — when a response page
    includes certain very large polygons. Every failing chunk is retried once
    before anything else, so a transient network blip costs one retry instead
    of a full bisection; only a chunk that fails twice is bisected to isolate
    poison features. A single poison feature is then retried with light
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

    def fetch_ids(id_batch, tolerance=None, retried=False):
        params = {"objectIds": ",".join(str(i) for i in id_batch), "outFields": "*",
                  "outSR": 4326, "f": "geojson"}
        if tolerance is not None:
            params["maxAllowableOffset"] = tolerance
        try:
            page = _query(layer_url, params)
        # RuntimeError included: servers can report the same poison-feature
        # failure in-band ({"error": ...} with HTTP 200) instead of dropping
        # the connection, and it must trigger the same bisection path
        except (requests.exceptions.RequestException, RuntimeError) as exc:
            if not retried:
                fetch_ids(id_batch, tolerance, retried=True)  # absorb transient blips
                return
            if len(id_batch) > 1:
                mid = len(id_batch) // 2
                print(f"fetch: {dest.name}: batch of {len(id_batch)} failed twice, bisecting")
                fetch_ids(id_batch[:mid], tolerance)
                fetch_ids(id_batch[mid:], tolerance)
                return
            if tolerance is None:
                # One poison feature: retry with ~1 m generalization,
                # negligible at res-10 cell scale (~120 m across)
                print(f"fetch: {dest.name}: objectid {id_batch[0]} failed raw, "
                      f"retrying generalized")
                fetch_ids(id_batch, tolerance=GENERALIZE_TOLERANCE_DEG)
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
    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    tmp.replace(dest)
    print(f"fetch: wrote {len(features)} features -> {dest}")
    return dest


def dem_tiles(bounds):
    """1-degree n##w### tile names covering (minx, miny, maxx, maxy) in EPSG:4326."""
    minx, miny, maxx, maxy = bounds
    return sorted({f"n{lat + 1:02d}w{abs(lon):03d}"
                   for lat in range(math.floor(miny), math.ceil(maxy))
                   for lon in range(math.floor(minx), math.ceil(maxx))})


def load_county(fips):
    """Single-row GeoDataFrame for the county, from the cached TIGER boundary file.

    Shared by the fetch and grid stages so the two cannot disagree about which
    row is "the county" or report a missing GEOID differently.
    """
    import geopandas as gpd  # local: keeps the network helpers importable without the geo stack
    path = raw_dir("county") / "counties.zip"
    counties = gpd.read_file(path)
    county = counties[counties["GEOID"] == fips]
    if len(county) != 1:
        raise RuntimeError(f"expected exactly 1 county with GEOID={fips}, found {len(county)} "
                           f"in {path}")
    return county


def county_bounds(fips):
    return tuple(load_county(fips).total_bounds)  # (minx, miny, maxx, maxy)


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
    """Clipped NLCD annual land cover GeoTIFF for the county bbox.

    Requested in EPSG:5070 rather than 4326 so pixels stay square 30 m cells on
    NLCD's own grid; a 4326 request would return degree-sized pixels and force
    the server to resample categorical class codes.

    The mosaic holds one raster per year 1985-2024, so the request pins
    NLCD_YEAR through a mosaicRule. Without it the server picks its own default
    slice and the land-cover vintage could change between runs without warning.
    """
    dest = raw_dir("nlcd") / f"nlcd_{fips}.tif"
    if dest.exists() and dest.stat().st_size > 0:
        print(f"fetch: {dest.name} already present, skipping")
        return dest

    import numpy as np
    import rasterio
    from pyproj import Transformer

    tf = Transformer.from_crs("EPSG:4326", f"EPSG:{NLCD_SR}", always_xy=True)
    corners = [tf.transform(x, y) for x in (bounds[0], bounds[2]) for y in (bounds[1], bounds[3])]
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    # Snap outward onto the 30 m grid so returned pixels align with native NLCD cells
    minx = math.floor(min(xs) / NLCD_RES_M) * NLCD_RES_M
    miny = math.floor(min(ys) / NLCD_RES_M) * NLCD_RES_M
    maxx = math.ceil(max(xs) / NLCD_RES_M) * NLCD_RES_M
    maxy = math.ceil(max(ys) / NLCD_RES_M) * NLCD_RES_M
    width = int((maxx - minx) / NLCD_RES_M)
    height = int((maxy - miny) / NLCD_RES_M)
    if width > NLCD_MAX_PX or height > NLCD_MAX_PX:
        raise RuntimeError(f"fetch: NLCD request {width}x{height} px exceeds the service limit of "
                           f"{NLCD_MAX_PX} px per side — this county needs a tiled request; "
                           f"do not lower the resolution, that would resample class codes")

    print(f"fetch: nlcd {NLCD_YEAR}: requesting {width}x{height} px @ {NLCD_RES_M} m "
          f"(EPSG:{NLCD_SR}) from {NLCD_WCS}")
    params = {"bbox": f"{minx},{miny},{maxx},{maxy}", "bboxSR": NLCD_SR, "imageSR": NLCD_SR,
              "size": f"{width},{height}", "format": "tiff", "pixelType": "U8", "f": "image",
              "interpolation": "RSP_NearestNeighbor",  # categorical: never average class codes
              "mosaicRule": json.dumps({"where": f"Year={NLCD_YEAR}"})}
    r = requests.get(f"{NLCD_WCS}/exportImage", params=params, timeout=TIMEOUT)
    r.raise_for_status()
    ctype = r.headers.get("Content-Type", "")
    if "image" not in ctype:
        # exportImage reports failures as an HTTP 200 JSON body, so a bad request
        # would otherwise be written straight to disk as a "valid" .tif
        raise RuntimeError(f"fetch: NLCD exportImage returned {ctype!r}, not an image: "
                           f"{r.text[:300]} — check the endpoint (see docs/data-sources.md)")

    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.write_bytes(r.content)
    # Verify before publishing: a rendered RGB image or an all-nodata window would
    # silently poison every land-cover measurement downstream
    with rasterio.open(tmp) as ds:
        res, crs, shape = ds.res, ds.crs, (ds.width, ds.height)
        band = ds.read(1)
    if res != (NLCD_RES_M, NLCD_RES_M):
        tmp.unlink()
        raise RuntimeError(f"fetch: NLCD raster came back at {res} m, expected "
                           f"{NLCD_RES_M} m — the service resampled; zonal stats would be wrong")
    values = {int(v) for v in np.unique(band)}
    unexpected = values - NLCD_CLASSES - {0}
    if unexpected:
        tmp.unlink()
        raise RuntimeError(f"fetch: NLCD raster holds non-legend values {sorted(unexpected)[:10]} "
                           f"— the service likely returned a rendered image instead of class "
                           f"codes (see docs/data-sources.md)")
    classified = float((band != 0).sum()) / band.size
    if classified < 0.5:
        tmp.unlink()
        raise RuntimeError(f"fetch: NLCD raster is only {classified:.1%} classified — the request "
                           f"window is mostly nodata, so the bbox or CRS is wrong")
    tmp.replace(dest)
    print(f"fetch: wrote {dest} ({dest.stat().st_size:,} bytes) — {shape[0]}x{shape[1]} px, "
          f"{crs}, {classified:.1%} classified, classes {sorted(values - {0})}")
    return dest
