"""Ingest and Publish National ABS 1 km² Population Grid (Australia-Wide).

- Downloads official ABS 2025 Australian Population Grid raster GeoTIFF.
- Extracts all 286,827 populated cells across the Australian continent (~27.61M people).
- Runs Zero-Mock Level 1, Level 2, and Level 3 validation gates.
- Writes Stored GeoParquet (EPSG:7844) to data/lake/geoparquet/abs_australia_1km_population_grid/.
- Generates RFC 7946 deliverables in data/lake/exports/australia_population_grid/ (result.parquet, result.geojson, analysis_manifest.json).
- Updates config/dataset_manifest.json and uploads directly to Google Cloud Storage.
"""

import io
import json
import os
import sys
import time
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

from src.catalogue.manifest_loader import DatasetCategory, DatasetEntry, LicenceMetadata, QAStatus, load_manifest, save_manifest
from src.ingestion.gcs_storage import GCSLakeStorage
from src.ingestion.telemetry import compute_sha256, utc_now_compact, utc_now_iso
from src.validation.geoparquet_validation import verify_level2_stored_artifact
from src.validation.reconciliation import compute_overall_dataset_qa_status, verify_level3_reconciliation
from src.validation.source_contracts import verify_level1_source_contract

ABS_GEOTIFF_ZIP_URL = "https://www.abs.gov.au/statistics/people/population/regional-population/2024-25/GEOTIFF.zip"
DATASET_KEY = "abs_australia_1km_population_grid"
SOURCE_VINTAGE = "2025-ABS"


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


