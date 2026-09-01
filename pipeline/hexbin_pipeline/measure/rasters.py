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
    del mosaic, srcs  # ~1 GB no longer needed; trims peak RAM through the gradient step
    dy, dx = np.gradient(dem_utm, res)
    slope_pct = np.hypot(dx, dy) * 100.0
    # tiled: zonal_stats does one windowed read per hex; against 1-row-strip
    # GeoTIFFs each tiny window decompresses full-width rows (measured: minutes
    # of extra runtime per zonal pass at county scale)
    with rasterio.open(out_path, "w", driver="GTiff", height=h, width=w, count=1,
                       dtype="float32", crs=UTM, transform=dst_transform,
                       nodata=np.nan, compress="deflate",
                       tiled=True, blockxsize=256, blockysize=256) as dst:
        dst.write(slope_pct, 1)
    print(f"rasters: slope raster {w}x{h} @ {res} m -> {out_path}")
    return out_path


def _cells_in_raster_crs(cells, raster_path):
    with rasterio.open(raster_path) as src:
        crs = src.crs
    return cells.to_crs(crs)


def _series(values, cells, raster_path, what):
    """Series indexed by h3_index in cells' row order, with loud no-coverage count."""
    s = pd.Series(values, index=pd.Index(cells["h3_index"], name="h3_index"))
    n_null = int(s.isna().sum())
    if n_null:
        print(f"rasters: WARNING — {what}: {n_null}/{len(s)} cells got no raster "
              f"coverage from {raster_path}; validate will gate on the null rate")
    return s


def zonal_mean(cells, raster_path):
    """Mean raster value per cell (all_touched so ~120 m hexes never sample zero pixels)."""
    stats = zonal_stats(_cells_in_raster_crs(cells, raster_path).geometry, str(raster_path),
                        stats=["mean"], all_touched=True)
    return _series([s["mean"] for s in stats], cells, raster_path, "zonal_mean")


def zonal_pct_above(cells, raster_path, threshold):
    """% of each cell's valid pixels exceeding threshold."""
    def pct_above(masked):
        n = masked.count()
        return float((masked > threshold).sum() / n * 100.0) if n else None
    stats = zonal_stats(_cells_in_raster_crs(cells, raster_path).geometry, str(raster_path),
                        stats=["count"], add_stats={"pct_above": pct_above}, all_touched=True)
    return _series([s["pct_above"] for s in stats], cells, raster_path, "zonal_pct_above")


def zonal_majority(cells, raster_path):
    """Modal (majority) raster value per cell — for categorical rasters like NLCD."""
    stats = zonal_stats(_cells_in_raster_crs(cells, raster_path).geometry, str(raster_path),
                        stats=["majority"], all_touched=True)
    return _series([s["majority"] for s in stats], cells, raster_path, "zonal_majority")
