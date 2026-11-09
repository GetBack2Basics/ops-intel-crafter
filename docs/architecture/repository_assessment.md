# Repository Assessment & Engineering Audit — `operational_intelligence_crafter`

**Generated:** 2026-11-09  
**Target Workspace:** `c:\Projects\operational_intelligence_crafter`  
**Inspected Repositories:**
1. `c:\Projects\aura_siting_crafter` ([GitHub](https://github.com/GetBack2Basics/aura_siting_crafter))
2. `c:\Projects\CheatSheets` ([GitHub](https://github.com/GetBack2Basics/CheatSheets))
3. `c:\Projects\nsw_public_transport_crafter` ([GitHub](https://github.com/GetBack2Basics/public_transport_crafter))
4. `c:\Projects\GeoLibre` (local monorepo reference)

---

## 1. Graphify Baseline Audit Results

Executed `c:\Projects\aura_siting_crafter\tools\graphify_analysis.py` via the AURA virtual environment (`c:\Projects\aura_siting_crafter\.venv\Scripts\python.exe`):
- **Secrets Detected:** `0`
- **Banned Legacy References:** `2` (self-references inside `tools/graphify_analysis.py` and `tests/lint/test_no_place_names.py`)
- **Import Dependency Graph:** Confirmed clean decoupling between `src/Ingestion_v2/`, `src/geolibre_proxy/`, and `tools/`.

---

## 2. Existing Reusable Modules & Their Locations

| Source Repository | Module / File Path | Reusability Assessment | Target Location in `operational_intelligence_crafter` |
|---|---|---|---|
| `aura_siting_crafter` | `src/Ingestion_v2/publish_gate.py` | **Direct Reuse (with minor extension)**: Blocks `.env`, credentials, private keys, and unverified redistribution licences (`licence.redistribution is True`) before any public GCS upload. | `src/validation/publish_gate.py` |
| `aura_siting_crafter` | `src/Ingestion_v2/etl_telemetry_v2.py` | **Direct Reuse**: High-resolution stage timer and JSON audit log emitter. | `src/ingestion/telemetry.py` |
| `aura_siting_crafter` | `tests/lint/test_no_mock_data.py` | **Direct Reuse + Strengthen**: AST/regex gate banning `sampleFeatures`, `mock_data`, `dummy_records`, `placeholder_count`, and hardcoded bbox arrays. Will be extended to ban hardcoded `AUTHORITATIVE_COUNTS` and `_seed_authoritative_lake_dataset_if_needed`. | `tests/zero_mock/test_no_mock_data.py` |
| `aura_siting_crafter` | `tests/lint/test_no_secrets.py` | **Direct Reuse**: Scans all `.py`, `.html`, `.json`, `.md` files for leaked API keys, tokens, and `.env` values. | `tests/zero_mock/test_no_secrets.py` |
| `aura_siting_crafter` | `src/geolibre_frontend/js/geolibre-layer-limiter.js` | **Direct Reuse**: Official `@geolibre/layer-limiter` viewport feature limiter with explicit cap reporting (never silent truncation). | `src/geolibre/js/geolibre-layer-limiter.js` |
| `nsw_public_transport_crafter` | `src/Ingestion/gcs_manager.py` & `src/Ingestion/lake_io.py` | **Direct Reuse (Parameterized)**: Clean GCS upload/download/list helpers using `google.cloud.storage` with `TemporaryDirectory` staging and configurable bucket/project env vars. | `src/ingestion/gcs_storage.py` |
| `aura_siting_crafter` | `tools/graphify_analysis.py` | **Direct Reuse (Adapted for new repo)**: AST dependency, SQL table, and secret scanner. | `tools/graphify_analysis.py` |

---

## 3. Existing Components Requiring Adaptation (and Defects Found During Inspection)

### 3.1 `aura_siting_crafter/config/dataset_manifest_v2.json` & `config/datasets/nsw/*.json`
* **What was found:**
  1. **Storage Coupling:** Configured for `havasu.iceberg` (`wherobots://fgsdb/aura_siting/...`) and `s3://wherobots-user-storage/...` rather than versioned GCS GeoParquet (`gs://<bucket>/geoparquet/<dataset_key>/<source_vintage>/<retrieval_timestamp>/`).
  2. **Null Licences:** 30 of 36 entries in `dataset_manifest_v2.json` have `licence.name: null` and `licence.redistribution: null`.
  3. **Duplicate / Mislabelled Endpoints ("Right Church, Wrong Pew" Trap #13):**
     - `national_healthcare_nhsd_v2` and `national_schools_acara_v2` both point to the exact same NSW endpoint (`NSW_Features_of_Interest_Category/FeatureServer/3`).
     - `national_cadastre_gnaf_v2` points to `NSW_Land_Parcel_Property_Theme/FeatureServer/8` (NSW-only, not national).
     - `qld_transmission_grid_v2` and `sa_transmission_grid_electranet_v2` point to the GA national `Electricity_Infrastructure/MapServer/2` rather than state distribution feeds.
  4. **Hallucinated v1 Endpoints (Trap #11 / #15):**
     - `config/datasets/nsw/nsw_flood_hazard.json`, `nsw_dams_safety_tsf.json`, and `nsw_drinking_water_catchments.json` reference `https://services.slip.nsw.gov.au/...` — a non-existent domain conflating WA's SLIP (`services.slip.wa.gov.au`) with NSW Spatial Services.
* **Adaptation required:** Build `config/dataset_manifest.json` from scratch with strict schema validation, separating dataset classification (`static_authoritative`, `periodically_refreshed_authoritative`, `live_operational_feed`, `open_community`, `derived`, `scenario_input`) and requiring verified endpoint probes before marking any source `VERIFIED`.

### 3.2 `aura_siting_crafter/tools/generate_qa_report.py`
* **What was found:**
  - Lines 230–263 contain a hardcoded `AUTHORITATIVE_COUNTS` dictionary (`"national_cadastre_gnaf_v2": 3357016`, etc.) with a fallback of `live_count or 1000`.
  - Lines 284–290 set `source_count_val = live_count if live_count is not None else s3_count` and default `delta_pct = "100%"`, meaning an unreachable endpoint or un-ingested dataset still displays a green `100%` sync badge!
* **Adaptation required:** Replace completely in `src/validation/qa_report.py` and `tools/run_qa.py`. All counts, hashes, bounding boxes, geometry validity rates, and CRS metadata must be read from actual Level 1 (live source contract), Level 2 (stored GeoParquet footer/metadata), and Level 3 (reconciliation) JSON artifacts on GCS/disk. Untested or unreachable sources must explicitly render `NOT TESTED` or `FAIL`.

### 3.3 `aura_siting_crafter/src/Ingestion_v2/dataset_loader_v2.py`
* **What was found:**
  - Silently drops invalid geometries without recording invalid/null geometry counts for Level 2/3 reconciliation.
  - Falls back to writing a `.json` file if `geopandas` is missing, while the caller expects `.parquet`.
  - Overwrites output paths instead of writing immutable `<source_vintage>/<retrieval_timestamp>/part-*.parquet` snapshots alongside raw payloads (`raw/<dataset_key>/<retrieval_timestamp>/`).
* **Adaptation required:** Split into `src/ingestion/live_fetch.py`, `src/ingestion/snapshot_ingest.py`, and `src/ingestion/geoparquet_writer.py` with full GeoParquet 1.1.0 / 2.0 metadata validation (`geo` schema metadata key, CRS PROJJSON, bbox column/metadata, SHA-256 content hash, and GCS generation ID).

### 3.4 `aura_siting_crafter/src/geolibre_proxy/ai_spatial_agent.py` & `main.py`
* **What was found:**
  - `ai_spatial_agent.py` is hardcoded to data-centre siting rules and silently injects default thresholds (`dist_to_substation_km <= 1.5`, `area_ha >= 15.0`, `dist_to_sensitive_km >= 1.0`, `slope_pct <= 2.5`) whenever the user does not specify a number.
  - Queries a single hardcoded S3 path (`s3://wherobots-user-storage/aura_siting/candidates/datacenter_candidates_national.parquet`).
* **Adaptation required:** Re-architect into `src/ai/spatial_agent.py`, `src/ai/query_planner.py`, `src/ai/sql_validator.py`, and `src/ai/execution_audit.py`. Remove all siting defaults; enforce ambiguity detection that halts and returns clarifying questions instead of inventing thresholds; validate AST/SQL against the allow-listed catalogue tables and columns; execute on DuckDB Spatial or Wherobots/Sedona; and persist full execution audit logs.

### 3.5 `nsw_public_transport_crafter/src/Ingestion/catalog_router.py` & `src/Routing/valhalla_client.py`
* **What was found:**
  - `catalog_router.py` contains `_seed_authoritative_lake_dataset_if_needed()` (lines 1573–1852), which fabricates small synthetic DataFrames of stops, routes, and traffic hazards when `TFNSW_API_KEY` is absent.
  - `valhalla_client.py` (lines 1348–1378) silently substitutes circular Euclidean buffers (`pt_mga.buffer(distance_meters)`) when the Valhalla routing daemon is offline.
* **Adaptation required:** Transfer the clean `GcsQueryEngine` (`src/Query/gcs_query_engine.py`) fail-closed pattern (`ALLOW_LOCAL_LAKE=1` opt-in), and strictly prohibit synthetic seed fallbacks or silent Euclidean buffer substitution in `src/analysis/accessibility.py`. If Valhalla is unavailable, accessibility analysis must either spin up the ephemeral Valhalla container/VM or report `VALHALLA_UNAVAILABLE` with explicit provenance.

### 3.6 `aura_siting_crafter/tools/build_project_package.py` & `src/geolibre_frontend/docs/qa/geolibre_qa_inspect.html`
* **What was found:**
  - `build_project_package.py` embeds GeoJSON inline into HTML, which works for small layers, but loads MapLibre GL JS/CSS from `https://unpkg.com/maplibre-gl@3.6.2/...` and basemap tiles from `https://tiles.openfreemap.org/styles/liberty`. It fails when opened without internet access.
* **Adaptation required:** Build `src/exports/map_package_builder.py` to bundle local `maplibre-gl.js`, `maplibre-gl.css`, `pmtiles.js`, local font glyphs/sprites, a bbox-clipped local basemap (PMTiles or bundled vector/raster basemap layers), `data/*.geojson`, and `qa/*.json` so the Map-in-a-Box works 100% offline.

---

## 4. Dependencies & Deployment Assumptions

- **Python Environments Available Locally:**
  - `c:\Projects\aura_siting_crafter\.venv` (Python 3.12 with `geopandas==1.2.0`, `pyarrow==26.0.0`, `pyproj==3.8.0`, `shapely==2.2.0`, `pyogrio==0.13.0`, `google-cloud-storage==3.17.1`, `wherobots-python-dbapi==0.30.1`, `fastapi==0.162.0`, `pydantic==2.14.2`, `pytest==9.2.0`).
  - `c:\Projects\nsw_public_transport_crafter\.venv` (Python 3.12 with `duckdb==2.0.0`, `gcsfs==2026.10.1`, `geopandas==1.2.0`, `pyarrow==26.0.0`).
  - We will configure a dedicated `.venv` (or unified `requirements.txt` / `pyproject.toml`) in `c:\Projects\operational_intelligence_crafter` combining `duckdb`, `geopandas`, `pyarrow`, `shapely`, `pyproj`, `google-cloud-storage`, `wherobots-python-dbapi`, `fastapi`, `uvicorn`, `pydantic`, `requests`, `httpx`, `pytest`, and `jsonschema`.
- **CRS Standards:**
  - Canonical stored GeoParquet CRS: `EPSG:7844` (GDA2020 geographic) or documented native CRS where preserved, with metric calculations performed in `EPSG:3112` (GDA94 / Geoscience Australia Lambert) or `EPSG:9473` (GDA2020 / Australian Albers) and RFC 7946 GeoJSON exports strictly in `EPSG:4326` (WGS84 lon/lat).
- **Cloud & Compute Rules:**
  - GCS is the canonical spatial data lake (no persistent query-result cache).
  - Before any `gcloud`, `gsutil`, `bq`, or GCS SDK operation, verify `core/project` and `billing/quota_project` match the target project.
  - All Wherobots/Sedona sessions and ephemeral routing VMs must be torn down immediately after execution and verified stopped (`$0.00/hr` idle cost).

---

## 5. Existing QA and Zero-Mock Rules Adopted

1. **Zero-Mock AST Gate (`tests/zero_mock/test_no_mock_data.py`):** Fails CI on any synthetic coordinate array, `sampleFeatures`, `mock_data`, hardcoded count dictionary, or silent fallback generator.
2. **Three-Tier Validation (`src/validation/`):**
   - **Level 1 (Source Contract):** HTTP status, Content-Type verification (rejecting `text/html` landing/block pages), ArcGIS `200 OK` embedded `{"error": ...}` inspection, geometry type contract match, and pagination handling.
   - **Level 2 (Stored Artifact):** Physical file existence, Parquet magic bytes + footer inspection, GeoParquet `"geo"` metadata validation, CRS presence, valid bounding box, feature count, schema recording, invalid/null geometry counts (`ST_IsValid`), SHA-256 hash, and GCS object generation ID.
   - **Level 3 (Source-to-Storage Reconciliation):** Explicit comparison of source vs stored feature counts, bounding boxes, attribute schemas, duplicate IDs, and geometry validity, recording expected deltas from filtering/cleaning and outputting strict `PASS`, `WARNING`, `FAIL`, `NOT TESTED`, or `NOT APPLICABLE` statuses.

---

## 6. Proposed New Modules in `operational_intelligence_crafter`

```text
c:\Projects\operational_intelligence_crafter\
├── config/
│   ├── dataset_manifest.json
│   ├── analysis_templates/
│   └── benchmark_profiles/
├── docs/
│   └── architecture/
│       ├── repository_assessment.md
│       └── implementation_plan.md
├── src/
│   ├── catalogue/
│   │   ├── dataset_registry.py
│   │   ├── manifest_loader.py
│   │   └── schema_inspector.py
│   ├── ingestion/
│   │   ├── source_connectors/
│   │   │   ├── arcgis_connector.py
│   │   │   ├── wfs_connector.py
│   │   │   ├── osm_connector.py
│   │   │   └── file_download_connector.py
│   │   ├── live_fetch.py
│   │   ├── snapshot_ingest.py
│   │   ├── geoparquet_writer.py
│   │   ├── gcs_storage.py
│   │   └── telemetry.py
│   ├── validation/
│   │   ├── publish_gate.py
│   │   ├── source_contracts.py
│   │   ├── geoparquet_validation.py
│   │   ├── geometry_validation.py
│   │   ├── reconciliation.py
│   │   └── qa_report.py
│   ├── engines/
│   │   ├── duckdb_engine.py
│   │   ├── wherobots_engine.py
│   │   └── benchmark_runner.py
│   ├── analysis/
│   │   ├── exposure.py
│   │   ├── population_methods.py
│   │   ├── accessibility.py
│   │   ├── isolation.py
│   │   └── infrastructure_dependencies.py
│   ├── ai/
│   │   ├── spatial_agent.py
│   │   ├── query_planner.py
│   │   ├── sql_validator.py
│   │   └── execution_audit.py
│   ├── exports/
│   │   ├── geojson_export.py
│   │   ├── geoparquet_export.py
│   │   └── map_package_builder.py
│   ├── geolibre/
│   │   ├── project_config.py
│   │   ├── map_layer_catalog.py
│   │   └── qa_inspector.py
│   └── api/
│       └── main.py
├── tools/
│   ├── graphify_analysis.py
│   ├── ingest_dataset.py
│   ├── run_qa.py
│   ├── build_map_package.py
│   └── run_benchmarks.py
└── tests/
    ├── unit/
    ├── integration/
    ├── data_quality/
    ├── zero_mock/
    └── offline_package/
```

---

## 7. Known Gaps & Unverified Assumptions

1. **Target GCP Project & GCS Bucket Name:** Must be confirmed with the user (do not hardcode `aura-siting-crafter` or `nsw-transit-spatial-crafter`).
2. **NExT Layer Family Access & Vintages:**
   - Need to verify live public REST/download URLs for the NExT baseline layers (Aged care services, Declared public/private hospitals, Major power stations, ASGS 2025 LGA boundaries, ASGS 2021 UCL/SAL, ABS National Population Grid, G-NAF May 2026) and confirm whether any NExT layers reside in an existing authenticated portal/bucket or public ABS/GA/Geoscape endpoints.
3. **Wherobots GCS Integration Mechanism:**
   - Wherobots Cloud defaults to `wherobots://` or `s3://`; reading `gs://` directly from Wherobots/Sedona requires verifying whether GCS HMAC keys (`fs.gs.*` / S3-interoperability) or signed HTTPS URLs / service account credentials are configured in the Wherobots runtime.
4. **Live Outage Feeds (Ergon Energy / Energex / State DNSPs):**
   - Public outage feeds often use anti-scraping middleware or dynamic GeoJSON/KML endpoints; live reachability and rate limits must be probed and documented (recording `FAIL` or `BLOCKED` if restricted, per Section 4.6).
5. **Valhalla Routing Instance:**
   - Need to confirm whether to use the existing GCE `valhalla-tuffs` (`australia-southeast1-b`) on-demand VM, a local Docker container, or a public/local Valhalla endpoint for repeatable accessibility benchmarking.

