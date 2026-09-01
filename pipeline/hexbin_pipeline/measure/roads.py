import geopandas as gpd
import pandas as pd

from .. import paths
from .common import dist_to_nearest

# TIGER MTFCC: S1100 primary, S1200 secondary, S1400 local/neighborhood roads.
# MVP measures distance to improved roads only — functional-class weighting is
# a post-MVP refinement (spec).
IMPROVED = {"S1100", "S1200", "S1400"}


def run(fips):
    cells = gpd.read_parquet(paths.grid_path(fips))
    roads = gpd.read_file(paths.raw_dir("roads") / f"roads_{fips}.zip")
    improved = roads[roads["MTFCC"].isin(IMPROVED)]
    print(f"roads: {len(roads)} segments, {len(improved)} improved (MTFCC {sorted(IMPROVED)})")
    out = pd.DataFrame({
        "h3_index": cells["h3_index"],
        "road_dist_m": dist_to_nearest(cells, improved).values,
    })
    dest = paths.work_dir(fips) / "measure_roads.parquet"
    out.to_parquet(dest, index=False)
    print(f"roads: wrote {len(out)} rows, median dist {out.road_dist_m.median():.0f} m -> {dest}")
    return dest
