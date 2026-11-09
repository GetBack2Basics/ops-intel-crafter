# Operational Intelligence Crafter — Project Rules & Invariants

## Project Invariants (Recorded from AI Intake Interview — 2026-11-09)
- **Canonical Source of Truth & Cloud-First Execution:** Google Cloud Storage (`gs://operational-intelligence-crafter-lake/`, configurable via `OIC_GCS_BUCKET` and `OIC_GCP_PROJECT`). **All data storage, processing, and web testing happen directly on GCS.**
- **Local Repository Role:** Local disk (`c:\Projects\operational_intelligence_crafter`) is strictly for code storage and git backup to `https://github.com/GetBack2Basics/ops-intel-crafter`. All datasets, manifests, QA pages, and deliverables are published directly to GCS after passing `publish_gate.py`. Silent fallback from cloud to local is forbidden.
- **No Query-Result Cache:** Stored GeoParquet files in `geoparquet/<dataset_key>/<source_vintage>/<retrieval_timestamp>/` are the reusable source snapshots. Analytical queries execute directly against stored GeoParquet or explicitly selected live endpoints—never against cached query results.
- **NExT & Emergency Catalogue Sourcing:** Sourced directly from official public Australian government services (ABS ASGS 2025/2021 & 1 km² Population Grid, Geoscience Australia, AIHW/State Health, Geoscape/State Address & Cadastre, NSW Spatial Services/RFS, QSpatial/Ergon/Energex, Vicmap, SLIP WA, Geofabrik OSM).
- **Population Methodology Invariant:** Must preserve and compare all three methods on identical incident footprints:
  - **Method A:** NExT 1 km² cell-centroid point-in-polygon baseline (`ST_Contains`).
  - **Method B:** 1 km² cell polygon footprint intersection (`ST_Intersects`), reporting full-cell population totals and boundary-straddling edge cases separately.
  - **Method C:** Optional area-weighted proportional estimate (`ST_Area(ST_Intersection) / ST_Area(cell)`), explicitly labelled as a uniform within-cell population assumption (never reported as an observed count).
- **Wherobots & Valhalla Lifecycle:** Use DuckDB Spatial locally and Wherobots DB-API / headless `tiny` jobs for distributed Sedona workloads with mandatory `try...finally` teardown (`$0.00/hr` idle cost). Spin up GCE `valhalla-tuffs` or local Valhalla container only during accessibility benchmarks and verify termination immediately after.
- **Zero-Mock & Three-Level Validation:**
  - Zero synthetic coordinates, `sampleFeatures`, `mock_data`, hardcoded `AUTHORITATIVE_COUNTS`, or silent Euclidean buffer substitutions.
  - Every dataset and analysis must record **Level 1 (Source Contract)**, **Level 2 (Stored GeoParquet Artifact)**, and **Level 3 (Source-to-Storage Reconciliation)** with explicit `PASS`, `WARNING`, `FAIL`, `NOT TESTED`, or `NOT APPLICABLE` statuses.
- **Destructive Actions & Cloud Spend:** Require explicit user confirmation before any bucket overwrite, deletion, or paid cloud deployment.

## Graphify Onboarding Rule
At the start of any refactoring session, run:
```bash
python tools/graphify_analysis.py
```

## Lint & Zero-Mock Gate Rule
All code modifications must pass:
```bash
pytest tests/zero_mock/ tests/unit/ tests/data_quality/ -v
```

