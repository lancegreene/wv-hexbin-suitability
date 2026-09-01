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
