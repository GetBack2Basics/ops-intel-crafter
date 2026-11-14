"""Critical Infrastructure Dependency Analysis (Section 6.4).

Evaluates:
1. High-voltage substations (`ga_electricity_substations`) and transmission lines
   (`ga_electricity_transmission_lines`) within or adjacent to inundation areas (`nsw_water_inundation_areas`).
2. Downstream civic/building complexes (`nsw_foi_building_complexes`) within a 5 km metric
   service catchment (`EPSG:3112`) of each substation to quantify potential outage blast radius.
"""

from typing import Any, Dict

from src.engines.duckdb_engine import DuckDBSpatialEngine


def run_infrastructure_dependency_analysis(
    engine: DuckDBSpatialEngine,
) -> Dict[str, Any]:
    """Computes substation flood proximity and 5 km metric service-catchment facility dependencies."""

    engine.register_catalogue_view("substations", "ga_electricity_substations")
    engine.register_catalogue_view("tx_lines", "ga_electricity_transmission_lines")
    engine.register_catalogue_view("inundation", "nsw_water_inundation_areas")
    engine.register_catalogue_view("foi_buildings", "nsw_foi_building_complexes")

    sql = """
    WITH inund_3112 AS (
        SELECT
            _bbox_minx, _bbox_miny, _bbox_maxx, _bbox_maxy,
            ST_Transform(geom, 'EPSG:7844', 'EPSG:3112', true) AS geom_3112
        FROM inundation
        WHERE _bbox_maxx >= 151.30 AND _bbox_minx <= 151.95 AND _bbox_maxy >= -33.30 AND _bbox_miny <= -32.60
    ),
    sub_3112 AS (
        SELECT
            objectid AS substation_id,
            COALESCE(feature_name, 'Unnamed Substation') AS substation_name,
            voltage_kv,
            COALESCE(locality, 'Unknown') AS locality,
            state,
            _bbox_minx,
            _bbox_miny,
            _bbox_maxx,
            _bbox_maxy,
            ST_Transform(geom, 'EPSG:7844', 'EPSG:3112', true) AS geom_3112,
            ST_AsGeoJSON(geom) AS geojson_7844
        FROM substations
        WHERE _bbox_maxx >= 151.30 AND _bbox_minx <= 151.95 AND _bbox_maxy >= -33.30 AND _bbox_miny <= -32.60
    ),
    sub_flood_dist AS (
        SELECT
            s.substation_id,
            s.substation_name,
            s.voltage_kv,
            s.locality,
            s.state,
            s._bbox_minx,
            s._bbox_miny,
            s._bbox_maxx,
            s._bbox_maxy,
            s.geom_3112,
            s.geojson_7844,
            COALESCE(ROUND(MIN(ST_Distance(s.geom_3112, i.geom_3112)), 1), 99999.0) AS distance_to_inundation_m
        FROM sub_3112 s
        LEFT JOIN inund_3112 i
          ON s._bbox_maxx >= (i._bbox_minx - 0.15) AND s._bbox_minx <= (i._bbox_maxx + 0.15)
         AND s._bbox_maxy >= (i._bbox_miny - 0.15) AND s._bbox_miny <= (i._bbox_maxy + 0.15)
        GROUP BY
            s.substation_id, s.substation_name, s.voltage_kv, s.locality, s.state,
            s._bbox_minx, s._bbox_miny, s._bbox_maxx, s._bbox_maxy, s.geom_3112, s.geojson_7844
    ),
    foi_3112 AS (
        SELECT
            objectid AS foi_id,
            _bbox_minx,
            _bbox_miny,
            _bbox_maxx,
            _bbox_maxy,
            ST_Transform(geom, 'EPSG:7844', 'EPSG:3112', true) AS geom_3112
        FROM foi_buildings
    ),
    sub_foi_counts AS (
        SELECT
            s.substation_id,
            COUNT(DISTINCT f.foi_id) AS dependent_foi_within_5km
        FROM sub_flood_dist s
        LEFT JOIN foi_3112 f
          ON f._bbox_maxx >= (s._bbox_minx - 0.06) AND f._bbox_minx <= (s._bbox_maxx + 0.06)
         AND f._bbox_maxy >= (s._bbox_miny - 0.06) AND f._bbox_miny <= (s._bbox_maxy + 0.06)
         AND ST_DWithin(s.geom_3112, f.geom_3112, 5000.0)
        GROUP BY s.substation_id
    ),
    tx_3112 AS (
        SELECT
            objectid AS tx_id,
            _bbox_minx,
            _bbox_miny,
            _bbox_maxx,
            _bbox_maxy,
            ST_Transform(geom, 'EPSG:7844', 'EPSG:3112', true) AS geom_3112
        FROM tx_lines
    ),
    sub_tx_counts AS (
        SELECT
            s.substation_id,
            COUNT(DISTINCT t.tx_id) AS connected_tx_corridors
        FROM sub_flood_dist s
        LEFT JOIN tx_3112 t
          ON t._bbox_maxx >= (s._bbox_minx - 0.02) AND t._bbox_minx <= (s._bbox_maxx + 0.02)
         AND t._bbox_maxy >= (s._bbox_miny - 0.02) AND t._bbox_miny <= (s._bbox_maxy + 0.02)
         AND ST_DWithin(s.geom_3112, t.geom_3112, 1000.0)
        GROUP BY s.substation_id
    )
    SELECT
        s.substation_id,
        s.substation_name,
        s.voltage_kv,
        s.locality,
        s.state,
        s.distance_to_inundation_m,
        COALESCE(fc.dependent_foi_within_5km, 0) AS dependent_foi_within_5km,
        COALESCE(tc.connected_tx_corridors, 0) AS connected_tx_corridors,
        CASE
            WHEN s.distance_to_inundation_m <= 500.0 THEN 'CRITICAL_FLOOD_PROXIMITY_500M'
            WHEN s.distance_to_inundation_m <= 2000.0 THEN 'ELEVATED_FLOOD_PROXIMITY_2KM'
            ELSE 'STANDARD_ELEVATION_BUFFER'
        END AS hazard_exposure_tier,
        s.geojson_7844
    FROM sub_flood_dist s
    LEFT JOIN sub_foi_counts fc ON s.substation_id = fc.substation_id
    LEFT JOIN sub_tx_counts tc ON s.substation_id = tc.substation_id
    ORDER BY s.distance_to_inundation_m ASC, dependent_foi_within_5km DESC
    """
    res = engine.execute_spatial_sql(sql, query_label="substation_dependency_catchment")
    return {
        "analysis_type": "critical_infrastructure_dependencies",
        "metric_crs": "EPSG:3112",
        "catchment_radius_m": 5000.0,
        "substation_count": res["row_count"],
        "execution_ms": res["elapsed_ms"],
        "substations": res["rows"],
    }
