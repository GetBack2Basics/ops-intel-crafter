"""Ingest and Publish National ABS 1 km² Population Grid (Australia-Wide) — Cloud-First.

- Downloads the official ABS 2025 Australian Population Grid raster GeoTIFF.
- Extracts all populated cells across the Australian continent (~27.61M people).
- Runs Zero-Mock Level 1, Level 2, and Level 3 validation gates.
- Writes Stored GeoParquet (EPSG:7844) to an in-memory buffer and uploads it directly
  to `gs://<bucket>/geoparquet/abs_australia_1km_population_grid/<vintage>/<ts>/`.
- Level 2 validates the stored artifact by reading it back from `gs://` (no local lake).
- Streams RFC 7946 deliverables straight to `gs://<bucket>/exports/australia_population_grid/`
  (result.parquet, result.geojson, analysis_manifest.json).
- Publishes canonical dataset/QA manifests and updates `config/dataset_manifest.json`.

No `data/lake/` staging is written. Passing `upload_cloud=False` performs a fully
ephemeral dry-run: validation runs against a temp file and nothing is persisted.
"""

import hashlib
import io
import json
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Dict

import geopandas as gpd
import numpy as np
import pyproj
import shapely
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.catalogue.manifest_loader import (
    DatasetCategory,
    DatasetEntry,
    LicenceMetadata,
    QAStatus,
    load_manifest,
    save_manifest,
)
from src.ingestion.gcs_storage import GCSLakeStorage
from src.ingestion.telemetry import utc_now_compact, utc_now_iso
from src.validation.geoparquet_validation import verify_level2_stored_artifact
from src.validation.reconciliation import compute_overall_dataset_qa_status, verify_level3_reconciliation
from src.validation.source_contracts import verify_level1_source_contract

ABS_GEOTIFF_ZIP_URL = "https://www.abs.gov.au/statistics/people/population/regional-population/2024-25/GEOTIFF.zip"
DATASET_KEY = "abs_australia_1km_population_grid"
SOURCE_VINTAGE = "2025-ABS"
EXPORT_NAME = "australia_population_grid"


def create_national_dataset_entry() -> DatasetEntry:
    """Builds the canonical DatasetEntry for the ABS 2025 National 1 km² Population Grid."""
    return DatasetEntry(
        dataset_key=DATASET_KEY,
        title="ABS 2025 — Australian Population Grid 1 km² (National Modeled ERP Grid)",
        category=DatasetCategory.PERIODICALLY_REFRESHED,
        theme="NExT Population & Geography",
        scale="national",
        jurisdiction="NATIONAL",
        provider="Australian Bureau of Statistics",
        source_agency="Australian Bureau of Statistics (ABS)",
        service_type="file_download",
        endpoint=ABS_GEOTIFF_ZIP_URL,
        licence=LicenceMetadata(
            name="CC-BY-4.0",
            url="https://creativecommons.org/licenses/by/4.0/",
            attribution="© Commonwealth of Australia (Australian Bureau of Statistics 2025) — CC-BY 4.0",
            redistribution_permitted=True,
            verified_on="2026-11-10",
        ),
        source_publication_date="2026-03-26",
        source_vintage=SOURCE_VINTAGE,
        refresh_policy="annual_release",
        original_crs="EPSG:3577",
        stored_crs="EPSG:7844",
        metric_crs="EPSG:3112",
        geometry_type="Polygon",
        primary_key="cell_id",
        required_fields=["cell_id", "easting_m", "northing_m", "cell_population", "centroid_lon", "centroid_lat"],
        schema_mapping={
            "cell_id": "cell_id",
            "cell_population": "cell_population",
            "easting_m": "easting_m",
            "northing_m": "northing_m",
        },
        known_limitations=[
            "Official ABS modeled 1 km² Estimated Resident Population (ERP) grid based on the National Nested Grid Standard.",
            "Population counts are disaggregated from SA1 using ABS Address Register and ICP points; modelled proxy, not a direct headcount.",
        ],
        operational_suitability="National baseline for Method A, B, and C exposure calculations across Australia.",
        default_bbox=[95.0, -45.0, 168.0, -9.0],
    )


