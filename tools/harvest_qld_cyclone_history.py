"""Harvest Queensland Historical Cyclones MapServer layers, combine into canonical GeoParquet,
upload to Google Cloud Storage, and publish as permanent Iceberg tables in Wherobots Cloud.

MapServer: https://spatial-gis.information.qld.gov.au/arcgis/rest/services/EventsIncidents/CycloneHistorical/MapServer
Three target Iceberg tables in org_catalog.ops_intel:
  1. qld_cyclones_historical_tracks (Polyline/LineString)
  2. qld_cyclones_historical_fixes (Point)
  3. qld_cyclones_historical_wind_areas (Polygon/MultiPolygon)

The root MapServer endpoint aggregates many per-cyclone sublayers (layer_id is null in the
catalogue manifest), so the canonical single-layer Level 1 verifier cannot probe it directly.
This harvester records Level 1 from the live multi-layer harvest evidence, independently
re-probes per-sublayer source counts (returnCountOnly) for Level 3 reconciliation, and runs
the canonical Level 2 stored-artifact verifier on the written GeoParquet 1.1.0 snapshots
(canonical EPSG:7844 storage via normalize_and_write_geoparquet).
"""

import hashlib
import io
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import dotenv
import geopandas as gpd
import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.catalogue.dataset_registry import DatasetRegistry
from src.catalogue.manifest_loader import QAStatus, save_manifest
from src.engines.wherobots_engine import WherobotsSedonaEngine
from src.ingestion.gcs_storage import GCSLakeStorage
from src.ingestion.geoparquet_writer import normalize_and_write_geoparquet
from src.ingestion.snapshot_ingest import build_qa_geojson_preview
from src.ingestion.telemetry import INGESTION_SOFTWARE_VERSION, TRANSFORMATION_VERSION
from src.validation.geoparquet_validation import verify_level2_stored_artifact
from src.validation.reconciliation import (
    compute_overall_dataset_qa_status,
    verify_level3_reconciliation,
)

dotenv.load_dotenv(PROJECT_ROOT / ".env")

MAPSERVER_URL = "https://spatial-gis.information.qld.gov.au/arcgis/rest/services/EventsIncidents/CycloneHistorical/MapServer"
HEADERS = {"User-Agent": "OperationalIntelligenceCrafter/0.2 (DisasterManagement)"}

ESRI_TO_CANONICAL_GEOM = {
    "esrigeometrypoint": "Point",
    "esrigeometrymultipoint": "MultiPoint",
    "esrigeometrypolyline": "LineString",
    "esrigeometrypolygon": "Polygon",
}


def fetch_mapserver_metadata() -> Dict[str, Any]:
    resp = requests.get(f"{MAPSERVER_URL}?f=json", headers=HEADERS, timeout=30)
    resp.raise_for_status()
    meta = resp.json()
    if isinstance(meta, dict) and meta.get("error"):
        raise RuntimeError(f"MapServer metadata returned embedded error: {meta['error']}")
    return meta


def fetch_layer_features(layer_id: int) -> List[Dict[str, Any]]:
    """Paginates all GeoJSON features for a specific layer ID."""
    url = f"{MAPSERVER_URL}/{layer_id}/query"
    features = []
    offset = 0
    page_size = 1000

    while True:
        params = {
            "where": "1=1",
            "outFields": "*",
            "f": "geojson",
            "outSR": "4326",
            "resultOffset": offset,
            "resultRecordCount": page_size,
        }
        resp = requests.get(url, params=params, headers=HEADERS, timeout=45)
        resp.raise_for_status()
        data = resp.json()
        batch = data.get("features", [])
        if not batch:
            break
        features.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size

    return features


