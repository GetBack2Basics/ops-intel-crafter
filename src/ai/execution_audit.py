"""Structured Provenance & Execution Audit Recorder for AI-Assisted Spatial Queries (Section 8.2)."""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.ingestion.telemetry import utc_now_iso


@dataclass
class AIExecutionAuditRecord:
    audit_id: str
    timestamp_utc: str
    user_question: str
    status: str  # EXECUTED, CLARIFICATION_REQUIRED, REJECTED_UNCATALOGUED
    selected_datasets: List[str] = field(default_factory=list)
    source_vintages: Dict[str, str] = field(default_factory=dict)
    retrieval_timestamps: Dict[str, str] = field(default_factory=dict)
    generated_sql: Optional[str] = None
    execution_engine: str = "duckdb_spatial"
    stored_crs: str = "EPSG:7844"
    metric_crs: str = "EPSG:3112"
    population_method: Optional[str] = None
    row_count: int = 0
    execution_ms: float = 0.0
    clarification_questions: List[str] = field(default_factory=list)
    warnings_and_limitations: List[str] = field(default_factory=list)
    grounded_explanation: str = ""
    sample_rows: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def save(self, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)
        return output_path

