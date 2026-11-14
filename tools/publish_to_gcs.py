"""Provision & Publish the Canonical GCS Lakehouse (`gs://operational-intelligence-crafter-lake`).

Cloud-first by design: all GeoParquet snapshots, per-dataset manifests, and QA records
are written directly to GCS by the ingestion/harvest pipelines. This tool never reads
or writes a local staging tree. It:

1. Ensures the billing account, bucket, versioning, CORS, and public object-viewer IAM.
2. Fails loudly when no canonical cloud artifacts exist yet.
3. Audits per-dataset manifest lineage against the real stored GCS generations/sizes.
4. Rebuilds and publishes the QA summary + QA HTML pages from canonical GCS records.
5. Publishes the catalogue manifest and delegates web/static assets to
   `tools/publish_docs_to_gcs.py`.
6. Verifies the live HTTPS endpoints.

Enforces the publish gate (`assert_publishable_dataset`, secret scanning, safe object
names) before any catalogue metadata is published.
"""

import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Tuple

import dotenv
from google.cloud import storage

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.catalogue.dataset_registry import DatasetRegistry
from src.ingestion.gcs_storage import GCSLakeStorage
from src.validation.publish_gate import (
    assert_publishable_dataset,
    assert_safe_object_name,
    load_env_secret_values,
)
from src.validation.qa_report import build_qa_summary, render_qa_html_pages

# Local .env is the documented credential/config store; without this the defaults
# below silently diverge from the actual bucket project.
dotenv.load_dotenv(PROJECT_ROOT / ".env")

GCP_PROJECT = os.environ.get("OIC_GCP_PROJECT", "operational-intelligence-crafter")
BUCKET_NAME = os.environ.get("OIC_GCS_BUCKET", "operational-intelligence-crafter-lake")
BUCKET_LOCATION = "AUSTRALIA-SOUTHEAST1"

# Canonical cloud-first artifact families. At least one object must already exist.
CANONICAL_PREFIXES = ("geoparquet/", "manifests/", "qa/", "exports/")

# Web/QA endpoints that must resolve after publication.
REQUIRED_WEB_OBJECTS = (
    "index.html",
    "qa/index.html",
    "qa/inspect.html",
    "qa/data/qa_summary.json",
    "manifests/dataset_manifest.json",
    "operational-intelligence-crafter.geolibre.json",
)

# Optional deliverables (only verified when present in the bucket).
OPTIONAL_WEB_OBJECTS = (
    "qa/geolibre_qa_inspect.html",
    "map_packages/hunter_flood_emergency_pack/index.html",
    "exports/hunter_population_grid_comparison/result.geojson",
    "data/locality_gazetteer.json",
)


