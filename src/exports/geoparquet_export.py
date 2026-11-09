"""GeoParquet 1.1.0 Deliverable Exporter for Analytical Results."""

from pathlib import Path
from typing import Any, Dict

import geopandas as gpd

from src.ingestion.telemetry import compute_sha256


def export_analysis_geoparquet(
    gdf: gpd.GeoDataFrame,
    output_parquet_path: Path,
    stored_crs: str = "EPSG:7844",
) -> Dict[str, Any]:
    """Writes an analytical GeoDataFrame to GeoParquet 1.1.0 in `stored_crs`."""
    if gdf.empty:
        raise ValueError("Cannot export empty GeoDataFrame to GeoParquet.")

    work = gdf.copy()
    if work.crs is None:
        work = work.set_crs(stored_crs)
    elif str(work.crs).upper() != stored_crs.upper():
        work = work.to_crs(stored_crs)

    output_parquet_path.parent.mkdir(parents=True, exist_ok=True)
    work.to_parquet(output_parquet_path, index=False, schema_version="1.1.0")
    return {
        "parquet_path": str(output_parquet_path),
        "parquet_size_bytes": output_parquet_path.stat().st_size,
        "parquet_sha256": compute_sha256(output_parquet_path),
        "row_count": len(work),
        "crs": stored_crs,
    }