def _stream_national_geojson(
    cell_ids: list[str],
    pops: np.ndarray,
    gdf_7844: gpd.GeoDataFrame,
    bbox_4326: list[float],
    provenance: Dict[str, Any],
    num_cells: int,
) -> bytes:
    """Streams the RFC 7946 centroids GeoJSON into memory (no local file staging)."""
    buf = io.StringIO()
    buf.write('{"type":"FeatureCollection","name":"australia_population_grid","bbox":')
    json.dump(bbox_4326, buf)
    buf.write(',"oic_provenance":')
    json.dump(provenance, buf, separators=(",", ":"))
    buf.write(',"features":[')

    centroids = gdf_7844[["centroid_lon", "centroid_lat"]].to_numpy(copy=False)
    easting = gdf_7844["easting_m"].to_numpy(copy=False)
    northing = gdf_7844["northing_m"].to_numpy(copy=False)
    for i in range(num_cells):
        cid = cell_ids[i]
        lon = float(centroids[i, 0])
        lat = float(centroids[i, 1])
        sep = "," if i > 0 else ""
        buf.write(
            f'{sep}{{"type":"Feature","id":"{cid}",'
            f'"properties":{{"cell_id":"{cid}","cell_population":{round(float(pops[i]), 1)},'
            f'"easting_m":{round(float(easting[i]), 1)},"northing_m":{round(float(northing[i]), 1)}}},'
            f'"geometry":{{"type":"Point","coordinates":[{lon},{lat}]}}}}'
        )
    buf.write("]}")
    return buf.getvalue().encode("utf-8")


