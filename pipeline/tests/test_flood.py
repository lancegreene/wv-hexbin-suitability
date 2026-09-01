import geopandas as gpd
import pandas as pd

from hexbin_pipeline import paths
from hexbin_pipeline.measure import flood

def test_flood_columns_and_values(seven_cells, tmp_path, monkeypatch):
    fips = "99999"
    monkeypatch.setattr(paths, "RAW", tmp_path / "raw")
    monkeypatch.setattr(paths, "WORK", tmp_path / "work")

    seven_cells.to_parquet(paths.grid_path(fips))
    # AE zone exactly covering cell 0; no floodway anywhere
    nfhl = gpd.GeoDataFrame(
        {"FLD_ZONE": ["AE"], "ZONE_SUBTY": [None]},
        geometry=[seven_cells.geometry.iloc[0]], crs="EPSG:4326")
    nfhl.to_file(paths.raw_dir("nfhl") / f"nfhl_{fips}.geojson", driver="GeoJSON")

    dest = flood.run(fips)
    out = pd.read_parquet(dest)
    assert list(out.columns) == ["h3_index", "flood_pct_a_ae", "floodway_pct"]
    assert len(out) == 7
    row0 = out[out.h3_index == seven_cells.h3_index.iloc[0]].iloc[0]
    assert row0.flood_pct_a_ae > 95
    assert (out.floodway_pct == 0).all()
