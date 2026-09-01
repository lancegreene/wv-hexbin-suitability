import geopandas as gpd
import pandas as pd

from .. import paths
from .common import dist_to_nearest


# Bbox-clipped source: distances near the county edge are upper bounds — acceptable for MVP screening.
def run(fips):
    cells = gpd.read_parquet(paths.grid_path(fips))
    lines = gpd.read_file(paths.raw_dir("transmission") / f"transmission_{fips}.geojson")
    print(f"transmission: {len(lines)} line features")
    out = pd.DataFrame({
        "h3_index": cells["h3_index"],
        "transmission_dist_m": dist_to_nearest(cells, lines).values,
    })
    dest = paths.work_dir(fips) / "measure_transmission.parquet"
    out.to_parquet(dest, index=False)
    print(f"transmission: wrote {len(out)} rows, median dist {out.transmission_dist_m.median():.0f} m -> {dest}")
    return dest
