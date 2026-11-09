"""Unit tests for the AI Spatial SQL Allow-List & Read-Only Safety Validator."""

import pytest
from src.ai.sql_validator import SQLValidationError, validate_spatial_sql
from src.ai.query_planner import plan_natural_language_query


ALLOWLIST = {
    "ga_electricity_substations",
    "nsw_water_inundation_areas",
    "nsw_foi_building_complexes",
    "next_lga_boundaries_asgs2025",
}


def test_valid_select_with_ctes_passes() -> None:
    sql = """
    WITH inund AS (
        SELECT geom FROM nsw_water_inundation_areas
    )
    SELECT s.objectid
    FROM ga_electricity_substations s
    JOIN inund i ON ST_Intersects(s.geom, i.geom)
    """
    res = validate_spatial_sql(sql, ALLOWLIST)
    assert "nsw_water_inundation_areas" in res["verified_tables"]
    assert "ga_electricity_substations" in res["verified_tables"]
    assert "inund" in res["cte_names"]


def test_ddl_or_dml_is_rejected() -> None:
    with pytest.raises(SQLValidationError):
        validate_spatial_sql("DROP TABLE ga_electricity_substations", ALLOWLIST)

    with pytest.raises(SQLValidationError):
        validate_spatial_sql("SELECT * FROM ga_electricity_substations; DELETE FROM ga_electricity_substations", ALLOWLIST)


def test_uncatalogued_table_is_rejected() -> None:
    with pytest.raises(SQLValidationError, match="uncatalogued"):
        validate_spatial_sql("SELECT * FROM imaginary_hospital_beds_table", ALLOWLIST)


def test_ambiguous_population_question_triggers_clarification() -> None:
    plan = plan_natural_language_query("How many people are affected by the flood?")
    assert plan.status == "CLARIFICATION_REQUIRED"
    assert len(plan.clarification_questions) >= 1


def test_uncatalogued_telemetry_triggers_rejection() -> None:
    plan = plan_natural_language_query("Show live SCADA load and ICU bed occupancy")
    assert plan.status == "REJECTED_UNCATALOGUED"

