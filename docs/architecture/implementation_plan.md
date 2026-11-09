# Implementation Plan & Backlog — `operational_intelligence_crafter`

**Project:** Emergency Spatial Intelligence — GCS GeoParquet, Wherobots and GeoLibre  
**Date:** 2026-11-09  
**Status:** Phase 1 Complete (Assessment & Architecture) — Ready for Intake Confirmation & Phase 2/3 Execution

---

## 1. Proposed Emergency Spatial Dataset Catalogue

Every dataset in `config/dataset_manifest.json` is classified into one of six source categories:
- `static_authoritative`
- `periodically_refreshed_authoritative`
- `live_operational_feed`
- `open_community`
- `derived`
- `scenario_input`

> **Anti-Hallucination Note:** Endpoints below are recorded from the AURA v2 manifest audit and official Australian government spatial portals (Geoscience Australia, ABS Geoservices, NSW Spatial Services, QSpatial, Vicmap, SLIP WA). No endpoint is marked `VERIFIED` in the manifest until Level 1 (`src/validation/source_contracts.py`) executes a live network probe and records the HTTP status, `Content-Type`, schema, CRS, and feature count.

### 1.1 NExT Baseline & Core National Authoritative Layers

| Dataset Key | Title | Category | Source Agency | Candidate Endpoint / Source | Vintage | Target CRS |
|---|---|---|---|---|---|---|
| `next_lga_boundaries_asgs2025` | Local Government Areas (ASGS Ed 3 / 2025) | `periodically_refreshed_authoritative` | ABS | `https://geo.abs.gov.au/arcgis/rest/services/ASGS2025/LGA/MapServer/0` (verify exact ASGS 2025/2021 layer) | ASGS 2025 | `EPSG:7844` |
| `next_ucl_asgs2021` | Urban Centres and Localities (UCL) | `static_authoritative` | ABS | `https://geo.abs.gov.au/arcgis/rest/services/ASGS2021/UCL/MapServer/0` | ASGS 2021 | `EPSG:7844` |
| `next_sal_asgs2021` | Suburbs and Localities (SAL) | `static_authoritative` | ABS | `https://geo.abs.gov.au/arcgis/rest/services/ASGS2021/SAL/MapServer/0` | ASGS 2021 | `EPSG:7844` |
| `next_population_grid_centroids` | Australian Population Grid (1 km² Centroid Points — Method A) | `static_authoritative` | ABS / NExT | ABS 1 km² Population Grid GeoPackage/ArcGIS service (centroids derived/verified against grid cells) | 2025 / ABS Grid | `EPSG:7844` |
| `next_population_grid_cells` | Australian Population Grid (1 km² Cell Polygons — Methods B & C) | `static_authoritative` | ABS | ABS 1 km² Population Grid (`EPSG:3577` / `EPSG:7844` polygon grid) | 2025 / ABS Grid | `EPSG:7844` |
| `next_gnaf_addresses` | Geoscape G-NAF National Address Points | `periodically_refreshed_authoritative` | Geoscape / data.gov.au | Geoscape G-NAF / state address FeatureServers | May 2026 | `EPSG:7844` |
| `next_major_power_stations` | National Major Power Stations | `periodically_refreshed_authoritative` | Geoscience Australia | `https://services.ga.gov.au/gis/rest/services/Electricity_Infrastructure/MapServer/0` | GA Current | `EPSG:7844` |
| `national_electricity_transmission_lines` | National Electricity Transmission Lines (>=66kV) | `periodically_refreshed_authoritative` | Geoscience Australia | `https://services.ga.gov.au/gis/rest/services/Electricity_Infrastructure/MapServer/2` | GA Current | `EPSG:7844` |
| `national_electricity_substations` | National Electricity Substations | `periodically_refreshed_authoritative` | Geoscience Australia | `https://services.ga.gov.au/gis/rest/services/Electricity_Infrastructure/MapServer/1` | GA Current | `EPSG:7844` |
| `next_public_hospitals` | Declared Public Hospitals | `periodically_refreshed_authoritative` | AIHW / NHSD / State Health | AIHW / State Features of Interest Health Services (to be verified per jurisdiction) | Current | `EPSG:7844` |
| `next_private_hospitals` | Declared Private Hospitals | `periodically_refreshed_authoritative` | AIHW / NHSD / State Health | AIHW / State Features of Interest Health Services | Current | `EPSG:7844` |
| `next_aged_care_services` | Aged Care Services | `periodically_refreshed_authoritative` | Dept of Health & Aged Care / GEN | GEN Aged Care Service list / geocoded authoritative extract | Current | `EPSG:7844` |
| `national_cyclone_hazard_tcha` | Tropical Cyclone Hazard Assessment (TCHA18) | `static_authoritative` | Geoscience Australia | `https://services.ga.gov.au/gis/rest/services/Tropical_Cyclone_Hazard_Assessment_2018/MapServer/1` | 2018 | `EPSG:7844` |
| `national_seismic_hazard_nsha` | National Seismic Hazard Assessment (NSHA18) | `static_authoritative` | Geoscience Australia | `https://services.ga.gov.au/gis/rest/services/National_Seismic_Hazard_Assessment_2018/MapServer/0` | 2018 | `EPSG:7844` |
| `national_mobile_coverage` | ACCC / Govt Mobile Coverage Maps (3G/4G/5G Outdoor Predicted) | `periodically_refreshed_authoritative` | Dept of Infrastructure / Carriers | data.gov.au Mobile Black Spot & Carrier Predicted Coverage layers | Current | `EPSG:7844` |

