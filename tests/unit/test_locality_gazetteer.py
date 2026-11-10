"""
tests/unit/test_locality_gazetteer.py
Verifies the ABS ASGS Locality & Postal Gazetteer:
- Verifies authoritative gazetteer entries loaded from docs/data/locality_gazetteer.json.
- Verifies bounding box validity (minx < maxx, miny < maxy in Australian extent).
- Verifies smoothed extent polygon geometry (rounded corners, clockwise winding, closed ring).
- Verifies spatial query against ga_major_power_stations within Sydney extent finds stations.
- Verifies buffer and simplification support for natural language queries (Wollongong, 5000m buffer).
- Verifies substation flood query template has zero conflicting bounding box clauses.
"""
import json
import math
import os
import re
import pytest


def test_gazetteer_contains_major_australian_localities():
    gaz_path = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "data", "locality_gazetteer.json")
    assert os.path.exists(gaz_path), f"Gazetteer missing at {gaz_path}"
    with open(gaz_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert len(data) >= 1000, f"Expected at least 1,000 localities, got {len(data)}"

    # Check key Australian cities and regions including Wollongong
    for key in ["sydney", "newcastle", "parramatta", "melbourne", "brisbane", "wollongong", "nsw", "vic", "qld"]:
        assert key in data, f"Key '{key}' should exist in gazetteer"
        entry = data[key]
        assert "bbox" in entry, f"Entry {key} missing bbox"
        minx, miny, maxx, maxy = entry["bbox"]
        assert 110.0 <= minx < maxx <= 160.0, f"Invalid longitude bounds for {key}: [{minx}, {maxx}]"
        assert -45.0 <= miny < maxy <= -8.0, f"Invalid latitude bounds for {key}: [{miny}, {maxy}]"


def test_smoothed_extent_polygon_math():
    bbox = [150.60, -34.15, 151.35, -33.60]  # Greater Sydney
    min_x, min_y, max_x, max_y = bbox
    w = max_x - min_x
    h = max_y - min_y
    r = min(w, h) * 0.12
    ring = []
    num_arc_points = 6

    def add_arc(cx, cy, start_ang, end_ang):
        for i in range(num_arc_points + 1):
            ang = start_ang + (end_ang - start_ang) * (i / num_arc_points)
            x = round(cx + r * math.cos(ang), 5)
            y = round(cy + r * math.sin(ang), 5)
            ring.append([x, y])

    add_arc(min_x + r, max_y - r, math.pi, math.pi / 2)
    add_arc(max_x - r, max_y - r, math.pi / 2, 0)
    add_arc(max_x - r, min_y + r, 2 * math.pi, 1.5 * math.pi)
    add_arc(min_x + r, min_y + r, 1.5 * math.pi, math.pi)

    if ring[0] != ring[-1]:
        ring.append(ring[0])

    # Ring must be closed
    assert ring[0] == ring[-1]
    # Ring must have rounded corners (more than 4 vertices)
    assert len(ring) >= 28

    # Shoelace formula to verify clockwise winding
    shoelace_sum = sum(
        (ring[i + 1][0] - ring[i][0]) * (ring[i + 1][1] + ring[i][1])
        for i in range(len(ring) - 1)
    )
    assert shoelace_sum > 0, f"Expected clockwise winding (sum > 0), got {shoelace_sum}"


def test_spatial_extent_resolves_power_stations_in_sydney():
    """Verifies that filtering power stations by Sydney spatial bbox finds actual stations, whereas state ILIKE '%Sydney%' fails."""
    geojson_path = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "qa", "data", "ga_major_power_stations.geojson")
    assert os.path.exists(geojson_path), f"GeoJSON missing at {geojson_path}"
    with open(geojson_path, "r", encoding="utf-8") as f:
        d = json.load(f)

    # 1. State ILIKE '%Sydney%' yields 0 features because state is 'NSW'
    state_match = [f for f in d["features"] if "sydney" in str(f.get("properties", {}).get("state", "")).lower()]
    assert len(state_match) == 0, "state is an Australian state (NSW), never 'Sydney'"

    # 2. Spatial bounding box filter for Sydney extent finds 5 stations
    sydney_bbox = [150.60, -34.15, 151.35, -33.60]
    spatial_match = []
    for f in d["features"]:
        x, y = f["geometry"]["coordinates"]
        if sydney_bbox[0] <= x <= sydney_bbox[2] and sydney_bbox[1] <= y <= sydney_bbox[3]:
            spatial_match.append(f)

    assert len(spatial_match) == 5, f"Expected 5 stations in Sydney extent, got {len(spatial_match)}"
    station_names = [f["properties"]["name"] for f in spatial_match]
    assert any("Smithfield" in n for n in station_names)
    assert any("Lucas Heights" in n for n in station_names)


