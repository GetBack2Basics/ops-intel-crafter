# Operational Intelligence Crafter — Emergency Spatial Intelligence Lakehouse

> [!WARNING]
> **Analytical Demonstration & Research Prototype Only:** This system is an engineering proof of concept demonstrating multi-scale emergency spatial intelligence over Google Cloud Storage (GCS) GeoParquet 1.1.0, DuckDB Spatial, Wherobots/Sedona, and MapLibre. **Do not use for operational emergency warning, dispatch, or life-safety decisions.**

---

## Live GCS Hosted Deliverables (`operational-intelligence-crafter`)

- **Emergency Spatial Intelligence Workbench (Blank-on-Start Progressive Workflow):**  
  https://storage.googleapis.com/operational-intelligence-crafter-lake/index.html
- **3-Level Data Validation & QA Dashboard (9 `PASS`, 1 `WARNING`, 1 `FAIL`):**  
  https://storage.googleapis.com/operational-intelligence-crafter-lake/qa/index.html
- **MapLibre Per-Dataset Source Inspector:**  
  https://storage.googleapis.com/operational-intelligence-crafter-lake/qa/inspect.html
- **Air-Gapped Offline Map-in-a-Box (`hunter_flood_emergency_pack`):**  
  https://storage.googleapis.com/operational-intelligence-crafter-lake/map_packages/hunter_flood_emergency_pack/index.html
- **RFC 7946 GeoJSON Deliverables (QGIS & GeoLibre Compatible):**
  - [1 km² NExT Population Comparison GeoJSON](https://storage.googleapis.com/operational-intelligence-crafter-lake/exports/hunter_population_grid_comparison/result.geojson)
  - [Substation 5km Flood Dependency GeoJSON](https://storage.googleapis.com/operational-intelligence-crafter-lake/exports/hunter_substation_flood_dependency/result.geojson)
  - [Allow-Listed Dataset Manifest JSON](https://storage.googleapis.com/operational-intelligence-crafter-lake/manifests/dataset_manifest.json)

---

## Key Capabilities Implemented

1. **GCS GeoParquet 1.1.0 Spatial Data Lake (`gs://operational-intelligence-crafter-lake/`):**
   - Immutable timestamped object layout (`geoparquet/<dataset_key>/<source_vintage>/<retrieval_timestamp>/part-00000.parquet`) with GCS object generation lineage, SHA-256 hashes, and zero query-result caching.
   - Stored CRS normalized to `EPSG:7844` (GDA2020), metric buffers/areas computed in `EPSG:3112` (Geoscience Australia Lambert), and exports in `EPSG:4326` (RFC 7946 WGS84).
2. **Three-Level Anti-Mock Data Validation (`src/validation/`):**
   - **Level 1 (Source Contract):** Verifies HTTP status, content type, and rejects HTTP 200 responses containing embedded error payloads (e.g., `nsw_emergency_management_restricted` returning ArcGIS error `499: Token Required`).
   - **Level 2 (Stored GeoParquet Artifact):** Verifies Parquet magic bytes, footer, `"geo"` metadata, CRS, bounding boxes, and geometry validity.
   - **Level 3 (Source-to-Storage Reconciliation):** Reconciles stored row counts against live `returnCountOnly=true` source counts without ever claiming false 100% reconciliation.
3. **Controlled NExT 1 km² Population Representation Comparison (`src/analysis/population_methods.py`):**
   - Compares **Method A** (cell-centroid `ST_Contains`), **Method B** (1 km² cell polygon `ST_Intersects` separating interior vs boundary-straddling cells), and **Method C** (area-weighted proportional estimate in `EPSG:3112` explicitly labelled as a uniform density assumption) across 4 geometry regimes.
4. **Catalogue-Grounded AI Spatial SQL Planner (`src/ai/`):**
   - Enforces read-only `SELECT` over allow-listed catalogue views, prompts for clarification when Population Method A/B/C is omitted, and refuses uncatalogued telemetry requests.

---

## Reproducible Commands

```powershell
# 1. Run AST & Zero-Mock / Zero-Secret verification
& .\.venv\Scripts\python.exe tools\graphify_analysis.py

# 2. Run full 20-test suite (zero-mock, unit, data quality, integration, offline package)
& .\.venv\Scripts\python.exe -m pytest tests -v

# 3. Rebuild multi-scale analyses, exports, and offline Map-in-a-Box
& .\.venv\Scripts\python.exe tools\build_workbench_and_packs.py

# 4. Audit canonical GCS artifacts, rebuild QA reports, and publish web deliverables
#    (cloud-first: no local data/lake staging is read or written)
& .\.venv\Scripts\python.exe tools\publish_to_gcs.py
```