### 1.2 State & Regional Authoritative Layers (NSW, QLD, VIC, WA, SA, TAS)

| Dataset Key | State | Title | Category | Candidate Endpoint |
|---|---|---|---|---|
| `nsw_rfs_bushfire_prone_land` | NSW | NSW Bush Fire Prone Land | `periodically_refreshed_authoritative` | `https://portal.spatial.nsw.gov.au/server/rest/services/NSW_Emergency_Management_Category/FeatureServer/0` |
| `nsw_coastal_inundation_water` | NSW | NSW Water & Coastal Inundation Extent | `periodically_refreshed_authoritative` | `https://portal.spatial.nsw.gov.au/server/rest/services/NSW_Water_Theme/FeatureServer/7` |
| `nsw_landslide_susceptibility` | NSW | NSW Landslide & Slope Susceptibility | `static_authoritative` | `https://portal.spatial.nsw.gov.au/server/rest/services/NSW_Land_Parcel_Property_Theme/FeatureServer/7` |
| `nsw_cadastre_lots` | NSW | NSW Cadastral Parcel Fabric | `periodically_refreshed_authoritative` | `https://portal.spatial.nsw.gov.au/server/rest/services/NSW_Land_Parcel_Property_Theme/FeatureServer/8` |
| `nsw_foi_health_education` | NSW | NSW Features of Interest (Hospitals, Schools, Emergency Services) | `periodically_refreshed_authoritative` | `https://portal.spatial.nsw.gov.au/server/rest/services/NSW_Features_of_Interest_Category/FeatureServer/3` |
| `nsw_live_traffic_hazards` | NSW | TfNSW Live Traffic Hazards & Road Closures | `live_operational_feed` | `https://api.transport.nsw.gov.au/v1/live-traffic/hazards` (or NSW RFS Fires Near Me GeoJSON `https://www.rfs.nsw.gov.au/feeds/firesNearMe.json`) |
| `qld_landslide_hazard` | QLD | QLD SPP Landslide Hazard Overlay | `static_authoritative` | `https://spatial-gis.information.qld.gov.au/arcgis/rest/services/GeoscientificInformation/SoilsAndLandResource/MapServer/51` |
| `qld_watercourses_barriers` | QLD | QLD Watercourses & Barriers | `periodically_refreshed_authoritative` | `https://spatial-gis.information.qld.gov.au/arcgis/rest/services/InlandWaters/WaterCoursesAndBodies/MapServer/33` |
| `qld_ergon_energex_outages` | QLD | Ergon Energy & Energex Distribution & Outage Feeds | `live_operational_feed` | Ergon/Energex public outage GeoJSON/ArcGIS endpoints (probed & recorded with actual status) |
| `vic_hydro_watercourses` | VIC | Vicmap Hydrography Watercourses | `periodically_refreshed_authoritative` | `https://opendata.maps.vic.gov.au/geoserver/wfs` (`open-data-platform:vmlite_hy_watercourse`) |
| `vic_landslide_susceptibility` | VIC | Vicmap Slope Stability Overlay | `static_authoritative` | `https://opendata.maps.vic.gov.au/geoserver/wfs` (`open-data-platform:shalld100_polygon`) |
| `wa_slip_transmission_grid` | WA | Western Power / Horizon Power Transmission Network | `periodically_refreshed_authoritative` | `https://services.slip.wa.gov.au/public/rest/services/SLIP_Public_Services/Infrastructure_and_Utilities/MapServer/75` |
| `tas_list_transmission_grid` | TAS | TasNetworks High-Voltage Transmission Network | `periodically_refreshed_authoritative` | `https://services.thelist.tas.gov.au/arcgis/rest/services/Public/Infrastructure/MapServer/4` |

