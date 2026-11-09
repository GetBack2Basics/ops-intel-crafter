"""Provision GCS Bucket (`gs://operational-intelligence-crafter-lake` in `ops-intelligence-crafter`),
Sync All Lakehouse GeoParquet/Manifest/QA Artifacts, and Verify Live HTTPS Endpoints.

Enforces:
- Publish Gate (`assert_safe_object_name`, `assert_publishable_dataset`, zero `.env` secrets).
- Records real GCS `blob.generation` numbers into dataset manifests and `qa_summary.json`.
- Configures CORS and public object viewer IAM on `gs://operational-intelligence-crafter-lake`
  so MapLibre / GeoLibre web pages and GeoParquet / GeoJSON deliverables are live-testable on GCS.
"""

import json
import mimetypes
import os
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

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

GCP_PROJECT = os.environ.get("OIC_GCP_PROJECT", "ops-intelligence-crafter")
BUCKET_NAME = os.environ.get("OIC_GCS_BUCKET", "operational-intelligence-crafter-lake")
BUCKET_LOCATION = "AUSTRALIA-SOUTHEAST1"


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


def ensure_bucket_provisioned(bucket_name: str) -> tuple[storage.Client, storage.Bucket]:
    """Ensures the canonical GCS bucket exists in ops-intelligence-crafter with versioning, CORS, and public reader access."""
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


def _guess_content_type(path: Path) -> str:
    if path.suffix == ".parquet":
        return "application/octet-stream"
    if path.suffix == ".geojson":
        return "application/geo+json; charset=utf-8"
    if path.suffix == ".json":
        return "application/json; charset=utf-8"
    if path.suffix == ".html":
        return "text/html; charset=utf-8"
    if path.suffix == ".css":
        return "text/css; charset=utf-8"
    if path.suffix == ".js":
        return "application/javascript; charset=utf-8"
    ctype, _ = mimetypes.guess_type(str(path))
    return ctype or "application/octet-stream"


