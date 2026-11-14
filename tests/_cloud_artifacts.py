"""Cloud-first test artifact resolution helpers.

Canonical storage is GCS (`gs://operational-intelligence-crafter-lake/`). Local
`docs/exports/` and `docs/map_packages/` mirrors are untracked publish staging, so
tests must never *require* them. These helpers prefer an existing local mirror for
speed, then fall back to materialising the artifact from GCS into a temp cache.
"""

import os
import tempfile
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BUCKET_NAME = os.environ.get("OIC_GCS_BUCKET", "operational-intelligence-crafter-lake")
_CACHE_ROOT = Path(tempfile.gettempdir()) / "oic_test_artifacts"


def _gcs_fs():
    import fsspec

    return fsspec.filesystem("gcs")


def _bucket_path(object_key: str) -> str:
    return f"{BUCKET_NAME}/{object_key.lstrip('/')}"


def gs_uri(object_key: str) -> str:
    return f"gs://{BUCKET_NAME}/{object_key.lstrip('/')}"


def resolve_local_mirror(*relative_paths: str) -> Optional[Path]:
    """Returns the first existing local mirror path, if any."""
    for rel in relative_paths:
        candidate = PROJECT_ROOT / rel
        if candidate.exists():
            return candidate
    return None


def materialize_cloud_object(object_key: str, local_filename: Optional[str] = None) -> Path:
    """Downloads a GCS object into the temp cache (once) and returns the local path."""
    dest = _CACHE_ROOT / object_key.lstrip("/")
    if local_filename:
        dest = dest.parent / local_filename
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    fs = _gcs_fs()
    tmp = dest.with_suffix(dest.suffix + ".part")
    with fs.open(_bucket_path(object_key), "rb") as src, open(tmp, "wb") as out:
        while True:
            chunk = src.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)
    tmp.replace(dest)
    return dest


def materialize_cloud_prefix(prefix: str) -> Path:
    """Downloads every object under a GCS prefix into the temp cache and returns the root dir."""
    root = _CACHE_ROOT / prefix.strip("/")
    marker = root / ".complete"
    if marker.exists():
        return root
    fs = _gcs_fs()
    full_prefix = _bucket_path(prefix).rstrip("/")
    for path in fs.find(full_prefix):
        rel = path[len(full_prefix) :].lstrip("/")
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and dest.stat().st_size > 0:
            continue
        with fs.open(path, "rb") as src, open(dest, "wb") as out:
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
    marker.write_text("ok", encoding="utf-8")
    return root


def resolve_export_artifact(export_name: str, filename: str) -> Path:
    """Resolves a published analysis export, preferring the local docs mirror."""
    local = resolve_local_mirror(f"docs/exports/{export_name}/{filename}")
    if local is not None:
        return local
    return materialize_cloud_object(f"exports/{export_name}/{filename}")


def resolve_map_package(package_name: str) -> Path:
    """Resolves a published offline map package, preferring the local docs mirror."""
    local = resolve_local_mirror(f"docs/map_packages/{package_name}")
    if local is not None:
        return local
    return materialize_cloud_prefix(f"map_packages/{package_name}")


def resolve_qa_preview(dataset_key: str, ext: str = "geojson") -> Path:
    """Resolves a published QA preview artifact, preferring the local docs mirror."""
    filename = f"{dataset_key}.{ext}"
    local = resolve_local_mirror(f"docs/qa/data/{filename}")
    if local is not None:
        return local
    return materialize_cloud_object(f"qa/data/{filename}")


def resolve_geoparquet(gs_uri_or_key: str) -> str:
    """Returns a readable reference for DuckDB: gs:// URIs are used directly."""
    if gs_uri_or_key.startswith(("gs://", "https://", "http://")):
        return gs_uri_or_key
    return gs_uri(gs_uri_or_key)