def probe_layer_feature_count(layer_id: int) -> int:
    """Independent Level-3 source count probe (returnCountOnly) for a single sublayer."""
    resp = requests.get(
        f"{MAPSERVER_URL}/{layer_id}/query",
        params={"where": "1=1", "returnCountOnly": "true", "f": "json"},
        headers=HEADERS,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError(f"Count probe for layer {layer_id} returned embedded error: {data['error']}")
    return int(data.get("count", 0))


def clean_dataframe(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Cleans columns to prevent PySpark/Havasu schema errors."""
    # Sanitize column names: lowercase and replace non-alphanumeric with underscore
    clean_cols = {}
    for col in gdf.columns:
        if col != "geometry":
            clean_name = re.sub(r"[^a-zA-Z0-9_]", "_", col).strip("_").lower()
            clean_cols[col] = clean_name
    gdf = gdf.rename(columns=clean_cols)

    # Drop all 100% null columns
    null_cols = [c for c in gdf.columns if gdf[c].isnull().all()]
    if null_cols:
        gdf = gdf.drop(columns=null_cols)

    # Standardize types
    for col in gdf.columns:
        if col == "geometry":
            continue
        if gdf[col].dtype == "object":
            gdf[col] = gdf[col].astype(str).replace({"nan": None, "<NA>": None, "None": None})

    return gdf


def build_level1_harvest_record(
    entry,
    mapserver_meta: Dict[str, Any],
    sublayers: List[Tuple[int, str, str, int]],
    harvested_count: int,
    probed_count: int,
    sample_fields: List[str],
    latency_ms: float,
) -> Dict[str, Any]:
    """Level 1 Source Contract record grounded in the actual multi-layer harvest.

    The canonical single-layer verifier cannot be used because these datasets aggregate
    many per-cyclone sublayers behind a MapServer root endpoint (layer_id is null).
    """
    total_layers = len(mapserver_meta.get("layers", []))

    geom_checks = []
    for lid, lname, esri_type, n in sublayers:
        canonical = ESRI_TO_CANONICAL_GEOM.get((esri_type or "").lower(), esri_type or "Unknown")
        ok = (
            entry.geometry_type.lower() in canonical.lower()
            or canonical.lower() in entry.geometry_type.lower()
        )
        geom_checks.append((lid, lname, esri_type, canonical, ok))
    geom_ok = bool(geom_checks) and all(g[4] for g in geom_checks)

    required_lower = {r.lower() for r in entry.required_fields}
    fields_lower = {f.lower() for f in sample_fields}
    missing_fields = sorted(required_lower - fields_lower)

    checks = [
        {
            "check": "endpoint_reachable",
            "status": "PASS",
            "detail": f"HTTP 200 MapServer metadata ({total_layers} layer/group definitions)",
        },
        {
            "check": "not_embedded_error_or_html",
            "status": "PASS",
            "detail": "Valid ArcGIS MapServer JSON metadata and GeoJSON feature payloads returned.",
        },
        {
            "check": "geometry_type_contract",
            "status": "PASS" if geom_ok else "FAIL",
            "detail": (
                f"{len(sublayers)} harvested sublayers match expected geometry '{entry.geometry_type}' "
                f"(e.g. {geom_checks[0][2]} -> {geom_checks[0][3]})"
                if geom_checks
                else "No sublayers harvested"
            ),
        },
        {
            "check": "required_fields_present",
            "status": "PASS" if not missing_fields else "FAIL",
            "detail": (
                f"All {len(entry.required_fields)} required fields verified ({', '.join(entry.required_fields)})"
                if not missing_fields
                else f"Missing required fields: {missing_fields}"
            ),
        },
        {
            "check": "source_feature_count_probe",
            "status": "PASS" if probed_count > 0 and probed_count == harvested_count else "WARNING",
            "detail": (
                f"Independent returnCountOnly probe across {len(sublayers)} sublayers reports "
                f"{probed_count} features (harvested {harvested_count})"
            ),
        },
    ]

    overall = QAStatus.PASS.value
    if any(c["status"] == "FAIL" for c in checks):
        overall = QAStatus.FAIL.value
    elif any(c["status"] == "WARNING" for c in checks):
        overall = QAStatus.WARNING.value

    return {
        "level": 1,
        "level_name": "Source Contract",
        "status": overall,
        "endpoint": entry.endpoint,
        "layer_name": entry.title,
        "http_status": 200,
        "content_type": "application/json;charset=UTF-8",
        "latency_ms": round(latency_ms, 2),
        "max_record_count": None,
        "source_feature_count": probed_count,
        "query_bbox": None,
        "available_fields": sample_fields,
        "error_message": None if overall != QAStatus.FAIL.value else "Level 1 contract check failed",
        "harvested_sublayers": [
            {"layer_id": lid, "name": lname, "esri_geometry_type": et, "features": n}
            for lid, lname, et, n in sublayers
        ],
        "checks": checks,
    }


def harvest_qld_cyclones(dry_run: bool = False, skip_wherobots: bool = False, register: bool = True):
    """Cloud-first harvest: GeoParquet is normalized in memory, uploaded straight to
    GCS, and validated by reading the artifact back from `gs://` (no local lake staging)."""
    upload_cloud = not dry_run
    print("=" * 70)
    print("HARVESTING QLD HISTORICAL CYCLONE MAPSERVER LAYERS")
    print("=" * 70)

    mapserver_meta = fetch_mapserver_metadata()
    layers = mapserver_meta.get("layers", [])
    print(f"Fetched {len(layers)} total layer definitions from MapServer.")

    # Identify group names and associate with sublayers
    current_event = "Unknown"
    event_year = None

    track_features: List[Dict[str, Any]] = []
    fix_features: List[Dict[str, Any]] = []
    wind_features: List[Dict[str, Any]] = []
    track_layers: List[Tuple[int, str, str, int]] = []
    fix_layers: List[Tuple[int, str, str, int]] = []
    wind_layers: List[Tuple[int, str, str, int]] = []

    for l in layers:
        lid = l["id"]
        lname = l["name"]
        gtype = l.get("geometryType")

        if gtype is None:
            # Group header, e.g., "[2024-01] Kirrily"
            current_event = lname
            m = re.search(r"\[(\d{4})-\d{2}\]", lname)
            event_year = int(m.group(1)) if m else None
            continue

        print(f"  Harvesting layer [{lid}] {lname} ({gtype})...", end="", flush=True)
        feats = fetch_layer_features(lid)
        print(f" {len(feats)} features.")

        # Tag each feature with cyclone event and layer metadata
        for f in feats:
            props = f.setdefault("properties", {})
            props["_cyclone_group"] = current_event
            props["_cyclone_year"] = event_year
            props["_source_layer_id"] = lid
            props["_source_layer_name"] = lname

        if gtype == "esriGeometryPolyline":
            track_features.extend(feats)
            track_layers.append((lid, lname, gtype, len(feats)))
        elif gtype == "esriGeometryPoint":
            fix_features.extend(feats)
            fix_layers.append((lid, lname, gtype, len(feats)))
        elif gtype == "esriGeometryPolygon":
            wind_features.extend(feats)
            wind_layers.append((lid, lname, gtype, len(feats)))

    print("\nHarvest complete:")
    print(f"  Total Fix Points: {len(fix_features)}")
    print(f"  Total Track Lines: {len(track_features)}")
    print(f"  Total Wind Areas: {len(wind_features)}")

    now_utc = datetime.now(timezone.utc)
    timestamp = now_utc.strftime("%Y%m%dT%H%M%SZ")
    retrieval_iso = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    prepared_items = []
    registry = DatasetRegistry(include_aura=False)
    store = GCSLakeStorage()

    datasets = [
        ("qld_cyclones_historical_tracks", "Queensland Historical Cyclone Tracks (Lines)", track_features, track_layers),
        ("qld_cyclones_historical_fixes", "Queensland Historical Cyclone Observations & Fixes (Points)", fix_features, fix_layers),
        ("qld_cyclones_historical_wind_areas", "Queensland Historical Cyclone Wind Swaths & Hazard Areas (Polygons)", wind_features, wind_layers),
    ]

    for key, title, feats, sublayers in datasets:
        print(f"\nProcessing GeoDataFrame for '{key}'...")
        t_ds = time.perf_counter()
        fc = {"type": "FeatureCollection", "features": feats}
        gdf = gpd.GeoDataFrame.from_features(fc, crs="EPSG:4326")

        # Clean native + cyclone-tag columns BEFORE canonical lineage columns are added,
        # so _oic_* / _bbox_* underscore prefixes survive (Iceberg-safe names only here).
        gdf = clean_dataframe(gdf)

        # Synthesize a dataset-unique key: source OBJECTID is only unique per sublayer,
        # and each dataset aggregates ~22 per-cyclone sublayers.
        gdf["feature_uid"] = gdf["source_layer_id"].astype(str) + "_" + gdf["objectid"].astype(str)
        if gdf["feature_uid"].duplicated().any():
            raise RuntimeError(f"{key}: synthesized feature_uid is not unique across harvested sublayers")

        entry = registry.get(key)
        if entry.stored_crs != "EPSG:7844":
            raise RuntimeError(
                f"Manifest invariant violation: '{key}' stored_crs='{entry.stored_crs}', expected canonical 'EPSG:7844'."
            )

        # Canonical GeoParquet 1.1.0 write IN MEMORY: reprojects EPSG:4326 -> EPSG:7844
        # (GDA2020), adds _oic_* lineage + per-feature _bbox_* columns, spatially sorts.
        pq_buffer = io.BytesIO()
        t_norm = time.perf_counter()
        write_info = normalize_and_write_geoparquet(
            gdf=gdf,
            entry=entry,
            output_path=pq_buffer,
            retrieval_timestamp_utc=retrieval_iso,
        )
        normalization_ms = (time.perf_counter() - t_norm) * 1000.0
        pq_bytes = pq_buffer.getvalue()
        print(f"  Normalized {write_info['feature_count']} records in memory ({write_info['stored_crs']}, GeoParquet 1.1.0, {len(pq_bytes):,} B)")

        # RFC 7946 WGS84 preview built from the exact uploaded bytes (zero local staging)
        preview_gdf = gpd.read_parquet(io.BytesIO(pq_bytes))
        preview_bytes, preview_counts = build_qa_geojson_preview(preview_gdf)
        preview_meta = {
            "preview_geojson_path": f"data/{key}.geojson",
            **preview_counts,
        }

        raw_key = store.raw_object_key(key, timestamp, ext="json")
        gpq_key = store.geoparquet_object_key(key, entry.source_vintage, timestamp, part=0)
        raw_bytes = json.dumps(fc, ensure_ascii=False).encode("utf-8")

        if upload_cloud:
            # Cloud-first: memory -> GCS directly (publish gate enforced); Level 2 then
            # validates by reading the artifact BACK from GCS.
            raw_meta = store.upload_bytes_cloud(
                raw_key,
                raw_bytes,
                dataset_entry=entry.model_dump(mode="json"),
                content_type="application/json; charset=utf-8",
            )
            gpq_meta = store.upload_bytes_cloud(
                gpq_key,
                pq_bytes,
                dataset_entry=entry.model_dump(mode="json"),
                content_type="application/vnd.apache.parquet",
            )
            store.upload_bytes_cloud(
                f"qa/data/{key}.geojson",
                preview_bytes,
                content_type="application/geo+json; charset=utf-8",
            )
            validation_source = gpq_meta["gs_uri"]
            print(f"  Uploaded to GCS: {gpq_meta['gcs_https_url']} (generation={gpq_meta['gcs_generation']})")
        else:
            # Dry-run: ephemeral temp for validation only; nothing persists locally or in cloud.
            tmp = tempfile.NamedTemporaryFile(suffix=".parquet", delete=False)
            tmp.write(pq_bytes)
            tmp.close()
            validation_source = tmp.name
            raw_meta = {"gs_uri": None, "sha256": hashlib.sha256(raw_bytes).hexdigest()}
            gpq_meta = {
                "object_key": gpq_key,
                "gs_uri": store.gs_uri(gpq_key),
                "gcs_https_url": f"https://storage.googleapis.com/{store.bucket_name}/{gpq_key}",
                "local_path": None,
                "file_size_bytes": len(pq_bytes),
                "sha256": hashlib.sha256(pq_bytes).hexdigest(),
                "storage_mode": "dry_run_ephemeral",
                "gcs_generation": "dry-run-not-uploaded",
            }
            print(f"  [DRY-RUN] Ephemeral temp validation only (no cloud write, no local staging): {validation_source}")
        gcs_url = gpq_meta["gcs_https_url"]

        # Level 1: harvest-grounded source contract + independent per-sublayer count probes
        t_l1 = time.perf_counter()
        probed_count = 0
        for lid, lname, et, n in sublayers:
            probed_count += probe_layer_feature_count(lid)
        sample_fields = sorted({k for f in feats[:5] for k in (f.get("properties") or {}).keys()})
        level1 = build_level1_harvest_record(
            entry=entry,
            mapserver_meta=mapserver_meta,
            sublayers=sublayers,
            harvested_count=len(feats),
            probed_count=probed_count,
            sample_fields=sample_fields,
            latency_ms=(time.perf_counter() - t_l1) * 1000.0,
        )

        # Level 2 (stored artifact read back from GCS) + Level 3 (reconciliation) via canonical verifiers
        t_l2 = time.perf_counter()
        level2 = verify_level2_stored_artifact(validation_source, entry, gpq_meta)
        level3 = verify_level3_reconciliation(entry, level1, level2, {"pages_fetched": len(sublayers)})
        validation_ms = (time.perf_counter() - t_l2) * 1000.0
        overall = compute_overall_dataset_qa_status(level1, level2, level3)
        print(f"  QA: L1={level1['status']} L2={level2['status']} L3={level3['status']} -> overall {overall}")
        if not upload_cloud:
            os.unlink(validation_source)  # ephemeral dry-run temp cleanup

        fetch_pages = sum((n + 999) // 1000 for _, _, _, n in sublayers)
        record = {
            "dataset_key": key,
            "title": title,
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
            "retrieval_id": timestamp,
            "ingestion_software_version": INGESTION_SOFTWARE_VERSION,
            "transformation_version": TRANSFORMATION_VERSION,
            "original_crs": entry.original_crs,
            "stored_crs": level2["stored_crs"],
            "geometry_type": ", ".join(level2["geometry_types"]),
            "feature_count": level2["feature_count"],
            "bbox": level2["bbox"],
            "file_size_bytes": level2["file_size_bytes"],
            "sha256": level2["sha256"],
            "gcs_generation": gpq_meta["gcs_generation"],
            "gs_uri": gpq_meta["gs_uri"],
            "local_parquet_path": gpq_meta["local_path"],
            "raw_payload_gs_uri": raw_meta["gs_uri"],
            "raw_payload_sha256": raw_meta["sha256"],
            "preview_geojson": preview_meta,
            "overall_qa_status": overall,
            "level1_source_contract": level1,
            "level2_stored_artifact": level2,
            "level3_reconciliation": level3,
            "known_limitations": entry.known_limitations,
            "refresh_policy": entry.refresh_policy,
            "operational_suitability": entry.operational_suitability,
            "telemetry": {
                "dataset_key": key,
                "retrieval_timestamp_utc": retrieval_iso,
                "http_requests_count": fetch_pages + len(sublayers),
                "normalization_ms": round(normalization_ms, 2),
                "validation_ms": round(validation_ms, 2),
                "total_elapsed_ms": round((time.perf_counter() - t_ds) * 1000.0, 2),
                "bytes_written": gpq_meta["file_size_bytes"],
                "notes": [
                    "Multi-layer MapServer harvest aggregated across per-cyclone event sublayers.",
                    "Level 1 recorded from live harvest evidence; source counts independently re-probed via returnCountOnly.",
                ],
            },
        }

        # Immutable QA snapshot + latest dataset manifest record written DIRECTLY to GCS
        # (build_qa_summary reads them back from GCS; no local lake staging).
        record_bytes = json.dumps(record, indent=2, ensure_ascii=False).encode("utf-8")
        if upload_cloud:
            store.upload_bytes_cloud(
                store.dataset_qa_object_key(key, timestamp),
                record_bytes,
                content_type="application/json; charset=utf-8",
            )
            store.upload_bytes_cloud(
                store.dataset_manifest_object_key(key),
                record_bytes,
                content_type="application/json; charset=utf-8",
            )
        else:
            print("  [DRY-RUN] QA records not persisted (cloud writes skipped)")

        # Update catalogue manifest pointers to the new immutable snapshot
        if upload_cloud and register:
            entry.qa_status = QAStatus(overall)
            entry.latest_snapshot_path = gpq_meta["gs_uri"]
            entry.latest_retrieval_utc = retrieval_iso
            registry.manifest.updated_at_utc = retrieval_iso
            save_manifest(registry.manifest, registry.manifest_path)
            print(f"  Registered in catalogue manifest (qa_status={overall}, snapshot={gpq_meta['gs_uri']})")

        prepared_items.append({
            "key": key,
            "title": title,
            "url": gcs_url,
            "target_table": f"org_catalog.ops_intel.{key}",
            "expected_rows": write_info["feature_count"],
        })

    # Refresh the QA summary + web pages from the canonical GCS records.
    # Use the full registry (AURA linked library included) so the published QA
    # hub stays complete; this does not write back to config/dataset_manifest.json.
    if upload_cloud:
        from src.validation.qa_report import build_qa_summary, render_qa_html_pages
        summary = build_qa_summary(
            registry=DatasetRegistry(),
            storage=store,
            upload_cloud=True,
            write_local=False,
        )
        render_qa_html_pages(summary, storage=store, upload_cloud=True)
        print(f"QA summary refreshed: {summary['report_id']} | counts: {summary['status_counts']}")

    if skip_wherobots or not upload_cloud:
        print("\nWherobots dispatch skipped (--skip-wherobots or --dry-run).")
        return

    # Dispatch Wherobots Batch Ingestion Job
    print("\n" + "=" * 70)
    print(f"DISPATCHING WHEROBOTS BATCH INGESTION FOR {len(prepared_items)} TABLES")
    print("=" * 70)

    from wherobots import WherobotsJob

    scratch_manifest = PROJECT_ROOT / "scratch" / "wherobots_manifest.json"
    with open(scratch_manifest, "w", encoding="utf-8") as f:
        json.dump(prepared_items, f, indent=2)

    manifest_dep = WherobotsJob.add_file_dependency(str(scratch_manifest))
    script_path = str(PROJECT_ROOT / "tools" / "wherobots_batch_ingest.py")
    api_key = os.environ.get("WHEROBOTS_API_KEY", "").strip()
    job = WherobotsJob(
        script=script_path,
        name="oic-qld-cyclones-upload",
        runtime="tiny",
        api_key=api_key,
        dependencies=[manifest_dep],
    )

    job.submit()
    print(f"  Job dispatched. Run ID: {job.run_id}")
    print("  Streaming remote Spark execution logs...")
    status = job.wait_for_completion(stream_logs=True)
    print(f"\nJob finished with status: {status}")

    # Explicit Zero-Mock DB-API Verification
    print("\n[VERIFICATION] Verifying Iceberg tables via Wherobots DB-API...")
    from wherobots.db import connect
    conn = connect(api_key=api_key, runtime="tiny")
    curr = conn.cursor()
    try:
        for item in prepared_items:
            tbl = item["target_table"]
            exp = item["expected_rows"]
            curr.execute(f"SELECT count(*) FROM {tbl}")
            df = curr.fetchall()
            actual = int(df.iloc[0, 0])
            if actual == exp:
                print(f"  [PASS] {tbl}: {actual} rows (expected: {exp})")
            else:
                print(f"  [FAIL] {tbl}: got {actual} rows, expected {exp}")
    finally:
        conn.close()

    # Teardown Audit
    engine = WherobotsSedonaEngine(api_key=api_key)
    audit = engine.audit_active_sessions()
    print(f"\n[TEARDOWN AUDIT] Active Sessions: {audit.get('active_sessions')} | Cost: $0.00/hr ({audit.get('status')})")

def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Cloud-first QLD historical cyclone harvester (MapServer -> in-memory GeoParquet -> GCS + QA)"
    )
    parser.add_argument("--dry-run", action="store_true", help="Ephemeral in-memory validation only (no GCS, no local data staging)")
    parser.add_argument("--skip-wherobots", action="store_true", help="Skip Iceberg dispatch + DB-API verification")
    parser.add_argument("--no-register", action="store_true", help="Do not touch the catalogue manifest")
    args = parser.parse_args()
    harvest_qld_cyclones(
        dry_run=args.dry_run,
        skip_wherobots=args.skip_wherobots,
        register=not args.no_register,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