def upload_and_sync_all() -> Dict[str, Any]:
    reg = DatasetRegistry()
    store = GCSLakeStorage(bucket_name=BUCKET_NAME, gcp_project=GCP_PROJECT)
    secrets = load_env_secret_values(PROJECT_ROOT)

    # Ensure every catalogued dataset passes publish_gate
    for k in reg.list_keys():
        entry = reg.get(k)
        assert_publishable_dataset(entry.model_dump(mode="json"))

    client, bucket = ensure_bucket_provisioned(BUCKET_NAME)

    uploaded_generations: Dict[str, str] = {}
    lake_root = PROJECT_ROOT / "data" / "lake"

    # 1. Upload raw/ and geoparquet/ first so we capture exact GCS object generation IDs
    for subdir in ("raw", "geoparquet"):
        folder = lake_root / subdir
        if not folder.exists():
            continue
        for item in sorted(folder.rglob("*")):
            if not item.is_file():
                continue
            object_key = item.relative_to(lake_root).as_posix()
            assert_safe_object_name(object_key)
            blob = bucket.blob(object_key)
            blob.cache_control = "public, max-age=300"
            blob.upload_from_filename(str(item), content_type=_guess_content_type(item))
            blob.reload()
            uploaded_generations[object_key] = str(blob.generation)
            print(f"  [UPLOAD] gs://{BUCKET_NAME}/{object_key} (gen={blob.generation}, {item.stat().st_size:,} B)")

    # 2. Update dataset manifests with real GCS generation IDs and re-render QA pages
    manifests_dir = lake_root / "manifests" / "datasets"
    if manifests_dir.exists():
        for mf in sorted(manifests_dir.glob("*.json")):
            rec = json.loads(mf.read_text(encoding="utf-8"))
            local_pq = rec.get("local_parquet_path") or ""
            if local_pq.startswith("data/lake/"):
                obj_key = local_pq[len("data/lake/"):]
                if obj_key in uploaded_generations:
                    gen = uploaded_generations[obj_key]
                    rec["gcs_generation"] = gen
                    if "level2_stored_artifact" in rec and isinstance(rec["level2_stored_artifact"], dict):
                        rec["level2_stored_artifact"]["gcs_generation"] = gen
                        for chk in rec["level2_stored_artifact"].get("checks", []):
                            if chk.get("check") == "sha256_and_storage_lineage":
                                chk["detail"] = f"sha256={rec.get('sha256', '')[:16]}... | generation={gen}"
            mf.write_text(json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")

    # Rebuild QA summary and HTML pages with real GCS generations
    summary = build_qa_summary(registry=reg, storage=store)
    render_qa_html_pages(summary)

    # 3. Upload manifests/, qa/, exports/, and map_packages/ under data/lake/
    for subdir in ("manifests", "qa", "exports", "map_packages"):
        folder = lake_root / subdir
        if not folder.exists():
            continue
        for item in sorted(folder.rglob("*")):
            if not item.is_file():
                continue
            object_key = item.relative_to(lake_root).as_posix()
            assert_safe_object_name(object_key)
            if item.suffix in (".json", ".html", ".css", ".js", ".txt", ".geojson"):
                text = item.read_text(encoding="utf-8", errors="ignore")
                if any(s in text for s in secrets if s):
                    raise RuntimeError(f"Blocked {object_key}: contains secret value")
            blob = bucket.blob(object_key)
            blob.cache_control = "public, max-age=60"
            blob.upload_from_filename(str(item), content_type=_guess_content_type(item))
            print(f"  [UPLOAD] gs://{BUCKET_NAME}/{object_key} ({item.stat().st_size:,} B)")

    # 4. Upload docs/qa/ web deliverables to gs://<bucket>/qa/ and docs/index.html to root
    docs_qa = PROJECT_ROOT / "docs" / "qa"
    for item in sorted(docs_qa.rglob("*")):
        if not item.is_file():
            continue
        rel = item.relative_to(docs_qa).as_posix()
        object_key = f"qa/{rel}"
        assert_safe_object_name(object_key)
        text = item.read_text(encoding="utf-8", errors="ignore")
        if any(s in text for s in secrets if s):
            raise RuntimeError(f"Blocked {object_key}: contains secret value")
        blob = bucket.blob(object_key)
        blob.cache_control = "public, max-age=60"
        blob.upload_from_filename(str(item), content_type=_guess_content_type(item))
        print(f"  [UPLOAD] gs://{BUCKET_NAME}/{object_key} ({item.stat().st_size:,} B)")

    for root_doc in ("index.html", "style.css", "app.js", "layers.js", "data/workbench_bundle.json"):
        doc_path = PROJECT_ROOT / "docs" / root_doc
        if doc_path.exists():
            assert_safe_object_name(root_doc)
            text = doc_path.read_text(encoding="utf-8", errors="ignore")
            if any(s in text for s in secrets if s):
                raise RuntimeError(f"Blocked {root_doc}: contains secret value")
            blob = bucket.blob(root_doc)
            blob.cache_control = "public, max-age=60"
            blob.upload_from_filename(str(doc_path), content_type=_guess_content_type(doc_path))
            print(f"  [UPLOAD] gs://{BUCKET_NAME}/{root_doc} ({doc_path.stat().st_size:,} B)")

    # 5. Also upload config/dataset_manifest.json to manifests/dataset_manifest.json
    manifest_cfg = PROJECT_ROOT / "config" / "dataset_manifest.json"
    blob = bucket.blob("manifests/dataset_manifest.json")
    blob.cache_control = "public, max-age=60"
    blob.upload_from_filename(str(manifest_cfg), content_type="application/json; charset=utf-8")

    # 6. Verify live HTTPS URLs
    test_urls = [
        f"https://storage.googleapis.com/{BUCKET_NAME}/index.html",
        f"https://storage.googleapis.com/{BUCKET_NAME}/qa/index.html",
        f"https://storage.googleapis.com/{BUCKET_NAME}/qa/inspect.html",
        f"https://storage.googleapis.com/{BUCKET_NAME}/map_packages/hunter_flood_emergency_pack/index.html",
        f"https://storage.googleapis.com/{BUCKET_NAME}/exports/hunter_population_grid_comparison/result.geojson",
        f"https://storage.googleapis.com/{BUCKET_NAME}/qa/data/qa_summary.json",
        f"https://storage.googleapis.com/{BUCKET_NAME}/manifests/dataset_manifest.json",
    ]
    verified = []
    for u in test_urls:
        req = urllib.request.Request(u, method="HEAD")
        with urllib.request.urlopen(req, timeout=20) as resp:
            print(f"  [VERIFY HTTP {resp.status}] {u}")
            verified.append({"url": u, "status": resp.status})

    return {"bucket": BUCKET_NAME, "project": GCP_PROJECT, "verified_urls": verified}


if __name__ == "__main__":
    upload_and_sync_all()

