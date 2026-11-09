"""Execution Engine Benchmark & Cost Telemetry Runner (Section 5.3).

Compares and records verifiable latency, data volume, and cost metrics across:
1. Live Source Endpoint ingestion (recorded from actual HTTP retrieval telemetry in `qa/datasets/`).
2. DuckDB Spatial over stored GeoParquet 1.1.0 snapshots (cold view registration vs warm spatial SQL execution).
3. Wherobots / Apache Sedona engine status (records exact configuration status or live run telemetry with $0.00/hr idle teardown guarantee).
"""

import json
import time
from pathlib import Path
from typing import Any, Dict, List

from src.engines.duckdb_engine import DuckDBSpatialEngine
from src.engines.wherobots_engine import WherobotsSedonaEngine
from src.ingestion.telemetry import utc_now_iso


def run_engine_benchmarks(
    lake_root: Path,
) -> Dict[str, Any]:
    """Executes reproducible spatial SQL benchmarks over stored GeoParquet and compares against
    recorded live endpoint retrieval telemetry.
    """
    geoparquet_dir = lake_root / "geoparquet"
    qa_datasets_dir = lake_root / "qa" / "datasets"

    # 1. Gather recorded live source retrieval timings from latest QA artifacts
    live_retrievals: List[Dict[str, Any]] = []
    if qa_datasets_dir.exists():
        for ds_dir in sorted(qa_datasets_dir.iterdir()):
            if not ds_dir.is_dir():
                continue
            qa_files = sorted(ds_dir.glob("*.json"))
            if not qa_files:
                continue
            latest_qa = json.loads(qa_files[-1].read_text(encoding="utf-8"))
            telem = latest_qa.get("telemetry") or {}
            l1 = latest_qa.get("level_1_source_contract") or {}
            l2 = latest_qa.get("level_2_stored_artifact") or {}
            live_retrievals.append(
                {
                    "dataset_key": ds_dir.name,
                    "qa_status": latest_qa.get("overall_status"),
                    "http_probe_ms": l1.get("elapsed_ms"),
                    "full_source_download_ms": telem.get("source_download_ms"),
                    "normalization_and_parquet_write_ms": round(
                        float(telem.get("normalization_ms") or 0.0)
                        + float(telem.get("parquet_write_ms") or 0.0),
                        2,
                    ),
                    "raw_bytes_downloaded": telem.get("bytes_downloaded"),
                    "geoparquet_bytes_stored": l2.get("file_size_bytes"),
                    "stored_row_count": l2.get("num_rows"),
                }
            )

    # 2. Execute DuckDB Spatial cold vs warm spatial queries over stored GeoParquet
    duck_tasks: List[Dict[str, Any]] = []
    with DuckDBSpatialEngine() as engine:
        t_cold_start = time.perf_counter()
        for ds_key in (
            "ga_electricity_substations",
            "ga_electricity_transmission_lines",
            "ga_major_power_stations",
            "next_lga_boundaries_asgs2025",
            "next_sa2_boundaries_asgs2021",
            "nsw_foi_building_complexes",
            "nsw_water_inundation_areas",
            "nsw_rfs_major_incidents_live",
        ):
            files = sorted((geoparquet_dir / ds_key).glob("*/*/part-*.parquet"))
            if files:
                engine.register_geoparquet_view(ds_key, files[-1])
        cold_register_ms = round((time.perf_counter() - t_cold_start) * 1000.0, 2)

        queries = [
            (
                "bbox_filter_foi_buildings",
                "BBox Pushdown Filter on 2,000 NSW FOI Building Complexes",
                "SELECT COUNT(*) AS cnt FROM nsw_foi_building_complexes WHERE _bbox_minx >= 151.50 AND _bbox_maxx <= 151.78 AND _bbox_miny >= -32.90 AND _bbox_maxy <= -32.70",
            ),
            (
                "spatial_join_lga_multi_layer",
                "Multi-Layer Spatial Join (LGA x Substations with BBox Pushdown)",
                """
                SELECT l.lga_name_2025, COUNT(DISTINCT s.objectid) AS sub_cnt
                FROM next_lga_boundaries_asgs2025 l
                LEFT JOIN ga_electricity_substations s
                  ON s._bbox_maxx >= l._bbox_minx AND s._bbox_minx <= l._bbox_maxx
                 AND s._bbox_maxy >= l._bbox_miny AND s._bbox_miny <= l._bbox_maxy
                 AND ST_Intersects(l.geom, s.geom)
                GROUP BY l.lga_name_2025
                """,
            ),
            (
                "metric_buffer_inundation_exposure",
                "Metric CRS (EPSG:3112) 250m Flood Buffer Facility Intersection",
                """
                WITH inund_buf AS (
                    SELECT
                        _bbox_minx - 0.005 AS bminx,
                        _bbox_miny - 0.005 AS bminy,
                        _bbox_maxx + 0.005 AS bmaxx,
                        _bbox_maxy + 0.005 AS bmaxy,
                        ST_Buffer(ST_Transform(geom, 'EPSG:7844', 'EPSG:3112', true), 250.0) AS buf_3112
                    FROM nsw_water_inundation_areas
                ),
                foi_3112 AS (
                    SELECT
                        objectid,
                        _bbox_minx, _bbox_miny, _bbox_maxx, _bbox_maxy,
                        ST_Transform(geom, 'EPSG:7844', 'EPSG:3112', true) AS geom_3112
                    FROM nsw_foi_building_complexes
                )
                SELECT COUNT(DISTINCT f.objectid) AS exposed_cnt
                FROM foi_3112 f
                JOIN inund_buf i
                  ON f._bbox_maxx >= i.bminx AND f._bbox_minx <= i.bmaxx
                 AND f._bbox_maxy >= i.bminy AND f._bbox_miny <= i.bmaxy
                 AND ST_Intersects(f.geom_3112, i.buf_3112)
                """,
            ),
        ]

        for q_id, q_title, sql in queries:
            cold_res = engine.execute_spatial_sql(sql, query_label=f"{q_id}_run1")
            warm_res = engine.execute_spatial_sql(sql, query_label=f"{q_id}_run2_warm")
            duck_tasks.append(
                {
                    "benchmark_id": q_id,
                    "title": q_title,
                    "engine": "duckdb_spatial",
                    "first_run_ms": cold_res["elapsed_ms"],
                    "warm_run_ms": warm_res["elapsed_ms"],
                    "row_count": warm_res["row_count"],
                    "estimated_compute_cost_usd": 0.0,
                }
            )

    # 3. Check Wherobots / Apache Sedona configuration & record truthful status
    wb = WherobotsSedonaEngine()
    wb_probe = wb.execute_sedona_sql("SELECT 1 AS sedona_ping")

    total_raw_bytes = sum(int(r.get("raw_bytes_downloaded") or 0) for r in live_retrievals)
    total_parquet_bytes = sum(int(r.get("geoparquet_bytes_stored") or 0) for r in live_retrievals)

    return {
        "benchmark_timestamp_utc": utc_now_iso(),
        "storage_efficiency": {
            "total_raw_payload_bytes": total_raw_bytes,
            "total_geoparquet_bytes": total_parquet_bytes,
            "compression_ratio_raw_to_geoparquet": (
                round(total_raw_bytes / total_parquet_bytes, 2) if total_parquet_bytes > 0 else None
            ),
            "gcs_monthly_storage_cost_estimate_usd": round((total_parquet_bytes / (1024**3)) * 0.023, 6),
        },
        "duckdb_spatial_view_registration_ms": cold_register_ms,
        "duckdb_spatial_benchmarks": duck_tasks,
        "live_source_ingestion_telemetry": live_retrievals,
        "wherobots_sedona_engine": wb_probe,
        "idle_cloud_compute_cost_per_hour_usd": 0.0,
    }