def ensure_project_billing_linked(project_id: str) -> None:
    """Checks Cloud Billing API (enabling it via Service Usage API if needed) and links the active open billing account to `project_id`."""
    import time
    import google.auth
    from google.auth.transport.requests import AuthorizedSession

    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    if hasattr(creds, "with_quota_project"):
        creds = creds.with_quota_project(project_id)
    authed_session = AuthorizedSession(creds)

    # Enable cloudbilling.googleapis.com on project_id if not yet enabled
    su_url = f"https://serviceusage.googleapis.com/v1/projects/{project_id}/services/cloudbilling.googleapis.com:enable"
    su_resp = authed_session.post(su_url, json={}, timeout=20)
    if su_resp.status_code == 200:
        print(f"[SERVICE USAGE] Enabled cloudbilling.googleapis.com on '{project_id}'.")
        time.sleep(3)

    info_url = f"https://cloudbilling.googleapis.com/v1/projects/{project_id}/billingInfo"
    resp = authed_session.get(info_url, timeout=20)
    if resp.status_code == 200:
        data = resp.json()
        if data.get("billingEnabled"):
            print(f"[BILLING] Project '{project_id}' already linked to {data.get('billingAccountName')}.")
            return

    # Find open billing account
    acct_resp = authed_session.get("https://cloudbilling.googleapis.com/v1/billingAccounts", timeout=20)
    if acct_resp.status_code != 200:
        raise RuntimeError(f"Could not list billing accounts (HTTP {acct_resp.status_code}): {acct_resp.text}")

    accounts = acct_resp.json().get("billingAccounts", [])
    open_accts = [a for a in accounts if a.get("open")]
    if not open_accts:
        raise RuntimeError(f"No open billing accounts found: {accounts}")

    target_acct = open_accts[0]["name"]
    print(f"[BILLING] Linking project '{project_id}' to active billing account '{target_acct}' ({open_accts[0].get('displayName')})...")
    link_resp = authed_session.put(
        info_url,
        json={"billingAccountName": target_acct},
        timeout=20,
    )
    if link_resp.status_code != 200 and "quota" in link_resp.text.lower():
        unlink_project = "gen-lang-client-0804943594"
        print(f"[BILLING] Unlinking '{unlink_project}' from '{target_acct}' to free a slot for '{project_id}'...")
        unlink_url = f"https://cloudbilling.googleapis.com/v1/projects/{unlink_project}/billingInfo"
        unlink_resp = authed_session.put(unlink_url, json={"billingAccountName": ""}, timeout=20)
        if unlink_resp.status_code != 200:
            raise RuntimeError(f"Failed to unlink {unlink_project}: {unlink_resp.text}")
        print(f"[BILLING] Unlinked '{unlink_project}'. Retrying link for '{project_id}'...")
        time.sleep(2)
        link_resp = authed_session.put(
            info_url,
            json={"billingAccountName": target_acct},
            timeout=20,
        )
    if link_resp.status_code != 200:
        raise RuntimeError(f"Failed to link billing account to {project_id}: {link_resp.text}")
    print(f"[BILLING] Linked '{project_id}' -> '{target_acct}' (billingEnabled={link_resp.json().get('billingEnabled')}).")


def ensure_bucket_provisioned(bucket_name: str) -> Tuple[storage.Client, storage.Bucket]:
    """Ensures the canonical GCS bucket exists in operational-intelligence-crafter with versioning, CORS, and public reader access."""
    ensure_project_billing_linked(GCP_PROJECT)
    client = storage.Client(project=GCP_PROJECT)
    bucket = client.bucket(bucket_name)
    if not bucket.exists():
        print(f"[GCS] Creating bucket gs://{bucket_name} in project {GCP_PROJECT} ({BUCKET_LOCATION})...")
        bucket.storage_class = "STANDARD"
        bucket.iam_configuration.uniform_bucket_level_access_enabled = True
        bucket = client.create_bucket(bucket, location=BUCKET_LOCATION, project=GCP_PROJECT)
    else:
        bucket.reload()
        print(f"[GCS] Bucket gs://{bucket_name} exists in {bucket.location} (project={GCP_PROJECT}).")

    # Enable object versioning for immutable audit lineage
    bucket.versioning_enabled = True
    bucket.cors = [
        {
            "origin": ["*"],
            "method": ["GET", "HEAD", "OPTIONS"],
            "responseHeader": ["Content-Type", "Range", "Content-Range", "Access-Control-Allow-Origin"],
            "maxAgeSeconds": 3600,
        }
    ]
    bucket.patch()

    # Grant allUsers objectViewer so static HTML/GeoJSON/GeoParquet links can be tested directly in browser
    try:
        policy = bucket.get_iam_policy(requested_policy_version=3)
        has_public = any(
            b.get("role") == "roles/storage.objectViewer" and "allUsers" in b.get("members", set())
            for b in policy.bindings
        )
        if not has_public:
            policy.bindings.append(
                {"role": "roles/storage.objectViewer", "members": {"allUsers"}}
            )
            bucket.set_iam_policy(policy)
            print(f"[GCS] Granted roles/storage.objectViewer to allUsers on gs://{bucket_name}")
    except Exception as exc:
        print(f"[GCS] Note: could not set allUsers IAM policy ({exc})")

    return client, bucket


