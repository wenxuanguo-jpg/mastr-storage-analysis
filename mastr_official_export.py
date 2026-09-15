"""Process the official MaStR export for two balcony categories.

The full official export is downloaded to the ephemeral GitHub Actions runner
and processed row by row. It is never loaded into RAM as one dataframe.

Balcony PV:
    Registrierungsdatum der Einheit > 2023-01-01
    Art der Solaranlage == Steckerfertige Solaranlage (sog. Balkonkraftwerk)

Balcony storage:
    Registrierungsdatum der Einheit > 2023-01-01
    Nettonennleistung der Einheit == 0.8 kW
    Energieträger == Speicher
"""

from __future__ import annotations

import argparse
import csv
import gzip
import html
import io
import json
import os
import re
import sqlite3
import sys
import time
import zipfile
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple

import requests


ROOT_DIR = Path(__file__).resolve().parent
DOWNLOAD_PAGE = "https://www.marktstammdatenregister.de/MaStR/Datendownload"
FALLBACK_EXPORT_URL = (
    "https://download.marktstammdatenregister.de/"
    "Gesamtdatenexport_20260915_26.1.zip"
)
PUBLIC_SOURCE_PAGE = (
    "https://www.marktstammdatenregister.de/MaStR/Einheit/Einheiten/"
    "ErweiterteOeffentlicheEinheitenuebersicht"
)
DATE_CUTOFF = date(2023, 1, 1)
TARGET_POWER_KW = 0.8
TARGET_PV_TYPE = "Steckerfertige Solaranlage (sog. Balkonkraftwerk)"
USER_AGENT = "MaStR balcony trend research client/1.0"

F_ID = "MaStR-Nr. der Einheit"
F_NAME = "Anzeige-Name der Einheit"
F_STATUS = "Betriebs-Status"
F_ENERGY = "Energieträger"
F_POWER = "Nettonennleistung der Einheit"
F_REGISTERED = "Registrierungsdatum der Einheit"
F_STATE = "Bundesland"
F_DISTRICT = "Landkreis"
F_MUNICIPALITY = "Gemeinde"
F_ZIP = "Postleitzahl"
F_TOWN = "Ort"
F_SOLAR_TYPE = "Art der Solaranlage"
F_SOLAR_TECH = "Technologie der Stromerzeugung"
F_MODULES = "Anzahl der Solar-Module"
F_DIRECTION = "Hauptausrichtung der Solar-Module"
F_INCLINATION = "Hauptneigungswinkel der Solar-Module"
F_BUILDING_USE = "Nutzungsbereich des Gebäudes mit Solaranlage"
F_STORAGE_TECH = "Speichertechnologie"
F_CAPACITY = "Nutzbare Speicherkapazität in kWh"
F_COUPLING = "AC/DC-Koppelung"

ALIASES: Dict[str, Tuple[str, ...]] = {
    "id": (F_ID, "EinheitMastrNummer"),
    "name": (F_NAME, "NameStromerzeugungseinheit"),
    "status": (F_STATUS, "EinheitBetriebsstatus", "EinheitSystemstatus"),
    "energy": (F_ENERGY, "Energietraeger"),
    "power": (F_POWER, "Nettonennleistung"),
    "registered": (F_REGISTERED, "Registrierungsdatum"),
    "state": (F_STATE, "Bundesland"),
    "district": (F_DISTRICT, "Landkreis"),
    "municipality": (F_MUNICIPALITY, "Gemeinde"),
    "zip": (F_ZIP, "Postleitzahl"),
    "town": (F_TOWN, "Ort"),
    "solar_type": (F_SOLAR_TYPE, "ArtDerSolaranlage"),
    "solar_tech": (F_SOLAR_TECH, "TechnologieDerStromerzeugung"),
    "modules": (F_MODULES, "AnzahlDerSolarModule"),
    "direction": (F_DIRECTION, "HauptausrichtungDerSolarModule"),
    "inclination": (F_INCLINATION, "HauptneigungswinkelDerSolarModule"),
    "building_use": (F_BUILDING_USE, "NutzungsbereichDesGebaeudesMitSolaranlage"),
    "storage_tech": (F_STORAGE_TECH, "Batterietechnologie", "Speichertechnologie"),
    "capacity": (F_CAPACITY, "NutzbareSpeicherkapazitaet"),
    "coupling": (F_COUPLING, "AcDcKoppelung"),
}

