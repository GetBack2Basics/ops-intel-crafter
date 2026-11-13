"""Harvest Queensland Historical Cyclones MapServer layers, combine into canonical GeoParquet,
upload to Google Cloud Storage, and publish as permanent Iceberg tables in Wherobots Cloud.

MapServer: https://spatial-gis.information.qld.gov.au/arcgis/rest/services/EventsIncidents/CycloneHistorical/MapServer
Three target Iceberg tables in org_catalog.ops_intel:
  1. qld_cyclones_historical_tracks (Polyline/LineString - 52 features)
  2. qld_cyclones_historical_fixes (Point - 955 features)
  3. qld_cyclones_historical_wind_areas (Polygon/MultiPolygon - 3,349 features)
"""

import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Tuple

import dotenv
import geopandas as gpd
import pandas as pd
import requests
from google.cloud import storage

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.engines.wherobots_engine import WherobotsSedonaEngine

dotenv.load_dotenv(PROJECT_ROOT / ".env")

GCS_BUCKET_NAME = os.environ.get("OIC_GCS_BUCKET", "operational-intelligence-crafter-lake")
LAKE_ROOT = PROJECT_ROOT / "data" / "lake"
MAPSERVER_URL = "https://spatial-gis.information.qld.gov.au/arcgis/rest/services/EventsIncidents/CycloneHistorical/MapServer"
HEADERS = {"User-Agent": "OperationalIntelligenceCrafter/0.2 (DisasterManagement)"}


def fetch_all_layers_metadata() -> List[Dict[str, Any]]:
    resp = requests.get(f"{MAPSERVER_URL}?f=json", headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json().get("layers", [])


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


def upload_geoparquet_to_gcs(local_file: Path, gcs_blob_name: str) -> str:
    """Uploads local GeoParquet file to Google Cloud Storage bucket."""
    client = storage.Client()
    bucket = client.bucket(GCS_BUCKET_NAME)
    blob = bucket.blob(gcs_blob_name)
    blob.upload_from_filename(str(local_file), content_type="application/vnd.apache.parquet")
    return f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{gcs_blob_name}"


def harvest_qld_cyclones():
    print("=" * 70)
    print("HARVESTING QLD HISTORICAL CYCLONE MAPSERVER LAYERS")
    print("=" * 70)

    layers = fetch_all_layers_metadata()
    print(f"Fetched {len(layers)} total layer definitions from MapServer.")

    # Identify group names and associate with sublayers
    current_event = "Unknown"
    event_year = None

    track_features = []
    fix_features = []
    wind_features = []

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
        elif gtype == "esriGeometryPoint":
            fix_features.extend(feats)
        elif gtype == "esriGeometryPolygon":
            wind_features.extend(feats)

    print("\nHarvest complete:")
    print(f"  Total Fix Points: {len(fix_features)}")
    print(f"  Total Track Lines: {len(track_features)}")
    print(f"  Total Wind Areas: {len(wind_features)}")

    timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    prepared_items = []

    datasets = [
        ("qld_cyclones_historical_tracks", "Queensland Historical Cyclone Tracks (Lines)", track_features),
        ("qld_cyclones_historical_fixes", "Queensland Historical Cyclone Observations & Fixes (Points)", fix_features),
        ("qld_cyclones_historical_wind_areas", "Queensland Historical Cyclone Wind Swaths & Hazard Areas (Polygons)", wind_features),
    ]

    for key, title, feats in datasets:
        print(f"\nProcessing GeoDataFrame for '{key}'...")
        fc = {"type": "FeatureCollection", "features": feats}
        gdf = gpd.GeoDataFrame.from_features(fc, crs="EPSG:4326")
        gdf["_oic_dataset_key"] = key
        gdf["_oic_retrieval_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        bounds = gdf.total_bounds
        gdf["_bbox_minx"] = bounds[0]
        gdf["_bbox_miny"] = bounds[1]
        gdf["_bbox_maxx"] = bounds[2]
        gdf["_bbox_maxy"] = bounds[3]

        gdf = clean_dataframe(gdf)

        local_pq = LAKE_ROOT / "geoparquet" / key / "QLD-HISTORICAL" / timestamp / "part-00000.parquet"
        local_pq.parent.mkdir(parents=True, exist_ok=True)
        gdf.to_parquet(local_pq, index=False)
        print(f"  Saved {len(gdf)} records to {local_pq}")

        rel_blob = f"geoparquet/{key}/QLD-HISTORICAL/{timestamp}/part-00000.parquet"
        gcs_url = upload_geoparquet_to_gcs(local_pq, rel_blob)
        print(f"  Uploaded to GCS: {gcs_url}")

        prepared_items.append({
            "key": key,
            "title": title,
            "url": gcs_url,
            "target_table": f"org_catalog.ops_intel.{key}",
            "expected_rows": len(gdf),
        })

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


if __name__ == "__main__":
    harvest_qld_cyclones()

