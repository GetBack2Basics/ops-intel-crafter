"""Unit tests for the National ABS 1 km² Population Grid."""

import json
from pathlib import Path
import geopandas as gpd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def test_national_population_grid_exports_exist_and_valid():
    """Verifies that the national population grid export files exist and meet schema invariants."""
    exp_dir = PROJECT_ROOT / "data" / "lake" / "exports" / "australia_population_grid"
    manifest_file = exp_dir / "analysis_manifest.json"
    parquet_file = exp_dir / "result.parquet"
    geojson_file = exp_dir / "result.geojson"

    assert manifest_file.exists(), "analysis_manifest.json must exist"
    assert parquet_file.exists(), "result.parquet must exist"
    assert geojson_file.exists(), "result.geojson must exist"

    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert manifest["analysis_id"] == "australia_population_grid"
    assert manifest["feature_count"] == 286827
    assert manifest["total_population"] > 25000000.0
    assert manifest["level1_source_contract"]["status"] == "PASS"
    assert manifest["level2_stored_artifact"]["status"] == "PASS"
    assert manifest["level3_reconciliation"]["status"] == "PASS"


def test_national_population_grid_parquet_crs_and_columns():
    """Verifies stored GeoParquet CRS is EPSG:7844 and primary columns exist."""
    exp_parquet = PROJECT_ROOT / "data" / "lake" / "exports" / "australia_population_grid" / "result.parquet"
    gdf = gpd.read_parquet(exp_parquet)
    assert len(gdf) == 286827
    assert gdf.crs.to_epsg() == 7844 or "7844" in str(gdf.crs)
    assert "cell_id" in gdf.columns
    assert "cell_population" in gdf.columns
    assert "centroid_lon" in gdf.columns
    assert "centroid_lat" in gdf.columns
