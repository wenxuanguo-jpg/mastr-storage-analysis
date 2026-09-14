# MaStR storage analysis

GitHub Actions downloads the official MaStR Gesamtdatenexport, filters storage units with `Registrierungsdatum > 2023-01-01` and `Nettonennleistung == 0.8 kW`, and uploads the filtered CSV plus monthly analysis as workflow artifacts.

The result is a proxy for the requested conditions. The official export does not reliably identify balcony or plug-in storage as a separate product category.
