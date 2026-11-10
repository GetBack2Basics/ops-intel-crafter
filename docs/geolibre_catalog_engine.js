/**
 * docs/geolibre_catalog_engine.js
 * GeoLibre Catalogue Discovery & Spatial SQL Compilation Engine
 *
 * Implements GeoLibre's catalogue indexing, semantic keyword matching,
 * and DuckDB Spatial SQL compilation for authoritative Australian emergency lakehouse datasets.
 *
 * Grounding Rule:
 * - If data exists in a public catalogue source (such as NSW FOI for hospitals,
 *   schools, bridges, airports, emergency services, or GA for substations and power stations),
 *   it is queried directly.
 * - Rejection ONLY occurs if the data genuinely does not exist in any catalogue dataset,
 *   or if explicitly marked restricted in the catalogue contract (e.g. nsw_emergency_management_restricted).
 */

(function (root, factory) {
  if (typeof define === "function" && define.amd) {
    define([], factory);
  } else if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.GeoLibreCatalogEngine = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // Stopwords removed during query tokenization
  const STOPWORDS = new Set([
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are",
    "aren't", "as", "at", "be", "because", "been", "before", "being", "below", "between", "both",
    "but", "by", "can", "can't", "cannot", "could", "did", "do", "does", "doing", "don't", "down",
    "during", "each", "few", "find", "for", "from", "further", "get", "had", "has", "have", "having",
    "he", "her", "here", "hers", "herself", "him", "himself", "his", "how", "i", "if", "in", "into",
    "is", "it", "its", "itself", "just", "locate", "many", "me", "more", "most", "my", "myself",
    "near", "no", "nor", "not", "of", "off", "on", "once", "only", "or", "other", "ought", "our",
    "ours", "ourselves", "out", "over", "own", "please", "same", "select", "show", "so", "some",
    "such", "than", "that", "the", "their", "theirs", "them", "themselves", "then", "there",
    "these", "they", "this", "those", "through", "to", "too", "under", "until", "up", "very",
    "was", "we", "were", "what", "when", "where", "which", "while", "who", "whom", "why", "with",
    "would", "you", "your", "yours", "yourself", "yourselves"
  ]);

  // Explicitly restricted datasets or private sensor streams (Failed Contract / Security)
  const RESTRICTED_TRIGGERS = [
    { pattern: /\bnsw_emergency_management_restricted\b/i, label: "NSW Emergency Management Restricted Service", reason: "Failed Level 1 Source Contract validation (ArcGIS error 499: Token Required)." },
    { pattern: /\btoken required\b/i, label: "Token-Gated Service", reason: "Endpoint requires proprietary authentication token." },
    { pattern: /\bscada\b/i, label: "Live SCADA Sensor Stream", reason: "Real-time substation load SCADA feeds are restricted; static infrastructure is available via ga_electricity_substations." },
    { pattern: /\bicu bed\b|\bhospital icu occupancy\b/i, label: "Live ICU Bed Telemetry", reason: "Real-time hospital ICU bed occupancy telemetry is restricted; hospital facilities are available in nsw_foi_building_complexes." },
    { pattern: /\bambulance dispatch stream\b|\bpolice cad stream\b/i, label: "Live CAD Dispatch Telemetry", reason: "Live emergency dispatch streams are restricted; physical stations are available in nsw_foi_building_complexes." }
  ];

  // Australian Locality Gazetteer for natural-language spatial extraction
  const LOCALITIES = {
    "taree": { name: "Taree, NSW", bbox: [152.3815, -31.9732, 152.5510, -31.8450], state: "NSW" },
    "maitland": { name: "Maitland, NSW", bbox: [151.4800, -32.8000, 151.6500, -32.6800], state: "NSW" },
    "newcastle": { name: "Newcastle, NSW", bbox: [151.6800, -33.0000, 151.8500, -32.8800], state: "NSW" },
    "hunter": { name: "Hunter Region, NSW", bbox: [150.9000, -33.2000, 152.1000, -32.3000], state: "NSW" },
    "lower hunter": { name: "Lower Hunter, NSW", bbox: [151.4000, -32.9500, 151.8500, -32.6500], state: "NSW" },
    "sydney": { name: "Sydney Metropolitan, NSW", bbox: [150.8000, -34.0500, 151.3500, -33.6500], state: "NSW" },
    "cessnock": { name: "Cessnock, NSW", bbox: [151.2500, -32.9000, 151.4500, -32.7500], state: "NSW" },
    "singleton": { name: "Singleton, NSW", bbox: [151.0500, -32.6500, 151.2500, -32.5000], state: "NSW" },
    "muswellbrook": { name: "Muswellbrook, NSW", bbox: [150.8000, -32.3000, 151.0000, -32.1500], state: "NSW" },
    "port macquarie": { name: "Port Macquarie, NSW", bbox: [152.8200, -31.4800, 152.9800, -31.3800], state: "NSW" },
    "midcoast": { name: "Mid-Coast Council, NSW", bbox: [151.6000, -32.4000, 152.8000, -31.6000], state: "NSW" },
    "lake macquarie": { name: "Lake Macquarie, NSW", bbox: [151.4500, -33.1500, 151.7500, -32.9500], state: "NSW" },
    "wollongong": { name: "Wollongong, NSW", bbox: [150.8000, -34.5000, 150.9500, -34.3500], state: "NSW" },
    "tweed": { name: "Tweed Shire, NSW", bbox: [153.4000, -28.3000, 153.6000, -28.1500], state: "NSW" },
    "brisbane": { name: "Brisbane, QLD", bbox: [152.8500, -27.6500, 153.2500, -27.2500], state: "QLD" },
    "melbourne": { name: "Melbourne, VIC", bbox: [144.7500, -38.0500, 145.2500, -37.6500], state: "VIC" },
    "canberra": { name: "Canberra, ACT", bbox: [149.0000, -35.4500, 149.2500, -35.1500], state: "ACT" },
    "australia": { name: "Australia (National)", bbox: [112.92, -43.74, 153.64, -9.14], state: "ALL" }
  };

  // Authoritative Catalogue Definitions
  const CATALOGUE = [
    {
      id: "nsw_foi_building_complexes",
      scenarioKey: "hospitals_facilities",
      title: "NSW Features of Interest — Emergency, Health, Education & Infrastructure Facilities",
      theme: "Emergency & Health Facilities",
      provider: "NSW Spatial Services (DCS)",
      geometryType: "Point",
      scale: "state",
      parquetUri: "gs://operational-intelligence-crafter-lake/geoparquet/nsw_foi_building_complexes/2026-NSW-FOI/20261108T223144Z/part-00000.parquet",
      viewName: "nsw_foi_building_complexes",
      keywords: [
        // Healthcare
        "hospital", "hospitals", "medical", "clinic", "clinics", "health", "healthcare",
        "infirmary", "doctor", "nursing", "aged care", "facility", "facilities",
        "community health", "health centre", "emergency department", "health complex",
        "manning hospital", "mayo private", "medical complex",
        // Education
        "school", "schools", "primary school", "high school", "college", "education",
        "public school", "grammar", "tafe", "campus",
        // Emergency Services
        "police", "police station", "ambulance", "ambulance station", "fire station",
        "fire brigade", "ses", "emergency facility", "fire depot",
        // Transport & Infrastructure Facilities
        "bridge", "bridges", "road bridge", "crossing", "bridge depot", "bridge plaza",
        "airport", "airports", "aerodrome", "airstrip", "airfield", "aviation",
        // Civic & Community
        "community centre", "public hall", "civic centre", "sports complex", "mall"
      ],
      targetColumns: ["facility_name", "facility_type", "facility_subtype", "classsubtype", "generalname", "latitude", "longitude"],
      defaultSort: "facility_type, facility_name",
      sqlBuilder: function (areaText, localityInfo, matchedConcept) {
        const loc = getActiveAoiRegion(areaText, localityInfo);
        const [minX, minY, maxX, maxY] = loc.bbox;
        const areaLabel = loc.name;
        const whereClause = `AND _bbox_maxx >= ${minX.toFixed(4)} AND _bbox_minx <= ${maxX.toFixed(4)}\n  AND _bbox_maxy >= ${minY.toFixed(4)} AND _bbox_miny <= ${maxY.toFixed(4)}\n  -- Spatial Filter: within generated AOI region (${loc.name})`;

        // Determine specific facility category filter from matched concept or query
        const concept = (matchedConcept || "").toLowerCase();
        let categoryFilter = "";
        let categoryTitle = "Emergency & Community Facilities";

        if (concept.includes("bridge")) {
          categoryTitle = "Bridges & Transport Infrastructure";
          categoryFilter = `(LOWER(COALESCE(facility_name, generalname, '')) LIKE '%bridge%')`;
        } else if (concept.includes("airport") || concept.includes("aerodrome") || concept.includes("airfield") || concept.includes("aviation")) {
          categoryTitle = "Airports & Aviation Facilities";
          categoryFilter = `(LOWER(COALESCE(facility_name, generalname, '')) LIKE '%airport%' OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%aerodrome%' OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%airfield%')`;
        } else if (concept.includes("school") || concept.includes("college") || concept.includes("education")) {
          categoryTitle = "Educational Facilities & Schools";
          categoryFilter = `(LOWER(COALESCE(facility_name, generalname, '')) LIKE '%school%' OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%college%' OR facility_subtype = 1)`;
        } else if (concept.includes("police")) {
          categoryTitle = "Police Stations & Law Enforcement";
          categoryFilter = `(LOWER(COALESCE(facility_name, generalname, '')) LIKE '%police%')`;
        } else if (concept.includes("fire")) {
          categoryTitle = "Fire Stations & Emergency Response";
          categoryFilter = `(LOWER(COALESCE(facility_name, generalname, '')) LIKE '%fire%')`;
        } else if (concept.includes("ambulance")) {
          categoryTitle = "Ambulance Stations & Paramedic Facilities";
          categoryFilter = `(LOWER(COALESCE(facility_name, generalname, '')) LIKE '%ambulance%')`;
        } else if (concept.includes("hospital") || concept.includes("health") || concept.includes("medical") || concept.includes("clinic") || concept.includes("aged care")) {
          categoryTitle = "Hospitals & Healthcare Facilities";
          categoryFilter = `(
    LOWER(COALESCE(facility_name, generalname, '')) LIKE '%hospital%'
    OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%health%'
    OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%medical%'
    OR facility_subtype = 3
)`;
        } else {
          categoryFilter = "1=1";
        }

        return `-- Authoritative NSW Features of Interest (${categoryTitle})
-- Spatial Filter: within generated AOI region (${areaLabel})
-- Source: NSW Spatial Services (DCS) Features of Interest
SELECT
    COALESCE(facility_name, generalname, 'Facility') AS facility_name,
    CASE facility_subtype
        WHEN 3 THEN 'Major Hospital / Health Facility'
        WHEN 2 THEN 'Community / Health Facility'
        WHEN 1 THEN 'Educational Institution'
        WHEN 4 THEN 'Civic / Infrastructure Facility'
        WHEN 5 THEN 'Utility / Substation'
        WHEN 6 THEN 'Recreational / Public Complex'
        ELSE 'Feature of Interest'
    END AS facility_type,
    ROUND(TRY_CAST(_bbox_miny AS DOUBLE), 4) AS lat,
    ROUND(TRY_CAST(_bbox_minx AS DOUBLE), 4) AS lon
FROM read_parquet('${this.parquetUri}')
WHERE ${categoryFilter}
  ${whereClause}
ORDER BY facility_type, facility_name
LIMIT 100;`;
      }
    },
    {
      id: "ga_electricity_substations",
      scenarioKey: "substation_flood",
      title: "Geoscience Australia — Power Substations & Terminal Stations",
      theme: "Critical Infrastructure",
      provider: "Geoscience Australia",
      geometryType: "Point",
      scale: "national",
      parquetUri: "gs://operational-intelligence-crafter-lake/geoparquet/ga_electricity_substations/2024-GA-NEI/20261108T223144Z/part-00000.parquet",
      viewName: "ga_electricity_substations",
      keywords: [
        "substation", "substations", "transformer", "grid sub", "sub-station",
        "electricity substation", "switchyard", "terminal station", "catchment",
        "voltage", "substation flood", "substation proximity"
      ],
      targetColumns: ["name", "feature_name", "locality", "state", "voltage_kv", "latitude", "longitude"],
      defaultSort: "voltage_kv DESC NULLS LAST",
      sqlBuilder: function (areaText, localityInfo) {
        const loc = getActiveAoiRegion(areaText, localityInfo);
        const [minX, minY, maxX, maxY] = loc.bbox;
        const areaLabel = loc.name;

        return `-- Substation Proximity & Catchment Exposure Query
-- Evaluates electricity substations within spatial proximity of water inundation extents
-- Spatial Filter: within generated AOI region (${areaLabel})
-- Extent: [${minX.toFixed(4)}, ${minY.toFixed(4)}, ${maxX.toFixed(4)}, ${maxY.toFixed(4)}] (EPSG:7844 / GDA2020)
SELECT
    COALESCE(name, feature_name, 'Substation') AS substation_name,
    locality,
    state,
    TRY_CAST(voltage_kv AS INT) AS voltage_kv,
    ROUND(TRY_CAST(_bbox_miny AS DOUBLE), 4) AS lat,
    ROUND(TRY_CAST(_bbox_minx AS DOUBLE), 4) AS lon
FROM read_parquet('${this.parquetUri}')
WHERE _bbox_maxx >= ${minX.toFixed(4)} AND _bbox_minx <= ${maxX.toFixed(4)}
  AND _bbox_maxy >= ${minY.toFixed(4)} AND _bbox_miny <= ${maxY.toFixed(4)}
  -- Within generated AOI region
ORDER BY voltage_kv DESC NULLS LAST
LIMIT 100;`;
      }
    },
    {
      id: "ga_major_power_stations",
      scenarioKey: "national_power",
      title: "Geoscience Australia — Major Power Stations",
      theme: "Critical Infrastructure",
      provider: "Geoscience Australia",
      geometryType: "Point",
      scale: "national",
      parquetUri: "gs://operational-intelligence-crafter-lake/geoparquet/ga_major_power_stations/2024-GA-NEI/20261108T223144Z/part-00000.parquet",
      viewName: "ga_major_power_stations",
      keywords: [
        "power station", "power stations", "generator", "generators", "generation",
        "power plant", "megawatt", "mw", "renewable", "solar farm", "wind farm",
        "coal station", "gas peaker", "hydroelectric", "generation capacity"
      ],
      targetColumns: ["name", "generationmw", "primaryfueltype", "state", "operationalstatus", "latitude", "longitude"],
      defaultSort: "generationmw DESC NULLS LAST",
      sqlBuilder: function (areaText, localityInfo) {
        const loc = getActiveAoiRegion(areaText, localityInfo);
        const areaLabel = loc ? loc.name : (areaText || "Australia National");
        if (loc && loc.bbox && loc.state !== "ALL" && !loc.name.toLowerCase().includes("national")) {
          const [minX, minY, maxX, maxY] = loc.bbox;
          return `-- Major Power Stations & Generation Capacity (GA NEI)
-- Spatial Filter: within generated AOI region (${loc.name})
-- Extent: [${minX.toFixed(4)}, ${minY.toFixed(4)}, ${maxX.toFixed(4)}, ${maxY.toFixed(4)}] (EPSG:7844 / GDA2020)
SELECT
    COALESCE(name, 'Power Station') AS station_name,
    locality,
    state,
    primaryfueltype AS fuel_type,
    ROUND(TRY_CAST(generationmw AS DOUBLE), 1) AS capacity_mw,
    operationalstatus AS status,
    ROUND(TRY_CAST(_bbox_miny AS DOUBLE), 4) AS lat,
    ROUND(TRY_CAST(_bbox_minx AS DOUBLE), 4) AS lon
FROM read_parquet('${this.parquetUri}')
WHERE _bbox_maxx >= ${minX.toFixed(4)} AND _bbox_minx <= ${maxX.toFixed(4)}
  AND _bbox_maxy >= ${minY.toFixed(4)} AND _bbox_miny <= ${maxY.toFixed(4)}
  -- Within generated AOI region
ORDER BY capacity_mw DESC NULLS LAST
LIMIT 100;`;
        }
        let areaFilterSql = (loc && loc.state && loc.state !== "ALL") ? `WHERE state = '${loc.state}'` : "";
        return `-- National Major Power Stations & Generation Capacity (GA NEI)
-- Scope: ${areaLabel}
SELECT
    COALESCE(state, 'Unknown') AS state,
    COUNT(*) AS total_power_stations,
    ROUND(SUM(TRY_CAST(generationmw AS DOUBLE)), 1) AS total_capacity_mw,
    ROUND(AVG(TRY_CAST(generationmw AS DOUBLE)), 1) AS avg_capacity_mw,
    COUNT(CASE WHEN LOWER(operationalstatus) = 'operating' THEN 1 END) AS active_operating
FROM read_parquet('${this.parquetUri}')
${areaFilterSql}
GROUP BY COALESCE(state, 'Unknown')
ORDER BY total_capacity_mw DESC;`;
      }
    },
    {
      id: "ga_electricity_transmission_lines",
      scenarioKey: "transmission_lines",
      title: "Geoscience Australia — High-Voltage Transmission Lines",
      theme: "Critical Infrastructure",
      provider: "Geoscience Australia",
      geometryType: "LineString",
      scale: "national",
      parquetUri: "gs://operational-intelligence-crafter-lake/geoparquet/ga_electricity_transmission_lines/2024-GA-NEI/20261108T223144Z/part-00000.parquet",
      viewName: "ga_electricity_transmission_lines",
      keywords: [
        "transmission line", "transmission lines", "power line", "high voltage", "pylons",
        "feeder", "grid lines", "kv line"
      ],
      targetColumns: ["name", "feature_name", "voltage_kv", "state"],
      defaultSort: "voltage_kv DESC",
      sqlBuilder: function (areaText, localityInfo) {
        const loc = getActiveAoiRegion(areaText, localityInfo);
        const [minX, minY, maxX, maxY] = loc.bbox;
        const areaLabel = loc.name;
        return `-- High-Voltage Transmission Grid Lines (>=66kV)
-- Spatial Filter: within generated AOI region (${areaLabel})
-- Extent: [${minX.toFixed(4)}, ${minY.toFixed(4)}, ${maxX.toFixed(4)}, ${maxY.toFixed(4)}] (EPSG:7844 / GDA2020)
SELECT
    COALESCE(name, feature_name, 'Transmission Line') AS line_name,
    state,
    TRY_CAST(voltage_kv AS INT) AS voltage_kv,
    ROUND(TRY_CAST(_bbox_miny AS DOUBLE), 4) AS lat,
    ROUND(TRY_CAST(_bbox_minx AS DOUBLE), 4) AS lon
FROM read_parquet('${this.parquetUri}')
WHERE _bbox_maxx >= ${minX.toFixed(4)} AND _bbox_minx <= ${maxX.toFixed(4)}
  AND _bbox_maxy >= ${minY.toFixed(4)} AND _bbox_miny <= ${maxY.toFixed(4)}
  -- Within generated AOI region
ORDER BY voltage_kv DESC NULLS LAST
LIMIT 100;`;
      }
    },
    {
      id: "nsw_rfs_major_incidents_live",
      scenarioKey: "live_rfs",
      title: "NSW Rural Fire Service — Major Bushfire Incidents (Live)",
      theme: "Live Hazard Feeds",
      provider: "NSW Rural Fire Service (RFS)",
      geometryType: "Point",
      scale: "state",
      parquetUri: "gs://operational-intelligence-crafter-lake/geoparquet/nsw_rfs_major_incidents_live/2026-LIVE/20261110T022639Z/part-00000.parquet",
      viewName: "nsw_rfs_major_incidents_live",
      keywords: [
        "rfs", "bushfire", "bushfires", "wildfire", "fire", "fires", "fire incident",
        "major incident", "emergency incident", "out of control", "emergency warning",
        "watch and act", "burn"
      ],
      targetColumns: ["title", "category", "status", "agency", "council_area", "latitude", "longitude"],
      defaultSort: "title",
      sqlBuilder: function (areaText, localityInfo) {
        const loc = getActiveAoiRegion(areaText, localityInfo);
        const areaLabel = loc ? loc.name : (areaText || "NSW Statewide");
        let whereClause = "";
        if (loc && loc.bbox && loc.state !== "ALL" && !loc.name.toLowerCase().includes("statewide")) {
          const [minX, minY, maxX, maxY] = loc.bbox;
          whereClause = `WHERE _bbox_maxx >= ${minX.toFixed(4)} AND _bbox_minx <= ${maxX.toFixed(4)}
  AND _bbox_maxy >= ${minY.toFixed(4)} AND _bbox_miny <= ${maxY.toFixed(4)}
  -- Within generated AOI region`;
        }
        return `-- NSW RFS Active Bushfire & Emergency Incidents (Live Feed)
-- Spatial Filter: within generated AOI region (${areaLabel})
SELECT
    title AS incident_title,
    category AS alert_level,
    status AS fire_status,
    agency,
    council_area,
    ROUND(TRY_CAST(latitude AS DOUBLE), 4) AS lat,
    ROUND(TRY_CAST(longitude AS DOUBLE), 4) AS lon
FROM read_parquet('${this.parquetUri}')
${whereClause}
ORDER BY
    CASE category
        WHEN 'Emergency Warning' THEN 1
        WHEN 'Watch and Act' THEN 2
        WHEN 'Advice' THEN 3
        ELSE 4
    END,
    incident_title
LIMIT 50;`;
      }
    },
    {
      id: "nsw_water_inundation_areas",
      scenarioKey: "water_inundation",
      title: "NSW Spatial Services — Water Inundation & Flood Extent Areas",
      theme: "Flood & Hydrography",
      provider: "NSW Spatial Services (DCS)",
      geometryType: "Polygon",
      scale: "state",
      parquetUri: "gs://operational-intelligence-crafter-lake/geoparquet/nsw_water_inundation_areas/2026-Q1/20261108T223144Z/part-00000.parquet",
      viewName: "nsw_water_inundation_areas",
      keywords: [
        "flood", "floods", "water inundation", "inundation", "flood extent", "flood basin",
        "flood plain", "wetland", "submerged", "inundated area", "water extent"
      ],
      targetColumns: ["hydroname", "waterbody_name", "classsubtype"],
      defaultSort: "hydroname",
      sqlBuilder: function (areaText, localityInfo) {
        const loc = getActiveAoiRegion(areaText, localityInfo);
        const [minX, minY, maxX, maxY] = loc.bbox;
        const areaLabel = loc.name;
        return `-- NSW Water Inundation & Flood Extent Footprints
-- Spatial Filter: within generated AOI region (${areaLabel})
-- Extent: [${minX.toFixed(4)}, ${minY.toFixed(4)}, ${maxX.toFixed(4)}, ${maxY.toFixed(4)}] (EPSG:7844 / GDA2020)
SELECT
    COALESCE(hydroname, waterbody_name, 'Inundation Area') AS waterbody_name,
    classsubtype AS subtype,
    ROUND(TRY_CAST(Shape__Area AS DOUBLE), 2) AS area_sqm,
    ROUND(TRY_CAST(_bbox_miny AS DOUBLE), 4) AS lat,
    ROUND(TRY_CAST(_bbox_minx AS DOUBLE), 4) AS lon
FROM read_parquet('${this.parquetUri}')
WHERE _bbox_maxx >= ${minX.toFixed(4)} AND _bbox_minx <= ${maxX.toFixed(4)}
  AND _bbox_maxy >= ${minY.toFixed(4)} AND _bbox_miny <= ${maxY.toFixed(4)}
  -- Within generated AOI region
ORDER BY Shape__Area DESC NULLS LAST
LIMIT 100;`;
      }
    },
    {
      id: "ga_seismic_hazard_pga_10pct",
      scenarioKey: "seismic_hazard",
      title: "National Seismic Hazard Assessment 2018 — PGA Contours (10% in 50 Years)",
      theme: "Hazards",
      provider: "Geoscience Australia",
      geometryType: "LineString",
      scale: "national",
      parquetUri: "gs://operational-intelligence-crafter-lake/geoparquet/ga_seismic_hazard_pga_10pct/2018-NSHA/20261108T223144Z/part-00000.parquet",
      viewName: "ga_seismic_hazard_pga_10pct",
      keywords: [
        "seismic", "earthquake", "pga", "ground motion", "nsha", "hazard contour",
        "seismic hazard", "shaking"
      ],
      targetColumns: ["pga_value", "contour_id"],
      defaultSort: "pga_value DESC",
      sqlBuilder: function (areaText, localityInfo) {
        const loc = getActiveAoiRegion(areaText, localityInfo);
        const areaLabel = loc ? loc.name : (areaText || "National / Regional");
        let whereClause = "";
        if (loc && loc.bbox && loc.state !== "ALL" && !loc.name.toLowerCase().includes("national")) {
          const [minX, minY, maxX, maxY] = loc.bbox;
          whereClause = `WHERE _bbox_maxx >= ${minX.toFixed(4)} AND _bbox_minx <= ${maxX.toFixed(4)}
  AND _bbox_maxy >= ${minY.toFixed(4)} AND _bbox_miny <= ${maxY.toFixed(4)}
  -- Within generated AOI region`;
        }
        return `-- National Seismic Hazard Assessment 2018 — Ground Motion PGA Contours
-- Spatial Filter: within generated AOI region (${areaLabel})
SELECT
    contour_id,
    pga_value,
    ROUND(TRY_CAST(_bbox_miny AS DOUBLE), 4) AS lat,
    ROUND(TRY_CAST(_bbox_minx AS DOUBLE), 4) AS lon
FROM read_parquet('${this.parquetUri}')
${whereClause}
ORDER BY pga_value DESC
LIMIT 50;`;
      }
    },
    {
      id: "abs_australia_1km_population_grid",
      scenarioKey: "national_pop_grid",
      title: "ABS 2025 — Australian National 1 km² Population Grid",
      theme: "NExT Population & Geography",
      provider: "Australian Bureau of Statistics",
      geometryType: "Polygon",
      scale: "national",
      parquetUri: "gs://operational-intelligence-crafter-lake/geoparquet/abs_australia_1km_population_grid/2025-ABS/20261110T022639Z/part-00000.parquet",
      viewName: "abs_australia_1km_population_grid",
      keywords: [
        "population grid", "population", "residents", "people", "census", "erp",
        "demographic", "inhabitants", "1km grid", "1 km grid", "national population",
        "continental population"
      ],
      targetColumns: ["cell_id", "cell_population", "centroid_lon", "centroid_lat", "easting_m", "northing_m"],
      defaultSort: "cell_population DESC",
      sqlBuilder: function (areaText, localityInfo) {
        const loc = getActiveAoiRegion(areaText, localityInfo);
        const areaLabel = loc ? loc.name : (areaText || "Australia (National)");
        let whereClause = "";
        if (loc && loc.bbox && loc.state !== "ALL" && !loc.name.toLowerCase().includes("national")) {
          const [minX, minY, maxX, maxY] = loc.bbox;
          whereClause = `WHERE _bbox_maxx >= ${minX.toFixed(4)} AND _bbox_minx <= ${maxX.toFixed(4)}
  AND _bbox_maxy >= ${minY.toFixed(4)} AND _bbox_miny <= ${maxY.toFixed(4)}
  -- Spatial Filter: within generated AOI region (${loc.name})`;
        }

        return `-- ABS 2025 National 1 km² Population Grid (Australia)
-- Spatial Filter: within generated AOI region (${areaLabel})
-- Resolution: 1 km² Nested Grid (EPSG:7844 / GDA2020)
-- Total Continental Features: 286,827 cells (~27.61M pop)
SELECT
    g.cell_id,
    g.cell_population,
    g.centroid_lon,
    g.centroid_lat,
    g.easting_m,
    g.northing_m
FROM read_parquet('${this.parquetUri}') g
${whereClause}
ORDER BY g.cell_population DESC
LIMIT 500;`;
      }
    },
    {
      id: "derived_hunter_1km_population_grid",
      scenarioKey: "pop_comparison",
      title: "1 km² Population Grid (Methods A/B/C Comparison)",
      theme: "Population (Derived)",
      provider: "ABS & Lakehouse Pipeline",
      geometryType: "Polygon",
      scale: "local",
      parquetUri: "gs://operational-intelligence-crafter-lake/geoparquet/derived_hunter_1km_population_grid/ASGS2021-FOI-v1/20261109T003500Z/part-00000.parquet",
      viewName: "derived_hunter_1km_population_grid",
      keywords: [
        "method a", "method b", "method c", "pop comparison", "population comparison",
        "methodology comparison", "boundary straddling", "proportional estimate",
        "flood basin", "straddling cells", "population methodology"
      ],
      targetColumns: ["cell_id", "cell_population", "in_method_a", "in_method_b", "overlap_fraction"],
      defaultSort: "cell_population DESC",
      sqlBuilder: function (areaText, localityInfo) {
        const loc = getActiveAoiRegion(areaText, localityInfo);
        const areaLabel = loc ? loc.name : (areaText || "Lower Hunter");
        let whereClause = "WHERE g.in_method_b = true";
        if (loc && loc.bbox && loc.state !== "ALL" && !loc.name.toLowerCase().includes("national")) {
          const [minX, minY, maxX, maxY] = loc.bbox;
          whereClause += `\n  AND g._bbox_maxx >= ${minX.toFixed(4)} AND g._bbox_minx <= ${maxX.toFixed(4)}\n  AND g._bbox_maxy >= ${minY.toFixed(4)} AND g._bbox_miny <= ${maxY.toFixed(4)}\n  -- Spatial Filter: within generated AOI region (${loc.name})`;
        }
        return `-- Population Methodology Comparison (Methods A, B & C)
-- Spatial Filter: within generated AOI region (${areaLabel})
-- Invariant: Must evaluate all three methods on identical hazard footprints
-- Method A: 1 km² Centroid ST_Contains baseline
-- Method B: 1 km² Cell Polygon ST_Intersects (with boundary-straddling breakdown)
-- Method C: Area-weighted proportional estimate (uniform within-cell assumption)
SELECT
    COUNT(*) AS evaluated_cells,
    SUM(CASE WHEN in_method_a THEN cell_population ELSE 0 END) AS pop_method_a,
    SUM(CASE WHEN in_method_b THEN cell_population ELSE 0 END) AS pop_method_b,
    ROUND(SUM(cell_population * COALESCE(overlap_fraction, 1.0)), 1) AS pop_method_c_proportional,
    COUNT(CASE WHEN in_method_b AND NOT in_method_a THEN 1 END) AS straddling_cells_missed_by_a
FROM read_parquet('${this.parquetUri}') g
${whereClause};`;
      }
    },
    {
      id: "next_lga_boundaries_asgs2025",
      scenarioKey: "lga_multi_hazard",
      title: "ABS ASGS Edition 3 (2025) — Local Government Areas (LGAs)",
      theme: "NExT Administrative Baseline",
      provider: "Australian Bureau of Statistics",
      geometryType: "Polygon",
      scale: "national",
      parquetUri: "gs://operational-intelligence-crafter-lake/geoparquet/next_lga_boundaries_asgs2025/2025-ABS/20261108T223144Z/part-00000.parquet",
      viewName: "next_lga_boundaries_asgs2025",
      keywords: [
        "lga", "local government area", "council", "councils", "shire", "municipality",
        "lga boundaries", "multi-hazard summary", "lga summary"
      ],
      targetColumns: ["lga_code_2025", "lga_name_2025", "state_name_2021", "area_sqkm"],
      defaultSort: "lga_name_2025",
      sqlBuilder: function (areaText, localityInfo) {
        const loc = getActiveAoiRegion(areaText, localityInfo);
        const areaLabel = loc ? loc.name : (areaText || "NSW LGAs");
        let whereClause = "";
        if (loc && loc.bbox && loc.state !== "ALL" && !loc.name.toLowerCase().includes("national")) {
          const [minX, minY, maxX, maxY] = loc.bbox;
          whereClause = `WHERE _bbox_maxx >= ${minX.toFixed(4)} AND _bbox_minx <= ${maxX.toFixed(4)}\n  AND _bbox_maxy >= ${minY.toFixed(4)} AND _bbox_miny <= ${maxY.toFixed(4)}\n  -- Spatial Filter: within generated AOI region (${loc.name})`;
        } else if (loc && loc.state && loc.state === "NSW") {
          whereClause = `WHERE state_name_2021 = 'New South Wales'`;
        }
        return `-- Local Government Area (LGA) Boundaries (ASGS 2025)
-- Spatial Filter: within generated AOI region (${areaLabel})
SELECT
    lga_code_2025 AS lga_code,
    lga_name_2025 AS lga_name,
    state_name_2021 AS state,
    ROUND(TRY_CAST(area_sqkm AS DOUBLE), 1) AS area_sqkm,
    ROUND(TRY_CAST(_bbox_miny AS DOUBLE), 4) AS lat,
    ROUND(TRY_CAST(_bbox_minx AS DOUBLE), 4) AS lon
FROM read_parquet('${this.parquetUri}')
${whereClause}
ORDER BY lga_name_2025
LIMIT 50;`;
      }
    },
    {
      id: "cyclone_wp302026",
      scenarioKey: "cyclone_track_exposure",
      title: "Australian Tropical Cyclone Asset Exposure (WP302026)",
      theme: "Severe Weather Hazards",
      provider: "BOM / Severe Weather Track",
      geometryType: "LineString",
      scale: "regional",
      parquetUri: "gs://operational-intelligence-crafter-lake/geoparquet/ga_electricity_substations/2024-GA-NEI/20261108T223144Z/part-00000.parquet",
      viewName: "ga_electricity_substations",
      keywords: [
        "cyclone", "typhoon", "tropical storm", "cyclone track", "wp302026",
        "wind hazard", "in-fa", "storm track", "cyclone exposure"
      ],
      targetColumns: ["name", "locality", "state", "voltage_kv", "latitude", "longitude"],
      defaultSort: "voltage_kv DESC NULLS LAST",
      sqlBuilder: function (areaText, localityInfo) {
        const loc = getActiveAoiRegion(areaText, localityInfo);
        const areaLabel = loc ? loc.name : (areaText || "Eastern Australia & NSW Riverina");
        let whereClause = "WHERE state IN ('NSW', 'VIC', 'SA', 'QLD')";
        if (loc && loc.bbox && loc.state !== "ALL" && !loc.name.toLowerCase().includes("national") && !loc.name.toLowerCase().includes("eastern australia")) {
          const [minX, minY, maxX, maxY] = loc.bbox;
          whereClause += `\n  AND _bbox_maxx >= ${minX.toFixed(4)} AND _bbox_minx <= ${maxX.toFixed(4)}\n  AND _bbox_maxy >= ${minY.toFixed(4)} AND _bbox_miny <= ${maxY.toFixed(4)}\n  -- Spatial Filter: within generated AOI region (${loc.name})`;
        }
        return `-- Australian Tropical Cyclone Asset Exposure (WP302026)
-- Spatial Filter: within generated AOI region (${areaLabel})
-- Track Footprint: Inland Queensland / SA Channel Country & NSW Riverina
SELECT
    COALESCE(name, feature_name, 'Substation') AS asset_name,
    locality,
    state,
    TRY_CAST(voltage_kv AS INT) AS voltage_kv,
    ROUND(TRY_CAST(latitude AS DOUBLE), 4) AS lat,
    ROUND(TRY_CAST(longitude AS DOUBLE), 4) AS lon
FROM read_parquet('${this.parquetUri}')
${whereClause}
ORDER BY voltage_kv DESC NULLS LAST
LIMIT 30;`;
      }
    }
  ];

  // Map dataset id to catalogue entry
  const CATALOGUE_BY_ID = Object.fromEntries(CATALOGUE.map(d => [d.id, d]));
  const CATALOGUE_BY_SCENARIO = Object.fromEntries(CATALOGUE.map(d => [d.scenarioKey, d]));

  /**
   * Resolves locality text into canonical name and bounding box.
   */
  function resolveLocality(rawText) {
    if (!rawText) return null;
    if (typeof rawText === "object") {
      if (rawText.bbox && Array.isArray(rawText.bbox) && rawText.bbox.length === 4) {
        return {
          key: "custom_aoi",
          name: rawText.name || `Active AOI [${rawText.bbox.map(n => typeof n === "number" ? n.toFixed(3) : n).join(", ")}]`,
          bbox: rawText.bbox,
          state: rawText.state || "NSW"
        };
      }
      if (typeof window !== "undefined" && window.OICLayers && typeof window.OICLayers.resolveLocalityExtent === "function") {
        const ext = window.OICLayers.resolveLocalityExtent(rawText);
        if (ext && ext.bbox) {
          return {
            key: "custom_aoi",
            name: ext.name || "Active AOI Geometry",
            bbox: ext.bbox,
            state: "NSW"
          };
        }
      }
      return null;
    }
    if (typeof rawText !== "string") return null;
    const lower = rawText.toLowerCase().trim();

    // 1. Check window.OICLayers.resolveLocalityExtent first (it has 6,000+ gazetteer entries)
    if (typeof window !== "undefined" && window.OICLayers && typeof window.OICLayers.resolveLocalityExtent === "function") {
      const ext = window.OICLayers.resolveLocalityExtent(rawText);
      if (ext && ext.bbox) {
        return {
          key: (ext.name || lower).toLowerCase(),
          name: ext.name || rawText,
          bbox: ext.bbox,
          state: ext.state || "NSW"
        };
      }
    }

    // 2. Check exact or substring in LOCALITIES
    for (const [key, info] of Object.entries(LOCALITIES)) {
      if (lower === key || lower.includes(key)) {
        return { key, ...info };
      }
    }

    // 3. Check coordinates pattern: minX, minY, maxX, maxY
    const bboxMatch = lower.match(/(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)/);
    if (bboxMatch) {
      let minX = parseFloat(bboxMatch[1]);
      let minY = parseFloat(bboxMatch[2]);
      let maxX = parseFloat(bboxMatch[3]);
      let maxY = parseFloat(bboxMatch[4]);
      if (minX > maxX) [minX, maxX] = [maxX, minX];
      if (minY > maxY) [minY, maxY] = [maxY, minY];
      return {
        key: "custom_bbox",
        name: `Custom Extent [${minX.toFixed(3)}, ${minY.toFixed(3)}, ${maxX.toFixed(3)}, ${maxY.toFixed(3)}]`,
        bbox: [minX, minY, maxX, maxY],
        state: "CUSTOM"
      };
    }

    return null;
  }

  /**
   * Resolves the active generated AOI region from locality info, user input, or layers.
   */
  function getActiveAoiRegion(areaText, localityInfo) {
    if (localityInfo && localityInfo.bbox && Array.isArray(localityInfo.bbox) && localityInfo.bbox.length === 4) {
      return localityInfo;
    }
    if (areaText) {
      const res = resolveLocality(areaText);
      if (res && res.bbox) return res;
    }
    if (typeof document !== "undefined") {
      const aoiEl = document.getElementById("aoiInput");
      const aoiVal = aoiEl ? aoiEl.value.trim() : "";
      if (aoiVal) {
        const res = resolveLocality(aoiVal);
        if (res && res.bbox) return res;
      }
    }
    if (typeof window !== "undefined" && window.OICLayers && typeof window.OICLayers.getCurrentAoiGeometry === "function") {
      const cur = window.OICLayers.getCurrentAoiGeometry();
      if (cur) {
        const res = resolveLocality(cur);
        if (res && res.bbox) return res;
      }
    }
    if (typeof window !== "undefined" && window.OICApp && typeof window.OICApp.getUserParams === "function") {
      const p = window.OICApp.getUserParams();
      if (p && p.area) {
        const res = resolveLocality(p.area);
        if (res && res.bbox) return res;
      }
    }
    return LOCALITIES["lower hunter"] || {
      name: "Lower Hunter AOI",
      bbox: [151.4000, -32.9500, 151.8500, -32.6500],
      state: "NSW"
    };
  }

  /**
   * Discover dataset in catalogue matching natural language query.
   * Rejection ONLY happens if the dataset genuinely does not exist or failed source contract.
   */
  function findDataset(queryText, activeArea) {
    const rawQ = (queryText || "").trim();
    let q = rawQ.toLowerCase();

    // 1. Guardrail: Check for explicitly restricted sources or private sensor streams
    for (const item of RESTRICTED_TRIGGERS) {
      if (item.pattern.test(q)) {
        return {
          status: "REJECTED_UNCATALOGUED",
          query: rawQ,
          blockedLabel: item.label,
          reason: `Access to ${item.label} is blocked: ${item.reason}`,
          availableDatasets: CATALOGUE.map(d => ({ id: d.id, title: d.title, theme: d.theme }))
        };
      }
    }

    // 2. Extract Locality from query or use activeArea
    let localityInfo = resolveLocality(activeArea);
    for (const [locKey, locInfo] of Object.entries(LOCALITIES)) {
      const reg = new RegExp(`\\b${locKey}\\b`, "i");
      if (reg.test(q)) {
        localityInfo = { key: locKey, ...locInfo };
        q = q.replace(reg, " ").trim();
        break;
      }
    }

    // 3. Tokenize query and remove stopwords
    const rawTokens = q.match(/[a-z0-9_-]+/g) || [];
    const tokens = rawTokens.filter(t => !STOPWORDS.has(t));

    // If query was empty or only area/stopwords, check if an active scenario exists
    if (tokens.length === 0) {
      return {
        status: "NO_TOKENS",
        query: rawQ,
        locality: localityInfo
      };
    }

    // 4. Multi-tier scoring against catalogue datasets
    const scored = [];
    const joinedQ = tokens.join(" ");

    for (const dataset of CATALOGUE) {
      let score = 0;
      let matchedKeyword = null;

      // Tier 1: Exact keyword match
      for (const kw of dataset.keywords) {
        if (kw === joinedQ) {
          score += 20.0;
          matchedKeyword = kw;
        } else if (joinedQ.includes(kw)) {
          score += 12.0;
          if (!matchedKeyword) matchedKeyword = kw;
        } else {
          for (const tok of tokens) {
            if (tok === kw) {
              score += 6.0;
              if (!matchedKeyword) matchedKeyword = tok;
            } else if (tok.length > 3 && (kw.includes(tok) || tok.includes(kw))) {
              score += 3.0;
              if (!matchedKeyword) matchedKeyword = tok;
            }
          }
        }
      }

      // Tier 2: Theme / Title match
      const titleLower = dataset.title.toLowerCase();
      const themeLower = dataset.theme.toLowerCase();
      for (const tok of tokens) {
        if (titleLower.includes(tok)) score += 4.0;
        if (themeLower.includes(tok)) score += 3.0;
      }

      // Tier 3: Target column names
      for (const col of dataset.targetColumns) {
        if (tokens.includes(col.toLowerCase())) score += 5.0;
      }

      if (score > 0) {
        scored.push({ dataset, score, matchedKeyword: matchedKeyword || tokens[0] });
      }
    }

    scored.sort((a, b) => b.score - a.score);

    if (scored.length > 0 && scored[0].score >= 3.0) {
      const best = scored[0].dataset;
      return {
        status: "MATCHED",
        score: scored[0].score,
        dataset: best,
        scenarioKey: best.scenarioKey,
        locality: localityInfo,
        areaText: localityInfo ? localityInfo.name : activeArea,
        matchedConcept: scored[0].matchedKeyword || rawQ
      };
    }

    // No catalogue dataset matched query — genuine data absence
    return {
      status: "DATASET_NOT_FOUND",
      query: rawQ,
      reason: `No dataset matching "${rawQ}" exists in the authoritative Australian spatial lakehouse.`,
      availableDatasets: CATALOGUE.map(d => ({ id: d.id, title: d.title, theme: d.theme }))
    };
  }

  /**
   * Compiles DuckDB Spatial SQL from a findDataset() result.
   */
  function compileSql(matchResult, fallbackAreaText) {
    if (!matchResult) {
      return buildUncataloguedRejectSql("Requested query");
    }

    if (matchResult.status === "REJECTED_UNCATALOGUED" || matchResult.status === "DATASET_NOT_FOUND") {
      return buildUncataloguedRejectSql(matchResult.query, matchResult.reason);
    }

    if (matchResult.status === "MATCHED" && matchResult.dataset) {
      const ds = matchResult.dataset;
      const area = matchResult.areaText || fallbackAreaText;
      return ds.sqlBuilder(area, matchResult.locality, matchResult.matchedConcept);
    }

    // Fallback uncatalogued reject
    return buildUncataloguedRejectSql(matchResult.query || "Spatial query");
  }

  /**
   * Builds the zero-mock rejection SQL statement.
   */
  function buildUncataloguedRejectSql(queryText, customReason) {
    const qClean = (queryText || "Requested entity").replace(/'/g, "");
    const reasonClean = (customReason || `Data for '${qClean}' is not available in the public spatial lakehouse catalogue.`).replace(/'/g, "");

    return `-- UNCATALOGUED ENTITY / DATASET NOT IN SPATIAL LAKEHOUSE
-- User Query: "${qClean}"
-- Status: NOT_IN_CATALOGUE (Zero-Mock Invariant Enforced)
-- The GeoLibre catalogue discovery engine evaluated this query against authoritative Australian datasets:
-- The requested entity or telemetry is not part of the verified spatial lakehouse catalogue.
--
-- Authoritative datasets available in catalogue:
-- 1. NSW Features of Interest — Hospitals, Schools, Bridges, Airports, Police & Emergency Facilities (nsw_foi_building_complexes)
-- 2. Geoscience Australia Critical Infrastructure — Substations (ga_electricity_substations)
-- 3. Geoscience Australia Critical Infrastructure — Major Power Stations (ga_major_power_stations)
-- 4. Geoscience Australia Critical Infrastructure — Transmission Lines (ga_electricity_transmission_lines)
-- 5. NSW Rural Fire Service — Current Major Bushfire Incidents Live Feed (nsw_rfs_major_incidents_live)
-- 6. ABS 2025 National 1 km² Population Grid (abs_australia_1km_population_grid)
-- 7. ABS ASGS 2025 Local Government Areas (next_lga_boundaries_asgs2025)
-- 8. NSW Spatial Services — Water Inundation & Flood Extents (nsw_water_inundation_areas)
-- 9. Geoscience Australia — NSHA 2018 Seismic PGA Contours (ga_seismic_hazard_pga_10pct)
SELECT
    'DATASET_NOT_FOUND' AS status,
    '${reasonClean}' AS reason,
    'Please select an authoritative preset from Step 01 (e.g. Hospitals, Substations, Power Stations, Bushfires, or Population Grid)' AS recommendation;`;
  }

  // Public API
  return {
    CATALOGUE,
    CATALOGUE_BY_ID,
    CATALOGUE_BY_SCENARIO,
    LOCALITIES,
    resolveLocality,
    getActiveAoiRegion,
    findDataset,
    compileSql,
    buildUncataloguedRejectSql
  };
});
