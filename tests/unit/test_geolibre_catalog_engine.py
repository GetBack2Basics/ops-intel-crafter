"""Unit tests for the GeoLibre Catalogue Discovery & Spatial SQL Engine."""

import os
import re


def test_geolibre_catalog_engine_exists_and_registered_in_html() -> None:
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    engine_path = os.path.join(repo_root, "docs", "geolibre_catalog_engine.js")
    index_path = os.path.join(repo_root, "docs", "index.html")

    assert os.path.exists(engine_path), "docs/geolibre_catalog_engine.js must exist"
    assert os.path.getsize(engine_path) > 5000, "geolibre_catalog_engine.js must have substantive content"

    with open(index_path, "r", encoding="utf-8") as f:
        html = f.read()

    assert "geolibre_catalog_engine.js" in html, "index.html must load geolibre_catalog_engine.js"


def test_geolibre_catalog_engine_datasets_and_zero_mock_contracts() -> None:
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    engine_path = os.path.join(repo_root, "docs", "geolibre_catalog_engine.js")

    with open(engine_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 1. Authoritative GCS Parquet URIs must be referenced
    assert "gs://operational-intelligence-crafter-lake/geoparquet/nsw_foi_building_complexes/" in content
    assert "gs://operational-intelligence-crafter-lake/geoparquet/ga_electricity_substations/" in content
    assert "gs://operational-intelligence-crafter-lake/geoparquet/ga_major_power_stations/" in content
    assert "gs://operational-intelligence-crafter-lake/geoparquet/abs_australia_1km_population_grid/" in content
    assert "gs://operational-intelligence-crafter-lake/geoparquet/nsw_rfs_major_incidents_live/" in content

    # 2. Key operational scenarios must be mapped
    assert "hospitals_facilities" in content
    assert "substation_flood" in content
    assert "national_power" in content
    assert "live_rfs" in content
    assert "national_pop_grid" in content
    assert "pop_comparison" in content
    assert "lga_multi_hazard" in content

    # 3. Public infrastructure keywords mapped to FOI building complexes
    assert "bridges" in content
    assert "airports" in content
    assert "school" in content
    assert "police" in content
    assert "ambulance" in content

    # 4. Explicit restricted guardrails & genuine dataset absence
    assert "scada" in content
    assert "nsw_emergency_management_restricted" in content
    assert "REJECTED_UNCATALOGUED" in content
    assert "DATASET_NOT_FOUND" in content


def test_app_js_wires_geolibre_catalog_engine() -> None:
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    app_path = os.path.join(repo_root, "docs", "app.js")

    with open(app_path, "r", encoding="utf-8") as f:
        content = f.read()

    # app.js must call GeoLibreCatalogEngine.findDataset
    assert "window.GeoLibreCatalogEngine" in content
    assert "window.GeoLibreCatalogEngine.findDataset" in content
    assert "window.GeoLibreCatalogEngine.compileSql" in content

    # Button event listeners must invoke analyzeQuery to allow dynamic catalogue discovery
    btn_analyze_block = content[content.find('const btnAnalyze = document.getElementById("btnAnalyze");'):]
    assert "await analyzeQuery(null, false);" in btn_analyze_block[:500]

    btn_gen_block = content[content.find('const btnGenerateSql = document.getElementById("btnGenerateSql");'):]
    assert "await analyzeQuery(null, false);" in btn_gen_block[:500]


def test_spatial_filter_within_generated_aoi_region() -> None:
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    engine_path = os.path.join(repo_root, "docs", "geolibre_catalog_engine.js")

    with open(engine_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 1. getActiveAoiRegion must be implemented and exposed
    assert "function getActiveAoiRegion(" in content
    assert "getActiveAoiRegion," in content

    # 2. nsw_water_inundation_areas must filter within the generated AOI region
    water_block = content[content.find('id: "nsw_water_inundation_areas"'):]
    water_sql = water_block[:water_block.find("},\n    {")]
    assert "within generated AOI region" in water_sql
    assert "_bbox_maxx >=" in water_sql
    assert "_bbox_minx <=" in water_sql
    assert "_bbox_maxy >=" in water_sql
    assert "_bbox_miny <=" in water_sql

    # 3. substation_flood must not be clobbered by other datasets
    assert 'id: "ga_electricity_substations",\n      scenarioKey: "substation_flood"' in content
    assert 'scenarioKey: "transmission_lines"' in content
    assert 'scenarioKey: "water_inundation"' in content


