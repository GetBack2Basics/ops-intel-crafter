"""Level 1 Validation — Source Contract Verifier.

Verifies:
1. Endpoint resolves (no DNS / socket failure).
2. HTTP status is 200 OK.
3. Content-Type is expected JSON / GeoJSON (not an HTML landing or block page).
4. Payload is not an embedded error object (e.g., ArcGIS 200 OK with {"error": {"code": 499, "message": "Token Required"}}).
5. Expected geometry type and required fields are present.
6. Source record count is probed and recorded.
"""

import json
import ssl
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from src.catalogue.manifest_loader import DatasetEntry, QAStatus

ESRI_TO_CANONICAL_GEOM = {
    "esrigeometrypoint": "Point",
    "esrigeometrymultipoint": "MultiPoint",
    "esrigeometrypolyline": "LineString",
    "esrigeometrypolygon": "Polygon",
}


def _http_get(url: str, timeout: int = 25) -> Dict[str, Any]:
    ctx = ssl.create_default_context()
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "OperationalIntelligenceCrafter/0.2 (GeospatialQA; +https://github.com/GetBack2Basics)",
            "Accept": "application/json, application/geo+json, */*",
        },
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw_bytes = resp.read()
            elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            return {
                "ok": True,
                "http_status": resp.status,
                "content_type": resp.headers.get("Content-Type", ""),
                "final_url": resp.geturl(),
                "elapsed_ms": elapsed_ms,
                "raw_bytes": raw_bytes,
                "text": raw_bytes.decode("utf-8", errors="replace"),
                "error": None,
            }
    except urllib.error.HTTPError as he:
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        body = ""
        try:
            body = he.read(2048).decode("utf-8", errors="replace")
        except Exception:
            pass
        return {
            "ok": False,
            "http_status": he.code,
            "content_type": he.headers.get("Content-Type", "") if he.headers else "",
            "final_url": url,
            "elapsed_ms": elapsed_ms,
            "raw_bytes": b"",
            "text": body,
            "error": f"HTTPError {he.code}: {he.reason}",
        }
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        return {
            "ok": False,
            "http_status": None,
            "content_type": "",
            "final_url": url,
            "elapsed_ms": elapsed_ms,
            "raw_bytes": b"",
            "text": "",
            "error": f"{type(exc).__name__}: {exc}",
        }


def validate_payload_not_error_page(
    http_status: Optional[int], content_type: str, text: str
) -> Dict[str, Any]:
    """Detects HTTP errors, HTML landing/block pages, and ArcGIS 200-OK embedded error payloads."""
    if http_status != 200:
        return {
            "valid": False,
            "reason": f"Expected HTTP 200, got {http_status}",
            "embedded_error": None,
        }

    stripped = text.lstrip()
    ct_lower = (content_type or "").lower()
    if "text/html" in ct_lower or stripped.lower().startswith(("<!doctype html", "<html")):
        return {
            "valid": False,
            "reason": f"Endpoint returned HTML page instead of structured spatial data (Content-Type: {content_type})",
            "embedded_error": stripped[:300],
        }

    try:
        parsed = json.loads(text)
    except Exception as exc:
        return {
            "valid": False,
            "reason": f"Response is not valid JSON/GeoJSON: {exc}",
            "embedded_error": stripped[:300],
        }

    if isinstance(parsed, dict) and "error" in parsed and parsed["error"]:
        err_obj = parsed["error"]
        code = err_obj.get("code") if isinstance(err_obj, dict) else "unknown"
        msg = err_obj.get("message") if isinstance(err_obj, dict) else str(err_obj)
        return {
            "valid": False,
            "reason": f"Embedded service error in HTTP 200 payload (code={code}): {msg}",
            "embedded_error": err_obj,
        }

    return {"valid": True, "reason": "OK", "parsed": parsed}


