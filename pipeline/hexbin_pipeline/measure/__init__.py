"""Measure modules: each exposes run(fips) -> Path writing measure_<name>.parquet."""


def run_all(fips, only=None):
    from . import flood, hwy_access, landcover, mined, roads, slope, transmission, water
    modules = {"slope": slope, "flood": flood, "water": water, "roads": roads,
               "transmission": transmission, "mined": mined, "landcover": landcover,
               "hwy_access": hwy_access}
    if only:
        if only not in modules:
            raise SystemExit(f"unknown measure module '{only}'; choose from {sorted(modules)}")
        modules = {only: modules[only]}
    for name, mod in modules.items():
        print(f"=== measure: {name} ===")
        mod.run(fips)
