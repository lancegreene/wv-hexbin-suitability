import geopandas as gpd
import h3
from shapely.geometry import Polygon

from .paths import grid_path, raw_dir

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
    return cells_to_gdf(cell_ids)


def run(fips):
    counties = gpd.read_file(raw_dir("county") / "counties.zip")
    county = counties[counties["GEOID"] == fips]
    if len(county) != 1:
        raise RuntimeError(f"expected exactly 1 county with GEOID={fips}, found {len(county)} "
                           f"in {raw_dir('county') / 'counties.zip'}")
    # Buffer 500 m so edge parcels still get full cell coverage (boundary file is generalized)
    boundary = county.to_crs(UTM).buffer(500).to_crs("EPSG:4326").iloc[0]
    gdf = cells_for_boundary(boundary)
    dest = grid_path(fips)
    gdf.to_parquet(dest)
    print(f"grid: {len(gdf)} res-10 cells for {fips} -> {dest}")
    return dest
