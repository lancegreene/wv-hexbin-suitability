import h3
from shapely.geometry import Polygon

from hexbin_pipeline.grid import cells_for_boundary


def test_cells_cover_small_polygon():
    # ~1 km square near Beckley, EPSG:4326 (lng, lat order)
    poly = Polygon([(-81.19, 37.77), (-81.18, 37.77), (-81.18, 37.78), (-81.19, 37.78)])
    gdf = cells_for_boundary(poly)
    assert len(gdf) > 30  # ~1 km^2 at res 10 (~0.015 km^2/cell)
    assert set(gdf.columns) >= {"h3_index", "h3_r9", "h3_r8", "geometry"}
    assert gdf["h3_index"].is_unique
    row = gdf.iloc[0]
    assert h3.get_resolution(row.h3_index) == 10
    assert h3.cell_to_parent(row.h3_index, 9) == row.h3_r9
    assert h3.cell_to_parent(row.h3_index, 8) == row.h3_r8
    assert gdf.crs.to_epsg() == 4326
