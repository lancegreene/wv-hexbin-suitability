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
