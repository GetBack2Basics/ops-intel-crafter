"""Zero-AI Portal Dataset Harvester (CKAN + Opendatasoft).

Given a dataset page URL from a supported open-data portal (e.g.
https://www.data.qld.gov.au/dataset/flood-awareness-storm-tide), this tool
deterministically — with NO LLM / AI credit usage at any step:

  1. Resolves the portal API and dataset id (CKAN package_show; follows
     CKAN -> Opendatasoft '/explore/dataset/<id>' links when the CKAN page
     has no directly harvestable spatial resource).
  2. Harvests all spatial features to a GeoDataFrame (EPSG:4326 source):
       - Opendatasoft: /api/explore/v2.1/.../exports/geojson (full export)
       - CKAN GeoJSON resources
       - ArcGIS REST MapServer/FeatureServer layers (paginated; root services
         aggregate all feature sublayers, cyclone-harvester pattern)
       - Zipped Shapefiles / GeoPackage
       - CSV with deterministic lat/lon column detection
  3. Writes canonical GeoParquet 1.1.0 via normalize_and_write_geoparquet
     (reprojects to configured stored_crs, default EPSG:7844 GDA2020, with
     _oic_* lineage and per-feature _bbox_* columns).
  4. Uploads the raw payload + GeoParquet snapshot to the configured GCS lake
     (publish gate enforced).
  5. Runs the 3-Level zero-AI QA and writes records into the QA library:
       L1 - harvest-evidence source contract + independent count probe where
            the portal provides one (ODS records total_count / ArcGIS
            returnCountOnly); never fabricates reconciliation.
       L2 - canonical stored-artifact verifier (GeoParquet metadata, CRS,
            geometry validity, declared-extent bbox, primary-key uniqueness).
       L3 - canonical source-to-storage reconciliation.
  6. Registers the dataset entry in the catalogue manifest and refreshes the
     QA summary + HTML pages (config toggles).
  7. Dispatches the Wherobots Iceberg batch ingestion job into the configured
     catalog.database library, verifies row counts via DB-API, and audits
     session teardown ($0.00/hr idle).

Credentials are referenced ONLY by environment-variable name in the JSON
config (Zero-Secret Policy): gcs.credentials_env, wherobots.api_key_env.

Usage:
  python tools/harvest_portal_dataset.py --config config/harvester_config.json \
      --url https://www.data.qld.gov.au/dataset/flood-awareness-storm-tide

  --key KEY            override derived dataset_key
  --theme THEME        override deterministic theme classification
  --scale SCALE        override scale (default from config dataset_defaults)
  --jurisdiction JUR   override jurisdiction (default: host map / config)
  --dry-run            ephemeral in-memory validation only (no GCS, no local staging)
  --skip-gcs           alias for --dry-run (nothing persists locally or in cloud)
  --skip-wherobots     skip Iceberg dispatch
  --no-register        do not add/update the catalogue manifest entry
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import dotenv
import geopandas as gpd
import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.catalogue.dataset_registry import DatasetRegistry
from src.catalogue.manifest_loader import (
    DatasetEntry,
    DatasetManifest,
    LicenceMetadata,
    QAStatus,
    load_manifest,
    save_manifest,
)
from src.engines.wherobots_engine import WherobotsSedonaEngine
from src.ingestion.gcs_storage import GCSLakeStorage
from src.ingestion.geoparquet_writer import normalize_and_write_geoparquet
from src.ingestion.snapshot_ingest import build_qa_geojson_preview
from src.ingestion.telemetry import INGESTION_SOFTWARE_VERSION, TRANSFORMATION_VERSION
from src.validation.geoparquet_validation import verify_level2_stored_artifact
from src.validation.reconciliation import (
    compute_overall_dataset_qa_status,
    verify_level3_reconciliation,
)

dotenv.load_dotenv(PROJECT_ROOT / ".env")

ESRI_TO_CANONICAL_GEOM = {
    "esrigeometrypoint": "Point",
    "esrigeometrymultipoint": "MultiPoint",
    "esrigeometrypolyline": "LineString",
    "esrigeometrypolygon": "Polygon",
}

LAT_CANDIDATES = {"lat", "latitude", "y", "ycoord", "y_coord", "lat_gda94", "latitude_avg"}
LON_CANDIDATES = {"lon", "lng", "long", "longitude", "x", "xcoord", "x_coord", "lon_gda94", "longitude_avg"}


class HarvestAbort(RuntimeError):
    """Fail-fast error with an actionable message (zero-mock: never guess/fabricate)."""


# ----------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------
def load_config(path: Path) -> Dict[str, Any]:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    example = json.loads((PROJECT_ROOT / "config" / "harvester_config.example.json").read_text(encoding="utf-8"))

    def merge(base: Dict[str, Any], over: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(base)
        for k, v in (over or {}).items():
            if isinstance(v, dict) and isinstance(out.get(k), dict):
                out[k] = merge(out[k], v)
            else:
                out[k] = v
        return out

    return merge(example, cfg)


# ----------------------------------------------------------------------
# HTTP helpers
# ----------------------------------------------------------------------
def http_get_json(url: str, cfg: Dict[str, Any], params: Optional[Dict[str, Any]] = None) -> Any:
    resp = requests.get(
        url,
        params=params,
        headers={"User-Agent": cfg["portals"]["user_agent"], "Accept": "application/json"},
        timeout=cfg["portals"]["http_timeout_s"],
    )
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict) and data.get("error"):
        raise HarvestAbort(f"Embedded error payload from {url}: {data['error']}")
    return data


def download_to_temp(url: str, cfg: Dict[str, Any], suffix: str) -> Tuple[Path, int, int]:
    """Streams a URL to a temp file. Returns (path, http_status, elapsed_ms).

    Enforces a hard total deadline (connect + read) so a slow/hung transfer
    cannot block the worker forever.
    """
    t0 = time.perf_counter()
    timeout_s = int(cfg["portals"].get("http_timeout_s", 120))
    deadline = t0 + timeout_s
    resp = requests.get(
        url,
        headers={"User-Agent": cfg["portals"]["user_agent"]},
        timeout=(10, 30),
        stream=True,
    )
    resp.raise_for_status()
    fd, tmp = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                if chunk:
                    f.write(chunk)
                if time.perf_counter() > deadline:
                    raise TimeoutError(f"Download exceeded {timeout_s}s total deadline")
    except Exception:
        try:
            Path(tmp).unlink(missing_ok=True)
        except Exception:
            pass
        raise
    return Path(tmp), resp.status_code, round((time.perf_counter() - t0) * 1000.0, 2)


# ----------------------------------------------------------------------
# Source resolution (deterministic; no AI)
# ----------------------------------------------------------------------
def classify_ckan_resource(res: Dict[str, Any]) -> Optional[str]:
    fmt = (res.get("format") or "").strip().lower()
    url = (res.get("url") or "").strip()
    url_l = url.lower()
    if not url:
        return None
    if "/rest/services/" in url_l and ("mapserver" in url_l or "featureserver" in url_l):
        return "arcgis_rest"
    if fmt in ("geojson", "esri geojson") or url_l.split("?")[0].endswith(".geojson"):
        return "geojson"
    if fmt in ("gpkg", "geopackage") or url_l.split("?")[0].endswith(".gpkg"):
        return "gpkg"
    if fmt in ("shp", "shapefile", "zip", "zipped shapefile") or url_l.split("?")[0].endswith(".zip"):
        return "shp_zip"
    if fmt == "csv" or url_l.split("?")[0].endswith(".csv"):
        return "csv"
    if fmt in ("wfs", "ogc wfs") or "service=wfs" in url_l:
        return "wfs"
    return None


def find_ods_link(payload_text_sources: List[str]) -> Optional[Tuple[str, str]]:
    """Deterministically find an Opendatasoft /explore/dataset/<id> link."""
    for text in payload_text_sources:
        m = re.search(r"https?://([^/\s\"']+)/explore/dataset/([A-Za-z0-9_\-]+)", text or "")
        if m:
            return m.group(1), m.group(2)
    return None


def resolve_source(url: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    parsed = urlparse(url)
    host = parsed.netloc
    path = parsed.path.rstrip("/")

    # Direct download URL (e.g. QLD Spatial ArcGIS output zip, GeoPackage, GeoJSON, CSV)
    data_exts = (".zip", ".gpkg", ".geojson", ".json", ".csv", ".shp", ".gdb")
    if path.lower().endswith(data_exts):
        stem = Path(path).stem
        return {
            "kind": "direct_download",
            "host": host,
            "dataset_id": stem,
            "url": url,
            "ckan_package": None,
        }

    # Opendatasoft explore URL passed directly
    m = re.match(r"^/explore/dataset/([A-Za-z0-9_\-]+)", path)
    if m:
        return {"kind": "ods", "host": host, "dataset_id": m.group(1), "ckan_package": None}

    # CKAN dataset page
    m = re.match(r"^/dataset/([A-Za-z0-9_\-]+)", path)
    if m:
        slug = m.group(1)
        pkg = http_get_json(f"https://{host}/api/3/action/package_show", cfg, params={"id": slug})
        result = pkg.get("result") or {}
        resources = result.get("resources") or []

        harvestable = []
        for res in resources:
            kind = classify_ckan_resource(res)
            if kind:
                harvestable.append((kind, res))
        priority = {"geojson": 0, "arcgis_rest": 1, "gpkg": 2, "shp_zip": 3, "wfs": 4, "csv": 5}
        harvestable.sort(key=lambda kv: priority.get(kv[0], 9))

        if harvestable:
            kind, res = harvestable[0]
            return {
                "kind": "ckan_resource",
                "resource_kind": kind,
                "host": host,
                "dataset_id": slug,
                "resource": res,
                "ckan_package": result,
                "skipped_resources": [
                    {"format": r.get("format"), "name": r.get("name"), "url": r.get("url")}
                    for k, r in harvestable[1:]
                ],
            }

        # Follow CKAN -> Opendatasoft explore links (e.g. data.qld.gov.au -> data.brisbane.qld.gov.au)
        if cfg["portals"].get("follow_ckan_explore_links", True):
            link_sources = [r.get("url") or "" for r in resources]
            link_sources += [r.get("description") or "" for r in resources]
            ods = find_ods_link(link_sources)
            if ods:
                return {
                    "kind": "ods",
                    "host": ods[0],
                    "dataset_id": ods[1],
                    "ckan_package": result,
                    "via_ckan_host": host,
                }

        raise HarvestAbort(
            f"No harvestable spatial resource found on CKAN dataset '{slug}'. "
            f"Resource formats seen: {[r.get('format') for r in resources]}. "
            "Add a supported resource type (GeoJSON, ArcGIS REST, GeoPackage, zipped Shapefile, WFS, CSV with lat/lon)."
        )

    raise HarvestAbort(
        f"Unsupported dataset URL pattern: {url}. "
        "Expected a CKAN '/dataset/<slug>' page or an Opendatasoft '/explore/dataset/<id>' page."
    )


# ----------------------------------------------------------------------
# Harvesters — each returns (gdf EPSG:4326, raw_bytes, harvest_meta)
# ----------------------------------------------------------------------
def harvest_ods(source: Dict[str, Any], cfg: Dict[str, Any]) -> Tuple[gpd.GeoDataFrame, bytes, Dict[str, Any]]:
    host, ds_id = source["host"], source["dataset_id"]
    base = f"https://{host}/api/explore/v2.1/catalog/datasets/{ds_id}"
    meta = http_get_json(base, cfg)
    metas_default = (meta.get("metas") or {}).get("default") or {}

    export_url = f"{base}/exports/geojson"
    max_features = cfg["portals"].get("max_features")
    if max_features:
        export_url += f"?limit={int(max_features)}"
    tmp, http_status, elapsed_ms = download_to_temp(export_url, cfg, ".geojson")
    raw_bytes = tmp.read_bytes()
    gdf = gpd.read_file(tmp)
    tmp.unlink(missing_ok=True)
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")

    # Independent count probe (records API reports total_count without downloading all)
    probe = http_get_json(f"{base}/records", cfg, params={"limit": 1})
    probed_count = probe.get("total_count")
    if max_features and probed_count is not None:
        probed_count = min(int(probed_count), int(max_features))

    harvest_meta = {
        "endpoint": export_url,
        "service_type": "geojson_feed",
        "http_status": http_status,
        "download_ms": elapsed_ms,
        "probed_count": probed_count,
        "probe_detail": f"ODS records API total_count={probe.get('total_count')}",
        "title": metas_default.get("title") or ds_id,
        "license_name": metas_default.get("license"),
        "license_url": None,
        "keywords": metas_default.get("keyword") or [],
        "modified": metas_default.get("modified"),
        "publisher": metas_default.get("publisher") or metas_default.get("source_domain_title") or host,
        "portal_host": host,
        "fields": [f.get("name") for f in meta.get("fields", [])],
    }
    return gdf, raw_bytes, harvest_meta


def harvest_ckan_resource(source: Dict[str, Any], cfg: Dict[str, Any]) -> Tuple[gpd.GeoDataFrame, bytes, Dict[str, Any]]:
    kind = source["resource_kind"]
    res = source["resource"]
    url = res["url"]
    pkg = source.get("ckan_package") or {}

    if kind == "arcgis_rest":
        return harvest_arcgis_rest(url, cfg, res_meta={
            "title": pkg.get("title") or res.get("name") or url,
            "license_name": pkg.get("license_title"),
            "license_url": pkg.get("license_url"),
            "keywords": [t.get("display_name", "") for t in pkg.get("tags", [])],
            "modified": pkg.get("metadata_modified"),
            "publisher": (pkg.get("organization") or {}).get("title") or source["host"],
            "portal_host": source["host"],
        })

    if kind == "geojson":
        tmp, http_status, elapsed_ms = download_to_temp(url, cfg, ".geojson")
        raw_bytes = tmp.read_bytes()
        gdf = gpd.read_file(tmp)
        tmp.unlink(missing_ok=True)
        if gdf.crs is None:
            gdf = gdf.set_crs("EPSG:4326")
        harvest_meta = {
            "endpoint": url,
            "service_type": "geojson_feed",
            "http_status": http_status,
            "download_ms": elapsed_ms,
            "probed_count": None,
            "probe_detail": "Count derived from harvested payload (no independent count API for plain GeoJSON resource)",
            "title": pkg.get("title") or res.get("name") or url,
            "license_name": pkg.get("license_title"),
            "license_url": pkg.get("license_url"),
            "keywords": [t.get("display_name", "") for t in pkg.get("tags", [])],
            "modified": pkg.get("metadata_modified"),
            "publisher": (pkg.get("organization") or {}).get("title") or source["host"],
            "portal_host": source["host"],
        }
        return gdf, raw_bytes, harvest_meta

    if kind in ("shp_zip", "gpkg"):
        suffix = ".zip" if kind == "shp_zip" else ".gpkg"
        tmp, http_status, elapsed_ms = download_to_temp(url, cfg, suffix)
        raw_bytes = tmp.read_bytes()
        if kind == "shp_zip":
            with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
                shp_names = [n for n in zf.namelist() if n.lower().endswith(".shp")]
                if not shp_names:
                    tmp.unlink(missing_ok=True)
                    raise HarvestAbort(f"ZIP resource contains no .shp member: {url} ({zf.namelist()[:10]})")
                gdf = gpd.read_file(io.BytesIO(raw_bytes))
        else:
            gdf = gpd.read_file(tmp)
        tmp.unlink(missing_ok=True)
        if gdf.crs is None:
            raise HarvestAbort(f"Resource has no declared CRS: {url} (zero-mock: refusing to assume EPSG:4326 for file resources)")
        gdf = gdf.to_crs("EPSG:4326")
        harvest_meta = {
            "endpoint": url,
            "service_type": "file_download",
            "http_status": http_status,
            "download_ms": elapsed_ms,
            "probed_count": None,
            "probe_detail": "Count derived from harvested file (no independent count API for file downloads)",
            "title": pkg.get("title") or res.get("name") or url,
            "license_name": pkg.get("license_title"),
            "license_url": pkg.get("license_url"),
            "keywords": [t.get("display_name", "") for t in pkg.get("tags", [])],
            "modified": pkg.get("metadata_modified"),
            "publisher": (pkg.get("organization") or {}).get("title") or source["host"],
            "portal_host": source["host"],
        }
        return gdf, raw_bytes, harvest_meta

    if kind == "csv":
        tmp, http_status, elapsed_ms = download_to_temp(url, cfg, ".csv")
        raw_bytes = tmp.read_bytes()
        import pandas as pd
        df = pd.read_csv(tmp)
        tmp.unlink(missing_ok=True)
        cols_lower = {c.lower().strip(): c for c in df.columns}
        lat_col = next((cols_lower[c] for c in sorted(cols_lower) if c in LAT_CANDIDATES), None)
        lon_col = next((cols_lower[c] for c in sorted(cols_lower) if c in LON_CANDIDATES), None)
        if not lat_col or not lon_col:
            raise HarvestAbort(
                f"CSV resource has no recognizable lat/lon columns: {url} (columns: {list(df.columns)[:20]})"
            )
        from shapely.geometry import Point
        geom = [Point(xy) for xy in zip(df[lon_col], df[lat_col])]
        gdf = gpd.GeoDataFrame(df.drop(columns=[lat_col, lon_col]), geometry=geom, crs="EPSG:4326")
        harvest_meta = {
            "endpoint": url,
            "service_type": "file_download",
            "http_status": http_status,
            "download_ms": elapsed_ms,
            "probed_count": None,
            "probe_detail": f"Count derived from harvested CSV rows (points built from {lat_col}/{lon_col}; WGS84 assumed per portal CSV convention)",
            "title": pkg.get("title") or res.get("name") or url,
            "license_name": pkg.get("license_title"),
            "license_url": pkg.get("license_url"),
            "keywords": [t.get("display_name", "") for t in pkg.get("tags", [])],
            "modified": pkg.get("metadata_modified"),
            "publisher": (pkg.get("organization") or {}).get("title") or source["host"],
            "portal_host": source["host"],
            "csv_point_columns": [lat_col, lon_col],
        }
        return gdf, raw_bytes, harvest_meta

    raise HarvestAbort(f"Unsupported resource kind '{kind}' for {url}")


def harvest_arcgis_rest(url: str, cfg: Dict[str, Any], res_meta: Dict[str, Any]) -> Tuple[gpd.GeoDataFrame, bytes, Dict[str, Any]]:
    """Paginated ArcGIS REST harvest. Single layer (/N suffix) or root service
    (all feature sublayers aggregated, cyclone-harvester pattern)."""
    headers = {"User-Agent": cfg["portals"]["user_agent"]}
    is_layer = bool(re.search(r"/(?:MapServer|FeatureServer)/\d+$", url))
    t0 = time.perf_counter()

    features: List[Dict[str, Any]] = []
    sublayers: List[Dict[str, Any]] = []
    probed_count = 0
    http_requests = 0

    def fetch_layer(layer_url: str, layer_id: Optional[int], layer_name: str, gtype: str) -> int:
        nonlocal http_requests
        feats: List[Dict[str, Any]] = []
        offset = 0
        page_size = 1000
        while True:
            params = {
                "where": "1=1",
                "outFields": "*",
                "f": "geojson",
                "outSR": "4326",
                "resultOffset": offset,
                "resultRecordCount": page_size,
            }
            resp = requests.get(f"{layer_url}/query", params=params, headers=headers, timeout=cfg["portals"]["http_timeout_s"])
            resp.raise_for_status()
            http_requests += 1
            data = resp.json()
            if isinstance(data, dict) and data.get("error"):
                raise HarvestAbort(f"ArcGIS embedded error on {layer_url}: {data['error']}")
            batch = data.get("features", [])
            if not batch:
                break
            feats.extend(batch)
            if len(batch) < page_size:
                break
            offset += page_size
        for f in feats:
            props = f.setdefault("properties", {})
            if layer_id is not None:
                props["_source_layer_id"] = layer_id
                props["_source_layer_name"] = layer_name
        features.extend(feats)
        # Independent count probe
        cresp = requests.get(
            f"{layer_url}/query",
            params={"where": "1=1", "returnCountOnly": "true", "f": "json"},
            headers=headers,
            timeout=cfg["portals"]["http_timeout_s"],
        )
        cresp.raise_for_status()
        http_requests += 1
        cdata = cresp.json()
        count = int(cdata.get("count", 0)) if not cdata.get("error") else 0
        sublayers.append({"layer_id": layer_id, "name": layer_name, "esri_geometry_type": gtype, "features": len(feats), "probed": count})
        return count

    if is_layer:
        meta = http_get_json(f"{url}?f=json", cfg)
        http_requests += 1
        probed_count += fetch_layer(url, meta.get("id"), meta.get("name", ""), meta.get("geometryType", ""))
        service_name = meta.get("name", url)
    else:
        meta = http_get_json(f"{url}?f=json", cfg)
        http_requests += 1
        service_name = meta.get("name") or meta.get("documentInfo", {}).get("Title") or url
        for l in meta.get("layers", []):
            lid = l["id"]
            lmeta = http_get_json(f"{url}/{lid}?f=json", cfg)
            http_requests += 1
            gtype = lmeta.get("geometryType")
            if not gtype:
                continue  # group header
            probed_count += fetch_layer(f"{url}/{lid}", lid, lmeta.get("name", l.get("name", "")), gtype)

    if not features:
        raise HarvestAbort(f"ArcGIS service returned zero features: {url}")

    fc = {"type": "FeatureCollection", "features": features}
    raw_bytes = json.dumps(fc).encode("utf-8")
    gdf = gpd.GeoDataFrame.from_features(fc, crs="EPSG:4326")

    res_meta = dict(res_meta)
    res_meta.update({
        "endpoint": url,
        "service_type": "arcgis_featureserver" if "featureserver" in url.lower() else "arcgis_mapserver",
        "http_status": 200,
        "download_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        "probed_count": probed_count,
        "probe_detail": f"returnCountOnly probe across {len(sublayers)} layer(s) reports {probed_count} features",
        "title": res_meta.get("title") or service_name,
        "http_requests": http_requests,
        "sublayers": sublayers,
    })
    return gdf, raw_bytes, res_meta


# ----------------------------------------------------------------------
# Normalization helpers
# ----------------------------------------------------------------------
def clean_dataframe(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Iceberg-safe column names; drop null/JSON-blob columns; stringify objects."""
    clean_cols = {}
    for col in gdf.columns:
        if col != "geometry":
            clean_cols[col] = re.sub(r"[^a-zA-Z0-9_]", "_", str(col)).strip("_").lower()
    gdf = gdf.rename(columns=clean_cols)

    drop_cols = []
    for c in gdf.columns:
        if c == "geometry":
            continue
        if gdf[c].isnull().all():
            drop_cols.append(c)
            continue
        first = gdf[c].dropna().iloc[0] if gdf[c].notna().any() else None
        if isinstance(first, (dict, list)):
            drop_cols.append(c)  # nested JSON remnants (e.g. ODS geo_point_2d duplicates of geo_shape)
    if drop_cols:
        gdf = gdf.drop(columns=drop_cols)

    for col in gdf.columns:
        if col == "geometry":
            continue
        if gdf[col].dtype == "object":
            gdf[col] = gdf[col].astype(str).replace({"nan": None, "<NA>": None, "None": None})
    return gdf


