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


def _series(values, cells):
    return pd.Series(values, index=pd.Index(cells["h3_index"], name="h3_index"))


def zonal_mean(cells, raster_path):
    stats = zonal_stats(_cells_in_raster_crs(cells, raster_path).geometry, str(raster_path),
                        stats=["mean"], all_touched=True)
    return _series([s["mean"] for s in stats], cells)


def zonal_pct_above(cells, raster_path, threshold):
    def pct_above(masked):
        n = masked.count()
        return float((masked > threshold).sum() / n * 100.0) if n else None
    stats = zonal_stats(_cells_in_raster_crs(cells, raster_path).geometry, str(raster_path),
                        stats=["count"], add_stats={"pct_above": pct_above}, all_touched=True)
    return _series([s["pct_above"] for s in stats], cells)


def zonal_majority(cells, raster_path):
    stats = zonal_stats(_cells_in_raster_crs(cells, raster_path).geometry, str(raster_path),
                        stats=["majority"], all_touched=True)
    return _series([s["majority"] for s in stats], cells)