### 1.3 Open Community & Routing Datasets

| Dataset Key | Title | Category | Source | Notes |
|---|---|---|---|---|
| `osm_au_roads_bridges` | OpenStreetMap Australia Roads & Bridges | `open_community` | Geofabrik Australia PBF (`https://download.geofabrik.de/australia-oceania/australia-latest.osm.pbf`) / regional GeoParquet extract | Static road/bridge geometry; explicitly NOT live traffic or road closure status. |
| `osm_au_buildings_facilities` | OpenStreetMap Buildings & Emergency POIs | `open_community` | Geofabrik Australia PBF / Overture Maps buildings extract | Versioned by OSM extract timestamp; ODbL attribution retained. |

---

## 2. First Three Datasets to Ingest (Phase 4 Milestone) & Why They Are Suitable

1. **Authoritative National Dataset:** `national_electricity_transmission_lines` (and `next_major_power_stations` from Geoscience Australia `Electricity_Infrastructure/MapServer`)
   - **Why suitable:** Confirmed public, zero-auth ArcGIS MapServer operated by Geoscience Australia (`services.ga.gov.au`); national coverage (~3,147 transmission line features + power stations); moderate payload size ideal for testing end-to-end Level 1 (ArcGIS count/schema probe), Level 2 (GeoParquet 1.1/2.0 metadata & geometry validation), and Level 3 (100% deterministic source-to-storage count & extent reconciliation).
2. **Authoritative State Dataset:** `nsw_rfs_bushfire_prone_land` or `nsw_coastal_inundation_water` (NSW Spatial Services `portal.spatial.nsw.gov.au`) + `next_lga_boundaries_asgs2025`
   - **Why suitable:** High-value emergency hazard polygon layer with rich attributes (`hydroname`, `classsubtype`, `Shape__Area`), exercising polygon validity repair (`ST_MakeValid`), pagination, and regional LGA spatial joins.
3. **Open OSM-Derived Dataset + Live Operational Feed:**
   - **OSM Stored GeoParquet:** `osm_hunter_roads_bridges` (extracted from Geofabrik Australia OSM PBF or regional extract for the Hunter/Newcastle test region, containing roads, bridges, and emergency facilities).
   - **Live Query-Time Endpoint:** NSW RFS Current Incidents GeoJSON (`https://www.rfs.nsw.gov.au/feeds/firesNearMe.json`) or live ArcGIS bbox query against NSW Features of Interest, retaining a timestamped snapshot in `gs://<bucket>/raw/<dataset_key>/<retrieval_timestamp>/` on every fetch.

---

## 3. First Local, Regional, and National Benchmark Queries

All benchmarks will run without any query-result cache, comparing:
1. **Live Source Retrieval + In-Memory Spatial Analysis**
2. **DuckDB Spatial against Stored GeoParquet (Local & GCS HTTPFS/PyArrow)**
3. **Wherobots / Apache Sedona against Stored GeoParquet**
4. **Optional BigQuery GIS External Table (BigLake GeoParquet) Comparison**

### 3.1 Local / Incident Scale Query
- **Workload:** Given an incident flood/bushfire hazard polygon in the Hunter Valley / Lake Macquarie (`bbox: [151.50, -33.15, 151.80, -32.70]`):
  1. Compute exposed population using all three controlled representations on identical inputs:
     - **Method A (NExT Centroid Baseline):** `ST_Contains(incident_geom, pop_centroid.geom)` -> cell count & sum of population.
     - **Method B (1 km² Cell Footprint Intersection):** `ST_Intersects(incident_geom, pop_cell.geom)` -> intersecting cell count, full-cell population sum, and boundary-straddling edge-case cells (where cell intersects hazard footprint but centroid falls outside).
     - **Method C (Area-Weighted Estimate):** `SUM(pop_cell.population * (ST_Area(ST_Intersection( ST_Transform(incident_geom, 'EPSG:3112'), ST_Transform(pop_cell.geom, 'EPSG:3112') )) / ST_Area(ST_Transform(pop_cell.geom, 'EPSG:3112'))))` — explicitly labelled as a uniform-density assumption.
  2. Identify exposed hospitals, aged care services, schools, power assets, and road bridges within the footprint, plus Valhalla drive-time accessibility / road closure isolation.