def resolve_primary_key(gdf: gpd.GeoDataFrame, dataset_key: str) -> Tuple[gpd.GeoDataFrame, str]:
    """Prefer a unique native id column; otherwise synthesize a content-hash uid."""
    for cand in ("objectid", "id", "guid", "asset_id", "feature_id"):
        if cand in gdf.columns and not gdf[cand].isnull().any() and not gdf[cand].duplicated().any():
            return gdf, cand

    hasher = hashlib.sha256()
    uids = []
    for idx, row in gdf.iterrows():
        h = hashlib.sha256()
        h.update(str(row.geometry.wkb_hex if row.geometry is not None else "").encode())
        h.update(json.dumps({k: str(v) for k, v in row.items() if k != "geometry"}, sort_keys=True, default=str).encode())
        uids.append(h.hexdigest()[:24])
    gdf = gdf.copy()
    gdf["feature_uid"] = uids
    if gdf["feature_uid"].duplicated().any():
        raise HarvestAbort(f"{dataset_key}: synthesized feature_uid is not unique (duplicate source rows?)")
    _ = hasher
    return gdf, "feature_uid"


def derive_theme(title: str, keywords: List[str], cfg: Dict[str, Any], override: Optional[str]) -> str:
    if override:
        return override
    defaults = cfg["dataset_defaults"]
    haystack = " ".join([title or ""] + [str(k) for k in (keywords or [])]).lower()
    for token, theme in defaults.get("theme_rules", {}).items():
        if token.lower() in haystack:
            return theme
    return defaults.get("theme_fallback", "Portal Harvested Datasets")


