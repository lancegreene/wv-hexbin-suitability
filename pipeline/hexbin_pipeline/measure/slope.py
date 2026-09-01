import geopandas as gpd
import pandas as pd

from .. import paths
from ..fetch import county_bounds, dem_tiles
from .rasters import build_slope_raster, zonal_mean, zonal_pct_above


def run(fips):
    cells = gpd.read_parquet(paths.grid_path(fips))
    # data/raw/dem is a shared cross-county tile cache — select only THIS
    # county's tiles, never glob the whole cache (a second county's tiles
    # would silently bloat the mosaic)
    dems = [paths.raw_dir("dem") / f"USGS_13_{t}.tif" for t in dem_tiles(county_bounds(fips))]
    missing = [d.name for d in dems if not d.exists()]
    if missing:
        raise RuntimeError(f"slope: missing DEM tiles {missing} in data/raw/dem — "
                           f"run the fetch stage for {fips}")
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
