import geopandas as gpd
import h3
from shapely.geometry import Polygon

from .fetch import GRID_BUFFER_M, load_county
from .paths import grid_path

UTM = "EPSG:26917"


def cells_to_gdf(cell_ids):
    rows = []
    for c in cell_ids:
        ring = [(lng, lat) for lat, lng in h3.cell_to_boundary(c)]
        rows.append({"h3_index": c, "h3_r9": h3.cell_to_parent(c, 9),
                     "h3_r8": h3.cell_to_parent(c, 8), "geometry": Polygon(ring)})
    return gpd.GeoDataFrame(rows, crs="EPSG:4326")


def cells_for_boundary(boundary_4326):
    """(Multi)Polygon in EPSG:4326 -> GeoDataFrame of covering res-10 cells."""
    shape = h3.geo_to_h3shape(boundary_4326.__geo_interface__)
    cell_ids = h3.h3shape_to_cells(shape, 10)
    if not cell_ids:
        raise RuntimeError("H3 polyfill returned 0 cells — boundary geometry or CRS is wrong")
    if len(cell_ids) != len(set(cell_ids)):
        raise RuntimeError("H3 polyfill returned duplicate cells — boundary polygon is "
                           "likely invalid (self-intersecting or overlapping parts)")
    return cells_to_gdf(cell_ids)


def run(fips):
    county = load_county(fips)
    # Buffer so edge parcels still get full cell coverage (boundary file is
    # generalized). GRID_BUFFER_M is shared with fetch.county_bounds so every
    # fetched source's bbox is guaranteed to cover the buffered grid.
    boundary = county.to_crs(UTM).buffer(GRID_BUFFER_M).to_crs("EPSG:4326").iloc[0]
    gdf = cells_for_boundary(boundary)
    dest = grid_path(fips)
    gdf.to_parquet(dest)
    print(f"grid: {len(gdf)} res-10 cells for {fips} -> {dest}")
    return dest
