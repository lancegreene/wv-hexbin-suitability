import pandas as pd
import pytest

from hexbin_pipeline import paths, validate


@pytest.fixture
def staged(seven_cells, tmp_path, monkeypatch):
    fips = "99999"
    monkeypatch.setattr(paths, "WORK", tmp_path / "work")
    monkeypatch.setattr(paths, "PROCESSED", tmp_path / "processed")
    seven_cells.to_parquet(paths.grid_path(fips))
    idx = seven_cells["h3_index"]
    full = pd.DataFrame({
        "h3_index": idx, "slope_mean_pct": 12.0, "slope_pct_gt15": 30.0,
        "flood_pct_a_ae": 0.0, "floodway_pct": 0.0, "water_in_service": 1,
        "water_conf": "authoritative", "road_dist_m": 500.0, "hwy_drive_min": 8.0,
        "transmission_dist_m": 2000.0, "mined_pct": 0.0, "nlcd_mode": 41,
    })
    full.to_parquet(paths.work_dir(fips) / "measure_all.parquet", index=False)
    pd.DataFrame({"parcel_id": ["P1"], "h3_index": [idx.iloc[0]], "overlap_frac": [1.0]}) \
        .to_parquet(paths.work_dir(fips) / "parcel_cell_xwalk.parquet", index=False)
    pd.DataFrame({"parcel_id": ["P1"]}).to_parquet(paths.work_dir(fips) / "parcels.parquet", index=False)
    (paths.work_dir(fips) / "parcels.geojson").write_text('{"type":"FeatureCollection","features":[]}')
    (paths.work_dir(fips) / "county_boundary.geojson").write_text('{"type":"FeatureCollection","features":[]}')
    return fips


def test_clean_run_publishes(staged):
    validate.run(staged)
    out = pd.read_parquet(paths.processed_dir(staged) / "cells_r10.parquet")
    assert len(out) == 7
    assert "slope_mean_pct" in out.columns and "h3_r8" in out.columns
    assert (paths.processed_dir(staged) / "county_boundary.geojson").exists()


def test_missing_boundary_halts(staged):
    (paths.work_dir(staged) / "county_boundary.geojson").unlink()
    with pytest.raises(SystemExit):
        validate.run(staged)


def test_missing_column_halts(staged):
    p = paths.work_dir(staged) / "measure_all.parquet"
    pd.read_parquet(p).drop(columns=["mined_pct"]).to_parquet(p, index=False)
    with pytest.raises(SystemExit):
        validate.run(staged)


def test_excess_nulls_halt(staged):
    p = paths.work_dir(staged) / "measure_all.parquet"
    df = pd.read_parquet(p)
    df.loc[:, "road_dist_m"] = float("nan")
    df.to_parquet(p, index=False)
    with pytest.raises(SystemExit):
        validate.run(staged)
