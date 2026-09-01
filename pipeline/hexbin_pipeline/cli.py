import argparse


def main():
    p = argparse.ArgumentParser(prog="hexbin_pipeline",
                                description="WV parcel suitability measurement pipeline")
    p.add_argument("stage", choices=["fetch", "grid", "measure", "xwalk", "validate", "all"])
    p.add_argument("--fips", required=True, help="5-digit county FIPS, e.g. 54081")
    p.add_argument("--only", help="run a single measure module (slope|flood|water|roads|transmission|mined|landcover)")
    args = p.parse_args()
    if args.only and args.stage not in ("measure", "all"):
        p.error(f"--only applies to the measure stage, not '{args.stage}'")

    # local imports so a broken module only breaks its own stage
    if args.stage in ("fetch", "all"):
        from . import fetch
        fetch.run(args.fips)
    if args.stage in ("grid", "all"):
        from . import grid
        grid.run(args.fips)
    if args.stage in ("measure", "all"):
        from . import measure
        measure.run_all(args.fips, only=args.only)
    if args.stage in ("xwalk", "all"):
        from . import xwalk
        xwalk.run(args.fips)
    if args.stage in ("validate", "all"):
        from . import validate
        validate.run(args.fips)