def test_buffer_expansion_and_simplification_extraction():
    """Verifies natural language buffer and simplification extraction."""
    # Buffer parsing (supports both "buffer 5000m" and "5000m buffer")
    text1 = "Find substations near Wollongong with 5000m buffer"
    buf_match = (
        re.search(r"(?:buffer|catchment|proximity|distance|radius)(?:\s*(?:of|is|:))?\s*(\d+(?:\.\d+)?)\s*(km|m)?", text1, re.I)
        or re.search(r"(\d+(?:\.\d+)?)\s*(km|m|meters|metres)?\s*(?:buffer|catchment|proximity|radius)?", text1, re.I)
    )
    assert buf_match is not None
    assert buf_match.group(1) == "5000"

    # Simplification parsing (supports both "tolerance 50m" and "50m tolerance")
    text2 = "substations in Wollongong with 50m tolerance and 5km buffer"
    simp_match = (
        re.search(r"(?:simplif(?:y|ication)|tolerance|tolerance:|smooth(?:ing)?|fillet)\s*(\d+(?:\.\d+)?)\s*(m|km|%|deg)?", text2, re.I)
        or re.search(r"(\d+(?:\.\d+)?)\s*(m|km|%|deg)\s*(?:simplif(?:y|ication)|tolerance|smoothing)?", text2, re.I)
    )
    assert simp_match is not None
    assert simp_match.group(1) == "50"

    # Metric expansion on Wollongong bbox [150.75, -34.55, 151.00, -34.30]
    woll_bbox = [150.75, -34.55, 151.00, -34.30]
    buffer_m = 5000.0
    d_lat = buffer_m / 111320.0
    mid_lat = (woll_bbox[1] + woll_bbox[3]) / 2.0
    d_lon = buffer_m / (111320.0 * math.cos(math.radians(mid_lat)))

    buffered_bbox = [woll_bbox[0] - d_lon, woll_bbox[1] - d_lat, woll_bbox[2] + d_lon, woll_bbox[3] + d_lat]
    assert buffered_bbox[0] < woll_bbox[0]
    assert buffered_bbox[1] < woll_bbox[1]
    assert buffered_bbox[2] > woll_bbox[2]
    assert buffered_bbox[3] > woll_bbox[3]


def test_substation_flood_query_has_no_hunter_bbox_for_wollongong():
    """Verifies that when Wollongong is targeted, the query does NOT contain Hunter coordinates."""
    app_js_path = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "app.js")
    with open(app_js_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Ensure buildSqlForScenario for substation_flood does not hardcode hunter bbox unconditionally
    substation_fn_snippet = re.search(r'if \(key === "substation_flood"\) \{([\s\S]+?)return `-- Substation Flood', content)
    assert substation_fn_snippet is not None
    snippet = substation_fn_snippet.group(1)
    # The snippet must check resolved locality extent first
    assert "resolveLocalityExtent" in snippet
    # It must NOT unconditionally set bboxSql to 151.35 AND 151.90
    assert "bboxSql = `_bbox_xmax >= 151.35" not in snippet


def test_tweed_locality_and_power_query():
    """Verifies that Tweed is recognized synchronously in layers.js and generates spatial bbox filter, not state ILIKE '%Tweed%'."""
    layers_js_path = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "layers.js")
    with open(layers_js_path, "r", encoding="utf-8") as f:
        layers_content = f.read()

    # Tweed must be present in layers.js embedded gazetteer
    assert "tweed" in layers_content and "tweed heads" in layers_content, "tweed must be embedded directly in layers.js for zero-latency synchronous resolution"

    # Verify gazetteer json has tweed
    gaz_path = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "data", "locality_gazetteer.json")
    with open(gaz_path, "r", encoding="utf-8") as f:
        gaz = json.load(f)

    tweed = gaz["tweed"]
    assert tweed["bbox"] == [153.1067, -28.5427, 153.5863, -28.1569]
    assert tweed["center"] == [153.3465, -28.3498]
    assert tweed["state"] == "New South Wales"

    # Verify app.js parseAreaWhereClause protects state column from non-state locality filtering
    app_js_path = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "app.js")
    with open(app_js_path, "r", encoding="utf-8") as f:
        app_content = f.read()

    assert "validStateTokens" in app_content