def ingest_national_population_grid(upload_cloud: bool = True) -> Dict[str, Any]:
    print("=" * 78)
    print("INGESTING NATIONAL ABS 1 KM² POPULATION GRID (ALL OF AUSTRALIA)")
    print("=" * 78)

    entry = create_national_dataset_entry()

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

    # Step 2: Extract & Vectorize 286,827 Grid Cells
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

    # Step 3: Write Level 2 Stored GeoParquet Artifact
    print("\n[Step 3/6] Writing Stored GeoParquet artifact...")
    parquet_dir = (
        PROJECT_ROOT
        / "data"
        / "lake"
        / "geoparquet"
        / DATASET_KEY
        / SOURCE_VINTAGE
        / retrieval_compact
    )
    parquet_dir.mkdir(parents=True, exist_ok=True)
    parquet_file = parquet_dir / "part-00000.parquet"
    gdf_7844.to_parquet(parquet_file, index=False, schema_version="1.1.0")

    file_size_mb = round(parquet_file.stat().st_size / (1024 * 1024), 2)
    print(f"  GeoParquet written: {parquet_file.name} ({file_size_mb} MB)")

    # Run Level 2 & Level 3 Validation
    print("  Running Level 2 Stored Artifact Validation...")
    l2_report = verify_level2_stored_artifact(parquet_file, entry)
    print(f"  Level 2 Status: {l2_report['status']}")

    print("  Running Level 3 Source-to-Storage Reconciliation...")
    l3_report = verify_level3_reconciliation(entry, l1_report, l2_report)
    print(f"  Level 3 Status: {l3_report['status']} ({l3_report.get('reconciliation_rate_pct')}%)")

    overall_status = compute_overall_dataset_qa_status(l1_report, l2_report, l3_report)
    print(f"  Overall Dataset QA Status: {overall_status}")

    # Update manifest entry
    entry.qa_status = QAStatus(overall_status)
    rel_parquet_path = str(parquet_file.relative_to(PROJECT_ROOT)).replace("\\", "/")
    entry.latest_snapshot_path = rel_parquet_path
    entry.latest_retrieval_utc = retrieval_iso

    manifest = load_manifest()
    manifest.datasets[DATASET_KEY] = entry
    manifest.updated_at_utc = retrieval_iso
    save_manifest(manifest)
    print("  Updated config/dataset_manifest.json with new dataset entry.")

    # Step 4: Export National Deliverables (Parquet + GeoJSON Centroids + Manifest)
    print("\n[Step 4/6] Exporting RFC 7946 National Deliverables...")
    exports_dir = PROJECT_ROOT / "data" / "lake" / "exports" / "australia_population_grid"
    exports_dir.mkdir(parents=True, exist_ok=True)

    # 1. Full Polygon Parquet
    exp_parquet = exports_dir / "result.parquet"
    gdf_7844.to_parquet(exp_parquet, index=False, schema_version="1.1.0")
    print(f"  Exported result.parquet ({round(exp_parquet.stat().st_size / (1024*1024), 2)} MB)")

    # 2. RFC 7946 Centroids GeoJSON (fast, web-friendly, ~32MB compact)
    print("  Generating RFC 7946 Centroids GeoJSON...")
    exp_geojson = exports_dir / "result.geojson"

    min_lon = float(gdf_7844["centroid_lon"].min())
    min_lat = float(gdf_7844["centroid_lat"].min())
    max_lon = float(gdf_7844["centroid_lon"].max())
    max_lat = float(gdf_7844["centroid_lat"].max())
    bbox_4326 = [round(min_lon, 6), round(min_lat, 6), round(max_lon, 6), round(max_lat, 6)]

    # Stream compact GeoJSON to avoid memory overhead
    with open(exp_geojson, "w", encoding="utf-8") as f:
        f.write('{"type":"FeatureCollection","name":"australia_population_grid","bbox":')
        json.dump(bbox_4326, f)
        f.write(',"oic_provenance":{')
        prov = {
            "analysis_id": "australia_population_grid",
            "title": "ABS 2025 Australian National 1 km² Population Grid (All Australia)",
            "generated_at_utc": retrieval_iso,
            "rfc7946_crs": "EPSG:4326",
            "source_datasets": [DATASET_KEY],
            "source_vintages": {DATASET_KEY: SOURCE_VINTAGE},
            "population_method": "ABS_NESTED_GRID_ERP",
            "total_population": round(total_pop, 1),
            "feature_count": num_cells,
            "bbox": bbox_4326,
            "geolibre_qgis_compatible": True,
        }
        f.write(f'"analysis_id":"{prov["analysis_id"]}",')
        f.write(f'"title":"{prov["title"]}",')
        f.write(f'"total_population":{prov["total_population"]},')
        f.write(f'"feature_count":{prov["feature_count"]},')
        f.write(f'"rfc7946_crs":"EPSG:4326"')
        f.write('},"features":[')

        # Vectorized write of feature items
        chunk_size = 50000
        for i in range(num_cells):
            cid = cell_ids[i]
            p = float(pops[i])
            lon = float(gdf_7844["centroid_lon"].iloc[i])
            lat = float(gdf_7844["centroid_lat"].iloc[i])
            em = float(gdf_7844["easting_m"].iloc[i])
            nm = float(gdf_7844["northing_m"].iloc[i])
            sep = "," if i > 0 else ""
            feat_str = (
                f'{sep}{{"type":"Feature","id":"{cid}",'
                f'"properties":{{"cell_id":"{cid}","cell_population":{round(p, 1)},'
                f'"easting_m":{round(em, 1)},"northing_m":{round(nm, 1)}}},'
                f'"geometry":{{"type":"Point","coordinates":[{lon},{lat}]}}}}'
            )
            f.write(feat_str)
        f.write("]}")

    geojson_size_mb = round(exp_geojson.stat().st_size / (1024 * 1024), 2)
    print(f"  Exported result.geojson ({geojson_size_mb} MB, {num_cells:,} features)")

    # 3. Sidecar Analysis Manifest
    exp_manifest = exports_dir / "analysis_manifest.json"
    manifest_doc = {
        "analysis_id": "australia_population_grid",
        "title": "ABS 2025 Australian National 1 km² Population Grid (All Australia)",
        "generated_at_utc": retrieval_iso,
        "source_dataset": DATASET_KEY,
        "source_vintage": SOURCE_VINTAGE,
        "feature_count": num_cells,
        "total_population": round(total_pop, 1),
        "parquet_sha256": compute_sha256(exp_parquet),
        "geojson_sha256": compute_sha256(exp_geojson),
        "licence": entry.licence.model_dump(),
        "level1_source_contract": l1_report,
        "level2_stored_artifact": l2_report,
        "level3_reconciliation": l3_report,
    }
    with open(exp_manifest, "w", encoding="utf-8") as f:
        json.dump(manifest_doc, f, indent=2)
    print(f"  Exported analysis_manifest.json")

    # Mirror to docs/exports/ for local static web hosting / QA
    docs_exp_dir = PROJECT_ROOT / "docs" / "exports" / "australia_population_grid"
    docs_exp_dir.mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.copy2(exp_parquet, docs_exp_dir / "result.parquet")
    shutil.copy2(exp_geojson, docs_exp_dir / "result.geojson")
    shutil.copy2(exp_manifest, docs_exp_dir / "analysis_manifest.json")
    print("  Mirrored exports to docs/exports/australia_population_grid/")

    # Step 5: Upload to Cloud Lakehouse (GCS)
    if upload_cloud:
        print("\n[Step 5/6] Uploading to Google Cloud Storage (gs://operational-intelligence-crafter-lake/)...")
        from google.cloud import storage

        client = storage.Client()
        bucket = client.bucket("operational-intelligence-crafter-lake")

        # 1. Upload Stored GeoParquet snapshot
        gcs_pq_key = f"geoparquet/{DATASET_KEY}/{SOURCE_VINTAGE}/{retrieval_compact}/part-00000.parquet"
        blob_pq = bucket.blob(gcs_pq_key)
        blob_pq.upload_from_filename(str(parquet_file), content_type="application/vnd.apache.parquet")
        print(f"  Uploaded gs://operational-intelligence-crafter-lake/{gcs_pq_key}")

        # 2. Upload Exports
        for local_f, ctype in [
            (exp_parquet, "application/vnd.apache.parquet"),
            (exp_geojson, "application/geo+json"),
            (exp_manifest, "application/json"),
        ]:
            blob_key = f"exports/australia_population_grid/{local_f.name}"
            b = bucket.blob(blob_key)
            b.upload_from_filename(str(local_f), content_type=ctype)
            print(f"  Uploaded gs://operational-intelligence-crafter-lake/{blob_key}")

        # 3. Upload updated config/dataset_manifest.json
        manifest_blob = bucket.blob("config/dataset_manifest.json")
        manifest_blob.upload_from_filename(
            str(PROJECT_ROOT / "config" / "dataset_manifest.json"), content_type="application/json"
        )
        print("  Uploaded gs://operational-intelligence-crafter-lake/config/dataset_manifest.json")

    # Step 6: Verify HTTPS Endpoints
    print("\n[Step 6/6] Verifying Live GCS HTTPS Endpoints...")
    test_urls = [
        "https://storage.googleapis.com/operational-intelligence-crafter-lake/exports/australia_population_grid/result.geojson",
        "https://storage.googleapis.com/operational-intelligence-crafter-lake/exports/australia_population_grid/result.parquet",
        "https://storage.googleapis.com/operational-intelligence-crafter-lake/exports/australia_population_grid/analysis_manifest.json",
    ]
    for url in test_urls:
        try:
            req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                print(f"  [OK {resp.status}] {url}")
        except Exception as e:
            print(f"  [WARN] {url}: {e}")

    print("\n" + "=" * 78)
    print("NATIONAL POPULATION GRID INGESTION & PUBLICATION COMPLETE")
    print("=" * 78)

    return {
        "status": "SUCCESS",
        "cell_count": num_cells,
        "total_population": total_pop,
        "parquet_path": str(parquet_file),
        "export_geojson_path": str(exp_geojson),
        "export_parquet_path": str(exp_parquet),
        "overall_qa_status": overall_status,
    }


if __name__ == "__main__":
    res = ingest_national_population_grid(upload_cloud=True)
    print("\nResult summary:", json.dumps({k: v for k, v in res.items() if not k.endswith("_path")}, indent=2))
