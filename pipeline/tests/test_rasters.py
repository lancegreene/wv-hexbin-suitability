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


def test_zonal_result_order_matches_cells(seven_cells, tmp_path):
    # Callers consume .values positionally; index must track the cells argument
    cells_m = seven_cells.to_crs(UTM)
    minx, miny, maxx, maxy = cells_m.total_bounds
    w = int((maxx - minx) / 10) + 2
    h = int((maxy - miny) / 10) + 2
    tif = tmp_path / "grad.tif"
    write_tif(tif, np.tile(np.linspace(0, 100, w, dtype="float32"), (h, 1)),
              from_origin(minx, maxy, 10, 10))
    shuffled = seven_cells.sample(frac=1, random_state=3).reset_index(drop=True)
    mean = zonal_mean(shuffled, tif)
    assert mean.index.tolist() == shuffled["h3_index"].tolist()
    # east-west gradient: values must differ per cell and follow centroid x-order
    order_by_value = mean.sort_values().index.tolist()
    order_by_x = shuffled.assign(x=cells_m_centroid_x(shuffled)).sort_values("x")["h3_index"].tolist()
    assert order_by_value == order_by_x


def cells_m_centroid_x(cells):
    return cells.to_crs(UTM).geometry.centroid.x.values