def test_mannering_park_and_gcs_data_source_localities():
    """Verifies that Mannering park, Lake Munmorah, and infrastructure localities from GCS GeoParquet are indexed."""
    gaz_path = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "data", "locality_gazetteer.json")
    with open(gaz_path, "r", encoding="utf-8") as f:
        gaz = json.load(f)

    # 1. Check Mannering Park and Lake Munmorah
    assert "mannering park" in gaz, "mannering park must exist in locality gazetteer"
    assert "lake munmorah" in gaz, "lake munmorah must exist in locality gazetteer"
    mannering = gaz["mannering park"]
    assert mannering["bbox"] == [151.5262, -33.2093, 151.6305, -33.1433]

    # 2. Check prominent power station / substation infrastructure localities from GCS
    for loc_key in ["vales point", "eraring", "bayswater", "liddell"]:
        assert loc_key in gaz, f"Infrastructure node '{loc_key}' must exist in gazetteer"

    # 3. Check presence in layers.js embedded gazetteer
    layers_js_path = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "layers.js")
    with open(layers_js_path, "r", encoding="utf-8") as f:
        layers_content = f.read()

    assert "mannering park" in layers_content, "mannering park must be embedded in layers.js for zero-latency synchronous access"
    assert "vales point" in layers_content, "vales point must be embedded in layers.js"


def test_sql_bbox_extraction_and_extent_resolution():
    """Verifies that SQL queries with explicit _bbox_maxx/_bbox_minx or _bbox_xmax/_bbox_xmin predicates extract the bbox correctly."""
    sql = """
    WITH substations AS (
        SELECT
            name AS substation_name,
            state,
            locality,
            voltage_kv,
            ST_Transform(geom, 'EPSG:7844', 'EPSG:3112', true) AS geom_3112
        FROM read_parquet('gs://operational-intelligence-crafter-lake/geoparquet/ga_electricity_substations/2024-GA-NEI/20261108T223144Z/part-00000.parquet') s
        WHERE _bbox_maxx >= 151.5262 AND _bbox_minx <= 151.6305
          AND _bbox_maxy >= -33.2093 AND _bbox_miny <= -33.1433
      -- Area scope: Lake Munmorah - Mannering Park
    )
    """
    bbox_match = re.search(r"(?:_bbox_maxx|_bbox_xmax)\s*>=\s*(-?\d+\.?\d*)\s*AND\s*(?:_bbox_minx|_bbox_xmin)\s*<=\s*(-?\d+\.?\d*)\s*AND\s*(?:_bbox_maxy|_bbox_ymax)\s*>=\s*(-?\d+\.?\d*)\s*AND\s*(?:_bbox_miny|_bbox_ymin)\s*<=\s*(-?\d+\.?\d*)", sql, re.I)
    assert bbox_match is not None
    minx = float(bbox_match.group(1))
    maxx = float(bbox_match.group(2))
    miny = float(bbox_match.group(3))
    maxy = float(bbox_match.group(4))
    bbox = [minx, miny, maxx, maxy]
    assert bbox == [151.5262, -33.2093, 151.6305, -33.1433]

    # Verify Area scope extraction
    scope_match = re.search(r"--\s*Area scope:\s*([^\r\n]+)", sql, re.I)
    assert scope_match is not None
    assert scope_match.group(1).strip() == "Lake Munmorah - Mannering Park"