### 3.2 Regional / State Scale Query
- **Workload:** Across all LGAs in NSW (or the Hunter + Central Coast + Greater Sydney multi-LGA region) and multiple active hazard polygons:
  - Spatial join (`ST_Intersects`) of hazard footprints against LGA boundaries, population grid cells, transmission lines/substations, and road networks.
  - Aggregate exposed population (Methods A, B, C), critical facilities, and transmission line kilometres by `lga_code` and `lga_name`.

### 3.3 National Scale Query
- **Workload:** Continental multi-layer spatial aggregation across all 8 Australian states and territories:
  - Spatial join of national population grid cells and critical infrastructure (`national_electricity_transmission_lines`, `next_major_power_stations`, hospitals) against national cyclone wind regions (`national_cyclone_hazard_tcha`) and seismic hazard zones (`national_seismic_hazard_nsha`), grouped by state/territory and hazard class.

---

## 4. GCS Bucket & Project Configuration (No Deployment Until Approved)

### 4.1 Canonical GCS Layout
```text
gs://<BUCKET_NAME>/
    raw/
        <dataset_key>/<retrieval_timestamp>/source_payload.*
    geoparquet/
        <dataset_key>/<source_vintage>/<retrieval_timestamp>/part-00000.parquet
    manifests/
        datasets/<dataset_key>.json
        releases/<release_id>.json
    qa/
        datasets/<dataset_key>/<retrieval_timestamp>.json
        reports/<report_id>/
    exports/
        <analysis_id>/
            result.geojson
            result.parquet
            analysis_manifest.json
    map_packages/
        <package_id>/
            index.html
            data/
            assets/
            qa/
            manifest.json
            README.txt
```

### 4.2 Configuration Variables (`.env.example`)
- `OIC_GCP_PROJECT`: Target Google Cloud Project ID (verified against `gcloud config get-value core/project` and `billing/quota_project`).
- `OIC_GCS_BUCKET`: Target GCS bucket for the GeoParquet spatial data lake.
- `OIC_ALLOW_LOCAL_LAKE`: Explicit `0` or `1` flag (defaults to `0` in cloud mode; when `1` for local offline testing, logs an explicit provenance warning and uses the exact same directory structure under a local staging root).
- `WHEROBOTS_API_KEY`: Loaded strictly from `.env` (never committed).

---

## 5. Google Stitch Design Architecture (`web_dashboard` Shell)

All interactive HTML deliverables — the **Data QA & Quality Gates Hub** (`docs/qa/index.html`), the **GeoLibre Spatial QA Inspector** (`docs/qa/inspect.html`), and the **Emergency Spatial Intelligence Workbench** (`src/geolibre/`) — implement the Google Stitch Design Architecture (`https://stitch.withgoogle.com/preview/16679632945800137648?node-id=43b75c7a51594d42b646c7d152256adb`, `shell-type="web_dashboard"`):

### 5.1 Design Tokens & Colour Palette (Material 3 / Stitch Theme)
- **Primary & Brand Containers**:
  - `primary`: `#001026` | `primary-container`: `#0b2545` | `primary-fixed`: `#d5e3ff` | `on-primary-container`: `#778db2`
  - `secondary`: `#006973` | `secondary-container`: `#81f0ff` | `secondary-fixed-dim`: `#66d6e5`
  - `on-tertiary-container` (Warning / Amber Accent): `#d47300` | `error` (Fail / Alert): `#ba1a1a` | `error-container`: `#ffdad6`
- **Surfaces & Text**:
  - `surface`: `#faf8ff` | `surface-container-lowest`: `#ffffff` | `surface-container-low`: `#f2f3ff`
  - `surface-container`: `#eaedff` | `surface-container-high`: `#e2e7ff` | `surface-container-highest`: `#dae2fd`
  - `on-surface`: `#131b2e` | `on-surface-variant`: `#44474e` | `outline`: `#74777f` | `outline-variant`: `#c4c6cf`
