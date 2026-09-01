import geopandas as gpd
import h3
import pytest
from shapely.geometry import Polygon

BECKLEY = (37.778, -81.188)  # lat, lng


def cells_from_h3(cell_ids):
    """Build a grid-style GeoDataFrame from explicit H3 cells (mirrors grid.cells_to_gdf)."""
    rows = []
    for c in cell_ids:
        ring = [(lng, lat) for lat, lng in h3.cell_to_boundary(c)]
        rows.append({"h3_index": c, "h3_r9": h3.cell_to_parent(c, 9),
                     "h3_r8": h3.cell_to_parent(c, 8), "in_county": True,
                     "geometry": Polygon(ring)})
    return gpd.GeoDataFrame(rows, crs="EPSG:4326")


@pytest.fixture
def seven_cells():
    """A res-10 cell near Beckley plus its 6 neighbors."""
    center = h3.latlng_to_cell(*BECKLEY, 10)
    return cells_from_h3(h3.grid_disk(center, 1))
