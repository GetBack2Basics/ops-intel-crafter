# Plan: GCS Harvester & Export Plugin for GeoLibre

## Goal
Allow GeoLibre users to connect their own GCS accounts, create buckets, harvest portal datasets, and export GeoParquet to GCS — mirroring the OIC harvester pipeline (`tools/harvest_portal_dataset.py` + `tools/export_geolibre_project.py`).

## Architecture

### Phase 3a: GCS Connection Settings (Settings → Cloud Storage)
- Add "Google Cloud Storage" as a provider type alongside S3.
- Store: bucket name, project ID, service account key (or OAuth token), region.
- Test connection: list buckets / create bucket.
- Persist in app settings (same as S3 connections).

### Phase 3b: Export to GCS (Processing → Export to GCS)
- Menu action: "Export layers to GCS GeoParquet".
- Uses DuckDB-WASM `COPY ... TO 'gs://bucket/path/file.parquet'` with GCS credentials.
- Generates a `.geolibre.json` project file pointing to the GCS URLs.
- Uploads the project JSON to GCS.

### Phase 3c: Harvest from Portal URL
- Dialog: enter portal URL + licence.
- Uses the existing harvester logic (ported to JS/TS or called via a Cloud Run backend).
- For the web app: call the OIC Cloud Run harvester backend (already deployed).
- For the desktop app: run the Python harvester as a subprocess (like the S3 browser).

### Phase 3d: GCS Browser Plugin
- Mirror of `maplibre-s3-browser` but for GCS.
- Browse buckets, list objects, add GeoParquet/GeoJSON layers.
- Uses `gs://` URLs (already supported in SQL Workspace).

## Implementation Priority
1. Phase 3a (connection settings) — foundation
2. Phase 3b (export) — core value
3. Phase 3d (browser) — convenience
4. Phase 3c (harvest) — advanced (requires backend or Python subprocess)

## Files to Modify/Create
- `packages/plugins/src/plugins/maplibre-gcs-browser.ts` — GCS browser plugin
- `apps/geolibre-desktop/src/components/layout/CloudStorageSection.tsx` — add GCS provider
- `apps/geolibre-desktop/src/lib/gcs-connections.ts` — GCS connection management
- `apps/geolibre-desktop/src/lib/gcs-export.ts` — export to GCS via DuckDB-WASM
- `packages/core/src/s3.ts` — already has gs:// support (Phase 1)

## Estimated Effort
- Phase 3a: 2-3 days
- Phase 3b: 3-5 days
- Phase 3c: 5-7 days (requires backend integration)
- Phase 3d: 3-5 days

## Dependencies
- Phase 1 (gs:// URL support) — DONE
- GCS HMAC keys or OAuth for browser-based access
- DuckDB-WASM GCS support (uses HTTP range requests, already works)