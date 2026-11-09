"""Schema and GeoParquet metadata inspector for stored and live datasets."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import pyarrow.parquet as pq


def inspect_parquet_schema_and_geo_metadata(parquet_path: Path) -> Dict[str, Any]:
    """Reads Parquet footer and GeoParquet 'geo' metadata without loading full data into memory."""
    if not parquet_path.exists():
        raise FileNotFoundError(f"Parquet file not found: {parquet_path}")

    file_size = parquet_path.stat().st_size
    if file_size < 12:
        raise ValueError(f"Parquet file is too small ({file_size} bytes): {parquet_path}")

    with open(parquet_path, "rb") as f:
        head_magic = f.read(4)
        f.seek(-4, 2)
        tail_magic = f.read(4)

    if head_magic != b"PAR1" or tail_magic != b"PAR1":
        raise ValueError(f"Invalid Parquet magic bytes in {parquet_path} (head={head_magic!r}, tail={tail_magic!r})")

    pf = pq.ParquetFile(parquet_path)
    schema = pf.schema_arrow
    metadata = schema.metadata or {}

    columns: List[Dict[str, str]] = []
    for i in range(len(schema)):
        field = schema.field(i)
        columns.append({"name": field.name, "type": str(field.type), "nullable": field.nullable})

    geo_meta: Optional[Dict[str, Any]] = None
    if b"geo" in metadata:
        geo_meta = json.loads(metadata[b"geo"].decode("utf-8"))

    return {
        "file_path": str(parquet_path),
        "file_size_bytes": file_size,
        "num_rows": pf.metadata.num_rows,
        "num_row_groups": pf.metadata.num_row_groups,
        "columns": columns,
        "has_geo_metadata": geo_meta is not None,
        "geo_metadata": geo_meta,
    }

