"""Immutable Versioned Snapshot Ingestion Pipeline (Levels 1, 2, and 3 Integrated)."""

import hashlib
import io
import json
import os
import tempfile
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


def build_qa_geojson_preview(
    gdf: gpd.GeoDataFrame,
    max_features: int = 100000,
) -> tuple[bytes, Dict[str, Any]]:
    """Builds an RFC 7946 WGS84 (EPSG:4326) GeoJSON preview payload IN MEMORY.

    Cloud-first: callers can upload the returned bytes directly to GCS without
    staging anything on local disk. Intended for the MapLibre QA Inspector.
    """
    work = gdf.copy()
    total_count = len(work)
    if work.crs and str(work.crs).upper() != "EPSG:4326":
        work = work.to_crs("EPSG:4326")

    # Drop internal helper columns for clean inspector table display
    drop_cols = [c for c in work.columns if c.startswith("_bbox_")]
    if drop_cols:
        work = work.drop(columns=drop_cols)

    # For heavy polygon layers, apply lightweight simplification for the web preview
    # so MapLibre stays snappy in browser, while GeoParquet preserves full raw precision.
    if any(gt in ("Polygon", "MultiPolygon") for gt in work.geom_type.unique()):
        work["geometry"] = work.geometry.simplify(0.0005, preserve_topology=True)

    # Convert any datetime columns to string for clean GeoJSON serialization
    for col in work.select_dtypes(include=["datetime64", "datetimetz"]).columns:
        work[col] = work[col].astype(str)

    preview_gdf = work.head(max_features) if total_count > max_features else work
    payload = preview_gdf.to_json(drop_id=True)
    return payload.encode("utf-8"), {
        "preview_feature_count": int(len(preview_gdf)),
        "total_feature_count": int(total_count),
    }


def _export_qa_geojson_preview(
    parquet_path: Path,
    dataset_key: str,
    project_root: Path,
    max_features: int = 100000,
) -> Dict[str, Any]:
    """Exports an RFC 7946 WGS84 (EPSG:4326) GeoJSON file for the MapLibre QA Inspector and Workbench."""
    gdf = gpd.read_parquet(parquet_path)
    payload, counts = build_qa_geojson_preview(gdf, max_features=max_features)
    qa_data_dir = project_root / "docs" / "qa" / "data"
    qa_data_dir.mkdir(parents=True, exist_ok=True)
    (qa_data_dir / f"{dataset_key}.geojson").write_bytes(payload)
    return {
        "preview_geojson_path": f"data/{dataset_key}.geojson",
        **counts,
    }


def _persist_dataset_json(
    store: GCSLakeStorage,
    object_key: str,
    payload: Dict[str, Any],
    entry: DatasetEntry,
    upload_cloud: bool,
    overwrite: bool = False,
) -> None:
    """Persists a QA/manifest JSON record cloud-first (memory -> GCS) or locally in offline mode."""
    payload_bytes = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
    if upload_cloud:
        store.upload_bytes_cloud(
            object_key,
            payload_bytes,
            dataset_entry=entry.model_dump(mode="json"),
            content_type="application/json; charset=utf-8",
        )
    else:
        store.write_json(
            object_key,
            payload,
            dataset_entry=entry.model_dump(mode="json"),
            upload_cloud=False,
            overwrite=overwrite,
        )


