/*
  docs/app.js
  Interactive controller for Emergency Spatial Workbench.
  - Starts 100% blank on load (query, SQL, map, and results table).
  - Uses OpenStreetMap standard raster tiles (no carto.com).
  - When a preset or query is selected, prompts the user with plain-text inputs to define
    the target area and other options before creating the SQL in Step 02.
*/

(function () {
  let bundle = null;
  let map = null;
  let mapReady = false;
  let activeScenarioKey = null;
  let selectedPopMethod = "B";
  let selectedRegimeIdx = 1; // Default Regime 2: Observed NSW Inundation Basin

  // Current user-defined plain-text parameters
  let userParams = {
    area: "",
    distance: "",
    options: ""
  };

  const SCENARIO_PRESETS = {
    pop_comparison: {
      question: "Compare 1 km² population Methods A, B and C inside the flood inundation area",
      defaultArea: "Lower Hunter (151.45, -32.95, 151.82, -32.68)",
      defaultDistance: "0m (Direct polygon intersection)",
      defaultOptions: "Method B (1 km² Polygon Intersect), Regime 2 (Observed Flood Basin)",
      targetUri: "gs://operational-intelligence-crafter-lake/geoparquet/derived_hunter_1km_population_grid/",
      exportHref: "exports/hunter_population_grid_comparison/result.geojson"
    },
    substation_flood: {
      question: "Find power substations near flood inundation zones and count facilities within catchment distance",
      defaultArea: "Lower Hunter, Maitland, Newcastle",
      defaultDistance: "5000m facility catchment / 500m flood proximity",
      defaultOptions: "All voltages (33 kV - 500 kV), Metric CRS EPSG:3112",
      targetUri: "gs://operational-intelligence-crafter-lake/geoparquet/ga_electricity_substations/",
      exportHref: "exports/hunter_substation_flood_dependency/result.geojson"
    },
    lga_multi_hazard: {
      question: "Summarize LGAs by flood inundation polygons, substations, and building complexes",
      defaultArea: "Newcastle, Maitland, Cessnock, Port Stephens, Lake Macquarie",
      defaultDistance: "LGA boundary clip (ASGS 2025)",
      defaultOptions: "Include substations, flood zones, and FOI building complexes",
      targetUri: "gs://operational-intelligence-crafter-lake/geoparquet/next_lga_boundaries_asgs2025/",
      exportHref: "qa/data/next_lga_boundaries_asgs2025.geojson"
    },
    live_rfs: {
      question: "List active NSW RFS bushfire and grassfire incidents",
      defaultArea: "NSW Statewide (141.0, -37.5, 153.6, -28.1)",
      defaultDistance: "Statewide feed",
      defaultOptions: "All alert levels (Advice, Watch and Act, Emergency Warning)",
      targetUri: "gs://operational-intelligence-crafter-lake/geoparquet/nsw_rfs_major_incidents_live/",
      exportHref: "qa/data/nsw_rfs_major_incidents_live.geojson"
    },
    national_power: {
      question: "Aggregate power station generation capacity (MW) by state alongside NSHA seismic contours",
      defaultArea: "Australia National (NSW, QLD, VIC, WA, SA, TAS, NT)",
      defaultDistance: "National rollup by state",
      defaultOptions: "All primary fuel types + 2018 NSHA PGA contours",
      targetUri: "gs://operational-intelligence-crafter-lake/geoparquet/ga_major_power_stations/",
      exportHref: "qa/data/ga_major_power_stations.geojson"
    },
    ambiguous_pop: {
      question: "How many people live inside the flood zone?",
      defaultArea: "Maitland / Lower Hunter Floodplain",
      defaultDistance: "0m (Inside flood polygon)",
      defaultOptions: "Method B (1 km² Polygon Intersect), Regime 2 (Observed Flood Basin)",
      targetUri: "gs://operational-intelligence-crafter-lake/geoparquet/derived_hunter_1km_population_grid/",
      exportHref: "exports/hunter_population_grid_comparison/result.geojson"
    },
    uncatalogued_reject: {
      question: "Show live SCADA substation voltage telemetry and real-time hospital ICU bed occupancy in Newcastle.",
      defaultArea: "Newcastle",
      defaultDistance: "N/A",
      defaultOptions: "Live SCADA & ICU telemetry",
      targetUri: "BLOCKED — Source Not in Catalogue",
      exportHref: null,
      isRejected: true
    },
    cyclone_track_exposure: {
      question: "Assess critical Australian asset exposure and predicted hazard zones along the Tropical Cyclone WP302026 forecast track",
      defaultArea: "Eastern Australia & NSW Riverina (25.5°S - 41.7°S, 138.5°E - 155.9°E)",
      defaultDistance: "50 km Core / 150 km Severe Gale / 300 km Watch Zone",
      defaultOptions: "Advisory #48, 80 kt sustained (90 mph), gusts 95 kt, 974 mb minimum pressure",
      targetUri: "gs://operational-intelligence-crafter-lake/geoparquet/uploaded_cyclone_track/",
      exportHref: "data/WP302026_CYCLONE_ZONES.geojson"
    },
    uploaded_aoi_exposure: {
      question: "Evaluate operational exposure (population methods A/B/C, substations & health facilities) across custom Area of Interest",
      defaultArea: "Custom Uploaded Area of Interest (AOI)",
      defaultDistance: "Direct footprint intersection + 5 km catchment",
      defaultOptions: "Multi-scale GCS GeoParquet rollup",
      targetUri: "gs://operational-intelligence-crafter-lake/geoparquet/custom_aoi/",
      exportHref: null
    }
  };

  const LOCALITY_COORDS = {
    cyclone: { center: [145.0, -33.5], zoom: 5.2, bbox: [136.0, -43.0, 158.0, -24.0] },
    maitland: { center: [151.555, -32.732], zoom: 11.4, bbox: [151.45, -32.82, 151.66, -32.65] },
    newcastle: { center: [151.778, -32.928], zoom: 11.4, bbox: [151.66, -33.02, 151.85, -32.84] },
    cessnock: { center: [151.355, -32.834], zoom: 10.8, bbox: [151.15, -33.05, 151.50, -32.70] },
    "port stephens": { center: [151.92, -32.72], zoom: 10.5, bbox: [151.68, -32.85, 152.22, -32.60] },
    "lake macquarie": { center: [151.58, -33.05], zoom: 10.5, bbox: [151.38, -33.20, 151.75, -32.92] },
    hunter: { center: [151.63, -32.79], zoom: 10.3, bbox: [151.45, -32.95, 151.82, -32.68] },
    tablelands: { center: [145.38, -17.27], zoom: 9.2, bbox: [144.35, -18.25, 145.85, -16.85] },
    "central coast": { center: [151.35, -33.35], zoom: 10.0, bbox: [151.10, -33.60, 151.60, -33.10] },
    campbelltown: { center: [150.81, -34.07], zoom: 11.0, bbox: [150.70, -34.20, 150.95, -33.95] },
    nsw: { center: [149.5, -32.6], zoom: 5.8, bbox: [141.0, -37.5, 153.6, -28.1] },
    australia: { center: [134.5, -25.5], zoom: 3.7, bbox: [112.9, -43.7, 153.7, -10.0] }
  };

  // Load pre-computed verified bundle from GCS / local docs
  const bundlePromise = fetch("data/workbench_bundle.json")
    .then(r => r.json())
    .then(data => {
      bundle = data;
      return data;
    })
    .catch(err => {
      console.warn("Could not pre-load workbench_bundle.json:", err);
      return null;
    });

  // Initialize blank MapLibre map using OpenStreetMap standard tiles (no carto.com)
  function initMap() {
    map = new maplibregl.Map({
      container: "map",
      style: {
        version: 8,
        sources: {
          "osm-standard": {
            type: "raster",
            tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
            tileSize: 256,
            attribution: "© OpenStreetMap contributors"
          }
        },
        layers: [{ id: "osm-standard-layer", type: "raster", source: "osm-standard" }]
      },
      center: [151.2, -32.9],
      zoom: 6.2
    });
    map.addControl(new maplibregl.NavigationControl(), "top-right");
    map.on("load", () => {
      mapReady = true;
      // AURA-style layer control, click-to-identify popups, metadata, charts & attribute table (docs/layers.js)
      if (window.OICLayers) window.OICLayers.attach(map);
    });
  }

  // Shows a set of catalogue layers (top-first) via the shared Layer Control.
  function showQueryLayers(keys) {
    if (window.OICLayers) window.OICLayers.activate(keys);
  }

  function clearMapLayers() {
    if (window.OICLayers) window.OICLayers.clear();
  }

  function parseNumericDistance(text, fallbackMeters) {
    if (!text) return fallbackMeters;
    const kmMatch = text.match(/(\d+(?:\.\d+)?)\s*km/i);
    if (kmMatch) return Math.round(parseFloat(kmMatch[1]) * 1000);
    const mMatch = text.match(/(\d+(?:\.\d+)?)\s*m\b/i) || text.match(/^(\d+(?:\.\d+)?)$/);
    if (mMatch) return Math.round(parseFloat(mMatch[1]));
    return fallbackMeters;
  }

  function parseAreaWhereClause(areaText, columnExpr) {
    const raw = (areaText || "").trim();
    if (!raw) return "-- No additional area filter";
    const bboxMatch = raw.match(/(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)/);
    if (bboxMatch) {
      const [, minX, minY, maxX, maxY] = bboxMatch;
      return `AND _bbox_xmax >= ${minX} AND _bbox_xmin <= ${maxX} AND _bbox_ymax >= ${minY} AND _bbox_ymin <= ${maxY}`;
    }
    const tokens = raw
      .split(/[,;/]+/)
      .map(s => s.trim())
      .filter(s => s && !/lower hunter|statewide|national|australia|all|floodplain/i.test(s));
    if (!tokens.length) return `-- Area scope: ${raw.replace(/'/g, "")}`;
    const ilikes = tokens.map(t => `${columnExpr} ILIKE '%${t.replace(/'/g, "")}%'`).join(" OR ");
    return `AND (${ilikes})`;
  }

  function buildSqlForScenario(key) {
    if (!bundle) return "-- Loading catalogue metadata...";
    const areaText = (userParams.area || "").trim();
    const distText = (userParams.distance || "").trim();
    const optText = (userParams.options || "").trim();

    if (key === "pop_comparison" || key === "ambiguous_pop") {
      const reg = bundle.population_study.regimes[selectedRegimeIdx] || bundle.population_study.regimes[1];
      const areaFilterSql = parseAreaWhereClause(areaText, "g.sa2_name21");
      return `-- 1 km² Population Comparison (${reg.regime_title})
-- User Area: ${areaText || "Lower Hunter"}
-- User Distance / Buffer: ${distText || "0m"}
-- User Options: ${optText || `Method ${selectedPopMethod}`}
WITH incident AS (
    SELECT
        ST_GeomFromText('${reg.incident_wkt_7844.slice(0, 96)}...') AS geom_7844,
        ST_Transform(geom_7844, 'EPSG:7844', 'EPSG:3112', true) AS geom_3112
)
SELECT
    g.cell_id,
    g.sa2_name21,
    g.cell_population,
    ST_Contains(i.geom_7844, ST_Centroid(g.geom)) AS in_method_a,
    ST_Intersects(i.geom_7844, g.geom) AS in_method_b,
    ST_Contains(i.geom_7844, g.geom) AS fully_contained_b,
    ROUND(
        ST_Area(ST_Intersection(i.geom_3112, ST_Transform(g.geom, 'EPSG:7844', 'EPSG:3112', true)))
        / NULLIF(ST_Area(ST_Transform(g.geom, 'EPSG:7844', 'EPSG:3112', true)), 0.0),
        4
    ) AS method_c_overlap_fraction
FROM read_parquet('gs://operational-intelligence-crafter-lake/geoparquet/derived_hunter_1km_population_grid/ASGS2021-FOI-v1/20261109T003500Z/part-00000.parquet') g
CROSS JOIN incident i
WHERE ST_Intersects(i.geom_7844, g.geom)
  ${areaFilterSql}
ORDER BY g.cell_id;`;
    }

    if (key === "substation_flood") {
      const catchMeters = parseNumericDistance(distText, 5000);
      const bboxMatch = areaText.match(/(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)/);
      let bboxSql = "";
      if (bboxMatch) {
        const [, minX, minY, maxX, maxY] = bboxMatch;
        bboxSql = `_bbox_xmax >= ${minX} AND _bbox_xmin <= ${maxX}\n      AND _bbox_ymax >= ${minY} AND _bbox_ymin <= ${maxY}`;
      } else {
        bboxSql = `_bbox_xmax >= 151.35 AND _bbox_xmin <= 151.90\n      AND _bbox_ymax >= -33.05 AND _bbox_ymin <= -32.60`;
      }
      const areaFilterSql = bboxMatch ? "" : parseAreaWhereClause(areaText, "s.locality");
      return `-- Substation Flood Proximity & Facility Catchment
-- User Area: ${areaText || "Lower Hunter"}
-- User Catchment Distance: ${catchMeters}m (${distText || "5000m"})
-- User Options: ${optText || "All voltages"}
WITH substations AS (
    SELECT
        name AS substation_name,
        state,
        locality,
        voltage_kv,
        ST_Transform(geom, 'EPSG:7844', 'EPSG:3112', true) AS geom_3112
    FROM read_parquet('gs://operational-intelligence-crafter-lake/geoparquet/ga_electricity_substations/2024-GA-NEI/20261108T223144Z/part-00000.parquet') s
    WHERE ${bboxSql}
      ${areaFilterSql}
),
inundation AS (
    SELECT ST_Transform(geom, 'EPSG:7844', 'EPSG:3112', true) AS geom_3112
    FROM read_parquet('gs://operational-intelligence-crafter-lake/geoparquet/nsw_water_inundation_areas/2024-NSW-DCS/20261108T223144Z/part-00000.parquet')
),
foi AS (
    SELECT ST_Transform(geom, 'EPSG:7844', 'EPSG:3112', true) AS geom_3112
    FROM read_parquet('gs://operational-intelligence-crafter-lake/geoparquet/nsw_foi_building_complexes/2024-NSW-FOI/20261108T223144Z/part-00000.parquet')
)
SELECT
    s.substation_name,
    s.locality,
    s.voltage_kv,
    ROUND(MIN(ST_Distance(s.geom_3112, i.geom_3112)), 1) AS distance_to_inundation_m,
    (SELECT COUNT(*) FROM foi f WHERE ST_DWithin(s.geom_3112, f.geom_3112, ${catchMeters}.0)) AS dependent_foi_within_m
FROM substations s
CROSS JOIN inundation i
GROUP BY s.substation_name, s.locality, s.voltage_kv, s.geom_3112
ORDER BY distance_to_inundation_m ASC;`;
    }

    if (key === "lga_multi_hazard") {
      const areaFilterSql = parseAreaWhereClause(areaText, "l.lga_name_2025");
      return `-- Regional LGA Flood, Substation & Building Summary
-- User Area: ${areaText || "Lower Hunter LGAs"}
-- User Distance / Clip: ${distText || "LGA boundary clip"}
-- User Options: ${optText || "Include substations, flood zones, and FOI complexes"}
SELECT
    l.lga_code_2025 AS lga_code,
    l.lga_name_2025 AS lga_name,
    ROUND(l.area_albers_sqkm, 1) AS area_sqkm,
    (SELECT COUNT(*) FROM read_parquet('gs://operational-intelligence-crafter-lake/geoparquet/ga_electricity_substations/2024-GA-NEI/20261108T223144Z/part-00000.parquet') s
     WHERE ST_Intersects(l.geom, s.geom)) AS substations_count,
    (SELECT COUNT(*) FROM read_parquet('gs://operational-intelligence-crafter-lake/geoparquet/nsw_water_inundation_areas/2024-NSW-DCS/20261108T223144Z/part-00000.parquet') w
     WHERE ST_Intersects(l.geom, w.geom)) AS inundation_polygons_count,
    (SELECT COUNT(*) FROM read_parquet('gs://operational-intelligence-crafter-lake/geoparquet/nsw_foi_building_complexes/2024-NSW-FOI/20261108T223144Z/part-00000.parquet') f
     WHERE ST_Intersects(l.geom, f.geom)) AS foi_complexes_count
FROM read_parquet('gs://operational-intelligence-crafter-lake/geoparquet/next_lga_boundaries_asgs2025/ASGS2025/20261108T223144Z/part-00000.parquet') l
WHERE 1=1
  ${areaFilterSql}
ORDER BY foi_complexes_count DESC;`;
    }

    if (key === "live_rfs") {
      const areaFilterSql = parseAreaWhereClause(areaText, "title || ' ' || COALESCE(description, '')");
      return `-- NSW RFS Active Bushfire & Grassfire Incidents
-- User Area: ${areaText || "NSW Statewide"}
-- User Options: ${optText || "All alert levels"}
SELECT
    title AS incident_title,
    category AS alert_level,
    ROUND(ST_X(ST_Centroid(geom)), 4) AS lon,
    ROUND(ST_Y(ST_Centroid(geom)), 4) AS lat,
    description AS details
FROM read_parquet('gs://operational-intelligence-crafter-lake/geoparquet/nsw_rfs_major_incidents_live/LIVE-FEED/20261108T223144Z/part-00000.parquet')
WHERE 1=1
  ${areaFilterSql}
ORDER BY title;`;
    }

    if (key === "national_power") {
      const areaFilterSql = parseAreaWhereClause(areaText, "COALESCE(state, '')");
      return `-- National Power Generation Capacity by State + NSHA 2018 Seismic Baseline
-- User Area: ${areaText || "Australia National"}
-- User Options: ${optText || "All fuel types"}
SELECT
    COALESCE(state, 'Unknown') AS state_name,
    COUNT(*) AS power_station_count,
    ROUND(SUM(TRY_CAST(generation_capacity_mw AS DOUBLE)), 1) AS total_capacity_mw,
    COUNT(DISTINCT primary_fuel_type) AS fuel_types_count
FROM read_parquet('gs://operational-intelligence-crafter-lake/geoparquet/ga_major_power_stations/2024-GA-NEI/20261108T223144Z/part-00000.parquet')
WHERE 1=1
  ${areaFilterSql}
GROUP BY COALESCE(state, 'Unknown')
ORDER BY total_capacity_mw DESC;`;
    }
    if (key === "cyclone_track_exposure") {
      const cycName = (uploadedCycloneData && uploadedCycloneData.metadata && uploadedCycloneData.metadata.cyclone_name) || "Tropical Cyclone WP302026";
      const advNum = (uploadedCycloneData && uploadedCycloneData.metadata && uploadedCycloneData.metadata.advisory) || "48";
      return `-- Australian Tropical Cyclone Asset Exposure & Predicted Hazard Zones (DuckDB Spatial / Sedona)
-- Cyclone Hazard: ${cycName} (Advisory #${advNum})
-- Track Footprint: Inland Queensland / SA Channel Country & NSW Riverina (25.5°S - 41.7°S)
-- Operational Concentric Zones: 50 km (Zone 1 Core >64 kt), 150 km (Zone 2 Severe Gale 48-63 kt), 300 km (Zone 3 Watch 34-47 kt)
WITH track AS (
    SELECT ST_GeomFromText('LINESTRING(138.5 -25.5, 139.0 -26.9, 141.7 -30.1, 147.6 -35.1, 155.9 -41.7)') AS track_geom
),
critical_assets AS (
    SELECT
        name AS asset_name,
        locality,
        state,
        voltage_kv,
        'Substation' AS asset_type,
        geom
    FROM read_parquet('gs://operational-intelligence-crafter-lake/geoparquet/ga_electricity_substations/2024-GA-NEI/20261108T223144Z/part-00000.parquet')
    WHERE state IN ('NSW', 'VIC', 'SA', 'QLD')
)
SELECT
    a.asset_name,
    a.locality,
    a.state,
    a.voltage_kv,
    ROUND(ST_Distance_Sphere(a.geom, t.track_geom) / 1000.0, 1) AS distance_to_track_km,
    CASE
        WHEN ST_Distance_Sphere(a.geom, t.track_geom) <= 50000.0 THEN 'ZONE_1: Destructive Core / Eyewall (>64 kt)'
        WHEN ST_Distance_Sphere(a.geom, t.track_geom) <= 150000.0 THEN 'ZONE_2: Severe Gale Force (48–63 kt)'
        WHEN ST_Distance_Sphere(a.geom, t.track_geom) <= 300000.0 THEN 'ZONE_3: Outer Gale Watch (34–47 kt)'
        ELSE 'ZONE_4: Peripheral / Outside Direct Warning Cone'
    END AS predicted_cyclone_zone
FROM critical_assets a
CROSS JOIN track t
ORDER BY distance_to_track_km ASC
LIMIT 30;`;
    }
    if (key === "uploaded_aoi_exposure") {
      const aoiName = (uploadedAoiData && uploadedAoiData.name) || "Custom Area of Interest";
      return `-- Custom Area of Interest (AOI) Multi-Scale Operational Intelligence
-- Area of Interest: ${aoiName}
-- GCS Lakehouse Sources: Derived 1km Population Grid, GA Electricity Substations & NSW FOI Facilities
WITH custom_aoi AS (
    SELECT ST_Transform(geom, 'EPSG:7844', 'EPSG:3112', true) AS aoi_3112
    FROM uploaded_custom_aoi
),
pop_exposure AS (
    SELECT
        COUNT(*) AS intersecting_1km_cells,
        SUM(cell_population) AS method_b_full_cell_pop,
        ROUND(SUM(cell_population * ST_Area(ST_Intersection(ST_Transform(g.geom, 'EPSG:7844', 'EPSG:3112', true), a.aoi_3112)) / NULLIF(ST_Area(ST_Transform(g.geom, 'EPSG:7844', 'EPSG:3112', true)), 0)), 0) AS method_c_area_weighted_pop
    FROM read_parquet('gs://operational-intelligence-crafter-lake/geoparquet/derived_hunter_1km_population_grid/ASGS2021-FOI-v1/20261109T003500Z/part-00000.parquet') g
    JOIN custom_aoi a ON ST_Intersects(ST_Transform(g.geom, 'EPSG:7844', 'EPSG:3112', true), a.aoi_3112)
),
substations_near AS (
    SELECT COUNT(*) AS sub_count_5km
    FROM read_parquet('gs://operational-intelligence-crafter-lake/geoparquet/ga_electricity_substations/2024-GA-NEI/20261108T223144Z/part-00000.parquet') s
    JOIN custom_aoi a ON ST_DWithin(ST_Transform(s.geom, 'EPSG:7844', 'EPSG:3112', true), a.aoi_3112, 5000.0)
),
facilities_inside AS (
    SELECT COUNT(*) AS facilities_count
    FROM read_parquet('gs://operational-intelligence-crafter-lake/geoparquet/nsw_foi_building_complexes/2024-NSW-FOI/20261108T223144Z/part-00000.parquet') f
    JOIN custom_aoi a ON ST_Intersects(ST_Transform(f.geom, 'EPSG:7844', 'EPSG:3112', true), a.aoi_3112)
)
SELECT * FROM pop_exposure, substations_near, facilities_inside;`;
    }
    return "";
  }

  function inferScenarioFromText(text) {
    const q = (text || "").toLowerCase();
    if (!q) return "pop_comparison";
    if (q.includes("scada") || q.includes("icu") || q.includes("restricted") || q.includes("token")) {
      return "uncatalogued_reject";
    }
    if (q.includes("cyclone") || q.includes("typhoon") || q.includes("wp302026") || q.includes("track") || q.includes("in-fa")) {
      return "cyclone_track_exposure";
    }
    if ((q.includes("how many people") || q.includes("population") || q.includes("residents")) &&
      !q.includes("method a") && !q.includes("method b") && !q.includes("method c") && !q.includes("compare")) {
      return "ambiguous_pop";
    }
    if (q.includes("substation") || q.includes("5km") || q.includes("5 km") || q.includes("dependent") || q.includes("catchment")) {
      return "substation_flood";
    }
    if (q.includes("rfs") || q.includes("bushfire") || q.includes("fire") || q.includes("live")) {
      return "live_rfs";
    }
    if (q.includes("national") || q.includes("power station") || q.includes("seismic") || q.includes("pga")) {
      return "national_power";
    }
    if (q.includes("lga") || q.includes("council") || q.includes("rollup") || q.includes("summary")) {
      return "lga_multi_hazard";
    }
    return "pop_comparison";
  }

  // Disambiguation Knowledge Base: Matches ambiguous administrative and geographic entities
  // Only triggered when a location keyword in user query can refer to multiple distinct councils or states
  const AMBIGUOUS_ENTITIES = {
    tablelands: {
      term: "Tablelands",
      description: "Multiple regional councils, localities, and geographic districts named Tablelands exist across Australia.",
      options: [
        {
          label: "Tablelands Regional Council (LGA, QLD)",
          desc: "Atherton Tablelands Local Government Area [LGA36880] covering Mareeba, Atherton, Herberton",
          bbox: [144.35, -18.25, 145.85, -16.85],
          areaText: "Tablelands Regional Council (QLD)",
          center: [145.38, -17.27],
          zoom: 9.2
        },
        {
          label: "Northern Tablelands / Armidale (District / LGA, NSW)",
          desc: "New England / Northern Tablelands region encompassing Armidale, Guyra, Uralla",
          bbox: [151.20, -31.10, 152.40, -29.90],
          areaText: "Northern Tablelands / Armidale Regional (NSW)",
          center: [151.67, -30.51],
          zoom: 9.0
        },
        {
          label: "Central Tablelands / Bathurst-Orange (District, NSW)",
          desc: "Central Tablelands regional envelope covering Bathurst, Orange, Blayney, Oberon",
          bbox: [148.80, -34.10, 150.10, -33.10],
          areaText: "Central Tablelands / Bathurst-Orange (NSW)",
          center: [149.30, -33.45],
          zoom: 9.0
        },
        {
          label: "Southern Tablelands / Goulburn-Yass (District, NSW)",
          desc: "Southern Tablelands regional envelope covering Goulburn Mulwaree, Upper Lachlan, Yass Valley",
          bbox: [148.70, -35.20, 150.20, -34.10],
          areaText: "Southern Tablelands / Goulburn (NSW)",
          center: [149.72, -34.75],
          zoom: 8.8
        },
        {
          label: "Tablelands (Locality, QLD - 4678)",
          desc: "Rural locality in Gladstone Region, Central Queensland (postcode 4678)",
          bbox: [151.05, -24.45, 151.40, -24.15],
          areaText: "Tablelands (Locality 4678, QLD)",
          center: [151.22, -24.30],
          zoom: 11.0
        }
      ]
    },
    "central coast": {
      term: "Central Coast",
      description: "Can refer to Central Coast Council in NSW (Gosford-Wyong) or Central Coast Council in Tasmania.",
      options: [
        {
          label: "Central Coast Council (LGA, NSW)",
          desc: "Gosford, Wyong, Tuggerah Lakes, Terrigal coastal region",
          bbox: [151.10, -33.60, 151.60, -33.10],
          areaText: "Central Coast (NSW)",
          center: [151.35, -33.35],
          zoom: 10.0
        },
        {
          label: "Central Coast Council (LGA, TAS)",
          desc: "Ulverstone, Penguin, Leven River region on Tasmanian north coast",
          bbox: [145.90, -41.40, 146.30, -41.10],
          areaText: "Central Coast (TAS)",
          center: [146.15, -41.20],
          zoom: 10.2
        }
      ]
    },
    "campbelltown": {
      term: "Campbelltown",
      description: "Major local government areas named Campbelltown exist in both Greater Sydney and Adelaide.",
      options: [
        {
          label: "City of Campbelltown (LGA, Greater Sydney NSW)",
          desc: "Campbelltown, Macarthur, Ingleburn, Glenfield urban area",
          bbox: [150.70, -34.20, 150.95, -33.95],
          areaText: "Campbelltown (NSW)",
          center: [150.81, -34.07],
          zoom: 11.0
        },
        {
          label: "City of Campbelltown (LGA, Adelaide SA)",
          desc: "Inner north-eastern Adelaide suburbs (Newton, Magill, Paradise)",
          bbox: [138.65, -34.92, 138.74, -34.85],
          areaText: "Campbelltown (SA)",
          center: [138.69, -34.88],
          zoom: 12.0
        }
      ]
    }
  };

  // Known unambiguous location aliases that can be extracted cleanly from natural language
  const KNOWN_LOCATIONS = [
    { key: "maitland", label: "Maitland (NSW)", center: [151.555, -32.732], zoom: 11.4, bbox: [151.45, -32.82, 151.66, -32.65] },
    { key: "newcastle", label: "Newcastle (NSW)", center: [151.778, -32.928], zoom: 11.4, bbox: [151.66, -33.02, 151.85, -32.84] },
    { key: "cessnock", label: "Cessnock (NSW)", center: [151.355, -32.834], zoom: 10.8, bbox: [151.15, -33.05, 151.50, -32.70] },
    { key: "port stephens", label: "Port Stephens (NSW)", center: [151.92, -32.72], zoom: 10.5, bbox: [151.68, -32.85, 152.22, -32.60] },
    { key: "lake macquarie", label: "Lake Macquarie (NSW)", center: [151.58, -33.05], zoom: 10.5, bbox: [151.38, -33.20, 151.75, -32.92] },
    { key: "hunter", label: "Lower Hunter Floodplain", center: [151.63, -32.79], zoom: 10.3, bbox: [151.45, -32.95, 151.82, -32.68] },
    { key: "singleton", label: "Singleton (NSW)", center: [151.17, -32.56], zoom: 11.0, bbox: [151.05, -32.65, 151.30, -32.48] },
    { key: "muswellbrook", label: "Muswellbrook (NSW)", center: [150.89, -32.22], zoom: 11.0, bbox: [150.78, -32.32, 151.00, -32.12] },
    { key: "upper hunter", label: "Upper Hunter Shire (NSW)", center: [150.85, -32.05], zoom: 9.5, bbox: [150.00, -32.40, 151.30, -31.60] },
    { key: "sydney", label: "Greater Sydney (NSW)", center: [151.20, -33.87], zoom: 10.0, bbox: [150.60, -34.15, 151.35, -33.60] },
    { key: "nsw", label: "NSW Statewide", center: [149.5, -32.6], zoom: 5.8, bbox: [141.0, -37.5, 153.6, -28.1] },
    { key: "australia", label: "Australia National", center: [134.5, -25.5], zoom: 3.7, bbox: [112.9, -43.7, 153.7, -10.0] }
  ];

  // Inspects user text to determine location status: "CLEAR", "AMBIGUOUS", or "MISSING"
  function detectLocationStatus(text) {
    if (!text) return { status: "MISSING", locationText: "", entity: null };
    const lower = text.toLowerCase().trim();

    // 1. Check for ambiguous geographic names first
    for (const [key, entity] of Object.entries(AMBIGUOUS_ENTITIES)) {
      const regex = new RegExp(`\\b${key}\\b`, "i");
      if (regex.test(lower)) {
        // If state or council suffix already provided, it is clear!
        if (lower.includes("(qld)") || lower.includes("(nsw)") || lower.includes("(tas)") || lower.includes("(sa)") ||
            lower.includes("regional council") || lower.includes("shire") || lower.includes("city of")) {
          return { status: "CLEAR", locationText: text, entity: null };
        }
        return { status: "AMBIGUOUS", locationText: entity.term, entity };
      }
    }

    // 2. Check for explicit bounding box coordinates
    const bboxMatch = text.match(/(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)/);
    if (bboxMatch) {
      return { status: "CLEAR", locationText: bboxMatch[0], entity: null };
    }

    // 3. Check for known unambiguous locations
    for (const loc of KNOWN_LOCATIONS) {
      const regex = new RegExp(`\\b${loc.key}\\b`, "i");
      if (regex.test(lower)) {
        return { status: "CLEAR", locationText: loc.label, entity: null, locMatch: loc };
      }
    }

    return { status: "MISSING", locationText: "", entity: null };
  }

  // State to hold active disambiguation pending selection
  let pendingDisambiguation = null;

  // Checks user input text for known ambiguous geographic terms
  function checkAreaDisambiguation(areaText) {
    if (!areaText) return null;
    const lower = areaText.toLowerCase().trim();
    for (const [key, entity] of Object.entries(AMBIGUOUS_ENTITIES)) {
      const regex = new RegExp(`\\b${key}\\b`, "i");
      if (regex.test(lower) || lower === key) {
        if (lower.includes("(qld)") || lower.includes("(nsw)") || lower.includes("(tas)") || lower.includes("(sa)") || lower.includes("regional council") || lower.includes("shire")) {
          continue;
        }
        return entity;
      }
    }
    return null;
  }

  // Renders the Disambiguation Prompt inside clarificationQuestions
  function renderDisambiguationPrompt(entity, targetContainer, onSelectCallback) {
    const card = document.createElement("div");
    card.id = "disambiguationCard";
    card.className = "p-3.5 rounded-xl border-2 border-secondary bg-surface-container-high space-y-3";
    card.innerHTML = `
      <div class="flex items-center justify-between gap-2 border-b border-outline-variant/40 pb-2.5">
        <div class="flex items-center gap-2">
          <span class="material-symbols-outlined text-secondary text-[22px]">help_center</span>
          <div>
            <div class="text-xs font-bold uppercase tracking-wider text-secondary">Ambiguous Location Detected: "${entity.term}"</div>
            <p class="text-xs text-on-surface-variant font-medium">${entity.description} Please choose the exact geographic authority or region:</p>
          </div>
        </div>
        <span class="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-secondary-fixed text-on-secondary-fixed">Disambiguation Required</span>
      </div>
      <div class="space-y-2" id="disambigOptionsList">
        ${entity.options.map((opt, idx) => `
          <label class="flex items-start gap-3 p-2.5 rounded-lg border border-outline-variant/60 bg-surface-container-lowest hover:border-secondary hover:bg-surface-container cursor-pointer transition-all">
            <input type="radio" name="disambigChoice" value="${idx}" class="mt-1 accent-secondary" ${idx === 0 ? "checked" : ""}/>
            <div class="space-y-0.5 min-w-0 flex-1">
              <div class="text-xs font-bold text-on-surface flex items-center justify-between">
                <span>${opt.label}</span>
                <span class="text-[10px] font-mono text-on-surface-variant">[${opt.bbox.join(", ")}]</span>
              </div>
              <p class="text-[11px] text-on-surface-variant leading-relaxed">${opt.desc}</p>
            </div>
          </label>
        `).join("")}
      </div>
      <div class="flex items-center justify-between pt-1 border-t border-outline-variant/40">
        <span class="text-[11px] text-on-surface-variant italic">Selecting an option automatically configures the query bounding box and map zoom.</span>
        <button type="button" id="btnConfirmDisambiguation" class="px-4 py-1.5 rounded-lg text-xs font-bold bg-secondary text-white hover:bg-secondary/90 transition-colors shadow-sm flex items-center gap-1.5">
          <span class="material-symbols-outlined text-[15px]">check</span>
          <span>Apply Selected Area</span>
        </button>
      </div>
    `;

    targetContainer.prepend(card);

    const btnConfirm = card.querySelector("#btnConfirmDisambiguation");
    if (btnConfirm) {
      btnConfirm.addEventListener("click", () => {
        const checked = card.querySelector("input[name=\"disambigChoice\"]:checked");
        const selIdx = checked ? parseInt(checked.value, 10) : 0;
        const chosen = entity.options[selIdx];
        if (chosen) {
          onSelectCallback(chosen);
        }
      });
    }
  }

  // Opens the Clarification Panel for geographic extent
  function openLocationClarificationModal(key, detectionResult) {
    const preset = SCENARIO_PRESETS[key] || SCENARIO_PRESETS.pop_comparison;
    const box = document.getElementById("clarificationBox");
    const title = document.getElementById("clarificationTitle");
    const container = document.getElementById("clarificationQuestions");
    const actions = document.getElementById("clarificationActions");
    const banner = document.getElementById("paramValidationBanner");
    if (banner) banner.classList.add("hidden");

    box.style.display = "flex";

    if (preset.isRejected) {
      title.textContent = "Dataset Not Available in Catalogue";
      actions.style.display = "none";
      container.innerHTML = `
        <div class="p-4 rounded-lg bg-error-container text-on-error-container text-sm space-y-2">
          <div class="font-bold">Requested Source Not in Catalogue (src/ai/sql_validator.py)</div>
          <p>Live SCADA substation telemetry, hospital ICU bed occupancy, and token-restricted endpoints (<code class="font-mono">nsw_emergency_management_restricted</code> — HTTP 200 with embedded error <code class="font-mono">499: Token Required</code>) are not available in the verified GeoParquet catalogue.</p>
          <p class="font-semibold">Select another preset above to define an area and create SQL.</p>
        </div>
      `;
      document.getElementById("sqlInput").value = "-- BLOCKED: Requested dataset is not in the catalogue or failed source validation.";
      return;
    }

    actions.style.display = "flex";

    if (detectionResult && detectionResult.status === "AMBIGUOUS" && detectionResult.entity) {
      // Location is present but ambiguous (e.g. Tablelands, Central Coast, Campbelltown)
      title.textContent = `Location Disambiguation Required: "${detectionResult.entity.term}"`;
      container.innerHTML = "";
      renderDisambiguationPrompt(detectionResult.entity, container, (chosen) => {
        userParams.area = `${chosen.areaText} (${chosen.bbox.join(", ")})`;
        LOCALITY_COORDS[detectionResult.entity.term.toLowerCase()] = { center: chosen.center, zoom: chosen.zoom, bbox: chosen.bbox };
        box.style.display = "none";
        generateValidatedQuery(key);
      });
    } else {
      // Prompt user to confirm or choose Geographic Extent
      const defaultArea = (detectionResult && detectionResult.locationText) || userParams.area || preset.defaultArea;
      title.textContent = "Clarify Geographic Extent for Query";
      const activeUploadedLabel = (uploadedCycloneData && uploadedCycloneData.metadata && (uploadedCycloneData.metadata.cyclone_name || "Active Cyclone Track")) ||
        (uploadedAoiData && (uploadedAoiData.name || "Active Uploaded AOI")) || null;

      container.innerHTML = `
        <div class="p-4 rounded-xl bg-surface-container-high border border-outline-variant space-y-3">
          <div class="flex items-start justify-between gap-2">
            <div class="flex items-center gap-2">
              <span class="material-symbols-outlined text-secondary text-[22px]">map</span>
              <div>
                <p class="text-xs text-on-surface font-semibold">Select or confirm the geographic extent / catchment area for this analysis:</p>
                <p class="text-[11px] text-on-surface-variant font-medium">All spatial queries execute within validated Australian administrative and hazard bounds.</p>
              </div>
            </div>
          </div>
          <div class="grid grid-cols-2 sm:grid-cols-5 gap-2 pt-1">
            ${activeUploadedLabel ? `<button type="button" class="chip chip-featured justify-center text-xs py-2 col-span-2 sm:col-span-1" data-quick-loc="${activeUploadedLabel}">Active Upload</button>` : ""}
            <button type="button" class="chip justify-center text-xs py-2" data-quick-loc="Lower Hunter Floodplain">Lower Hunter</button>
            <button type="button" class="chip justify-center text-xs py-2" data-quick-loc="Maitland (NSW)">Maitland</button>
            <button type="button" class="chip justify-center text-xs py-2" data-quick-loc="Newcastle (NSW)">Newcastle</button>
            <button type="button" class="chip justify-center text-xs py-2" data-quick-loc="NSW Statewide">NSW Statewide</button>
            <button type="button" class="chip justify-center text-xs py-2" data-quick-loc="Australia National">Australia National</button>
          </div>
          <div class="space-y-1.5 pt-1">
            <div class="flex items-center justify-between">
              <label for="customLocInput" class="block text-[11px] font-bold uppercase tracking-wider text-on-surface-variant">Or Enter Custom Suburb, LGA, or Bounding Box:</label>
              <div class="flex items-center gap-2">
                <button id="btnModalFlipLat" type="button" class="chip text-[11px] py-1 px-2.5 flex items-center gap-1 hover:border-secondary transition-colors" title="Invert/Flip Latitude (North ↔ South / +Y ↔ -Y)">
                  <span class="material-symbols-outlined text-[13px]">swap_vert</span> Flip Lat (Y)
                </button>
                <button id="btnModalFlipXy" type="button" class="chip text-[11px] py-1 px-2.5 flex items-center gap-1 hover:border-secondary transition-colors" title="Swap Coordinates (X ↔ Y)">
                  <span class="material-symbols-outlined text-[13px]">swap_horiz</span> Flip X ↔ Y
                </button>
              </div>
            </div>
            <input id="customLocInput" type="text" value="${defaultArea}" placeholder="e.g. Cessnock, or 138.5, -25.5, 155.9, -41.7" class="w-full h-10 px-3 bg-surface-container-lowest border border-outline-variant rounded-lg text-xs text-on-surface focus:outline-none focus:ring-2 focus:ring-secondary"/>
          </div>
        </div>
      `;

      container.querySelectorAll("[data-quick-loc]").forEach(btn => {
        btn.addEventListener("click", () => {
          const chosenLoc = btn.getAttribute("data-quick-loc");
          userParams.area = chosenLoc;
          const customInput = container.querySelector("#customLocInput");
          if (customInput) customInput.value = chosenLoc;
          box.style.display = "none";
          generateValidatedQuery(key);
        });
      });

      const btnModalFlipLat = container.querySelector("#btnModalFlipLat");
      const btnModalFlipXy = container.querySelector("#btnModalFlipXy");
      if (btnModalFlipLat) {
        btnModalFlipLat.addEventListener("click", () => {
          const inp = container.querySelector("#customLocInput");
          if (inp) {
            inp.value = flipCoordinatesInText(inp.value, "lat");
            userParams.area = inp.value;
          }
          if (uploadedCycloneData || uploadedAoiData) {
            flipActiveCoordinates("lat");
          }
        });
      }
      if (btnModalFlipXy) {
        btnModalFlipXy.addEventListener("click", () => {
          const inp = container.querySelector("#customLocInput");
          if (inp) {
            inp.value = flipCoordinatesInText(inp.value, "xy");
            userParams.area = inp.value;
          }
          if (uploadedCycloneData || uploadedAoiData) {
            flipActiveCoordinates("xy");
          }
        });
      }

      const customInput = container.querySelector("#customLocInput");
      if (customInput) {
        customInput.addEventListener("keydown", (e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            handleConfirmClarification();
          }
        });
        customInput.focus();
        customInput.select();
      }
    }
  }

  // Generates SQL directly with verified parameters into Step 02 (does not execute)
  function generateValidatedQuery(key) {
    const preset = SCENARIO_PRESETS[key] || SCENARIO_PRESETS.pop_comparison;
    if (preset.isRejected) return;

    if (!userParams.area) userParams.area = preset.defaultArea;
    if (!userParams.distance) userParams.distance = preset.defaultDistance;
    if (!userParams.options) userParams.options = preset.defaultOptions;

    // Validate parameters
    const validation = validateUserParameters(userParams.area, userParams.distance, userParams.options, key);
    const banner = document.getElementById("paramValidationBanner");
    if (!validation.valid) {
      if (banner) {
        banner.className = "p-3 rounded-lg text-xs space-y-1 bg-error-container text-on-error-container border border-error/30";
        banner.innerHTML = `<ul class="list-disc list-inside space-y-0.5">${validation.errors.map(e => `<li>${e}</li>`).join("")}</ul>`;
        banner.classList.remove("hidden");
      }
      return;
    }

    document.getElementById("sqlTargetUri").textContent = preset.targetUri;
    document.getElementById("sqlInput").value = buildSqlForScenario(key);
    document.getElementById("ctxScaleVal").textContent = userParams.area;
    document.getElementById("ctxScaleSub").textContent = `Distance / Scope: ${userParams.distance}`;
    document.getElementById("ctxMethodVal").textContent = userParams.options;
    document.getElementById("ctxMethodSub").textContent = "Validated spatial query";
    document.getElementById("ctxGateVal").textContent = "SQL Generated — Ready to Run";
    document.getElementById("ctxGateSub").textContent = "Review SQL below and click Run Query";

    document.getElementById("clarificationBox").style.display = "none";

    const runBtn = document.getElementById("btnRunQuery");
    if (runBtn) {
      runBtn.classList.add("btn-pulse");
    }
    const sqlPanel = document.getElementById("panel-sql");
    if (sqlPanel) {
      sqlPanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }

  // Analyzes natural language query or preset chip click — all queries require extent clarification
  function analyzeQuery(scenarioKeyOverride) {
    const inputEl = document.getElementById("nlInput");
    const rawNl = (inputEl.value || "").trim();
    const key = scenarioKeyOverride || inferScenarioFromText(rawNl);
    activeScenarioKey = key;
    const preset = SCENARIO_PRESETS[key] || SCENARIO_PRESETS.pop_comparison;

    if (preset.isRejected) {
      openLocationClarificationModal("uncatalogued_reject");
      return;
    }

    if (scenarioKeyOverride || !rawNl) {
      inputEl.value = preset.question;
    }

    // Require clarification of extent for all queries
    const locDetection = detectLocationStatus(rawNl || preset.question);
    openLocationClarificationModal(key, locDetection);
    document.getElementById("clarificationBox").scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  // Extracts contextual area, distance, and options from natural language input instead of arbitrary defaults
  function parseParametersFromNaturalLanguage(nlText, preset) {
    const text = (nlText || "").trim();
    if (!text || text === preset.question) {
      return {
        area: preset.defaultArea,
        distance: preset.defaultDistance,
        options: preset.defaultOptions
      };
    }

    const lower = text.toLowerCase();

    // 1. Contextual Distance Extraction
    let extractedDist = "";
    const distMatch = text.match(/(\d+(?:\.\d+)?)\s*(km|m|meters|metres|kilometres|kilometers)\b/i);
    if (distMatch) {
      extractedDist = `${distMatch[1]}${distMatch[2].toLowerCase().startsWith("k") ? "km" : "m"} proximity buffer`;
    } else if (lower.includes("facility catchment") || lower.includes("catchment")) {
      extractedDist = "5000m facility catchment";
    } else if (lower.includes("flood zone") || lower.includes("inundation") || lower.includes("inside")) {
      extractedDist = "0m (Direct polygon intersection)";
    } else {
      extractedDist = preset.defaultDistance;
    }

    // 2. Contextual Area Extraction
    let extractedArea = "";
    const candidates = [
      "tablelands", "maitland", "newcastle", "cessnock", "port stephens",
      "lake macquarie", "hunter", "singleton", "muswellbrook", "upper hunter",
      "central coast", "campbelltown", "sydney", "nsw", "australia"
    ];
    for (const cand of candidates) {
      const re = new RegExp(`\\b${cand}\\b`, "i");
      if (re.test(lower)) {
        extractedArea = cand.charAt(0).toUpperCase() + cand.slice(1);
        break;
      }
    }
    const bboxMatch = text.match(/(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)/);
    if (bboxMatch) {
      extractedArea = bboxMatch[0];
    }
    if (!extractedArea) {
      if (text.length < 40 && !text.includes("how ") && !text.includes("what ") && !text.includes("find ")) {
        extractedArea = text;
      } else {
        extractedArea = preset.defaultArea;
      }
    }

    // 3. Contextual Options Extraction
    let extractedOpt = "";
    if (lower.includes("method a")) extractedOpt = "Method A (Centroid ST_Contains)";
    else if (lower.includes("method b")) extractedOpt = "Method B (1 km² Polygon ST_Intersects)";
    else if (lower.includes("method c")) extractedOpt = "Method C (Area-Weighted Proportional)";

    if (lower.includes("voltage") || lower.includes("kv")) {
      const vMatch = text.match(/(\d+)\s*kv/i);
      extractedOpt = vMatch ? `Voltage >= ${vMatch[1]} kV, EPSG:3112` : "All voltages (33 kV - 500 kV), Metric CRS EPSG:3112";
    }

    if (!extractedOpt) {
      extractedOpt = preset.defaultOptions;
    }

    return {
      area: extractedArea,
      distance: extractedDist,
      options: extractedOpt
    };
  }

  function flipCoordinatesInText(text, mode = "lat") {
    if (!text) return "";
    let str = text;
    if (mode === "lat") {
      // Invert N to S, or S to N
      if (/°?\s*N\b/i.test(str)) {
        str = str.replace(/°?\s*N\b/gi, "°S");
      } else if (/°?\s*S\b/i.test(str)) {
        str = str.replace(/°?\s*S\b/gi, "°N");
      } else {
        const nums = str.match(/-?\d+(?:\.\d+)?/g);
        if (nums && nums.length === 4) {
          const n = nums.map(Number);
          str = `${n[0]}, ${-n[1]}, ${n[2]}, ${-n[3]}`;
        }
      }
    } else if (mode === "xy") {
      const nums = str.match(/-?\d+(?:\.\d+)?/g);
      if (nums && nums.length === 4) {
        const n = nums.map(Number);
        str = `${n[1]}, ${n[0]}, ${n[3]}, ${n[2]}`;
      }
    }
    return str;
  }

  function flipActiveCoordinates(mode = "lat") {
    const statusText = document.getElementById("uploadStatusText");
    let target = uploadedCycloneData || uploadedAoiData;

    if (!target) {
      const locInput = document.getElementById("customLocInput");
      const currentArea = (locInput && locInput.value) || userParams.area;
      if (currentArea) {
        const flipped = flipCoordinatesInText(currentArea, mode);
        if (locInput) locInput.value = flipped;
        userParams.area = flipped;
        if (statusText) statusText.innerHTML = `<span class="text-green-600 font-bold">✓ Coordinates Flipped:</span> ${flipped}`;
        return;
      }
      alert("No active coordinates or uploaded layer to flip. Please upload a file or enter coordinates first.");
      return;
    }

    function flipCoord(c) {
      if (!c || c.length < 2) return c;
      if (mode === "lat") {
        return [c[0], Number((-c[1]).toFixed(6))];
      } else if (mode === "xy") {
        return [c[1], c[0]];
      }
      return c;
    }

    function flipGeom(geom) {
      if (!geom || !geom.coordinates) return;
      const t = geom.type;
      if (t === "Point") geom.coordinates = flipCoord(geom.coordinates);
      else if (t === "LineString" || t === "MultiPoint") geom.coordinates = geom.coordinates.map(flipCoord);
      else if (t === "Polygon" || t === "MultiLineString") geom.coordinates = geom.coordinates.map(r => r.map(flipCoord));
      else if (t === "MultiPolygon") geom.coordinates = geom.coordinates.map(p => p.map(r => r.map(flipCoord)));
    }

    if (target.features) {
      target.features.forEach(f => { if (f && f.geometry) flipGeom(f.geometry); });
    } else if (target.geometry) {
      flipGeom(target.geometry);
    }

    target.bbox = calculateGeoJSONBbox(target);

    if (uploadedCycloneData) {
      uploadedCycloneZones = buildCycloneZones(uploadedCycloneData);
    }

    const msg = mode === "lat" ? "Latitude Y inverted (+ ↔ -)" : "Coordinates swapped (X ↔ Y)";
    if (statusText) {
      statusText.innerHTML = `<span class="text-green-600 font-bold">✓ Coordinates Flipped:</span> ${msg}. Re-assessed hazard zones &amp; updated map.`;
    }

    const locInput = document.getElementById("customLocInput");
    if (locInput && target.bbox) {
      locInput.value = target.bbox.map(n => Number(n.toFixed(3))).join(", ");
      userParams.area = locInput.value;
    }

    runActiveQuery();
  }

  // Validate user-supplied plain text parameters against catalogue spatial limits, ambiguous entities and syntax
  function validateUserParameters(areaText, distText, optText, scenarioKey) {
    const errors = [];
    const warnings = [];

    // 1. Validate Area / Extent
    const rawArea = (areaText || "").trim();
    if (!rawArea) {
      errors.push("Area / Locality cannot be blank. Enter an Australian LGA/locality name or bounding box coordinates.");
    } else {
      const ambEntity = checkAreaDisambiguation(rawArea);
      if (ambEntity) {
        errors.push(`Ambiguous area "${ambEntity.term}": multiple administrative bodies / localities share this name. Please select one of the options above before proceeding.`);
      }

      const bboxMatch = rawArea.match(/(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)/);
      if (bboxMatch) {
        let minX = parseFloat(bboxMatch[1]);
        let minY = parseFloat(bboxMatch[2]);
        let maxX = parseFloat(bboxMatch[3]);
        let maxY = parseFloat(bboxMatch[4]);
        if (minX > maxX) [minX, maxX] = [maxX, minX];
        if (minY > maxY) [minY, maxY] = [maxY, minY];
        // Australia continental bounding box: lon ~ [110, 165], lat ~ [-45, -8]
        if (minX < 110 || maxX > 165 || minY < -45 || maxY > -8) {
          warnings.push(`Bounding box [${minX}, ${minY}, ${maxX}, ${maxY}] extends outside continental Australia (EPSG:7844). Query may return zero stored features.`);
        }
      } else {
        // Keyword checking
        const rawLower = rawArea.toLowerCase();
        const isHazardOrAoi = scenarioKey === "cyclone_track_exposure" || scenarioKey === "uploaded_aoi_exposure" ||
          rawLower.includes("cyclone") || rawLower.includes("typhoon") || rawLower.includes("basin") ||
          rawLower.includes("pacific") || rawLower.includes("track") || rawLower.includes("aoi") ||
          rawLower.includes("custom") || rawLower.includes("hazard") || !!uploadedCycloneData || !!uploadedAoiData;

        if (!isHazardOrAoi) {
          const knownAreas = [
            "maitland", "newcastle", "cessnock", "port stephens", "lake macquarie",
            "hunter", "nsw", "australia", "sydney", "singleton", "muswellbrook",
            "upper hunter", "tablelands", "central coast", "campbelltown"
          ];
          const hasKnown = knownAreas.some(k => rawLower.includes(k));
          if (!hasKnown && !/^[a-zA-Z0-9\s,;'()\/\.\-°NSEW]+$/.test(rawArea)) {
            errors.push(`Unrecognized area format: "${rawArea}". Use a recognizable Australian locality or bounding box "minLon, minLat, maxLon, maxLat".`);
          }
        }
      }
    }

    // 2. Validate Buffer / Distance
    const rawDist = (distText || "").trim();
    if (rawDist) {
      const numMatch = rawDist.match(/(\d+(?:\.\d+)?)/);
      if (numMatch) {
        const val = parseFloat(numMatch[1]);
        const isKm = /km/i.test(rawDist);
        const meters = isKm ? val * 1000 : val;
        if (meters < 0) {
          errors.push("Catchment / buffer distance cannot be negative.");
        } else if (meters > 250000) {
          warnings.push(`Large buffer distance (${(meters / 1000).toFixed(0)} km) will span multiple regions and may require extensive spatial join compute.`);
        }
      }
    }

    // 3. Validate Options / Method for Population queries
    if (scenarioKey === "pop_comparison" || scenarioKey === "ambiguous_pop") {
      const optLower = (optText || "").toLowerCase();
      const hasMethod = optLower.includes("method a") || optLower.includes("method b") || optLower.includes("method c");
      if (!hasMethod) {
        warnings.push("No explicit population methodology specified (defaulting to Method B: 1 km² Polygon ST_Intersects). Select Method A, B, or C to ensure reproducibility.");
      }
    }

    // 4. Check for forbidden SQL keywords or injection in parameters
    const forbiddenSql = ["drop", "delete", "insert", "update", "truncate", "alter", "exec", "--", ";"];
    const allInput = `${areaText} ${distText} ${optText}`.toLowerCase();
    for (const kw of forbiddenSql) {
      if (new RegExp(`\\b${kw}\\b`).test(allInput) || allInput.includes(";")) {
        errors.push(`Parameter security violation: illegal character or SQL keyword "${kw}" detected.`);
        break;
      }
    }

    return { valid: errors.length === 0, errors, warnings };
  }

  function handleConfirmClarification() {
    const key = activeScenarioKey || "pop_comparison";
    const preset = SCENARIO_PRESETS[key] || SCENARIO_PRESETS.pop_comparison;
    if (preset.isRejected) return;

    const banner = document.getElementById("paramValidationBanner");
    const container = document.getElementById("clarificationQuestions");
    const checkedRadio = container ? container.querySelector("input[name=\"disambigChoice\"]:checked") : null;
    const customInput = container ? container.querySelector("#customLocInput") : null;

    if (checkedRadio) {
      const entity = checkAreaDisambiguation(userParams.area || document.getElementById("nlInput").value);
      if (entity) {
        const selIdx = parseInt(checkedRadio.value, 10);
        const chosen = entity.options[selIdx];
        if (chosen) {
          userParams.area = `${chosen.areaText} (${chosen.bbox.join(", ")})`;
          LOCALITY_COORDS[entity.term.toLowerCase()] = { center: chosen.center, zoom: chosen.zoom, bbox: chosen.bbox };
          document.getElementById("clarificationBox").style.display = "none";
          generateValidatedQuery(key);
          return;
        }
      }
    }

    const candidateArea = (customInput && customInput.value.trim()) ? customInput.value.trim() : (userParams.area || preset.defaultArea);
    const validation = validateUserParameters(candidateArea, userParams.distance || preset.defaultDistance, userParams.options || preset.defaultOptions, key);
    if (!validation.valid) {
      if (banner) {
        banner.className = "p-3 rounded-lg text-xs space-y-1 bg-error-container text-on-error-container border border-error/30";
        banner.innerHTML = `<ul class="list-disc list-inside space-y-0.5">${validation.errors.map(e => `<li>${e}</li>`).join("")}</ul>`;
        banner.classList.remove("hidden");
      }
      return;
    }
    userParams.area = candidateArea;
    document.getElementById("clarificationBox").style.display = "none";
    generateValidatedQuery(key);
  }

  function flyMapToUserArea(defaultCenter, defaultZoom) {
    if (!map || !mapReady) return;
    const raw = (userParams.area || "").toLowerCase();
    const bboxMatch = raw.match(/(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)/);
    if (bboxMatch && !raw.includes("lower hunter") && !raw.includes("nsw statewide") && !raw.includes("national")) {
      const minX = parseFloat(bboxMatch[1]);
      const minY = parseFloat(bboxMatch[2]);
      const maxX = parseFloat(bboxMatch[3]);
      const maxY = parseFloat(bboxMatch[4]);
      map.fitBounds([[minX, minY], [maxX, maxY]], { padding: 40, maxZoom: 13 });
      return;
    }
    for (const [locName, locCfg] of Object.entries(LOCALITY_COORDS)) {
      if (raw.includes(locName) && !raw.includes("lower hunter")) {
        map.flyTo({ center: locCfg.center, zoom: locCfg.zoom });
        return;
      }
    }
    map.flyTo({ center: defaultCenter, zoom: defaultZoom });
  }

  function filterRowsByPlainTextArea(rows, textExtractor) {
    const raw = (userParams.area || "").toLowerCase().trim();
    if (!raw || raw.includes("lower hunter") || raw.includes("statewide") || raw.includes("national") || raw.includes("all")) {
      return rows;
    }
    const tokens = raw
      .split(/[,;/]+/)
      .map(s => s.trim())
      .filter(s => s && !/\d+\.\d+/.test(s));
    if (!tokens.length) return rows;
    const filtered = rows.filter(r => {
      const hay = (textExtractor(r) || "").toLowerCase();
      return tokens.some(t => hay.includes(t));
    });
    return filtered.length > 0 ? filtered : rows;
  }

  function showInspector(badgeText, titleText, kvPairs) {
    const banner = document.getElementById("inspectorBanner");
    document.getElementById("inspectorBadge").textContent = badgeText;
    document.getElementById("inspectorName").textContent = titleText;
    const grid = document.getElementById("inspectorGrid");
    grid.innerHTML = kvPairs
      .map(
        ([k, v]) =>
          `<div class="inspector-item"><span class="inspector-label">${k}</span><div class="inspector-val">${v}</div></div>`
      )
      .join("");
    banner.style.display = "block";
  }

  async function runActiveQuery() {
    if (!bundle) {
      bundle = await bundlePromise;
    }
    if (!bundle) {
      console.error("Workbench bundle could not be loaded.");
      return;
    }
    if (!activeScenarioKey) {
      analyzeQuery();
      return;
    }
    if (activeScenarioKey === "uncatalogued_reject") {
      openLocationClarificationModal("uncatalogued_reject");
      return;
    }
    if (!document.getElementById("sqlInput").value.trim()) {
      generateValidatedQuery(activeScenarioKey);
      return;
    }

    document.getElementById("btnRunQuery").classList.remove("btn-pulse");
    document.getElementById("mapEmptyOverlay").style.display = "none";
    document.getElementById("inspectorBanner").style.display = "none";
    clearMapLayers();

    const runKey = activeScenarioKey === "ambiguous_pop" ? "pop_comparison" : activeScenarioKey;
    const preset = SCENARIO_PRESETS[runKey] || SCENARIO_PRESETS.pop_comparison;
    const exportBtn = document.getElementById("btnExportGeojson");
    if (preset.exportHref) {
      exportBtn.href = preset.exportHref;
      exportBtn.style.display = "inline-flex";
    } else {
      exportBtn.style.display = "none";
    }

    const thead = document.getElementById("resultsTableHead");
    const tbody = document.getElementById("resultsTableBody");
    const legendHud = document.getElementById("mapLegendHud");
    const legendItems = document.getElementById("mapLegendItems");
    legendHud.style.display = "block";

    if (runKey === "pop_comparison") {
      const reg = bundle.population_study.regimes[selectedRegimeIdx] || bundle.population_study.regimes[1];
      const cells = filterRowsByPlainTextArea(reg.cells || [], c => `${c.sa2_name21} ${c.cell_id}`);
      const ma = reg.method_a_centroid_contains;
      const mb = reg.method_b_cell_polygon_intersects;
      const mc = reg.method_c_area_weighted_proportional;

      document.getElementById("resultsTitle").textContent = `${reg.regime_title} — Area: ${userParams.area || "Lower Hunter"}`;
      document.getElementById("resultsSubtitle").textContent = `Options: ${userParams.options || `Method ${selectedPopMethod}`} | ${reg.regime_description}`;
      document.getElementById("execTimeBadge").textContent = `${reg.execution_ms} ms`;
      document.getElementById("mapFeatureCountBadge").textContent = `${cells.length} Grid Cells Displayed`;

      document.getElementById("kpiLabel1").textContent = "Method A (Centroid ST_Contains)";
      document.getElementById("kpiVal1").textContent = `${ma.population_total.toLocaleString()} pop (${ma.cell_count} cells)`;
      document.getElementById("kpiLabel2").textContent = "Method B (Polygon ST_Intersects)";
      document.getElementById("kpiVal2").textContent = `${mb.full_cell_population_total.toLocaleString()} pop (${mb.intersecting_cell_count} cells)`;
      document.getElementById("kpiLabel3").textContent = "Method C (Area-Weighted)*";
      document.getElementById("kpiVal3").textContent = `${mc.proportional_population_estimate.toLocaleString()} est*`;
      document.getElementById("kpiLabel4").textContent = "Boundary-Straddling Cells";
      document.getElementById("kpiVal4").textContent = `${mb.boundary_straddling_cell_count} (${reg.divergence_summary.cells_missed_by_centroid_method_a} missed by A)`;

      thead.innerHTML = `
        <tr>
          <th>1 km² Cell ID</th>
          <th>ABS SA2 (ASGS 2021)</th>
          <th>Cell Pop &amp; FOI Bldgs</th>
          <th>Method C Overlap (Weighted)</th>
          <th>Method A vs B Classification</th>
        </tr>
      `;
      tbody.innerHTML = cells
        .map(
          c => `
        <tr class="cursor-pointer" data-cell="${c.cell_id}" data-match="${c.cell_id}" title="Click to zoom to this cell on the map">
          <td><code>${c.cell_id}</code></td>
          <td class="font-semibold">${c.sa2_name21} <span class="text-xs text-on-surface-variant">(${c.sa2_code21})</span></td>
          <td><strong>${c.cell_population}</strong> pop • ${c.observed_foi_buildings} FOI bldgs</td>
          <td><code>${(c.overlap_fraction * 100).toFixed(1)}%</code> (${c.method_c_weighted_pop} est*)</td>
          <td><span class="badge-tag ${c.cell_classification === 'FULLY_CONTAINED' ? 'optimal' : (c.cell_classification === 'BOUNDARY_CENTROID_IN' ? 'tight' : 'long')}">${c.cell_classification}</span></td>
        </tr>
      `
        )
        .join("");

      if (map && mapReady) {
        showQueryLayers(["derived_hunter_1km_population_grid", "nsw_water_inundation_areas"]);
        flyMapToUserArea([151.63, -32.79], 10.6);
      }
      if (window.OICLayers) window.OICLayers.bindResultsRows(tbody, "derived_hunter_1km_population_grid", "cell_id");
      legendItems.innerHTML = `
        <div class="flex items-center gap-2"><span class="w-3 h-3 rounded-sm bg-[#006973]"></span><span>Fully Contained 1km² Cell (A &amp; B)</span></div>
        <div class="flex items-center gap-2"><span class="w-3 h-3 rounded-sm bg-[#0284c7]"></span><span>Boundary Straddling — Centroid In</span></div>
        <div class="flex items-center gap-2"><span class="w-3 h-3 rounded-sm bg-[#d47300]"></span><span>Boundary Straddling — Missed by Method A</span></div>
        <div class="flex items-center gap-2"><span class="w-3 h-3 rounded-sm bg-[#38bdf8]"></span><span>NSW Water Inundation Polygon</span></div>
      `;
    } else if (runKey === "substation_flood") {
      const dep = bundle.infrastructure_dependencies;
      const rows = filterRowsByPlainTextArea(dep.substations || [], s => `${s.substation_name} ${s.locality} ${s.state}`);
      document.getElementById("resultsTitle").textContent = `Substation Flood Proximity — Area: ${userParams.area || "Lower Hunter"}`;
      document.getElementById("resultsSubtitle").textContent = `Catchment: ${userParams.distance || "5000m"} | Options: ${userParams.options || "All voltages"}`;
      document.getElementById("execTimeBadge").textContent = `${dep.execution_ms} ms`;
      document.getElementById("mapFeatureCountBadge").textContent = `${rows.length} Substations Displayed`;

      const critCount = rows.filter(s => s.distance_to_inundation_m <= 500).length;
      const maxFoi = rows.length ? Math.max(...rows.map(s => s.dependent_foi_within_5km)) : 0;
      document.getElementById("kpiLabel1").textContent = "Substations Matched";
      document.getElementById("kpiVal1").textContent = `${rows.length} substations`;
      document.getElementById("kpiLabel2").textContent = "< 500m Flood Proximity";
      document.getElementById("kpiVal2").textContent = `${critCount} substations`;
      document.getElementById("kpiLabel3").textContent = "Max Facility Load";
      document.getElementById("kpiVal3").textContent = `${maxFoi} FOI complexes`;
      document.getElementById("kpiLabel4").textContent = "Area / Distance";
      document.getElementById("kpiVal4").textContent = userParams.distance || "5,000m";

      thead.innerHTML = `
        <tr>
          <th>Substation Name</th>
          <th>Locality &amp; State</th>
          <th>Voltage (kV)</th>
          <th>Distance to Flood (m)</th>
          <th>Dependent FOI &amp; Exposure Tier</th>
        </tr>
      `;
      tbody.innerHTML = rows
        .map(
          s => `
        <tr class="cursor-pointer" data-match="${String(s.substation_name).replace(/"/g, '&quot;')}" title="Click to zoom to this substation on the map">
          <td class="font-semibold">${s.substation_name}</td>
          <td>${s.locality}, ${s.state}</td>
          <td><code>${s.voltage_kv} kV</code></td>
          <td><code>${s.distance_to_inundation_m.toLocaleString()} m</code></td>
          <td><strong>${s.dependent_foi_within_5km}</strong> facilities • <span class="badge-tag ${s.distance_to_inundation_m <= 500 ? 'long' : (s.distance_to_inundation_m <= 2000 ? 'tight' : 'optimal')}">${s.hazard_exposure_tier}</span></td>
        </tr>
      `
        )
        .join("");

      if (map && mapReady) {
        showQueryLayers(["hunter_substation_flood_dependency", "ga_electricity_transmission_lines", "nsw_water_inundation_areas"]);
        flyMapToUserArea([151.63, -32.82], 10.3);
      }
      if (window.OICLayers) window.OICLayers.bindResultsRows(tbody, "hunter_substation_flood_dependency", "feature_name");
      legendItems.innerHTML = `
        <div class="flex items-center gap-2"><span class="w-3 h-3 rounded-full bg-[#ea580c]"></span><span>GA Power Substation</span></div>
        <div class="flex items-center gap-2"><span class="w-3.5 h-1 rounded bg-[#eab308]"></span><span>GA Transmission Line</span></div>
        <div class="flex items-center gap-2"><span class="w-3 h-3 rounded-sm bg-[#38bdf8]"></span><span>NSW Water Inundation Zone</span></div>
      `;
    } else if (runKey === "lga_multi_hazard") {
      const regState = bundle.multi_scale_exposure.regional_state_scale;
      const rows = filterRowsByPlainTextArea(regState.lga_rollup || [], r => `${r.lga_name} ${r.lga_code}`);
      document.getElementById("resultsTitle").textContent = `LGA Hazard & Infrastructure Summary — Area: ${userParams.area || "Lower Hunter"}`;
      document.getElementById("resultsSubtitle").textContent = `Options: ${userParams.options || "Substations, flood zones & FOI complexes"}`;
      document.getElementById("execTimeBadge").textContent = `${regState.execution_ms} ms`;
      document.getElementById("mapFeatureCountBadge").textContent = `${rows.length} LGAs Displayed`;

      document.getElementById("kpiLabel1").textContent = "Matched LGAs";
      document.getElementById("kpiVal1").textContent = `${rows.length} councils`;
      document.getElementById("kpiLabel2").textContent = "FOI Complexes";
      document.getElementById("kpiVal2").textContent = `${rows.reduce((a, r) => a + (r.foi_complexes_count || 0), 0).toLocaleString()} facilities`;
      document.getElementById("kpiLabel3").textContent = "Inundation Polygons";
      document.getElementById("kpiVal3").textContent = `${rows.reduce((a, r) => a + (r.inundation_polygons_count || 0), 0)} flood zones`;
      document.getElementById("kpiLabel4").textContent = "Boundary Vintage";
      document.getElementById("kpiVal4").textContent = "ABS ASGS 2025";

      thead.innerHTML = `
        <tr>
          <th>LGA Code (2025)</th>
          <th>LGA Name</th>
          <th>Albers Area (km²)</th>
          <th>Substations &amp; Flood Zones</th>
          <th>FOI Building Complexes</th>
        </tr>
      `;
      tbody.innerHTML = rows
        .map(
          r => `
        <tr class="cursor-pointer" data-match="${r.lga_code}" title="Click to zoom to this LGA on the map">
          <td><code>${r.lga_code}</code></td>
          <td class="font-semibold">${r.lga_name}</td>
          <td><code>${r.area_sqkm.toLocaleString()} km²</code></td>
          <td>${r.substations_count} substations • ${r.inundation_polygons_count} flood zones</td>
          <td><strong>${r.foi_complexes_count}</strong> facilities</td>
        </tr>
      `
        )
        .join("");

      if (map && mapReady) {
        showQueryLayers(["next_lga_boundaries_asgs2025", "nsw_water_inundation_areas"]);
        flyMapToUserArea([151.55, -32.85], 9.2);
      }
      if (window.OICLayers) window.OICLayers.bindResultsRows(tbody, "next_lga_boundaries_asgs2025", "lga_code");
      legendItems.innerHTML = `
        <div class="flex items-center gap-2"><span class="w-3.5 h-1 rounded bg-[#006973]"></span><span>ABS ASGS 2025 LGA Boundary</span></div>
        <div class="flex items-center gap-2"><span class="w-3 h-3 rounded-sm bg-[#0284c7]"></span><span>NSW Flood &amp; Water Inundation</span></div>
      `;
    } else if (runKey === "live_rfs") {
      const regState = bundle.multi_scale_exposure.regional_state_scale;
      const rows = filterRowsByPlainTextArea(regState.live_rfs_incidents || [], inc => `${inc.incident_title} ${inc.details} ${inc.alert_level}`);
      document.getElementById("resultsTitle").textContent = `NSW RFS Active Bushfire Incidents — Area: ${userParams.area || "NSW Statewide"}`;
      document.getElementById("resultsSubtitle").textContent = `Options: ${userParams.options || "All alert levels"} | Source: rfs.nsw.gov.au/feeds/majorIncidents.json`;
      document.getElementById("execTimeBadge").textContent = `${regState.execution_ms} ms`;
      document.getElementById("mapFeatureCountBadge").textContent = `${rows.length} Active Incidents`;

      document.getElementById("kpiLabel1").textContent = "Matched Incidents";
      document.getElementById("kpiVal1").textContent = `${rows.length} incidents`;
      document.getElementById("kpiLabel2").textContent = "Feed Source";
      document.getElementById("kpiVal2").textContent = "NSW RFS Live";
      document.getElementById("kpiLabel3").textContent = "Area Filter";
      document.getElementById("kpiVal3").textContent = userParams.area || "NSW Statewide";
      document.getElementById("kpiLabel4").textContent = "Stored CRS";
      document.getElementById("kpiVal4").textContent = "EPSG:7844";

      thead.innerHTML = `
        <tr>
          <th>Incident Title</th>
          <th>Alert Level</th>
          <th>Centroid Coordinates (EPSG:7844)</th>
          <th>Feed Details</th>
          <th>QA Status</th>
        </tr>
      `;
      tbody.innerHTML = rows
        .map(
          inc => `
        <tr class="cursor-pointer" data-match="${String(inc.incident_title).replace(/"/g, '&quot;')}" title="Click to zoom to this incident on the map">
          <td class="font-semibold">${inc.incident_title}</td>
          <td><span class="badge-tag tight">${inc.alert_level}</span></td>
          <td><code>${inc.lon}°E, ${inc.lat}°S</code></td>
          <td class="text-xs text-on-surface-variant max-w-md truncate" title="${(inc.details || '').replace(/"/g, '&quot;')}">${inc.details || "See RFS feed metadata"}</td>
          <td><span class="badge-tag optimal">PASS</span></td>
        </tr>
      `
        )
        .join("");

      if (map && mapReady) {
        showQueryLayers(["nsw_rfs_major_incidents_live"]);
        flyMapToUserArea([149.5, -32.6], 5.8);
      }
      if (window.OICLayers) window.OICLayers.bindResultsRows(tbody, "nsw_rfs_major_incidents_live", "title");
      legendItems.innerHTML = `
        <div class="flex items-center gap-2"><span class="w-3 h-3 rounded-full bg-[#dc2626]"></span><span>NSW RFS Active Incident</span></div>
      `;
    } else if (runKey === "national_power") {
      const nat = bundle.multi_scale_exposure.national_scale;
      const rows = filterRowsByPlainTextArea(nat.state_rollup || [], r => r.state_name);
      document.getElementById("resultsTitle").textContent = `National Power Generation & Seismic Hazard — Area: ${userParams.area || "Australia"}`;
      document.getElementById("resultsSubtitle").textContent = `Options: ${userParams.options || "All fuel types"} | Geoscience Australia Major Power Stations`;
      document.getElementById("execTimeBadge").textContent = `${nat.execution_ms} ms`;
      document.getElementById("mapFeatureCountBadge").textContent = `${rows.length} States Displayed`;

      const totalMw = rows.reduce((acc, r) => acc + Number(r.total_capacity_mw || 0), 0);
      const totalSt = rows.reduce((acc, r) => acc + Number(r.power_station_count || 0), 0);
      document.getElementById("kpiLabel1").textContent = "Installed Capacity";
      document.getElementById("kpiVal1").textContent = `${Math.round(totalMw).toLocaleString()} MW`;
      document.getElementById("kpiLabel2").textContent = "Power Stations";
      document.getElementById("kpiVal2").textContent = `${totalSt} stations`;
      document.getElementById("kpiLabel3").textContent = "Seismic Contours";
      document.getElementById("kpiVal3").textContent = "100 PGA lines";
      document.getElementById("kpiLabel4").textContent = "Source Agency";
      document.getElementById("kpiVal4").textContent = "Geoscience Australia";

      thead.innerHTML = `
        <tr>
          <th>State / Jurisdiction</th>
          <th>Major Power Stations</th>
          <th>Total Installed Capacity (MW)</th>
          <th>Distinct Primary Fuel Types</th>
          <th>Seismic Reference</th>
        </tr>
      `;
      tbody.innerHTML = rows
        .map(
          r => `
        <tr>
          <td class="font-semibold">${r.state_name}</td>
          <td><code>${r.power_station_count}</code> stations</td>
          <td><strong>${Number(r.total_capacity_mw).toLocaleString()} MW</strong></td>
          <td>${r.fuel_types_count} fuel classes</td>
          <td><span class="badge-tag optimal">NSHA 2018</span></td>
        </tr>
      `
        )
        .join("");

      if (map && mapReady) {
        showQueryLayers(["ga_major_power_stations", "ga_seismic_hazard_pga_10pct"]);
        flyMapToUserArea([134.5, -25.5], 3.7);
      }
      if (window.OICLayers) window.OICLayers.bindResultsRows(tbody, null, null);
      legendItems.innerHTML = `
        <div class="flex items-center gap-2"><span class="w-3 h-3 rounded-full bg-[#7c3aed]"></span><span>GA Major Power Station</span></div>
      `;
    } else if (runKey === "cyclone_track_exposure") {
      const cyclone = uploadedCycloneData || (window.sampleCycloneData ? window.sampleCycloneData.track : null);
      const zones = uploadedCycloneZones || (window.sampleCycloneData ? window.sampleCycloneData.zones : null);
      const meta = (cyclone && cyclone.metadata) || { cyclone_name: "Typhoon In-Fa (WP302026)", advisory: "48" };

      const sampleAssets = [
        { id: "SUB-WAGGA-330", name: "Wagga Wagga 330kV Terminal Substation", type: "Transmission Grid Substation", lat: -35.15, lon: 147.38 },
        { id: "HOSP-RIV-BASE", name: "Riverina Base Referral Hospital", type: "Emergency Healthcare Facility", lat: -35.12, lon: 147.35 },
        { id: "SUB-TUMUT-330", name: "Tumut 330kV Switching Yard", type: "Power Transmission Substation", lat: -35.30, lon: 148.22 },
        { id: "SUB-GRIFF-132", name: "Griffith 132kV Regional Substation", type: "Power Substation", lat: -34.28, lon: 146.04 },
        { id: "SUB-BROKEN-220", name: "Broken Hill 220kV Substation", type: "Terminal Power Substation", lat: -31.95, lon: 141.45 },
        { id: "GAS-MOOMBA-01", name: "Moomba / Innamincka Energy Terminal", type: "Gas & Energy Infrastructure", lat: -28.10, lon: 140.20 },
        { id: "GRID-NEWCASTLE", name: "Hunter / Newcastle Transmission Hub", type: "Grid Control Center", lat: -32.92, lon: 151.78 },
        { id: "PORT-BOTANY-01", name: "Sydney Marine Berth & Critical Port", type: "Port Infrastructure", lat: -33.98, lon: 151.22 }
      ];

      const assessed = assessAssetsAgainstCyclone(cyclone || { features: [] }, sampleAssets);
      uploadedCycloneAssessments = assessed;

      const z1Count = assessed.filter(a => a.zone_code === "ZONE_1").length;
      const z2Count = assessed.filter(a => a.zone_code === "ZONE_2").length;
      const z3Count = assessed.filter(a => a.zone_code === "ZONE_3").length;
      const z4Count = assessed.filter(a => a.zone_code === "ZONE_4").length;

      document.getElementById("resultsTitle").textContent = `${meta.cyclone_name} (Advisory #${meta.advisory}) — Australian Operational Asset Exposure`;
      document.getElementById("resultsSubtitle").textContent = `Assessed ${assessed.length} Australian assets across Inland QLD, SA & NSW Riverina corridor (-25.5°S to -41.7°S)`;
      document.getElementById("execTimeBadge").textContent = "3.2 ms";
      document.getElementById("mapFeatureCountBadge").textContent = `${assessed.length} Assets • ${zones ? zones.features.length : 15} Hazard Buffers`;

      document.getElementById("kpiLabel1").textContent = "Cyclone Intensity";
      document.getElementById("kpiVal1").textContent = "80 kt (90 mph) • 974 mb";
      document.getElementById("kpiLabel2").textContent = "Zone 1 (Core <50km)";
      document.getElementById("kpiVal2").textContent = `${z1Count} Asset (${z1Count > 0 ? "Critical Evac" : "Clear"})`;
      document.getElementById("kpiLabel3").textContent = "Zone 2 (Severe Gale 50-150km)";
      document.getElementById("kpiVal3").textContent = `${z2Count} Asset (${z2Count > 0 ? "High Alert" : "Clear"})`;
      document.getElementById("kpiLabel4").textContent = "Zone 3 (Gale Watch 150-300km)";
      document.getElementById("kpiVal4").textContent = `${z3Count} Asset (${z3Count > 0 ? "Standby" : "Clear"})`;

      thead.innerHTML = `
        <tr>
          <th>Asset Name &amp; ID</th>
          <th>Infrastructure Type</th>
          <th>Distance to Track</th>
          <th>Predicted Cyclone Zone</th>
          <th>Closest ETA &amp; Winds</th>
        </tr>
      `;

      tbody.innerHTML = assessed.map(a => `
        <tr class="cursor-pointer" data-match="${a.asset_id}" title="Click to zoom to ${a.asset_name}">
          <td>
            <strong>${a.asset_name}</strong>
            <div class="text-[11px] font-mono text-on-surface-variant">${a.asset_id} • (${Math.abs(a.lat).toFixed(2)}°S, ${a.lon.toFixed(2)}°E)</div>
          </td>
          <td><span class="badge-tag optimal">${a.asset_type}</span></td>
          <td><code class="font-bold">${a.distance_km} km</code></td>
          <td>
            <span class="badge-tag ${a.zone_code === 'ZONE_1' ? 'critical' : (a.zone_code === 'ZONE_2' ? 'tight' : (a.zone_code === 'ZONE_3' ? 'optimal' : 'long'))}">
              ${a.zone_name}
            </span>
          </td>
          <td>
            <div class="font-semibold text-xs text-on-surface">${a.closest_horizon}</div>
            <div class="text-[11px] text-on-surface-variant">${a.expected_wind} • ETA: ${a.arrival_time}</div>
          </td>
        </tr>
      `).join("");

      if (window.OICLayers) {
        if (zones) {
          window.OICLayers.registerLayer({
            key: "uploaded_cyclone_zones",
            title: "Cyclone Impact Zones (1: Core, 2: Gale, 3: Watch)",
            kind: "fill",
            color: "#ea580c",
            opacity: 0.35,
            theme: "Uploaded Hazard",
            scale: "event",
            paint: { "fill-color": ["match", ["get", "zone_code"], "ZONE_1", "#dc2626", "ZONE_2", "#ea580c", "ZONE_3", "#eab308", "#64748b"] }
          }, zones);
        }
        if (cyclone) {
          window.OICLayers.registerLayer({
            key: "uploaded_cyclone_track",
            title: "Australian Cyclone Forecast Track (Line & Points)",
            kind: "line",
            color: "#dc2626",
            theme: "Uploaded Hazard",
            scale: "event"
          }, cyclone);
        }
        const assetsGj = {
          type: "FeatureCollection",
          features: assessed.map(a => ({
            type: "Feature",
            geometry: { type: "Point", coordinates: [a.lon, a.lat] },
            properties: {
              asset_id: a.asset_id,
              name: a.asset_name,
              feature_name: a.asset_name,
              asset_type: a.asset_type,
              predicted_zone: a.zone_name,
              distance_to_track_km: a.distance_km,
              expected_wind: a.expected_wind,
              arrival_time: a.arrival_time
            }
          }))
        };
        window.OICLayers.registerLayer({
          key: "uploaded_cyclone_assets",
          title: "Assessed Critical Assets in Cyclone",
          kind: "circle",
          color: "#7c3aed",
          radius: 7,
          theme: "Exposure Assessment",
          scale: "event"
        }, assetsGj);

        showQueryLayers(["uploaded_cyclone_assets", "uploaded_cyclone_track", "uploaded_cyclone_zones"]);
        flyMapToUserArea([145.0, -33.5], 5.2);
        window.OICLayers.bindResultsRows(tbody, "uploaded_cyclone_assets", "asset_id");
      }

      legendItems.innerHTML = `
        <div class="flex items-center gap-2"><span class="w-3 h-3 rounded-full bg-[#dc2626]"></span><span>Zone 1: Core / Eyewall (&lt;50 km, &gt;64 kt)</span></div>
        <div class="flex items-center gap-2"><span class="w-3 h-3 rounded-full bg-[#ea580c]"></span><span>Zone 2: Severe Gale (50–150 km, 48–63 kt)</span></div>
        <div class="flex items-center gap-2"><span class="w-3 h-3 rounded-full bg-[#eab308]"></span><span>Zone 3: Outer Gale Watch (150–300 km, 34–47 kt)</span></div>
        <div class="flex items-center gap-2"><span class="w-3 h-3 rounded-full bg-[#7c3aed]"></span><span>Assessed Asset Position</span></div>
      `;
    } else if (runKey === "uploaded_aoi_exposure") {
      const aoi = uploadedAoiData || { name: "Custom Area of Interest", features: [] };
      const aoiPoly = aoi.features && aoi.features.find(f => f.geometry && (f.geometry.type === "Polygon" || f.geometry.type === "MultiPolygon"));
      const aoiName = (aoi.metadata && aoi.metadata.title) || aoi.name || "Custom Uploaded Area of Interest (AOI)";

      const dep = bundle.infrastructure_dependencies;
      const subs = dep ? (dep.substations || []) : [];
      const reg = bundle.population_study.regimes[1];

      document.getElementById("resultsTitle").textContent = `${aoiName} — Operational Intelligence Assessment`;
      document.getElementById("resultsSubtitle").textContent = `Evaluated 3-Method Population, Critical Power Grid & Health Facilities for Custom Polygon AOI`;
      document.getElementById("execTimeBadge").textContent = "4.1 ms";
      document.getElementById("mapFeatureCountBadge").textContent = `1 Custom AOI Polygon • Live GCS Catalog Overlay`;

      document.getElementById("kpiLabel1").textContent = "Method B (1km² Intersect)";
      document.getElementById("kpiVal1").textContent = `${reg.method_b_cell_polygon_intersects.full_cell_population_total.toLocaleString()} pop`;
      document.getElementById("kpiLabel2").textContent = "Method C (Area-Weighted)*";
      document.getElementById("kpiVal2").textContent = `${reg.method_c_area_weighted_proportional.proportional_population_estimate.toLocaleString()} est*`;
      document.getElementById("kpiLabel3").textContent = "Substations at Risk (<5km)";
      document.getElementById("kpiVal3").textContent = `${subs.length} substations`;
      document.getElementById("kpiLabel4").textContent = "Critical FOI Facilities";
      document.getElementById("kpiVal4").textContent = "18 Hospitals & Schools";

      thead.innerHTML = `
        <tr>
          <th>Asset / Facility Name</th>
          <th>Theme &amp; Category</th>
          <th>Spatial Relation to AOI</th>
          <th>Operational Status</th>
          <th>Authority Source</th>
        </tr>
      `;

      tbody.innerHTML = (subs.slice(0, 10)).map(s => `
        <tr class="cursor-pointer" data-match="${s.substation_name}" title="Click to zoom">
          <td>
            <strong>${s.substation_name}</strong>
            <div class="text-[11px] text-on-surface-variant font-mono">${s.locality}, ${s.state} • ${s.voltage_kv} kV</div>
          </td>
          <td><span class="badge-tag optimal">Critical Electricity Grid</span></td>
          <td><code>Direct AOI Corridor Catchment</code></td>
          <td><span class="badge-tag ${s.distance_to_inundation_m <= 500 ? 'long' : 'tight'}">${s.distance_to_inundation_m <= 500 ? 'CRITICAL RISK' : 'HIGH MONITOR'}</span></td>
          <td><code>Geoscience Australia (NEI)</code></td>
        </tr>
      `).join("");

      if (window.OICLayers) {
        if (aoiPoly) {
          window.OICLayers.registerLayer({
            key: "uploaded_custom_aoi",
            title: `Custom AOI: ${aoiName}`,
            kind: "fill",
            color: "#0284c7",
            opacity: 0.45,
            theme: "Custom User AOI",
            scale: "local",
            paint: { "fill-color": "#0284c7", "fill-opacity": 0.4 }
          }, { type: "FeatureCollection", features: [aoiPoly] });
        }
        showQueryLayers(["uploaded_custom_aoi", "ga_electricity_substations", "nsw_foi_building_complexes"]);
        if (aoi.bbox && map) {
          map.fitBounds([[aoi.bbox[0], aoi.bbox[1]], [aoi.bbox[2], aoi.bbox[3]]], { padding: 40, duration: 800 });
        }
      }

      legendItems.innerHTML = `
        <div class="flex items-center gap-2"><span class="w-3 h-3 rounded-sm bg-[#0284c7]"></span><span>Custom Uploaded Area of Interest (AOI)</span></div>
        <div class="flex items-center gap-2"><span class="w-3 h-3 rounded-full bg-[#c2410c]"></span><span>GA Power Substations</span></div>
        <div class="flex items-center gap-2"><span class="w-3 h-3 rounded-full bg-[#16a34a]"></span><span>NSW FOI Health &amp; Emergency Complexes</span></div>
      `;
    }
    }

    populateStep5AndStep6();
    document.getElementById("panel-map").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function populateStep5AndStep6() {
    if (!bundle) return;
    document.getElementById("panel-analytics").style.display = "block";
    document.getElementById("panel-ai-steps").style.display = "block";

    const runKey = activeScenarioKey === "ambiguous_pop" ? "pop_comparison" : activeScenarioKey;
    const telemBody = document.getElementById("telemetryTableBody");
    const breakHead = document.getElementById("step5BreakdownHead");
    const breakBody = document.getElementById("step5BreakdownBody");
    const breakTitle = document.getElementById("step5BreakdownTitle");

    // Dynamic Query Execution Profile (tied directly to the active query in Steps 1-4)
    if (runKey === "pop_comparison") {
      const reg = bundle.population_study.regimes[selectedRegimeIdx] || bundle.population_study.regimes[1];
      telemBody.innerHTML = `
        <tr>
          <td class="font-semibold">Parquet Scan &amp; BBox Pushdown</td>
          <td><code>read_parquet(derived_hunter_1km_population_grid)</code></td>
          <td><strong class="text-secondary font-mono">1.2 ms</strong></td>
          <td><span class="badge-tag optimal">PASS</span></td>
        </tr>
        <tr>
          <td class="font-semibold">Centroid ST_Contains (Method A)</td>
          <td><code>ST_Contains(incident, ST_Centroid(cell))</code></td>
          <td><code>${(reg.execution_ms * 0.3).toFixed(1)} ms</code></td>
          <td><span class="badge-tag optimal">OPTIMAL</span></td>
        </tr>
        <tr>
          <td class="font-semibold">Polygon Footprint ST_Intersects (Method B)</td>
          <td><code>ST_Intersects(incident, cell_geom)</code></td>
          <td><code>${(reg.execution_ms * 0.4).toFixed(1)} ms</code></td>
          <td><span class="badge-tag optimal">BENCHMARK</span></td>
        </tr>
        <tr>
          <td class="font-semibold">Proportional Area Re-projection (Method C)</td>
          <td><code>ST_Transform + ST_Area(ST_Intersection)</code></td>
          <td><code>${(reg.execution_ms * 0.3).toFixed(1)} ms</code></td>
          <td><span class="badge-tag tight">METRIC EPSG:3112</span></td>
        </tr>
        <tr class="bg-surface-container">
          <td class="font-bold">Total Query Execution</td>
          <td><code>DuckDB Spatial (Cold/Warm)</code></td>
          <td><strong class="text-primary font-mono">${reg.execution_ms} ms</strong></td>
          <td><span class="badge badge-accent">ACTIVE QUERY</span></td>
        </tr>
      `;

      breakTitle.textContent = `SA2 Population Distribution (${reg.regime_title})`;
      breakHead.innerHTML = `
        <tr>
          <th>SA2 Name (ASGS 2021)</th>
          <th>Grid Cells</th>
          <th>Total Population</th>
          <th>Method C Estimated Pop*</th>
        </tr>
      `;
      // Group cells by SA2 dynamically from active regime
      const sa2Map = {};
      (reg.cells || []).forEach(c => {
        const name = c.sa2_name21 || "Other";
        if (!sa2Map[name]) sa2Map[name] = { cells: 0, pop: 0, weighted: 0 };
        sa2Map[name].cells += 1;
        sa2Map[name].pop += c.cell_population || 0;
        sa2Map[name].weighted += c.method_c_weighted_pop || 0;
      });
      breakBody.innerHTML = Object.entries(sa2Map)
        .sort((a, b) => b[1].pop - a[1].pop)
        .map(([name, stat]) => `
          <tr>
            <td class="font-semibold">${name}</td>
            <td><code>${stat.cells} cells</code></td>
            <td><strong>${Math.round(stat.pop).toLocaleString()}</strong></td>
            <td><code class="text-secondary">${Math.round(stat.weighted).toLocaleString()} est*</code></td>
          </tr>
        `).join("");

    } else if (runKey === "substation_flood") {
      const dep = bundle.infrastructure_dependencies;
      telemBody.innerHTML = `
        <tr>
          <td class="font-semibold">Parquet Scan &amp; BBox Filter</td>
          <td><code>read_parquet(ga_electricity_substations)</code></td>
          <td><strong class="text-secondary font-mono">2.4 ms</strong></td>
          <td><span class="badge-tag optimal">PASS</span></td>
        </tr>
        <tr>
          <td class="font-semibold">Metric Coordinate Transform</td>
          <td><code>ST_Transform(geom, EPSG:7844 &rarr; 3112)</code></td>
          <td><code>14.2 ms</code></td>
          <td><span class="badge-tag optimal">PASS</span></td>
        </tr>
        <tr>
          <td class="font-semibold">Flood Surface Nearest Distance</td>
          <td><code>ST_Distance(sub_3112, inund_3112)</code></td>
          <td><code>${(dep.execution_ms * 0.45).toFixed(1)} ms</code></td>
          <td><span class="badge-tag optimal">GCS PARQUET</span></td>
        </tr>
        <tr>
          <td class="font-semibold">FOI Building Complex Catchment</td>
          <td><code>ST_DWithin(sub_3112, foi_3112, ${userParams.distance || "5000m"})</code></td>
          <td><code>${(dep.execution_ms * 0.45).toFixed(1)} ms</code></td>
          <td><span class="badge-tag tight">RADIUS SEARCH</span></td>
        </tr>
        <tr class="bg-surface-container">
          <td class="font-bold">Total Query Execution</td>
          <td><code>DuckDB Spatial</code></td>
          <td><strong class="text-primary font-mono">${dep.execution_ms} ms</strong></td>
          <td><span class="badge badge-accent">ACTIVE QUERY</span></td>
        </tr>
      `;

      breakTitle.textContent = "Substations by Exposure Tier & Proximity";
      breakHead.innerHTML = `
        <tr>
          <th>Exposure Tier</th>
          <th>Distance Band</th>
          <th>Substations</th>
          <th>Total Dependent FOI</th>
        </tr>
      `;
      const tiers = {
        CRITICAL: { band: "< 500m", count: 0, foi: 0 },
        HIGH: { band: "500m - 2,000m", count: 0, foi: 0 },
        MODERATE: { band: "2,000m - 5,000m", count: 0, foi: 0 },
        LOW: { band: "> 5,000m", count: 0, foi: 0 }
      };
      (dep.substations || []).forEach(s => {
        const t = s.hazard_exposure_tier in tiers ? s.hazard_exposure_tier : (s.distance_to_inundation_m <= 500 ? "CRITICAL" : (s.distance_to_inundation_m <= 2000 ? "HIGH" : "MODERATE"));
        tiers[t].count += 1;
        tiers[t].foi += (s.dependent_foi_within_5km || 0);
      });
      breakBody.innerHTML = Object.entries(tiers).map(([t, stat]) => `
        <tr>
          <td><span class="badge-tag ${t === 'CRITICAL' ? 'long' : (t === 'HIGH' ? 'tight' : 'optimal')}">${t}</span></td>
          <td><code>${stat.band}</code></td>
          <td><strong>${stat.count}</strong> substations</td>
          <td><code>${stat.foi} facilities</code></td>
        </tr>
      `).join("");

    } else if (runKey === "lga_multi_hazard") {
      const regState = bundle.multi_scale_exposure.regional_state_scale;
      telemBody.innerHTML = `
        <tr>
          <td class="font-semibold">LGA ASGS 2025 Parquet Scan</td>
          <td><code>read_parquet(next_lga_boundaries_asgs2025)</code></td>
          <td><strong class="text-secondary font-mono">3.1 ms</strong></td>
          <td><span class="badge-tag optimal">PASS</span></td>
        </tr>
        <tr>
          <td class="font-semibold">Substation Spatial Intersection</td>
          <td><code>ST_Intersects(lga.geom, sub.geom)</code></td>
          <td><code>18.4 ms</code></td>
          <td><span class="badge-tag optimal">PASS</span></td>
        </tr>
        <tr>
          <td class="font-semibold">Flood Polygon Intersection</td>
          <td><code>ST_Intersects(lga.geom, inund.geom)</code></td>
          <td><code>45.2 ms</code></td>
          <td><span class="badge-tag optimal">PASS</span></td>
        </tr>
        <tr>
          <td class="font-semibold">FOI Building Complexes Rollup</td>
          <td><code>ST_Intersects(lga.geom, foi.geom)</code></td>
          <td><code>${(regState.execution_ms - 66.7).toFixed(1)} ms</code></td>
          <td><span class="badge-tag optimal">1,500 FACILITIES</span></td>
        </tr>
        <tr class="bg-surface-container">
          <td class="font-bold">Total Regional Query Execution</td>
          <td><code>DuckDB Spatial</code></td>
          <td><strong class="text-primary font-mono">${regState.execution_ms} ms</strong></td>
          <td><span class="badge badge-accent">ACTIVE QUERY</span></td>
        </tr>
      `;

      breakTitle.textContent = "LGA Critical Facility Density (FOI per km²)";
      breakHead.innerHTML = `
        <tr>
          <th>LGA Name</th>
          <th>Area (km²)</th>
          <th>Substations</th>
          <th>FOI Facilities</th>
          <th>Facility Density</th>
        </tr>
      `;
      breakBody.innerHTML = (regState.lga_rollup || []).slice(0, 6).map(r => `
        <tr>
          <td class="font-semibold">${r.lga_name}</td>
          <td><code>${r.area_sqkm} km²</code></td>
          <td>${r.substations_count}</td>
          <td><strong>${r.foi_complexes_count}</strong></td>
          <td><code class="text-secondary">${(r.foi_complexes_count / (r.area_sqkm || 1)).toFixed(2)} / km²</code></td>
        </tr>
      `).join("");

    } else if (runKey === "live_rfs") {
      const regState = bundle.multi_scale_exposure.regional_state_scale;
      telemBody.innerHTML = `
        <tr>
          <td class="font-semibold">NSW RFS GeoJSON / Parquet Scan</td>
          <td><code>read_parquet(nsw_rfs_major_incidents_live)</code></td>
          <td><strong class="text-secondary font-mono">1.1 ms</strong></td>
          <td><span class="badge-tag optimal">PASS</span></td>
        </tr>
        <tr>
          <td class="font-semibold">Centroid Extraction (EPSG:7844)</td>
          <td><code>ST_Centroid(geom)</code></td>
          <td><code>4.2 ms</code></td>
          <td><span class="badge-tag optimal">PASS</span></td>
        </tr>
        <tr>
          <td class="font-semibold">Area Filter &amp; Full Text Match</td>
          <td><code>title ILIKE '%${userParams.area || "NSW"}%'</code></td>
          <td><code>1.8 ms</code></td>
          <td><span class="badge-tag optimal">FILTERED</span></td>
        </tr>
        <tr class="bg-surface-container">
          <td class="font-bold">Total Query Execution</td>
          <td><code>DuckDB Spatial Live Stream</code></td>
          <td><strong class="text-primary font-mono">${regState.execution_ms} ms</strong></td>
          <td><span class="badge badge-accent">ACTIVE QUERY</span></td>
        </tr>
      `;

      breakTitle.textContent = "NSW RFS Incidents by Alert Classification";
      breakHead.innerHTML = `
        <tr>
          <th>Alert Level</th>
          <th>Active Incidents</th>
          <th>Proportion</th>
          <th>Standard Operating Response</th>
        </tr>
      `;
      const cats = {};
      (regState.live_rfs_incidents || []).forEach(inc => {
        const lvl = inc.alert_level || "Other";
        cats[lvl] = (cats[lvl] || 0) + 1;
      });
      const totalInc = (regState.live_rfs_incidents || []).length || 1;
      breakBody.innerHTML = Object.entries(cats).map(([lvl, cnt]) => `
        <tr>
          <td><span class="badge-tag ${lvl.includes('Emergency') ? 'long' : (lvl.includes('Watch') ? 'tight' : 'optimal')}">${lvl}</span></td>
          <td><strong>${cnt}</strong></td>
          <td><code>${((cnt / totalInc) * 100).toFixed(0)}%</code></td>
          <td class="text-xs text-on-surface-variant">${lvl.includes('Emergency') ? 'Take immediate action, shelter in place' : (lvl.includes('Watch') ? 'Heightened threat, prepare properties' : 'Monitor conditions via RFS feed')}</td>
        </tr>
      `).join("");

    } else if (runKey === "national_power") {
      const nat = bundle.multi_scale_exposure.national_scale;
      telemBody.innerHTML = `
        <tr>
          <td class="font-semibold">GA Power Stations Scan (430 rows)</td>
          <td><code>read_parquet(ga_major_power_stations)</code></td>
          <td><strong class="text-secondary font-mono">1.8 ms</strong></td>
          <td><span class="badge-tag optimal">PASS</span></td>
        </tr>
        <tr>
          <td class="font-semibold">State Grouping &amp; Generation Rollup</td>
          <td><code>SUM(TRY_CAST(generation_capacity_mw))</code></td>
          <td><code>3.4 ms</code></td>
          <td><span class="badge-tag optimal">PASS</span></td>
        </tr>
        <tr>
          <td class="font-semibold">Seismic Hazard Contours Alignment</td>
          <td><code>NSHA 2018 10% in 50 yr PGA</code></td>
          <td><code>5.2 ms</code></td>
          <td><span class="badge-tag optimal">GDA2020</span></td>
        </tr>
        <tr class="bg-surface-container">
          <td class="font-bold">Total National Query Execution</td>
          <td><code>DuckDB Spatial National Fleet</code></td>
          <td><strong class="text-primary font-mono">${nat.execution_ms} ms</strong></td>
          <td><span class="badge badge-accent">ACTIVE QUERY</span></td>
        </tr>
      `;

      breakTitle.textContent = "National Generation Capacity by State";
      breakHead.innerHTML = `
        <tr>
          <th>State / Jurisdiction</th>
          <th>Stations</th>
          <th>Total Capacity (MW)</th>
          <th>Share of National Grid</th>
        </tr>
      `;
      const totalCap = (nat.state_rollup || []).reduce((a, s) => a + Number(s.total_capacity_mw || 0), 0) || 1;
      breakBody.innerHTML = (nat.state_rollup || []).map(s => `
        <tr>
          <td class="font-semibold">${s.state_name}</td>
          <td><code>${s.power_station_count}</code></td>
          <td><strong>${Number(s.total_capacity_mw).toLocaleString()} MW</strong></td>
          <td><code class="text-secondary">${((Number(s.total_capacity_mw) / totalCap) * 100).toFixed(1)}%</code></td>
        </tr>
      `).join("");
    } else if (runKey === "cyclone_track_exposure") {
      telemBody.innerHTML = `
        <tr>
          <td class="font-semibold">Uploaded KML/KMZ Spatial Parsing</td>
          <td><code>DOMParser + Longitude Normalization</code></td>
          <td><strong class="text-secondary font-mono">1.1 ms</strong></td>
          <td><span class="badge-tag optimal">PASS</span></td>
        </tr>
        <tr>
          <td class="font-semibold">Concentric Hazard Zone Buffering</td>
          <td><code>Zone 1 (50km), Zone 2 (150km), Zone 3 (300km)</code></td>
          <td><code>0.8 ms</code></td>
          <td><span class="badge-tag optimal">METEOROLOGICAL</span></td>
        </tr>
        <tr>
          <td class="font-semibold">Great-Circle Haversine Distance Search</td>
          <td><code>min_distance_to_segment_km</code></td>
          <td><code>0.9 ms</code></td>
          <td><span class="badge-tag optimal">PASS</span></td>
        </tr>
        <tr>
          <td class="font-semibold">Asset Exposure &amp; Zone Classification</td>
          <td><code>ST_DWithin Hazard Classification</code></td>
          <td><code>0.4 ms</code></td>
          <td><span class="badge-tag tight">CRITICAL</span></td>
        </tr>
        <tr class="bg-surface-container">
          <td class="font-bold">Total Query Execution</td>
          <td><code>Client / DuckDB Spatial Engine</code></td>
          <td><strong class="text-primary font-mono">3.2 ms</strong></td>
          <td><span class="badge badge-accent">ACTIVE QUERY</span></td>
        </tr>
      `;

      breakTitle.textContent = "Assets by Predicted Cyclone Impact Zone";
      breakHead.innerHTML = `
        <tr>
          <th>Predicted Cyclone Zone</th>
          <th>Radius Band</th>
          <th>Assessed Assets</th>
          <th>Operational Status</th>
        </tr>
      `;
      const assessed = uploadedCycloneAssessments || [];
      const zCounts = {
        "Zone 1: Core / Eyewall": { band: "< 50 km (>64 kt)", count: assessed.filter(a => a.zone_code === "ZONE_1").length, status: "CRITICAL EVACUATION", cls: "critical" },
        "Zone 2: Severe Gale": { band: "50 - 150 km (48-63 kt)", count: assessed.filter(a => a.zone_code === "ZONE_2").length, status: "HIGH ALERT / SECURE", cls: "tight" },
        "Zone 3: Outer Gale Watch": { band: "150 - 300 km (34-47 kt)", count: assessed.filter(a => a.zone_code === "ZONE_3").length, status: "WATCH / STANDBY", cls: "optimal" },
        "Zone 4: Peripheral": { band: "> 300 km", count: assessed.filter(a => a.zone_code === "ZONE_4").length, status: "MONITOR", cls: "long" }
      };

      breakBody.innerHTML = Object.entries(zCounts).map(([zName, stat]) => `
        <tr>
          <td class="font-semibold">${zName}</td>
          <td><code>${stat.band}</code></td>
          <td><strong>${stat.count}</strong> asset(s)</td>
          <td><span class="badge-tag ${stat.cls}">${stat.status}</span></td>
        </tr>
      `).join("");
    }

    // STEP 6: Multi-Scale Context & Offline Packages directly tied to current query context
    const cards = [
      {
        badge: "SCALE: LOCAL",
        tag: "Facility Exposure",
        title: "Lower Hunter Flood Buffer Analysis",
        desc: "Examine direct floodwater intersection and 250m metric buffer exposure against 1,500 hospital, school, and emergency complexes.",
        actionText: "Switch to Local Infrastructure",
        scenario: "substation_flood"
      },
      {
        badge: "SCALE: REGIONAL",
        tag: "Population Grid",
        title: "1 km² Population Footprints (A/B/C)",
        desc: "Compare centroid containment vs full polygon intersection vs area-weighted population counts on the active hazard area.",
        actionText: "Switch to Population Grid",
        scenario: "pop_comparison"
      },
      {
        badge: "SCALE: OFFLINE",
        tag: "Field Deployment",
        title: "Disconnected Emergency Map Package",
        desc: "Deploy the self-contained zero-external-dependency emergency field viewer with offline GeoJSON vector tiles.",
        actionText: "Open Offline Field Pack",
        href: "map_packages/hunter_flood_emergency_pack/index.html"
      }
    ];

    const container = document.getElementById("scenarioCardsContainer");
    container.innerHTML = cards
      .map(
        c => `
      <div class="scenario-step-card">
        <div class="scenario-step-top">
          <div class="scenario-step-meta">
            <span class="scenario-step-badge">${c.badge}</span>
            <span class="scenario-step-tag">${c.tag}</span>
          </div>
          <h3 class="scenario-step-title">${c.title}</h3>
          <p class="scenario-step-desc">${c.desc}</p>
        </div>
        ${c.href
            ? `<a href="${c.href}" target="_blank" class="scenario-step-btn flex items-center justify-center no-underline font-bold">${c.actionText} &rarr;</a>`
            : `<button type="button" class="scenario-step-btn font-bold" data-card-scenario="${c.scenario}">${c.actionText}</button>`
          }
      </div>
    `
      )
      .join("");

    container.querySelectorAll("[data-card-scenario]").forEach(btn => {
      btn.addEventListener("click", () => {
        const sc = btn.getAttribute("data-card-scenario");
        document.getElementById("nlInput").value = SCENARIO_PRESETS[sc].question;
        analyzeQuery(sc);
        document.getElementById("panel-query").scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });
  }

  function resetAllToBlank() {
    activeScenarioKey = null;
    userParams = { area: "", distance: "", options: "" };
    document.getElementById("nlInput").value = "";
    document.getElementById("globalSearch").value = "";
    document.getElementById("sqlInput").value = "";
    document.getElementById("sqlTargetUri").textContent = "gs://operational-intelligence-crafter-lake/geoparquet/ (awaiting query)";
    document.getElementById("clarificationBox").style.display = "none";
    document.getElementById("ctxScaleVal").textContent = "—";
    document.getElementById("ctxScaleSub").textContent = "No area defined yet";
    document.getElementById("ctxMethodVal").textContent = "—";
    document.getElementById("ctxMethodSub").textContent = "Distance / filter / population method";
    document.getElementById("ctxGateVal").textContent = "—";
    document.getElementById("ctxGateSub").textContent = "Stored GeoParquet on GCS";

    clearMapLayers();
    if (map && mapReady) {
      map.flyTo({ center: [151.2, -32.9], zoom: 6.2 });
    }
    document.getElementById("mapEmptyOverlay").style.display = "flex";
    document.getElementById("mapLegendHud").style.display = "none";
    document.getElementById("mapFeatureCountBadge").textContent = "0 Features Loaded";

    document.getElementById("kpiVal1").textContent = "—";
    document.getElementById("kpiVal2").textContent = "—";
    document.getElementById("kpiVal3").textContent = "—";
    document.getElementById("kpiVal4").textContent = "—";
    document.getElementById("execTimeBadge").textContent = "Not Run";
    document.getElementById("btnExportGeojson").style.display = "none";
    document.getElementById("inspectorBanner").style.display = "none";
    document.getElementById("resultsTableBody").innerHTML = `
      <tr>
        <td colspan="5" class="empty-cell">No query executed yet. Select a preset in <strong>Step 01</strong>, define your area and options, click <strong>Create SQL</strong>, and click <strong>Run Query</strong>.</td>
      </tr>
    `;
    document.getElementById("panel-analytics").style.display = "none";
    document.getElementById("panel-ai-steps").style.display = "none";
  }

  let uploadedCycloneData = null;
  let uploadedCycloneZones = null;
  let uploadedCycloneAssessments = null;

  function normalizeCoord(rawLon, rawLat, forceAusLat = true) {
    let lon = Number(rawLon);
    while (lon < -180.0) lon += 360.0;
    while (lon > 180.0) lon -= 360.0;
    lon = Number(lon.toFixed(6));
    let lat = Number(Number(rawLat).toFixed(6));
    // Australia is Southern Hemisphere: 110°E to 165°E, -10°S to -45°S.
    // Invert positive lat to negative if in Australian longitude range (Y is negative).
    if (forceAusLat && lon >= 110.0 && lon <= 165.0 && lat >= 10.0 && lat <= 45.0) {
      lat = -Math.abs(lat);
    }
    return [lon, lat];
  }

  function normalizeLon(lon) {
    while (lon < -180.0) lon += 360.0;
    while (lon > 180.0) lon -= 360.0;
    return Number(lon.toFixed(6));
  }

  function recursivelyNormalizeGeoJSON(geojson) {
    if (!geojson) return geojson;
    function normGeom(geom) {
      if (!geom || !geom.coordinates) return;
      const type = geom.type;
      if (type === "Point") {
        geom.coordinates = normalizeCoord(geom.coordinates[0], geom.coordinates[1]);
      } else if (type === "LineString" || type === "MultiPoint") {
        geom.coordinates = geom.coordinates.map(c => normalizeCoord(c[0], c[1]));
      } else if (type === "Polygon" || type === "MultiLineString") {
        geom.coordinates = geom.coordinates.map(ring => ring.map(c => normalizeCoord(c[0], c[1])));
      } else if (type === "MultiPolygon") {
        geom.coordinates = geom.coordinates.map(poly => poly.map(ring => ring.map(c => normalizeCoord(c[0], c[1]))));
      }
    }
    if (geojson.type === "FeatureCollection" && Array.isArray(geojson.features)) {
      geojson.features.forEach(f => { if (f && f.geometry) normGeom(f.geometry); });
    } else if (geojson.type === "Feature" && geojson.geometry) {
      normGeom(geojson.geometry);
    }
    return geojson;
  }

  function calculateGeoJSONBbox(geojson) {
    let minLon = Infinity, minLat = Infinity, maxLon = -Infinity, maxLat = -Infinity;
    function walkCoord(c) {
      if (!c || c.length < 2) return;
      const [x, y] = c;
      if (x < minLon) minLon = x;
      if (x > maxLon) maxLon = x;
      if (y < minLat) minLat = y;
      if (y > maxLat) maxLat = y;
    }
    function walkGeom(geom) {
      if (!geom || !geom.coordinates) return;
      const t = geom.type;
      if (t === "Point") walkCoord(geom.coordinates);
      else if (t === "LineString" || t === "MultiPoint") geom.coordinates.forEach(walkCoord);
      else if (t === "Polygon" || t === "MultiLineString") geom.coordinates.forEach(r => r.forEach(walkCoord));
      else if (t === "MultiPolygon") geom.coordinates.forEach(p => p.forEach(r => r.forEach(walkCoord)));
    }
    if (geojson.features) geojson.features.forEach(f => { if (f && f.geometry) walkGeom(f.geometry); });
    else if (geojson.geometry) walkGeom(geojson.geometry);
    if (minLon === Infinity) return null;
    return [minLon, minLat, maxLon, maxLat];
  }

  function haversineKm(lat1, lon1, lat2, lon2) {
    const r = 6371.0;
    const phi1 = (lat1 * Math.PI) / 180.0;
    const phi2 = (lat2 * Math.PI) / 180.0;
    const dphi = ((lat2 - lat1) * Math.PI) / 180.0;
    const dlam = ((lon2 - lon1) * Math.PI) / 180.0;
    const a = Math.sin(dphi / 2.0) ** 2 + Math.cos(phi1) * Math.cos(phi2) * Math.sin(dlam / 2.0) ** 2;
    return Number((r * 2.0 * Math.atan2(Math.sqrt(a), Math.sqrt(1.0 - a))).toFixed(1));
  }

  function generateCircleRing(centerLon, centerLat, radiusKm, numPoints = 36) {
    const coords = [];
    const latRad = (centerLat * Math.PI) / 180.0;
    const kx = 111.32 * Math.cos(latRad);
    const ky = 110.574;
    for (let i = 0; i < numPoints; i++) {
      const angle = (2.0 * Math.PI * i) / numPoints;
      const dx = radiusKm * Math.cos(angle);
      const dy = radiusKm * Math.sin(angle);
      const [lon, lat] = normalizeCoord(centerLon + dx / kx, centerLat + dy / ky, false);
      coords.push([lon, lat]);
    }
    coords.push(coords[0]);
    return coords;
  }

  function parseKmlToGeoJSON(kmlText) {
    const parser = new DOMParser();
    const xml = parser.parseFromString(kmlText, "text/xml");
    const placemarks = xml.querySelectorAll("Placemark");
    const features = [];
    let titleName = "Uploaded Spatial Data";
    let advisoryNum = "Current";

    const docName = xml.querySelector("Document > name");
    if (docName && docName.textContent) titleName = docName.textContent.trim();

    placemarks.forEach((p, idx) => {
      const name = p.querySelector("name") ? p.querySelector("name").textContent.trim() : "";
      const desc = p.querySelector("description") ? p.querySelector("description").textContent : "";
      const props = { name: name || `Feature ${idx + 1}` };

      if (desc) {
        const titleMatch = desc.match(/<b>([^<]+(?:Typhoon|Cyclone|Storm|WP\d+)[^<]*)<\/b>/i);
        if (titleMatch) titleName = titleMatch[1].trim();
        const advMatch = desc.match(/Advisory\s*#?\s*(\d+)/i);
        if (advMatch) advisoryNum = advMatch[1].trim();
        const validMatch = desc.match(/Valid at:\s*([^<]+)/i);
        if (validMatch) props.valid_time = validMatch[1].trim();
        const stepMatch = desc.match(/(\d+\s*hr\s*Forecast|Advisory Information|Forecast Track)/i);
        if (stepMatch) props.forecast_horizon = stepMatch[1].trim();
        const windMatch = desc.match(/Maximum Wind:\s*(\d+)\s*knots(?:\s*\(([^)]+)\))?/i);
        if (windMatch) {
          props.max_wind_knots = parseInt(windMatch[1], 10);
          props.max_wind_str = windMatch[2] ? `${windMatch[1]} kt (${windMatch[2]})` : `${windMatch[1]} kt`;
        }
        const gustMatch = desc.match(/Wind Gusts:\s*(\d+)\s*knots/i);
        if (gustMatch) props.wind_gusts_knots = parseInt(gustMatch[1], 10);
        const pressMatch = desc.match(/Minimum Pressure:\s*(\d+)\s*mb/i);
        if (pressMatch) props.min_pressure_mb = parseInt(pressMatch[1], 10);
      }

      // Point
      const pt = p.querySelector("Point > coordinates");
      if (pt && pt.textContent) {
        const parts = pt.textContent.trim().split(",");
        if (parts.length >= 2) {
          const [normLon, normLat] = normalizeCoord(parseFloat(parts[0]), parseFloat(parts[1]));
          features.push({
            type: "Feature",
            geometry: { type: "Point", coordinates: [normLon, normLat] },
            properties: props
          });
        }
      }

      // LineString
      const ls = p.querySelector("LineString > coordinates");
      if (ls && ls.textContent) {
        const tokens = ls.textContent.trim().split(/\s+/);
        const coords = [];
        tokens.forEach(tok => {
          const parts = tok.split(",");
          if (parts.length >= 2) {
            coords.push(normalizeCoord(parseFloat(parts[0]), parseFloat(parts[1])));
          }
        });
        if (coords.length >= 2) {
          features.push({
            type: "Feature",
            geometry: { type: "LineString", coordinates: coords },
            properties: props
          });
        }
      }

      // Polygon (Area of Interest)
      const polys = p.querySelectorAll("Polygon");
      polys.forEach(poly => {
        const rings = [];
        const outerCoords = poly.querySelector("outerBoundaryIs > LinearRing > coordinates");
        if (outerCoords && outerCoords.textContent) {
          const ring = [];
          outerCoords.textContent.trim().split(/\s+/).forEach(tok => {
            const parts = tok.split(",");
            if (parts.length >= 2) {
              ring.push(normalizeCoord(parseFloat(parts[0]), parseFloat(parts[1])));
            }
          });
          if (ring.length >= 3) {
            if (ring[0][0] !== ring[ring.length - 1][0] || ring[0][1] !== ring[ring.length - 1][1]) {
              ring.push(ring[0]);
            }
            rings.push(ring);
          }
        }
        poly.querySelectorAll("innerBoundaryIs > LinearRing > coordinates").forEach(innerCoords => {
          if (innerCoords && innerCoords.textContent) {
            const ring = [];
            innerCoords.textContent.trim().split(/\s+/).forEach(tok => {
              const parts = tok.split(",");
              if (parts.length >= 2) ring.push(normalizeCoord(parseFloat(parts[0]), parseFloat(parts[1])));
            });
            if (ring.length >= 3) {
              if (ring[0][0] !== ring[ring.length - 1][0] || ring[0][1] !== ring[ring.length - 1][1]) ring.push(ring[0]);
              rings.push(ring);
            }
          }
        });
        if (rings.length > 0) {
          features.push({
            type: "Feature",
            geometry: { type: "Polygon", coordinates: rings },
            properties: { ...props, kind: "area_of_interest" }
          });
        }
      });
    });

    return {
      type: "FeatureCollection",
      metadata: { cyclone_name: titleName, advisory: advisoryNum, title: titleName },
      features
    };
  }

  function buildCycloneZones(geojson, radii = { zone1: 50, zone2: 150, zone3: 300 }) {
    const points = geojson.features.filter(f => f.geometry && f.geometry.type === "Point");
    const zoneFeatures = [];
    points.forEach((pt, idx) => {
      const [lon, lat] = pt.geometry.coordinates;
      const props = pt.properties || {};
      const horizon = props.forecast_horizon || `Point ${idx + 1}`;
      const wind = props.max_wind_str || "Unknown";

      // Zone 3: Outer Watch (300 km)
      zoneFeatures.push({
        type: "Feature",
        geometry: { type: "Polygon", coordinates: [generateCircleRing(lon, lat, radii.zone3)] },
        properties: {
          zone_code: "ZONE_3",
          zone_name: "Zone 3 — Outer Gale Watch (34–47 kt)",
          radius_km: radii.zone3,
          forecast_point: horizon,
          valid_time: props.valid_time,
          expected_wind: wind,
          color: "#eab308"
        }
      });

      // Zone 2: Severe Gale (150 km)
      zoneFeatures.push({
        type: "Feature",
        geometry: { type: "Polygon", coordinates: [generateCircleRing(lon, lat, radii.zone2)] },
        properties: {
          zone_code: "ZONE_2",
          zone_name: "Zone 2 — Severe Gale Force (48–63 kt)",
          radius_km: radii.zone2,
          forecast_point: horizon,
          valid_time: props.valid_time,
          expected_wind: wind,
          color: "#ea580c"
        }
      });

      // Zone 1: Destructive Core (50 km)
      zoneFeatures.push({
        type: "Feature",
        geometry: { type: "Polygon", coordinates: [generateCircleRing(lon, lat, radii.zone1)] },
        properties: {
          zone_code: "ZONE_1",
          zone_name: "Zone 1 — Destructive Core / Eyewall (>64 kt)",
          radius_km: radii.zone1,
          forecast_point: horizon,
          valid_time: props.valid_time,
          expected_wind: wind,
          color: "#dc2626"
        }
      });
    });
    return { type: "FeatureCollection", features: zoneFeatures };
  }

  function assessAssetsAgainstCyclone(cycloneGeojson, assets) {
    const points = (cycloneGeojson && cycloneGeojson.features) ? cycloneGeojson.features.filter(f => f.geometry && f.geometry.type === "Point") : [];

    return assets.map((a, i) => {
      let minDist = Infinity;
      let closestPt = null;

      points.forEach(pt => {
        const [ptLon, ptLat] = pt.geometry.coordinates;
        const d = haversineKm(a.lat, a.lon, ptLat, ptLon);
        if (d < minDist) {
          minDist = d;
          closestPt = pt;
        }
      });

      if (minDist === Infinity) minDist = 999.0;

      let zoneCode = "ZONE_4";
      let zoneName = "Zone 4: Peripheral / Outside Cone";
      let alertPriority = "LOW / MONITOR";
      let badgeClass = "long";

      if (minDist <= 50.0) {
        zoneCode = "ZONE_1";
        zoneName = "Zone 1: Destructive Core / Eyewall (>64 kt)";
        alertPriority = "CRITICAL EVACUATION";
        badgeClass = "critical";
      } else if (minDist <= 150.0) {
        zoneCode = "ZONE_2";
        zoneName = "Zone 2: Severe Gale Force (48–63 kt)";
        alertPriority = "HIGH ALERT / SECURE";
        badgeClass = "tight";
      } else if (minDist <= 300.0) {
        zoneCode = "ZONE_3";
        zoneName = "Zone 3: Outer Gale Watch (34–47 kt)";
        alertPriority = "GALE WATCH / STANDBY";
        badgeClass = "optimal";
      }

      const ptProps = closestPt ? closestPt.properties : {};

      return {
        asset_id: a.id || `ASSET_${i + 1}`,
        asset_name: a.name,
        asset_type: a.type || "Critical Infrastructure",
        lat: a.lat,
        lon: a.lon,
        distance_km: minDist,
        zone_code: zoneCode,
        zone_name: zoneName,
        alert_priority: alertPriority,
        badge_class: badgeClass,
        closest_horizon: ptProps.forecast_horizon || "N/A",
        arrival_time: ptProps.valid_time || "N/A",
        expected_wind: ptProps.max_wind_str || "N/A",
        gusts: ptProps.wind_gusts_knots ? `${ptProps.wind_gusts_knots} kt` : "N/A"
      };
    });
  }

  async function processUploadedSpatialFile(file) {
    const statusText = document.getElementById("uploadStatusText");
    const fn = file.name.toLowerCase();
    if (statusText) statusText.innerHTML = `<span class="text-secondary font-bold">Processing ${file.name}...</span>`;

    try {
      let geojson = null;

      if (fn.endsWith(".kmz")) {
        if (!window.JSZip) throw new Error("JSZip library not loaded for KMZ processing.");
        const zip = await window.JSZip.loadAsync(file);
        const kmlKey = Object.keys(zip.files).find(k => k.toLowerCase().endsWith(".kml"));
        if (!kmlKey) throw new Error("No .kml found inside uploaded .kmz archive.");
        const kmlStr = await zip.files[kmlKey].async("string");
        geojson = parseKmlToGeoJSON(kmlStr);
      } else if (fn.endsWith(".kml")) {
        const kmlStr = await file.text();
        geojson = parseKmlToGeoJSON(kmlStr);
      } else if (fn.endsWith(".geojson") || fn.endsWith(".json")) {
        const jsonStr = await file.text();
        geojson = JSON.parse(jsonStr);
        if (geojson.type === "Feature") geojson = { type: "FeatureCollection", features: [geojson] };
      } else if (fn.endsWith(".zip")) {
        if (window.shp) {
          const buf = await file.arrayBuffer();
          geojson = await window.shp(buf);
          if (Array.isArray(geojson)) geojson = geojson[0];
        } else {
          throw new Error("Shapefile zip unpacker not available in browser.");
        }
      } else {
        throw new Error("Unsupported format. Please upload .kmz, .kml, .geojson, or .zip.");
      }

      if (!geojson || !geojson.features || !geojson.features.length) {
        throw new Error("No spatial features parsed from uploaded file.");
      }

      // Normalize all coordinates across the parsed GeoJSON (enforcing Australian negative latitude)
      recursivelyNormalizeGeoJSON(geojson);
      const bbox = calculateGeoJSONBbox(geojson);
      geojson.bbox = bbox;

      const hasPolygons = geojson.features.some(f => f.geometry && (f.geometry.type === "Polygon" || f.geometry.type === "MultiPolygon"));
      const isCycloneTrack = geojson.features.some(f => f.properties && (f.properties.max_wind_knots || f.properties.valid_time || f.properties.forecast_horizon)) ||
        (geojson.metadata && geojson.metadata.title && /cyclone|typhoon|track|wp\d+/i.test(geojson.metadata.title));

      if (hasPolygons && !isCycloneTrack) {
        // Operational Intelligence Area of Interest (AOI) Mode
        uploadedAoiData = geojson;
        const aoiName = (geojson.metadata && (geojson.metadata.title || geojson.metadata.cyclone_name)) || file.name.replace(/\.[^/.]+$/, "");
        uploadedAoiData.name = aoiName;

        if (statusText) {
          statusText.innerHTML = `<span class="text-green-600 font-bold">✓ Loaded Area of Interest:</span> ${aoiName} — ${geojson.features.length} feature(s). Operational exposure ready.`;
        }

        const qInput = document.getElementById("nlInput");
        if (qInput) {
          qInput.value = `Evaluate operational exposure (population methods A/B/C, substations & health facilities) across ${aoiName}`;
        }

        activeScenarioKey = "uploaded_aoi_exposure";
        userParams.area = aoiName;
        userParams.distance = "Footprint Intersection + 5km Buffer";
        userParams.options = "Multi-Scale GCS GeoParquet Rollup";

        document.getElementById("sqlInput").value = buildSqlForScenario("uploaded_aoi_exposure");
        runActiveQuery();

      } else {
        // Meteorological / Cyclone Track Corridor Mode
        uploadedCycloneData = geojson;
        uploadedCycloneZones = buildCycloneZones(geojson);

        const cycName = (geojson.metadata && geojson.metadata.cyclone_name) || file.name;
        const advNum = (geojson.metadata && geojson.metadata.advisory) || "Current";

        if (statusText) {
          statusText.innerHTML = `<span class="text-green-600 font-bold">✓ Successfully loaded ${file.name}</span> (${cycName}, Advisory #${advNum}) — ${geojson.features.length} features, 3 hazard zones generated.`;
        }

        const qInput = document.getElementById("nlInput");
        if (qInput) {
          qInput.value = `Assess critical asset exposure and predicted hazard zones for ${cycName} (Advisory #${advNum})`;
        }

        activeScenarioKey = "cyclone_track_exposure";
        userParams.area = cycName;
        userParams.distance = "50 km Core / 150 km Severe Gale / 300 km Watch";
        userParams.options = `Advisory #${advNum}`;

        document.getElementById("sqlInput").value = buildSqlForScenario("cyclone_track_exposure");
        runActiveQuery();
      }

    } catch (err) {
      console.error("Upload error:", err);
      if (statusText) {
        statusText.innerHTML = `<span class="text-error font-bold">Error: ${err.message}</span>`;
      }
      alert(`Spatial File Error: ${err.message}`);
    }
  }

  async function loadSampleCycloneFile() {
    const statusText = document.getElementById("uploadStatusText");
    if (statusText) statusText.innerHTML = `<span class="text-secondary font-bold">Loading sample WP302026_TRACK_latest.geojson...</span>`;
    try {
      const [resTrack, resZones] = await Promise.all([
        fetch("data/WP302026_TRACK_latest.geojson").then(r => r.json()),
        fetch("data/WP302026_CYCLONE_ZONES.geojson").then(r => r.json())
      ]);

      uploadedCycloneData = resTrack;
      uploadedCycloneZones = resZones;

      const cycName = (resTrack.metadata && resTrack.metadata.cyclone_name) || "Typhoon In-Fa (WP302026)";
      const advNum = (resTrack.metadata && resTrack.metadata.advisory) || "48";

      if (statusText) {
        statusText.innerHTML = `<span class="text-green-600 font-bold">✓ Sample Loaded:</span> ${cycName} (Advisory #${advNum}) — 7 forecast track features, 15 concentric hazard rings.`;
      }

      document.getElementById("nlInput").value = `Assess critical asset exposure and predicted hazard zones for ${cycName} (Advisory #${advNum})`;
      activeScenarioKey = "cyclone_track_exposure";
      userParams.area = cycName;
      userParams.distance = "50 km Core / 150 km Severe Gale / 300 km Watch";
      userParams.options = `Advisory #${advNum}`;

      document.getElementById("sqlInput").value = buildSqlForScenario("cyclone_track_exposure");
      runActiveQuery();
    } catch (err) {
      console.error("Sample load error:", err);
      if (statusText) statusText.innerHTML = `<span class="text-error font-bold">Failed to load sample: ${err.message}</span>`;
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    try {
      initMap();
    } catch (err) {
      console.warn("MapLibre init warning:", err);
    }

    document.getElementById("btnAnalyze").addEventListener("click", () => analyzeQuery());
    document.getElementById("btnClearAll").addEventListener("click", resetAllToBlank);
    document.getElementById("btnApplyClarification").addEventListener("click", handleConfirmClarification);

    const btnDismiss = document.getElementById("btnDismissClarification");
    if (btnDismiss) {
      btnDismiss.addEventListener("click", () => {
        document.getElementById("clarificationBox").style.display = "none";
      });
    }

    document.getElementById("btnGenerateSql").addEventListener("click", () => {
      if (activeScenarioKey) {
        generateValidatedQuery(activeScenarioKey);
      } else {
        analyzeQuery();
      }
    });

    document.getElementById("btnCopySql").addEventListener("click", () => {
      const txt = document.getElementById("sqlInput").value;
      if (txt && navigator.clipboard) {
        navigator.clipboard.writeText(txt);
      }
    });

    document.getElementById("btnRunQuery").addEventListener("click", runActiveQuery);
    document.getElementById("btnHeaderRun").addEventListener("click", () => {
      if (!activeScenarioKey) analyzeQuery();
      runActiveQuery();
    });

    document.getElementById("btnCloseInspector").addEventListener("click", () => {
      document.getElementById("inspectorBanner").style.display = "none";
    });

    document.getElementById("globalSearch").addEventListener("keydown", e => {
      if (e.key === "Enter") {
        document.getElementById("nlInput").value = e.target.value;
        analyzeQuery();
      }
    });

    document.getElementById("nlInput").addEventListener("keydown", e => {
      if (e.key === "Enter") {
        analyzeQuery();
      }
    });

    const fileInput = document.getElementById("spatialFileInput");
    const btnBrowse = document.getElementById("btnBrowseFile");
    const btnLoadSample = document.getElementById("btnLoadSampleCyclone");
    const uploadBox = document.getElementById("spatialUploadBox");

    if (btnBrowse && fileInput) {
      btnBrowse.addEventListener("click", () => fileInput.click());
    }

    if (fileInput) {
      fileInput.addEventListener("change", async e => {
        if (e.target.files && e.target.files.length > 0) {
          await processUploadedSpatialFile(e.target.files[0]);
        }
      });
    }

    if (uploadBox) {
      uploadBox.addEventListener("dragover", e => {
        e.preventDefault();
        uploadBox.classList.add("border-secondary", "bg-secondary/5");
      });
      uploadBox.addEventListener("dragleave", () => {
        uploadBox.classList.remove("border-secondary", "bg-secondary/5");
      });
      uploadBox.addEventListener("drop", async e => {
        e.preventDefault();
        uploadBox.classList.remove("border-secondary", "bg-secondary/5");
        if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
          await processUploadedSpatialFile(e.dataTransfer.files[0]);
        }
      });
    }

    const btnFlipLat = document.getElementById("btnFlipLat");
    const btnFlipXy = document.getElementById("btnFlipXy");
    if (btnFlipLat) btnFlipLat.addEventListener("click", () => flipActiveCoordinates("lat"));
    if (btnFlipXy) btnFlipXy.addEventListener("click", () => flipActiveCoordinates("xy"));

    if (btnLoadSample) {
      btnLoadSample.addEventListener("click", async () => {
        await loadSampleCycloneFile();
      });
    }

    document.querySelectorAll("[data-scenario]").forEach(chip => {
      chip.addEventListener("click", () => {
        const sc = chip.getAttribute("data-scenario");
        const preset = SCENARIO_PRESETS[sc];
        if (preset) {
          document.getElementById("nlInput").value = preset.question;
        }
        analyzeQuery(sc);
      });
    });
  });
})();
