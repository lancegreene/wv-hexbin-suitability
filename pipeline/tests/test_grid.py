import h3
import pytest
from shapely.geometry import MultiPolygon, Polygon

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


def test_cells_cover_multipolygon():
    # Two disjoint ~1 km squares — buffered county boundaries can be multi-part
    part_a = Polygon([(-81.19, 37.77), (-81.18, 37.77), (-81.18, 37.78), (-81.19, 37.78)])
    part_b = Polygon([(-81.15, 37.77), (-81.14, 37.77), (-81.14, 37.78), (-81.15, 37.78)])
    gdf = cells_for_boundary(MultiPolygon([part_a, part_b]))
    both = len(gdf)
    assert both > 60  # roughly double the single-square count
    assert both == pytest.approx(len(cells_for_boundary(part_a)) + len(cells_for_boundary(part_b)), abs=2)
    assert gdf["h3_index"].is_unique