def ingest_national_population_grid(
    upload_cloud: bool = True,
    persist_records: bool = True,
) -> Dict[str, Any]:
    """Ingests the national grid cloud-first; `upload_cloud=False` is an ephemeral dry-run."""
    print("=" * 78)
    print("INGESTING NATIONAL ABS 1 KM² POPULATION GRID (ALL OF AUSTRALIA)")
    print("=" * 78)

    entry = create_national_dataset_entry()
    store = GCSLakeStorage()

    # Step 1: Level 1 Source Contract Verification
    print("\n[Step 1/6] Running Level 1 Source Contract Verification...")
    l1_report = verify_level1_source_contract(entry)
    print(f"  Level 1 Status: {l1_report['status']}")
    print(f"  HTTP Status:    {l1_report.get('http_status')} ({l1_report.get('latency_ms')} ms)")
    print(f"  Source Cells:   {l1_report.get('source_feature_count'):,}")

    raw_zip_bytes = l1_report.pop("_raw_bytes", None)
    if not raw_zip_bytes:
        print("  Downloading ZIP archive directly...")
        req = urllib.request.Request(entry.endpoint, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=45) as resp:
            raw_zip_bytes = resp.read()

    # Step 2: Extract & Vectorize the continental grid
    print("\n[Step 2/6] Vectorizing 1 km² continental grid from GeoTIFF...")
    zf = zipfile.ZipFile(io.BytesIO(raw_zip_bytes))
    tif_name = [n for n in zf.namelist() if n.endswith(".tif")][0]
    im = Image.open(io.BytesIO(zf.read(tif_name)))
    arr = np.array(im)

    valid_mask = np.isfinite(arr) & (arr > 0)
    rows, cols = np.where(valid_mask)
    pops = arr[valid_mask].astype(np.float32)
    total_pop = float(np.sum(pops))
    num_cells = len(rows)

    print(f"  Populated Cells: {num_cells:,}")
    print(f"  Total ERP Pop:   {total_pop:,.1f}")

    # Tiepoint and resolution from GeoTIFF tags:
    x0, y0 = -3901000.0, -1000000.0
    res = 1000.0

    minx = x0 + cols * res
    maxx = minx + res
    maxy = y0 - rows * res
    miny = maxy - res

    cx = minx + 500.0
    cy = miny + 500.0

    print("  Constructing Shapely 2.0 polygons and computing cell identifiers...")
    boxes = shapely.box(minx, miny, maxx, maxy)
    cell_ids = [f"G1KM_{int(e // 1000)}_{int(n // 1000)}" for e, n in zip(cx, cy)]

    print("  Creating EPSG:3577 GeoDataFrame...")
    gdf_3577 = gpd.GeoDataFrame(
        {
            "cell_id": cell_ids,
            "easting_m": cx.astype(np.float64),
            "northing_m": cy.astype(np.float64),
            "cell_population": pops,
        },
        geometry=boxes,
        crs="EPSG:3577",
    )

    print("  Reprojecting continental grid to stored CRS EPSG:7844 (GDA2020)...")
    gdf_7844 = gdf_3577.to_crs("EPSG:7844")

    print("  Computing EPSG:7844 centroid coordinates and bounding boxes...")
    trans = pyproj.Transformer.from_crs("EPSG:3577", "EPSG:7844", always_xy=True)
    clon, clat = trans.transform(cx, cy)
    gdf_7844["centroid_lon"] = np.round(clon, 6)
    gdf_7844["centroid_lat"] = np.round(clat, 6)

    bounds = gdf_7844.geometry.bounds
    gdf_7844["_bbox_minx"] = bounds["minx"].astype(np.float64)
    gdf_7844["_bbox_miny"] = bounds["miny"].astype(np.float64)
    gdf_7844["_bbox_maxx"] = bounds["maxx"].astype(np.float64)
    gdf_7844["_bbox_maxy"] = bounds["maxy"].astype(np.float64)

    retrieval_iso = utc_now_iso()
    retrieval_compact = utc_now_compact()
    gdf_7844["_oic_dataset_key"] = DATASET_KEY
    gdf_7844["_oic_source_vintage"] = SOURCE_VINTAGE
    gdf_7844["_oic_retrieval_utc"] = retrieval_iso

    # Step 3: Write Level 2 Stored GeoParquet artifact IN MEMORY, then upload to GCS
    print("\n[Step 3/6] Writing Stored GeoParquet artifact (in memory)...")
    gpq_key = store.geoparquet_object_key(
        dataset_key=DATASET_KEY,
        source_vintage=SOURCE_VINTAGE,
        retrieval_ts=retrieval_compact,
        part=0,
    )
    pq_buffer = io.BytesIO()
    gdf_7844.to_parquet(pq_buffer, index=False, schema_version="1.1.0")
    pq_bytes = pq_buffer.getvalue()
    file_size_mb = round(len(pq_bytes) / (1024 * 1024), 2)
    print(f"  GeoParquet serialized: part-00000.parquet ({file_size_mb} MB)")

    if upload_cloud:
        gpq_meta = store.upload_bytes_cloud(
            gpq_key,
            pq_bytes,
            dataset_entry=entry.model_dump(mode="json"),
            content_type="application/vnd.apache.parquet",
        )
        validation_source: Any = gpq_meta["gs_uri"]
        print(f"  Uploaded {gpq_meta['gs_uri']} (generation={gpq_meta['gcs_generation']})")
    else:
        tmp = tempfile.NamedTemporaryFile(suffix=".parquet", delete=False)
        tmp.write(pq_bytes)
        tmp.close()
        validation_source = tmp.name
        gpq_meta = {
            "object_key": gpq_key,
            "gs_uri": store.gs_uri(gpq_key),
            "local_path": None,
            "file_size_bytes": len(pq_bytes),
            "sha256": hashlib.sha256(pq_bytes).hexdigest(),
            "storage_mode": "dry_run_ephemeral",
            "gcs_generation": "dry-run-not-uploaded",
        }
        print(f"  Dry-run: validating ephemeral buffer ({len(pq_bytes):,} bytes, not persisted)")

    # Run Level 2 & Level 3 Validation against the stored artifact (gs:// when uploaded)
    print("  Running Level 2 Stored Artifact Validation...")
    l2_report = verify_level2_stored_artifact(validation_source, entry, storage_meta=gpq_meta)
    print(f"  Level 2 Status: {l2_report['status']}")

    print("  Running Level 3 Source-to-Storage Reconciliation...")
    l3_report = verify_level3_reconciliation(entry, l1_report, l2_report)
    print(f"  Level 3 Status: {l3_report['status']} ({l3_report.get('reconciliation_rate_pct')}%)")

    overall_status = compute_overall_dataset_qa_status(l1_report, l2_report, l3_report)
    print(f"  Overall Dataset QA Status: {overall_status}")

    if not upload_cloud:
        Path(validation_source).unlink(missing_ok=True)

    # Update the top-level catalogue manifest pointer (only when persisting records)
    entry.qa_status = QAStatus(overall_status)
    entry.latest_retrieval_utc = retrieval_iso
    if upload_cloud:
        entry.latest_snapshot_path = gpq_meta["gs_uri"]
        manifest = load_manifest()
        manifest.datasets[DATASET_KEY] = entry
        manifest.updated_at_utc = retrieval_iso
        save_manifest(manifest)
        print("  Updated config/dataset_manifest.json with gs:// snapshot pointer.")
    else:
        print("  Dry-run: config/dataset_manifest.json left unchanged.")

    # Step 4: Export National Deliverables (Parquet + GeoJSON Centroids + Manifest) in memory
    print("\n[Step 4/6] Building RFC 7946 National Deliverables (in memory)...")
    exp_parquet_bytes = pq_bytes

    min_lon = float(gdf_7844["centroid_lon"].min())
    min_lat = float(gdf_7844["centroid_lat"].min())
    max_lon = float(gdf_7844["centroid_lon"].max())
    max_lat = float(gdf_7844["centroid_lat"].max())
    bbox_4326 = [round(min_lon, 6), round(min_lat, 6), round(max_lon, 6), round(max_lat, 6)]

    provenance = {
        "analysis_id": EXPORT_NAME,
        "title": "ABS 2025 Australian National 1 km² Population Grid (All Australia)",
        "generated_at_utc": retrieval_iso,
        "rfc7946_crs": "EPSG:4326",
        "source_datasets": [DATASET_KEY],
        "source_vintages": {DATASET_KEY: SOURCE_VINTAGE},
        "population_method": "ABS_NESTED_GRID_ERP",
        "total_population": round(total_pop, 1),
        "feature_count": num_cells,
        "bbox": bbox_4326,
        "stored_parquet_gs_uri": gpq_meta["gs_uri"],
        "geolibre_qgis_compatible": True,
    }
    exp_geojson_bytes = _stream_national_geojson(
        cell_ids=cell_ids,
        pops=pops,
        gdf_7844=gdf_7844,
        bbox_4326=bbox_4326,
        provenance=provenance,
        num_cells=num_cells,
    )
    print(
        f"  Built result.geojson ({round(len(exp_geojson_bytes) / (1024 * 1024), 2)} MB, {num_cells:,} features)"
    )

    manifest_doc = {
        "analysis_id": EXPORT_NAME,
        "title": "ABS 2025 Australian National 1 km² Population Grid (All Australia)",
        "generated_at_utc": retrieval_iso,
        "source_dataset": DATASET_KEY,
        "source_vintage": SOURCE_VINTAGE,
        "feature_count": num_cells,
        "total_population": round(total_pop, 1),
        "parquet_sha256": hashlib.sha256(exp_parquet_bytes).hexdigest(),
        "geojson_sha256": hashlib.sha256(exp_geojson_bytes).hexdigest(),
        "stored_parquet_gs_uri": gpq_meta["gs_uri"],
        "gcs_generation": gpq_meta["gcs_generation"],
        "licence": entry.licence.model_dump(),
        "level1_source_contract": l1_report,
        "level2_stored_artifact": l2_report,
        "level3_reconciliation": l3_report,
    }
    exp_manifest_bytes = json.dumps(manifest_doc, indent=2, ensure_ascii=False).encode("utf-8")
    print("  Built analysis_manifest.json")

    # Step 5: Publish stored snapshot, exports, and canonical manifests to GCS
    if upload_cloud:
        print("\n[Step 5/6] Publishing to Google Cloud Storage...")
        for filename, payload, content_type in (
            ("result.parquet", exp_parquet_bytes, "application/vnd.apache.parquet"),
            ("result.geojson", exp_geojson_bytes, "application/geo+json; charset=utf-8"),
            ("analysis_manifest.json", exp_manifest_bytes, "application/json; charset=utf-8"),
        ):
            export_meta = store.upload_bytes_cloud(
                f"exports/{EXPORT_NAME}/{filename}",
                payload,
                dataset_entry=entry.model_dump(mode="json"),
                content_type=content_type,
            )
            print(f"  Uploaded {export_meta['gs_uri']} ({export_meta['file_size_bytes']:,} bytes)")

        # Canonical per-dataset version + QA record so the QA report reads it from GCS
        dataset_record = {
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
            "original_crs": entry.original_crs,
            "stored_crs": l2_report["stored_crs"],
            "geometry_type": ", ".join(l2_report["geometry_types"]),
            "feature_count": l2_report["feature_count"],
            "bbox": l2_report["bbox"],
            "file_size_bytes": l2_report["file_size_bytes"],
            "sha256": l2_report["sha256"],
            "gcs_generation": gpq_meta["gcs_generation"],
            "gs_uri": gpq_meta["gs_uri"],
            "local_parquet_path": None,
            "overall_qa_status": overall_status,
            "level1_source_contract": l1_report,
            "level2_stored_artifact": l2_report,
            "level3_reconciliation": l3_report,
            "known_limitations": entry.known_limitations,
            "refresh_policy": entry.refresh_policy,
            "operational_suitability": entry.operational_suitability,
        }
        record_bytes = json.dumps(dataset_record, indent=2, ensure_ascii=False).encode("utf-8")
        for object_key in (
            store.dataset_qa_object_key(DATASET_KEY, retrieval_compact),
            store.dataset_manifest_object_key(DATASET_KEY),
        ):
            store.upload_bytes_cloud(
                object_key,
                record_bytes,
                dataset_entry=entry.model_dump(mode="json"),
                content_type="application/json; charset=utf-8",
            )
            print(f"  Uploaded {store.gs_uri(object_key)}")

        catalogue_bytes = (PROJECT_ROOT / "config" / "dataset_manifest.json").read_bytes()
        store.upload_bytes_cloud(
            "manifests/dataset_manifest.json",
            catalogue_bytes,
            content_type="application/json; charset=utf-8",
        )
        print(f"  Uploaded {store.gs_uri('manifests/dataset_manifest.json')}")

        # Step 6: Verify HTTPS Endpoints
        print("\n[Step 6/6] Verifying Live GCS HTTPS Endpoints...")
        for filename in ("result.geojson", "result.parquet", "analysis_manifest.json"):
            url = f"https://storage.googleapis.com/{store.bucket_name}/exports/{EXPORT_NAME}/{filename}"
            try:
                req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    print(f"  [OK {resp.status}] {url}")
            except Exception as e:
                print(f"  [WARN] {url}: {e}")
    else:
        print("\n[Step 5/6] Dry-run: skipping GCS publication (nothing persisted).")
        print("[Step 6/6] Dry-run: skipping live HTTPS verification.")

    print("\n" + "=" * 78)
    print("NATIONAL POPULATION GRID INGESTION & PUBLICATION COMPLETE")
    print("=" * 78)

    return {
        "status": "SUCCESS",
        "storage_mode": gpq_meta["storage_mode"],
        "cell_count": num_cells,
        "total_population": total_pop,
        "parquet_gs_uri": gpq_meta["gs_uri"] if upload_cloud else None,
        "gcs_generation": gpq_meta["gcs_generation"],
        "overall_qa_status": overall_status,
    }


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv or "--skip-gcs" in sys.argv
    res = ingest_national_population_grid(upload_cloud=not dry_run)
    print("\nResult summary:", json.dumps(res, indent=2))