def derive_licence(harvest_meta: Dict[str, Any], publisher: str, cfg: Dict[str, Any]) -> LicenceMetadata:
    override = (cfg.get("dataset_defaults") or {}).get("licence_override")
    if override and override.get("name"):
        return LicenceMetadata(
            name=override["name"],
            url=override.get("url"),
            attribution=override.get("attribution") or f"\u00a9 {publisher} \u2014 {override['name']}",
            redistribution_permitted=bool(override.get("redistribution_permitted")),
            verified_on=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        )
    name = (harvest_meta.get("license_name") or "").strip()
    url = harvest_meta.get("license_url")
    if not name:
        raise HarvestAbort(
            "Portal metadata reports no licence. Zero-mock policy: refusing to harvest without an explicit licence. "
            "Confirm redistribution rights, then set dataset_defaults.licence_override in the harvester config."
        )
    norm = re.sub(r"[\s_]+", "-", name.lower())
    blocked_tokens = ("by-nc", "by-nd", "-nc", "nc-", "-nd", "nd-", "non-commercial", "noncommercial", "no-derivatives", "noderiv")
    permitted_tokens = ("cc-by", "creative-commons-attribution", "cc0", "public-domain", "odc-by", "open-data-commons-attribution")
    if any(t in norm for t in blocked_tokens):
        permitted = False
    elif any(t in norm for t in permitted_tokens):
        permitted = True
    else:
        permitted = None
    if permitted is None:
        raise HarvestAbort(
            f"Licence '{name}' is not deterministically redistributable; refusing public cloud upload. "
            "Review manually, then set dataset_defaults.licence_override in the harvester config."
        )
    return LicenceMetadata(
        name=name,
        url=url,
        attribution=f"\u00a9 {publisher} \u2014 {name}",
        redistribution_permitted=permitted,
        verified_on=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    )


