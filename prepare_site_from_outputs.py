"""Rebuild the static dashboard payload from a completed analysis artifact."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import shutil
from pathlib import Path
from typing import Dict, Iterable

from mastr_official_export import compact_record


FILES = {
    "mastr_dashboard_summary.json": "summary.json",
    "mastr_dashboard_monthly.json": "monthly.json",
    "mastr_dashboard_features.json": "features.json",
}


def read_rows(path: Path) -> Iterable[Dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        yield from csv.DictReader(source)


def write_records(source_path: Path, destination: Path, category: str) -> int:
    count = 0
    with gzip.open(destination, "wt", encoding="utf-8") as output:
        for row in read_rows(source_path):
            record = compact_record(row, category)
            output.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outputs", type=Path, required=True)
    parser.add_argument("--site", type=Path, required=True)
    args = parser.parse_args()

    data_dir = args.site / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    for source_name, destination_name in FILES.items():
        source = args.outputs / source_name
        if not source.is_file():
            raise FileNotFoundError(f"Missing analysis artifact file: {source}")
        shutil.copyfile(source, data_dir / destination_name)

    expected = {
        "pv": args.outputs / "balcony_pv.csv",
        "storage": args.outputs / "balcony_storage.csv",
    }
    counts = {}
    for category, source in expected.items():
        if not source.is_file():
            raise FileNotFoundError(f"Missing filtered data file: {source}")
        destination = data_dir / f"records_{category}.ndjson.gz"
        counts[category] = write_records(source, destination, category)

    summary = json.loads((data_dir / "summary.json").read_text(encoding="utf-8"))
    for category, expected_count in counts.items():
        actual_count = int(summary["categories"][category]["matching_records"])
        if actual_count != expected_count:
            raise RuntimeError(
                f"{category}: restored {expected_count:,} records, expected {actual_count:,}"
            )

    print(f"Restored dashboard data: PV {counts['pv']:,}; storage {counts['storage']:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