def verify_level1_source_contract(
    entry: DatasetEntry,
    bbox: Optional[List[float]] = None,
) -> Dict[str, Any]:
    """Executes Level 1 Source Contract validation against a live endpoint."""
    checks: List[Dict[str, Any]] = []
    effective_bbox = bbox if bbox is not None else entry.default_bbox

    if entry.service_type in ("arcgis_mapserver", "arcgis_featureserver"):
        meta_url = f"{entry.endpoint.rstrip('/')}?f=json"
        resp = _http_get(meta_url)
        checks.append(
            {
                "check": "endpoint_reachable",
                "status": "PASS" if resp["ok"] else "FAIL",
                "detail": f"HTTP {resp['http_status']} ({resp['elapsed_ms']} ms)",
            }
        )
        if not resp["ok"]:
            return {
                "level": 1,
                "level_name": "Source Contract",
                "status": QAStatus.FAIL.value,
                "endpoint": entry.endpoint,
                "http_status": resp["http_status"],
                "content_type": resp["content_type"],
                "latency_ms": resp["elapsed_ms"],
                "source_feature_count": None,
                "error_message": resp["error"],
                "checks": checks,
            }

        payload_check = validate_payload_not_error_page(
            resp["http_status"], resp["content_type"], resp["text"]
        )
        if not payload_check["valid"]:
            checks.append(
                {
                    "check": "not_embedded_error_or_html",
                    "status": "FAIL",
                    "detail": payload_check["reason"],
                }
            )
            return {
                "level": 1,
                "level_name": "Source Contract",
                "status": QAStatus.FAIL.value,
                "endpoint": entry.endpoint,
                "http_status": resp["http_status"],
                "content_type": resp["content_type"],
                "latency_ms": resp["elapsed_ms"],
                "source_feature_count": None,
                "error_message": payload_check["reason"],
                "checks": checks,
            }

        checks.append(
            {
                "check": "not_embedded_error_or_html",
                "status": "PASS",
                "detail": "Valid ArcGIS Layer JSON metadata returned.",
            }
        )
        meta = payload_check["parsed"]
        layer_name = meta.get("name", "")
        esri_geom = (meta.get("geometryType") or "").lower()
        canonical_geom = ESRI_TO_CANONICAL_GEOM.get(esri_geom, meta.get("geometryType") or "Unknown")
        max_record_count = meta.get("maxRecordCount", 1000)

        geom_ok = (
            entry.geometry_type.lower() in canonical_geom.lower()
            or canonical_geom.lower() in entry.geometry_type.lower()
            or entry.geometry_type.lower() == "geometry"
        )
        checks.append(
            {
                "check": "geometry_type_contract",
                "status": "PASS" if geom_ok else "FAIL",
                "detail": f"Layer '{layer_name}' reports {meta.get('geometryType')} (canonical: {canonical_geom}, expected: {entry.geometry_type})",
            }
        )

        # Check required fields against layer field catalogue
        layer_fields = {f.get("name", ""): f.get("type", "") for f in meta.get("fields", [])}
        layer_fields_lower = {k.lower(): k for k in layer_fields}
        missing_fields = [
            req for req in entry.required_fields if req.lower() not in layer_fields_lower
        ]
        checks.append(
            {
                "check": "required_fields_present",
                "status": "PASS" if not missing_fields else "FAIL",
                "detail": (
                    f"All {len(entry.required_fields)} required fields verified ({', '.join(entry.required_fields)})"
                    if not missing_fields
                    else f"Missing required fields: {missing_fields}"
                ),
            }
        )

        # Probe source feature count for the query scope (bbox or 1=1)
        count_params = {"where": "1=1", "returnCountOnly": "true", "f": "json"}
        if effective_bbox:
            count_params["geometry"] = ",".join(str(x) for x in effective_bbox)
            count_params["geometryType"] = "esriGeometryEnvelope"
            count_params["inSR"] = "4326"
            count_params["spatialRel"] = "esriSpatialRelIntersects"

        count_url = f"{entry.endpoint.rstrip('/')}/query?{urllib.parse.urlencode(count_params)}"
        count_resp = _http_get(count_url)
        source_count: Optional[int] = None
        if count_resp["ok"]:
            c_check = validate_payload_not_error_page(
                count_resp["http_status"], count_resp["content_type"], count_resp["text"]
            )
            if c_check["valid"]:
                source_count = c_check["parsed"].get("count")

        count_status = "PASS" if (source_count is not None and source_count > 0) else "WARNING"
        checks.append(
            {
                "check": "source_feature_count_probe",
                "status": count_status,
                "detail": f"Source reports {source_count} features in query scope (maxRecordCount={max_record_count})",
            }
        )

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
            "layer_name": layer_name,
            "http_status": resp["http_status"],
            "content_type": resp["content_type"],
            "latency_ms": round(resp["elapsed_ms"] + count_resp.get("elapsed_ms", 0.0), 2),
            "max_record_count": max_record_count,
            "source_feature_count": source_count,
            "query_bbox": effective_bbox,
            "available_fields": list(layer_fields.keys()),
            "error_message": None if overall != QAStatus.FAIL.value else "Level 1 contract check failed",
            "checks": checks,
        }

    elif entry.service_type == "geojson_feed":
        resp = _http_get(entry.endpoint)
        checks.append(
            {
                "check": "endpoint_reachable",
                "status": "PASS" if resp["ok"] else "FAIL",
                "detail": f"HTTP {resp['http_status']} ({resp['elapsed_ms']} ms)",
            }
        )
        if not resp["ok"]:
            return {
                "level": 1,
                "level_name": "Source Contract",
                "status": QAStatus.FAIL.value,
                "endpoint": entry.endpoint,
                "http_status": resp["http_status"],
                "content_type": resp["content_type"],
                "latency_ms": resp["elapsed_ms"],
                "source_feature_count": None,
                "error_message": resp["error"],
                "checks": checks,
            }

        payload_check = validate_payload_not_error_page(
            resp["http_status"], resp["content_type"], resp["text"]
        )
        if not payload_check["valid"]:
            checks.append(
                {
                    "check": "not_embedded_error_or_html",
                    "status": "FAIL",
                    "detail": payload_check["reason"],
                }
            )
            return {
                "level": 1,
                "level_name": "Source Contract",
                "status": QAStatus.FAIL.value,
                "endpoint": entry.endpoint,
                "http_status": resp["http_status"],
                "content_type": resp["content_type"],
                "latency_ms": resp["elapsed_ms"],
                "source_feature_count": None,
                "error_message": payload_check["reason"],
                "checks": checks,
            }

        fc = payload_check["parsed"]
        features = fc.get("features", []) if isinstance(fc, dict) else []
        checks.append(
            {
                "check": "geojson_feature_collection",
                "status": "PASS" if fc.get("type") == "FeatureCollection" else "FAIL",
                "detail": f"GeoJSON type={fc.get('type')!r}, features={len(features)}",
            }
        )

        sample_props = features[0].get("properties", {}) if features else {}
        missing_fields = [
            req for req in entry.required_fields if req not in sample_props
        ] if features else []
        checks.append(
            {
                "check": "required_fields_present",
                "status": "PASS" if not missing_fields else "FAIL",
                "detail": (
                    f"Verified required fields ({', '.join(entry.required_fields)})"
                    if not missing_fields
                    else f"Missing required fields in GeoJSON properties: {missing_fields}"
                ),
            }
        )

        overall = (
            QAStatus.FAIL.value
            if any(c["status"] == "FAIL" for c in checks)
            else QAStatus.PASS.value
        )
        return {
            "level": 1,
            "level_name": "Source Contract",
            "status": overall,
            "endpoint": entry.endpoint,
            "layer_name": entry.title,
            "http_status": resp["http_status"],
            "content_type": resp["content_type"],
            "latency_ms": resp["elapsed_ms"],
            "source_feature_count": len(features),
            "query_bbox": effective_bbox,
            "available_fields": list(sample_props.keys()),
            "error_message": None if overall != QAStatus.FAIL.value else "GeoJSON contract check failed",
            "checks": checks,
            "_raw_bytes": resp["raw_bytes"],
        }

    else:
        return {
            "level": 1,
            "level_name": "Source Contract",
            "status": QAStatus.NOT_TESTED.value,
            "endpoint": entry.endpoint,
            "http_status": None,
            "content_type": None,
            "latency_ms": 0.0,
            "source_feature_count": None,
            "error_message": f"Unsupported service_type for Level 1 probe: {entry.service_type}",
            "checks": [],
        }