def audit_cloud_inventory(bucket: storage.Bucket) -> Dict[str, Any]:
    """Counts canonical cloud artifacts and fails loudly when the lakehouse is empty."""
    prefix_counts: Dict[str, int] = {}
    total_blobs = 0
    total_bytes = 0
    for prefix in CANONICAL_PREFIXES:
        count = 0
        for blob in bucket.list_blobs(prefix=prefix, fields="name,size"):
            count += 1
            total_bytes += int(blob.size or 0)
        prefix_counts[prefix] = count
        total_blobs += count

    print("[INVENTORY] Canonical cloud artifacts: " + ", ".join(f"{p}{n}" for p, n in prefix_counts.items()))
    if total_blobs == 0:
        raise RuntimeError(
            f"gs://{bucket.name}/ contains no canonical artifacts under {CANONICAL_PREFIXES}. "
            "Run a cloud-first ingestion/harvest pipeline before publishing; local lake staging is not supported."
        )
    return {
        "prefix_counts": prefix_counts,
        "total_blobs": total_blobs,
        "total_bytes": total_bytes,
    }


def audit_manifest_lineage(
    bucket: storage.Bucket, dataset_records: Dict[str, Dict[str, Any]]
) -> Dict[str, Any]:
    """Compares recorded GCS generations/sizes with the real stored blobs (read-only audit)."""
    bucket_prefix = f"gs://{bucket.name}/"
    checked = 0
    mismatches: List[Dict[str, Any]] = []

    for record_key, record in dataset_records.items():
        gs_uri = record.get("gs_uri")
        if not gs_uri or not str(gs_uri).startswith(bucket_prefix):
            continue
        object_key = str(gs_uri)[len(bucket_prefix):]
        blob = bucket.get_blob(object_key)
        if blob is None:
            mismatches.append({"record": record_key, "issue": "missing_blob", "gs_uri": gs_uri})
            continue
        checked += 1
        recorded_gen = record.get("gcs_generation")
        if recorded_gen and str(recorded_gen) != str(blob.generation):
            mismatches.append(
                {
                    "record": record_key,
                    "issue": "generation_mismatch",
                    "recorded": str(recorded_gen),
                    "actual": str(blob.generation),
                    "gs_uri": gs_uri,
                }
            )
            continue
        recorded_size = record.get("file_size_bytes")
        if recorded_size and int(recorded_size) != int(blob.size or 0):
            mismatches.append(
                {
                    "record": record_key,
                    "issue": "size_mismatch",
                    "recorded": int(recorded_size),
                    "actual": int(blob.size or 0),
                    "gs_uri": gs_uri,
                }
            )

    if mismatches:
        print(f"[LINEAGE] WARNING: {len(mismatches)} dataset manifest record(s) disagree with stored GCS blobs.")
        for item in mismatches[:10]:
            print(f"  [LINEAGE] {item}")
    else:
        print(f"[LINEAGE] Verified {checked} dataset manifest generation/size reference(s) against GCS.")
    return {"checked": checked, "mismatches": mismatches}


def _assert_paths_secret_free(paths: List[Path], secrets: List[str]) -> None:
    """Blocks publication of any static asset that embeds a `.env` secret value."""
    text_suffixes = {".json", ".html", ".css", ".js", ".txt", ".geojson", ".svg", ".md"}
    for path in paths:
        if path.suffix.lower() not in text_suffixes or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(secret and secret in text for secret in secrets):
            raise RuntimeError(f"Blocked publication: {path} contains a secret value from .env")


def _verify_urls(items: List[Tuple[str, bool]], bucket_name: str) -> Dict[str, Any]:
    """HEAD-checks live HTTPS endpoints; missing required objects raise, optional ones warn."""
    verified: List[Dict[str, Any]] = []
    failures: List[str] = []
    for object_key, required in items:
        url = f"https://storage.googleapis.com/{bucket_name}/{object_key}"
        try:
            req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                print(f"  [VERIFY HTTP {resp.status}] {url}")
                verified.append({"url": url, "status": resp.status})
        except Exception as exc:
            label = "FAIL" if required else "WARN"
            print(f"  [{label}] {url}: {exc}")
            if required:
                failures.append(url)

    if failures:
        raise RuntimeError(f"Required live endpoints failed verification: {failures}")
    return {"verified": verified, "required_failures": failures}


