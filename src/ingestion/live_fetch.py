"""Just-in-Time (JIT) Live Feed Ingestion & Snapshot Fallback Resolver.

Implements Pattern B (Just-in-Time Live Ingestion) from Section 5 of the specification:
1. Queries the live operational endpoint at request time.
2. Validates the response against the Level 1 source contract.
3. Normalizes geometry and CRS to EPSG:7844.
4. Saves an immutable timestamped snapshot to the lakehouse for provenance & reproducibility.
5. If the live endpoint fails and `allow_snapshot_fallback=True`, explicitly reports the live failure
   and returns the latest verified stored snapshot with an explicit fallback provenance warning
   (never silently substituting data!).
"""

from typing import Any, Dict, List, Optional
import geopandas as gpd

from src.catalogue.dataset_registry import DatasetRegistry
from src.catalogue.manifest_loader import QAStatus
from src.ingestion.gcs_storage import GCSLakeStorage
from src.ingestion.snapshot_ingest import ingest_dataset_snapshot


def fetch_just_in_time_or_snapshot(
    dataset_key: str,
    bbox: Optional[List[float]] = None,
    allow_snapshot_fallback: bool = True,
    registry: Optional[DatasetRegistry] = None,
    storage: Optional[GCSLakeStorage] = None,
) -> Dict[str, Any]:
    """Executes JIT live ingestion and records provenance, with explicit (never silent) fallback."""
    reg = registry or DatasetRegistry()
    store = storage or GCSLakeStorage()
    entry = reg.get(dataset_key)

    live_record = ingest_dataset_snapshot(
        dataset_key=dataset_key,
        registry=reg,
        storage=store,
        bbox=bbox,
        upload_cloud=False,
    )

    if live_record["overall_qa_status"] != QAStatus.FAIL.value:
        parquet_path = store.project_root / live_record["local_parquet_path"]
        gdf = gpd.read_parquet(parquet_path)
        return {
            "mode": "just_in_time_live",
            "fallback_used": False,
            "live_error": None,
            "dataset_key": dataset_key,
            "retrieval_timestamp_utc": live_record["retrieval_timestamp_utc"],
            "parquet_path": str(parquet_path),
            "gs_uri": live_record["gs_uri"],
            "qa_status": live_record["overall_qa_status"],
            "gdf": gdf,
            "provenance": live_record,
        }

    live_err = live_record["level1_source_contract"].get("error_message", "Live endpoint failed")
    if allow_snapshot_fallback and entry.latest_snapshot_path:
        snap_file = store.project_root / entry.latest_snapshot_path
        if snap_file.exists():
            gdf = gpd.read_parquet(snap_file)
            return {
                "mode": "stored_snapshot_explicit_fallback",
                "fallback_used": True,
                "live_error": live_err,
                "warning": (
                    f"LIVE ENDPOINT FAILED ({live_err}). Explicitly using stored snapshot from "
                    f"{entry.latest_retrieval_utc} ({entry.latest_snapshot_path})."
                ),
                "dataset_key": dataset_key,
                "retrieval_timestamp_utc": entry.latest_retrieval_utc,
                "parquet_path": str(snap_file),
                "gs_uri": store.gs_uri(entry.latest_snapshot_path),
                "qa_status": QAStatus.WARNING.value,
                "gdf": gdf,
                "provenance": live_record,
            }

    raise RuntimeError(
        f"JIT live fetch failed for '{dataset_key}' ({live_err}) and no verified stored snapshot is available."
    )

