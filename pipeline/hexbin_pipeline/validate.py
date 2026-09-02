import json
import shutil

import geopandas as gpd
import pandas as pd

from . import paths

MAX_NULL_FRAC = 0.01
MAX_UNCOVERED_PARCEL_FRAC = 0.005


def run(fips):
    problems = []
    grid = gpd.read_parquet(paths.grid_path(fips))
    cells = grid[["h3_index", "h3_r9", "h3_r8", "in_county"]].copy()

    measure_files = sorted(paths.work_dir(fips).glob("measure_*.parquet"))
    if not measure_files:
        raise SystemExit("validate: no measure_*.parquet files — run the measure stage")
    for p in measure_files:
        df = pd.read_parquet(p)
        before = len(cells)
        cells = cells.merge(df, on="h3_index", how="left", validate="one_to_one")
        print(f"validate: joined {p.name} ({len(df)} rows, {len(df.columns) - 1} columns)")
        if len(cells) != before:
            problems.append(f"{p.name}: join changed row count {before} -> {len(cells)}")

    registry = json.loads(paths.CRITERIA.read_text())
    expected = ({c["column"] for c in registry["criteria"]}
                | {m["column"] for m in registry["masks"]})
    missing = expected - set(cells.columns)
    if missing:
        problems.append(f"columns in criteria.json but not measured: {sorted(missing)}")
    # Reverse direction is a warning, not a failure: measure files may carry
    # supporting columns (confidence flags, informational stats) beyond the
    # registry, but an unexpected one is worth eyes (e.g. a renamed criterion's
    # orphaned parquet would otherwise slip into the published artifact)
    known_extra = {"water_conf", "slope_pct_gt15", "road_dist_m"}
    unexpected = set(cells.columns) - expected - {"h3_index", "h3_r9", "h3_r8", "in_county"} - known_extra
    if unexpected:
        print(f"validate: WARNING — measured columns not in criteria.json: {sorted(unexpected)}")

    for col in cells.columns.drop(["h3_index", "h3_r9", "h3_r8"]):
        frac = cells[col].isna().mean()
        if frac > MAX_NULL_FRAC:
            problems.append(f"{col}: {frac:.1%} null (max {MAX_NULL_FRAC:.0%})")

    xw_path = paths.work_dir(fips) / "parcel_cell_xwalk.parquet"
    pq_path = paths.work_dir(fips) / "parcels.parquet"
    gj_path = paths.work_dir(fips) / "parcels.geojson"
    bd_path = paths.work_dir(fips) / "county_boundary.geojson"
    for p in (xw_path, pq_path, gj_path, bd_path):
        if not p.exists() or p.stat().st_size == 0:
            problems.append(f"missing or empty artifact: {p.name}")
    if xw_path.exists() and pq_path.exists():
        xw = pd.read_parquet(xw_path)
        parcels = pd.read_parquet(pq_path)
        uncovered = 1 - xw["parcel_id"].nunique() / max(len(parcels), 1)
        if uncovered > MAX_UNCOVERED_PARCEL_FRAC:
            problems.append(f"{uncovered:.1%} of parcels have no cells (max {MAX_UNCOVERED_PARCEL_FRAC:.1%})")
        bad_frac = xw[(xw.overlap_frac <= 0) | (xw.overlap_frac > 1.001)]
        if len(bad_frac):
            problems.append(f"{len(bad_frac)} xwalk rows with overlap_frac outside (0, 1]")

    if problems:
        print("validate: FAILED — artifacts NOT published:")
        for p in problems:
            print(f"  - {p}")
        raise SystemExit(1)

    out = paths.processed_dir(fips)
    cells.to_parquet(out / "cells_r10.parquet", index=False)
    shutil.copy2(xw_path, out / "parcel_cell_xwalk.parquet")
    shutil.copy2(pq_path, out / "parcels.parquet")
    shutil.copy2(gj_path, out / "parcels.geojson")
    shutil.copy2(bd_path, out / "county_boundary.geojson")
    print(f"validate: OK — {len(cells)} cells, {len(cells.columns)} columns published to {out}")
