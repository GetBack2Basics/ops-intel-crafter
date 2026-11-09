"""GeoJSON Live Feed Connector (e.g., NSW RFS majorIncidents.json)."""

from typing import Any, Dict, List, Optional, Tuple
import geopandas as gpd
from shapely.geometry import GeometryCollection, shape

from src.catalogue.manifest_loader import DatasetEntry
from src.validation.source_contracts import _http_get, validate_payload_not_error_page


def _normalize_geometry_collection(geom: Any) -> Any:
    """Extracts the primary polygon or point from a GeometryCollection so GeoParquet consumers can index it."""
    if geom is None:
        return None
    if isinstance(geom, GeometryCollection):
        polys = [g for g in geom.geoms if g.geom_type in ("Polygon", "MultiPolygon") and not g.is_empty]
        if polys:
            return polys[0]
        lines = [g for g in geom.geoms if g.geom_type in ("LineString", "MultiLineString") and not g.is_empty]
        if lines:
            return lines[0]
        pts = [g for g in geom.geoms if g.geom_type in ("Point", "MultiPoint") and not g.is_empty]
        if pts:
            return pts[0]
        return None
    return geom


def fetch_geojson_feed(
    entry: DatasetEntry,
    bbox: Optional[List[float]] = None,
) -> Tuple[gpd.GeoDataFrame, bytes, Dict[str, Any]]:
    """Fetches a live GeoJSON FeatureCollection feed and normalizes GeometryCollections."""
    resp = _http_get(entry.endpoint, timeout=30)
    if not resp["ok"]:
        raise RuntimeError(f"GeoJSON feed fetch failed for {entry.dataset_key}: {resp['error']}")

    check = validate_payload_not_error_page(
        resp["http_status"], resp["content_type"], resp["text"]
    )
    if not check["valid"]:
        raise RuntimeError(
            f"GeoJSON feed contract failure for {entry.dataset_key}: {check['reason']}"
        )

    fc = check["parsed"]
    features = fc.get("features", []) if isinstance(fc, dict) else []

    rows: List[Dict[str, Any]] = []
    geoms: List[Any] = []
    geometry_collections_unpacked = 0

    for feat in features:
        props = dict(feat.get("properties") or {})
        raw_geom = feat.get("geometry")
        geom_obj = shape(raw_geom) if raw_geom else None
        if isinstance(geom_obj, GeometryCollection):
            geometry_collections_unpacked += 1
            props["_original_geom_type"] = "GeometryCollection"
            props["_sub_geometry_count"] = len(geom_obj.geoms)
            geom_obj = _normalize_geometry_collection(geom_obj)
        elif geom_obj is not None:
            props["_original_geom_type"] = geom_obj.geom_type
            props["_sub_geometry_count"] = 1
        rows.append(props)
        geoms.append(geom_obj)

    if rows:
        gdf = gpd.GeoDataFrame(rows, geometry=geoms, crs=entry.original_crs or "EPSG:4326")
    else:
        gdf = gpd.GeoDataFrame({"geometry": []}, geometry="geometry", crs=entry.original_crs or "EPSG:4326")

    effective_bbox = bbox if bbox is not None else entry.default_bbox
    if effective_bbox and len(gdf) > 0:
        minx, miny, maxx, maxy = effective_bbox
        gdf = gdf.cx[minx:maxx, miny:maxy].copy()

    meta = {
        "pages_fetched": 1,
        "http_requests": 1,
        "bytes_downloaded": len(resp["raw_bytes"]),
        "raw_feature_count": len(features),
        "geometry_collections_unpacked": geometry_collections_unpacked,
        "query_bbox": effective_bbox,
    }
    return gdf, resp["raw_bytes"], meta

