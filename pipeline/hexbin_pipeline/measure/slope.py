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