FEATURE_FIELDS = {
    "state": ALIASES["state"],
    "district": ALIASES["district"],
    "municipality": ALIASES["municipality"],
    "status": ALIASES["status"],
    "energy": ALIASES["energy"],
    "solar_type": ALIASES["solar_type"],
    "solar_tech": ALIASES["solar_tech"],
    "storage_tech": ALIASES["storage_tech"],
    "coupling": ALIASES["coupling"],
    "capacity": ALIASES["capacity"],
    "name": ALIASES["name"],
}

DEFAULT_WORK_DIR = Path(
    os.environ.get(
        "MASTR_WORK_DIR",
        str(Path(os.environ.get("RUNNER_TEMP", str(ROOT_DIR / "tmp"))) / "mastr_export"),
    )
)
DEFAULT_OUTPUT_DIR = Path(os.environ.get("MASTR_OUTPUT_DIR", str(ROOT_DIR / "outputs")))
DEFAULT_SITE_DIR = Path(os.environ.get("MASTR_SITE_DIR", str(ROOT_DIR / "site")))


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def get_value(row: Mapping[str, str], aliases: Sequence[str]) -> str:
    for key in aliases:
        if key in row:
            value = clean(row[key])
            if value:
                return value
    return ""


def parse_date(raw: str) -> Optional[date]:
    value = clean(raw)
    if not value:
        return None
    for pattern in (
        r"^(\d{4})/(\d{1,2})/(\d{1,2})",
        r"^(\d{4})-(\d{1,2})-(\d{1,2})",
        r"^(\d{1,2})\.(\d{1,2})\.(\d{4})",
    ):
        match = re.match(pattern, value)
        if not match:
            continue
        try:
            values = tuple(int(item) for item in match.groups())
            return (
                date(values[0], values[1], values[2])
                if pattern.startswith(r"^(\d{4})")
                else date(values[2], values[1], values[0])
            )
        except ValueError:
            return None
    return None


def parse_number(raw: str) -> Optional[float]:
    value = clean(raw).replace(" ", "").replace(",", ".")
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def discover_export_url() -> str:
    try:
        response = requests.get(
            DOWNLOAD_PAGE,
            headers={"User-Agent": USER_AGENT},
            timeout=(30, 90),
        )
        response.raise_for_status()
        page = html.unescape(response.text)
        matches = re.findall(
            r"(?i)(?:https?://|//)?download\.marktstammdatenregister\.de/"
            r"(?:Stichtag/)?Gesamtdatenexport_[^\"'<>\s]+?\.zip",
            page,
        )
        candidates: List[str] = []
        for match in matches:
            if match.startswith("//"):
                match = "https:" + match
            elif not match.startswith("http"):
                match = "https://" + match
            candidates.append(match)
        candidates = list(dict.fromkeys(candidates))
        if candidates:
            current = [item for item in candidates if "/Stichtag/" not in item]
            return sorted(current or candidates)[-1]
        print("No export link found; using fallback URL.", flush=True)
    except requests.RequestException as exc:
        print(f"Download page unavailable ({exc}); using fallback URL.", flush=True)
    return FALLBACK_EXPORT_URL


def download_resumable(url: str, destination: Path) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    existing = destination.stat().st_size if destination.exists() else 0
    headers = {"User-Agent": USER_AGENT}
    if existing:
        headers["Range"] = f"bytes={existing}-"
    with requests.get(url, headers=headers, stream=True, timeout=(60, 600)) as response:
        if existing and response.status_code == 206:
            mode = "ab"
            length = int(response.headers.get("content-length", "0"))
            total = existing + length if length else 0
        elif response.status_code == 200:
            mode = "wb"
            existing = 0
            total = int(response.headers.get("content-length", "0"))
        else:
            response.raise_for_status()
            raise RuntimeError(f"Unexpected HTTP status {response.status_code}")
        downloaded = existing
        last_report = time.monotonic()
        with destination.open(mode) as output:
            for chunk in response.iter_content(chunk_size=8 * 1024 * 1024):
                if not chunk:
                    continue
                output.write(chunk)
                downloaded += len(chunk)
                now = time.monotonic()
                if now - last_report >= 5:
                    suffix = f" ({downloaded / total:.1%})" if total else ""
                    print(f"downloaded {downloaded / 1024**3:.2f} GB{suffix}", flush=True)
                    last_report = now
    size = destination.stat().st_size
    if total and size != total:
        raise RuntimeError(f"Incomplete download: {size} bytes, expected {total}")
    return size


