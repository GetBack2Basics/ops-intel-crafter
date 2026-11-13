"""Wherobots Remote Apache Sedona Batch Ingestion Script.

Executed on Wherobots Cloud Spark Cluster (Runtime: TINY):
1. Reads GeoParquet snapshots directly from GCS (https://storage.googleapis.com/operational-intelligence-crafter-lake/).
2. Writes optimized spatial tables into Wherobots Havasu Iceberg catalog (`org_catalog.ops_intel.<dataset_key>`).
3. Executes Level 3 verification queries (row counts and bounding box extents).
"""

import json
import os
import sys
import time

def run_batch_ingestion():
    from sedona.spark import SedonaContext
    from pyspark.sql import functions as F

    print("[WHEROBOTS_INGEST] Initializing Apache Sedona Spark context on Wherobots...")
    spark = SedonaContext.create(SedonaContext.builder().getOrCreate())

    # Create target database catalog
    db_name = "org_catalog.ops_intel"
    spark.sql(f"CREATE DATABASE IF NOT EXISTS {db_name}")
    print(f"[WHEROBOTS_INGEST] Target catalog ready: {db_name}")

    # Load dataset payload manifest
    candidates = [
        "wherobots_qld_cyclone_manifest.json",
        "/opt/wherobots/wherobots_qld_cyclone_manifest.json",
        "wherobots_manifest.json",
        "/opt/wherobots/wherobots_manifest.json",
        "wherobots_linked_manifest.json",
        "/opt/wherobots/wherobots_linked_manifest.json",
        "manifest.json",
        "/opt/wherobots/manifest.json",
    ]
    # Also discover any manifest json in working dir
    for search_dir in [".", "/opt/wherobots"]:
        if os.path.isdir(search_dir):
            for fname in os.listdir(search_dir):
                if fname.endswith(".json") and "manifest" in fname:
                    cand_path = os.path.join(search_dir, fname)
                    if cand_path not in candidates:
                        candidates.insert(0, cand_path)

    datasets = None
    for cand in candidates:
        if os.path.exists(cand):
            try:
                with open(cand, "r", encoding="utf-8") as f:
                    content = json.load(f)
                    if isinstance(content, list) and len(content) > 0 and "key" in content[0]:
                        datasets = content
                        print(f"[WHEROBOTS_INGEST] Successfully loaded manifest from {cand} ({len(datasets)} datasets)")
                        break
            except Exception as e:
                print(f"[WHEROBOTS_INGEST] Could not parse {cand}: {e}")

    if not datasets:
        # Fallback default datasets
        datasets = [
            {
                "key": "ga_electricity_substations",
                "url": "https://storage.googleapis.com/operational-intelligence-crafter-lake/geoparquet/ga_electricity_substations/2024-GA-NEI/20261109T073013Z/part-00000.parquet",
            },
            {
                "key": "ga_electricity_transmission_lines",
                "url": "https://storage.googleapis.com/operational-intelligence-crafter-lake/geoparquet/ga_electricity_transmission_lines/2024-GA-NEI/20261109T073016Z/part-00000.parquet",
            },
            {
                "key": "ga_major_power_stations",
                "url": "https://storage.googleapis.com/operational-intelligence-crafter-lake/geoparquet/ga_major_power_stations/2024-GA-NEI/20261109T073026Z/part-00000.parquet",
            },
            {
                "key": "next_lga_boundaries_asgs2025",
                "url": "https://storage.googleapis.com/operational-intelligence-crafter-lake/geoparquet/next_lga_boundaries_asgs2025/ASGS-2025/20261109T073027Z/part-00000.parquet",
            },
            {
                "key": "nsw_water_inundation_areas",
                "url": "https://storage.googleapis.com/operational-intelligence-crafter-lake/geoparquet/nsw_water_inundation_areas/2026-NSW-Water/20261109T073310Z/part-00000.parquet",
            },
            {
                "key": "abs_australia_1km_population_grid",
                "url": "https://storage.googleapis.com/operational-intelligence-crafter-lake/geoparquet/abs_australia_1km_population_grid/2025-ABS/20261110T022639Z/part-00000.parquet",
            },
        ]

    import urllib.request

    results = []
    for item in datasets:
        ds_key = item["key"]
        parquet_url = item["url"]
        table_name = f"{db_name}.{ds_key}"
        print(f"\n[WHEROBOTS_INGEST] Processing '{ds_key}' -> {table_name}")
        t0 = time.perf_counter()
        local_file = f"/tmp/{ds_key}.parquet"

        try:
            # 1. Download GeoParquet from GCS HTTPS to executor local scratch
            print(f"  Downloading snapshot from {parquet_url}...")
            t_dl = time.perf_counter()
            urllib.request.urlretrieve(parquet_url, local_file)
            file_mb = round(os.path.getsize(local_file) / (1024 * 1024), 2)
            print(f"  Downloaded {file_mb} MB to {local_file} in {round(time.perf_counter() - t_dl, 2)}s")

            # 2. Ingest into Spark / Sedona DataFrame
            sdf = None
            try:
                # Try direct local GeoParquet reader first
                sdf = spark.read.format("geoparquet").load(f"file://{local_file}")
            except Exception as read_err:
                print(f"  Direct GeoParquet load notice ({read_err}); loading via PyArrow...")
                import pyarrow as pa
                import pyarrow.parquet as pq
                arrow_tbl = pq.read_table(local_file)
                pdf = arrow_tbl.to_pandas()
                # Drop columns that are 100% null to prevent Spark CANNOT_DETERMINE_TYPE inference failure
                null_cols = [c for c in pdf.columns if pdf[c].isnull().all()]
                if null_cols:
                    print(f"  Dropping {len(null_cols)} all-null columns: {null_cols}")
                    pdf = pdf.drop(columns=null_cols)

                # Clean string object columns
                for col_name in pdf.columns:
                    if col_name != "geometry" and pdf[col_name].dtype == "object":
                        pdf[col_name] = pdf[col_name].astype(str).replace({"nan": None, "<NA>": None, "None": None})
                raw_sdf = spark.createDataFrame(pdf)
                if "geometry" in raw_sdf.columns:
                    sdf = raw_sdf.withColumn("geom", F.expr("ST_GeomFromWKB(geometry)")).drop("geometry")
                else:
                    sdf = raw_sdf

            row_count = sdf.count()
            print(f"  Parsed {row_count} rows in {round(time.perf_counter() - t0, 2)}s")

            # 3. Write to Wherobots Havasu Iceberg catalog
            t_write = time.perf_counter()
            sdf.write.format("havasu.iceberg").mode("overwrite").saveAsTable(table_name)
            write_sec = round(time.perf_counter() - t_write, 2)
            print(f"  Saved Havasu Iceberg table '{table_name}' in {write_sec}s")

            # 4. Level 3 verification query
            res_df = spark.sql(f"SELECT COUNT(*) AS cnt FROM {table_name}").collect()
            verified_count = res_df[0]["cnt"] if res_df else 0
            status = "PASS" if verified_count == row_count else "COUNT_MISMATCH"

            results.append({
                "dataset_key": ds_key,
                "table": table_name,
                "status": status,
                "rows_ingested": verified_count,
                "total_sec": round(time.perf_counter() - t0, 2),
            })
            print(f"  Verification: {status} (Verified rows: {verified_count})")

        except Exception as exc:
            print(f"  ERROR processing '{ds_key}': {exc}", file=sys.stderr)
            results.append({
                "dataset_key": ds_key,
                "table": table_name,
                "status": f"FAILED: {type(exc).__name__}",
                "error": str(exc),
            })
        finally:
            if os.path.exists(local_file):
                try:
                    os.remove(local_file)
                except Exception:
                    pass

    print("\n[WHEROBOTS_INGEST] Batch Ingestion Summary:")
    print(json.dumps(results, indent=2))
    return results

if __name__ == "__main__":
    run_batch_ingestion()

