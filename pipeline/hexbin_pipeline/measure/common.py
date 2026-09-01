import geopandas as gpd
import pandas as pd
from shapely import make_valid

UTM = "EPSG:26917"


def pct_overlap(cells, polys):
    """% of each cell's area covered by the union of polys.

    cells: grid GeoDataFrame (EPSG:4326, h3_index column). polys: any polygon
    GeoDataFrame. Returns Series indexed by h3_index, aligned to cells order.
    Empty polys -> zeros (caller decides whether empty input is legitimate).
    Invalid source polygons (real occurrence in the EPA water and TAGIS mined
    layers) are repaired with make_valid — gpd.overlay would silently drop
    them otherwise.
    """
    order = cells["h3_index"]
    if polys.empty:
        print("pct_overlap: WARNING — empty polygon input, returning all zeros")
        return pd.Series(0.0, index=pd.Index(order, name="h3_index"))
    cells_m = cells.to_crs(UTM)[["h3_index", "geometry"]]
    polys_m = polys.to_crs(UTM)[["geometry"]]
    invalid = ~polys_m.geometry.is_valid
    if invalid.any():
        print(f"pct_overlap: repairing {int(invalid.sum())} invalid polygon(s)")
        polys_m.loc[invalid, "geometry"] = polys_m.loc[invalid, "geometry"].apply(make_valid)
    polys_m = polys_m.dissolve()  # dissolve: no double-counting overlaps
    inter = gpd.overlay(cells_m, polys_m, how="intersection", keep_geom_type=True)
    cell_area = cells_m.set_index("h3_index").area
    covered = inter.assign(a=inter.area).groupby("h3_index")["a"].sum()
    pct = (covered.reindex(cell_area.index, fill_value=0.0) / cell_area * 100.0)
    return pct.reindex(order)


def dist_to_nearest(cells, features):
    """Meters from each cell centroid to the nearest feature. Series indexed by h3_index."""
    if features.empty:
        raise RuntimeError("dist_to_nearest: empty feature input — a distance criterion "
                           "cannot be measured from nothing; check the fetch output")
    order = cells["h3_index"]
    cents = cells.to_crs(UTM)[["h3_index", "geometry"]].copy()
    cents["geometry"] = cents.geometry.centroid
    feats_m = features.to_crs(UTM)[["geometry"]]
    joined = gpd.sjoin_nearest(cents, feats_m, distance_col="dist_m")
    return joined.drop_duplicates("h3_index").set_index("h3_index")["dist_m"].reindex(order)
