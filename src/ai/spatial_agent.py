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
        """Registers query views from canonical gs:// snapshots (cloud-first, no local staging)."""
        registered = self.engine.register_catalogue_views(list(dataset_keys))
        missing = [k for k in dataset_keys if k not in registered]
        if missing:
            raise FileNotFoundError(
                "Dataset(s) have no stored GeoParquet snapshot (local or GCS): " + ", ".join(missing)
            )

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

    def assess_uploaded_spatial_file(
        self,
        file_path_or_bytes: Any,
        filename: str,
        assets: Optional[list[dict[str, Any]]] = None,
        radii_km: Optional[dict[str, float]] = None,
    ) -> dict[str, Any]:
        """Parses user-uploaded KMZ/KML/GeoJSON/Shapefile and generates cyclone hazard zone asset intelligence."""
        from src.analysis.spatial_uploader import (
            assess_asset_in_cyclone,
            build_cyclone_hazard_zones,
            generate_cyclone_intelligence_reply,
            parse_uploaded_spatial_file,
        )

        geo = parse_uploaded_spatial_file(file_path_or_bytes, filename)
        zones = build_cyclone_hazard_zones(geo, radii_km=radii_km)

        # Default real Australian critical assets along the track (QLD, SA, NSW Riverina)
        target_assets = assets or [
            {"asset_id": "SUB_WAGGA", "asset_name": "Wagga Wagga 132kV Transmission Substation", "lat": -35.12, "lon": 147.37},
            {"asset_id": "HOSP_RIV", "asset_name": "Riverina Base Referral Hospital (Wagga Wagga)", "lat": -35.11, "lon": 147.35},
            {"asset_id": "GAS_MOOMBA", "asset_name": "Moomba Gas & Energy Processing Hub (SA)", "lat": -28.10, "lon": 140.20},
            {"asset_id": "SUB_BHILL", "asset_name": "Broken Hill Regional Transmission Substation", "lat": -31.95, "lon": 141.46},
        ]

        evaluated_assets = [
            assess_asset_in_cyclone(
                asset_id=a.get("asset_id", a.get("id", f"A_{i}")),
                asset_name=a.get("asset_name", a.get("name", "Unnamed Asset")),
                lat=float(a.get("latitude", a.get("lat", 0.0))),
                lon=float(a.get("longitude", a.get("lon", 0.0))),
                cyclone_geojson=geo,
                radii_km=radii_km,
            )
            for i, a in enumerate(target_assets)
        ]

        reply = generate_cyclone_intelligence_reply(geo, evaluated_assets)
        return {
            "status": "SUCCESS",
            "parsed_geojson": geo,
            "hazard_zones_geojson": zones,
            "reply": reply,
            "evaluated_assets": evaluated_assets,
        }


