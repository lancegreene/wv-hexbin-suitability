import geopandas as gpd
import pytest
from shapely.ops import unary_union

from hexbin_pipeline.xwalk import build_xwalk


def test_overlap_fracs_sum_to_one(seven_cells):
    # P1 = union of cells 0 and 1; P2 = cell 2 alone. Two parcels so that a
    # global-sum denominator bug (dividing by total intersection area instead
    # of each parcel's own area) cannot masquerade as correct.
    parcel_geom = unary_union([seven_cells.geometry.iloc[0], seven_cells.geometry.iloc[1]])
    parcels = gpd.GeoDataFrame({"parcel_id": ["P1", "P2"]},
                               geometry=[parcel_geom, seven_cells.geometry.iloc[2]],
                               crs="EPSG:4326")
    xw = build_xwalk(seven_cells, parcels)
    assert set(xw.columns) == {"parcel_id", "h3_index", "overlap_frac"}
    p1 = xw[xw.parcel_id == "P1"]
    assert len(p1) == 2
    assert p1.overlap_frac.sum() == pytest.approx(1.0, abs=0.01)
    assert p1.overlap_frac.min() == pytest.approx(0.5, abs=0.05)
    p2 = xw[xw.parcel_id == "P2"]
    assert p2.overlap_frac.sum() == pytest.approx(1.0, abs=0.01)
