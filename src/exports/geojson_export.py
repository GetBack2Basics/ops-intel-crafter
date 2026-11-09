"""RFC 7946 GeoJSON Exporter for GeoLibre and QGIS Interoperability (Section 10)."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import geopandas as gpd
from shapely.geometry import mapping, shape

from src.ingestion.telemetry import compute_sha256, utc_now_iso


def export_rfc7946_geojson(
    gdf: gpd.GeoDataFrame,
    output_geojson_path: Path,
    analysis_id: str,
    title: str,
    source_datasets: List[str],
    source_vintages: Dict[str, str],
    population_method: str = "NOT_APPLICABLE",
    known_limitations: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Exports a GeoDataFrame as an RFC 7946 compliant GeoJSON FeatureCollection in EPSG:4326
    with top-level `bbox`, preserved feature properties, and embedded provenance metadata,
    plus a sidecar `analysis_manifest.json`.
    """
    if gdf.empty:
        raise ValueError(f"Cannot export empty GeoDataFrame for analysis '{analysis_id}'.")

    work = gdf.copy()
    if work.crs is None:
        work = work.set_crs("EPSG:7844")
    work_4326 = work.to_crs("EPSG:4326")

    # Filter out null or empty geometries
    work_4326 = work_4326[work_4326.geometry.notna() & ~work_4326.geometry.is_empty].copy()
    if work_4326.empty:
        raise ValueError(f"No valid geometries remaining for analysis '{analysis_id}'.")

    minx, miny, maxx, maxy = [round(float(v), 6) for v in work_4326.total_bounds]
    bbox = [minx, miny, maxx, maxy]

    prop_cols = [c for c in work_4326.columns if c != work_4326.geometry.name]
    features: List[Dict[str, Any]] = []
    geom_types = set()

    for idx, row in work_4326.iterrows():
        geom = row[work_4326.geometry.name]
        geom_dict = mapping(geom)
        geom_types.add(geom_dict.get("type", "Unknown"))
        props: Dict[str, Any] = {}
        for c in prop_cols:
            val = row[c]
            if hasattr(val, "item"):
                val = val.item()
            if val != val:  # NaN check
                val = None
            props[c] = val

        features.append(
            {
                "type": "Feature",
                "id": str(props.get("cell_id") or props.get("substation_id") or props.get("objectid") or idx),
                "properties": props,
                "geometry": geom_dict,
            }
        )

    generated_utc = utc_now_iso()
    provenance = {
        "analysis_id": analysis_id,
        "title": title,
        "generated_at_utc": generated_utc,
        "rfc7946_crs": "EPSG:4326",
        "source_datasets": source_datasets,
        "source_vintages": source_vintages,
        "population_method": population_method,
        "feature_count": len(features),
        "geometry_types": sorted(geom_types),
        "bbox": bbox,
        "known_limitations": known_limitations or [],
        "geolibre_qgis_compatible": True,
    }

    fc = {
        "type": "FeatureCollection",
        "name": analysis_id,
        "bbox": bbox,
        "oic_provenance": provenance,
        "features": features,
    }

    output_geojson_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_geojson_path, "w", encoding="utf-8") as f:
        json.dump(fc, f, indent=2)

    sha256 = compute_sha256(output_geojson_path)
    provenance["geojson_sha256"] = sha256
    provenance["geojson_size_bytes"] = output_geojson_path.stat().st_size

    manifest_path = output_geojson_path.parent / "analysis_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(provenance, f, indent=2)

    return provenance