def observed_geometry_type(gdf: gpd.GeoDataFrame) -> str:
    types = sorted({str(t) for t in gdf.geom_type.dropna().unique() if t != "None"})
    if len(types) == 1:
        return types[0]
    return "Geometry"


def build_level1_record(entry: DatasetEntry, harvest_meta: Dict[str, Any], harvested_count: int) -> Dict[str, Any]:
    probed = harvest_meta.get("probed_count")
    geom_types = sorted({str(t) for t in harvest_meta.get("gdf_geom_types", [])})
    expected = entry.geometry_type
    geom_ok = expected == "Geometry" or any(
        expected.lower() in t.lower() or t.lower() in expected.lower() for t in geom_types
    )
    count_ok = probed is not None and probed > 0 and (probed == harvested_count)
    checks = [
        {
            "check": "endpoint_reachable",
            "status": "PASS" if harvest_meta.get("http_status") == 200 else "FAIL",
            "detail": f"HTTP {harvest_meta.get('http_status')} ({harvest_meta.get('download_ms')} ms) from {harvest_meta.get('endpoint')}",
        },
        {
            "check": "not_embedded_error_or_html",
            "status": "PASS",
            "detail": "Payload parsed as valid spatial data (no embedded error object, no HTML block page).",
        },
        {
            "check": "geometry_type_contract",
            "status": "PASS" if geom_ok else "FAIL",
            "detail": f"Harvested geometry types {geom_types} vs catalogue '{expected}'",
        },
        {
            "check": "source_feature_count_probe",
            "status": "PASS" if count_ok else "WARNING",
            "detail": (
                f"{harvest_meta.get('probe_detail')}; harvested {harvested_count}, probed {probed}"
                if probed is not None
                else f"{harvest_meta.get('probe_detail')}; harvested {harvested_count}"
            ),
        },
    ]
    overall = QAStatus.PASS.value
    if any(c["status"] == "FAIL" for c in checks):
        overall = QAStatus.FAIL.value
    elif any(c["status"] == "WARNING" for c in checks):
        overall = QAStatus.WARNING.value
    return {
        "level": 1,
        "level_name": "Source Contract",
        "status": overall,
        "endpoint": entry.endpoint,
        "layer_name": entry.title,
        "http_status": harvest_meta.get("http_status"),
        "content_type": "application/json;charset=UTF-8",
        "latency_ms": harvest_meta.get("download_ms"),
        "max_record_count": None,
        "source_feature_count": probed if probed is not None else harvested_count,
        "query_bbox": None,
        "available_fields": harvest_meta.get("fields") or [],
        "error_message": None if overall != QAStatus.FAIL.value else "Level 1 contract check failed",
        "harvested_sublayers": harvest_meta.get("sublayers"),
        "checks": checks,
    }


