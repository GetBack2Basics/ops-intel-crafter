"""DuckDB Spatial Execution Engine over Versioned GeoParquet Lakehouse Snapshots.

Invariants enforced:
- Queries execute directly against stored GeoParquet files (local staging mirror or gs://).
- Zero query-result caching: every execution reads the immutable GeoParquet snapshot.
- Uses native DuckDB `spatial` extension when cached, with automatic GEOS (Shapely 2) + PROJ (PyProj)
  SQL function registration when running in an offline/sandboxed environment without `~/.duckdb`.
"""

import hashlib
import json
import os
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure PROJ data directory is discovered in OSGeo4W or standard paths
if not os.environ.get("PROJ_DATA"):
    for cand in [Path("C:/OSGeo4W/share/proj"), Path("/usr/share/proj")]:
        if cand.exists():
            os.environ["PROJ_DATA"] = str(cand)
            try:
                import pyproj.datadir
                pyproj.datadir.set_data_dir(str(cand))
            except Exception:
                pass
            break

import duckdb
import pandas as pd
from pyproj import Transformer
from shapely import wkb, wkt
from shapely.geometry import mapping
from shapely.ops import transform as shapely_transform

from src.catalogue.dataset_registry import DatasetRegistry
from src.ingestion.gcs_storage import GCSLakeStorage


@lru_cache(maxsize=16)
def _get_transformer(src_crs: str, dst_crs: str) -> Transformer:
    return Transformer.from_crs(src_crs, dst_crs, always_xy=True)


def _geom_from_any(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, (bytes, bytearray, memoryview)):
        return wkb.loads(bytes(val))
    if isinstance(val, str):
        return wkt.loads(val)
    return None


