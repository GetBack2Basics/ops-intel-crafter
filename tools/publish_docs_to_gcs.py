"""Upload updated web application assets to gs://operational-intelligence-crafter-lake."""

import os
from pathlib import Path
import dotenv
from google.cloud import storage

PROJECT_ROOT = Path(__file__).resolve().parent.parent
dotenv.load_dotenv(PROJECT_ROOT / ".env")

BUCKET_NAME = os.environ.get("OIC_GCS_BUCKET", "operational-intelligence-crafter-lake")
PROJECT_ID = os.environ.get("OIC_GCP_PROJECT", "operational-intelligence-crafter")

DOCS_DIR = PROJECT_ROOT / "docs"

def upload_web_assets():
    client = storage.Client(project=PROJECT_ID)
    bucket = client.bucket(BUCKET_NAME)

    files_to_upload = [
        ("app.js", "application/javascript; charset=utf-8"),
        ("duckdb_wasm.js", "application/javascript; charset=utf-8"),
        ("layers.js", "application/javascript; charset=utf-8"),
        ("geolibre_catalog_engine.js", "application/javascript; charset=utf-8"),
        ("index.html", "text/html; charset=utf-8"),
        ("style.css", "text/css; charset=utf-8"),
        ("operational-intelligence-crafter.geolibre.json", "application/json; charset=utf-8"),
        ("operational-intelligence-crafter.gcs.geolibre.json", "application/json; charset=utf-8"),
        ("js/geolibre-qa-layer-registry.js", "application/javascript; charset=utf-8"),
        ("qa/js/geolibre-qa-layer-registry.js", "application/javascript; charset=utf-8"),
        ("qa/index.html", "text/html; charset=utf-8"),
        ("qa/inspect.html", "text/html; charset=utf-8"),
        ("qa/geolibre_qa_inspect.html", "text/html; charset=utf-8"),
        ("geolibre_qa_inspect.html", "text/html; charset=utf-8"),
        ("data/WP302026_TRACK_latest.kmz", "application/vnd.google-earth.kmz"),
        ("data/WP302026_TRACK_latest.geojson", "application/geo+json; charset=utf-8"),
        ("data/WP302026_CYCLONE_ZONES.geojson", "application/geo+json; charset=utf-8"),
        ("data/workbench_bundle.json", "application/json; charset=utf-8"),
        ("data/locality_gazetteer.json", "application/json; charset=utf-8"),
    ]

    # qa/data artifacts (GeoJSON previews + parquet samples) are published directly by
    # the cloud-first ingestion/harvest pipelines. Local docs/qa/data mirrors are stale by
    # design, so they must never overwrite the canonical GCS copies here.

    # Also include js directory (geolibre limiter & registry)
    js_dir = DOCS_DIR / "js"
    if js_dir.exists():
        for p in sorted(js_dir.rglob("*")):
            if p.is_file():
                rel = p.relative_to(DOCS_DIR).as_posix()
                ct = "application/javascript; charset=utf-8" if p.suffix == ".js" else "text/plain"
                files_to_upload.append((rel, ct))

    # Also include exports files (parquet, geojson, json)
    exports_dir = DOCS_DIR / "exports"
    if exports_dir.exists():
        for p in sorted(exports_dir.rglob("*")):
            if p.is_file():
                rel = p.relative_to(DOCS_DIR).as_posix()
                ct = "application/octet-stream" if p.suffix == ".parquet" else "application/geo+json; charset=utf-8" if p.suffix == ".geojson" else "application/json; charset=utf-8"
                files_to_upload.append((rel, ct))

    # Also include map_packages
    map_packages_dir = DOCS_DIR / "map_packages"
    if map_packages_dir.exists():
        for p in sorted(map_packages_dir.rglob("*")):
            if p.is_file():
                rel = p.relative_to(DOCS_DIR).as_posix()
                ct = "text/html; charset=utf-8" if p.suffix == ".html" else "application/json" if p.suffix == ".json" else "text/css" if p.suffix == ".css" else "application/javascript" if p.suffix == ".js" else "text/plain"
                files_to_upload.append((rel, ct))

    FORCE_UPLOAD = {
        "app.js", "duckdb_wasm.js", "layers.js", "geolibre_catalog_engine.js",
        "index.html", "style.css", "qa/index.html", "qa/inspect.html",
        "qa/geolibre_qa_inspect.html", "geolibre_qa_inspect.html",
        "operational-intelligence-crafter.geolibre.json", "js/geolibre-qa-layer-registry.js", "qa/js/geolibre-qa-layer-registry.js"
    }

    # Cleanup obsolete files from bucket
    obsolete_blobs = ["aura-siting-crafter.geolibre.json"]
    for obs in obsolete_blobs:
        obs_blob = bucket.blob(obs)
        if obs_blob.exists():
            obs_blob.delete()
            print(f"[CLEANUP] Deleted obsolete gs://{BUCKET_NAME}/{obs}")

    for rel_path, content_type in files_to_upload:
        file_path = DOCS_DIR / rel_path
        if not file_path.exists():
            print(f"Warning: {file_path} does not exist.")
            continue
        
        blob = bucket.blob(rel_path)
        if rel_path not in FORCE_UPLOAD:
            try:
                blob.reload()
                if blob.size == file_path.stat().st_size:
                    # Unchanged, skip upload
                    continue
            except Exception:
                pass

        # Prevent aggressive CDN caching so changes are immediately visible
        blob.cache_control = "no-cache, max-age=0"
        blob.upload_from_filename(str(file_path), content_type=content_type)
        print(f"[UPLOADED] gs://{BUCKET_NAME}/{rel_path} ({file_path.stat().st_size:,} bytes)")

    print(f"\nLive URL: https://storage.googleapis.com/{BUCKET_NAME}/index.html")

if __name__ == "__main__":
    upload_web_assets()

