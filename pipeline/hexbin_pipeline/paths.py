from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
WORK = ROOT / "data" / "work"
PROCESSED = ROOT / "data" / "processed"
CRITERIA = ROOT / "config" / "criteria.json"


def raw_dir(source: str) -> Path:
    d = RAW / source
    d.mkdir(parents=True, exist_ok=True)
    return d


def work_dir(fips: str) -> Path:
    d = WORK / fips
    d.mkdir(parents=True, exist_ok=True)
    return d


def processed_dir(fips: str) -> Path:
    d = PROCESSED / fips
    d.mkdir(parents=True, exist_ok=True)
    return d


def grid_path(fips: str) -> Path:
    return work_dir(fips) / "grid.parquet"
