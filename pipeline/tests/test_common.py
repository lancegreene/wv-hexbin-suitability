import geopandas as gpd
import pytest
from shapely.geometry import LineString, Polygon

from hexbin_pipeline.measure.common import UTM, dist_to_nearest, pct_overlap


def test_pct_overlap_full_and_none(seven_cells):
    # Polygon = exact footprint of cell 0 -> that cell ~100%, at least one other cell ~0
    target = seven_cells.iloc[[0]]
    polys = gpd.GeoDataFrame(geometry=[target.geometry.iloc[0]], crs="EPSG:4326")
    pct = pct_overlap(seven_cells, polys)
    assert pct.loc[target.h3_index.iloc[0]] == pytest.approx(100, abs=1)
    assert pct.min() == pytest.approx(0, abs=1)
    assert len(pct) == len(seven_cells)


def test_pct_overlap_empty_polys_returns_zeros(seven_cells):
    empty = gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    pct = pct_overlap(seven_cells, empty)
    assert (pct == 0).all()


def test_pct_overlap_repairs_invalid_polygons(seven_cells, capsys):
    # Bowtie (self-intersecting) polygon spanning cell 0's neighborhood. Current
    # GEOS happens to overlay bowties correctly even unrepaired, so the value
    # assertions alone can't prove the repair exists — the repair-message
    # assertion binds this test to the make_valid block (its loud print is part
    # of the fail-visibly contract, not decoration).
    minx, miny, maxx, maxy = seven_cells.total_bounds
    bowtie = Polygon([(minx, miny), (maxx, maxy), (minx, maxy), (maxx, miny)])
    assert not bowtie.is_valid
    polys = gpd.GeoDataFrame(geometry=[bowtie], crs="EPSG:4326")
    pct = pct_overlap(seven_cells, polys)
    assert "repairing 1 invalid polygon" in capsys.readouterr().out
    assert pct.max() > 10  # repaired bowtie genuinely covers parts of the cells
    assert len(pct) == len(seven_cells)


def test_dist_to_nearest(seven_cells):
    # Line 1000 m east of cell 0's centroid, in UTM
    cent = seven_cells.iloc[[0]].to_crs(UTM).geometry.centroid.iloc[0]
    line = LineString([(cent.x + 1000, cent.y - 5000), (cent.x + 1000, cent.y + 5000)])
    lines = gpd.GeoDataFrame(geometry=[line], crs=UTM).to_crs("EPSG:4326")
    dist = dist_to_nearest(seven_cells, lines)
    assert dist.loc[seven_cells.h3_index.iloc[0]] == pytest.approx(1000, abs=15)