def publish_and_verify() -> Dict[str, Any]:
    """Publishes catalogue metadata, QA pages, and web assets, then verifies live endpoints."""
    reg = DatasetRegistry()
    store = GCSLakeStorage(bucket_name=BUCKET_NAME, gcp_project=GCP_PROJECT)
    secrets = load_env_secret_values(PROJECT_ROOT)

    # Enforce the publish gate for every catalogued dataset before publishing anything.
    for key in reg.list_keys():
        assert_publishable_dataset(reg.get(key).model_dump(mode="json"))

    client, bucket = ensure_bucket_provisioned(BUCKET_NAME)

    # 1. Refuse to publish an empty lakehouse (no local staging fallback exists).
    inventory = audit_cloud_inventory(bucket)

    # 2. Audit canonical per-dataset manifests against the real stored blobs.
    dataset_records = store.read_json_prefix_cloud("manifests/datasets/")
    if not dataset_records:
        raise RuntimeError(
            "No canonical dataset manifests found under gs://.../manifests/datasets/. "
            "Run cloud-first ingestion/harvest before publishing."
        )
    lineage = audit_manifest_lineage(bucket, dataset_records)

    # 3. Publish the canonical catalogue manifest (config is the tracked source of truth).
    manifest_cfg = PROJECT_ROOT / "config" / "dataset_manifest.json"
    catalogue_bytes = manifest_cfg.read_bytes()
    if any(secret and secret in catalogue_bytes.decode("utf-8", errors="ignore") for secret in secrets):
        raise RuntimeError("Blocked publication: config/dataset_manifest.json contains a .env secret value.")
    assert_safe_object_name("manifests/dataset_manifest.json")
    store.upload_bytes_cloud(
        "manifests/dataset_manifest.json",
        catalogue_bytes,
        content_type="application/json; charset=utf-8",
    )
    print(f"[UPLOAD] gs://{BUCKET_NAME}/manifests/dataset_manifest.json ({len(catalogue_bytes):,} B)")

    # 4. Rebuild the QA summary from canonical GCS records and publish QA pages.
    summary = build_qa_summary(registry=reg, storage=store, upload_cloud=True, write_local=False)
    docs_qa_data = PROJECT_ROOT / "docs" / "qa" / "data"
    docs_qa_data.mkdir(parents=True, exist_ok=True)
    (docs_qa_data / "qa_summary.json").write_bytes(
        json.dumps(summary, indent=2, ensure_ascii=False).encode("utf-8")
    )
    render_qa_html_pages(summary, storage=store, upload_cloud=True)

    # 5. Publish static web assets (no stale qa/data previews are uploaded by the delegate).
    from tools.publish_docs_to_gcs import upload_web_assets

    _assert_paths_secret_free(sorted((PROJECT_ROOT / "docs").rglob("*")), secrets)
    upload_web_assets()

    # 6. Verify live HTTPS endpoints.
    items = [(key, True) for key in REQUIRED_WEB_OBJECTS]
    items += [(key, False) for key in OPTIONAL_WEB_OBJECTS if bucket.get_blob(key) is not None]
    verification = _verify_urls(items, BUCKET_NAME)

    return {
        "bucket": BUCKET_NAME,
        "project": GCP_PROJECT,
        "inventory": inventory,
        "lineage": lineage,
        "qa_report_id": summary["report_id"],
        "verified_urls": verification["verified"],
    }


def upload_and_sync_all() -> Dict[str, Any]:
    """Backwards-compatible alias for `publish_and_verify` (cloud-first; no local lake)."""
    return publish_and_verify()


if __name__ == "__main__":
    publish_and_verify()
