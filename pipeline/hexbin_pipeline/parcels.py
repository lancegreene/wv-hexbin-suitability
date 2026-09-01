from pathlib import Path

import geopandas as gpd
import pyogrio
from shapely import make_valid

from . import paths

# From GDB inspection (Task 11 Step 1, WV_WVGISTC_Tax_2025.gdb):
# The GDB has two relevant layers that must be joined -- there is no single
# layer with both geometry and rich attributes:
#   - GEOM_LAYER: parcel polygons (MultiPolygon Z) + minimal IDs (CleanParcelID,
#     GISPID, Dist, Map, Parcel, Suffix, Acres_C, CountyID). CRS is EPSG:26917
#     (already matches measure/common.py's UTM constant).
#   - ATTR_LAYER: non-spatial table with the rich fields (owner, acreage,
#     district, address, land use, appraisal, ...). Links to GEOM_LAYER on
#     CleanParcelID.
# County is WV's internal 2-digit county code (NOT the FIPS county code):
# Raleigh = 41 on both layers -- confirmed via ATTR_LAYER's CountyCode/CountyName
# pair ((41, 'Raleigh')) against target FIPS 54081. On GEOM_LAYER the field is
# CountyID, a zero-padded *string* ('41'); on ATTR_LAYER it's CountyCode, an int.
#
# NOTE (pyogrio/FileGDB quirk): the field used in `where=` must also be
# included in `columns=`, or the filter silently returns 0 rows. Verified by
# direct comparison during inspection.
GEOM_LAYER = "MasterSurfWV_2025_noattr_clean"
ATTR_LAYER = "ParcelSummary"
COUNTY_FIELD = "CountyID"         # GEOM_LAYER, zero-padded string
ATTR_COUNTY_FIELD = "CountyCode"  # ATTR_LAYER, int
COUNTY_VALUE = {"54081": "41"}    # Raleigh

# CleanParcelID preferred per plan, and confirmed unique within Raleigh county
# on both layers during inspection (GEOM_LAYER: 60683/60683 unique;
# ATTR_LAYER: 64263/64263 unique). GISPID was NOT fully unique on GEOM_LAYER
# (60682 unique of 60683 rows), so it is not used.
ID_FIELD = "CleanParcelID"

# Owner / acreage / district / address fields that exist on ATTR_LAYER, plus
# Acres_C (GIS-calculated acreage) which lives on GEOM_LAYER itself.
ATTR_KEEP_FIELDS = [
    "FullOwnerName", "DeededAcres", "CalculatedAcres", "DistrictName",
    "TaxDistrict", "FullPhysicalAddress", "PropertyClassDescription",
]
KEEP_FIELDS = ATTR_KEEP_FIELDS + ["Acres_C"]


def load_county_parcels(fips):
    gdb = next(Path(paths.raw_dir("parcels")).glob("*.gdb"))
    county = COUNTY_VALUE[fips]

    parcels = gpd.read_file(gdb, layer=GEOM_LAYER,
                            columns=[ID_FIELD, "Acres_C", COUNTY_FIELD],
                            where=f"{COUNTY_FIELD} = '{county}'")
    if parcels.empty:
        raise RuntimeError(f"parcels: 0 features for {COUNTY_FIELD}={county} — "
                           f"wrong filter value; re-run the inspection step")
    if not parcels[ID_FIELD].is_unique:
        raise RuntimeError(f"parcels: {ID_FIELD} is not unique within county {fips} "
                           f"({parcels[ID_FIELD].duplicated().sum()} dupes) — pick another ID field")

    attrs = pyogrio.read_dataframe(gdb, layer=ATTR_LAYER, read_geometry=False,
                                   columns=[ID_FIELD, ATTR_COUNTY_FIELD] + ATTR_KEEP_FIELDS,
                                   where=f"{ATTR_COUNTY_FIELD} = {int(county)}")
    if attrs.empty:
        raise RuntimeError(f"parcels: 0 rows in {ATTR_LAYER} for {ATTR_COUNTY_FIELD}={county} — "
                           f"wrong filter value; re-run the inspection step")
    if not attrs[ID_FIELD].is_unique:
        raise RuntimeError(f"parcels: {ATTR_LAYER}.{ID_FIELD} is not unique within county {fips} "
                           f"({attrs[ID_FIELD].duplicated().sum()} dupes) — cannot safely join attributes")

    parcels = parcels.rename(columns={ID_FIELD: "parcel_id"}).drop(columns=[COUNTY_FIELD])
    attrs = attrs.rename(columns={ID_FIELD: "parcel_id"}).drop(columns=[ATTR_COUNTY_FIELD])
    before = len(parcels)
    parcels = parcels.merge(attrs, on="parcel_id", how="left")
    unmatched = int(parcels["FullOwnerName"].isna().sum())
    if unmatched:
        print(f"parcels: {unmatched}/{before} parcels have no {ATTR_LAYER} attribute match "
              f"(kept, attribute fields left blank)")

    invalid = ~parcels.geometry.is_valid
    if invalid.any():
        print(f"parcels: repairing {int(invalid.sum())} invalid geometries")
        parcels.loc[invalid, "geometry"] = parcels.loc[invalid, "geometry"].apply(make_valid)

    keep = ["parcel_id"] + [f for f in KEEP_FIELDS if f in parcels.columns] + ["geometry"]
    parcels = parcels[keep]
    print(f"parcels: {len(parcels)} parcels for {fips}")
    return parcels