def csv_member_names(archive: zipfile.ZipFile) -> List[str]:
    return sorted(
        item for item in archive.namelist()
        if item.lower().endswith(".csv")
        and "stromerzeug" in Path(item).name.lower()
    )


def catalog_member_names(archive: zipfile.ZipFile) -> List[str]:
    return sorted(
        item
        for item in archive.namelist()
        if item.lower().endswith(".xml")
        and "katalogwerte" in Path(item).name.lower()
    )


def xml_member_names(archive: zipfile.ZipFile) -> List[str]:
    return sorted(
        item for item in archive.namelist()
        if item.lower().endswith(".xml")
        and (
            "einheitensolar" in Path(item).name.lower()
            or "einheitenstromspeicher" in Path(item).name.lower()
        )
    )


def source_csv_rows(handle: io.BufferedIOBase) -> Iterator[Tuple[Dict[str, str], int]]:
    text = io.TextIOWrapper(handle, encoding="utf-8-sig", errors="replace", newline="")
    header = text.readline()
    if not header:
        return
    delimiter = ";" if header.count(";") >= header.count(",") else ","
    reader = csv.DictReader(_prepend_line(header, text), delimiter=delimiter)
    if not reader.fieldnames:
        return
    reader.fieldnames = [clean(name).lstrip("\ufeff") for name in reader.fieldnames]
    for line_number, raw_row in enumerate(reader, 2):
        yield (
            {clean(key): clean(value) for key, value in raw_row.items() if key is not None},
            line_number,
        )


def _prepend_line(first: str, rest: io.TextIOBase) -> Iterator[str]:
    yield first
    yield from rest


def source_xml_rows(
    handle: io.BufferedIOBase,
    row_names: Optional[Sequence[str]] = None,
) -> Iterator[Tuple[Dict[str, str], int]]:
    from lxml import etree

    def local_name(tag: object) -> str:
        return str(tag).rsplit("}", 1)[-1]

    wanted = set(row_names or {
        "EinheitSolar",
        "EinheitStromSpeicher",
        "EinheitStromerzeugung",
        "EinheitStromerzeugungseinheit",
    })
    context = etree.iterparse(handle, events=("end",), huge_tree=True)
    row_number = 0
    for _, element in context:
        if local_name(element.tag) not in wanted:
            continue
        row = {local_name(child.tag): clean(child.text) for child in element}
        row_number += 1
        yield row, row_number
        parent = element.getparent()
        element.clear()
        if parent is not None:
            while element.getprevious() is not None:
                del parent[0]
    del context


def xml_catalog_value(raw: str, catalog: Mapping[str, str]) -> str:
    value = clean(raw)
    return catalog.get(value, value)


def normalize_xml_row(row: Mapping[str, str], catalog: Mapping[str, str]) -> Dict[str, str]:
    """Add the public-table field names and resolve official catalog IDs."""
    normalized = dict(row)

    def copy_field(public_name: str, xml_name: str, resolve: bool = False) -> None:
        raw = clean(row.get(xml_name, ""))
        if raw:
            normalized[public_name] = xml_catalog_value(raw, catalog) if resolve else raw

    copy_field(F_ID, "EinheitMastrNummer")
    copy_field(F_NAME, "NameStromerzeugungseinheit")
    copy_field(F_STATUS, "EinheitBetriebsstatus", resolve=True)
    copy_field(F_ENERGY, "Energietraeger", resolve=True)
    copy_field(F_POWER, "Nettonennleistung")
    copy_field(F_REGISTERED, "Registrierungsdatum")
    copy_field(F_STATE, "Bundesland", resolve=True)
    copy_field(F_DISTRICT, "Landkreis")
    copy_field(F_MUNICIPALITY, "Gemeinde")
    copy_field(F_ZIP, "Postleitzahl")
    copy_field(F_TOWN, "Ort")
    copy_field(F_SOLAR_TYPE, "ArtDerSolaranlage", resolve=True)
    copy_field(F_SOLAR_TECH, "Technologie", resolve=True)
    copy_field(F_MODULES, "AnzahlModule")
    copy_field(F_DIRECTION, "Hauptausrichtung", resolve=True)
    copy_field(F_INCLINATION, "HauptausrichtungNeigungswinkel", resolve=True)
    copy_field(F_BUILDING_USE, "Nutzungsbereich", resolve=True)
    copy_field(F_STORAGE_TECH, "Batterietechnologie", resolve=True)
    copy_field(F_CAPACITY, "NutzbareSpeicherkapazitaet")
    copy_field(F_COUPLING, "AcDcKoppelung", resolve=True)
    return normalized


