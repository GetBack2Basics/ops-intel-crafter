"""Immutable Versioned Snapshot Ingestion Pipeline (Levels 1, 2, and 3 Integrated)."""

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import geopandas as gpd

from src.catalogue.dataset_registry import DatasetRegistry
from src.catalogue.manifest_loader import DatasetEntry, QAStatus, save_manifest
from src.ingestion.gcs_storage import GCSLakeStorage
from src.ingestion.geoparquet_writer import normalize_and_write_geoparquet
from src.ingestion.source_connectors import (
    fetch_arcgis_layer,
    fetch_geojson_feed,
    fetch_wfs_layer,
)
from src.ingestion.telemetry import (
    INGESTION_SOFTWARE_VERSION,
    TRANSFORMATION_VERSION,
    IngestionTelemetry,
    utc_now_compact,
    utc_now_iso,
)
from src.validation.geoparquet_validation import verify_level2_stored_artifact
from src.validation.reconciliation import (
    compute_overall_dataset_qa_status,
    verify_level3_reconciliation,
)
from src.validation.source_contracts import verify_level1_source_contract


def _export_qa_geojson_preview(
    parquet_path: Path,
    dataset_key: str,
    project_root: Path,
    max_features: int = 1500,
) -> Dict[str, Any]:
    """Exports an RFC 7946 WGS84 (EPSG:4326) GeoJSON file for the MapLibre QA Inspector."""
    gdf = gpd.read_parquet(parquet_path)
    total_count = len(gdf)
    if gdf.crs and str(gdf.crs).upper() != "EPSG:4326":
        gdf = gdf.to_crs("EPSG:4326")

    # Drop internal helper columns for clean inspector table display
    drop_cols = [c for c in gdf.columns if c.startswith("_bbox_")]
    if drop_cols:
        gdf = gdf.drop(columns=drop_cols)

    preview_gdf = gdf.head(max_features) if total_count > max_features else gdf
    qa_data_dir = project_root / "docs" / "qa" / "data"
    qa_data_dir.mkdir(parents=True, exist_ok=True)
    geojson_path = qa_data_dir / f"{dataset_key}.geojson"
    preview_gdf.to_file(geojson_path, driver="GeoJSON")
    return {
        "preview_geojson_path": f"data/{dataset_key}.geojson",
        "preview_feature_count": int(len(preview_gdf)),
        "total_feature_count": int(total_count),
    }


