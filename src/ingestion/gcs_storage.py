"""Google Cloud Storage Storage Manager (Cloud-First).

Enforces the canonical GCS layout:
gs://<bucket>/
    raw/<dataset_key>/<retrieval_timestamp>/source_payload.*
    geoparquet/<dataset_key>/<source_vintage>/<retrieval_timestamp>/part-00000.parquet
    manifests/datasets/<dataset_key>.json
    manifests/releases/<release_id>.json
    qa/datasets/<dataset_key>/<retrieval_timestamp>.json
    qa/reports/<report_id>/
    exports/<analysis_id>/
    map_packages/<package_id>/

Cloud-first is the default: bytes are uploaded straight from memory to GCS and no
local lake staging is written. An explicit local mirror is still possible for offline
debugging by setting `OIC_LOCAL_LAKE_ROOT` (and `OIC_STAGE_LOCAL=1`); it is never a
silent fallback.
"""

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.ingestion.telemetry import compute_sha256
from src.validation.publish_gate import (
    assert_publishable_dataset,
    assert_safe_object_name,
    load_env_secret_values,
    PublishBlocked,
)


def get_project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


class GCSLakeStorage:
    """Canonical storage manager for versioned GeoParquet, raw payloads, manifests, and QA artifacts."""

    def __init__(
        self,
        bucket_name: Optional[str] = None,
        gcp_project: Optional[str] = None,
        local_root: Optional[Path] = None,
        stage_local: Optional[bool] = None,
    ):
        self.project_root = get_project_root()
        self.bucket_name = bucket_name or os.environ.get(
            "OIC_GCS_BUCKET", "operational-intelligence-crafter-lake"
        )
        self.gcp_project = gcp_project or os.environ.get(
            "OIC_GCP_PROJECT", "operational-intelligence-crafter"
        )
        if local_root is not None:
            self.local_root: Optional[Path] = Path(local_root)
        else:
            env_root = os.environ.get("OIC_LOCAL_LAKE_ROOT", "").strip()
            self.local_root = (
                (self.project_root / env_root).resolve()
                if env_root
                else None
            )
        if stage_local is None:
            self.stage_local = (
                os.environ.get("OIC_STAGE_LOCAL", "0") == "1"
                and self.local_root is not None
            )
        else:
            self.stage_local = bool(stage_local)
        self._secrets = load_env_secret_values(self.project_root)

    # ------------------------------------------------------------------
    # Canonical Object Key Builders (Immutable Versioned Paths)
    # ------------------------------------------------------------------
    @staticmethod
    def raw_object_key(dataset_key: str, retrieval_ts: str, ext: str = "json") -> str:
        return f"raw/{dataset_key}/{retrieval_ts}/source_payload.{ext.lstrip('.')}"

    @staticmethod
    def geoparquet_object_key(
        dataset_key: str, source_vintage: str, retrieval_ts: str, part: int = 0
    ) -> str:
        safe_vintage = source_vintage.replace(" ", "_").replace("/", "-")
        return f"geoparquet/{dataset_key}/{safe_vintage}/{retrieval_ts}/part-{part:05d}.parquet"

    @staticmethod
    def dataset_manifest_object_key(dataset_key: str) -> str:
        return f"manifests/datasets/{dataset_key}.json"

    @staticmethod
    def release_manifest_object_key(release_id: str) -> str:
        return f"manifests/releases/{release_id}.json"

    @staticmethod
    def dataset_qa_object_key(dataset_key: str, retrieval_ts: str) -> str:
        return f"qa/datasets/{dataset_key}/{retrieval_ts}.json"

    @staticmethod
    def qa_report_object_key(report_id: str, filename: str = "qa_summary.json") -> str:
        return f"qa/reports/{report_id}/{filename}"

    def gs_uri(self, object_key: str) -> str:
        return f"gs://{self.bucket_name}/{object_key.lstrip('/')}"

    def local_path(self, object_key: str) -> Path:
        """Resolves an object key inside the explicit offline mirror.

        Raises when no mirror is configured: cloud-first callers must never fall
        back to local disk implicitly.
        """
        if self.local_root is None:
            raise RuntimeError(
                "No local lake mirror configured. Cloud-first storage writes directly to GCS. "
                "Set OIC_LOCAL_LAKE_ROOT (and OIC_STAGE_LOCAL=1) only for an explicit offline mirror."
            )
        return self.local_root / object_key.lstrip("/")

    def optional_local_path(self, object_key: str) -> Optional[Path]:
        """Returns the mirror path when a mirror is configured, else None (read-only probe)."""
        return None if self.local_root is None else self.local_root / object_key.lstrip("/")

    # ------------------------------------------------------------------
    # Artifact Write Operations (cloud-first by default)
    # ------------------------------------------------------------------
    def _scan_text_for_secrets(self, text: str, object_key: str) -> None:
        for secret in self._secrets:
            if secret and secret in text:
                raise PublishBlocked(
                    f"Blocked write to {object_key}: content contains a secret value from .env"
                )

    def write_bytes(
        self,
        object_key: str,
        data: bytes,
        dataset_entry: Optional[Dict[str, Any]] = None,
        upload_cloud: bool = True,
        overwrite: bool = False,
    ) -> Dict[str, Any]:
        """Writes an artifact cloud-first (memory -> GCS).

        Passing `upload_cloud=False` requires an explicit offline mirror
        (`OIC_LOCAL_LAKE_ROOT` plus `OIC_STAGE_LOCAL=1`); there is no silent
        local fallback.
        """
        assert_safe_object_name(object_key)
        if upload_cloud:
            result = self.upload_bytes_cloud(
                object_key, data, dataset_entry=dataset_entry
            )
            result["overwrite"] = overwrite
            return result

        if not (self.stage_local and self.local_root is not None):
            raise RuntimeError(
                "Local lake writing is disabled (cloud-first default). Upload to GCS instead, "
                "or set OIC_LOCAL_LAKE_ROOT and OIC_STAGE_LOCAL=1 for an explicit offline mirror."
            )

        dest = self.local_path(object_key)
        if dest.exists() and not overwrite and not object_key.startswith("manifests/datasets/"):
            raise FileExistsError(
                f"Immutable lakehouse artifact already exists and cannot be overwritten: {dest}"
            )
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return {
            "object_key": object_key,
            "gs_uri": self.gs_uri(object_key),
            "local_path": str(dest.relative_to(self.project_root)).replace("\\", "/"),
            "file_size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "storage_mode": "local_staged_mirror_explicit",
            "gcs_generation": None,
        }

    def write_json(
        self,
        object_key: str,
        payload: Dict[str, Any],
        dataset_entry: Optional[Dict[str, Any]] = None,
        upload_cloud: bool = True,
        overwrite: bool = False,
    ) -> Dict[str, Any]:
        text = json.dumps(payload, indent=2, ensure_ascii=False)
        self._scan_text_for_secrets(text, object_key)
        return self.write_bytes(
            object_key=object_key,
            data=text.encode("utf-8"),
            dataset_entry=dataset_entry,
            upload_cloud=upload_cloud,
            overwrite=overwrite,
        )

    def register_local_parquet(
        self,
        parquet_file: Path,
        object_key: str,
        dataset_entry: Optional[Dict[str, Any]] = None,
        upload_cloud: bool = True,
    ) -> Dict[str, Any]:
        """Registers an already-written GeoParquet file cloud-first (uploads from disk to GCS)."""
        assert_safe_object_name(object_key)
        if not parquet_file.exists():
            raise FileNotFoundError(f"GeoParquet file not found: {parquet_file}")

        if upload_cloud:
            return self.upload_file_to_gcs(
                local_file=parquet_file, object_key=object_key, dataset_entry=dataset_entry
            )

        if not (self.stage_local and self.local_root is not None):
            raise RuntimeError(
                "Local lake writing is disabled (cloud-first default). Set OIC_LOCAL_LAKE_ROOT "
                "and OIC_STAGE_LOCAL=1 for an explicit offline mirror."
            )

        dest = self.local_path(object_key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if parquet_file.resolve() != dest.resolve():
            shutil.copyfile(parquet_file, dest)
        return {
            "object_key": object_key,
            "gs_uri": self.gs_uri(object_key),
            "local_path": str(dest.relative_to(self.project_root)).replace("\\", "/"),
            "file_size_bytes": dest.stat().st_size,
            "sha256": compute_sha256(dest),
            "storage_mode": "local_staged_mirror_explicit",
            "gcs_generation": None,
        }

    def upload_file_to_gcs(
        self,
        local_file: Path,
        object_key: str,
        dataset_entry: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Uploads a local artifact to Google Cloud Storage (canonical storage)."""
        assert_safe_object_name(object_key)
        if dataset_entry is not None:
            assert_publishable_dataset(dataset_entry)

        from google.cloud import storage  # Lazy import so offline tests work without network

        client = storage.Client(project=self.gcp_project or None)
        bucket = client.bucket(self.bucket_name)
        blob = bucket.blob(object_key)
        blob.cache_control = "public, max-age=300"
        blob.upload_from_filename(str(local_file))
        blob.reload()
        return {
            "object_key": object_key,
            "gs_uri": self.gs_uri(object_key),
            "gcs_https_url": f"https://storage.googleapis.com/{self.bucket_name}/{object_key}",
            "local_path": None,
            "file_size_bytes": local_file.stat().st_size,
            "sha256": compute_sha256(local_file),
            "storage_mode": "gcs_canonical",
            "gcs_generation": str(blob.generation),
            "gcs_md5_hash": blob.md5_hash,
            "gcs_updated_utc": blob.updated.isoformat() if blob.updated else None,
        }

    # ------------------------------------------------------------------
    # Cloud-First Operations (zero local staging)
    # ------------------------------------------------------------------
    def upload_bytes_cloud(
        self,
        object_key: str,
        data: bytes,
        dataset_entry: Optional[Dict[str, Any]] = None,
        content_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Uploads bytes directly from memory to GCS — no local lake staging (cloud-first)."""
        assert_safe_object_name(object_key)
        if dataset_entry is not None:
            assert_publishable_dataset(dataset_entry)
        try:
            self._scan_text_for_secrets(data.decode("utf-8"), object_key)
        except UnicodeDecodeError:
            pass  # binary payload

        import hashlib
        import io as _io
        from google.cloud import storage

        client = storage.Client(project=self.gcp_project or None)
        blob = client.bucket(self.bucket_name).blob(object_key)
        blob.cache_control = "public, max-age=300"
        blob.upload_from_file(
            _io.BytesIO(data),
            size=len(data),
            content_type=content_type or "application/octet-stream",
        )
        blob.reload()
        return {
            "object_key": object_key,
            "gs_uri": self.gs_uri(object_key),
            "gcs_https_url": f"https://storage.googleapis.com/{self.bucket_name}/{object_key}",
            "local_path": None,
            "file_size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "storage_mode": "gcs_canonical_cloud_first",
            "gcs_generation": str(blob.generation),
            "gcs_md5_hash": blob.md5_hash,
        }

    def read_json_cloud(self, object_key: str) -> Optional[Dict[str, Any]]:
        """Reads a JSON record directly from GCS. Returns None when absent/unreadable."""
        try:
            from google.cloud import storage
            client = storage.Client(project=self.gcp_project or None)
            blob = client.bucket(self.bucket_name).blob(object_key)
            if not blob.exists(client):
                return None
            return json.loads(blob.download_as_text())
        except Exception:
            return None

    def cloud_object_exists(self, object_key: str) -> bool:
        """Checks whether a canonical object exists in GCS (returns False when unreachable)."""
        try:
            from google.cloud import storage
            client = storage.Client(project=self.gcp_project or None)
            return client.bucket(self.bucket_name).blob(object_key.lstrip("/")).exists(client)
        except Exception:
            return False

    def read_bytes_cloud(self, object_key: str) -> Optional[bytes]:
        """Reads raw bytes directly from GCS. Returns None when absent/unreadable."""
        try:
            from google.cloud import storage
            client = storage.Client(project=self.gcp_project or None)
            blob = client.bucket(self.bucket_name).blob(object_key.lstrip("/"))
            if not blob.exists(client):
                return None
            return blob.download_as_bytes()
        except Exception:
            return None

    def list_cloud_objects(self, prefix: str) -> List[str]:
        """Lists canonical object names under a GCS prefix (empty list when unreachable)."""
        try:
            from google.cloud import storage
            client = storage.Client(project=self.gcp_project or None)
            return sorted(
                blob.name
                for blob in client.list_blobs(self.bucket_name, prefix=prefix)
            )
        except Exception:
            return []

    def read_json_prefix_cloud(self, prefix: str) -> Dict[str, Dict[str, Any]]:
        """Bulk-reads JSON records under a GCS prefix, keyed by full object name.

        Used by the QA summary so a single list call resolves every canonical
        dataset record instead of issuing per-dataset existence/download round
        trips. Returns an empty mapping when GCS is unavailable.
        """
        try:
            from google.cloud import storage
            client = storage.Client(project=self.gcp_project or None)
            bucket = client.bucket(self.bucket_name)
            records: Dict[str, Dict[str, Any]] = {}
            for blob in client.list_blobs(bucket, prefix=prefix):
                if not blob.name.endswith(".json"):
                    continue
                records[blob.name] = json.loads(blob.download_as_text())
            return records
        except Exception:
            return {}

