import geopandas as gpd
import pytest
from shapely.ops import unary_union

from hexbin_pipeline.xwalk import build_xwalk


def test_overlap_fracs_sum_to_one(seven_cells):
    # Parcel = union of cells 0 and 1 -> two xwalk rows, fracs ~0.5 each, sum ~1
    parcel_geom = unary_union([seven_cells.geometry.iloc[0], seven_cells.geometry.iloc[1]])
    parcels = gpd.GeoDataFrame({"parcel_id": ["P1"]}, geometry=[parcel_geom], crs="EPSG:4326")
    xw = build_xwalk(seven_cells, parcels)
    assert set(xw.columns) == {"parcel_id", "h3_index", "overlap_frac"}
    p1 = xw[xw.parcel_id == "P1"]
    assert len(p1) == 2
    assert p1.overlap_frac.sum() == pytest.approx(1.0, abs=0.01)
    assert p1.overlap_frac.min() == pytest.approx(0.5, abs=0.05)
