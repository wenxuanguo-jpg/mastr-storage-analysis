"""Print aggregate storage-filter diagnostics on a GitHub runner."""

import json
from collections import Counter, defaultdict

from mastr_official_export import (
    ALIASES, HOUSEHOLD_VOLTAGE, TARGET_POWER_KW, SeenIds,
    discover_export_url, download_resumable, get_value, iter_members,
    parse_args, parse_date, parse_number,
)

def diagnose(source_path, index_path):
    counts = defaultdict(Counter)
    seen = SeenIds(index_path)
    try:
        for member, rows in iter_members(source_path):
            print(f"Inspecting {member}", flush=True)
            for row, line in rows:
                if get_value(row, ALIASES["energy"]) != "Speicher":
                    continue
                voltage = get_value(row, ALIASES["voltage"]) or "(missing)"
                bucket = counts[voltage]
                bucket["source_rows"] += 1
                unit_id = get_value(row, ALIASES["id"]) or f"{member}:{line}"
                if not seen.add("diagnostic_storage", unit_id):
                    bucket["duplicate_rows"] += 1
                    continue
                bucket["unique_units"] += 1
                power = parse_number(get_value(row, ALIASES["power"]))
                kind = ("missing_power" if power is None else
                        "power_0_8" if abs(power - TARGET_POWER_KW) <= 1e-9 else "other_power")
                bucket[kind] += 1
                registered = parse_date(get_value(row, ALIASES["registered"]))
                bucket[f"{kind}_{'dated' if registered else 'undated'}"] += 1
    finally:
        seen.close()
    result = {
        "voltage_distribution": {key: dict(value) for key, value in sorted(counts.items())},
        "household_voltage": HOUSEHOLD_VOLTAGE,
        "low_voltage": dict(counts[HOUSEHOLD_VOLTAGE]),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return result

def main():
    args = parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    if args.source_path:
        source_path = args.source_path
    else:
        source_url = args.export_url or discover_export_url()
        source_path = args.work_dir / "Gesamtdatenexport_latest.zip"
        print(f"Official export: {source_url}", flush=True)
        download_resumable(source_url, source_path)
    index_path = args.work_dir / "storage_diagnostic_seen.sqlite"
    if index_path.exists():
        index_path.unlink()
    result = diagnose(source_path, index_path)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "storage_diagnostics.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

if __name__ == "__main__":
    main()
