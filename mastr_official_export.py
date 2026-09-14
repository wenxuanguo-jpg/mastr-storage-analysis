"""Download and analyse the official MaStR Gesamtdatenexport.

The official full export is an XML ZIP. This script downloads it with resume
support, reads only the storage XML inside the ZIP, filters the records, and
writes a CSV incrementally so that the full export is never loaded into RAM.

Filter:
    Registrierungsdatum > 2023-01-01
    Nettonennleistung == 0.8 kW

MaStR does not provide a reliable public "balcony storage" product category in
this export. The output therefore covers all electricity storage units matching
the two filters, rather than a strict Balkonspeicher classification.
"""

from __future__ import annotations

import csv
import html
import json
import os
import re
import sys
import time
import zipfile
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

import pandas as pd
import requests
from lxml import etree


DOWNLOAD_PAGE = "https://www.marktstammdatenregister.de/MaStR/Datendownload"
# Used only if the download page is temporarily unavailable. Normally the
# script discovers the current link from the official page.
FALLBACK_EXPORT_URL = (
    "https://download.marktstammdatenregister.de/"
    "Gesamtdatenexport_20260914_26.1.zip"
)

OUTPUT_DIR = Path(__file__).resolve().parent
WORK_DIR = Path(
    os.environ.get(
        "MASTR_WORK_DIR",
        str(Path(os.environ.get("RUNNER_TEMP", r"D:\MaStR_Official_Export")) / "mastr_export"),
    )
)
ZIP_PATH = WORK_DIR / "Gesamtdatenexport_latest.zip"
OUTPUT_PATH = OUTPUT_DIR / "mastr_storage_0.8kw.csv"
MONTHLY_PATH = OUTPUT_DIR / "mastr_storage_0.8kw_monthly.csv"
ANALYSIS_PATH = OUTPUT_DIR / "mastr_storage_0.8kw_analysis.json"
REPORT_PATH = OUTPUT_DIR / "mastr_storage_0.8kw_analysis.md"
CHART_PATH = OUTPUT_DIR / "mastr_storage_0.8kw_monthly.png"

DATE_CUTOFF = date(2023, 1, 1)
TARGET_POWER_KW = 0.8
USER_AGENT = "MaStR official export research client/1.0"


def discover_export_url() -> str:
    """Find the current official ZIP link, with a known-good fallback."""
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
        candidates = []
        for match in matches:
            if match.startswith("//"):
                match = "https:" + match
            elif not match.startswith("http"):
                match = "https://" + match
            candidates.append(match)
        candidates = list(dict.fromkeys(candidates))
        if candidates:
            # Prefer the current export (without the historical Stichtag path),
            # then choose the newest date/version shown on the official page.
            current = [candidate for candidate in candidates if "/Stichtag/" not in candidate]
            return sorted(current or candidates)[-1]
        print("No export link found on the official page; using fallback URL.")
    except requests.RequestException as exc:
        print(f"Official download page unavailable ({exc}); using fallback URL.")
    return FALLBACK_EXPORT_URL


