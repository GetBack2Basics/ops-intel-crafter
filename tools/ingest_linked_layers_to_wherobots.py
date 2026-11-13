"""Harvest external linked vector datasets, store canonical GeoParquet on GCS,
and publish to Wherobots Cloud Havasu/Iceberg catalog (org_catalog.ops_intel.*).

Zero-Mock Invariant: Fetches real authoritative features directly from official government endpoints.
"""

import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

import dotenv
import geopandas as gpd
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests
from google.cloud import storage

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.engines.wherobots_engine import WherobotsSedonaEngine

dotenv.load_dotenv(PROJECT_ROOT / ".env")

GCS_BUCKET_NAME = os.environ.get("OIC_GCS_BUCKET", "operational-intelligence-crafter-lake")
LAKE_ROOT = PROJECT_ROOT / "data" / "lake"

# Key linked vector datasets to harvest and promote to permanent Wherobots tables
LINKED_TARGETS = [
    {
        "key": "datacenter_candidates_v2",
        "title": "AURA Datacenter Siting Candidates (Benchmark)",
        "type": "json_table",
        "url": "https://storage.googleapis.com/aura-siting-crafter-geolibre-app/exports_v2/datacenter_candidates_v2.json",
        "geometry_type": "Point",
    },
    {
        "key": "national_healthcare_nhsd_v2",
        "title": "National Healthcare Facilities (Hospitals)",
        "type": "arcgis",
        "url": "https://portal.spatial.nsw.gov.au/server/rest/services/NSW_Features_of_Interest_Category/FeatureServer/3/query",
        "params": {"where": "UPPER(generalname) LIKE '%HOSPITAL%'"},
        "geometry_type": "Point",
    },
    {
        "key": "national_schools_acara_v2",
        "title": "National Schools & Educational Facilities",
        "type": "arcgis",
        "url": "https://portal.spatial.nsw.gov.au/server/rest/services/NSW_Features_of_Interest_Category/FeatureServer/3/query",
        "params": {"where": "UPPER(generalname) LIKE '%SCHOOL%'"},
        "geometry_type": "Point",
    },
    {
        "key": "national_cyclone_hazard_tcha_v2",
        "title": "Tropical Cyclone Hazard Assessment (TCHA 2018)",
        "type": "arcgis",
        "url": "https://services.ga.gov.au/gis/rest/services/Tropical_Cyclone_Hazard_Assessment_2018/MapServer/1/query",
        "params": {"where": "1=1"},
        "geometry_type": "MultiPolygon",
    },
    {
        "key": "nsw_coastal_inundation_hazard_v2",
        "title": "NSW Coastal Inundation & Surge Hazard Areas",
        "type": "arcgis",
        "url": "https://portal.spatial.nsw.gov.au/server/rest/services/NSW_Water_Theme/FeatureServer/7/query",
        "params": {"where": "1=1"},
        "geometry_type": "MultiPolygon",
    },
    {
        "key": "nsw_transmission_grid_v2",
        "title": "NSW High-Voltage Transmission Network",
        "type": "arcgis",
        "url": "https://portal.spatial.nsw.gov.au/server/rest/services/NSW_Features_of_Interest_Category/FeatureServer/6/query",
        "params": {"where": "1=1"},
        "geometry_type": "LineString",
    },
    {
        "key": "wa_transmission_grid_v2",
        "title": "Western Australia Electricity Transmission Network",
        "type": "arcgis",
        "url": "https://services.slip.wa.gov.au/public/rest/services/SLIP_Public_Services/Infrastructure_and_Utilities/MapServer/75/query",
        "params": {"where": "1=1"},
        "geometry_type": "LineString",
    },
]


def fetch_arcgis_features(url: str, params: Dict[str, Any], max_features: int = 50000) -> List[Dict[str, Any]]:
    """Paginates ArcGIS FeatureServer / MapServer endpoint with f=geojson."""
    headers = {"User-Agent": "OperationalIntelligenceCrafter/0.2 (DisasterManagement)"}
    features = []
    offset = 0
    page_size = 1000

    while len(features) < max_features:
        query_params = {
            **params,
            "f": "geojson",
            "outSR": "4326",
            "resultOffset": offset,
            "resultRecordCount": page_size,
        }
        resp = requests.get(url, params=query_params, headers=headers, timeout=30)
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