class CategoryStats:
    def __init__(self, label: str) -> None:
        self.label = label
        self.count = 0
        self.unique_ids = 0
        self.monthly: Counter[str] = Counter()
        self.annual: Counter[str] = Counter()
        self.features: Dict[str, Counter[str]] = {
            name: Counter() for name in FEATURE_FIELDS
        }
        self.first_date: Optional[date] = None
        self.last_date: Optional[date] = None

    def observe(self, row: Mapping[str, str], registered: date) -> None:
        self.count += 1
        month = registered.strftime("%Y-%m")
        self.monthly[month] += 1
        self.annual[str(registered.year)] += 1
        self.first_date = registered if self.first_date is None else min(self.first_date, registered)
        self.last_date = registered if self.last_date is None else max(self.last_date, registered)
        for feature, aliases in FEATURE_FIELDS.items():
            self.features[feature][get_value(row, aliases) or "(keine Angabe)"] += 1

    def monthly_rows(self) -> List[Dict[str, object]]:
        total = max(self.count, 1)
        cumulative = 0
        result: List[Dict[str, object]] = []
        for month in sorted(self.monthly):
            count = self.monthly[month]
            cumulative += count
            result.append({
                "month": month,
                "registrations": count,
                "share": round(count / total, 6),
                "cumulative": cumulative,
            })
        return result

    def annual_rows(self) -> List[Dict[str, object]]:
        return [
            {"year": year, "registrations": self.annual[year]}
            for year in sorted(self.annual)
        ]


class SeenIds:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute("PRAGMA journal_mode=OFF")
        self.connection.execute("PRAGMA synchronous=OFF")
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS seen (category TEXT NOT NULL, unit_id TEXT NOT NULL, PRIMARY KEY(category, unit_id))"
        )
        self.pending = 0

    def add(self, category: str, unit_id: str) -> bool:
        cursor = self.connection.execute(
            "INSERT OR IGNORE INTO seen(category, unit_id) VALUES (?, ?)",
            (category, unit_id),
        )
        self.pending += 1
        if self.pending >= 5000:
            self.connection.commit()
            self.pending = 0
        return cursor.rowcount == 1

    def close(self) -> None:
        self.connection.commit()
        self.connection.close()


