import csv
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from mastr_official_export import (
    F_CAPACITY,
    F_MODULES,
    F_POWER,
    F_REGISTERED,
    OutputWriters,
    dashboard_performance,
    iter_members,
)
from prepare_site_from_outputs import main as rebuild_site


def row(registered, power="", modules="", capacity=""):
    return {
        F_REGISTERED: registered,
        F_POWER: power,
        F_MODULES: modules,
        F_CAPACITY: capacity,
    }


class DashboardPerformanceTests(unittest.TestCase):
    def setUp(self):
        self.rows = {
            "pv": [
                row("2025-04-15", power="0,5", modules="1"),
                row("2025-08-10", power="0,6", modules="2"),
                row("2025-08-20", power="0,8", modules="3"),
                row("2026-04-15", power="1,0", modules="4"),
                row("2026-05-15", power="1,0", modules="4"),
                row("2026-08-10", power="1,0", modules="4"),
                row("2026-09-02", power="1,2", modules="5"),
            ],
            "storage": [
                row("2025-04-15", capacity="1,0"),
                row("2025-08-10", capacity="1,0"),
                row("2026-04-15", capacity="2,0"),
                row("2026-05-15", capacity="2,0"),
                row("2026-08-10", capacity="2,0"),
                row("2026-09-02", capacity="3,0"),
            ],
        }

    def test_complete_period_growth_and_metric_yoy(self):
        result = dashboard_performance(self.rows, as_of=__import__("datetime").date(2026, 9, 17))
        self.assertEqual(result["latest_complete_month"], "2026-08")
        self.assertEqual(result["latest_complete_quarter"], "2026-Q2")

        pv = result["categories"]["pv"]
        self.assertEqual(pv["registration_yoy"]["month"]["registrations"], 1)
        self.assertEqual(pv["registration_yoy"]["month"]["comparison_registrations"], 2)
        self.assertEqual(pv["registration_yoy"]["month"]["yoy_pct"], -50.0)
        self.assertEqual(pv["registration_yoy"]["quarter"]["yoy_pct"], 100.0)

        power_months = {item["period"]: item for item in pv["metrics"]["power"]["monthly"]}
        self.assertNotIn("2026-09", power_months)
        self.assertEqual(power_months["2026-08"]["average"], 1.0)
        self.assertEqual(power_months["2026-08"]["yoy_pct"], 42.8571)

        capacity_months = {
            item["period"]: item
            for item in result["categories"]["storage"]["metrics"]["capacity"]["monthly"]
        }
        self.assertEqual(capacity_months["2026-08"]["average"], 2.0)
        self.assertEqual(capacity_months["2026-08"]["yoy_pct"], 100.0)

    def test_existing_artifact_rebuilds_performance_payload(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outputs = root / "outputs"
            site = root / "site"
            outputs.mkdir()
            for category, filename in (("pv", "balcony_pv.csv"), ("storage", "balcony_storage.csv")):
                with (outputs / filename).open("w", encoding="utf-8-sig", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=[F_REGISTERED, F_POWER, F_MODULES, F_CAPACITY])
                    writer.writeheader()
                    writer.writerows(self.rows[category])
            summary = {
                "generated_at_utc": "2026-09-17T00:00:00+00:00",
                "categories": {
                    "pv": {"matching_records": len(self.rows["pv"])},
                    "storage": {"matching_records": len(self.rows["storage"])},
                },
            }
            (outputs / "mastr_dashboard_summary.json").write_text(json.dumps(summary), encoding="utf-8")
            for filename in ("mastr_dashboard_monthly.json", "mastr_dashboard_features.json"):
                (outputs / filename).write_text("{}", encoding="utf-8")

            with patch.object(sys, "argv", ["prepare_site_from_outputs.py", "--outputs", str(outputs), "--site", str(site)]):
                self.assertEqual(rebuild_site(), 0)

            payload = json.loads((site / "data" / "performance.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["categories"]["storage"]["metrics"]["capacity"]["monthly"][-1]["period"], "2026-08")

    def test_filtered_storage_csv_keeps_capacity_column(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            writer = OutputWriters(root / "outputs", root / "site" / "data")
            writer.write("pv", row("2026-08-10", power="0,8", modules="2"), "solar.xml", [F_REGISTERED, F_POWER, F_MODULES])
            writer.write("storage", row("2026-08-10", power="0,8", capacity="2,0"), "storage.xml", [F_REGISTERED, F_POWER, F_MODULES])
            writer.close()
            with (root / "outputs" / "balcony_storage.csv").open("r", encoding="utf-8-sig", newline="") as stream:
                restored = list(csv.DictReader(stream))
            self.assertEqual(restored[0][F_CAPACITY], "2,0")

    def test_storage_capacity_is_joined_from_storage_plant_xml(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = Path(temporary) / "export.zip"
            unit_xml = """<?xml version="1.0" encoding="utf-8"?>
<EinheitenStromSpeicher><EinheitStromSpeicher>
  <EinheitMastrNummer>SEE123</EinheitMastrNummer>
  <Registrierungsdatum>2026-08-10</Registrierungsdatum>
  <NameStromerzeugungseinheit>Test storage</NameStromerzeugungseinheit>
  <Energietraeger>2493</Energietraeger>
  <Nettonennleistung>0.8</Nettonennleistung>
  <SpeMastrNummer>SEI456</SpeMastrNummer>
</EinheitStromSpeicher></EinheitenStromSpeicher>"""
            plant_xml = """<?xml version="1.0" encoding="utf-8"?>
<AnlagenStromSpeicher><AnlageStromSpeicher>
  <MaStRNummer>SEI456</MaStRNummer>
  <NutzbareSpeicherkapazitaet>1.6</NutzbareSpeicherkapazitaet>
  <VerknuepfteEinheitenMaStRNummern>SEE123</VerknuepfteEinheitenMaStRNummern>
</AnlageStromSpeicher></AnlagenStromSpeicher>"""
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("EinheitenStromSpeicher.xml", unit_xml)
                archive.writestr("AnlagenStromSpeicher.xml", plant_xml)

            rows = []
            for _name, member_rows in iter_members(archive_path):
                rows.extend(row for row, _line in member_rows)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0][F_CAPACITY], "1.6")


if __name__ == "__main__":
    unittest.main()
