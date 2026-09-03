import geopandas as gpd
import pandas as pd

from .. import paths
from ..fetch import adjacent_geoids
from .common import UTM
from .network import (MPH_TO_M_PER_MIN, ROAD_MTFCC, build_graph, find_access_points,
                      node_minutes)

ACCESS_LEG_MPH = 30  # centroid -> nearest graph node, straight line
# Beyond this, the straight-line access leg is meaningless and the cell is
# genuinely off-network -> NULL (validate gates the rate)
MAX_ACCESS_LEG_M = 5000


def _load_roads(fips):
    """Load TIGER EDGES (topological primitives, split at every node) for the
    target + adjacent counties, filtered to drivable roads.

    The ROADS product is whole-road features spanning many intersections —
    a graph built from it shatters (98% of cells were unreachable)."""
    counties_m = gpd.read_file(paths.raw_dir("county") / "counties.zip").to_crs(UTM)
    wanted = [fips] + adjacent_geoids(counties_m, fips)
    frames = []
    for f in wanted:
        p = paths.raw_dir("edges") / f"edges_{f}.zip"
        if not p.exists():
            raise RuntimeError(f"hwy_access: missing edges for county {f} ({p}) — "
                               f"run the fetch stage")
        e = gpd.read_file(p)[["ROADFLG", "MTFCC", "geometry"]]
        e = e[(e["ROADFLG"] == "Y") & e["MTFCC"].isin(ROAD_MTFCC)]
        frames.append(e[["MTFCC", "geometry"]])
    roads = pd.concat(frames, ignore_index=True)
    print(f"hwy_access: {len(roads)} road edges across {len(wanted)} counties")
    return gpd.GeoDataFrame(roads, crs=frames[0].crs).to_crs(UTM)


def map_cells_to_minutes(cells, minutes):
    """Per-cell drive minutes from per-node minutes.

    Maps each centroid to the nearest REACHABLE node: a cell whose nearest raw
    node is a disconnected stub (private drive, digitizing fragment) is not
    itself off-network — nearest-any-node NULLed 2% of Raleigh's cells.
    Honesty guard: if even the nearest reachable node is beyond
    MAX_ACCESS_LEG_M, the cell genuinely lacks network access -> NULL.
    Returns a DataFrame [h3_index, hwy_drive_min] aligned to cells order.
    """
    reach_nodes = list(minutes.keys())
    if not reach_nodes:
        raise RuntimeError("hwy_access: no reachable nodes — the network never "
                           "connected to an access point")
    nodes = gpd.GeoDataFrame({"minutes": [minutes[n] for n in reach_nodes]},
                             geometry=gpd.points_from_xy([n[0] for n in reach_nodes],
                                                         [n[1] for n in reach_nodes]),
                             crs=UTM)
    cents = cells.to_crs(UTM)[["h3_index", "geometry"]].copy()
    cents["geometry"] = cents.geometry.centroid
    joined = gpd.sjoin_nearest(cents, nodes, distance_col="leg_m").drop_duplicates("h3_index")
    drive_min = (joined["minutes"] + joined["leg_m"] / (ACCESS_LEG_MPH * MPH_TO_M_PER_MIN))
    drive_min = drive_min.where(joined["leg_m"] <= MAX_ACCESS_LEG_M)
    out = pd.DataFrame({"h3_index": joined["h3_index"].values,
                        "hwy_drive_min": drive_min.values})
    return out.set_index("h3_index").reindex(cells["h3_index"]).reset_index()


def run(fips):
    cells = gpd.read_parquet(paths.grid_path(fips))
    roads_m = _load_roads(fips)
    graph, _ = build_graph(roads_m)
    access = find_access_points(roads_m, strict=True)
    minutes = node_minutes(graph, access)
    reachable_frac = len(minutes) / max(graph.number_of_nodes(), 1)
    print(f"hwy_access: {reachable_frac:.1%} of graph nodes reachable from access points")

    out = map_cells_to_minutes(cells, minutes)
    n_null = int(out["hwy_drive_min"].isna().sum())
    if n_null:
        print(f"hwy_access: WARNING — {n_null}/{len(out)} cells unreachable (NULL); "
              f"validate gates on the null rate")
    dest = paths.work_dir(fips) / "measure_hwy_access.parquet"
    out.to_parquet(dest, index=False)
    print(f"hwy_access: wrote {len(out)} rows, median {out.hwy_drive_min.median():.1f} min, "
          f"max {out.hwy_drive_min.max():.1f} min -> {dest}")
    return dest