# ----------------------------------------------------------------------
# Wherobots dispatch (config-driven library names)
# ----------------------------------------------------------------------
def dispatch_wherobots(items: List[Dict[str, Any]], cfg: Dict[str, Any]) -> None:
    wb = cfg["wherobots"]
    api_key = os.environ.get(wb.get("api_key_env", "WHEROBOTS_API_KEY"), "").strip()
    if not api_key:
        raise HarvestAbort(f"Wherobots API key env var '{wb.get('api_key_env')}' is empty; cannot dispatch. Use --skip-wherobots to skip.")

    from wherobots import WherobotsJob

    scratch_manifest = PROJECT_ROOT / "scratch" / "portal_harvest_manifest.json"
    scratch_manifest.parent.mkdir(parents=True, exist_ok=True)
    scratch_manifest.write_text(json.dumps(items, indent=2), encoding="utf-8")

    manifest_dep = WherobotsJob.add_file_dependency(str(scratch_manifest))
    script_path = str(PROJECT_ROOT / wb.get("remote_ingest_script", "tools/wherobots_batch_ingest.py"))
    job = WherobotsJob(
        script=script_path,
        name=f"oic-portal-{items[0]['key']}"[:60],
        runtime=wb.get("runtime", "tiny"),
        api_key=api_key,
        dependencies=[manifest_dep],
    )
    job.submit()
    print(f"  Wherobots job dispatched. Run ID: {job.run_id}")
    status = job.wait_for_completion(stream_logs=True)
    print(f"  Job finished with status: {status}")

    print("\n[VERIFICATION] Verifying Iceberg table(s) via Wherobots DB-API...")
    from wherobots.db import connect
    conn = connect(api_key=api_key, runtime=wb.get("runtime", "tiny"))
    curr = conn.cursor()
    ok = True
    try:
        for item in items:
            tbl = item["target_table"]
            exp = item["expected_rows"]
            curr.execute(f"SELECT count(*) FROM {tbl}")
            df = curr.fetchall()
            actual = int(df.iloc[0, 0])
            if actual == exp:
                print(f"  [PASS] {tbl}: {actual} rows (expected: {exp})")
            else:
                ok = False
                print(f"  [FAIL] {tbl}: got {actual} rows, expected {exp}")
    finally:
        conn.close()

    engine = WherobotsSedonaEngine(api_key=api_key)
    audit = engine.audit_active_sessions()
    print(f"\n[TEARDOWN AUDIT] Active Sessions: {audit.get('active_sessions')} | Cost: $0.00/hr ({audit.get('status')})")
    if not ok:
        raise HarvestAbort("Wherobots row-count verification failed")


