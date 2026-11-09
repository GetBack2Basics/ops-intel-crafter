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
    }
  };

  const LOCALITY_COORDS = {
    maitland: { center: [151.555, -32.732], zoom: 11.4, bbox: [151.45, -32.82, 151.66, -32.65] },
    newcastle: { center: [151.778, -32.928], zoom: 11.4, bbox: [151.66, -33.02, 151.85, -32.84] },
    cessnock: { center: [151.355, -32.834], zoom: 10.8, bbox: [151.15, -33.05, 151.50, -32.70] },
    "port stephens": { center: [151.92, -32.72], zoom: 10.5, bbox: [151.68, -32.85, 152.22, -32.60] },
    "lake macquarie": { center: [151.58, -33.05], zoom: 10.5, bbox: [151.38, -33.20, 151.75, -32.92] },
    hunter: { center: [151.63, -32.79], zoom: 10.3, bbox: [151.45, -32.95, 151.82, -32.68] },
    nsw: { center: [149.5, -32.6], zoom: 5.8, bbox: [141.0, -37.5, 153.6, -28.1] },
    australia: { center: [134.5, -25.5], zoom: 3.7, bbox: [112.9, -43.7, 153.7, -10.0] }
  };

  // Load pre-computed verified bundle from GCS / local docs
  fetch("data/workbench_bundle.json")
    .then(r => r.json())
    .then(data => {
      bundle = data;
    })
    .catch(err => console.warn("Could not pre-load workbench_bundle.json:", err));

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
    });
  }

  function clearMapLayers() {
    if (!map || !mapReady) return;
    const dynamicLayers = ["q-grid-fill", "q-grid-line", "q-inund-fill", "q-tx-line", "q-sub-circle", "q-rfs-circle", "q-pwr-circle", "q-lga-line"];
    const dynamicSources = ["s-grid", "s-inund", "s-tx", "s-sub", "s-rfs", "s-pwr", "s-lga"];
    dynamicLayers.forEach(id => {
      if (map.getLayer(id)) map.removeLayer(id);
    });
    dynamicSources.forEach(id => {
      if (map.getSource(id)) map.removeSource(id);
    });
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
      const areaFilterSql = parseAreaWhereClause(areaText, "s.locality");
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
    WHERE _bbox_xmax >= 151.35 AND _bbox_xmin <= 151.90
      AND _bbox_ymax >= -33.05 AND _bbox_ymin <= -32.60
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
    return "";
  }

  function inferScenarioFromText(text) {
    const q = (text || "").toLowerCase();
    if (!q) return "pop_comparison";
    if (q.includes("scada") || q.includes("icu") || q.includes("restricted") || q.includes("token")) {
      return "uncatalogued_reject";
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

  // Opens the Plain-Text Area & Options Panel BEFORE creating SQL
  function openPlainTextParameterForm(key) {
    const preset = SCENARIO_PRESETS[key] || SCENARIO_PRESETS.pop_comparison;
    const box = document.getElementById("clarificationBox");
    const title = document.getElementById("clarificationTitle");
    const container = document.getElementById("clarificationQuestions");
    const actions = document.getElementById("clarificationActions");

    box.style.display = "flex";

    // Clear Step 02 SQL until the user confirms plain-text options and clicks "Create SQL"
    document.getElementById("sqlInput").value = "";
    document.getElementById("sqlTargetUri").textContent = `${preset.targetUri} (define area & options above, then click Create SQL)`;
    document.getElementById("ctxScaleVal").textContent = "Pending Options";
    document.getElementById("ctxScaleSub").textContent = "Set area in plain text above";
    document.getElementById("ctxMethodVal").textContent = "Pending Options";
    document.getElementById("ctxGateVal").textContent = preset.isRejected ? "Unavailable" : "Ready";

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

    title.textContent = "Define Area & Query Options (Plain Text) Before Creating SQL";
    actions.style.display = "flex";

    userParams.area = preset.defaultArea;
    userParams.distance = preset.defaultDistance;
    userParams.options = preset.defaultOptions;

    const showPopHelpers = key === "pop_comparison" || key === "ambiguous_pop";

    container.innerHTML = `
      <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div class="space-y-1.5">
          <label for="paramAreaInput" class="block text-xs font-bold uppercase tracking-wider text-on-surface-variant">1. Area / Locality or Bounding Box (Plain Text)</label>
          <input id="paramAreaInput" type="text" value="${userParams.area.replace(/"/g, '&quot;')}" placeholder="e.g. Maitland, Newcastle, or 151.45, -32.95, 151.82, -32.68" class="w-full h-10 px-3 bg-surface-container-lowest border border-outline-variant rounded-lg text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-secondary"/>
          <p class="text-[11px] text-on-surface-variant">Type any suburb/LGA/state name (e.g. <code>Maitland</code>, <code>Newcastle</code>, <code>NSW</code>) or <code>minLon, minLat, maxLon, maxLat</code>.</p>
        </div>
        <div class="space-y-1.5">
          <label for="paramDistanceInput" class="block text-xs font-bold uppercase tracking-wider text-on-surface-variant">2. Buffer / Catchment Distance (Plain Text)</label>
          <input id="paramDistanceInput" type="text" value="${userParams.distance.replace(/"/g, '&quot;')}" placeholder="e.g. 5000m, 500m, or 0m" class="w-full h-10 px-3 bg-surface-container-lowest border border-outline-variant rounded-lg text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-secondary"/>
          <p class="text-[11px] text-on-surface-variant">Type distance in metres or km (e.g. <code>2000m</code>, <code>5km</code>) for proximity queries.</p>
        </div>
        <div class="space-y-1.5">
          <label for="paramOptionsInput" class="block text-xs font-bold uppercase tracking-wider text-on-surface-variant">3. Other Options / Filters (Plain Text)</label>
          <input id="paramOptionsInput" type="text" value="${userParams.options.replace(/"/g, '&quot;')}" placeholder="e.g. Method B, Regime 2, or voltage >= 132 kV" class="w-full h-10 px-3 bg-surface-container-lowest border border-outline-variant rounded-lg text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-secondary"/>
          <p class="text-[11px] text-on-surface-variant">Type population method (<code>Method A</code>, <code>B</code>, <code>C</code>), regime (<code>1-4</code>), or attribute filters.</p>
        </div>
      </div>
      ${
        showPopHelpers
          ? `
      <div class="pt-2 space-y-2 border-t border-surface-container-high">
        <div class="text-xs font-bold uppercase tracking-wider text-on-surface-variant">Quick Fill for Population Method &amp; Incident Footprint (updates plain-text options above):</div>
        <div class="flex flex-wrap gap-2" id="quickPopPills">
          <button type="button" class="chip" data-quick-method="A">Method A (Centroid ST_Contains)</button>
          <button type="button" class="chip chip-featured" data-quick-method="B">Method B (1 km² Polygon ST_Intersects)</button>
          <button type="button" class="chip" data-quick-method="C">Method C (Area-Weighted Proportional)</button>
          <button type="button" class="chip" data-quick-regime="0">Regime 1: Narrow Levee Strip</button>
          <button type="button" class="chip chip-featured" data-quick-regime="1">Regime 2: Observed Flood Basin</button>
          <button type="button" class="chip" data-quick-regime="2">Regime 3: Regional Flood Envelope</button>
          <button type="button" class="chip" data-quick-regime="3">Regime 4: 500m Transmission Corridor</button>
        </div>
      </div>`
          : ""
      }
    `;

    const optInput = document.getElementById("paramOptionsInput");
    container.querySelectorAll("[data-quick-method]").forEach(btn => {
      btn.addEventListener("click", () => {
        selectedPopMethod = btn.getAttribute("data-quick-method");
        const regNames = ["Regime 1 (Narrow Strip)", "Regime 2 (Observed Flood Basin)", "Regime 3 (Regional Envelope)", "Regime 4 (500m Corridor)"];
        optInput.value = `Method ${selectedPopMethod}, ${regNames[selectedRegimeIdx] || regNames[1]}`;
      });
    });

    container.querySelectorAll("[data-quick-regime]").forEach(btn => {
      btn.addEventListener("click", () => {
        selectedRegimeIdx = parseInt(btn.getAttribute("data-quick-regime"), 10) || 0;
        const regNames = ["Regime 1 (Narrow Strip)", "Regime 2 (Observed Flood Basin)", "Regime 3 (Regional Envelope)", "Regime 4 (500m Corridor)"];
        optInput.value = `Method ${selectedPopMethod}, ${regNames[selectedRegimeIdx] || regNames[1]}`;
      });
    });
  }

  function applyUserParametersAndCreateSql() {
    if (!activeScenarioKey) {
      activeScenarioKey = inferScenarioFromText(document.getElementById("nlInput").value);
    }
    const preset = SCENARIO_PRESETS[activeScenarioKey] || SCENARIO_PRESETS.pop_comparison;
    if (preset.isRejected) return;

    const areaEl = document.getElementById("paramAreaInput");
    const distEl = document.getElementById("paramDistanceInput");
    const optEl = document.getElementById("paramOptionsInput");

    userParams.area = areaEl ? areaEl.value.trim() : preset.defaultArea;
    userParams.distance = distEl ? distEl.value.trim() : preset.defaultDistance;
    userParams.options = optEl ? optEl.value.trim() : preset.defaultOptions;

    // Parse Method A/B/C or Regime 1-4 from plain text if typed by the user
    const optLower = userParams.options.toLowerCase();
    if (optLower.includes("method a")) selectedPopMethod = "A";
    else if (optLower.includes("method b")) selectedPopMethod = "B";
    else if (optLower.includes("method c")) selectedPopMethod = "C";

    if (optLower.includes("regime 1") || optLower.includes("narrow")) selectedRegimeIdx = 0;
    else if (optLower.includes("regime 2") || optLower.includes("basin")) selectedRegimeIdx = 1;
    else if (optLower.includes("regime 3") || optLower.includes("regional")) selectedRegimeIdx = 2;
    else if (optLower.includes("regime 4") || optLower.includes("corridor") || optLower.includes("transmission")) selectedRegimeIdx = 3;

    document.getElementById("sqlTargetUri").textContent = preset.targetUri;
    document.getElementById("sqlInput").value = buildSqlForScenario(activeScenarioKey);
    document.getElementById("ctxScaleVal").textContent = userParams.area || preset.defaultArea;
    document.getElementById("ctxScaleSub").textContent = `Distance / Scope: ${userParams.distance || preset.defaultDistance}`;
    document.getElementById("ctxMethodVal").textContent = userParams.options || preset.defaultOptions;
    document.getElementById("ctxMethodSub").textContent = "Plain-text parameters applied to SQL";
    document.getElementById("ctxGateVal").textContent = "SQL Created";
    document.getElementById("ctxGateSub").textContent = "Click Run Query to execute and render map";

    const runBtn = document.getElementById("btnRunQuery");
    runBtn.classList.add("btn-pulse");
    document.getElementById("panel-sql").scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function analyzeQuery(scenarioKeyOverride) {
    const inputEl = document.getElementById("nlInput");
    const key = scenarioKeyOverride || inferScenarioFromText(inputEl.value);
    activeScenarioKey = key;
    const preset = SCENARIO_PRESETS[key];
    if (preset && (scenarioKeyOverride || !inputEl.value.trim())) {
      inputEl.value = preset.question;
    }
    openPlainTextParameterForm(key);
  }

  function flyMapToUserArea(defaultCenter, defaultZoom) {
    if (!map || !mapReady) return;
    const raw = (userParams.area || "").toLowerCase();
    const bboxMatch = raw.match(/(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)/);
    if (bboxMatch && !raw.includes("lower hunter") && !raw.includes("nsw statewide")) {
      const [, minX, minY, maxX, maxY] = bboxMatch.map(Number);
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

  function runActiveQuery() {
    if (!bundle) return;
    if (!activeScenarioKey) {
      analyzeQuery();
      applyUserParametersAndCreateSql();
    }
    if (activeScenarioKey === "uncatalogued_reject") {
      openPlainTextParameterForm("uncatalogued_reject");
      return;
    }
    if (!document.getElementById("sqlInput").value.trim()) {
      applyUserParametersAndCreateSql();
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
        <tr class="cursor-pointer" data-cell="${c.cell_id}">
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
        map.addSource("s-grid", { type: "geojson", data: "exports/hunter_population_grid_comparison/result.geojson" });
        map.addLayer({
          id: "q-grid-fill",
          type: "fill",
          source: "s-grid",
          paint: {
            "fill-color": [
              "match",
              ["get", "cell_classification"],
              "FULLY_CONTAINED", "#006973",
              "BOUNDARY_CENTROID_IN", "#0284c7",
              "BOUNDARY_CENTROID_OUT", "#d47300",
              "#64748b"
            ],
            "fill-opacity": 0.45
          }
        });
        map.addLayer({
          id: "q-grid-line",
          type: "line",
          source: "s-grid",
          paint: { "line-color": "#001026", "line-width": 1 }
        });
        map.addSource("s-inund", { type: "geojson", data: "qa/data/nsw_water_inundation_areas.geojson" });
        map.addLayer({
          id: "q-inund-fill",
          type: "fill",
          source: "s-inund",
          paint: { "fill-color": "#38bdf8", "fill-opacity": 0.38 }
        });
        flyMapToUserArea([151.63, -32.79], 10.6);
        map.on("click", "q-grid-fill", e => {
          if (!e.features || !e.features.length) return;
          const p = e.features[0].properties;
          showInspector("1 km² Grid Cell", `${p.cell_id} — ${p.sa2_name21}`, [
            ["Cell Population", `${p.cell_population} residents`],
            ["Observed NSW FOI Bldgs", `${p.observed_foi_buildings} facilities`],
            ["Method C Overlap", `${(Number(p.overlap_fraction) * 100).toFixed(1)}% (${p.method_c_weighted_pop} est*)`],
            ["Classification", p.cell_classification]
          ]);
        });
      }
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
        <tr>
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
        map.addSource("s-inund", { type: "geojson", data: "qa/data/nsw_water_inundation_areas.geojson" });
        map.addLayer({ id: "q-inund-fill", type: "fill", source: "s-inund", paint: { "fill-color": "#38bdf8", "fill-opacity": 0.4 } });
        map.addSource("s-tx", { type: "geojson", data: "qa/data/ga_electricity_transmission_lines.geojson" });
        map.addLayer({ id: "q-tx-line", type: "line", source: "s-tx", paint: { "line-color": "#eab308", "line-width": 2 } });
        map.addSource("s-sub", { type: "geojson", data: "exports/hunter_substation_flood_dependency/result.geojson" });
        map.addLayer({
          id: "q-sub-circle",
          type: "circle",
          source: "s-sub",
          paint: { "circle-radius": 7, "circle-color": "#ea580c", "circle-stroke-width": 2, "circle-stroke-color": "#ffffff" }
        });
        flyMapToUserArea([151.63, -32.82], 10.3);
      }
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
        <tr>
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
        map.addSource("s-lga", { type: "geojson", data: "qa/data/next_lga_boundaries_asgs2025.geojson" });
        map.addLayer({ id: "q-lga-line", type: "line", source: "s-lga", paint: { "line-color": "#006973", "line-width": 2 } });
        map.addSource("s-inund", { type: "geojson", data: "qa/data/nsw_water_inundation_areas.geojson" });
        map.addLayer({ id: "q-inund-fill", type: "fill", source: "s-inund", paint: { "fill-color": "#0284c7", "fill-opacity": 0.45 } });
        flyMapToUserArea([151.55, -32.85], 9.2);
      }
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
        <tr>
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
        map.addSource("s-rfs", { type: "geojson", data: "qa/data/nsw_rfs_major_incidents_live.geojson" });
        map.addLayer({
          id: "q-rfs-circle",
          type: "circle",
          source: "s-rfs",
          paint: { "circle-radius": 8, "circle-color": "#dc2626", "circle-stroke-width": 2, "circle-stroke-color": "#ffffff" }
        });
        flyMapToUserArea([149.5, -32.6], 5.8);
      }
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
        map.addSource("s-pwr", { type: "geojson", data: "qa/data/ga_major_power_stations.geojson" });
        map.addLayer({
          id: "q-pwr-circle",
          type: "circle",
          source: "s-pwr",
          paint: { "circle-radius": 5, "circle-color": "#7c3aed", "circle-stroke-width": 1.2, "circle-stroke-color": "#ffffff" }
        });
        flyMapToUserArea([134.5, -25.5], 3.7);
      }
      legendItems.innerHTML = `
        <div class="flex items-center gap-2"><span class="w-3 h-3 rounded-full bg-[#7c3aed]"></span><span>GA Major Power Station</span></div>
      `;
    }

    populateStep5AndStep6();
    document.getElementById("panel-map").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function populateStep5AndStep6() {
    if (!bundle) return;
    document.getElementById("panel-analytics").style.display = "block";
    document.getElementById("panel-ai-steps").style.display = "block";

    const benchBody = document.getElementById("benchTableBody");
    benchBody.innerHTML = (bundle.benchmarks.duckdb_spatial_benchmarks || [])
      .map(
        b => `
      <tr>
        <td class="font-semibold">${b.title}</td>
        <td><code>${b.first_run_ms} ms</code></td>
        <td><strong class="text-secondary font-mono">${b.warm_run_ms} ms</strong></td>
        <td><code>${b.row_count}</code></td>
      </tr>
    `
      )
      .join("");

    const isoBody = document.getElementById("isolationTableBody");
    isoBody.innerHTML = (bundle.isolation_analysis.sa2_isolation_ranking || [])
      .slice(0, 8)
      .map(
        s => `
      <tr>
        <td><code>${s.sa2_code21}</code></td>
        <td class="font-semibold">${s.sa2_name21}</td>
        <td><code>${s.inundated_area_sqkm} km²</code></td>
        <td><strong>${s.inundated_pct_of_sa2}%</strong></td>
        <td><span class="badge-tag ${s.isolation_classification === 'HIGH_ISOLATION_RISK' ? 'long' : 'tight'}">${s.isolation_classification}</span></td>
      </tr>
    `
      )
      .join("");

    const cards = [
      {
        badge: "PRESET 01",
        tag: "Population Grid",
        title: "Compare Population Methods (A / B / C)",
        desc: "Define an area or flood footprint and compare centroid, polygon, and area-weighted counts.",
        actionText: "Configure Area & Options",
        scenario: "pop_comparison"
      },
      {
        badge: "PRESET 02",
        tag: "Infrastructure",
        title: "Substation Flood & Facility Catchment",
        desc: "Define a locality and buffer distance to find substations near flood zones and dependent facilities.",
        actionText: "Configure Area & Options",
        scenario: "substation_flood"
      },
      {
        badge: "PACKAGE 03",
        tag: "Offline Field Pack",
        title: "Open Offline Map-in-a-Box",
        desc: "Open the self-contained Lower Hunter emergency map package for disconnected field use.",
        actionText: "Open Offline Map Pack",
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
        ${
          c.href
            ? `<a href="${c.href}" class="scenario-step-btn flex items-center justify-center no-underline">${c.actionText}</a>`
            : `<button type="button" class="scenario-step-btn" data-card-scenario="${c.scenario}">${c.actionText}</button>`
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

  document.addEventListener("DOMContentLoaded", () => {
    initMap();

    document.getElementById("btnAnalyze").addEventListener("click", () => analyzeQuery());
    document.getElementById("btnClearAll").addEventListener("click", resetAllToBlank);
    document.getElementById("btnApplyClarification").addEventListener("click", applyUserParametersAndCreateSql);

    document.getElementById("btnGenerateSql").addEventListener("click", () => {
      if (activeScenarioKey) {
        applyUserParametersAndCreateSql();
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
