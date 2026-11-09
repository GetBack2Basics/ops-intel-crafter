"""ArcGIS REST (MapServer / FeatureServer) Connector with Pagination and Esri-JSON/GeoJSON Support."""

import json
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

import geopandas as gpd
from shapely.geometry import LineString, MultiLineString, MultiPolygon, Point, Polygon, shape

from src.catalogue.manifest_loader import DatasetEntry
from src.validation.source_contracts import _http_get, validate_payload_not_error_page


def _esri_geom_to_shapely(esri_geom: Optional[Dict[str, Any]]) -> Any:
    """Converts Esri JSON geometry (x/y, paths, rings) to a Shapely geometry."""
    if not esri_geom or not isinstance(esri_geom, dict):
        return None
    if "x" in esri_geom and "y" in esri_geom:
        if esri_geom["x"] is None or esri_geom["y"] is None:
            return None
        return Point(float(esri_geom["x"]), float(esri_geom["y"]))
    if "paths" in esri_geom:
        paths = esri_geom["paths"]
        if not paths:
            return None
        lines = [LineString(p) for p in paths if len(p) >= 2]
        if not lines:
            return None
        return lines[0] if len(lines) == 1 else MultiLineString(lines)
    if "rings" in esri_geom:
        rings = esri_geom["rings"]
        if not rings:
            return None
        polys = [Polygon(r) for r in rings if len(r) >= 3]
        if not polys:
            return None
        return polys[0] if len(polys) == 1 else MultiPolygon(polys)
    return None


def fetch_arcgis_layer(
    entry: DatasetEntry,
    bbox: Optional[List[float]] = None,
    max_pages: int = 100,
    page_size: int = 1000,
) -> Tuple[gpd.GeoDataFrame, bytes, Dict[str, Any]]:
    """Fetches features from an ArcGIS MapServer or FeatureServer layer with pagination."""
    effective_bbox = bbox if bbox is not None else entry.default_bbox
    all_features: List[Dict[str, Any]] = []
    raw_pages: List[Dict[str, Any]] = []
    offset = 0
    pages_fetched = 0
    total_bytes = 0

    while pages_fetched < max_pages:
        params: Dict[str, str] = {
            "where": "1=1",
            "outFields": "*",
            "returnGeometry": "true",
            "outSR": "4326",
            "f": "geojson",
            "resultOffset": str(offset),
            "resultRecordCount": str(page_size),
        }
        if effective_bbox:
            params["geometry"] = ",".join(str(x) for x in effective_bbox)
            params["geometryType"] = "esriGeometryEnvelope"
            params["inSR"] = "4326"
            params["spatialRel"] = "esriSpatialRelIntersects"

        query_url = f"{entry.endpoint.rstrip('/')}/query?{urllib.parse.urlencode(params)}"
        resp = _http_get(query_url, timeout=45)
        if not resp["ok"]:
            raise RuntimeError(
                f"ArcGIS query failed for {entry.dataset_key} at offset {offset}: {resp['error']}"
            )

        check = validate_payload_not_error_page(
            resp["http_status"], resp["content_type"], resp["text"]
        )
        if not check["valid"]:
            # Fallback to f=json if an older ArcGIS service rejects f=geojson or resultOffset
            if offset == 0 and params.get("f") == "geojson":
                params["f"] = "json"
                params.pop("resultOffset", None)
                params.pop("resultRecordCount", None)
                fallback_url = f"{entry.endpoint.rstrip('/')}/query?{urllib.parse.urlencode(params)}"
                resp = _http_get(fallback_url, timeout=45)
                check = validate_payload_not_error_page(
                    resp["http_status"], resp["content_type"], resp["text"]
                )
            if not check["valid"]:
                raise RuntimeError(
                    f"ArcGIS payload contract failure for {entry.dataset_key}: {check['reason']}"
                )

        total_bytes += len(resp["raw_bytes"])
        parsed = check["parsed"]
        raw_pages.append(parsed)
        pages_fetched += 1

        if parsed.get("type") == "FeatureCollection":
            batch = parsed.get("features", [])
            all_features.extend(batch)
            exceeded = parsed.get("exceededTransferLimit", False)
            if len(batch) < page_size and not exceeded:
                break
            offset += len(batch)
            if len(batch) == 0:
                break
        elif "features" in parsed:
            # Esri JSON format
            batch = parsed.get("features", [])
            for feat in batch:
                attrs = feat.get("attributes", {})
                geom = _esri_geom_to_shapely(feat.get("geometry"))
                all_features.append(
                    {
                        "type": "Feature",
                        "properties": attrs,
                        "geometry": geom.__geo_interface__ if geom is not None else None,
                    }
                )
            exceeded = parsed.get("exceededTransferLimit", False)
            if len(batch) < page_size and not exceeded:
                break
            offset += len(batch)
            if len(batch) == 0:
                break
        else:
            break

    rows: List[Dict[str, Any]] = []
    geoms: List[Any] = []
    for feat in all_features:
        props = dict(feat.get("properties") or {})
        raw_geom = feat.get("geometry")
        geom_obj = shape(raw_geom) if raw_geom else None
        rows.append(props)
        geoms.append(geom_obj)

    if rows:
        gdf = gpd.GeoDataFrame(rows, geometry=geoms, crs="EPSG:4326")
    else:
        gdf = gpd.GeoDataFrame({"geometry": []}, geometry="geometry", crs="EPSG:4326")

    combined_raw = json.dumps(
        {
            "dataset_key": entry.dataset_key,
            "endpoint": entry.endpoint,
            "query_bbox": effective_bbox,
            "pages_fetched": pages_fetched,
            "feature_count": len(all_features),
            "features": all_features,
        }
    ).encode("utf-8")

    meta = {
        "pages_fetched": pages_fetched,
        "http_requests": pages_fetched,
        "bytes_downloaded": total_bytes,
        "raw_feature_count": len(all_features),
        "query_bbox": effective_bbox,
    }
    return gdf, combined_raw, meta