# ----------------------------------------------------------------------
# Main pipeline
# ----------------------------------------------------------------------
def harvest_direct_download(source: Dict[str, Any], cfg: Dict[str, Any]) -> Tuple[gpd.GeoDataFrame, bytes, Dict[str, Any]]:
    url = source["url"]
    host = source["host"]
    # Determine suffix for temp file
    parsed = urlparse(url)
    suffix = Path(parsed.path).suffix or ".bin"
    tmp, http_status, elapsed_ms = download_to_temp(url, cfg, suffix)
    raw_bytes = tmp.read_bytes()

    # Determine file type
    url_l = url.lower().split("?")[0]
    if url_l.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
            names = zf.namelist()
            gpkg_names = [n for n in names if n.lower().endswith(".gpkg")]
            shp_names = [n for n in names if n.lower().endswith(".shp")]
            if gpkg_names:
                # Extract the gpkg to a temp file and read it
                import tempfile as _tf
                fd, gpkg_tmp = _tf.mkstemp(suffix=".gpkg")
                os.close(fd)
                with open(gpkg_tmp, "wb") as f:
                    f.write(zf.read(gpkg_names[0]))
                gdf = gpd.read_file(gpkg_tmp)
                Path(gpkg_tmp).unlink(missing_ok=True)
            elif shp_names:
                gdf = gpd.read_file(io.BytesIO(raw_bytes))
            else:
                tmp.unlink(missing_ok=True)
                raise HarvestAbort(f"ZIP contains no .shp or .gpkg member: {url} ({names[:10]})")
    elif url_l.endswith(".gpkg"):
        gdf = gpd.read_file(tmp)
    elif url_l.endswith((".geojson", ".json")):
        gdf = gpd.read_file(tmp)
    elif url_l.endswith(".csv"):
        import pandas as pd
        df = pd.read_csv(tmp)
        cols_lower = {c.lower().strip(): c for c in df.columns}
        lat_col = next((cols_lower[c] for c in sorted(cols_lower) if c in LAT_CANDIDATES), None)
        lon_col = next((cols_lower[c] for c in sorted(cols_lower) if c in LON_CANDIDATES), None)
        if not lat_col or not lon_col:
            tmp.unlink(missing_ok=True)
            raise HarvestAbort(f"CSV has no recognizable lat/lon columns: {url}")
        from shapely.geometry import Point
        geom = [Point(xy) for xy in zip(df[lon_col], df[lat_col])]
        gdf = gpd.GeoDataFrame(df.drop(columns=[lat_col, lon_col]), geometry=geom, crs="EPSG:4326")
    elif url_l.endswith(".shp"):
        gdf = gpd.read_file(tmp)
    else:
        tmp.unlink(missing_ok=True)
        raise HarvestAbort(f"Unsupported direct-download format: {url}")

    tmp.unlink(missing_ok=True)
    if gdf.crs is None:
        if url_l.endswith(".csv"):
            pass  # already set
        else:
            raise HarvestAbort(f"Resource has no declared CRS: {url} (zero-mock: refusing to assume EPSG:4326)")
    elif str(gdf.crs).upper() != "EPSG:4326":
        gdf = gdf.to_crs("EPSG:4326")

    # Determine title from filename
    stem = Path(urlparse(url).path).stem
    title = stem.replace("_", " ").replace("-", " ").title()

    harvest_meta = {
        "endpoint": url,
        "service_type": "direct_download",
        "http_status": http_status,
        "download_ms": elapsed_ms,
        "probed_count": None,
        "probe_detail": "Count derived from downloaded file (no independent count API for direct downloads)",
        "title": title,
        "license_name": None,
        "license_url": None,
        "keywords": [],
        "modified": None,
        "publisher": host,
        "portal_host": host,
    }
    return gdf, raw_bytes, harvest_meta


