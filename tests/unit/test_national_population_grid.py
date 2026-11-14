"""Unit tests for the National ABS 1 km² Population Grid."""

import json

import geopandas as gpd

from tests._cloud_artifacts import resolve_export_artifact

EXPORT_NAME = "australia_population_grid"


def test_national_population_grid_exports_exist_and_valid():
    """Verifies that the national population grid export files exist and meet schema invariants."""
    manifest = json.loads(
        resolve_export_artifact(EXPORT_NAME, "analysis_manifest.json").read_text(encoding="utf-8")
    )
    assert resolve_export_artifact(EXPORT_NAME, "result.parquet").exists()
    assert resolve_export_artifact(EXPORT_NAME, "result.geojson").exists()

    assert manifest["analysis_id"] == "australia_population_grid"
    assert manifest["feature_count"] == 286827
    assert manifest["total_population"] > 25000000.0
    assert manifest["level1_source_contract"]["status"] == "PASS"
    assert manifest["level2_stored_artifact"]["status"] == "PASS"
    assert manifest["level3_reconciliation"]["status"] == "PASS"


def test_national_population_grid_parquet_crs_and_columns():
    """Verifies stored GeoParquet CRS is EPSG:7844 and primary columns exist."""
    gdf = gpd.read_parquet(resolve_export_artifact(EXPORT_NAME, "result.parquet"))
    assert len(gdf) == 286827
    assert gdf.crs.to_epsg() == 7844 or "7844" in str(gdf.crs)
    assert "cell_id" in gdf.columns
    assert "cell_population" in gdf.columns
    assert "centroid_lon" in gdf.columns
    assert "centroid_lat" in gdf.columns
