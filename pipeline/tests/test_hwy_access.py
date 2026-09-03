import geopandas as gpd
import pytest
from shapely.geometry import LineString

from hexbin_pipeline.measure.common import UTM
from hexbin_pipeline.measure.hwy_access import (ACCESS_LEG_MPH, MAX_ACCESS_LEG_M,
                                                map_cells_to_minutes)
from hexbin_pipeline.measure.network import (MPH_TO_M_PER_MIN, ROAD_MTFCC,
                                             build_graph)


def _cell0_centroid_utm(cells):
    return cells.to_crs(UTM).geometry.centroid.iloc[0]


def test_map_cells_alignment_and_access_leg(seven_cells):
    c0 = _cell0_centroid_utm(seven_cells)
    node = (round(c0.x), round(c0.y))
    out = map_cells_to_minutes(seven_cells, {node: 7.0})
    assert out["h3_index"].tolist() == seven_cells["h3_index"].tolist()
    # cell 0's centroid sits on the node: minutes ~= 7.0 + ~zero leg
    assert out["hwy_drive_min"].iloc[0] == pytest.approx(7.0, abs=0.01)
    # neighbors are ~200-300 m away -> small positive leg at ACCESS_LEG_MPH
    legs = out["hwy_drive_min"] - 7.0
    assert (legs >= 0).all()
    assert legs.max() < 1000 / (ACCESS_LEG_MPH * MPH_TO_M_PER_MIN)


def test_map_cells_nulls_beyond_max_access_leg(seven_cells):
    c0 = _cell0_centroid_utm(seven_cells)
    far_node = (round(c0.x) + MAX_ACCESS_LEG_M + 2000, round(c0.y))
    out = map_cells_to_minutes(seven_cells, {far_node: 3.0})
    # every cell's only reachable node is > MAX_ACCESS_LEG_M away -> all NULL
    assert out["hwy_drive_min"].isna().all()


def test_map_cells_no_reachable_nodes_is_loud(seven_cells):
    with pytest.raises(RuntimeError, match="no reachable nodes"):
        map_cells_to_minutes(seven_cells, {})


def test_build_graph_rejects_geographic_crs():
    roads_4326 = gpd.GeoDataFrame({"MTFCC": ["S1400"]},
                                  geometry=[LineString([(-81.19, 37.77), (-81.18, 37.77)])],
                                  crs="EPSG:4326")
    with pytest.raises(RuntimeError, match="metric CRS"):
        build_graph(roads_4326)


def test_road_allowlist_excludes_pedestrian_classes():
    # ROADFLG='Y' alone admits these; the allowlist must not
    for bad in ("S1710", "S1820", "S1500X", "L4020", "R1011"):
        assert bad not in ROAD_MTFCC
    for good in ("S1100", "S1200", "S1400", "S1630"):
        assert good in ROAD_MTFCC