def download_resumable(url: str, destination: Path) -> int:
    """Download a URL, resuming a partial file when the server supports Range."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    existing = destination.stat().st_size if destination.exists() else 0
    headers = {"User-Agent": USER_AGENT}
    if existing:
        headers["Range"] = f"bytes={existing}-"

    with requests.get(
        url,
        headers=headers,
        stream=True,
        timeout=(60, 300),
    ) as response:
        if existing and response.status_code == 206:
            mode = "ab"
            content_length = int(response.headers.get("content-length", "0"))
            total = existing + content_length if content_length else 0
        elif response.status_code == 200:
            if existing:
                print("Server did not resume the partial file; restarting download.")
            mode = "wb"
            existing = 0
            total = int(response.headers.get("content-length", "0"))
        else:
            response.raise_for_status()
            raise RuntimeError(f"Unexpected HTTP status: {response.status_code}")

        downloaded = existing
        last_report = time.monotonic()
        with destination.open(mode) as output:
            for chunk in response.iter_content(chunk_size=4 * 1024 * 1024):
                if not chunk:
                    continue
                output.write(chunk)
                downloaded += len(chunk)
                now = time.monotonic()
                if now - last_report >= 5:
                    if total:
                        percent = downloaded / total * 100
                        progress = f" ({percent:.1f}%)"
                    else:
                        progress = ""
                    print(
                        f"downloaded {downloaded / 1024**3:.2f} GB"
                        f" / {total / 1024**3:.2f} GB{progress}",
                        flush=True,
                    )
                    last_report = now

    size = destination.stat().st_size
    if total and size != total:
        raise RuntimeError(f"Incomplete download: {size} bytes, expected {total}")
    return size


def local_name(tag: object) -> str:
    return str(tag).rsplit("}", 1)[-1]


def child_values(element: etree._Element) -> Dict[str, str]:
    """Return all direct leaf fields from one storage record."""
    values: Dict[str, str] = {}
    for child in element:
        values[local_name(child.tag)] = (child.text or "").strip()
    return values


def parse_date(raw: str) -> Optional[date]:
    raw = (raw or "").strip()
    if not raw:
        return None
    iso = re.match(r"^(\d{4}-\d{2}-\d{2})", raw)
    if iso:
        try:
            return date.fromisoformat(iso.group(1))
        except ValueError:
            return None
    german = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", raw)
    if german:
        try:
            return date(
                int(german.group(3)), int(german.group(2)), int(german.group(1))
            )
        except ValueError:
            return None
    return None


def parse_number(raw: str) -> Optional[float]:
    raw = (raw or "").strip().replace(",", ".")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def iter_storage_records(xml_file) -> Iterator[Dict[str, str]]:
    """Stream only ``EinheitStromSpeicher`` records from one XML member."""
    context = etree.iterparse(xml_file, events=("end",), huge_tree=True)
    for _, element in context:
        if local_name(element.tag) != "EinheitStromSpeicher":
            continue
        values = child_values(element)
        yield values

        # Release processed records and preceding siblings. This keeps memory
        # bounded while parsing a very large XML member in a ZIP stream.
        parent = element.getparent()
        element.clear()
        if parent is not None:
            while element.getprevious() is not None:
                del parent[0]
    del context


def is_match(values: Dict[str, str]) -> Tuple[bool, Optional[date], Optional[float]]:
    registered = parse_date(values.get("Registrierungsdatum", ""))
    power = parse_number(values.get("Nettonennleistung", ""))
    matches = (
        registered is not None
        and registered > DATE_CUTOFF
        and power is not None
        and abs(power - TARGET_POWER_KW) <= 1e-9
    )
    return matches, registered, power


def storage_xml_names(archive: zipfile.ZipFile) -> List[str]:
    names = [
        name
        for name in archive.namelist()
        if name.lower().endswith(".xml")
        and "stromspeicher" in Path(name).name.lower()
    ]
    if not names:
        raise RuntimeError(
            "The official ZIP contains no XML member whose name includes "
            "'StromSpeicher'. The export layout may have changed."
        )
    return names


def process_zip(source_url: str) -> Tuple[int, Counter, Dict[str, Counter], Dict[str, int]]:
    """Filter storage XML and write the result CSV incrementally."""
    del source_url  # Kept in the signature for clear call-site provenance.
    monthly: Counter = Counter()
    feature_counts: Dict[str, Counter] = {
        "Bundesland": Counter(),
        "Energietraeger": Counter(),
        "Batterietechnologie": Counter(),
        "AcDcKoppelung": Counter(),
        "Einsatzort": Counter(),
    }
    rows_written = 0

    with zipfile.ZipFile(ZIP_PATH) as archive, OUTPUT_PATH.open(
        "w", newline="", encoding="utf-8-sig"
    ) as output:
        xml_names = storage_xml_names(archive)
        print(f"Storage XML members: {len(xml_names)}", flush=True)
        csv_writer = None

        for index, name in enumerate(xml_names, 1):
            print(f"processing {index}/{len(xml_names)}: {name}", flush=True)
            with archive.open(name) as xml_file:
                for values in iter_storage_records(xml_file):
                    if csv_writer is None:
                        columns = list(values.keys())
                        if "source_xml" not in columns:
                            columns.append("source_xml")
                        csv_writer = csv.DictWriter(
                            output,
                            fieldnames=columns,
                            extrasaction="ignore",
                        )
                        csv_writer.writeheader()

                    matches, registered, _ = is_match(values)
                    if not matches or registered is None:
                        continue

                    row = dict(values)
                    row["source_xml"] = name
                    csv_writer.writerow(row)
                    rows_written += 1
                    monthly[registered.strftime("%Y-%m")] += 1
                    for feature_name, counter in feature_counts.items():
                        counter[row.get(feature_name, "") or "(empty)"] += 1

        if csv_writer is None:
            csv_writer = csv.DictWriter(output, fieldnames=["source_xml"])
            csv_writer.writeheader()

    return rows_written, monthly, feature_counts, {
        "storage_xml_members": len(xml_names),
    }


def top_values(frame: pd.DataFrame, column: str, limit: int = 10) -> Dict[str, int]:
    if column not in frame.columns:
        return {}
    series = frame[column].fillna("").replace("", "(empty)")
    counts = series.value_counts().head(limit)
    return {str(key): int(value) for key, value in counts.items()}


def analyse_csv(
    source_url: str,
    count_from_stream: int,
    monthly_from_stream: Counter,
    feature_counts: Dict[str, Counter],
    zip_info: Dict[str, int],
) -> Dict[str, object]:
    """Use pandas on the filtered CSV and create summaries."""
    del feature_counts  # Recomputed from the final CSV for an audit check.
    frame = pd.read_csv(OUTPUT_PATH, dtype=str, keep_default_na=False)
    if "Registrierungsdatum" in frame.columns:
        registration_dates = pd.to_datetime(
            frame["Registrierungsdatum"], errors="coerce"
        )
        frame["month"] = registration_dates.dt.strftime("%Y-%m")
    else:
        registration_dates = pd.Series([], dtype="datetime64[ns]")
        frame["month"] = ""

    monthly = (
        frame.loc[frame["month"] != ""]
        .groupby("month", as_index=False)
        .size()
        .rename(columns={"size": "registrations"})
        .sort_values("month")
    )
    monthly["share"] = monthly["registrations"] / max(len(frame), 1)
    monthly["cumulative"] = monthly["registrations"].cumsum()
    monthly.to_csv(MONTHLY_PATH, index=False, encoding="utf-8-sig")

    if len(frame) != count_from_stream:
        raise RuntimeError(
            f"CSV count mismatch: stream={count_from_stream}, pandas={len(frame)}"
        )
    if int(monthly["registrations"].sum()) != len(frame):
        raise RuntimeError("Monthly total does not equal CSV row count")

    peak = None
    if not monthly.empty:
        peak_row = monthly.loc[monthly["registrations"].idxmax()]
        peak = {
            "month": str(peak_row["month"]),
            "registrations": int(peak_row["registrations"]),
        }

    analysis: Dict[str, object] = {
        "source_url": source_url,
        "source_zip": str(ZIP_PATH),
        "filter": {
            "registration_date": "> 2023-01-01",
            "net_rated_power_kw": TARGET_POWER_KW,
        },
        "scope_note": (
            "The MaStR official storage export has no reliable public field "
            "that isolates balcony/plug-in storage. Results therefore cover "
            "all electricity storage units matching the two filters."
        ),
        "matching_records": int(len(frame)),
        "unique_unit_ids": int(frame["EinheitMastrNummer"].nunique())
        if "EinheitMastrNummer" in frame.columns
        else None,
        "first_registration_date": (
            registration_dates.min().strftime("%Y-%m-%d")
            if registration_dates.notna().any()
            else None
        ),
        "last_registration_date": (
            registration_dates.max().strftime("%Y-%m-%d")
            if registration_dates.notna().any()
            else None
        ),
        "monthly_peak": peak,
        "monthly_average": (
            round(float(monthly["registrations"].mean()), 2)
            if not monthly.empty
            else 0
        ),
        "monthly": {
            str(row.month): int(row.registrations)
            for row in monthly.itertuples(index=False)
        },
        "top_features_raw_codes": {
            column: top_values(frame, column)
            for column in (
                "Bundesland",
                "Energietraeger",
                "Batterietechnologie",
                "AcDcKoppelung",
                "Einsatzort",
            )
        },
        "validation": {
            "stream_count": int(count_from_stream),
            "stream_monthly_total": int(sum(monthly_from_stream.values())),
            "zip_storage_xml_members": zip_info["storage_xml_members"],
            "all_power_values_are_0_8": bool(
                frame["Nettonennleistung"]
                .map(parse_number)
                .map(
                    lambda value: value is not None
                    and abs(value - TARGET_POWER_KW) <= 1e-9
                )
                .all()
            )
            if "Nettonennleistung" in frame.columns and len(frame)
            else True,
        },
    }

    ANALYSIS_PATH.write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_markdown_report(analysis)
    make_chart(monthly)
    return analysis


def write_markdown_report(analysis: Dict[str, object]) -> None:
    peak = analysis.get("monthly_peak") or {}
    lines = [
        "# MaStR 0.8 kW 储能登记初步分析",
        "",
        f"- 匹配记录数：**{analysis['matching_records']:,}**",
        f"- 登记日期范围：{analysis.get('first_registration_date')} 至 {analysis.get('last_registration_date')}",
        f"- 月均记录数：{analysis.get('monthly_average')}",
        f"- 峰值月份：**{peak.get('month', '无')}**，{peak.get('registrations', 0):,} 条",
        "",
        "## 口径",
        "",
        "官方 Gesamtdatenexport 当前提供 XML ZIP。脚本仅读取其中的储能 XML，筛选登记日期大于 2023-01-01 且净额定功率等于 0.8 kW 的记录。",
        "",
        "MaStR 全量储能导出没有可靠的公开字段专门标识阳台储能/插入式储能，因此这份结果是满足两个条件的全部电力储能登记记录，不能直接等同于阳台储能销量或阳台储能登记数。",
        "",
        "## 结果文件",
        "",
        f"- 明细：`{OUTPUT_PATH.name}`",
        f"- 月度汇总：`{MONTHLY_PATH.name}`",
        f"- JSON 分析：`{ANALYSIS_PATH.name}`",
        f"- 月度趋势图：`{CHART_PATH.name}`（若 matplotlib 可用）",
        "",
        "## 月度注册趋势",
        "",
        "| 月份 | 登记数 | 占比 | 累计 |",
        "|---|---:|---:|---:|",
    ]
    monthly = analysis.get("monthly", {})
    total = max(int(analysis.get("matching_records", 0)), 1)
    cumulative = 0
    for month, value in monthly.items():
        value_int = int(value)
        cumulative += value_int
        lines.append(
            f"| {month} | {value_int:,} | {value_int / total:.2%} | {cumulative:,} |"
        )
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def make_chart(monthly: pd.DataFrame) -> None:
    if monthly.empty:
        return
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        figure, axis = plt.subplots(figsize=(13, 5.5))
        axis.plot(
            monthly["month"],
            monthly["registrations"],
            marker="o",
            linewidth=1.5,
        )
        axis.set_title("MaStR storage registrations: Nettonennleistung = 0.8 kW")
        axis.set_xlabel("Registration month")
        axis.set_ylabel("Registrations")
        axis.tick_params(axis="x", rotation=60)
        axis.grid(True, alpha=0.3)
        figure.tight_layout()
        figure.savefig(CHART_PATH, dpi=160)
        plt.close(figure)
    except ImportError:
        print("matplotlib is not installed; skipped PNG chart.")


def main() -> int:
    print("Discovering the current official MaStR export link...", flush=True)
    source_url = discover_export_url()
    print(f"Official export: {source_url}", flush=True)
    print(f"Downloading to: {ZIP_PATH}", flush=True)
    size = download_resumable(source_url, ZIP_PATH)
    print(f"Downloaded {size / 1024**3:.2f} GB", flush=True)

    try:
        with zipfile.ZipFile(ZIP_PATH) as archive:
            names = storage_xml_names(archive)
            print("ZIP opened successfully.", flush=True)
            print("Storage XML:", ", ".join(names), flush=True)
    except zipfile.BadZipFile as exc:
        raise RuntimeError(
            "Downloaded file is not a complete ZIP. Re-run the script to resume "
            "or restart the download."
        ) from exc

    count, monthly, features, zip_info = process_zip(source_url)
    analysis = analyse_csv(source_url, count, monthly, features, zip_info)
    print(f"Matched records: {count:,}", flush=True)
    print(f"Saved: {OUTPUT_PATH}", flush=True)
    print(f"Saved: {MONTHLY_PATH}", flush=True)
    print(f"Saved: {ANALYSIS_PATH}", flush=True)
    print(f"Saved: {REPORT_PATH}", flush=True)
    if CHART_PATH.exists():
        print(f"Saved: {CHART_PATH}", flush=True)
    if analysis.get("monthly_peak"):
        peak = analysis["monthly_peak"]
        print(
            f"Peak month: {peak['month']} ({peak['registrations']:,} registrations)",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted. Re-run to resume the ZIP download.", file=sys.stderr)
        raise SystemExit(130)
