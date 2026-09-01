import geopandas as gpd
import pandas as pd
from shapely import make_valid

from .. import paths
from .common import UTM

CONF_FIELD = "Model_Method"  # blank = authoritative, non-empty = EPA-modeled; see docs/data-sources.md


def run(fips):
    cells = gpd.read_parquet(paths.grid_path(fips))
    cws = gpd.read_file(paths.raw_dir("water") / f"water_{fips}.geojson")
    if CONF_FIELD not in cws.columns:
        raise RuntimeError(f"water: confidence field '{CONF_FIELD}' not in CWS attributes "
                           f"{list(cws.columns)} — fix CONF_FIELD per docs/data-sources.md")
    invalid = ~cws.geometry.is_valid
    if invalid.any():
        print(f"water: repairing {int(invalid.sum())} invalid polygon(s)")
        cws.loc[invalid, "geometry"] = cws.loc[invalid, "geometry"].apply(make_valid)
    print(f"water: {len(cws)} CWS polygons")
    cents = cells.to_crs(UTM)[["h3_index", "geometry"]].copy()
    cents["geometry"] = cents.geometry.centroid
    joined = gpd.sjoin(cents, cws.to_crs(UTM)[["geometry", CONF_FIELD]],
                       how="left", predicate="within")
    # Where authoritative and modeled service areas overlap, the authoritative
    # label must win the tie deterministically (blank Model_Method sorts first)
    joined = (joined.sort_values(CONF_FIELD, na_position="first")
              .drop_duplicates("h3_index"))
    in_service = joined["index_right"].notna()
    method = joined[CONF_FIELD].fillna("").astype(str).str.strip()
    conf = pd.Series("none", index=joined.index)
    conf[in_service & (method == "")] = "authoritative"
    conf[in_service & (method != "")] = "modeled:" + method[in_service & (method != "")]
    out = pd.DataFrame({
        "h3_index": joined["h3_index"].values,
        "water_in_service": in_service.astype("int8").values,
        "water_conf": conf.values,
    })
    dest = paths.work_dir(fips) / "measure_water.parquet"
    out.to_parquet(dest, index=False)
    print(f"water: wrote {len(out)} rows, {out.water_in_service.mean():.1%} in service -> {dest}")
    return dest