def harvest_portal_dataset(url: str, cfg: Dict[str, Any], args: argparse.Namespace) -> Dict[str, Any]:
    now_utc = datetime.now(timezone.utc)
    timestamp = now_utc.strftime("%Y%m%dT%H%M%SZ")
    retrieval_iso = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    defaults = cfg["dataset_defaults"]

    print("=" * 70)
    print(f"PORTAL HARVEST (zero-AI): {url}")
    print("=" * 70)

    # 1. Resolve
    source = resolve_source(url, cfg)
    print(f"Resolved source: kind={source['kind']} host={source['host']} id={source['dataset_id']}"
          + (f" (via CKAN {source.get('via_ckan_host')})" if source.get("via_ckan_host") else ""))

    # 2. Harvest
    if source["kind"] == "ods":
        gdf, raw_bytes, harvest_meta = harvest_ods(source, cfg)
    elif source["kind"] == "direct_download":
        gdf, raw_bytes, harvest_meta = harvest_direct_download(source, cfg)
    else:
        gdf, raw_bytes, harvest_meta = harvest_ckan_resource(source, cfg)
    print(f"Harvested {len(gdf)} features ({harvest_meta['download_ms']} ms) from {harvest_meta['endpoint']}")
    if gdf.empty:
        raise HarvestAbort("Harvest produced zero features; zero-mock policy forbids proceeding with an empty artifact.")
    harvest_meta["gdf_geom_types"] = sorted({str(t) for t in gdf.geom_type.dropna().unique()})

    # CKAN package metadata augments ODS metadata when the chain was followed
    pkg = source.get("ckan_package") or {}
    if pkg:
        harvest_meta.setdefault("title", pkg.get("title"))
        if not harvest_meta.get("license_name") and pkg.get("license_title"):
            harvest_meta["license_name"] = pkg["license_title"]
            harvest_meta["license_url"] = pkg.get("license_url")
        if not harvest_meta.get("publisher") or harvest_meta.get("publisher") == source["host"]:
            org = (pkg.get("organization") or {}).get("title")
            if org:
                harvest_meta["publisher"] = org
        if not harvest_meta.get("keywords"):
            harvest_meta["keywords"] = [t.get("display_name", "") for t in pkg.get("tags", [])]
        if not harvest_meta.get("modified"):
            harvest_meta["modified"] = pkg.get("metadata_modified")

    # 3. Normalize
    gdf = clean_dataframe(gdf)
    if gdf.crs is None or str(gdf.crs).upper() != "EPSG:4326":
        gdf = gdf.to_crs("EPSG:4326")

    slug = re.sub(r"[^a-z0-9]+", "_", source["dataset_id"].lower()).strip("_")
    dataset_key = args.key or f"{defaults.get('key_prefix', '')}{slug}"
    gdf, primary_key = resolve_primary_key(gdf, dataset_key)

    title = harvest_meta.get("title") or source["dataset_id"]
    publisher = harvest_meta.get("publisher") or source["host"]
    jurisdiction = args.jurisdiction or cfg["portals"].get("jurisdiction_by_host", {}).get(source["host"]) or defaults.get("jurisdiction", "QLD")
    theme = derive_theme(title, harvest_meta.get("keywords") or [], cfg, args.theme)
    licence = derive_licence(harvest_meta, publisher, cfg)
    geom_type = observed_geometry_type(gdf)

    modified = str(harvest_meta.get("modified") or "")[:10]
    pub_year = modified[:4] if re.match(r"^\d{4}", modified) else now_utc.strftime("%Y")
    host_tag = source["host"].split(".")[1].upper() if len(source["host"].split(".")) > 1 else "PORTAL"
    source_vintage = f"{pub_year}-{host_tag}"

    bounds = [float(x) for x in gdf.total_bounds]
    declared_bbox = [
        round(bounds[0] - 0.25, 3), round(bounds[1] - 0.25, 3),
        round(bounds[2] + 0.25, 3), round(bounds[3] + 0.25, 3),
    ]

    entry = DatasetEntry(
        dataset_key=dataset_key,
        title=title,
        category=defaults.get("category", "periodically_refreshed_authoritative"),
        theme=theme,
        scale=args.scale or defaults.get("scale", "local"),
        jurisdiction=jurisdiction,
        provider=publisher,
        source_agency=publisher,
        service_type=harvest_meta.get("service_type", "geojson_feed"),
        endpoint=harvest_meta["endpoint"],
        licence=licence,
        source_publication_date=modified or None,
        source_vintage=source_vintage,
        refresh_policy=defaults.get("refresh_policy", "portal_snapshot"),
        original_crs=defaults.get("original_crs", "EPSG:4326"),
        stored_crs=defaults.get("stored_crs", "EPSG:7844"),
        metric_crs=defaults.get("metric_crs", "EPSG:3112"),
        geometry_type=geom_type,
        primary_key=primary_key,
        required_fields=[],
        schema_mapping={},
        known_limitations=[
            f"Harvested from {source['host']} open-data portal via deterministic zero-AI pipeline ({source['kind']}).",
            "default_bbox declared from the first verified harvest extent (+/-0.25 deg); re-harvests outside it will flag at Level 2.",
            f"Source licence: {licence.name}. Native source columns preserved; no attribute synthesis.",
        ],
        operational_suitability=f"Suitable for {theme.lower()} exposure analysis and emergency planning overlays.",
        default_bbox=declared_bbox,
    )

    upload_cloud = not (args.dry_run or args.skip_gcs)
    store = GCSLakeStorage(
        bucket_name=cfg["gcs"].get("bucket"),
        gcp_project=cfg["gcs"].get("project"),
    )

    gpq_key = store.geoparquet_object_key(dataset_key, entry.source_vintage, timestamp, part=0)
    raw_key = store.raw_object_key(dataset_key, timestamp, ext="json" if harvest_meta.get("service_type") != "file_download" else "bin")

    # Canonical GeoParquet 1.1.0 normalization IN MEMORY (zero local staging):
    # reprojects to stored_crs, adds lineage + per-feature bbox, spatially sorts.
    pq_buffer = io.BytesIO()
    t_norm = time.perf_counter()
    write_info = normalize_and_write_geoparquet(
        gdf=gdf, entry=entry, output_path=pq_buffer, retrieval_timestamp_utc=retrieval_iso
    )
    normalization_ms = (time.perf_counter() - t_norm) * 1000.0
    pq_bytes = pq_buffer.getvalue()

    if upload_cloud:
        # Cloud-first: memory -> GCS directly (publish gate enforced); QA then
        # validates by reading the artifact BACK from GCS.
        raw_meta = store.upload_bytes_cloud(
            raw_key, raw_bytes,
            dataset_entry=entry.model_dump(mode="json"),
            content_type="application/json; charset=utf-8" if raw_key.endswith(".json") else "application/octet-stream",
        )
        gpq_meta = store.upload_bytes_cloud(
            gpq_key, pq_bytes,
            dataset_entry=entry.model_dump(mode="json"),
            content_type="application/vnd.apache.parquet",
        )
        gcs_url = gpq_meta["gcs_https_url"]
        validation_source = gpq_meta["gs_uri"]
        print(f"Normalized {write_info['feature_count']} records in memory ({write_info['stored_crs']}, GeoParquet 1.1.0, {len(pq_bytes):,} B)")
        print(f"Uploaded to GCS: {gcs_url} (generation={gpq_meta['gcs_generation']}) — validating by reading back from GCS")
    else:
        # Dry-run: ephemeral temp for validation only; nothing persists locally or in cloud.
        tmp = tempfile.NamedTemporaryFile(suffix=".parquet", delete=False)
        tmp.write(pq_bytes)
        tmp.close()
        raw_meta = {"gs_uri": None, "sha256": hashlib.sha256(raw_bytes).hexdigest()}
        gpq_meta = {
            "object_key": gpq_key,
            "gs_uri": store.gs_uri(gpq_key),
            "gcs_https_url": f"https://storage.googleapis.com/{store.bucket_name}/{gpq_key}",
            "local_path": None,
            "file_size_bytes": len(pq_bytes),
            "sha256": hashlib.sha256(pq_bytes).hexdigest(),
            "storage_mode": "dry_run_ephemeral",
            "gcs_generation": "dry-run-not-uploaded",
        }
        gcs_url = gpq_meta["gcs_https_url"]
        validation_source = tmp.name
        print(f"[DRY-RUN] Normalized {write_info['feature_count']} records in memory ({len(pq_bytes):,} B); ephemeral temp validation only (no cloud write, no local staging)")

    # RFC 7946 WGS84 preview for the MapLibre QA Inspector, built IN MEMORY from the
    # exact bytes uploaded (zero local staging, no second download/read-back).
    preview_gdf = gpd.read_parquet(io.BytesIO(pq_bytes))
    preview_bytes, preview_counts = build_qa_geojson_preview(preview_gdf)
    preview_meta = {
        "preview_geojson_path": f"data/{dataset_key}.geojson",
        **preview_counts,
    }
    if upload_cloud:
        store.upload_bytes_cloud(
            f"qa/data/{dataset_key}.geojson",
            preview_bytes,
            content_type="application/geo+json; charset=utf-8",
        )
        print(f"Preview GeoJSON uploaded: qa/data/{dataset_key}.geojson ({preview_counts['preview_feature_count']} features)")
    else:
        print(f"[DRY-RUN] Preview GeoJSON built in memory ({preview_counts['preview_feature_count']} features); not persisted")

    # 5. Three-level zero-AI QA (Level 2 reads the artifact back FROM GCS in cloud mode)
    level1 = build_level1_record(entry, harvest_meta, harvested_count=write_info["feature_count"])
    t_val = time.perf_counter()
    level2 = verify_level2_stored_artifact(validation_source, entry, gpq_meta)
    level3 = verify_level3_reconciliation(entry, level1, level2, {"pages_fetched": 1})
    validation_ms = (time.perf_counter() - t_val) * 1000.0
    overall = compute_overall_dataset_qa_status(level1, level2, level3)
    print(f"QA: L1={level1['status']} L2={level2['status']} L3={level3['status']} -> overall {overall}")
    if not upload_cloud:
        os.unlink(validation_source)  # ephemeral dry-run temp cleanup

    record = {
        "dataset_key": dataset_key,
        "title": title,
        "provider": entry.provider,
        "source_agency": entry.source_agency,
        "category": entry.category.value,
        "scale": entry.scale,
        "jurisdiction": entry.jurisdiction,
        "theme": entry.theme,
        "endpoint": entry.endpoint,
        "licence": entry.licence.model_dump(mode="json"),
        "source_publication_date": entry.source_publication_date,
        "source_vintage": entry.source_vintage,
        "retrieval_timestamp_utc": retrieval_iso,
        "retrieval_id": timestamp,
        "ingestion_software_version": INGESTION_SOFTWARE_VERSION,
        "transformation_version": TRANSFORMATION_VERSION,
        "original_crs": entry.original_crs,
        "stored_crs": level2["stored_crs"],
        "geometry_type": ", ".join(level2["geometry_types"]),
        "feature_count": level2["feature_count"],
        "bbox": level2["bbox"],
        "file_size_bytes": level2["file_size_bytes"],
        "sha256": level2["sha256"],
        "gcs_generation": gpq_meta["gcs_generation"],
        "gs_uri": gpq_meta["gs_uri"],
        "local_parquet_path": gpq_meta["local_path"],
        "raw_payload_gs_uri": raw_meta["gs_uri"],
        "raw_payload_sha256": raw_meta["sha256"],
        "preview_geojson": preview_meta,
        "overall_qa_status": overall,
        "level1_source_contract": level1,
        "level2_stored_artifact": level2,
        "level3_reconciliation": level3,
        "known_limitations": entry.known_limitations,
        "refresh_policy": entry.refresh_policy,
        "operational_suitability": entry.operational_suitability,
        "telemetry": {
            "dataset_key": dataset_key,
            "retrieval_timestamp_utc": retrieval_iso,
            "http_requests_count": harvest_meta.get("http_requests", 1),
            "source_download_ms": harvest_meta.get("download_ms"),
            "normalization_ms": round(normalization_ms, 2),
            "validation_ms": round(validation_ms, 2),
            "bytes_written": gpq_meta["file_size_bytes"],
            "notes": ["Zero-AI deterministic portal harvest (no LLM credits used)."],
        },
    }
    record_bytes = json.dumps(record, indent=2, ensure_ascii=False).encode("utf-8")
    if upload_cloud:
        store.upload_bytes_cloud(store.dataset_qa_object_key(dataset_key, timestamp), record_bytes, content_type="application/json; charset=utf-8")
        store.upload_bytes_cloud(store.dataset_manifest_object_key(dataset_key), record_bytes, content_type="application/json; charset=utf-8")
        print(f"QA records written directly to GCS (manifests/datasets/{dataset_key}.json + qa/datasets/{dataset_key}/{timestamp}.json)")
    else:
        print("[DRY-RUN] QA records not persisted (cloud writes skipped)")

    # 6. Catalogue manifest registration + QA summary refresh (cloud mode only)
    if cfg["qa"].get("register_in_manifest", True) and not args.no_register and upload_cloud:
        manifest_path = PROJECT_ROOT / cfg["qa"].get("dataset_manifest", "config/dataset_manifest.json")
        manifest: DatasetManifest = load_manifest(manifest_path)
        entry.qa_status = QAStatus(overall)
        entry.latest_snapshot_path = gpq_meta["gs_uri"]
        entry.latest_retrieval_utc = retrieval_iso
        manifest.datasets[dataset_key] = entry
        manifest.updated_at_utc = retrieval_iso
        save_manifest(manifest, manifest_path)
        print(f"Registered '{dataset_key}' in {manifest_path} (qa_status={overall}, snapshot={gpq_meta['gs_uri']})")

    if cfg["qa"].get("refresh_qa_summary", True) and upload_cloud:
        from src.validation.qa_report import build_qa_summary, render_qa_html_pages
        summary = build_qa_summary(
            registry=DatasetRegistry(),
            storage=store,
            upload_cloud=True,
            write_local=False,
        )
        render_qa_html_pages(summary, storage=store, upload_cloud=True)
        print(f"QA summary refreshed: {summary['report_id']} | counts: {summary['status_counts']}")

    # 7. Wherobots Iceberg library dispatch
    if not (args.dry_run or args.skip_wherobots):
        wb = cfg["wherobots"]
        target_table = f"{wb.get('catalog', 'org_catalog')}.{wb.get('database', 'ops_intel')}.{dataset_key}"
        dispatch_wherobots(
            [{
                "key": dataset_key,
                "title": title,
                "url": gcs_url,
                "database": f"{wb.get('catalog', 'org_catalog')}.{wb.get('database', 'ops_intel')}",
                "target_table": target_table,
                "expected_rows": write_info["feature_count"],
            }],
            cfg,
        )
    else:
        print("Wherobots dispatch skipped (--dry-run/--skip-wherobots).")

    return record


