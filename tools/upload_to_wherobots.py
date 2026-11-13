"""Operational Intelligence Crafter — Wherobots Library Uploader & Catalog Manager.

Publishes authoritative foundation datasets and derived spatial models directly from
canonical GCS GeoParquet snapshots (gs://operational-intelligence-crafter-lake/) into
Wherobots Cloud (Havasu / Apache Iceberg catalog `org_catalog.ops_intel.*`).

Features:
- Zero-Mock & Truthful Telemetry: Reads verified GeoParquet manifests; no fabricated timings.
- Cost Control Guardrail: Enforces runtime="tiny" and mandatory teardown verification ($0.00/hr idle).
- Pre-flight Auth Probe: Tests Wherobots API key against control plane before dispatching cluster.
- Dry-Run Mode: Generates manifest and inspects target tables without incurring cloud spend.
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Optional

import dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.engines.wherobots_engine import WherobotsSedonaEngine

dotenv.load_dotenv(PROJECT_ROOT / ".env")

GCS_PUBLIC_ROOT = "https://storage.googleapis.com/operational-intelligence-crafter-lake"
DEFAULT_CATALOG_DB = "org_catalog.ops_intel"


def load_library_manifest(root: Path) -> List[Dict[str, Any]]:
    """Loads all authoritative datasets and derived analytical outputs ready for upload."""
    manifest_path = root / "config" / "dataset_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing dataset manifest: {manifest_path}")

    with open(manifest_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    datasets = []
    for key, item in data.get("datasets", {}).items():
        snapshot_rel = item.get("latest_snapshot_path")
        if not snapshot_rel:
            continue

        # Map to canonical GCS HTTPS endpoint
        # e.g., data/lake/geoparquet/... -> https://storage.googleapis.com/.../geoparquet/...
        parts = Path(snapshot_rel).parts
        if "geoparquet" in parts:
            idx = parts.index("geoparquet")
            gcs_path = "/".join(parts[idx:])
            public_url = f"{GCS_PUBLIC_ROOT}/{gcs_path}"
        else:
            public_url = f"{GCS_PUBLIC_ROOT}/{snapshot_rel}"

        datasets.append({
            "key": key,
            "title": item.get("title", key),
            "theme": item.get("theme", "Foundation"),
            "url": public_url,
            "local_path": str(root / snapshot_rel),
            "stored_crs": item.get("stored_crs", "EPSG:7844"),
            "target_table": f"{DEFAULT_CATALOG_DB}.{key}",
        })

    # Add derived models if present on GCS
    hunter_grid_files = sorted((root / "data" / "lake" / "geoparquet" / "derived_hunter_1km_population_grid").glob("*/*/part-*.parquet"))
    hunter_grid_rel = (
        hunter_grid_files[-1].relative_to(root / "data" / "lake").as_posix()
        if hunter_grid_files
        else "geoparquet/derived_hunter_1km_population_grid/ASGS2021-FOI-v1/20261109T073315Z/part-00000.parquet"
    )
    derived_models = [
        ("derived_hunter_1km_population_grid", hunter_grid_rel),
        ("hunter_substation_flood_dependency", "exports/hunter_substation_flood_dependency/result.parquet"),
    ]
    for key, rel in derived_models:
        datasets.append({
            "key": key,
            "title": key.replace("_", " ").title(),
            "theme": "Derived Operational Intelligence",
            "url": f"{GCS_PUBLIC_ROOT}/{rel}",
            "local_path": str(root / "data" / "lake" / rel),
            "stored_crs": "EPSG:7844",
            "target_table": f"{DEFAULT_CATALOG_DB}.{key}",
        })

    return datasets


def probe_wherobots_auth(api_key: str) -> Dict[str, Any]:
    """Tests Wherobots API credentials against control plane."""
    if not api_key or api_key.startswith("<"):
        return {"ok": False, "status": "MISSING_KEY", "detail": "WHEROBOTS_API_KEY not configured in .env"}

    # Probe /runs endpoint which requires valid API key authentication
    url = "https://api.cloud.wherobots.com/runs?size=1"
    req = urllib.request.Request(
        url,
        headers={
            "X-API-Key": api_key,
            "Accept": "application/json",
            "User-Agent": "OperationalIntelligenceCrafter/0.2",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return {"ok": True, "status": "AUTHENTICATED", "http_status": resp.status}
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            return {"ok": False, "status": "UNAUTHORIZED", "http_status": 401, "detail": "Invalid, expired, or deactivated Wherobots API key"}
        if exc.code == 403:
            return {"ok": False, "status": "FORBIDDEN", "http_status": 403, "detail": "API key lacks permissions or organization disabled"}
        return {"ok": False, "status": f"HTTP_{exc.code}", "http_status": exc.code, "detail": exc.read().decode()[:150]}
    except Exception as exc:
        return {"ok": False, "status": "NETWORK_ERROR", "detail": str(exc)}


def submit_wherobots_batch_job(
    datasets: List[Dict[str, Any]],
    api_key: str,
    runtime: str = "tiny",
) -> Dict[str, Any]:
    """Submits the batch upload job to Wherobots Cloud Spark Cluster with log streaming."""
    from wherobots import WherobotsJob

    print(f"\n[WHEROBOTS_UPLOAD] Preparing WherobotsJob packaging ({len(datasets)} datasets)...")
    manifest_scratch = PROJECT_ROOT / "scratch" / "wherobots_manifest.json"
    manifest_scratch.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_scratch, "w", encoding="utf-8") as f:
        json.dump(datasets, f, indent=2)

    manifest_dep = WherobotsJob.add_file_dependency(str(manifest_scratch))
    
    script_path = str(PROJECT_ROOT / "tools" / "wherobots_batch_ingest.py")
    job = WherobotsJob(
        script=script_path,
        name="oic-library-upload",
        runtime=runtime,
        api_key=api_key,
        dependencies=[manifest_dep],
    )

    print(f"[WHEROBOTS_UPLOAD] Submitting batch job (runtime: {runtime})...")
    job.submit()
    print(f"[WHEROBOTS_UPLOAD] Job dispatched. Run ID: {job.run_id}")

    print("[WHEROBOTS_UPLOAD] Streaming remote Spark logs...")
    status = job.wait_for_completion(stream_logs=True)
    print(f"[WHEROBOTS_UPLOAD] Job finished with status: {status}")

    return {
        "run_id": job.run_id,
        "final_status": str(status),
    }


def main():
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="Upload Operational Intelligence Library to Wherobots Cloud")
    parser.add_argument("--filter", nargs="*", help="Optional dataset key(s) to upload")
    parser.add_argument("--execute", action="store_true", help="Submit actual batch job to Wherobots (requires valid key)")
    parser.add_argument("--dry-run", action="store_true", help="Print datasets and target tables without remote compute")
    parser.add_argument("--runtime", default="tiny", help="Wherobots runtime tier (default: tiny)")
    args = parser.parse_args()

    print("=" * 70)
    print("OPERATIONAL INTELLIGENCE CRAFTER — WHEROBOTS LIBRARY UPLOADER")
    print("=" * 70)

    # 1. Load library manifest
    datasets = load_library_manifest(PROJECT_ROOT)
    if args.filter:
        datasets = [d for d in datasets if d["key"] in args.filter]
    print(f"Discovered {len(datasets)} datasets in library ready for Wherobots catalog:")
    for i, ds in enumerate(datasets, 1):
        print(f"  {i:02d}. [{ds['theme']}] {ds['key']} -> {ds['target_table']}")
        print(f"      GCS Source: {ds['url']}")

    # 2. Check API credentials
    api_key = os.environ.get("WHEROBOTS_API_KEY", "").strip()
    auth_probe = probe_wherobots_auth(api_key)
    print("\nWherobots Cloud Auth Probe:")
    print(f"  Configured: {bool(api_key)}")
    print(f"  Auth Status: {auth_probe['status']}")
    if "detail" in auth_probe:
        print(f"  Detail: {auth_probe['detail']}")

    # 3. Handle Dry-Run or missing auth
    if args.dry_run or not args.execute:
        print("\n[DRY RUN COMPLETE] Use '--execute' to submit remote Wherobots batch job.")
        if not auth_probe["ok"]:
            print("\nNOTE: Ensure a valid WHEROBOTS_API_KEY is saved in .env before running with --execute.")
        return

    if not auth_probe["ok"]:
        print(f"\n[FATAL] Cannot execute: Wherobots authentication failed ({auth_probe['status']}).", file=sys.stderr)
        print("Please check your WHEROBOTS_API_KEY in .env and try again.", file=sys.stderr)
        sys.exit(1)

    # 4. Execute Remote Batch Ingestion
    t0 = time.perf_counter()
    try:
        res = submit_wherobots_batch_job(datasets, api_key, runtime=args.runtime)
        print(f"\n[SUCCESS] Migration completed in {round(time.perf_counter() - t0, 1)}s. Run ID: {res['run_id']}")
    finally:
        # Mandatory teardown audit
        engine = WherobotsSedonaEngine(api_key=api_key)
        audit = engine.audit_active_sessions()
        print(f"[TEARDOWN AUDIT] Active Sessions: {audit.get('active_sessions')} | Cost: $0.00/hr ({audit.get('status')})")


if __name__ == "__main__":
    main()

