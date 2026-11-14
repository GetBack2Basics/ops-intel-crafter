"""Multi-Scale Emergency Exposure Analysis (Local, State/Regional, and National Scales)."""

import time
from typing import Any, Dict

from src.engines.duckdb_engine import DuckDBSpatialEngine


def run_multi_scale_exposure_analysis(
    engine: DuckDBSpatialEngine,
) -> Dict[str, Any]:
    """Executes verifiable emergency exposure analyses across Local, Regional/State, and National scales
    directly against catalogue-resolved GeoParquet snapshots (gs://) in DuckDB Spatial.
    """
    t0 = time.perf_counter()

    engine.register_catalogue_view("substations", "ga_electricity_substations")
    engine.register_catalogue_view("power_stations", "ga_major_power_stations")
    engine.register_catalogue_view("tx_lines", "ga_electricity_transmission_lines")
    engine.register_catalogue_view("seismic_pga", "ga_seismic_hazard_pga_10pct")
    engine.register_catalogue_view("lga_asgs", "next_lga_boundaries_asgs2025")
    engine.register_catalogue_view("sa2_asgs", "next_sa2_boundaries_asgs2021")
    engine.register_catalogue_view("foi_buildings", "nsw_foi_building_complexes")
    engine.register_catalogue_view("inundation", "nsw_water_inundation_areas")
    engine.register_catalogue_view("rfs_incidents", "nsw_rfs_major_incidents_live")

    # 1. LOCAL SCALE: Lower Hunter Flood & Inundation Facility Exposure (within 250m metric buffer in EPSG:3112)
    local_sql = """
    WITH inund_3112 AS (
        SELECT
            hydroname,
            _bbox_minx - 0.005 AS bminx,
            _bbox_miny - 0.005 AS bminy,
            _bbox_maxx + 0.005 AS bmaxx,
            _bbox_maxy + 0.005 AS bmaxy,
            ST_Buffer(ST_Transform(geom, 'EPSG:7844', 'EPSG:3112', true), 250.0) AS hazard_buf_3112
        FROM inundation
        WHERE _bbox_maxx >= 151.40 AND _bbox_minx <= 151.90 AND _bbox_maxy >= -33.20 AND _bbox_miny <= -32.65
    ),
    foi_3112 AS (
        SELECT
            objectid,
            COALESCE(generalname, 'Unnamed Facility') AS facility_name,
            classsubtype,
            _bbox_minx,
            _bbox_miny,
            _bbox_maxx,
            _bbox_maxy,
            ST_Transform(geom, 'EPSG:7844', 'EPSG:3112', true) AS geom_3112,
            ST_AsGeoJSON(geom) AS geojson_7844
        FROM foi_buildings
        WHERE _bbox_maxx >= 151.40 AND _bbox_minx <= 151.90 AND _bbox_maxy >= -33.20 AND _bbox_miny <= -32.65
    )
    SELECT
        f.objectid,
        f.facility_name,
        f.classsubtype,
        COALESCE(i.hydroname, 'Hunter Floodplain Inundation Zone') AS hazard_zone,
        f.geojson_7844
    FROM foi_3112 f
    JOIN inund_3112 i
      ON f._bbox_maxx >= i.bminx AND f._bbox_minx <= i.bmaxx
     AND f._bbox_maxy >= i.bminy AND f._bbox_miny <= i.bmaxy
     AND ST_Intersects(f.geom_3112, i.hazard_buf_3112)
    ORDER BY f.facility_name
    """
    local_res = engine.execute_spatial_sql(local_sql, query_label="local_hunter_flood_exposure")

    # 2. REGIONAL / STATE SCALE: LGA & SA2 Emergency Exposure Rollup (Inundation + Substations + FOI Buildings)
    regional_sql = """
    WITH nsw_lga AS (
        SELECT * FROM lga_asgs
        WHERE state_name_2021 = 'New South Wales' OR state_name_2021 IS NULL
    ),
    lga_sub AS (
        SELECT l.lga_code_2025, COUNT(DISTINCT s.objectid) AS substations_count
        FROM nsw_lga l
        LEFT JOIN substations s
          ON s._bbox_maxx >= l._bbox_minx AND s._bbox_minx <= l._bbox_maxx
         AND s._bbox_maxy >= l._bbox_miny AND s._bbox_miny <= l._bbox_maxy
         AND ST_Intersects(l.geom, s.geom)
        GROUP BY l.lga_code_2025
    ),
    lga_inund AS (
        SELECT l.lga_code_2025, COUNT(DISTINCT i.objectid) AS inundation_polygons_count
        FROM nsw_lga l
        LEFT JOIN inundation i
          ON i._bbox_maxx >= l._bbox_minx AND i._bbox_minx <= l._bbox_maxx
         AND i._bbox_maxy >= l._bbox_miny AND i._bbox_miny <= l._bbox_maxy
         AND ST_Intersects(l.geom, i.geom)
        GROUP BY l.lga_code_2025
    ),
    lga_foi AS (
        SELECT l.lga_code_2025, COUNT(DISTINCT f.objectid) AS foi_complexes_count
        FROM nsw_lga l
        LEFT JOIN foi_buildings f
          ON f._bbox_maxx >= l._bbox_minx AND f._bbox_minx <= l._bbox_maxx
         AND f._bbox_maxy >= l._bbox_miny AND f._bbox_miny <= l._bbox_maxy
         AND ST_Intersects(l.geom, f.geom)
        GROUP BY l.lga_code_2025
    )
    SELECT
        l.lga_code_2025 AS lga_code,
        l.lga_name_2025 AS lga_name,
        ROUND(l.area_albers_sqkm, 1) AS area_sqkm,
        COALESCE(ls.substations_count, 0) AS substations_count,
        COALESCE(li.inundation_polygons_count, 0) AS inundation_polygons_count,
        COALESCE(lf.foi_complexes_count, 0) AS foi_complexes_count
    FROM nsw_lga l
    LEFT JOIN lga_sub ls ON l.lga_code_2025 = ls.lga_code_2025
    LEFT JOIN lga_inund li ON l.lga_code_2025 = li.lga_code_2025
    LEFT JOIN lga_foi lf ON l.lga_code_2025 = lf.lga_code_2025
    ORDER BY foi_complexes_count DESC, substations_count DESC
    """
    regional_res = engine.execute_spatial_sql(regional_sql, query_label="regional_lga_rollup")

    # Live RFS Major Incidents summary across NSW
    rfs_sql = """
    SELECT
        COALESCE(title, 'Incident') AS incident_title,
        COALESCE(category, 'Uncategorised') AS alert_level,
        COALESCE(description, '') AS details,
        ROUND(ST_X(ST_Centroid(geom)), 4) AS lon,
        ROUND(ST_Y(ST_Centroid(geom)), 4) AS lat,
        ST_AsGeoJSON(geom) AS geojson_7844
    FROM rfs_incidents
    ORDER BY category, title
    """
    rfs_res = engine.execute_spatial_sql(rfs_sql, query_label="state_live_rfs_incidents")

    # 3. NATIONAL SCALE: National Power Generation & Substation Capacity by State + Seismic Hazard Intersection
    national_sql = """
    WITH state_power AS (
        SELECT
            COALESCE(state, 'Unknown') AS state_name,
            COUNT(*) AS power_station_count,
            ROUND(SUM(TRY_CAST(generation_capacity_mw AS DOUBLE)), 1) AS total_capacity_mw,
            COUNT(DISTINCT primary_fuel_type) AS fuel_types_count
        FROM power_stations
        GROUP BY COALESCE(state, 'Unknown')
    ),
    seismic_summary AS (
        SELECT
            ROUND(MIN(TRY_CAST(levels AS DOUBLE)), 3) AS min_pga_g,
            ROUND(MAX(TRY_CAST(levels AS DOUBLE)), 3) AS max_pga_g,
            ROUND(AVG(TRY_CAST(levels AS DOUBLE)), 3) AS avg_pga_g,
            COUNT(*) AS seismic_contour_count
        FROM seismic_pga
    )
    SELECT
        sp.state_name,
        sp.power_station_count,
        COALESCE(sp.total_capacity_mw, 0.0) AS total_capacity_mw,
        sp.fuel_types_count,
        ss.max_pga_g AS national_sampled_max_pga_g
    FROM state_power sp
    CROSS JOIN seismic_summary ss
    ORDER BY total_capacity_mw DESC
    """
    national_res = engine.execute_spatial_sql(national_sql, query_label="national_power_seismic_rollup")

    return {
        "total_elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        "local_scale": {
            "title": "Local Scale — Hunter River Inundation + 250m Buffer Facility Exposure",
            "metric_crs": "EPSG:3112",
            "exposed_facility_count": local_res["row_count"],
            "execution_ms": local_res["elapsed_ms"],
            "exposed_facilities": local_res["rows"],
        },
        "regional_state_scale": {
            "title": "Regional & State Scale — Lower Hunter LGA Multi-Hazard Rollup & Live NSW RFS Feed",
            "lga_count": regional_res["row_count"],
            "lga_rollup": regional_res["rows"],
            "live_rfs_incident_count": rfs_res["row_count"],
            "live_rfs_incidents": rfs_res["rows"],
            "execution_ms": round(regional_res["elapsed_ms"] + rfs_res["elapsed_ms"], 2),
        },
        "national_scale": {
            "title": "National Scale — Australian Power Generation Capacity & Seismic Hazard Baseline",
            "state_rollup": national_res["rows"],
            "execution_ms": national_res["elapsed_ms"],
        },
    }
