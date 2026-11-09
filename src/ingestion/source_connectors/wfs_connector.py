"""OGC Web Feature Service (WFS 2.0.0) GeoJSON Connector."""

import urllib.parse
from typing import Any, Dict, List, Optional, Tuple
import geopandas as gpd
from shapely.geometry import shape

from src.catalogue.manifest_loader import DatasetEntry
from src.validation.source_contracts import _http_get, validate_payload_not_error_page


def fetch_wfs_layer(
    entry: DatasetEntry,
    bbox: Optional[List[float]] = None,
    count: int = 5000,
) -> Tuple[gpd.GeoDataFrame, bytes, Dict[str, Any]]:
    """Fetches features from an OGC WFS 2.0.0 endpoint requesting GeoJSON output."""
    effective_bbox = bbox if bbox is not None else entry.default_bbox
    params: Dict[str, str] = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": entry.wfs_type_name or entry.dataset_key,
        "outputFormat": "application/json",
        "srsName": "EPSG:4326",
        "count": str(count),
    }
    if effective_bbox:
        params["bbox"] = ",".join(str(x) for x in effective_bbox) + ",EPSG:4326"

    sep = "&" if "?" in entry.endpoint else "?"
    url = f"{entry.endpoint}{sep}{urllib.parse.urlencode(params)}"
    resp = _http_get(url, timeout=45)
    if not resp["ok"]:
        raise RuntimeError(f"WFS GetFeature failed for {entry.dataset_key}: {resp['error']}")

    check = validate_payload_not_error_page(
        resp["http_status"], resp["content_type"], resp["text"]
    )
    if not check["valid"]:
        raise RuntimeError(f"WFS payload contract failure for {entry.dataset_key}: {check['reason']}")

    fc = check["parsed"]
    features = fc.get("features", []) if isinstance(fc, dict) else []
    rows = [dict(f.get("properties") or {}) for f in features]
    geoms = [shape(f["geometry"]) if f.get("geometry") else None for f in features]

    gdf = (
        gpd.GeoDataFrame(rows, geometry=geoms, crs="EPSG:4326")
        if rows
        else gpd.GeoDataFrame({"geometry": []}, geometry="geometry", crs="EPSG:4326")
    )
    meta = {
        "pages_fetched": 1,
        "http_requests": 1,
        "bytes_downloaded": len(resp["raw_bytes"]),
        "raw_feature_count": len(features),
        "query_bbox": effective_bbox,
    }
    return gdf, resp["raw_bytes"], meta

