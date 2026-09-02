import geopandas as gpd
from shapely.geometry import box

from hexbin_pipeline.fetch import adjacent_geoids


def test_adjacent_geoids_finds_touching_counties_despite_sliver_gaps():
    # A(target) shares an edge with B; C is 50 m away (generalized-boundary
    # sliver); D is far. Buffer tolerance must catch C, exclude D.
    counties = gpd.GeoDataFrame({
        "GEOID": ["54081", "54019", "54045", "54001"],
        "geometry": [
            box(0, 0, 10_000, 10_000),
            box(10_000, 0, 20_000, 10_000),
            box(0, 10_050, 10_000, 20_000),
            box(50_000, 50_000, 60_000, 60_000),
        ],
    }, crs="EPSG:26917")
    assert adjacent_geoids(counties, "54081") == ["54019", "54045"]


def test_adjacent_geoids_missing_target_raises():
    counties = gpd.GeoDataFrame({"GEOID": ["54001"], "geometry": [box(0, 0, 1, 1)]},
                                crs="EPSG:26917")
    try:
        adjacent_geoids(counties, "54081")
        raise AssertionError("should have raised")
    except RuntimeError as e:
        assert "54081" in str(e)