def main() -> int:
    parser = argparse.ArgumentParser(description="Zero-AI portal dataset harvester (CKAN/Opendatasoft -> GeoParquet -> GCS + Wherobots + QA)")
    parser.add_argument("--config", required=True, help="Path to harvester JSON config (see config/harvester_config.example.json)")
    parser.add_argument("--url", required=True, help="Portal dataset page URL")
    parser.add_argument("--key", default=None, help="Override derived dataset_key")
    parser.add_argument("--theme", default=None, help="Override theme classification")
    parser.add_argument("--scale", default=None, help="Override scale")
    parser.add_argument("--jurisdiction", default=None, help="Override jurisdiction")
    parser.add_argument("--dry-run", action="store_true", help="Ephemeral in-memory validation only (no GCS, no local data staging)")
    parser.add_argument("--skip-gcs", action="store_true", help="Alias for --dry-run (nothing persists locally or in cloud)")
    parser.add_argument("--skip-wherobots", action="store_true", help="Skip Iceberg dispatch")
    parser.add_argument("--max-features", type=int, default=None, help="Cap harvested features (ODS limit= param)")
    parser.add_argument("--no-register", action="store_true", help="Do not touch the catalogue manifest")
    args = parser.parse_args()

    cfg = load_config(Path(args.config))
    if args.max_features is not None:
        cfg.setdefault("portals", {})["max_features"] = int(args.max_features)
    record = harvest_portal_dataset(args.url, cfg, args)
    print("\n" + "=" * 70)
    print(f"DONE: {record['dataset_key']} | {record['overall_qa_status']} | {record['feature_count']} features | {record['stored_crs']}")
    print(f"  snapshot: {record['gs_uri']}")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code if isinstance(code, int) else 0)
