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
    "central coast": { name: "Central Coast, NSW", bbox: [151.1000, -33.6000, 151.6000, -33.1000], state: "NSW" },
    "gosford": { name: "Gosford, NSW", bbox: [151.3000, -33.4500, 151.4000, -33.3800], state: "NSW" },
    "wyong": { name: "Wyong, NSW", bbox: [151.3800, -33.3200, 151.5200, -33.2200], state: "NSW" },
    "port stephens": { name: "Port Stephens, NSW", bbox: [151.6800, -32.8500, 152.2200, -32.6000], state: "NSW" },
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
      parquetUri: "gs://operational-intelligence-crafter-lake/geoparquet/nsw_foi_building_complexes/2026-NSW-FOI/20261109T073128Z/part-00000.parquet",
      viewName: "nsw_foi_building_complexes",
      keywords: [
        // Healthcare
        "hospital", "hospitals", "medical", "clinic", "clinics", "health", "healthcare",
        "infirmary", "doctor", "nursing", "aged care", "facility", "facilities",
        "community health", "health centre", "emergency department", "health complex",
        "manning hospital", "mayo private", "medical complex", "dentist", "pharmacy",
        // Education
        "school", "schools", "primary school", "high school", "college", "education",
        "public school", "grammar", "tafe", "campus", "university", "childcare", "daycare", "kindergarten", "preschool",
        // Emergency Services
        "police", "police station", "ambulance", "ambulance station", "fire station",
        "fire brigade", "ses", "emergency facility", "fire depot", "station", "watchhouse", "court", "courthouse",
        // Transport & Infrastructure Facilities
        "bridge", "bridges", "road bridge", "crossing", "bridge depot", "bridge plaza",
        "airport", "airports", "aerodrome", "airstrip", "airfield", "aviation", "helipad", "heliport",
        "train station", "railway", "interchange", "wharf", "ferry",
        // Civic, Community & Cultural
        "community centre", "public hall", "civic centre", "town hall", "hall", "centre",
        "library", "libraries", "museum", "museums", "gallery",
        "post office", "post offices", "postal", "depot", "depots", "works depot", "council depot",
        "church", "churches", "cathedral", "chapel", "mosque", "temple", "synagogue", "cemetery", "crematorium",
        // Sports & Recreation
        "park", "parks", "sports complex", "stadium", "oval", "pool", "aquatic centre", "recreation", "showground", "reserve",
        "surf club", "surf clubs", "slsc", "lifesaving", "golf course", "golf club", "bowling club", "bowls",
        "caravan park", "camping ground", "visitor centre", "information centre",
        // Commercial & Retail
        "shopping centre", "mall", "market", "plaza", "commercial complex"
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
        let facilityTypeCase = `CASE facility_subtype
        WHEN 1 THEN 'Educational Institution'
        WHEN 2 THEN 'Community / Health Facility'
        WHEN 3 THEN 'Health / Care Facility'
        WHEN 4 THEN 'Civic / Infrastructure Facility'
        WHEN 5 THEN 'Utility / Substation'
        WHEN 6 THEN 'Recreational / Public Complex'
        ELSE 'Feature of Interest'
    END`;

        if (concept.includes("bridge") || concept.includes("crossing") || concept.includes("viaduct")) {
          categoryTitle = "Bridges & Transport Infrastructure";
          categoryFilter = `(LOWER(COALESCE(facility_name, generalname, '')) LIKE '%bridge%' OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%crossing%')`;
          facilityTypeCase = `'Bridge / Transport Infrastructure'`;
        } else if (concept.includes("airport") || concept.includes("aerodrome") || concept.includes("airfield") || concept.includes("aviation") || concept.includes("helipad") || concept.includes("heliport") || concept.includes("airstrip")) {
          categoryTitle = "Airports & Aviation Facilities";
          categoryFilter = `(LOWER(COALESCE(facility_name, generalname, '')) LIKE '%airport%' OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%aerodrome%' OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%airfield%' OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%helipad%')`;
          facilityTypeCase = `CASE
        WHEN LOWER(COALESCE(facility_name, generalname, '')) LIKE '%airport%' THEN 'Airport'
        WHEN LOWER(COALESCE(facility_name, generalname, '')) LIKE '%aerodrome%' THEN 'Aerodrome'
        WHEN LOWER(COALESCE(facility_name, generalname, '')) LIKE '%helipad%' OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%heliport%' THEN 'Helipad'
        ELSE 'Aviation Facility'
    END`;
        } else if (concept.includes("school") || concept.includes("college") || concept.includes("education") || concept.includes("university") || concept.includes("campus") || concept.includes("tafe") || concept.includes("grammar")) {
          categoryTitle = "Educational Facilities & Schools";
          categoryFilter = `(LOWER(COALESCE(facility_name, generalname, '')) LIKE '%school%' OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%college%' OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%university%' OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%tafe%' OR facility_subtype = 1)`;
          facilityTypeCase = `CASE
        WHEN LOWER(COALESCE(facility_name, generalname, '')) LIKE '%university%' OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%campus%' THEN 'University / Campus'
        WHEN LOWER(COALESCE(facility_name, generalname, '')) LIKE '%tafe%' OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%college%' THEN 'College / TAFE'
        WHEN LOWER(COALESCE(facility_name, generalname, '')) LIKE '%high school%' THEN 'High School'
        WHEN LOWER(COALESCE(facility_name, generalname, '')) LIKE '%primary%' THEN 'Primary School'
        ELSE 'School / Educational'
    END`;
        } else if (concept.includes("childcare") || concept.includes("daycare") || concept.includes("preschool") || concept.includes("kindergarten")) {
          categoryTitle = "Childcare & Early Learning Centres";
          categoryFilter = `(LOWER(COALESCE(facility_name, generalname, '')) LIKE '%childcare%' OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%preschool%' OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%kindergarten%')`;
          facilityTypeCase = `'Early Learning / Childcare'`;
        } else if (concept.includes("library") || concept.includes("libraries")) {
          categoryTitle = "Public Libraries & Community Knowledge";
          categoryFilter = `(LOWER(COALESCE(facility_name, generalname, '')) LIKE '%library%' OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%libraries%')`;
          facilityTypeCase = `'Public Library'`;
        } else if (concept.includes("police") || concept.includes("court") || concept.includes("justice") || concept.includes("correction") || concept.includes("prison")) {
          categoryTitle = "Police Stations & Law Enforcement";
          categoryFilter = `(LOWER(COALESCE(facility_name, generalname, '')) LIKE '%police%' OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%court%')`;
          facilityTypeCase = `CASE WHEN LOWER(COALESCE(facility_name, generalname, '')) LIKE '%police%' THEN 'Police Station' ELSE 'Courthouse / Justice' END`;
        } else if (concept.includes("fire") || concept.includes("brigade") || /\bses\b/i.test(concept)) {
          categoryTitle = "Fire Stations & Emergency Response";
          categoryFilter = `(LOWER(COALESCE(facility_name, generalname, '')) LIKE '%fire%' OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%brigade%' OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%ses%')`;
          facilityTypeCase = `CASE WHEN LOWER(COALESCE(facility_name, generalname, '')) LIKE '%ses%' THEN 'State Emergency Service (SES)' ELSE 'Fire Station' END`;
        } else if (concept.includes("ambulance") || concept.includes("paramedic")) {
          categoryTitle = "Ambulance Stations & Paramedic Facilities";
          categoryFilter = `(LOWER(COALESCE(facility_name, generalname, '')) LIKE '%ambulance%' OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%paramedic%')`;
          facilityTypeCase = `'Ambulance Station'`;
        } else if (concept.includes("hospital")) {
          categoryTitle = "Authoritative NSW Hospitals & Acute Care";
          categoryFilter = `(
    (LOWER(COALESCE(facility_name, generalname, '')) LIKE '%hospital%'
     OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%health service%')
    AND LOWER(COALESCE(facility_name, generalname, '')) NOT LIKE '%bowling%'
    AND LOWER(COALESCE(facility_name, generalname, '')) NOT LIKE '%aged care%'
)`;
          facilityTypeCase = `CASE
        WHEN LOWER(COALESCE(facility_name, generalname, '')) LIKE '%private hospital%' THEN 'Private Hospital'
        WHEN LOWER(COALESCE(facility_name, generalname, '')) LIKE '%day hospital%' OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%day surgery%' THEN 'Day Surgery / Day Hospital'
        WHEN LOWER(COALESCE(facility_name, generalname, '')) LIKE '%community health%' THEN 'Hospital Community Health'
        WHEN LOWER(COALESCE(facility_name, generalname, '')) LIKE '%hospital%' THEN 'Public / General Hospital'
        ELSE 'Hospital & Health Service'
    END`;
        } else if (concept.includes("aged care") || concept.includes("nursing") || concept.includes("retirement")) {
          categoryTitle = "Aged Care & Residential Facilities";
          categoryFilter = `(LOWER(COALESCE(facility_name, generalname, '')) LIKE '%aged care%' OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%nursing home%' OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%retirement%')`;
          facilityTypeCase = `'Aged Care Facility'`;
        } else if (concept.includes("medical") || concept.includes("clinic") || concept.includes("health") || concept.includes("doctor") || concept.includes("pharmacy")) {
          categoryTitle = "Medical Centres & Community Health Facilities";
          categoryFilter = `(
    (LOWER(COALESCE(facility_name, generalname, '')) LIKE '%medical%'
     OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%clinic%'
     OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%health centre%'
     OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%community health%')
    AND LOWER(COALESCE(facility_name, generalname, '')) NOT LIKE '%bowling%'
)`;
          facilityTypeCase = `'Medical Centre / Clinic'`;
        } else if (concept.includes("church") || concept.includes("worship") || concept.includes("cathedral") || concept.includes("chapel") || concept.includes("mosque") || concept.includes("temple") || concept.includes("synagogue") || concept.includes("cemetery") || concept.includes("crematorium")) {
          categoryTitle = "Places of Worship & Memorial Grounds";
          categoryFilter = `(LOWER(COALESCE(facility_name, generalname, '')) LIKE '%church%' OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%cathedral%' OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%chapel%' OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%mosque%' OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%temple%' OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%cemetery%')`;
          facilityTypeCase = `CASE WHEN LOWER(COALESCE(facility_name, generalname, '')) LIKE '%cemetery%' OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%crematorium%' THEN 'Cemetery / Memorial' ELSE 'Place of Worship' END`;
        } else if (concept.includes("park") || concept.includes("sports") || concept.includes("stadium") || concept.includes("oval") || concept.includes("pool") || concept.includes("aquatic") || concept.includes("recreation") || concept.includes("showground") || concept.includes("reserve")) {
          categoryTitle = "Parks, Sports & Recreation Facilities";
          categoryFilter = `(LOWER(COALESCE(facility_name, generalname, '')) LIKE '%park%' OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%stadium%' OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%oval%' OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%sports%' OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%pool%' OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%recreation%' OR facility_subtype = 6)`;
          facilityTypeCase = `'Parks & Recreation'`;
        } else if (concept.includes("shopping") || concept.includes("mall") || concept.includes("market") || concept.includes("plaza")) {
          categoryTitle = "Commercial & Retail Complexes";
          categoryFilter = `(LOWER(COALESCE(facility_name, generalname, '')) LIKE '%shopping%' OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%mall%' OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%market%' OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%plaza%')`;
          facilityTypeCase = `'Commercial Complex'`;
        } else if (concept.includes("station") || concept.includes("train") || concept.includes("railway") || concept.includes("interchange") || concept.includes("ferry") || concept.includes("wharf")) {
          categoryTitle = "Transport Stations & Interchanges";
          categoryFilter = `(LOWER(COALESCE(facility_name, generalname, '')) LIKE '%station%' OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%railway%' OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%interchange%' OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%wharf%')`;
          facilityTypeCase = `'Transport Interchange / Station'`;
        } else if (concept.includes("community") || concept.includes("civic") || concept.includes("hall") || concept.includes("centre")) {
          categoryTitle = "Civic & Community Centres";
          categoryFilter = `(LOWER(COALESCE(facility_name, generalname, '')) LIKE '%community%' OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%civic%' OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%hall%' OR facility_subtype = 2)`;
          facilityTypeCase = `'Civic & Community Facility'`;
        } else if (concept.includes("post") || concept.includes("mail")) {
          categoryTitle = "Postal Facilities & Post Offices";
          categoryFilter = `(LOWER(COALESCE(facility_name, generalname, '')) LIKE '%post%' OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%mail%')`;
          facilityTypeCase = `'Postal Facility'`;
        } else if (concept.includes("depot")) {
          categoryTitle = "Depots & Municipal Works Facilities";
          categoryFilter = `(LOWER(COALESCE(facility_name, generalname, '')) LIKE '%depot%')`;
          facilityTypeCase = `'Municipal Depot'`;
        } else if (concept.includes("surf") || concept.includes("slsc") || concept.includes("lifesaving")) {
          categoryTitle = "Surf Lifesaving & Coastal Safety Clubs";
          categoryFilter = `(LOWER(COALESCE(facility_name, generalname, '')) LIKE '%surf%' OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%slsc%' OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%lifesaving%')`;
          facilityTypeCase = `'Surf Lifesaving Club'`;
        } else if (concept.includes("golf") || concept.includes("bowling") || concept.includes("bowls")) {
          categoryTitle = "Golf & Bowling Recreation Facilities";
          categoryFilter = `(LOWER(COALESCE(facility_name, generalname, '')) LIKE '%golf%' OR LOWER(COALESCE(facility_name, generalname, '')) LIKE '%bowl%' OR facility_subtype = 6)`;
          facilityTypeCase = `'Golf / Bowls Facility'`;
        } else {
          // Dynamic token-based search for ANY custom facility term the user enters
          const cleanTokens = concept.replace(/[^a-z0-9\s]/g, " ")
            .split(/\s+/)
            .filter(t => t.length >= 3 && !STOPWORDS.has(t) && !LOCALITIES[t]);
          if (cleanTokens.length > 0) {
            const filterParts = cleanTokens.map(t => `LOWER(COALESCE(facility_name, generalname, '')) LIKE '%${t}%'`);
            categoryFilter = `(${filterParts.join(" OR ")})`;
            const capitalizedTerm = cleanTokens[0].charAt(0).toUpperCase() + cleanTokens[0].slice(1);
            categoryTitle = `${capitalizedTerm} Facilities & Infrastructure`;
            facilityTypeCase = `'${capitalizedTerm} Facility'`;
          } else {
            categoryFilter = "1=1";
            categoryTitle = "Emergency & Community Facilities";
          }
        }

        return `-- Authoritative NSW Features of Interest (${categoryTitle})
-- Spatial Filter: within generated AOI region (${areaLabel})
-- Source: NSW Spatial Services (DCS) Features of Interest
SELECT
    COALESCE(facility_name, generalname, 'Facility') AS facility_name,
    ${facilityTypeCase} AS facility_type,
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
      parquetUri: "gs://operational-intelligence-crafter-lake/geoparquet/ga_electricity_substations/2024-GA-NEI/20261109T073013Z/part-00000.parquet",
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
      parquetUri: "gs://operational-intelligence-crafter-lake/geoparquet/ga_major_power_stations/2024-GA-NEI/20261109T073026Z/part-00000.parquet",
      viewName: "ga_major_power_stations",
      keywords: [
        "power station", "power stations", "generator", "generators", "generation",
        "power plant", "megawatt", "mw", "renewable", "solar farm", "wind farm",
        "coal station", "gas peaker", "hydroelectric", "generation capacity"
      ],
      targetColumns: ["name", "generation_capacity_mw", "primary_fuel_type", "state", "status", "latitude", "longitude"],
      defaultSort: "capacity_mw DESC NULLS LAST",
      sqlBuilder: function (areaText, localityInfo) {
        const loc = getActiveAoiRegion(areaText, localityInfo);
        const areaLabel = loc ? loc.name : (areaText || "Australia National");
        if (loc && loc.bbox && loc.state !== "ALL" && !loc.name.toLowerCase().includes("national")) {
          const [minX, minY, maxX, maxY] = loc.bbox;
          return `-- Major Power Stations & Generation Capacity (GA NEI)
-- Spatial Filter: within generated AOI region (${loc.name})
-- Extent: [${minX.toFixed(4)}, ${minY.toFixed(4)}, ${maxX.toFixed(4)}, ${maxY.toFixed(4)}] (EPSG:7844 / GDA2020)
SELECT
    COALESCE(name, feature_name, 'Power Station') AS station_name,
    locality,
    state,
    COALESCE(primary_fuel_type, fuel_type, 'Unknown') AS fuel_type,
    ROUND(TRY_CAST(COALESCE(generation_capacity_mw, capacity_mw) AS DOUBLE), 1) AS capacity_mw,
    status,
    ROUND(TRY_CAST(_bbox_miny AS DOUBLE), 4) AS lat,
    ROUND(TRY_CAST(_bbox_minx AS DOUBLE), 4) AS lon
FROM read_parquet('${this.parquetUri}')
WHERE _bbox_maxx >= ${minX.toFixed(4)} AND _bbox_minx <= ${maxX.toFixed(4)}
  AND _bbox_maxy >= ${minY.toFixed(4)} AND _bbox_miny <= ${maxY.toFixed(4)}
  -- Within generated AOI region
ORDER BY capacity_mw DESC NULLS LAST
LIMIT 100;`;
        }
        let areaFilterSql = (loc && loc.state && loc.state !== "ALL") ? `WHERE state = '${loc.state}'` : "WHERE state IS NOT NULL";
        return `-- National Major Power Stations & Generation Capacity (GA NEI)
-- Scope: ${areaLabel}
SELECT
    COALESCE(state, 'Unknown') AS state,
    COUNT(*) AS total_power_stations,
    ROUND(SUM(TRY_CAST(COALESCE(generation_capacity_mw, capacity_mw) AS DOUBLE)), 1) AS total_capacity_mw,
    ROUND(AVG(TRY_CAST(COALESCE(generation_capacity_mw, capacity_mw) AS DOUBLE)), 1) AS avg_capacity_mw,
    COUNT(CASE WHEN LOWER(status) = 'operating' THEN 1 END) AS active_operating
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
      parquetUri: "gs://operational-intelligence-crafter-lake/geoparquet/ga_electricity_transmission_lines/2024-GA-NEI/20261109T073016Z/part-00000.parquet",
      viewName: "ga_electricity_transmission_lines",
      keywords: [
        "transmission line", "transmission lines", "power line", "high voltage", "pylons",
        "feeder", "grid lines", "kv line"
      ],
      targetColumns: ["name", "feature_name", "capacity_kv", "state"],
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
    TRY_CAST(capacity_kv AS INT) AS voltage_kv,
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
      parquetUri: "gs://operational-intelligence-crafter-lake/geoparquet/nsw_rfs_major_incidents_live/LIVE-FEED/20261109T073310Z/part-00000.parquet",
      viewName: "nsw_rfs_major_incidents_live",
      keywords: [
        "rfs", "bushfire", "bushfires", "wildfire", "fire", "fires", "fire incident",
        "major incident", "emergency incident", "out of control", "emergency warning",
        "watch and act", "burn"
      ],
      targetColumns: ["title", "category", "alert_level", "pubDate", "description"],
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
    COALESCE(alert_level, category, 'Incident') AS alert_level,
    pubDate AS published_at,
    SUBSTRING(description, 1, 120) AS summary,
    ROUND(TRY_CAST(_bbox_miny AS DOUBLE), 4) AS lat,
    ROUND(TRY_CAST(_bbox_minx AS DOUBLE), 4) AS lon
FROM read_parquet('${this.parquetUri}')
${whereClause}
ORDER BY
    CASE COALESCE(alert_level, category)
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
      parquetUri: "gs://operational-intelligence-crafter-lake/geoparquet/nsw_water_inundation_areas/2026-NSW-Water/20261109T073310Z/part-00000.parquet",
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
      parquetUri: "gs://operational-intelligence-crafter-lake/geoparquet/ga_seismic_hazard_pga_10pct/NSHA-2018/20261109T073027Z/part-00000.parquet",
      viewName: "ga_seismic_hazard_pga_10pct",
      keywords: [
        "seismic", "earthquake", "pga", "ground motion", "nsha", "hazard contour",
        "seismic hazard", "shaking"
      ],
      targetColumns: ["pga_level_g", "contour_id"],
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
    ROUND(TRY_CAST(pga_level_g AS DOUBLE), 4) AS pga_value,
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
      parquetUri: "gs://operational-intelligence-crafter-lake/geoparquet/next_lga_boundaries_asgs2025/ASGS-2025/20261109T073027Z/part-00000.parquet",
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
      parquetUri: "gs://operational-intelligence-crafter-lake/geoparquet/ga_electricity_substations/2024-GA-NEI/20261109T073013Z/part-00000.parquet",
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
      let maxKwScore = 0;
      for (const kw of dataset.keywords) {
        let kwScore = 0;
        // Short keywords (<= 4 chars) require boundary check to avoid substring traps (e.g. 'courses' containing 'ses')
        const isKwInQuery = kw.length <= 4
          ? (tokens.includes(kw) || new RegExp("(^|\\s)" + kw + "(\\s|$)", "i").test(joinedQ))
          : (joinedQ.includes(kw) || tokens.includes(kw));

        if (kw === joinedQ) {
          kwScore = 20.0;
        } else if (isKwInQuery) {
          kwScore = 12.0 + (kw.length * 0.1);
        } else {
          for (const tok of tokens) {
            if (tok === kw) {
              kwScore = Math.max(kwScore, 6.0);
            } else if (tok.length > 3 && kw.length > 3 && (kw.includes(tok) || tok.includes(kw))) {
              kwScore = Math.max(kwScore, 3.0);
            }
          }
        }
        if (kwScore > 0) {
          score += kwScore;
          if (kwScore > maxKwScore || (kwScore === maxKwScore && kw.length > (matchedKeyword ? matchedKeyword.length : 0))) {
            maxKwScore = kwScore;
            matchedKeyword = kw;
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

    // 5. Dynamic fallback for arbitrary facilities / features of interest in a target area:
    // If user provided a locality or active area, or query contains searchable tokens,
    // route to nsw_foi_building_complexes to search the authoritative spatial lakehouse
    if ((localityInfo || activeArea) && tokens.length > 0) {
      const foiDataset = CATALOGUE_BY_ID["nsw_foi_building_complexes"];
      if (foiDataset) {
        return {
          status: "MATCHED",
          score: 2.5,
          dataset: foiDataset,
          scenarioKey: foiDataset.scenarioKey,
          locality: localityInfo,
          areaText: localityInfo ? localityInfo.name : activeArea,
          matchedConcept: tokens.join(" ")
        };
      }
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
