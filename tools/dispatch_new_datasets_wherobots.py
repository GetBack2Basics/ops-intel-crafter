"""One-off, zero-mock Wherobots dispatch for the four newly harvested datasets.

Reads the canonical dataset records from GCS (feature counts + snapshot URIs),
builds the remote-ingest manifest, dispatches the tiny Wherobots job, verifies
row counts via the DB-API, and audits teardown.
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ingestion.gcs_storage import GCSLakeStorage
from tools.harvest_portal_dataset import dispatch_wherobots, load_config

KEYS = [
    "flood_awareness_storm_tide",
    "qld_cyclones_historical_tracks",
    "qld_cyclones_historical_fixes",
    "qld_cyclones_historical_wind_areas",
]


def main() -> int:
    cfg = load_config(PROJECT_ROOT / "config" / "harvester_config.json")
    store = GCSLakeStorage()
    catalog = cfg["wherobots"].get("catalog", "org_catalog")
    database = cfg["wherobots"].get("database", "ops_intel")
    db_name = f"{catalog}.{database}"

    items = []
    for key in KEYS:
        record = store.read_json_cloud(store.dataset_manifest_object_key(key))
        if not record:
            raise SystemExit(f"Missing canonical GCS dataset record for '{key}'")
        gs_uri = record["gs_uri"]
        items.append({
            "key": key,
            "title": record["title"],
            "url": gs_uri.replace("gs://", "https://storage.googleapis.com/"),
            "database": db_name,
            "target_table": f"{db_name}.{key}",
            "expected_rows": int(record["feature_count"]),
        })

    print("Dispatch manifest (derived from GCS records):")
    print(json.dumps(items, indent=2))
    dispatch_wherobots(items, cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