def ingest_dataset_snapshot(
    dataset_key: str,
    registry: Optional[DatasetRegistry] = None,
    storage: Optional[GCSLakeStorage] = None,
    bbox: Optional[List[float]] = None,
    upload_cloud: bool = False,
    max_pages: int = 5,
) -> Dict[str, Any]:
    """Ingests a single dataset into an immutable timestamped GeoParquet snapshot with full 3-level QA."""
    reg = registry or DatasetRegistry()
    store = storage or GCSLakeStorage()
    entry: DatasetEntry = reg.get(dataset_key)

    retrieval_iso = utc_now_iso()
    retrieval_compact = utc_now_compact()
    telemetry = IngestionTelemetry(
        dataset_key=dataset_key,
        retrieval_timestamp_utc=retrieval_iso,
    )

    # ------------------------------------------------------------------
    # Step 1: Level 1 Source Contract Validation
    # ------------------------------------------------------------------
    t_val0 = time.perf_counter()
    level1_report = verify_level1_source_contract(entry, bbox=bbox)
    raw_cached_bytes = level1_report.pop("_raw_bytes", None)
    telemetry.validation_ms += round((time.perf_counter() - t_val0) * 1000.0, 2)
    telemetry.http_requests_count += 2 if entry.service_type.startswith("arcgis") else 1

    if level1_report["status"] == QAStatus.FAIL.value:
        # Zero-Mock Rule: Never fabricate data or create an empty Parquet file on failure.
        level3_report = verify_level3_reconciliation(entry, level1_report, None, None)
        overall_status = QAStatus.FAIL.value
        qa_payload = {
            "dataset_key": entry.dataset_key,
            "title": entry.title,
            "category": entry.category.value,
            "scale": entry.scale,
            "jurisdiction": entry.jurisdiction,
            "provider": entry.provider,
            "source_agency": entry.source_agency,
            "endpoint": entry.endpoint,
            "licence": entry.licence.model_dump(mode="json"),
            "source_publication_date": entry.source_publication_date,
            "source_vintage": entry.source_vintage,
            "retrieval_timestamp_utc": retrieval_iso,
            "retrieval_id": retrieval_compact,
            "ingestion_software_version": INGESTION_SOFTWARE_VERSION,
            "transformation_version": TRANSFORMATION_VERSION,
            "original_crs": entry.original_crs,
            "stored_crs": entry.stored_crs,
            "expected_geometry_type": entry.geometry_type,
            "overall_qa_status": overall_status,
            "level1_source_contract": level1_report,
            "level2_stored_artifact": {
                "level": 2,
                "level_name": "Stored GeoParquet Artifact",
                "status": QAStatus.NOT_APPLICABLE.value,
                "error_message": f"Skipped GeoParquet creation because Level 1 Source Contract failed: {level1_report.get('error_message')}",
                "checks": [],
            },
            "level3_reconciliation": level3_report,
            "known_limitations": entry.known_limitations,
            "refresh_policy": entry.refresh_policy,
            "telemetry": telemetry.finalize(),
        }
        qa_key = store.dataset_qa_object_key(dataset_key, retrieval_compact)
        store.write_json(qa_key, qa_payload, dataset_entry=entry.model_dump(mode="json"), upload_cloud=False)

        manifest_key = store.dataset_manifest_object_key(dataset_key)
        store.write_json(
            manifest_key,
            qa_payload,
            dataset_entry=entry.model_dump(mode="json"),
            upload_cloud=False,
            overwrite=True,
        )

        entry.qa_status = QAStatus.FAIL
        entry.latest_retrieval_utc = retrieval_iso
        reg.manifest.updated_at_utc = retrieval_iso
        save_manifest(reg.manifest, reg.manifest_path)
        return qa_payload

    # ------------------------------------------------------------------
    # Step 2: Source Feature Retrieval & Raw Payload Preservation
    # ------------------------------------------------------------------
    t_dl0 = time.perf_counter()
    if entry.service_type in ("arcgis_mapserver", "arcgis_featureserver"):
        gdf, raw_bytes, conn_meta = fetch_arcgis_layer(entry, bbox=bbox, max_pages=max_pages)
    elif entry.service_type == "geojson_feed":
        gdf, raw_bytes, conn_meta = fetch_geojson_feed(entry, bbox=bbox)
    elif entry.service_type == "ogc_wfs":
        gdf, raw_bytes, conn_meta = fetch_wfs_layer(entry, bbox=bbox)
    else:
        raise ValueError(f"Unsupported service_type: {entry.service_type}")

    telemetry.source_download_ms = round((time.perf_counter() - t_dl0) * 1000.0, 2)
    telemetry.http_requests_count += conn_meta.get("http_requests", 1)
    telemetry.bytes_downloaded = conn_meta.get("bytes_downloaded", len(raw_bytes))

    raw_key = store.raw_object_key(dataset_key, retrieval_compact, ext="json")
    raw_storage_meta = store.write_bytes(
        object_key=raw_key,
        data=raw_bytes,
        dataset_entry=entry.model_dump(mode="json"),
        upload_cloud=upload_cloud,
    )

    # ------------------------------------------------------------------
    # Step 3: GeoParquet 1.1.0 Normalization & Immutable Storage
    # ------------------------------------------------------------------
    t_norm0 = time.perf_counter()
    gpq_key = store.geoparquet_object_key(
        dataset_key=dataset_key,
        source_vintage=entry.source_vintage,
        retrieval_ts=retrieval_compact,
        part=0,
    )
    gpq_local_path = store.local_path(gpq_key)
    write_info = normalize_and_write_geoparquet(
        gdf=gdf,
        entry=entry,
        output_path=gpq_local_path,
        retrieval_timestamp_utc=retrieval_iso,
    )
    telemetry.parquet_write_ms = round((time.perf_counter() - t_norm0) * 1000.0, 2)

    gpq_storage_meta = store.register_local_parquet(
        parquet_file=gpq_local_path,
        object_key=gpq_key,
        dataset_entry=entry.model_dump(mode="json"),
        upload_cloud=upload_cloud,
    )
    telemetry.bytes_written = gpq_storage_meta["file_size_bytes"]

    # Export WGS84 GeoJSON preview for the MapLibre QA Inspector
    preview_meta = _export_qa_geojson_preview(
        parquet_path=gpq_local_path,
        dataset_key=dataset_key,
        project_root=store.project_root,
    )

    # ------------------------------------------------------------------
    # Step 4: Level 2 (Stored Artifact) & Level 3 (Reconciliation) QA
    # ------------------------------------------------------------------
    t_val2 = time.perf_counter()
    level2_report = verify_level2_stored_artifact(
        parquet_path=gpq_local_path,
        entry=entry,
        storage_meta=gpq_storage_meta,
    )
    level3_report = verify_level3_reconciliation(
        entry=entry,
        level1=level1_report,
        level2=level2_report,
        connector_meta=conn_meta,
    )
    telemetry.validation_ms += round((time.perf_counter() - t_val2) * 1000.0, 2)

    overall_status = compute_overall_dataset_qa_status(level1_report, level2_report, level3_report)
    final_telemetry = telemetry.finalize()

    # Complete 21-field versioned dataset & QA manifest
    dataset_version_record = {
        "dataset_key": entry.dataset_key,
        "title": entry.title,
        "provider": entry.provider,
        "source_agency": entry.source_agency,
        "category": entry.category.value,
        "scale": entry.scale,
        "jurisdiction": entry.jurisdiction,
        "theme": entry.theme,
        "endpoint": entry.endpoint,
        "licence": entry.licence.model_dump(mode="json"),
        "source_publication_date": entry.source_publication_date,
        "source_vintage": entry.source_vintage,
        "retrieval_timestamp_utc": retrieval_iso,
        "retrieval_id": retrieval_compact,
        "ingestion_software_version": INGESTION_SOFTWARE_VERSION,
        "transformation_version": TRANSFORMATION_VERSION,
        "original_crs": entry.original_crs,
        "stored_crs": level2_report["stored_crs"],
        "geometry_type": ", ".join(level2_report["geometry_types"]),
        "feature_count": level2_report["feature_count"],
        "bbox": level2_report["bbox"],
        "file_size_bytes": level2_report["file_size_bytes"],
        "sha256": level2_report["sha256"],
        "gcs_generation": gpq_storage_meta["gcs_generation"],
        "gs_uri": gpq_storage_meta["gs_uri"],
        "local_parquet_path": gpq_storage_meta["local_path"],
        "raw_payload_gs_uri": raw_storage_meta["gs_uri"],
        "raw_payload_sha256": raw_storage_meta["sha256"],
        "preview_geojson": preview_meta,
        "overall_qa_status": overall_status,
        "level1_source_contract": level1_report,
        "level2_stored_artifact": level2_report,
        "level3_reconciliation": level3_report,
        "known_limitations": entry.known_limitations,
        "refresh_policy": entry.refresh_policy,
        "operational_suitability": entry.operational_suitability,
        "telemetry": final_telemetry,
    }

    # Write immutable QA snapshot and update latest dataset manifest pointer
    qa_key = store.dataset_qa_object_key(dataset_key, retrieval_compact)
    store.write_json(
        qa_key,
        dataset_version_record,
        dataset_entry=entry.model_dump(mode="json"),
        upload_cloud=upload_cloud,
    )

    manifest_key = store.dataset_manifest_object_key(dataset_key)
    store.write_json(
        manifest_key,
        dataset_version_record,
        dataset_entry=entry.model_dump(mode="json"),
        upload_cloud=upload_cloud,
        overwrite=True,
    )

    # Update top-level catalogue manifest
    entry.qa_status = QAStatus(overall_status)
    entry.latest_snapshot_path = gpq_storage_meta["local_path"]
    entry.latest_retrieval_utc = retrieval_iso
    reg.manifest.updated_at_utc = retrieval_iso
    save_manifest(reg.manifest, reg.manifest_path)

    return dataset_version_record

