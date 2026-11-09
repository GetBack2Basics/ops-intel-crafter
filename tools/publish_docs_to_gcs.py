"""Upload updated web application assets to gs://operational-intelligence-crafter-lake."""

import os
from pathlib import Path
from google.cloud import storage

BUCKET_NAME = os.environ.get("OIC_GCS_BUCKET", "operational-intelligence-crafter-lake")
PROJECT_ID = os.environ.get("OIC_GCP_PROJECT", "ops-intelligence-crafter")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = PROJECT_ROOT / "docs"

def upload_web_assets():
    client = storage.Client(project=PROJECT_ID)
    bucket = client.bucket(BUCKET_NAME)

    files_to_upload = [
        ("app.js", "application/javascript; charset=utf-8"),
        ("layers.js", "application/javascript; charset=utf-8"),
        ("index.html", "text/html; charset=utf-8"),
        ("style.css", "text/css; charset=utf-8"),
        ("data/WP302026_TRACK_latest.kmz", "application/vnd.google-earth.kmz"),
        ("data/WP302026_TRACK_latest.geojson", "application/geo+json; charset=utf-8"),
        ("data/WP302026_CYCLONE_ZONES.geojson", "application/geo+json; charset=utf-8"),
    ]

    for rel_path, content_type in files_to_upload:
        file_path = DOCS_DIR / rel_path
        if not file_path.exists():
            print(f"Warning: {file_path} does not exist.")
            continue
        
        blob = bucket.blob(rel_path)
        # Prevent aggressive CDN caching so changes are immediately visible
        blob.cache_control = "no-cache, max-age=0"
        blob.upload_from_filename(str(file_path), content_type=content_type)
        print(f"[UPLOADED] gs://{BUCKET_NAME}/{rel_path} ({file_path.stat().st_size:,} bytes)")

    print(f"\nLive URL: https://storage.googleapis.com/{BUCKET_NAME}/index.html")

if __name__ == "__main__":
    upload_web_assets()

