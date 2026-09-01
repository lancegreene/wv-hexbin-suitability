import geopandas as gpd
import pandas as pd

from .. import paths
from .common import pct_overlap


def run(fips):
    cells = gpd.read_parquet(paths.grid_path(fips))
    mined = gpd.read_file(paths.raw_dir("mined") / f"mined_{fips}.geojson")
    # The TAGIS layer is NOT underground-only despite its title — it mixes
    # U/S/E/D/O/Q permit types (see permit_id caveat in docs/data-sources.md).
    # This mask exists for subsidence risk from underground workings, so keep
    # only U-prefix permits; reclaimed surface mines are not a constraint.
    underground = mined[mined["permit_id"].fillna("").str.startswith("U")]
    print(f"mined: {len(mined)} mining polygons, {len(underground)} underground (U-permit)")
    out = pd.DataFrame({
        "h3_index": cells["h3_index"],
        "mined_pct": pct_overlap(cells, underground).values,
    })
    dest = paths.work_dir(fips) / "measure_mined.parquet"
    out.to_parquet(dest, index=False)
    print(f"mined: wrote {len(out)} rows -> {dest}")
    return dest