class DuckDBSpatialEngine:
    """In-process analytical spatial SQL engine backed by DuckDB and GEOS/PROJ."""

    def __init__(
        self,
        registry: Optional[DatasetRegistry] = None,
        storage: Optional[GCSLakeStorage] = None,
    ):
        self.registry = registry or DatasetRegistry()
        self.storage = storage or GCSLakeStorage()
        self.conn = duckdb.connect(database=":memory:")
        self.native_spatial_loaded = False
        self._init_spatial_extension()
        self.registered_views: Dict[str, Dict[str, Any]] = {}

    def _init_spatial_extension(self) -> None:
        ext_dir = self.storage.project_root / ".duckdb_extensions"
        ext_dir.mkdir(parents=True, exist_ok=True)
        posix_ext = str(ext_dir.resolve()).replace("\\", "/")
        try:
            self.conn.execute(f"SET extension_directory = '{posix_ext}';")
            self.conn.execute("LOAD spatial;")
            self.native_spatial_loaded = True
            return
        except Exception:
            pass

        # Register GEOS (Shapely) + PROJ (PyProj) spatial SQL functions on DuckDB connection
        def st_geomfromwkb(b: bytes) -> Optional[bytes]:
            return bytes(b) if b is not None else None

        def st_aswkb(b: bytes) -> Optional[bytes]:
            return bytes(b) if b is not None else None

        def st_geomfromtext(text: str) -> Optional[bytes]:
            if not text:
                return None
            return wkt.loads(text).wkb

        def st_asgeojson(b: bytes) -> Optional[str]:
            g = _geom_from_any(b)
            return json.dumps(mapping(g)) if g is not None else None

        def st_centroid(b: bytes) -> Optional[bytes]:
            g = _geom_from_any(b)
            return g.centroid.wkb if g is not None else None

        def st_x(b: bytes) -> Optional[float]:
            g = _geom_from_any(b)
            return float(g.centroid.x) if g is not None else None

        def st_y(b: bytes) -> Optional[float]:
            g = _geom_from_any(b)
            return float(g.centroid.y) if g is not None else None

        def st_contains(a: bytes, b: bytes) -> bool:
            ga, gb = _geom_from_any(a), _geom_from_any(b)
            if ga is None or gb is None:
                return False
            return bool(ga.contains(gb))

        def st_intersects(a: bytes, b: bytes) -> bool:
            ga, gb = _geom_from_any(a), _geom_from_any(b)
            if ga is None or gb is None:
                return False
            return bool(ga.intersects(gb))

        def st_intersection(a: bytes, b: bytes) -> Optional[bytes]:
            ga, gb = _geom_from_any(a), _geom_from_any(b)
            if ga is None or gb is None:
                return None
            return ga.intersection(gb).wkb

        def st_area(b: bytes) -> float:
            g = _geom_from_any(b)
            return float(g.area) if g is not None else 0.0

        def st_buffer(b: bytes, dist: float) -> Optional[bytes]:
            g = _geom_from_any(b)
            return g.buffer(float(dist)).wkb if g is not None else None

        def st_distance(a: bytes, b: bytes) -> float:
            ga, gb = _geom_from_any(a), _geom_from_any(b)
            if ga is None or gb is None:
                return 0.0
            return float(ga.distance(gb))

        def st_dwithin(a: bytes, b: bytes, dist: float) -> bool:
            ga, gb = _geom_from_any(a), _geom_from_any(b)
            if ga is None or gb is None:
                return False
            return bool(ga.distance(gb) <= float(dist))

        def st_transform(b: bytes, src_crs: str, dst_crs: str, always_xy: bool = True) -> Optional[bytes]:
            g = _geom_from_any(b)
            if g is None:
                return None
            tr = _get_transformer(src_crs, dst_crs)
            return shapely_transform(tr.transform, g).wkb

        for fn_name, fn_impl in [
            ("ST_GeomFromWKB", st_geomfromwkb),
            ("ST_AsWKB", st_aswkb),
            ("ST_GeomFromText", st_geomfromtext),
            ("ST_AsGeoJSON", st_asgeojson),
            ("ST_Centroid", st_centroid),
            ("ST_X", st_x),
            ("ST_Y", st_y),
            ("ST_Contains", st_contains),
            ("ST_Intersects", st_intersects),
            ("ST_Intersection", st_intersection),
            ("ST_Area", st_area),
            ("ST_Buffer", st_buffer),
            ("ST_Distance", st_distance),
            ("ST_DWithin", st_dwithin),
            ("ST_Transform", st_transform),
        ]:
            try:
                self.conn.create_function(fn_name, fn_impl)
            except Exception:
                pass

    def register_geoparquet_view(self, view_name: str, parquet_path: Path) -> None:
        """Registers a GeoParquet file as a DuckDB view exposing `geom` and `geom_wkb`."""
        posix_path = str(Path(parquet_path).resolve()).replace("\\", "/")
        if self.native_spatial_loaded:
            col_info = self.conn.execute(
                f"DESCRIBE SELECT * FROM read_parquet('{posix_path}')"
            ).fetchall()
            geom_col_type = ""
            for cname, ctype, *_ in col_info:
                if cname == "geometry":
                    geom_col_type = str(ctype).upper()
                    break
            if "GEOMETRY" in geom_col_type:
                geom_expr = "geometry AS geom, ST_AsWKB(geometry) AS geom_wkb"
            else:
                geom_expr = "ST_GeomFromWKB(geometry) AS geom, geometry AS geom_wkb"
            view_sql = (
                f"CREATE OR REPLACE VIEW {view_name} AS "
                f"SELECT * EXCLUDE (geometry), {geom_expr} "
                f"FROM read_parquet('{posix_path}');"
            )
            self.conn.execute(view_sql)
        else:
            import pyarrow as pa
            import pyarrow.parquet as pq

            tbl = pq.read_table(parquet_path)
            if "geometry" in tbl.column_names:
                idx = tbl.column_names.index("geometry")
                raw_bin = tbl.column(idx).cast(pa.binary())
                tbl = tbl.set_column(idx, "geometry", raw_bin)
            rel_name = f"_raw_{view_name}"
            self.conn.register(rel_name, tbl)
            view_sql = (
                f"CREATE OR REPLACE VIEW {view_name} AS "
                f"SELECT * EXCLUDE (geometry), geometry AS geom, geometry AS geom_wkb "
                f"FROM {rel_name};"
            )
            self.conn.execute(view_sql)

    def register_catalogue_views(self, keys: Optional[List[str]] = None) -> Dict[str, Dict[str, Any]]:
        """Registers a DuckDB view for each catalogued dataset that has a verified GeoParquet snapshot."""
        target_keys = keys or self.registry.list_keys()
        for k in target_keys:
            entry = self.registry.get(k)
            if not entry.latest_snapshot_path:
                continue
            pq_file = self.storage.project_root / entry.latest_snapshot_path
            if not pq_file.exists():
                continue
            self.register_geoparquet_view(k, pq_file)
            self.registered_views[k] = {
                "dataset_key": k,
                "parquet_path": entry.latest_snapshot_path,
                "gs_uri": self.storage.gs_uri(entry.latest_snapshot_path),
                "source_vintage": entry.source_vintage,
                "retrieval_utc": entry.latest_retrieval_utc,
                "stored_crs": entry.stored_crs,
            }
        return self.registered_views

    def execute_spatial_sql(
        self,
        sql: str,
        params: Optional[List[Any]] = None,
        query_label: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Executes a read-only spatial SQL query against registered GeoParquet views."""
        t0 = time.perf_counter()
        rel = self.conn.execute(sql, params) if params else self.conn.execute(sql)
        df: pd.DataFrame = rel.fetchdf()
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)

        safe_records = json.loads(df.to_json(orient="records", date_format="iso", default_handler=str))
        result_hash = hashlib.sha256(
            json.dumps(safe_records, sort_keys=True).encode("utf-8")
        ).hexdigest()

        return {
            "engine": "duckdb_spatial",
            "query_label": query_label or "spatial_sql",
            "duckdb_version": duckdb.__version__,
            "execution_ms": elapsed_ms,
            "elapsed_ms": elapsed_ms,
            "row_count": len(df),
            "columns": list(df.columns),
            "result_sha256": result_hash,
            "records": safe_records,
            "rows": safe_records,
            "dataframe": df,
        }

    def __enter__(self) -> "DuckDBSpatialEngine":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass
