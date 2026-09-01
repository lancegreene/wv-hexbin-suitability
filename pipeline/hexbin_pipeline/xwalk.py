import geopandas as gpd

from . import paths
from .measure.common import UTM


def build_xwalk(cells, parcels):
    """parcel_id, h3_index, overlap_frac — fraction of the parcel's area in each cell."""
    cells_m = cells.to_crs(UTM)[["h3_index", "geometry"]]
    parcels_m = parcels.to_crs(UTM)[["parcel_id", "geometry"]]
    parcel_area = parcels_m.set_index("parcel_id").area
    inter = gpd.overlay(parcels_m, cells_m, how="intersection", keep_geom_type=True)
    inter["overlap_frac"] = inter.area / inter["parcel_id"].map(parcel_area)
    return inter[["parcel_id", "h3_index", "overlap_frac"]].reset_index(drop=True)


def run(fips):
    from .parcels import load_county_parcels
    cells = gpd.read_parquet(paths.grid_path(fips))
    parcels = load_county_parcels(fips)
    xw = build_xwalk(cells, parcels)
    covered = xw["parcel_id"].nunique()
    print(f"xwalk: {len(xw)} rows, {covered}/{len(parcels)} parcels have >=1 cell")
    dest = paths.work_dir(fips) / "parcel_cell_xwalk.parquet"
    xw.to_parquet(dest, index=False)

    # Parcel attribute + geometry outputs
    attrs = parcels.drop(columns="geometry")
    attrs.to_parquet(paths.work_dir(fips) / "parcels.parquet", index=False)
    simplified = parcels.to_crs(UTM)
    simplified["geometry"] = simplified.geometry.simplify(5)
    simplified.to_crs("EPSG:4326").to_file(paths.work_dir(fips) / "parcels.geojson", driver="GeoJSON")
    print(f"xwalk: wrote parcels.parquet ({len(attrs)} rows) and parcels.geojson")
    return dest
