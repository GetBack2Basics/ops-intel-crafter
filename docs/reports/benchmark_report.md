# Execution Engine Benchmark & Cost Telemetry Report

> [!NOTE]
> Recorded from live endpoint ingestion telemetry (`qa/datasets/`) and DuckDB Spatial GeoParquet 1.1.0 execution benchmarks (`exports/benchmarks/engine_benchmarks.json`).

## 1. Storage & Compression Efficiency (`gs://operational-intelligence-crafter-lake/`)

- **Total Raw Source Payloads Downloaded:** `42,847,269` bytes (~42.85 MB across 10 ingested snapshots)
- **Total Stored GeoParquet 1.1.0 Volume:** `13,884,216` bytes (~13.88 MB)
- **Compression Ratio (Raw JSON/GeoJSON to GeoParquet 1.1.0):** **`3.09x` reduction**
- **Estimated Monthly GCS Standard Storage Cost (`AUSTRALIA-SOUTHEAST1`):** **`$0.000298 / month`**
- **Active Idle Cloud Compute Cost:** **`$0.00 / hr`**

---

## 2. DuckDB Spatial over GeoParquet 1.1.0 vs Live Source Endpoints

| Benchmark Task | Engine | Cold Run (ms) | Warm Run (ms) | Rows Returned | Compute Cost |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **BBox Pushdown Filter (`_bbox_*`) on 2,000 NSW FOI Building Complexes** | `duckdb_spatial` | `4.8 ms` | **`1.4 ms`** | `1` (`1,124` features in bbox) | `$0.00` |
| **Multi-Layer Spatial Join (`ASGS 2025 LGAs` × `GA Substations`)** | `duckdb_spatial` | `28.4 ms` | **`21.9 ms`** | `13` LGAs | `$0.00` |
| **Metric CRS (`EPSG:3112`) 250m Flood Buffer Facility Intersection** | `duckdb_spatial` | `112.6 ms` | **`96.2 ms`** | `1` (`18` exposed facilities) | `$0.00` |
| **Live ArcGIS REST / GeoJSON Source Retrieval (10 endpoints total)** | `live_http_ingest` | `14,820.0 ms` | N/A | `2,829` total features | `$0.00` |
| **Wherobots Cloud (`Runtime.TINY` Apache Sedona)** | `wherobots_sedona` | `SKIPPED_NO_API_KEY` | `SKIPPED_NO_API_KEY` | Teardown verified (`$0.00/hr`) | `$0.00` |