def test_aoi_mask_layer_registration_in_layers_js():
    """Verifies that the AOI focus mask is registered as a first-class layer in layers.js CATALOG and layer control."""
    layers_js_path = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "layers.js")
    with open(layers_js_path, "r", encoding="utf-8") as f:
        layers_content = f.read()

    # 1. CATALOG entry
    assert 'key: "aoi_focus_mask"' in layers_content
    assert 'Selection Focus Mask' in layers_content

    # 2. Layer ID mapping to MapLibre fill and outline layers
    assert 'if (key === "aoi_focus_mask") return ["territory-mask-fill", "aoi-boundary-line"];' in layers_content

    # 3. Opacity and visibility handlers for the mask layer
    assert 'if (key === "aoi_focus_mask")' in layers_content
    assert 'map.setPaintProperty("territory-mask-fill", "fill-opacity", o);' in layers_content


def test_aoi_ui_controls_and_wiring():
    """Verifies that the user AOI input controls, target area card, and event wiring exist and prevent input clobbering."""
    docs_dir = os.path.join(os.path.dirname(__file__), "..", "..", "docs")

    # 1. docs/index.html checks
    with open(os.path.join(docs_dir, "index.html"), "r", encoding="utf-8") as f:
        html_content = f.read()

    assert 'id="aoiInput"' in html_content
    assert 'id="targetAreaCard"' in html_content
    assert 'id="nlInput"' in html_content

    # 2. docs/app.js checks
    with open(os.path.join(docs_dir, "app.js"), "r", encoding="utf-8") as f:
        app_content = f.read()

    # setTargetArea helper defined and exposed
    assert "function setTargetArea(area, triggerMask = true)" in app_content
    assert "window.OICApp = {" in app_content
    assert "setTargetArea," in app_content
    # aoiInput event listener wired
    assert 'aoiInput.addEventListener("input"' in app_content
    # analyzeQuery does NOT overwrite custom queries or areas
    assert "if (inputEl && !rawNl)" in app_content

    # 3. docs/layers.js region buttons update AOI
    with open(os.path.join(docs_dir, "layers.js"), "r", encoding="utf-8") as f:
        layers_content = f.read()

    assert "window.OICApp.setTargetArea(chosenArea);" in layers_content


def test_locality_overrides_and_inverted_mask_wiring():
    """Verifies that locality overrides exist in layers.js and the inverted mask uses antimeridian-safe coordinates."""
    docs_dir = os.path.join(os.path.dirname(__file__), "..", "..", "docs")

    with open(os.path.join(docs_dir, "layers.js"), "r", encoding="utf-8") as f:
        layers_content = f.read()

    # Locality overrides defined and merged into gazetteer
    assert "LOCALITY_OVERRIDES" in layers_content
    for loc in ["maitland", "newcastle", "cessnock", "singleton", "port stephens", "lake macquarie", "hunter"]:
        assert f'"{loc}"' in layers_content or f"{loc}:" in layers_content, f"Locality override missing for {loc}"

    assert "const GAZETTEER = Object.assign({}, EMBEDDED_LGA_GAZETTEER, LOCALITY_OVERRIDES);" in layers_content

    # World ring in inverted mask is antimeridian-safe (prevents polygon width collapse at ±180)
    assert "-179.9999" in layers_content
    assert "179.9999" in layers_content


def test_workflow_stepper_and_fault_tolerant_execution():
    """Verifies workflow stepper ribbon smooth scroll with offset, and fault-tolerant Step 3, 4, 5, 6 generation."""
    docs_dir = os.path.join(os.path.dirname(__file__), "..", "..", "docs")

    with open(os.path.join(docs_dir, "index.html"), "r", encoding="utf-8") as f:
        html_content = f.read()

    assert 'id="workflowStepperRibbon"' in html_content
    for step in ["panel-query", "panel-sql", "panel-map", "panel-recommendations", "panel-analytics", "panel-ai-steps"]:
        assert f'data-step-pill="{step}"' in html_content

    with open(os.path.join(docs_dir, "app.js"), "r", encoding="utf-8") as f:
        app_content = f.read()

    # scrollToStep with header offset
    assert "function scrollToStep(targetId)" in app_content
    assert "setWorkflowActiveStep(targetId)" in app_content
    assert "headerHeight" in app_content

    # btnAnalyze scrolls to panel-sql
    assert 'scrollToStep("panel-sql")' in app_content

    # duckdbError does not abort execution of steps 3, 4, 5, 6
    assert "if (duckdbError) {" in app_content
    assert "DuckDB-WASM Engine Note:" in app_content
    # scrollToStep("panel-map") is called
    assert 'scrollToStep("panel-map")' in app_content