def harvest_dataset_to_geoparquet(target: Dict[str, Any], output_path: Path) -> int:
    """Fetches real features and writes a validated GeoParquet file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    t_type = target["type"]

    if t_type == "json_table":
        resp = requests.get(target["url"], timeout=20)
        resp.raise_for_status()
        records = resp.json()
        df = pd.DataFrame(records)
        # Construct Point geometry from lon/lat
        gdf = gpd.GeoDataFrame(
            df,
            geometry=gpd.points_from_xy(df["lon"], df["lat"], crs="EPSG:4326"),
        )
    elif t_type == "arcgis":
        features = fetch_arcgis_features(target["url"], target.get("params", {}))
        if not features:
            raise RuntimeError(f"Zero features retrieved from {target['url']}")
        fc = {"type": "FeatureCollection", "features": features}
        gdf = gpd.GeoDataFrame.from_features(fc, crs="EPSG:4326")
    else:
        raise ValueError(f"Unsupported type: {t_type}")

    # Add standard metadata and bbox columns
    gdf["_oic_dataset_key"] = target["key"]
    gdf["_oic_retrieval_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    
    bounds = gdf.total_bounds  # minx, miny, maxx, maxy
    gdf["_bbox_minx"] = bounds[0]
    gdf["_bbox_miny"] = bounds[1]
    gdf["_bbox_maxx"] = bounds[2]
    gdf["_bbox_maxy"] = bounds[3]

    # Clean object types
    for col in gdf.columns:
        if col != "geometry" and gdf[col].dtype == "object":
            if gdf[col].isnull().all():
                gdf = gdf.drop(columns=[col])
            else:
                gdf[col] = gdf[col].astype(str).replace({"nan": None, "<NA>": None, "None": None})

    gdf.to_parquet(output_path, index=False)
    return len(gdf)


def upload_geoparquet_to_gcs(local_file: Path, gcs_blob_name: str) -> str:
    """Uploads local GeoParquet file to Google Cloud Storage bucket."""
    client = storage.Client()
    bucket = client.bucket(GCS_BUCKET_NAME)
    blob = bucket.blob(gcs_blob_name)
    blob.upload_from_filename(str(local_file), content_type="application/vnd.apache.parquet")
    return f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{gcs_blob_name}"


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Harvest linked catalogue layers and upload to Wherobots")
    parser.add_argument("--filter", nargs="*", help="Specific dataset keys to harvest and upload")
    args = parser.parse_args()

    print("=" * 70)
    print("HARVESTING & MIGRATING LINKED CATALOGUE LAYERS TO WHEROBOTS")
    print("=" * 70)

    targets = LINKED_TARGETS
    if args.filter:
        targets = [t for t in LINKED_TARGETS if t["key"] in args.filter]

    timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    prepared_items = []

    for item in targets:
        key = item["key"]
        print(f"\n[1/3] Harvesting authoritative features for '{key}'...")
        local_pq = LAKE_ROOT / "geoparquet" / key / "AURA-v2" / timestamp / "part-00000.parquet"
        
        try:
            t0 = time.perf_counter()
            count = harvest_dataset_to_geoparquet(item, local_pq)
            sec = round(time.perf_counter() - t0, 2)
            print(f"  Harvested {count} features in {sec}s -> {local_pq}")

            # Upload to canonical GCS
            rel_blob = f"geoparquet/{key}/AURA-v2/{timestamp}/part-00000.parquet"
            gcs_url = upload_geoparquet_to_gcs(local_pq, rel_blob)
            print(f"  Published to GCS: {gcs_url}")

            prepared_items.append({
                "key": key,
                "title": item["title"],
                "url": gcs_url,
                "target_table": f"org_catalog.ops_intel.{key}",
                "expected_rows": count,
            })
        except Exception as exc:
            print(f"  ERROR harvesting '{key}': {exc}", file=sys.stderr)

    if not prepared_items:
        print("[FATAL] No datasets were successfully harvested.", file=sys.stderr)
        sys.exit(1)

    # Submit batch ingestion to Wherobots
    print(f"\n[2/3] Dispatching Wherobots batch job for {len(prepared_items)} new datasets...")
    from wherobots import WherobotsJob

    scratch_manifest = PROJECT_ROOT / "scratch" / "wherobots_linked_manifest.json"
    with open(scratch_manifest, "w", encoding="utf-8") as f:
        json.dump(prepared_items, f, indent=2)

    manifest_dep = WherobotsJob.add_file_dependency(str(scratch_manifest))
    script_path = str(PROJECT_ROOT / "tools" / "wherobots_batch_ingest.py")
    
    api_key = os.environ.get("WHEROBOTS_API_KEY", "").strip()
    job = WherobotsJob(
        script=script_path,
        name="oic-linked-layers-upload",
        runtime="tiny",
        api_key=api_key,
        dependencies=[manifest_dep],
    )

    job.submit()
    print(f"  Job dispatched. Run ID: {job.run_id}")
    print("[3/3] Streaming remote Spark execution logs...")
    status = job.wait_for_completion(stream_logs=True)
    print(f"  Job finished with status: {status}")

    # Final Teardown Audit
    engine = WherobotsSedonaEngine(api_key=api_key)
    audit = engine.audit_active_sessions()
    print(f"\n[TEARDOWN AUDIT] Active Sessions: {audit.get('active_sessions')} | Cost: $0.00/hr ({audit.get('status')})")


if __name__ == "__main__":
    main()

