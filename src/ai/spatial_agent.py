"""Catalogue-Grounded AI Spatial Analysis Agent (Section 8).

Orchestrates:
1. Natural-language query planning (`plan_natural_language_query`).
2. Strict allow-list & read-only SQL validation (`validate_spatial_sql`).
3. DuckDB Spatial execution against stored GeoParquet snapshots.
4. Provenance-grounded explanation generation and JSON audit recording (`AIExecutionAuditRecord`).
"""

from pathlib import Path
from typing import Any, Dict, Optional, Set

from src.ai.execution_audit import AIExecutionAuditRecord
from src.ai.query_planner import plan_natural_language_query
from src.ai.sql_validator import SQLValidationError, validate_spatial_sql
from src.catalogue.dataset_registry import DatasetRegistry
from src.engines.duckdb_engine import DuckDBSpatialEngine
from src.ingestion.telemetry import utc_now_compact, utc_now_iso


class AISpatialAgent:
    """Grounded AI Spatial Analyst that enforces zero-mock and allow-listed catalogue rules."""

    def __init__(
        self,
        registry: Optional[DatasetRegistry] = None,
        engine: Optional[DuckDBSpatialEngine] = None,
        lake_geoparquet_dir: Optional[Path] = None,
    ):
        self.registry = registry or DatasetRegistry()
        self.engine = engine or DuckDBSpatialEngine()
        self.project_root = Path(__file__).resolve().parent.parent.parent
        self.lake_geoparquet_dir = lake_geoparquet_dir or (
            self.project_root / "data" / "lake" / "geoparquet"
        )

    def _register_dataset_views(self, dataset_keys: list[str]) -> None:
        for ds_key in dataset_keys:
            ds_dir = self.lake_geoparquet_dir / ds_key
            files = sorted(ds_dir.glob("*/*/part-*.parquet"))
            if not files:
                raise FileNotFoundError(
                    f"Dataset '{ds_key}' has no stored GeoParquet snapshot under {ds_dir}."
                )
            self.engine.register_geoparquet_view(ds_key, files[-1])

    def ask(
        self,
        question: str,
        explicit_pop_method: Optional[str] = None,
        explicit_scale: Optional[str] = None,
    ) -> AIExecutionAuditRecord:
        """Processes a user natural-language question and returns a verified `AIExecutionAuditRecord`."""
        audit_id = f"ai-audit-{utc_now_compact()}"
        ts_utc = utc_now_iso()
        plan = plan_natural_language_query(
            question=question,
            explicit_pop_method=explicit_pop_method,
            explicit_scale=explicit_scale,
        )

        if plan.status == "REJECTED_UNCATALOGUED":
            return AIExecutionAuditRecord(
                audit_id=audit_id,
                timestamp_utc=ts_utc,
                user_question=question,
                status="REJECTED_UNCATALOGUED",
                selected_datasets=plan.selected_datasets,
                warnings_and_limitations=[plan.rejection_reason or "Uncatalogued dataset requested."],
                grounded_explanation=plan.rejection_reason or "Request rejected by catalogue allow-list.",
            )

        if plan.status == "CLARIFICATION_REQUIRED":
            return AIExecutionAuditRecord(
                audit_id=audit_id,
                timestamp_utc=ts_utc,
                user_question=question,
                status="CLARIFICATION_REQUIRED",
                selected_datasets=plan.selected_datasets,
                clarification_questions=plan.clarification_questions,
                grounded_explanation=(
                    "Clarification required before executing spatial SQL: "
                    + " ".join(plan.clarification_questions)
                ),
            )

        # Verify all selected datasets are in the allow-listed catalogue and not FAIL
        allowlisted_keys: Set[str] = set(self.registry.list_keys())
        vintages: Dict[str, str] = {}
        retrievals: Dict[str, str] = {}
        warnings: list[str] = list(plan.notes)

        for ds_key in plan.selected_datasets:
            entry = self.registry.get(ds_key)
            if entry.qa_status.value == "FAIL":
                raise SQLValidationError(
                    f"Dataset '{ds_key}' has QA status FAIL and cannot be queried."
                )
            vintages[ds_key] = entry.source_vintage
            retrievals[ds_key] = entry.latest_retrieval_utc or "unknown"
            warnings.extend(entry.known_limitations)

        # Validate SQL read-only and allow-listed table references
        assert plan.sql is not None
        validate_spatial_sql(plan.sql, allowlisted_keys)

        # Register views and execute against real stored GeoParquet snapshots
        self._register_dataset_views(plan.selected_datasets)
        exec_res = self.engine.execute_spatial_sql(plan.sql, query_label=plan.intent_id)

        ds_citations = ", ".join(
            f"`{k}` (vintage `{vintages[k]}`, retrieved `{retrievals[k]}`)"
            for k in plan.selected_datasets
        )
        explanation = (
            f"Executed verified DuckDB Spatial SQL (`{plan.intent_id}`) across {ds_citations}. "
            f"Returned {exec_res['row_count']} row(s) in {exec_res['elapsed_ms']} ms "
            f"(stored CRS `{self.registry.manifest.default_stored_crs}`, metric CRS `{self.registry.manifest.default_metric_crs}`)."
        )

        return AIExecutionAuditRecord(
            audit_id=audit_id,
            timestamp_utc=ts_utc,
            user_question=question,
            status="EXECUTED",
            selected_datasets=plan.selected_datasets,
            source_vintages=vintages,
            retrieval_timestamps=retrievals,
            generated_sql=plan.sql,
            execution_engine="duckdb_spatial",
            stored_crs=self.registry.manifest.default_stored_crs,
            metric_crs=self.registry.manifest.default_metric_crs,
            population_method=plan.population_method,
            row_count=exec_res["row_count"],
            execution_ms=exec_res["elapsed_ms"],
            warnings_and_limitations=warnings,
            grounded_explanation=explanation,
            sample_rows=exec_res["rows"][:25],
        )

