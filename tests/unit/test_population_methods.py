"""Unit and integration tests for NExT Population Representation Comparison (Methods A, B, C)."""

from pathlib import Path
from src.analysis.population_methods import (
    METHOD_C_ASSUMPTION_LABEL,
    compare_population_methods_on_footprint,
)
from src.engines.duckdb_engine import DuckDBSpatialEngine

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
GRID_PARQUET = (
    PROJECT_ROOT
    / "data"
    / "lake"
    / "geoparquet"
    / "derived_hunter_1km_population_grid"
    / "ASGS2021-FOI-v1"
    / "20261109T003500Z"
    / "part-00000.parquet"
)


def test_population_methods_a_b_c_distinction_and_straddling_cells() -> None:
    """Verifies that Method A (centroid ST_Contains), Method B (polygon ST_Intersects), and
    Method C (area-weighted proportional estimate) execute on the 1 km² evaluation grid and
    explicitly separate fully contained vs boundary-straddling edge cases.
    """
    assert GRID_PARQUET.exists(), f"Expected 1 km² evaluation grid at {GRID_PARQUET}"

    # Narrow polygon crossing several 1 km² cells in the Lower Hunter
    narrow_wkt = "POLYGON ((151.552 -32.736, 151.584 -32.736, 151.584 -32.733, 151.552 -32.733, 151.552 -32.736))"

    with DuckDBSpatialEngine() as engine:
        res = compare_population_methods_on_footprint(
            engine=engine,
            grid_parquet_path=GRID_PARQUET,
            incident_wkt_7844=narrow_wkt,
            regime_id="test_narrow_strip",
            regime_title="Test Narrow Strip",
            regime_description="Unit test narrow corridor",
        )

    ma = res["method_a_centroid_contains"]
    mb = res["method_b_cell_polygon_intersects"]
    mc = res["method_c_area_weighted_proportional"]

    # Method B must find intersecting cells, even when narrow strip misses centroids in Method A
    assert mb["intersecting_cell_count"] > 0
    assert mb["intersecting_cell_count"] >= ma["cell_count"]
    assert (
        mb["fully_contained_cell_count"] + mb["boundary_straddling_cell_count"]
        == mb["intersecting_cell_count"]
    )
    assert mb["full_cell_population_total"] >= ma["population_total"]

    # Method C must be explicitly labelled as a modelled proportional estimate
    assert mc["is_modelled_estimate"] is True
    assert mc["assumption_warning"] == METHOD_C_ASSUMPTION_LABEL
    assert 0.0 < mc["proportional_population_estimate"] <= mb["full_cell_population_total"]

