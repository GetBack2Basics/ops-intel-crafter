"""Data Quality & Catalogue Contract Tests against Real Ingested GeoParquet Artifacts."""

import json
from pathlib import Path

from src.catalogue.dataset_registry import DatasetRegistry
from src.catalogue.manifest_loader import QAStatus
from src.catalogue.schema_inspector import inspect_parquet_schema_and_geo_metadata

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def test_catalogue_manifest_loads_and_validates():
    """Verifies config/dataset_manifest.json conforms to Pydantic schema and has all required metadata."""
    reg = DatasetRegistry()
    keys = reg.list_keys()
    assert len(keys) >= 10

    for k in keys:
        ds = reg.get(k)
        assert ds.dataset_key == k
        assert ds.endpoint.startswith("https://")
        assert ds.stored_crs == "EPSG:7844"
        assert ds.licence.redistribution_permitted is True
        assert ds.licence.attribution


def test_ingested_geoparquet_artifacts_and_failed_source_contract():
    """Verifies real stored GeoParquet 1.1.0 files and the demonstrated failed source in QA summary."""
    qa_summary_path = PROJECT_ROOT / "docs" / "qa" / "data" / "qa_summary.json"
    assert qa_summary_path.exists(), "Run tools/ingest_dataset.py --all before running data quality tests"

    summary = json.loads(qa_summary_path.read_text(encoding="utf-8"))
    by_key = {d["dataset_key"]: d for d in summary["datasets"]}

    # 1. Acceptance Test #17: Restricted endpoint must be recorded as FAIL with actual 499 Token Required error
    restricted = by_key["nsw_emergency_management_restricted"]
    assert restricted["overall_qa_status"] == QAStatus.FAIL.value
    assert "499" in (restricted["level1_source_contract"].get("error_message") or "")

    # 2. Working authoritative datasets must have verified GeoParquet 1.1.0 files with EPSG:7844 CRS
    passing_keys = [
        "ga_electricity_substations",
        "ga_major_power_stations",
        "ga_seismic_hazard_pga_10pct",
        "next_lga_boundaries_asgs2025",
        "nsw_lga_boundaries",
        "nsw_rfs_major_incidents_live",
    ]
    for k in passing_keys:
        rec = by_key[k]
        assert rec["overall_qa_status"] in (QAStatus.PASS.value, QAStatus.WARNING.value), f"{k} failed: {rec}"
        assert rec["feature_count"] > 0
        # Cloud-first: canonical artifacts live in GCS, not in local staging.
        gs_uri = rec.get("gs_uri")
        assert gs_uri and str(gs_uri).startswith("gs://"), f"{k} missing canonical gs_uri: {gs_uri}"
        info = inspect_parquet_schema_and_geo_metadata(gs_uri)
        assert info["has_geo_metadata"] is True
        assert info["num_rows"] == rec["feature_count"]

    # 3. Verify HTML QA pages exist and include the Stitch web_dashboard shell
    index_html = (PROJECT_ROOT / "docs" / "qa" / "index.html").read_text(encoding="utf-8")
    inspect_html = (PROJECT_ROOT / "docs" / "qa" / "inspect.html").read_text(encoding="utf-8")
    assert 'content="web_dashboard"' in index_html
    assert "nsw_emergency_management_restricted" in index_html
    assert "maplibregl.Map" in inspect_html

