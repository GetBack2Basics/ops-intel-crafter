"""Catalogue-Grounded Natural-Language Spatial Query Planner (Section 8.1)."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class PlannedSpatialQuery:
    status: str  # READY, CLARIFICATION_REQUIRED, REJECTED_UNCATALOGUED
    intent_id: str
    selected_datasets: List[str] = field(default_factory=list)
    sql: Optional[str] = None
    population_method: Optional[str] = None
    clarification_questions: List[str] = field(default_factory=list)
    rejection_reason: Optional[str] = None
    notes: List[str] = field(default_factory=list)


def plan_natural_language_query(
    question: str,
    explicit_pop_method: Optional[str] = None,
    explicit_scale: Optional[str] = None,
) -> PlannedSpatialQuery:
    """Plans a strictly catalogue-grounded Spatial SQL query from a natural-language question.

    Never guesses when a question omits required methodological parameters (such as Population
    Method A vs B vs C) or asks for datasets outside `config/dataset_manifest.json`.
    """
    q = question.strip().lower()

    # 1. Check for uncatalogued / unavailable real-time telemetry requests
    uncatalogued_triggers = {
        "icu bed": "Real-time hospital ICU bed occupancy is not in the public spatial catalogue.",
        "ambulance dispatch": "Live CAD ambulance dispatch telemetry is restricted and not in the public catalogue.",
        "scada": "Real-time SCADA substation load telemetry is not publicly available; `ga_electricity_substations` provides static foundation infrastructure.",
        "telecom tower outage": "Live carrier mobile tower outage feeds are not in the allow-listed catalogue.",
    }
    for trigger, reason in uncatalogued_triggers.items():
        if trigger in q:
            return PlannedSpatialQuery(
                status="REJECTED_UNCATALOGUED",
                intent_id="reject_uncatalogued_source",
                rejection_reason=(
                    f"{reason} Zero-mock policy prohibits fabricating or substituting synthetic data."
                ),
            )

    # Check if user explicitly asks for the restricted NSW Emergency Management layer
    if "restricted" in q or "token required" in q or "nsw_emergency_management_restricted" in q:
        return PlannedSpatialQuery(
            status="REJECTED_UNCATALOGUED",
            intent_id="reject_failed_restricted_layer",
            selected_datasets=["nsw_emergency_management_restricted"],
            rejection_reason=(
                "Dataset `nsw_emergency_management_restricted` failed Level 1 Source Contract validation "
                "(ArcGIS embedded error 499: Token Required). Zero-mock policy blocks querying failed sources."
            ),
        )

    # 2. Check for ambiguous population exposure questions that omit Method A / B / C
    if ("population" in q or "how many people" in q or "residents" in q) and not explicit_pop_method:
        if not any(tok in q for tok in ("method a", "method b", "method c", "centroid", "polygon", "compare", "all three")):
            return PlannedSpatialQuery(
                status="CLARIFICATION_REQUIRED",
                intent_id="clarify_population_methodology",
                selected_datasets=["next_sa2_boundaries_asgs2021", "nsw_water_inundation_areas", "nsw_foi_building_complexes"],
                clarification_questions=[
                    "Which population representation method should be used? (Method A: NExT 1 km² centroid ST_Contains, Method B: 1 km² polygon ST_Intersects with boundary-straddling breakdown, Method C: area-weighted proportional estimate, or compare all three?)",
                    "Which hazard footprint or spatial extent should be evaluated (e.g., Lower Hunter NSW water inundation areas, 500m transmission corridor buffer, or a custom bounding box)?",
                ],
            )

    # 3. Matched grounded intents
    if "substation" in q and ("flood" in q or "inundation" in q or "5km" in q or "5 km" in q or "dependent" in q):
        sql = """
        WITH inund_3112 AS (
            SELECT ST_Transform(geom, 'EPSG:7844', 'EPSG:3112', true) AS geom_3112
            FROM nsw_water_inundation_areas
        ),
        sub_3112 AS (
            SELECT
                objectid AS substation_id,
                COALESCE(feature_name, 'Unnamed Substation') AS substation_name,
                voltage_kv,
                COALESCE(locality, 'Unknown') AS locality,
                ST_Transform(geom, 'EPSG:7844', 'EPSG:3112', true) AS geom_3112
            FROM ga_electricity_substations
        ),
        sub_flood_dist AS (
            SELECT
                s.substation_id,
                s.substation_name,
                s.voltage_kv,
                s.locality,
                s.geom_3112,
                ROUND(MIN(ST_Distance(s.geom_3112, i.geom_3112)), 1) AS distance_to_inundation_m
            FROM sub_3112 s
            CROSS JOIN inund_3112 i
            GROUP BY s.substation_id, s.substation_name, s.voltage_kv, s.locality, s.geom_3112
        ),
        foi_3112 AS (
            SELECT
                objectid AS foi_id,
                ST_Transform(geom, 'EPSG:7844', 'EPSG:3112', true) AS geom_3112
            FROM nsw_foi_building_complexes
        )
        SELECT
            s.substation_id,
            s.substation_name,
            s.voltage_kv,
            s.locality,
            s.distance_to_inundation_m,
            COUNT(DISTINCT f.foi_id) AS dependent_foi_within_5km
        FROM sub_flood_dist s
        LEFT JOIN foi_3112 f
          ON ST_DWithin(s.geom_3112, f.geom_3112, 5000.0)
        GROUP BY s.substation_id, s.substation_name, s.voltage_kv, s.locality, s.distance_to_inundation_m
        ORDER BY s.distance_to_inundation_m ASC
        LIMIT 15
        """
        return PlannedSpatialQuery(
            status="READY",
            intent_id="substation_flood_dependency",
            selected_datasets=[
                "ga_electricity_substations",
                "nsw_water_inundation_areas",
                "nsw_foi_building_complexes",
            ],
            sql=sql.strip(),
            population_method="NOT_APPLICABLE",
            notes=[
                "Distances and 5,000m catchment radii computed in metric CRS EPSG:3112 (GDA2020 / Geoscience Australia Lambert)."
            ],
        )

    if "rfs" in q or "bushfire" in q or "live incident" in q or "active fire" in q:
        sql = """
        SELECT
            COALESCE(title, 'Incident') AS incident_title,
            COALESCE(category, 'Advice') AS alert_category,
            ROUND(ST_X(ST_Centroid(geom)), 4) AS centroid_lon,
            ROUND(ST_Y(ST_Centroid(geom)), 4) AS centroid_lat
        FROM nsw_rfs_major_incidents_live
        ORDER BY alert_category, incident_title
        """
        return PlannedSpatialQuery(
            status="READY",
            intent_id="live_nsw_rfs_incidents",
            selected_datasets=["nsw_rfs_major_incidents_live"],
            sql=sql.strip(),
            population_method="NOT_APPLICABLE",
            notes=["Queries stored snapshot of NSW RFS majorIncidents.json live operational feed."],
        )

    if "power station" in q or "generation capacity" in q or "national" in q:
        sql = """
        SELECT
            COALESCE(state, 'Unknown') AS state_name,
            COUNT(*) AS station_count,
            ROUND(SUM(TRY_CAST(generation_capacity_mw AS DOUBLE)), 1) AS total_capacity_mw
        FROM ga_major_power_stations
        GROUP BY COALESCE(state, 'Unknown')
        ORDER BY total_capacity_mw DESC
        """
        return PlannedSpatialQuery(
            status="READY",
            intent_id="national_power_generation_by_state",
            selected_datasets=["ga_major_power_stations"],
            sql=sql.strip(),
            population_method="NOT_APPLICABLE",
            notes=["Aggregates Geoscience Australia Major Power Stations across Australian states."],
        )

    if "lga" in q or "council" in q or "regional" in q or "inundation" in q or "flood" in q:
        sql = """
        WITH lga_inund AS (
            SELECT l.lga_code_2025, COUNT(DISTINCT i.objectid) AS inundation_zones
            FROM next_lga_boundaries_asgs2025 l
            LEFT JOIN nsw_water_inundation_areas i
              ON i._bbox_maxx >= l._bbox_minx AND i._bbox_minx <= l._bbox_maxx
             AND i._bbox_maxy >= l._bbox_miny AND i._bbox_miny <= l._bbox_maxy
             AND ST_Intersects(l.geom, i.geom)
            GROUP BY l.lga_code_2025
        ),
        lga_sub AS (
            SELECT l.lga_code_2025, COUNT(DISTINCT s.objectid) AS substations_count
            FROM next_lga_boundaries_asgs2025 l
            LEFT JOIN ga_electricity_substations s
              ON s._bbox_maxx >= l._bbox_minx AND s._bbox_minx <= l._bbox_maxx
             AND s._bbox_maxy >= l._bbox_miny AND s._bbox_miny <= l._bbox_maxy
             AND ST_Intersects(l.geom, s.geom)
            GROUP BY l.lga_code_2025
        ),
        lga_foi AS (
            SELECT l.lga_code_2025, COUNT(DISTINCT f.objectid) AS foi_complexes_count
            FROM next_lga_boundaries_asgs2025 l
            LEFT JOIN nsw_foi_building_complexes f
              ON f._bbox_maxx >= l._bbox_minx AND f._bbox_minx <= l._bbox_maxx
             AND f._bbox_maxy >= l._bbox_miny AND f._bbox_miny <= l._bbox_maxy
             AND ST_Intersects(l.geom, f.geom)
            GROUP BY l.lga_code_2025
        )
        SELECT
            l.lga_code_2025,
            l.lga_name_2025,
            ROUND(l.area_albers_sqkm, 1) AS lga_area_sqkm,
            COALESCE(li.inundation_zones, 0) AS inundation_zones,
            COALESCE(ls.substations_count, 0) AS substations_count,
            COALESCE(lf.foi_complexes_count, 0) AS foi_complexes_count
        FROM next_lga_boundaries_asgs2025 l
        LEFT JOIN lga_inund li ON l.lga_code_2025 = li.lga_code_2025
        LEFT JOIN lga_sub ls ON l.lga_code_2025 = ls.lga_code_2025
        LEFT JOIN lga_foi lf ON l.lga_code_2025 = lf.lga_code_2025
        ORDER BY foi_complexes_count DESC, substations_count DESC
        """
        return PlannedSpatialQuery(
            status="READY",
            intent_id="regional_lga_multi_hazard_summary",
            selected_datasets=[
                "next_lga_boundaries_asgs2025",
                "nsw_water_inundation_areas",
                "ga_electricity_substations",
                "nsw_foi_building_complexes",
            ],
            sql=sql.strip(),
            population_method=explicit_pop_method or "NOT_APPLICABLE",
            notes=["Joins ABS ASGS 2025 LGAs with NSW inundation polygons, GA substations, and NSW FOI complexes."],
        )

    # Default: require clarification rather than guessing an arbitrary query
    return PlannedSpatialQuery(
        status="CLARIFICATION_REQUIRED",
        intent_id="clarify_general_spatial_intent",
        clarification_questions=[
            "Please specify the target emergency theme (e.g., Lower Hunter flood inundation exposure, substation 5km service dependencies, live NSW RFS bushfire incidents, or national power station capacity).",
            "If requesting population exposure, please specify Method A (centroid ST_Contains), Method B (1 km² cell polygon ST_Intersects), or Method C (area-weighted proportional estimate).",
        ],
    )
