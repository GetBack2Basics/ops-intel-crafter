"""Schema and GeoParquet metadata inspector for stored and live datasets.

Supports local paths AND cloud URIs (gs://, https://) so validation can run
directly against canonical GCS artifacts (cloud-first execution).
"""

import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
import pyarrow.parquet as pq


def _open_parquet_source(parquet_path: Any) -> Tuple[bool, int, Optional[Callable[[], Any]]]:
    """Resolves a local path or cloud URI to (exists, size_bytes, opener).

    opener returns a readable binary file-like object (or the local Path for pyarrow).
    """
    s = str(parquet_path)
    if s.startswith(("gs://", "https://", "http://")):
        import fsspec
        if s.startswith("gs://"):
            fs = fsspec.filesystem("gcs")
            path = s[len("gs://"):]
        else:
            fs = fsspec.filesystem("https")
            path = s
        try:
            info = fs.info(path)
        except Exception:
            return False, 0, None
        return True, int(info.get("size") or 0), (lambda: fs.open(path, "rb"))
    p = Path(parquet_path)
    if not p.exists():
        return False, 0, None
    return True, p.stat().st_size, (lambda: p)


def inspect_parquet_schema_and_geo_metadata(parquet_path: Any) -> Dict[str, Any]:
    """Reads Parquet footer and GeoParquet 'geo' metadata without loading full data into memory."""
    exists, file_size, opener = _open_parquet_source(parquet_path)
    if not exists:
        raise FileNotFoundError(f"Parquet file not found: {parquet_path}")

    if file_size and file_size < 12:
        raise ValueError(f"Parquet file is too small ({file_size} bytes): {parquet_path}")

    opened = opener()
    try:
        if hasattr(opened, "read"):
            with opened as f:
                head_magic = f.read(4)
                f.seek(-4, 2)
                tail_magic = f.read(4)
        else:
            with open(opened, "rb") as f:
                head_magic = f.read(4)
                f.seek(-4, 2)
                tail_magic = f.read(4)
    finally:
        pass

    if head_magic != b"PAR1" or tail_magic != b"PAR1":
        raise ValueError(f"Invalid Parquet magic bytes in {parquet_path} (head={head_magic!r}, tail={tail_magic!r})")

    source = opener()
    if hasattr(source, "read"):
        with source as f:
            pf = pq.ParquetFile(f)
            schema = pf.schema_arrow
            num_rows = pf.metadata.num_rows
            num_row_groups = pf.metadata.num_row_groups
    else:
        pf = pq.ParquetFile(source)
        schema = pf.schema_arrow
        num_rows = pf.metadata.num_rows
        num_row_groups = pf.metadata.num_row_groups
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
        "num_rows": num_rows,
        "num_row_groups": num_row_groups,
        "columns": columns,
        "has_geo_metadata": geo_meta is not None,
        "geo_metadata": geo_meta,
    }

