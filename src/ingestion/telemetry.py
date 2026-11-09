"""Ingestion and query telemetry recorder for provenance, latency, and cost tracking."""

import hashlib
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

INGESTION_SOFTWARE_VERSION = "operational_intelligence_crafter/0.2.0"
TRANSFORMATION_VERSION = "geoparquet-1.1.0-gda2020-v1"


def utc_now_iso() -> str:
    """Returns ISO-8601 UTC timestamp string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_now_compact() -> str:
    """Returns compact UTC timestamp suitable for immutable object paths."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def compute_sha256(file_path: Path) -> str:
    """Computes SHA-256 hex digest of a file on disk."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class IngestionTelemetry:
    dataset_key: str
    retrieval_timestamp_utc: str
    start_monotonic: float = field(default_factory=time.perf_counter, repr=False)
    http_requests_count: int = 0
    source_download_ms: float = 0.0
    normalization_ms: float = 0.0
    parquet_write_ms: float = 0.0
    validation_ms: float = 0.0
    total_elapsed_ms: float = 0.0
    bytes_downloaded: int = 0
    bytes_written: int = 0
    notes: list[str] = field(default_factory=list)

    def finalize(self) -> Dict[str, Any]:
        self.total_elapsed_ms = round((time.perf_counter() - self.start_monotonic) * 1000.0, 2)
        data = asdict(self)
        data.pop("start_monotonic", None)
        return data

