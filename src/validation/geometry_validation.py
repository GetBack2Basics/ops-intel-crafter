"""Geometry & Primary-Key Integrity Validator for GeoParquet Datasets."""

from typing import Any, Dict, Optional
import geopandas as gpd


def validate_geodataframe_geometries(
    gdf: gpd.GeoDataFrame,
    primary_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Measures null geometries, empty geometries, invalid geometries (ST_IsValid), and duplicate primary keys."""
    total = int(len(gdf))
    if total == 0:
        return {
            "total_rows": 0,
            "null_geometry_count": 0,
            "empty_geometry_count": 0,
            "invalid_geometry_count": 0,
            "valid_geometry_rate_pct": 0.0,
            "duplicate_id_count": 0,
            "geometry_types": [],
        }

    null_mask = gdf.geometry.isna()
    null_count = int(null_mask.sum())

    non_null_geoms = gdf.geometry[~null_mask]
    empty_count = int(non_null_geoms.is_empty.sum()) if len(non_null_geoms) > 0 else 0
    invalid_count = int((~non_null_geoms.is_valid).sum()) if len(non_null_geoms) > 0 else 0

    valid_count = total - null_count - empty_count - invalid_count
    valid_rate = round((max(valid_count, 0) / total) * 100.0, 2)

    dup_count = 0
    resolved_pk = None
    if primary_key:
        for col in gdf.columns:
            if col.lower() == primary_key.lower():
                resolved_pk = col
                break
        if resolved_pk:
            dup_count = int(gdf[resolved_pk].duplicated().sum())

    geom_types = sorted({str(t) for t in non_null_geoms.geom_type.dropna().unique()})

    return {
        "total_rows": total,
        "null_geometry_count": null_count,
        "empty_geometry_count": empty_count,
        "invalid_geometry_count": invalid_count,
        "valid_geometry_count": valid_count,
        "valid_geometry_rate_pct": valid_rate,
        "primary_key_checked": resolved_pk,
        "duplicate_id_count": dup_count,
        "geometry_types": geom_types,
    }

