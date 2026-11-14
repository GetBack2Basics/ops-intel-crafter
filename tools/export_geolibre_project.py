"""Export a GeoLibre project file wired directly to GeoParquet layers on GCS.

Implements the approved plan (geolibre_gcs_export_plan.md):
  * Discovers the latest `geoparquet/<key>/<vintage>/<timestamp>/part-*.parquet`
    partition for every dataset actually present in the bucket (no invented paths).
  * Reads real row counts from each Parquet footer over public HTTPS (DuckDB httpfs),
    which doubles as the Phase 3 "read_parquet(url) works" verification.
  * Auth modes:
      public  -> plain https://storage.googleapis.com URLs (bucket is public-read).
                 Output: docs/operational-intelligence-crafter.gcs.geolibre.json (git-safe;`n                 the app's docs/operational-intelligence-crafter.geolibre.json is untouched).
      signed  -> V4 signed URLs (1-7 days). Requires a signing-capable credential
                 (service-account key or impersonation). Fails loudly otherwise.
      hmac    -> embeds OIC_GCS_HMAC_KEY_ID / OIC_GCS_HMAC_SECRET from .env.
                 Fails loudly if absent.
    signed / hmac output goes to exports/geolibre/ (git-ignored).

Usage:
  python tools/export_geolibre_project.py --auth public
  python tools/export_geolibre_project.py --auth signed --expiry-days 7
  python tools/export_geolibre_project.py --auth hmac
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from typing import Any, Dict

import dotenv
import duckdb
from google.cloud import storage

PROJECT_ROOT = Path(__file__).resolve().parent.parent
dotenv.load_dotenv(PROJECT_ROOT / ".env")
BUCKET = os.environ.get("OIC_GCS_BUCKET", "operational-intelligence-crafter-lake")
PROJECT = os.environ.get("OIC_GCP_PROJECT", "operational-intelligence-crafter")
HTTPS_BASE = f"https://storage.googleapis.com/{BUCKET}"
PUBLIC_OUT = PROJECT_ROOT / "docs" / "operational-intelligence-crafter.gcs.geolibre.json"
PRIVATE_DIR = PROJECT_ROOT / "exports" / "geolibre"
QA_SUMMARY = PROJECT_ROOT / "docs" / "qa" / "data" / "qa_summary.json"

LAYER_GROUPS = [
    {"id": "grp_emergency", "name": "ðŸš¨ Emergency Operations & Active Incidents", "visible": True},
    {"id": "grp_population", "name": "ðŸ‘¥ ABS Population Grid (Methods A/B/C)", "visible": True},
    {"id": "grp_infrastructure", "name": "âš¡ Energy & Critical Infrastructure", "visible": True},
    {"id": "grp_hazards", "name": "ðŸŒŠ Flood, Cyclone & Seismic Hazards", "visible": True},
    {"id": "grp_receptors", "name": "ðŸ¥ Health, Schools & Sensitive Receptors", "visible": True},
    {"id": "grp_boundaries", "name": "ðŸ—ºï¸ Statistical & Administrative Boundaries", "visible": False},
]

# key-substring -> (group, style). First match wins.
STYLE_RULES = [
    ("cyclones_historical_tracks", "grp_emergency", {"strokeColor": "#f43f5e", "strokeWidth": 2.5}),
    ("cyclones_historical_fixes", "grp_emergency", {"circleRadius": 5, "fillColor": "#ea580c", "strokeColor": "#ffffff", "strokeWidth": 1}),
    ("cyclones_historical_wind", "grp_hazards", {"fillColor": "#f59e0b", "fillOpacity": 0.28, "strokeColor": "#ea580c", "strokeWidth": 1}),
    ("rfs_major_incidents", "grp_emergency", {"circleRadius": 7, "fillColor": "#dc2626", "strokeColor": "#ffffff", "strokeWidth": 1.5}),
    ("population", "grp_population", {"circleRadius": 3, "fillColor": "#006973", "strokeColor": "#004f57", "strokeWidth": 0.5}),
    ("substation", "grp_infrastructure", {"circleRadius": 5, "fillColor": "#facc15", "strokeColor": "#111827", "strokeWidth": 1}),
    ("power_stations", "grp_infrastructure", {"circleRadius": 6, "fillColor": "#a855f7", "strokeColor": "#ffffff", "strokeWidth": 1}),
    ("transmission", "grp_infrastructure", {"strokeColor": "#f97316", "strokeWidth": 1.6}),
    ("datacenter", "grp_infrastructure", {"circleRadius": 6, "fillColor": "#22d3ee", "strokeColor": "#ffffff", "strokeWidth": 1}),
    ("inundation", "grp_hazards", {"fillColor": "#3b82f6", "fillOpacity": 0.35, "strokeColor": "#1d4ed8", "strokeWidth": 0.8}),
    ("cyclone_hazard", "grp_hazards", {"fillColor": "#fb7185", "fillOpacity": 0.25, "strokeColor": "#e11d48", "strokeWidth": 0.8}),
    ("seismic", "grp_hazards", {"strokeColor": "#8b5cf6", "strokeWidth": 1.2}),
    ("foi", "grp_receptors", {"fillColor": "#10b981", "fillOpacity": 0.4, "strokeColor": "#047857", "strokeWidth": 0.6}),
    ("healthcare", "grp_receptors", {"circleRadius": 5, "fillColor": "#ef4444", "strokeColor": "#ffffff", "strokeWidth": 1}),
    ("schools", "grp_receptors", {"circleRadius": 4, "fillColor": "#0ea5e9", "strokeColor": "#ffffff", "strokeWidth": 1}),
    ("boundaries", "grp_boundaries", {"fillColor": "#94a3b8", "fillOpacity": 0.05, "strokeColor": "#475569", "strokeWidth": 0.8}),
]


def classify(key: str):
    for needle, group, style in STYLE_RULES:
        if needle in key:
            return group, style
    return "grp_hazards", {"strokeColor": "#64748b", "strokeWidth": 1}


def discover_latest(client: storage.Client) -> dict[str, dict]:
    """Latest part-*.parquet per dataset key (lexicographic max of timestamp path)."""
    latest: dict[str, dict] = {}
    for blob in client.list_blobs(client.bucket(BUCKET), prefix="geoparquet/"):
        if not blob.name.endswith(".parquet"):
            continue
        parts = blob.name.split("/")
        if len(parts) < 3:
            continue
        key = parts[1]
        if key not in latest or blob.name > latest[key]["name"]:
            latest[key] = {"name": blob.name, "size": blob.size, "updated": blob.updated.isoformat()}
    return latest


def parquet_row_count(con: duckdb.DuckDBPyConnection, url: str) -> int:
    return con.execute("SELECT count(*) FROM read_parquet(?)", [url]).fetchone()[0]


def sign_url(client: storage.Client, object_name: str, days: int) -> str:
    blob = client.bucket(BUCKET).blob(object_name)
    return blob.generate_signed_url(version="v4", expiration=timedelta(days=days), method="GET")


def load_qa_summary(client: storage.Client) -> Dict[str, Dict[str, Any]]:
    """Loads the canonical QA summary from GCS, falling back to the local docs mirror."""
    try:
        blob = client.bucket(BUCKET).blob("qa/data/qa_summary.json")
        if blob.exists(client):
            payload = json.loads(blob.download_as_text())
            return {d["dataset_key"]: d for d in payload.get("datasets", [])}
    except Exception as exc:
        print(f"[WARN] Could not read qa/data/qa_summary.json from GCS ({exc.__class__.__name__}); using local mirror.")
    if QA_SUMMARY.exists():
        payload = json.loads(QA_SUMMARY.read_text(encoding="utf-8"))
        return {d["dataset_key"]: d for d in payload.get("datasets", [])}
    return {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--auth", choices=["public", "signed", "hmac"], default="public")
    ap.add_argument("--expiry-days", type=int, default=7)
    args = ap.parse_args()
    if not 1 <= args.expiry_days <= 7:
        sys.exit("V4 signed URLs are capped at 7 days by GCS; use --expiry-days 1..7.")

    hmac_id = hmac_secret = None
    if args.auth == "hmac":
        hmac_id = os.environ.get("OIC_GCS_HMAC_KEY_ID")
        hmac_secret = os.environ.get("OIC_GCS_HMAC_SECRET")
        if not (hmac_id and hmac_secret):
            sys.exit("BLOCKED: OIC_GCS_HMAC_KEY_ID / OIC_GCS_HMAC_SECRET not set in environment (.env). "
                     "No HMAC key was created; create one deliberately and re-run.")

    client = storage.Client(project=PROJECT)
    latest = discover_latest(client)
    if not latest:
        sys.exit(f"FAIL: no GeoParquet objects found under gs://{BUCKET}/geoparquet/")

    qa = load_qa_summary(client)

    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")

    layers, failures = [], []
    for key, info in sorted(latest.items()):
        https_url = f"{HTTPS_BASE}/{info['name']}"
        try:
            rows = parquet_row_count(con, https_url)
            read_status = "PASS"
        except Exception as exc:  # report, never substitute
            rows, read_status = None, f"FAIL: {exc.__class__.__name__}: {str(exc)[:160]}"
            failures.append(key)

        url = https_url
        if args.auth == "signed":
            try:
                url = sign_url(client, info["name"], args.expiry_days)
            except Exception as exc:
                sys.exit(f"BLOCKED: cannot sign URLs with current credentials ({exc.__class__.__name__}: {exc}). "
                         "Signing needs a service-account key or impersonation (roles/iam.serviceAccountTokenCreator). "
                         "Nothing was written.")

        group, style = classify(key)
        q = qa.get(key, {})
        layers.append({
            "id": key,
            "name": q.get("dataset_name") or q.get("title") or key.replace("_", " ").title(),
            "groupId": group,
            "type": "geoparquet",
            "visible": group != "grp_boundaries",
            "opacity": 0.9,
            "source": {
                "type": "geoparquet",
                "format": "parquet",
                "spatialEngine": "DuckDB-WASM",
                "gcsUri": f"gs://{BUCKET}/{info['name']}",
                "url": url,
            },
            "style": style,
            "metadata": {
                "source_agency": q.get("source_agency"),
                "features_stored": rows,
                "object_bytes": info["size"],
                "object_updated_utc": info["updated"],
                "qa_status": q.get("overall_qa_status") or q.get("overall_status"),
                "read_parquet_check": read_status,
                "crs": "EPSG:4326 / EPSG:7844",
            },
        })

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cloud = {"provider": "gcs", "endpoint": "https://storage.googleapis.com", "bucket": BUCKET, "authMode": args.auth}
    if args.auth == "signed":
        cloud["signedUrlExpiresUtc"] = (datetime.now(timezone.utc) + timedelta(days=args.expiry_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    if args.auth == "hmac":
        cloud["credentials"] = {"accessKeyId": hmac_id, "secretAccessKey": hmac_secret, "sessionToken": None}

    spec = {
        "version": "0.2.0",
        "name": "Operational Intelligence Crafter â€” National Emergency Spatial Workbench",
        "description": "Direct GCS GeoParquet project (byte-range reads via DuckDB-WASM / GeoLibre Desktop / QGIS).",
        "mapView": {"center": [133.7751, -25.2744], "zoom": 4.0, "bearing": 0, "pitch": 0, "bbox": [112.9, -43.7, 153.7, -10.0]},
        "basemapStyleUrl": "https://tiles.openfreemap.org/styles/liberty",
        "cloudStorage": cloud,
        "layerGroups": LAYER_GROUPS,
        "layers": layers,
        "metadata": {
            "generated_utc": generated,
            "generator": "tools/export_geolibre_project.py",
            "datasets_on_gcs": len(layers),
            "read_failures": failures,
            "zero_mock": True,
            "disclaimer": "Engineering proof of concept only. Not for operational emergency warning, dispatch, or life-safety decisions.",
        },
    }

    if args.auth == "public":
        out = PUBLIC_OUT
    else:
        PRIVATE_DIR.mkdir(parents=True, exist_ok=True)
        out = PRIVATE_DIR / f"operational-intelligence-crafter-{args.auth}.geolibre.json"
    out.write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")

    total = sum(l["metadata"]["features_stored"] or 0 for l in layers)
    print(f"[OK] {out} â€” {len(layers)} layers, {total:,} features, auth={args.auth}")
    for l in layers:
        print(f"  {l['metadata']['read_parquet_check']:<5} {l['id']:<40} {l['metadata']['features_stored']}")
    if failures:
        print(f"[WARNING] {len(failures)} layer(s) failed read_parquet: {failures}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

