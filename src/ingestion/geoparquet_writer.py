"""GeoParquet 1.1.0 Writer with CRS Normalization, Spatial Ordering, and Metadata Enrichment."""

from pathlib import Path
from typing import Any, Dict, List, Optional
import geopandas as gpd
import pandas as pd

from src.catalogue.manifest_loader import DatasetEntry


def normalize_and_write_geoparquet(
    gdf: gpd.GeoDataFrame,
    entry: DatasetEntry,
    output_path: Path,
    retrieval_timestamp_utc: str,
) -> Dict[str, Any]:
    """Normalizes CRS to stored_crs (default EPSG:7844), adds canonical mapped columns while
    preserving all native source columns, sorts spatially for row-group pruning, and writes GeoParquet 1.1.0.
    """
    if gdf.empty:
        raise ValueError(
            f"Cannot write empty GeoDataFrame for {entry.dataset_key} — zero-mock rule prohibits empty/synthetic artifacts."
        )

    work = gdf.copy()
    if work.crs is None:
        work = work.set_crs(entry.original_crs or "EPSG:4326")

    target_crs = entry.stored_crs or "EPSG:7844"
    if str(work.crs).upper() != target_crs.upper():
        work = work.to_crs(target_crs)

    # Preserve native source fields and also expose canonical mapped aliases if configured (case-insensitive source lookup)
    col_lookup_lower = {c.lower(): c for c in work.columns}
    for canonical_col, source_col in (entry.schema_mapping or {}).items():
        actual_src = col_lookup_lower.get(source_col.lower())
        if actual_src and canonical_col not in work.columns:
            work[canonical_col] = work[actual_src]

    # Add lineage columns
    work["_oic_dataset_key"] = entry.dataset_key
    work["_oic_source_vintage"] = entry.source_vintage
    work["_oic_retrieval_utc"] = retrieval_timestamp_utc

    # Compute per-feature bounding box columns for fast SQL pushdown & spatial sorting
    bounds = work.geometry.bounds
    work["_bbox_minx"] = bounds["minx"]
    work["_bbox_miny"] = bounds["miny"]
    work["_bbox_maxx"] = bounds["maxx"]
    work["_bbox_maxy"] = bounds["maxy"]

    # Spatial ordering by rounded centroid grid for row-group locality
    work["_sort_x"] = ((bounds["minx"] + bounds["maxx"]) * 0.5).round(3)
    work["_sort_y"] = ((bounds["miny"] + bounds["maxy"]) * 0.5).round(3)
    work = work.sort_values(by=["_sort_y", "_sort_x"]).drop(columns=["_sort_x", "_sort_y"]).reset_index(drop=True)

    is_filelike = not isinstance(output_path, (str, Path))
    if not is_filelike:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    # Write GeoParquet 1.1.0 with WKB encoding and embedded PROJJSON CRS
    # (output_path may be a file-like buffer for cloud-first writes with zero local staging)
    work.to_parquet(
        output_path,
        index=False,
        compression="snappy",
        schema_version="1.1.0",
    )

    total_bounds: List[float] = [float(x) for x in work.total_bounds]
    geom_types = sorted({str(t) for t in work.geometry.geom_type.dropna().unique()})

    return {
        "feature_count": int(len(work)),
        "stored_crs": target_crs,
        "geometry_types": geom_types,
        "bbox": [round(x, 6) for x in total_bounds],
        "columns": [c for c in work.columns if c != "geometry"],
    }
