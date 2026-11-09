"""Integration tests for DuckDB Spatial SQL queries, AI Spatial Agent, and RFC 7946 GeoJSON exports."""

import json
from pathlib import Path
from src.ai.spatial_agent import AISpatialAgent
from src.engines.duckdb_engine import DuckDBSpatialEngine

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def test_duckdb_catalogue_views_and_spatial_sql() -> None:
    with DuckDBSpatialEngine() as engine:
        views = engine.register_catalogue_views(["ga_electricity_substations", "nsw_lga_boundaries"])
        assert "ga_electricity_substations" in views
        assert "nsw_lga_boundaries" in views

        res = engine.execute_spatial_sql(
            "SELECT COUNT(*) AS cnt FROM ga_electricity_substations WHERE ST_X(geom) > 150.0"
        )
        assert res["row_count"] == 1
        assert int(res["rows"][0]["cnt"]) > 0


def test_ai_spatial_agent_end_to_end() -> None:
    agent = AISpatialAgent()
    rec = agent.ask("List all active NSW RFS major bushfire and grassfire incidents from the live operational feed.")
    assert rec.status == "EXECUTED"
    assert rec.row_count > 0
    assert "nsw_rfs_major_incidents_live" in rec.selected_datasets

    clarify = agent.ask("How many people live inside the flood zone?")
    assert clarify.status == "CLARIFICATION_REQUIRED"

    rejected = agent.ask("Show live SCADA substation load")
    assert rejected.status == "REJECTED_UNCATALOGUED"


def test_rfc7946_geojson_exports_valid() -> None:
    for exp_name in ("hunter_population_grid_comparison", "hunter_substation_flood_dependency"):
        gj_path = PROJECT_ROOT / "data" / "lake" / "exports" / exp_name / "result.geojson"
        mf_path = PROJECT_ROOT / "data" / "lake" / "exports" / exp_name / "analysis_manifest.json"
        if gj_path.exists():
            fc = json.loads(gj_path.read_text(encoding="utf-8"))
            assert fc["type"] == "FeatureCollection"
            assert isinstance(fc.get("bbox"), list) and len(fc["bbox"]) == 4
            assert len(fc["features"]) > 0
            assert "oic_provenance" in fc
            assert mf_path.exists()

