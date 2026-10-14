"""Inspect storage voltage joins on a runner; emit aggregate counts only."""

import json
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

from mastr_official_export import (
    TARGET_POWER_KW, catalog_member_names, clean, discover_export_url,
    download_resumable, parse_args, parse_number, source_xml_rows,
    xml_catalog_value,
)


def references(row, prefix):
    # Compare field spelling without assuming the official casing is stable.
    return {
        key: clean(value) for key, value in row.items()
        if key.casefold().startswith(prefix.casefold()) and clean(value)
    }


def inspect(source):
    counts = Counter()
    fields = defaultdict(Counter)
    connections = {}
    location_connections = defaultdict(set)
    location_voltages = defaultdict(set)
    old_locations = {}
    old_voltages = {}
    old_connection_voltages = {}
    connection_voltages = defaultdict(set)
    storage = defaultdict(Counter)
    with zipfile.ZipFile(source) as archive:
        catalog = {}
        for name in catalog_member_names(archive):
            with archive.open(name) as handle:
                for row, _ in source_xml_rows(handle, row_names=('Katalogwert',)):
                    catalog[clean(row.get('Id', ''))] = clean(row.get('Wert', ''))
        for name in sorted(archive.namelist()):
            basename = Path(name).name.lower()
            if not basename.endswith('.xml') or not any(
                part in basename for part in ('lokationen', 'netzanschlusspunkte')
            ):
                continue
            with archive.open(name) as handle:
                for row, _ in source_xml_rows(handle, row_names=('Lokation', 'Netzanschlusspunkt')):
                    kind = 'connection' if 'netzanschlusspunkte' in basename else 'location'
                    counts[kind + '_rows'] += 1
                    for key, value in row.items():
                        if clean(value):
                            fields[kind][key] += 1
                    locs = references(row, 'Lokation')
                    conns = references(row, 'Netzanschlusspunkt')
                    loc = next((v for k, v in locs.items() if k.casefold() == 'lokationmastrnummer'), '')
                    conn = next((v for k, v in conns.items() if k.casefold() == 'netzanschlusspunktmastrnummer'), '')
                    voltage = xml_catalog_value(row.get('Spannungsebene', ''), catalog)
                    if conn:
                        connections[conn] = True
                        if voltage:
                            connection_voltages[conn].add(voltage)
                    if loc:
                        if voltage:
                            location_voltages[loc].add(voltage)
                        if conn:
                            location_connections[loc].add(conn)
                    old_loc = clean(row.get('LokationMaStRNummer', '') or row.get('LokationMastrNummer', ''))
                    old_conn = clean(row.get('NetzanschlusspunktMastrNummer', ''))
                    if old_loc and voltage:
                        old_voltages[old_loc] = voltage
                    if old_conn and voltage:
                        old_connection_voltages[old_conn] = voltage
                    if old_loc and old_conn:
                        old_locations[old_loc] = old_conn
        for loc, conn in old_locations.items():
            if loc not in old_voltages and conn in old_connection_voltages:
                old_voltages[loc] = old_connection_voltages[conn]
        counts['locations_multiple_connections'] = sum(len(v) > 1 for v in location_connections.values())
        counts['connections_conflicting_voltages'] = sum(len(v) > 1 for v in connection_voltages.values())
        for name in sorted(archive.namelist()):
            if not Path(name).name.lower().startswith('einheitenstromspeicher') or not name.lower().endswith('.xml'):
                continue
            with archive.open(name) as handle:
                for row, _ in source_xml_rows(handle):
                    power = parse_number(row.get('Nettonennleistung', ''))
                    power_kind = 'missing_power' if power is None else (
                        'power_0_8' if abs(power - TARGET_POWER_KW) <= 1e-9 else 'other_power'
                    )
                    loc_refs = references(row, 'Lokation')
                    conn_refs = references(row, 'Netzanschlusspunkt')
                    for key in loc_refs.keys() | conn_refs.keys():
                        fields['storage_references'][key] += 1
                    loc = next((v for k, v in loc_refs.items() if k.casefold() == 'lokationmastrnummer'), '')
                    conn = next((v for k, v in conn_refs.items() if k.casefold() == 'netzanschlusspunktmastrnummer'), '')
                    direct = xml_catalog_value(row.get('Spannungsebene', ''), catalog)
                    old = direct or old_voltages.get(loc, '')
                    candidates = set(location_voltages.get(loc, ()))
                    for reference in location_connections.get(loc, ()):
                        candidates.update(connection_voltages.get(reference, ()))
                    if conn:
                        candidates.update(connection_voltages.get(conn, ()))
                    if direct:
                        reason = 'direct_voltage'
                    elif old:
                        reason = 'existing_join'
                    elif candidates:
                        reason = 'recovered_join'
                    elif not loc:
                        reason = 'missing_location_reference'
                    elif loc not in location_connections and loc not in location_voltages:
                        reason = 'location_not_found_or_no_connection'
                    elif not any(c in connections for c in location_connections.get(loc, ())):
                        reason = 'connection_not_found'
                    else:
                        reason = 'connection_voltage_missing'
                    candidate_label = '|'.join(sorted(candidates)) or '(missing)'
                    storage[reason][power_kind] += 1
                    storage['old_missing_candidates:' + candidate_label][power_kind] += int(not old)
    return {
        'join_counts': dict(counts),
        'populated_fields': {k: dict(v) for k, v in fields.items()},
        'storage_join_distribution': {k: dict(v) for k, v in sorted(storage.items())},
    }


def main():
    args = parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    source = args.source_path or args.work_dir / 'Gesamtdatenexport_latest.zip'
    if not args.source_path:
        download_resumable(args.export_url or discover_export_url(), source)
    result = inspect(source)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / 'storage_voltage_diagnostics.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8'
    )


if __name__ == '__main__':
    main()