def ingest_dataset_snapshot(
    dataset_key: str,
    registry: Optional[DatasetRegistry] = None,
    storage: Optional[GCSLakeStorage] = None,
    bbox: Optional[List[float]] = None,
    upload_cloud: bool = True,
    persist_records: bool = True,
    max_pages: int = 100,
) -> Dict[str, Any]:
    """Ingests a single dataset into an immutable timestamped GeoParquet snapshot with full 3-level QA.

    Cloud-first by default: normalization happens in memory, the artifact is uploaded
    straight to GCS, and Level 2 validates by reading it back from `gs://`.
    """
    reg = registry or DatasetRegistry(include_aura=False)
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
        if persist_records:
            _persist_dataset_json(store, qa_key, qa_payload, entry, upload_cloud)

            manifest_key = store.dataset_manifest_object_key(dataset_key)
            _persist_dataset_json(store, manifest_key, qa_payload, entry, upload_cloud, overwrite=True)

        if persist_records:
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
    if upload_cloud:
        raw_storage_meta = store.upload_bytes_cloud(
            raw_key,
            raw_bytes,
            dataset_entry=entry.model_dump(mode="json"),
            content_type="application/json; charset=utf-8",
        )
    else:
        # Ephemeral dry-run: fingerprint only, nothing written locally or to cloud.
        raw_storage_meta = {
            "object_key": raw_key,
            "gs_uri": store.gs_uri(raw_key),
            "local_path": None,
            "file_size_bytes": len(raw_bytes),
            "sha256": hashlib.sha256(raw_bytes).hexdigest(),
            "storage_mode": "dry_run_ephemeral",
            "gcs_generation": "dry-run-not-uploaded",
        }

    # ------------------------------------------------------------------
    # Step 3: GeoParquet 1.1.0 Normalization & Immutable Storage (in memory)
    # ------------------------------------------------------------------
    t_norm0 = time.perf_counter()
    gpq_key = store.geoparquet_object_key(
        dataset_key=dataset_key,
        source_vintage=entry.source_vintage,
        retrieval_ts=retrieval_compact,
        part=0,
    )
    pq_buffer = io.BytesIO()
    write_info = normalize_and_write_geoparquet(
        gdf=gdf,
        entry=entry,
        output_path=pq_buffer,
        retrieval_timestamp_utc=retrieval_iso,
    )
    pq_bytes = pq_buffer.getvalue()
    telemetry.parquet_write_ms = round((time.perf_counter() - t_norm0) * 1000.0, 2)

    if upload_cloud:
        gpq_storage_meta = store.upload_bytes_cloud(
            gpq_key,
            pq_bytes,
            dataset_entry=entry.model_dump(mode="json"),
            content_type="application/vnd.apache.parquet",
        )
        validation_source: Any = gpq_storage_meta["gs_uri"]
    else:
        tmp = tempfile.NamedTemporaryFile(suffix=".parquet", delete=False)
        tmp.write(pq_bytes)
        tmp.close()
        validation_source = tmp.name
        gpq_storage_meta = {
            "object_key": gpq_key,
            "gs_uri": store.gs_uri(gpq_key),
            "local_path": None,
            "file_size_bytes": len(pq_bytes),
            "sha256": hashlib.sha256(pq_bytes).hexdigest(),
            "storage_mode": "dry_run_ephemeral",
            "gcs_generation": "dry-run-not-uploaded",
        }
    telemetry.bytes_written = gpq_storage_meta["file_size_bytes"]

    # Export WGS84 GeoJSON preview for the MapLibre QA Inspector from the exact bytes written
    preview_gdf = gpd.read_parquet(io.BytesIO(pq_bytes))
    preview_bytes, preview_counts = build_qa_geojson_preview(preview_gdf)
    preview_meta = {"preview_geojson_path": f"data/{dataset_key}.geojson", **preview_counts}
    if upload_cloud:
        store.upload_bytes_cloud(
            f"qa/data/{dataset_key}.geojson",
            preview_bytes,
            content_type="application/geo+json; charset=utf-8",
        )
    else:
        (store.project_root / "docs" / "qa" / "data").mkdir(parents=True, exist_ok=True)
        (store.project_root / "docs" / "qa" / "data" / f"{dataset_key}.geojson").write_bytes(preview_bytes)

    # ------------------------------------------------------------------
    # Step 4: Level 2 (Stored Artifact) & Level 3 (Reconciliation) QA
    # ------------------------------------------------------------------
    t_val2 = time.perf_counter()
    level2_report = verify_level2_stored_artifact(
        parquet_path=validation_source,
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
    if not upload_cloud:
        os.unlink(validation_source)

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
    if persist_records:
        qa_key = store.dataset_qa_object_key(dataset_key, retrieval_compact)
        _persist_dataset_json(store, qa_key, dataset_version_record, entry, upload_cloud)

        manifest_key = store.dataset_manifest_object_key(dataset_key)
        _persist_dataset_json(store, manifest_key, dataset_version_record, entry, upload_cloud, overwrite=True)

        # Update top-level catalogue manifest
        entry.qa_status = QAStatus(overall_status)
        entry.latest_snapshot_path = gpq_storage_meta["gs_uri"]
        entry.latest_retrieval_utc = retrieval_iso
        reg.manifest.updated_at_utc = retrieval_iso
        save_manifest(reg.manifest, reg.manifest_path)

    return dataset_version_record

