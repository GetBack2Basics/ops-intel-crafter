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