- **Typography**:
  - **Headlines (`headline-xl` to `headline-sm`)**: `Space Grotesk` (`600`–`700` weight, tight tracking `-0.01em` to `-0.02em`)
  - **Body & Labels (`body-lg` to `label-sm`)**: `Plus Jakarta Sans` (`400`, `600`, `700`)
  - **Code, SQL, Hashes, Bboxes & Provenance (`mono`)**: `JetBrains Mono` (`400`, `500`)
  - **Icons**: Google `Material Symbols Outlined`

### 5.2 Layout & Component Hierarchy
1. **Fixed Left Sidebar (`aside.w-64.bg-surface-container-low`)**:
   - Brand header (`Emergency Spatial` / `Crafter Engine` with `crisis_alert` icon in `bg-primary-container`).
   - Primary navigation links (`.nav-link` with active state `bg-primary-container text-white`):
     - `01 Emergency Inquiry & AI Planner`
     - `02 Spatial SQL Workbench (DuckDB / Wherobots)`
     - `03 Interactive GeoLibre Map`
     - `04 NExT Population Representation (Methods A/B/C)`
     - `05 Engine Benchmarks & Cost Telemetry`
     - `06 Data QA & 3-Level Validation Hub` (`docs/qa/index.html`)
     - `07 Per-Dataset MapLibre QA Inspector` (`docs/qa/inspect.html`)
   - Footer status widget (`Lakehouse Sync: gs://operational-intelligence-crafter-lake` + local staging status badge).
2. **Dual-Tier Sticky Header (`header.fixed.top-0.left-64.right-0`)**:
   - Tier 1 (`h-16`): Global dataset/LGA/hazard search bar, GCS Lakehouse connection badge, `Data QA Hub` button, and primary action button.
   - Tier 2 (`h-12 bg-surface-container-lowest`): Workflow step pills (`01 Catalogue`, `02 Level 1 Source`, `03 Level 2 GeoParquet`, `04 Level 3 Reconciliation`, `05 Map Inspector`) + live verification summary counters (`PASS`, `WARNING`, `FAIL`, `NOT TESTED`).
3. **Structured Panel Cards (`section.panel-card` with `.step-tag` & `.kpi-tile` / `.context-tile`)**:
   - KPI Quad tiles for dataset counts, Level 1–3 QA status breakdown, feature counts, and geometry validity rates.
   - Dark Navy (`#001026`) SQL & Provenance inspection blocks with `JetBrains Mono` syntax display.
   - Interactive MapLibre GL JS canvas (`rounded-xl overflow-hidden`) with floating glassmorphic HUD legend (`bg-surface-container-lowest/95 backdrop-blur-md`).

---

## 6. Live-Verified Initial Dataset Catalogue (Probed 2026-11-09)

Every candidate source below was live-probed prior to catalogue inclusion to prevent "Right Church, Wrong Pew" sublayer mismatches:

