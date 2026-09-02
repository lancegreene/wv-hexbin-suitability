import geopandas as gpd
import pytest
from shapely.geometry import LineString

from hexbin_pipeline.measure.network import build_graph, find_access_points, node_minutes

UTM = "EPSG:26917"


def roads_gdf(rows):
    return gpd.GeoDataFrame(
        {"MTFCC": [r[0] for r in rows]},
        geometry=[LineString(r[1]) for r in rows], crs=UTM)


BASE = [
    ("S1400", [(0, 0), (1000, 0)]),        # surface road A-B
    ("S1630", [(1000, 0), (2000, 0)]),     # ramp B-H
    ("S1100", [(2000, 0), (3000, 0)]),     # highway H-I
    ("S1400", [(9000, 9000), (9500, 9000)]),  # disconnected fragment
]


def test_access_point_is_ramp_end_touching_surface_road():
    access = find_access_points(roads_gdf(BASE))
    assert access == [(1000, 0)]  # B: ramp end on the surface road; H touches only S1100


def test_node_minutes_hand_computed():
    g, _ = build_graph(roads_gdf(BASE))
    minutes = node_minutes(g, [(1000, 0)])
    assert minutes[(1000, 0)] == pytest.approx(0.0)
    assert minutes[(0, 0)] == pytest.approx(1.242742, abs=1e-4)      # 1000 m @ 30 mph
    assert minutes[(2000, 0)] == pytest.approx(1.065207, abs=1e-4)   # 1000 m @ 35 mph
    assert (9000, 9000) not in minutes                                # unreachable fragment


def test_endpoint_snapping_connects_near_coincident_ends():
    rows = [
        ("S1400", [(0, 0), (1000.0004, 0.0003)]),  # rounds to (1000, 0)
        ("S1400", [(1000, 0), (2000, 0)]),
    ]
    g, _ = build_graph(roads_gdf(rows))
    minutes = node_minutes(g, [(2000, 0)])
    assert (0, 0) in minutes  # connected through the snapped shared endpoint


def test_no_access_points_is_loud():
    no_ramp = roads_gdf([("S1400", [(0, 0), (1000, 0)])])
    with pytest.raises(RuntimeError, match="access point"):
        find_access_points(no_ramp, strict=True)