class OutputWriters:
    def __init__(self, output_dir: Path, site_data_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        site_data_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir = output_dir
        self.site_data_dir = site_data_dir
        self.csv_files: Dict[str, Tuple[io.TextIOBase, csv.DictWriter]] = {}
        self.gzip_files: Dict[str, gzip.GzipFile] = {}

    def write(self, category: str, row: Mapping[str, str], source_name: str, fields: Sequence[str]) -> None:
        if category not in self.csv_files:
            filename = "balcony_pv.csv" if category == "pv" else "balcony_storage.csv"
            output = (self.output_dir / filename).open("w", newline="", encoding="utf-8-sig")
            columns = list(fields)
            for extra in ("Kategorie", "Quelle"):
                if extra not in columns:
                    columns.append(extra)
            writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            self.csv_files[category] = (output, writer)
        output, writer = self.csv_files[category]
        enriched = dict(row)
        enriched["Kategorie"] = "阳台光伏" if category == "pv" else "阳台储能"
        enriched["Quelle"] = source_name
        writer.writerow(enriched)

        if category not in self.gzip_files:
            name = "records_pv.ndjson.gz" if category == "pv" else "records_storage.ndjson.gz"
            self.gzip_files[category] = gzip.open(
                self.site_data_dir / name, "wt", encoding="utf-8"
            )
        compact = compact_record(enriched, category)
        self.gzip_files[category].write(
            json.dumps(compact, ensure_ascii=False, separators=(",", ":")) + "\n"
        )

    def close(self) -> None:
        for output, _writer in self.csv_files.values():
            output.close()
        for stream in self.gzip_files.values():
            stream.close()


def compact_record(row: Mapping[str, str], category: str) -> Dict[str, str]:
    def value(name: str) -> str:
        return get_value(row, ALIASES[name])

    return {
        "id": value("id"),
        "name": value("name"),
        "status": value("status"),
        "energy": value("energy"),
        "power": value("power"),
        "registered": value("registered"),
        "state": value("state"),
        "district": value("district"),
        "municipality": value("municipality"),
        "zip": value("zip"),
        "town": value("town"),
        "solarType": value("solar_type"),
        "solarTech": value("solar_tech"),
        "modules": value("modules"),
        "direction": value("direction"),
        "inclination": value("inclination"),
        "buildingUse": value("building_use"),
        "storageTech": value("storage_tech"),
        "capacity": value("capacity"),
        "coupling": value("coupling"),
        "category": "pv" if category == "pv" else "storage",
    }


def matches(category: str, row: Mapping[str, str]) -> Tuple[bool, Optional[date]]:
    registered = parse_date(get_value(row, ALIASES["registered"]))
    if registered is None or registered <= DATE_CUTOFF:
        return False, registered
    if category == "pv":
        return get_value(row, ALIASES["solar_type"]) == TARGET_PV_TYPE, registered
    power = parse_number(get_value(row, ALIASES["power"]))
    return (
        power is not None
        and abs(power - TARGET_POWER_KW) <= 1e-9
        and get_value(row, ALIASES["energy"]) == "Speicher",
        registered,
    )


def iter_members(source_path: Path) -> Iterator[Tuple[str, Iterable[Tuple[Dict[str, str], int]]]]:
    if source_path.suffix.lower() == ".csv":
        yield source_path.name, source_csv_rows(source_path.open("rb"))
        return
    if source_path.suffix.lower() != ".zip":
        raise RuntimeError(f"Unsupported source file: {source_path}")
    archive = zipfile.ZipFile(source_path)
    names = csv_member_names(archive)
    if names:
        for name in names:
            yield name, source_csv_rows(archive.open(name))
        archive.close()
        return

    catalog: Dict[str, str] = {}
    for name in catalog_member_names(archive):
        with archive.open(name) as handle:
            for row, _line_number in source_xml_rows(handle, row_names=("Katalogwert",)):
                item_id = clean(row.get("Id", ""))
                item_value = clean(row.get("Wert", ""))
                if item_id and item_value:
                    catalog[item_id] = item_value

    names = xml_member_names(archive)
    if not names:
        archive.close()
        raise RuntimeError("The official ZIP contains no EinheitenSolar or EinheitenStromSpeicher XML member.")
    for name in names:
        def normalized_rows(member_name: str = name) -> Iterator[Tuple[Dict[str, str], int]]:
            with archive.open(member_name) as handle:
                for row, line_number in source_xml_rows(handle):
                    yield normalize_xml_row(row, catalog), line_number

        yield name, normalized_rows()
    archive.close()


def top_features(stats: CategoryStats, limit: int = 12) -> Dict[str, List[Dict[str, object]]]:
    return {
        feature: [
            {"value": value, "count": count}
            for value, count in counter.most_common(limit)
        ]
        for feature, counter in stats.features.items()
    }


def insight_lines(stats: CategoryStats) -> List[str]:
    if not stats.count:
        return [f"{stats.label}没有匹配记录，需检查官方导出包字段或筛选口径。"]
    lines = [f"按当前 MaStR 筛选口径，共有 **{stats.count:,}** 条登记记录。"]
    if stats.first_date and stats.last_date:
        lines.append(
            f"登记日期覆盖 **{stats.first_date.isoformat()} 至 {stats.last_date.isoformat()}**。"
        )
    peak_month, peak_count = max(stats.monthly.items(), key=lambda item: item[1])
    lines.append(f"月度峰值为 **{peak_month}**，共 {peak_count:,} 条。")
    state = stats.features["state"].most_common(1)
    if state and state[0][0] != "(keine Angabe)":
        lines.append(
            f"登记最多的州是 **{state[0][0]}**，占 {state[0][1] / stats.count:.1%}。"
        )
    recent_months = sorted(stats.monthly)[-3:]
    if recent_months:
        lines.append(
            f"最近 {len(recent_months)} 个数据月合计 "
            f"{sum(stats.monthly[item] for item in recent_months):,} 条。"
        )
    return lines


def write_analysis(
    source_url: str,
    export_name: str,
    generated_at: str,
    stats: Mapping[str, CategoryStats],
    output_dir: Path,
    site_data_dir: Path,
    scanned: int,
    source_members: int,
) -> Dict[str, object]:
    categories: Dict[str, object] = {}
    monthly: Dict[str, object] = {}
    features: Dict[str, object] = {}
    insights: Dict[str, object] = {}
    for key, item in stats.items():
        categories[key] = {
            "label": item.label,
            "matching_records": item.count,
            "unique_unit_ids": item.unique_ids,
            "first_registration_date": item.first_date.isoformat() if item.first_date else None,
            "last_registration_date": item.last_date.isoformat() if item.last_date else None,
            "annual": item.annual_rows(),
        }
        monthly[key] = item.monthly_rows()
        features[key] = top_features(item)
        insights[key] = insight_lines(item)
    summary: Dict[str, object] = {
        "generated_at_utc": generated_at,
        "source_page": PUBLIC_SOURCE_PAGE,
        "source_download_page": DOWNLOAD_PAGE,
        "source_export": export_name,
        "source_url": source_url,
        "filters": {
            "registration_date": "> 2023-01-01",
            "balcony_pv_solar_type": TARGET_PV_TYPE,
            "balcony_storage_power_kw": TARGET_POWER_KW,
            "balcony_storage_energy_carrier": "Speicher",
        },
        "categories": categories,
        "monthly": monthly,
        "features": features,
        "insights": insights,
        "validation": {
            "source_members": source_members,
            "source_rows_scanned": scanned,
            "monthly_totals_equal_counts": all(
                sum(item.monthly.values()) == item.count for item in stats.values()
            ),
            "unique_ids_equal_counts": all(
                item.unique_ids == item.count for item in stats.values()
            ),
        },
        "notes": [
            "统计口径是官方 MaStR 全量导出包中登记日期严格大于 2023-01-01 的记录。",
            "储能的 0.8 kW 匹配同时兼容官方 CSV 中的 0,8 和 0.8 写法。",
            "MaStR 没有公开字段能证明每一条 0.8 kW Speicher 都是物理上的插入式产品；阳台储能标签沿用用户给定筛选口径。",
            "扩展单位总览包含截至数据日已新登记或变更的公开记录，统计不是销量。",
        ],
    }
    site_data_dir.mkdir(parents=True, exist_ok=True)
    for filename, payload in (
        ("summary.json", summary),
        ("monthly.json", monthly),
        ("features.json", features),
    ):
        (site_data_dir / filename).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    for filename, payload in (
        ("mastr_dashboard_summary.json", summary),
        ("mastr_dashboard_monthly.json", monthly),
        ("mastr_dashboard_features.json", features),
    ):
        (output_dir / filename).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    report = [
        "# MaStR 阳台光伏与阳台储能分析",
        "",
        f"数据包：{export_name}",
        f"生成时间（UTC）：{generated_at}",
        "",
        "| 品类 | 登记数 | 日期范围 |",
        "|---|---:|---|",
    ]
    for key, label in (("pv", "阳台光伏"), ("storage", "阳台储能")):
        item = categories[key]
        report.append(
            f"| {label} | {item['matching_records']:,} | "
            f"{item['first_registration_date']} 至 {item['last_registration_date']} |"
        )
    report += ["", "## 自动分析", ""]
    for key, label in (("pv", "阳台光伏"), ("storage", "阳台储能")):
        report += [f"### {label}", ""]
        report += [f"- {line}" for line in insights[key]]
        report.append("")
    report += [
        "## 口径与限制",
        "",
        *[f"- {note}" for note in summary["notes"]],
        "",
        "完整筛选明细位于同一次 GitHub Actions 的 artifact；在线看板加载压缩后的交互字段。",
    ]
    (output_dir / "mastr_dashboard_analysis.md").write_text(
        "\n".join(report) + "\n", encoding="utf-8"
    )
    return summary


def process(source_path: Path, source_url: str, output_dir: Path, site_dir: Path) -> Dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    site_data_dir = site_dir / "data"
    site_data_dir.mkdir(parents=True, exist_ok=True)
    for path in site_data_dir.iterdir():
        if path.is_file():
            path.unlink()
    for filename in ("balcony_pv.csv", "balcony_storage.csv"):
        path = output_dir / filename
        if path.exists():
            path.unlink()

    stats = {"pv": CategoryStats("阳台光伏"), "storage": CategoryStats("阳台储能")}
    # A run must start with an empty de-duplication index. The index is only a
    # run-time guard against duplicate rows inside one export, not a history DB.
    seen_path = output_dir.parent / "mastr_seen.sqlite"
    if seen_path.exists():
        seen_path.unlink()
    seen = SeenIds(seen_path)
    writers = OutputWriters(output_dir, site_data_dir)
    fields: List[str] = []
    scanned = 0
    source_members = 0
    try:
        for source_name, rows in iter_members(source_path):
            source_members += 1
            print(f"processing {source_members}: {source_name}", flush=True)
            for row, _line_number in rows:
                scanned += 1
                if scanned % 250000 == 0:
                    print(f"scanned {scanned:,} source rows", flush=True)
                if not fields:
                    fields = list(row.keys())
                for category in ("pv", "storage"):
                    matched, registered = matches(category, row)
                    if not matched or registered is None:
                        continue
                    unit_id = get_value(row, ALIASES["id"]) or f"{source_name}:{scanned}"
                    if not seen.add(category, unit_id):
                        continue
                    stats[category].unique_ids += 1
                    stats[category].observe(row, registered)
                    writers.write(category, row, source_name, fields)
        if not fields:
            raise RuntimeError("No rows found in the official source.")
    finally:
        writers.close()
        seen.close()

    # Keep the artifact and the dashboard valid even if one category has zero
    # matches in a future export.
    for category, filename in (("pv", "balcony_pv.csv"), ("storage", "balcony_storage.csv")):
        csv_path = output_dir / filename
        if not csv_path.exists():
            columns = list(fields) + ["Kategorie", "Quelle"]
            with csv_path.open("w", newline="", encoding="utf-8-sig") as output:
                csv.DictWriter(output, fieldnames=columns).writeheader()
        gzip_name = "records_pv.ndjson.gz" if category == "pv" else "records_storage.ndjson.gz"
        gzip_path = site_data_dir / gzip_name
        if not gzip_path.exists():
            with gzip.open(gzip_path, "wt", encoding="utf-8"):
                pass

    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    summary = write_analysis(
        source_url,
        source_path.name,
        generated_at,
        stats,
        output_dir,
        site_data_dir,
        scanned,
        source_members,
    )
    print(f"Scanned source rows: {scanned:,}", flush=True)
    print(f"Balcony PV records: {stats['pv'].count:,}", flush=True)
    print(f"Balcony storage records: {stats['storage'].count:,}", flush=True)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-path", type=Path)
    parser.add_argument("--export-url", default="")
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--site-dir", type=Path, default=DEFAULT_SITE_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.source_path:
        source_path = args.source_path.resolve()
        source_url = "local test/source path"
    else:
        source_url = args.export_url or discover_export_url()
        source_path = args.work_dir / "Gesamtdatenexport_latest.zip"
        print(f"Official export: {source_url}", flush=True)
        print(f"Downloading to runner temporary directory: {source_path}", flush=True)
        size = download_resumable(source_url, source_path)
        print(f"Downloaded {size / 1024**3:.2f} GB", flush=True)
    if source_path.suffix.lower() == ".zip":
        try:
            with zipfile.ZipFile(source_path) as archive:
                names = csv_member_names(archive) or xml_member_names(archive)
                if not names:
                    raise RuntimeError("No Stromerzeuger members found in the ZIP.")
                print(f"Source members: {len(names)}", flush=True)
        except zipfile.BadZipFile as exc:
            raise RuntimeError("Source is not a complete ZIP; rerun to resume.") from exc
    process(source_path, source_url, args.output_dir.resolve(), args.site_dir.resolve())
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted. Re-run to resume the source download.", file=sys.stderr)
        raise SystemExit(130)
