"""Level 2 Validation — Stored GeoParquet Artifact Verifier.

Verifies:
1. File exists and is non-empty.
2. Parquet magic bytes (PAR1) and footer metadata can be read.
3. GeoParquet 'geo' metadata is valid (version, primary_column, encoding, geometry_types).
4. CRS is known and matches stored_crs (EPSG:7844).
5. Bounding boxes are valid and fall within Australian spatial bounds.
6. Feature count and schema are recorded.
7. Geometry validity (ST_IsValid), null geometry, empty geometry, and duplicate ID rates are measured.
8. SHA-256 file hash and GCS object generation / storage location are recorded.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional
import geopandas as gpd

from src.catalogue.manifest_loader import DatasetEntry, QAStatus
from src.catalogue.schema_inspector import inspect_parquet_schema_and_geo_metadata
from src.ingestion.telemetry import compute_sha256
from src.validation.geometry_validation import validate_geodataframe_geometries

# Broad Australian continental + territorial envelope [min_lon, min_lat, max_lon, max_lat]
AUSTRALIA_LON_BOUNDS = (95.0, 170.0)
AUSTRALIA_LAT_BOUNDS = (-55.0, -8.0)


def _extract_crs_code_from_projjson(crs_obj: Any) -> str:
    if not crs_obj:
        return "UNKNOWN"
    if isinstance(crs_obj, str):
        return crs_obj
    if isinstance(crs_obj, dict):
        crs_id = crs_obj.get("id")
        if isinstance(crs_id, dict) and "authority" in crs_id and "code" in crs_id:
            return f"{crs_id['authority']}:{crs_id['code']}"
        return crs_obj.get("name", "CUSTOM_PROJJSON")
    return "UNKNOWN"


def verify_level2_stored_artifact(
    parquet_path: Path,
    entry: DatasetEntry,
    storage_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Executes Level 2 Stored Artifact validation on a GeoParquet file."""
    checks: List[Dict[str, Any]] = []
    if not parquet_path.exists():
        return {
            "level": 2,
            "level_name": "Stored GeoParquet Artifact",
            "status": QAStatus.FAIL.value,
            "file_path": str(parquet_path),
            "error_message": f"GeoParquet file does not exist: {parquet_path}",
            "checks": [{"check": "file_exists", "status": "FAIL", "detail": "File missing on disk"}],
        }

    try:
        pq_info = inspect_parquet_schema_and_geo_metadata(parquet_path)
    except Exception as exc:
        return {
            "level": 2,
            "level_name": "Stored GeoParquet Artifact",
            "status": QAStatus.FAIL.value,
            "file_path": str(parquet_path),
            "error_message": f"Parquet footer/magic verification failed: {exc}",
            "checks": [{"check": "parquet_footer_and_magic", "status": "FAIL", "detail": str(exc)}],
        }

    checks.append(
        {
            "check": "parquet_footer_and_magic",
            "status": "PASS",
            "detail": f"PAR1 header/footer valid; {pq_info['num_rows']} rows in {pq_info['num_row_groups']} row group(s) ({pq_info['file_size_bytes']} bytes)",
        }
    )

    geo_meta = pq_info.get("geo_metadata")
    if not geo_meta or not isinstance(geo_meta, dict):
        checks.append(
            {
                "check": "geoparquet_metadata_valid",
                "status": "FAIL",
                "detail": "Missing 'geo' metadata key in Parquet schema footer",
            }
        )
        return {
            "level": 2,
            "level_name": "Stored GeoParquet Artifact",
            "status": QAStatus.FAIL.value,
            "file_path": str(parquet_path),
            "error_message": "Missing GeoParquet 'geo' metadata",
            "checks": checks,
        }

    gpq_version = geo_meta.get("version", "unknown")
    primary_col = geo_meta.get("primary_column", "geometry")
    col_meta = (geo_meta.get("columns") or {}).get(primary_col, {})
    encoding = col_meta.get("encoding", "unknown")
    gpq_geom_types = col_meta.get("geometry_types", [])
    crs_code = _extract_crs_code_from_projjson(col_meta.get("crs"))
    gpq_bbox = col_meta.get("bbox")

    checks.append(
        {
            "check": "geoparquet_metadata_valid",
            "status": "PASS" if gpq_version != "unknown" and encoding == "WKB" else "WARNING",
            "detail": f"GeoParquet v{gpq_version}, primary_column='{primary_col}', encoding='{encoding}', geometry_types={gpq_geom_types}",
        }
    )

    crs_ok = crs_code.upper() == entry.stored_crs.upper()
    checks.append(
        {
            "check": "crs_recorded_and_matched",
            "status": "PASS" if crs_ok else "WARNING",
            "detail": f"Stored CRS '{crs_code}' (expected '{entry.stored_crs}')",
        }
    )

    # Read GeoDataFrame for geometry validity and bounding box checks
    gdf = gpd.read_parquet(parquet_path)
    geom_stats = validate_geodataframe_geometries(gdf, primary_key=entry.primary_key)

    bbox = gpq_bbox if (gpq_bbox and len(gpq_bbox) == 4) else [float(x) for x in gdf.total_bounds]
    bbox_valid = (
        len(bbox) == 4
        and bbox[0] <= bbox[2]
        and bbox[1] <= bbox[3]
        and AUSTRALIA_LON_BOUNDS[0] <= bbox[0] <= AUSTRALIA_LON_BOUNDS[1]
        and AUSTRALIA_LON_BOUNDS[0] <= bbox[2] <= AUSTRALIA_LON_BOUNDS[1]
        and AUSTRALIA_LAT_BOUNDS[0] <= bbox[1] <= AUSTRALIA_LAT_BOUNDS[1]
        and AUSTRALIA_LAT_BOUNDS[0] <= bbox[3] <= AUSTRALIA_LAT_BOUNDS[1]
    )
    checks.append(
        {
            "check": "bounding_box_australian_envelope",
            "status": "PASS" if bbox_valid else "FAIL",
            "detail": f"Bbox {[round(x, 5) for x in bbox]} within Australian geographic envelope",
        }
    )

    geom_status = "PASS"
    if geom_stats["null_geometry_count"] > 0 or geom_stats["invalid_geometry_count"] > 0:
        geom_status = "WARNING" if geom_stats["valid_geometry_rate_pct"] >= 95.0 else "FAIL"
    checks.append(
        {
            "check": "geometry_validity_and_null_rates",
            "status": geom_status,
            "detail": (
                f"{geom_stats['valid_geometry_rate_pct']}% valid "
                f"(null={geom_stats['null_geometry_count']}, empty={geom_stats['empty_geometry_count']}, "
                f"invalid={geom_stats['invalid_geometry_count']})"
            ),
        }
    )

    dup_status = "PASS" if geom_stats["duplicate_id_count"] == 0 else "WARNING"
    checks.append(
        {
            "check": "primary_key_uniqueness",
            "status": dup_status,
            "detail": f"Primary key '{geom_stats['primary_key_checked']}': {geom_stats['duplicate_id_count']} duplicates across {geom_stats['total_rows']} rows",
        }
    )

    sha256_hex = (storage_meta or {}).get("sha256") or compute_sha256(parquet_path)
    gcs_gen = (storage_meta or {}).get("gcs_generation", "local-staged-pending-gcs-sync")
    gs_uri = (storage_meta or {}).get("gs_uri", "")

    checks.append(
        {
            "check": "sha256_and_storage_lineage",
            "status": "PASS",
            "detail": f"sha256={sha256_hex[:16]}... | generation={gcs_gen}",
        }
    )

    overall = QAStatus.PASS.value
    if any(c["status"] == "FAIL" for c in checks):
        overall = QAStatus.FAIL.value
    elif any(c["status"] == "WARNING" for c in checks):
        overall = QAStatus.WARNING.value

    return {
        "level": 2,
        "level_name": "Stored GeoParquet Artifact",
        "status": overall,
        "file_path": str(parquet_path),
        "gs_uri": gs_uri,
        "gcs_generation": gcs_gen,
        "file_size_bytes": pq_info["file_size_bytes"],
        "sha256": sha256_hex,
        "geoparquet_version": gpq_version,
        "geometry_encoding": encoding,
        "stored_crs": crs_code,
        "geometry_types": geom_stats["geometry_types"],
        "feature_count": geom_stats["total_rows"],
        "bbox": [round(x, 6) for x in bbox],
        "geometry_validation": geom_stats,
        "schema_columns": pq_info["columns"],
        "checks": checks,
    }