| Dataset Key | Scale | Category | Verified Endpoint | Verified Layer Name & Geometry | Verified Feature Count / Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `ga_electricity_substations` | National | `static_authoritative` | `.../Electricity_Infrastructure/MapServer/0` | `Power Substations` (`esriGeometryPoint`, `EPSG:7844`) | **2,764** features (HTTP 200) |
| `ga_major_power_stations` | National | `static_authoritative` | `.../Electricity_Infrastructure/MapServer/1` | `Major Power Stations` (`esriGeometryPoint`, `EPSG:7844`) | **379** features (HTTP 200) |
| `ga_electricity_transmission_lines` | National | `static_authoritative` | `.../Electricity_Infrastructure/MapServer/2` | `Electricity Transmission Lines` (`esriGeometryPolyline`, `EPSG:7844`) | **16,139** features (HTTP 200) |
| `ga_seismic_hazard_pga_10pct` | National | `static_authoritative` | `.../National_Seismic_Hazard_Assessment_2018/MapServer/15` | `Peak_Ground_Acceleration_contours_10pct` (`esriGeometryPolyline`, `EPSG:4283`) | **100** features (HTTP 200) |
| `next_lga_boundaries_asgs2025` | National | `periodically_refreshed` | `.../ASGS2025/LGA/MapServer/0` | `LGA` (`esriGeometryPolygon`, `EPSG:7844`) | **566** features (HTTP 200) |
| `next_sa2_boundaries_asgs2021` | National | `periodically_refreshed` | `.../ASGS2021/SA2/MapServer/0` | `SA2` (`esriGeometryPolygon`, `EPSG:7844`) | **2,473** features (HTTP 200) |
| `next_urban_centres_localities` | National | `static_authoritative` | `.../ASGS2021/UCL/MapServer/0` | `UCL` (`esriGeometryPolygon`, `EPSG:7844`) | **1,916** features (HTTP 200) |
| `nsw_lga_boundaries` | State (NSW) | `periodically_refreshed` | `.../NSW_Administrative_Boundaries_Theme/FeatureServer/8` | `LocalGovernmentArea` (`esriGeometryPolygon`, `EPSG:7844`) | **198** features (HTTP 200) |
| `nsw_water_inundation_areas` | State (NSW) | `periodically_refreshed` | `.../NSW_Water_Theme/FeatureServer/7` | `FuzzyExtentWaterArea` (`esriGeometryPolygon`, `EPSG:4283`) | **57,899** features (HTTP 200; bbox-filtered for Hunter/Newcastle) |
| `nsw_foi_building_complexes` | State (NSW) | `periodically_refreshed` | `.../NSW_Features_of_Interest_Category/FeatureServer/3` | `BuildingComplexPoint` (`esriGeometryPoint`, `EPSG:4283` — hospitals, schools, emergency services) | **11,367** features (HTTP 200) |
| `nsw_rfs_major_incidents_live` | State (NSW) | `live_operational_feed` | `https://www.rfs.nsw.gov.au/feeds/majorIncidents.json` | GeoJSON `FeatureCollection` (`Point` / `GeometryCollection`, `EPSG:4326`) | **22** live features (HTTP 200) |
| `nsw_emergency_management_restricted` | State (NSW) | `live_operational_feed` | `.../NSW_Emergency_Management_Category/FeatureServer/0` | Restricted ArcGIS FeatureServer | **FAIL (Demonstrated Failure)**: HTTP 200 with embedded JSON `{"error": {"code": 499, "message": "Token Required"}}` (Acceptance Test #17) |

---

## 7. Detailed Implementation Backlog

### Phase 1 — Repository Assessment & Architecture (COMPLETED)
- [x] Inspect `CheatSheets`, `aura_siting_crafter`, `nsw_public_transport_crafter`, and `GeoLibre`.
- [x] Run `tools/graphify_analysis.py` baseline check.
- [x] Author `docs/architecture/repository_assessment.md`.
- [x] Author `docs/architecture/implementation_plan.md` incorporating the Google Stitch Design Architecture.

### Phase 2 — GCS and Catalogue Foundation (COMPLETED)
- [x] `config/dataset_manifest.json`: Curated emergency management catalogue with strict schema (`dataset_key`, `title`, `category`, `provider`, `endpoint`, `licence`, `source_vintage`, `original_crs`, `stored_crs`, `refresh_policy`, `known_limitations`).
- [x] `src/catalogue/manifest_loader.py` & `src/catalogue/dataset_registry.py`: Pydantic-validated manifest loader, query by scale/category/theme, and synchronization verifier.
- [x] `src/catalogue/schema_inspector.py`: Inspects PyArrow/GeoParquet schemas and live service field definitions.
- [x] `src/ingestion/gcs_storage.py`: GCS client wrapper with quota-project verification, immutable timestamped path builder, object generation ID capture, SHA-256 hashing, and `publish_gate.py` integration.
- [x] `src/ingestion/source_connectors/`: Modular connectors for ArcGIS REST (`arcgis_connector.py`), OGC WFS (`wfs_connector.py`), and GeoJSON feeds (`geojson_connector.py`).
- [x] `src/ingestion/geoparquet_writer.py`: Writes GeoParquet 1.1.0 compliant files with validated `"geo"` metadata, CRS PROJJSON, bounding box columns, spatial sorting, and preserved source attributes.
- [x] `src/ingestion/snapshot_ingest.py` & `src/ingestion/live_fetch.py`: Immutable snapshot ingestion pipeline and JIT query-time live fetcher (which also saves a timestamped raw snapshot).
- [x] `tools/ingest_dataset.py` & `tools/graphify_analysis.py`: CLI entrypoints.

### Phase 3 — Data QA & Three-Level Validation (COMPLETED)
- [x] `src/validation/publish_gate.py`: Pre-upload secret, filename, and licence verification gate.
- [x] `src/validation/source_contracts.py`: **Level 1 Validation** — HTTP status, Content-Type verification (rejecting HTML landing/block pages), ArcGIS 200-error detection, geometry type match, and record count probe.
- [x] `src/validation/geoparquet_validation.py` & `src/validation/geometry_validation.py`: **Level 2 Validation** — Parquet footer check, GeoParquet `"geo"` metadata schema check, CRS check, bbox check, `ST_IsValid` / null / empty geometry rates, duplicate ID check, and SHA-256 hash.
- [x] `src/validation/reconciliation.py`: **Level 3 Validation** — Source-to-storage feature count reconciliation, bbox comparison, schema drift detection, and explicit `PASS` / `WARNING` / `FAIL` / `NOT TESTED` / `NOT APPLICABLE` grading.
- [x] `src/validation/qa_report.py` & `tools/run_qa.py`: Generates machine-readable JSON QA artifacts and Stitch-styled interactive HTML QA overview + per-dataset MapLibre QA inspector pages (`docs/qa/index.html` and `docs/qa/inspect.html`).
- [x] `tests/zero_mock/test_no_mock_data.py`, `tests/zero_mock/test_no_secrets.py`, `tests/unit/test_validation_levels.py`, `tests/data_quality/test_catalogue_contracts.py`: Automated test suite (`10 passed`).

### Phase 4 — First Real Datasets Ingestion (COMPLETED)
- [x] Ran live Level 1 probes and ingested initial authoritative national (`ga_electricity_substations`, `ga_major_power_stations`, `ga_electricity_transmission_lines`, `ga_seismic_hazard_pga_10pct`, `next_lga_boundaries_asgs2025`, `next_sa2_boundaries_asgs2021`), state/local (`nsw_lga_boundaries`, `nsw_water_inundation_areas`, `nsw_foi_building_complexes`), and live feed (`nsw_rfs_major_incidents_live`) datasets (`2,799` stored features across 10 GeoParquet 1.1.0 snapshots).
- [x] Demonstrated a genuine failed/restricted endpoint (`nsw_emergency_management_restricted` returning HTTP 200 with embedded ArcGIS error 499 `"Token Required"`) in the QA report with `FAIL` status and zero mock fallback (Acceptance Test #17).

### Phase 5 — Spatial Execution Engines
- [ ] `src/engines/duckdb_engine.py`: DuckDB Spatial execution engine querying versioned GeoParquet directly (GCS or local staging).
- [ ] `src/engines/wherobots_engine.py`: Wherobots DB-API & batch job execution engine with mandatory `try...finally` teardown and active session cost probing.

### Phase 6 — Emergency Analysis & Population Methods Comparison
- [ ] `src/analysis/population_methods.py`: Controlled implementation of Method A (NExT centroid point-in-polygon), Method B (1 km² cell footprint intersection + boundary edge cases), and Method C (area-weighted proportional estimate).
- [ ] `src/analysis/exposure.py`, `src/analysis/accessibility.py`, `src/analysis/isolation.py`, `src/analysis/infrastructure_dependencies.py`: Local, regional/state, and national analytical workflows.

### Phase 7 — AI-Assisted Spatial Analysis Workflow
- [ ] `src/ai/spatial_agent.py`, `src/ai/query_planner.py`, `src/ai/sql_validator.py`, `src/ai/execution_audit.py`: Catalogue-grounded natural-language planner with strict SQL allow-listing, zero silent defaults, ambiguity clarification prompts, and full JSON audit logging.

### Phase 8 — GeoLibre, GeoJSON Export & Offline Map-in-a-Box
- [ ] `src/exports/geojson_export.py` & `src/exports/geoparquet_export.py`: RFC 7946 WGS84 GeoJSON exporter with sidecar provenance manifest.
- [ ] `src/exports/map_package_builder.py` & `tools/build_map_package.py`: Bbox-specific, 100% offline Map-in-a-Box bundler with local MapLibre GL JS/CSS, local basemap tiles/PMTiles, GeoJSON layers, population comparison switcher, and offline network-disabled test (`tests/offline_package/test_offline_package.py`).

### Phase 9 — Benchmarking & Acceptance Verification
- [ ] `src/engines/benchmark_runner.py` & `tools/run_benchmarks.py`: Repeatable benchmark harness across Live, DuckDB Spatial, and Wherobots/Sedona.
- [ ] Execute all 20 Acceptance Tests (Section 13) and verify resource teardown.
