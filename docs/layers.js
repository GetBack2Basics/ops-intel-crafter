/*
  docs/layers.js
  AURA-style map interactivity for the Emergency Spatial Workbench:
  - Click-to-identify popups for points, lines and polygons (all visible layers).
  - Layer Control (visibility, opacity, order, zoom, metadata, charts, table).
  - Metadata & 3-Level QA lineage modal (from qa/data/qa_summary.json).
  - Attribute distribution chart modal (computed from real feature attributes).
  - Attribute Table dock with search, CSV export and click-to-zoom rows.
  Zero mock: every feature/value comes from stored GeoJSON previews of GCS GeoParquet.
*/
(function () {
  "use strict";

  // ---------- Catalogue registry (real GeoJSON previews / derived exports) ----------
  const CATALOG = [
    {
      key: "derived_hunter_1km_population_grid", title: "1 km² Population Grid (Methods A/B/C)", kind: "fill", color: "#006973",
      path: "exports/hunter_population_grid_comparison/result.geojson", theme: "Population (Derived)", scale: "local",
      derivedFrom: ["next_sa2_boundaries_asgs2021", "nsw_foi_building_complexes", "nsw_water_inundation_areas"],
      paint: { "fill-color": ["match", ["get", "cell_classification"], "FULLY_CONTAINED", "#006973", "BOUNDARY_CENTROID_IN", "#0284c7", "BOUNDARY_CENTROID_OUT", "#d47300", "#64748b"] },
      legendClasses: [["#006973", "Fully contained (A & B)"], ["#0284c7", "Straddling — centroid in"], ["#d47300", "Straddling — missed by A"]]
    },
    {
      key: "hunter_substation_flood_dependency", title: "Substation Flood Dependency (Derived)", kind: "circle", color: "#ea580c",
      path: "exports/hunter_substation_flood_dependency/result.geojson", theme: "Infrastructure (Derived)", scale: "local",
      derivedFrom: ["ga_electricity_substations", "nsw_water_inundation_areas", "nsw_foi_building_complexes"]
    },
    { key: "nsw_water_inundation_areas", title: "NSW Water Inundation Areas", kind: "fill", color: "#38bdf8", path: "qa/data/nsw_water_inundation_areas.geojson", theme: "Flood & Hydrography", scale: "state" },
    { key: "ga_electricity_transmission_lines", title: "GA Transmission Lines", kind: "line", color: "#eab308", path: "qa/data/ga_electricity_transmission_lines.geojson", theme: "Critical Infrastructure", scale: "national" },
    { key: "ga_electricity_substations", title: "GA Power Substations", kind: "circle", color: "#c2410c", path: "qa/data/ga_electricity_substations.geojson", theme: "Critical Infrastructure", scale: "national" },
    { key: "nsw_foi_building_complexes", title: "NSW FOI Building Complexes", kind: "circle", color: "#16a34a", path: "qa/data/nsw_foi_building_complexes.geojson", theme: "Emergency & Health Facilities", scale: "state", radius: 4 },
    { key: "next_lga_boundaries_asgs2025", title: "ABS LGA Boundaries (ASGS 2025)", kind: "fill", color: "#006973", path: "qa/data/next_lga_boundaries_asgs2025.geojson", theme: "NExT Administrative", scale: "national", hollow: true },
    { key: "next_sa2_boundaries_asgs2021", title: "ABS SA2 Boundaries (ASGS 2021)", kind: "fill", color: "#7c3aed", path: "qa/data/next_sa2_boundaries_asgs2021.geojson", theme: "NExT Population & Geography", scale: "national", hollow: true, dash: true },
    { key: "nsw_lga_boundaries", title: "NSW LGA Boundaries (Spatial Services)", kind: "fill", color: "#0b2545", path: "qa/data/nsw_lga_boundaries.geojson", theme: "Administrative Boundaries", scale: "state", hollow: true },
    { key: "nsw_rfs_major_incidents_live", title: "NSW RFS Major Incidents (Live)", kind: "circle", color: "#dc2626", path: "qa/data/nsw_rfs_major_incidents_live.geojson", theme: "Live Hazard Feeds", scale: "state", radius: 7 },
    { key: "ga_major_power_stations", title: "GA Major Power Stations", kind: "circle", color: "#7c3aed", path: "qa/data/ga_major_power_stations.geojson", theme: "Critical Infrastructure", scale: "national", radius: 5 },
    { key: "ga_seismic_hazard_pga_10pct", title: "NSHA 2018 Seismic PGA Contours", kind: "line", color: "#be185d", path: "qa/data/ga_seismic_hazard_pga_10pct.geojson", theme: "Hazards", scale: "national", dash: true },
    // ---------- AURA Linked Datasets (Zero Storage Duplication) ----------
    { key: "national_healthcare_nhsd_v2", title: "AURA: National Hospitals (NHSD)", kind: "circle", color: "#059669", endpoint: "https://portal.spatial.nsw.gov.au/server/rest/services/NSW_Features_of_Interest_Category/FeatureServer/3", theme: "AURA: Sensitive Receptors", scale: "national", radius: 5 },
    { key: "national_schools_acara_v2", title: "AURA: National Schools (ACARA)", kind: "circle", color: "#2563eb", endpoint: "https://portal.spatial.nsw.gov.au/server/rest/services/NSW_Features_of_Interest_Category/FeatureServer/3", theme: "AURA: Sensitive Receptors", scale: "national", radius: 4 },
    { key: "qld_transmission_grid_v2", title: "AURA: QLD Transmission Grid", kind: "line", color: "#f59e0b", endpoint: "https://services.ga.gov.au/gis/rest/services/Electricity_Infrastructure/MapServer/2", theme: "AURA: Transmission Grid", scale: "state" },
    { key: "national_cyclone_hazard_tcha_v2", title: "AURA: Tropical Cyclone Hazard (TCHA)", kind: "line", color: "#06b6d4", endpoint: "https://services.ga.gov.au/gis/rest/services/National_Seismic_Hazard_Assessment_2018/MapServer/15", theme: "AURA: Cyclone Hazard", scale: "national", dash: true },
    { key: "nsw_coastal_inundation_hazard_v2", title: "AURA: NSW Coastal Inundation & Surge", kind: "fill", color: "#0284c7", endpoint: "https://portal.spatial.nsw.gov.au/server/rest/services/NSW_Water_Theme/FeatureServer/7", theme: "AURA: Coastal Hazard", scale: "state", opacity: 0.45 }
  ];
  const BY_KEY = Object.fromEntries(CATALOG.map(c => [c.key, c]));
  const TITLE_FIELDS = ["feature_name", "title", "incident_title", "LGA_NAME_2025", "lga_name", "lganame", "sa2_name_2021", "hydroname", "cell_id", "contour_id", "generalname", "name"];
  const HIDDEN_PROP = k => k === "__fid" || k.startsWith("_bbox");
  const BASEMAPS = {
    "osm-standard": { label: "OSM Standard", tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"], attr: "© OpenStreetMap contributors" },
    "osm-hot": { label: "OSM Humanitarian", tiles: ["https://a.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png"], attr: "© OpenStreetMap contributors, HOT" },
    "esri-imagery": { label: "Esri Imagery", tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"], attr: "Imagery © Esri" },
    "dark-canvas": { label: "Dark Canvas", tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}"], attr: "© Esri" },
    "white-canvas": { label: "White Canvas", tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}"], attr: "© Esri" }
  };
  const EXTENTS = {
    hunter: [[151.45, -32.95], [151.82, -32.68]],
    nsw: [[141.0, -37.5], [153.6, -28.1]],
    australia: [[112.9, -43.7], [153.7, -10.0]]
  };

  // ---------- State ----------
  let map = null;
  let qaIndex = {};
  let mode = "identify";
  let showAll = false;
  let activeBasemap = "osm-standard";
  let basemapOpacity = 1;
  let popup = null;
  let dockKey = null;
  let pending = null;
  const state = {}; // key -> { data, loading, visible, opacity, inList }
  let order = [];   // top-first list of keys in the layer control

  CATALOG.forEach(c => { state[c.key] = { data: null, loading: null, visible: false, opacity: c.hollow ? 0.08 : (c.kind === "fill" ? 0.42 : 1), inList: false }; });

  fetch("qa/data/qa_summary.json")
    .then(r => r.json())
    .then(s => { (s.datasets || []).forEach(d => { qaIndex[d.dataset_key] = d; }); renderLayerControl(); })
    .catch(err => console.warn("qa_summary.json not loaded:", err));

  const $ = id => document.getElementById(id);
  const esc = v => String(v === null || v === undefined ? "" : v).replace(/[&<>"']/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
  const mapIds = key => {
    const c = BY_KEY[key];
    if (c.kind === "fill") return [`L-${key}-fill`, `L-${key}-outline`];
    if (c.kind === "line") return [`L-${key}-line`];
    return [`L-${key}-circle`];
  };
  const hitIds = key => {
    const c = BY_KEY[key];
    if (c.kind === "fill") return c.hollow ? [`L-${key}-fill`, `L-${key}-outline`] : [`L-${key}-fill`];
    return mapIds(key);
  };

  // ---------- Data loading & geometry helpers ----------
  function loadData(key) {
    const st = state[key];
    if (st.data) return Promise.resolve(st.data);
    if (st.loading) return st.loading;
    const c = BY_KEY[key];
    const fetchUrl = c.path ? c.path : (c.endpoint.replace(/\/+$/, '') + '/query?where=1%3D1&outFields=*&returnGeometry=true&outSR=4326&f=geojson&resultRecordCount=2000');
    st.loading = fetch(fetchUrl)
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status} for ${fetchUrl}`); return r.json(); })
      .then(data => {
        let gj = data;
        if (data && data.features && data.type !== "FeatureCollection") {
          // Normalize Esri JSON format to GeoJSON FeatureCollection
          gj = {
            type: "FeatureCollection",
            features: data.features.map(f => {
              let geom = null;
              if (f.geometry) {
                if (f.geometry.x !== undefined && f.geometry.y !== undefined) {
                  geom = { type: "Point", coordinates: [f.geometry.x, f.geometry.y] };
                } else if (f.geometry.paths) {
                  geom = { type: f.geometry.paths.length === 1 ? "LineString" : "MultiLineString", coordinates: f.geometry.paths.length === 1 ? f.geometry.paths[0] : f.geometry.paths };
                } else if (f.geometry.rings) {
                  geom = { type: f.geometry.rings.length === 1 ? "Polygon" : "MultiPolygon", coordinates: f.geometry.rings.length === 1 ? f.geometry.rings : [f.geometry.rings] };
                }
              }
              return { type: "Feature", properties: f.attributes || {}, geometry: geom };
            })
          };
        }
        (gj.features || []).forEach((f, i) => { f.properties = f.properties || {}; f.properties.__fid = i; });
        st.data = gj;
        return gj;
      })
      .catch(err => { st.loading = null; console.error(err); throw err; });
    return st.loading;
  }

  function flattenCoords(coords, out) {
    if (typeof coords[0] === "number") { out.push(coords); return out; }
    coords.forEach(c => flattenCoords(c, out));
    return out;
  }
  function geomBounds(geom) {
    if (!geom) return null;
    const geoms = geom.type === "GeometryCollection" ? geom.geometries : [geom];
    const pts = [];
    geoms.forEach(g => g && g.coordinates && flattenCoords(g.coordinates, pts));
    if (!pts.length) return null;
    let [x0, y0, x1, y1] = [Infinity, Infinity, -Infinity, -Infinity];
    pts.forEach(([x, y]) => { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); });
    return [[x0, y0], [x1, y1]];
  }
  function layerBounds(key) {
    const d = state[key].data;
    if (!d) return null;
    let b = null;
    d.features.forEach(f => {
      const fb = geomBounds(f.geometry);
      if (!fb) return;
      b = b ? [[Math.min(b[0][0], fb[0][0]), Math.min(b[0][1], fb[0][1])], [Math.max(b[1][0], fb[1][0]), Math.max(b[1][1], fb[1][1])]] : fb;
    });
    return b;
  }
  function geomTypes(key) {
    const d = state[key].data;
    if (!d) return [];
    return [...new Set(d.features.map(f => f.geometry && f.geometry.type).filter(Boolean))];
  }
  function featureTitle(key, props) {
    for (const f of TITLE_FIELDS) if (props[f] !== undefined && props[f] !== null && String(props[f]).trim()) return String(props[f]);
    return `${BY_KEY[key].title} #${props.__fid}`;
  }

  // ---------- Map layer management ----------
  function ensureMapLayers(key) {
    if (!map || map.getSource(`S-${key}`)) return;
    const c = BY_KEY[key];
    const st = state[key];
    map.addSource(`S-${key}`, { type: "geojson", data: st.data });
    if (c.kind === "fill") {
      map.addLayer({
        id: `L-${key}-fill`, type: "fill", source: `S-${key}`,
        paint: Object.assign({ "fill-color": c.color, "fill-opacity": st.opacity }, c.paint || {})
      });
      const outline = { "line-color": c.paint ? "#001026" : c.color, "line-width": c.hollow ? 2 : 1, "line-opacity": 1 };
      if (c.dash) outline["line-dasharray"] = [3, 2];
      map.addLayer({ id: `L-${key}-outline`, type: "line", source: `S-${key}`, paint: outline });
    } else if (c.kind === "line") {
      const p = { "line-color": c.color, "line-width": 2.2, "line-opacity": st.opacity };
      if (c.dash) p["line-dasharray"] = [3, 2];
      map.addLayer({ id: `L-${key}-line`, type: "line", source: `S-${key}`, paint: p });
    } else {
      map.addLayer({
        id: `L-${key}-circle`, type: "circle", source: `S-${key}`,
        paint: {
          "circle-radius": c.radius || 6, "circle-color": c.color, "circle-opacity": st.opacity,
          "circle-stroke-width": 1.5, "circle-stroke-color": "#ffffff", "circle-stroke-opacity": st.opacity
        }
      });
    }
  }

  function applyVisibility(key) {
    if (!map) return;
    mapIds(key).forEach(id => { if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", state[key].visible ? "visible" : "none"); });
  }

  function applyOpacity(key) {
    if (!map) return;
    const c = BY_KEY[key];
    const o = state[key].opacity;
    if (c.kind === "fill") {
      if (map.getLayer(`L-${key}-fill`)) map.setPaintProperty(`L-${key}-fill`, "fill-opacity", o);
      if (map.getLayer(`L-${key}-outline`)) map.setPaintProperty(`L-${key}-outline`, "line-opacity", c.hollow ? Math.max(0.15, Math.min(1, o * 8)) : Math.max(0.15, Math.min(1, o * 2)));
    } else if (c.kind === "line") {
      if (map.getLayer(`L-${key}-line`)) map.setPaintProperty(`L-${key}-line`, "line-opacity", o);
    } else if (map.getLayer(`L-${key}-circle`)) {
      map.setPaintProperty(`L-${key}-circle`, "circle-opacity", o);
      map.setPaintProperty(`L-${key}-circle`, "circle-stroke-opacity", o);
    }
  }

  // Draw order: polygons bottom, then lines, then points; within that, the layer-control order (top-first).
  function applyOrder() {
    if (!map) return;
    const rank = { fill: 0, line: 1, circle: 2 };
    const bottomFirst = order.slice().reverse().sort((a, b) => rank[BY_KEY[a].kind] - rank[BY_KEY[b].kind]);
    bottomFirst.forEach(k => mapIds(k).forEach(id => { if (map.getLayer(id)) map.moveLayer(id); }));

    // Keep Tuffs Territory / AOI Focus Mask and boundary on top of data layers
    if (map.getLayer("territory-mask-fill")) map.moveLayer("territory-mask-fill");
    if (map.getLayer("aoi-boundary-line")) map.moveLayer("aoi-boundary-line");

    ["oic-hl-fill", "oic-hl-line", "oic-hl-point"].forEach(id => { if (map.getLayer(id)) map.moveLayer(id); });
  }

  async function setVisible(key, visible, opts) {
    const st = state[key];
    st.visible = visible;
    if (visible) {
      st.inList = true;
      if (!order.includes(key)) order.unshift(key);
      renderLayerControl();
      try { await loadData(key); } catch (e) { st.visible = false; renderLayerControl(); alert(`Could not load ${BY_KEY[key].title}: ${e.message}`); return; }
      ensureMapLayers(key);
      applyOrder();
      if (opts && opts.zoom) zoomToLayer(key);
    }
    applyVisibility(key);
    afterChange();
  }

  function removeFromList(key) {
    state[key].visible = false;
    state[key].inList = false;
    order = order.filter(k => k !== key);
    applyVisibility(key);
    if (dockKey === key) dockKey = null;
    afterChange();
  }

  function afterChange() {
    renderLayerControl();
    renderLegend();
    refreshDockSelect();
    const anyVisible = CATALOG.some(c => state[c.key].visible);
    const overlay = $("mapEmptyOverlay");
    if (overlay && anyVisible) overlay.style.display = "none";
  }

  function zoomToLayer(key) {
    const b = layerBounds(key);
    if (b && map) map.fitBounds(b, { padding: 40, maxZoom: 13, duration: 700 });
  }

  // ---------- Basemaps ----------
  function installBasemaps() {
    Object.entries(BASEMAPS).forEach(([id, bm]) => {
      if (id === "osm-standard") return; // installed by app.js map style
      map.addSource(id, { type: "raster", tiles: bm.tiles, tileSize: 256, attribution: bm.attr });
      map.addLayer({ id: `${id}-layer`, type: "raster", source: id, layout: { visibility: "none" } });
    });
  }
  function setBasemap(id) {
    activeBasemap = id;
    Object.keys(BASEMAPS).forEach(b => {
      const lid = `${b}-layer`;
      if (map && map.getLayer(lid)) map.setLayoutProperty(lid, "visibility", b === id ? "visible" : "none");
    });
    setBasemapOpacity(basemapOpacity);
    if ($("basemapLabel")) $("basemapLabel").textContent = BASEMAPS[id].label;
  }
  function setBasemapOpacity(o) {
    basemapOpacity = o;
    const lid = `${activeBasemap}-layer`;
    if (map && map.getLayer(lid)) map.setPaintProperty(lid, "raster-opacity", o);
  }

  // ---------- Tuffs-Style Territory / AOI Focus Mask (#030712 @ 80% Opacity) ----------
  const DEFAULT_HUNTER_AOI_WKT =
    "POLYGON ((151.79677994467662 -32.81913824355183, 151.78397271217995 -32.82029275994482, 151.7726097748274 -32.825222751525864, 151.76982765107 -32.8295542986488, 151.7715143673733 -32.83154661495801, 151.7736883388699 -32.83660964116112, 151.77043816949327 -32.84175382709676, 151.76633422689753 -32.84059984932129, 151.76443347799463 -32.84215919648963, 151.7602722812743 -32.842867296375566, 151.74421211977642 -32.843063553762725, 151.74145444097448 -32.843935444319655, 151.74369442247482 -32.84437906260999, 151.73954665466962 -32.84406935728741, 151.7440268521305 -32.84552967054209, 151.74373571084186 -32.84577034398082, 151.74204220866488 -32.845725694875966, 151.74181992953098 -32.845881094584264, 151.75259536778938 -32.84549255933217, 151.75311654246946 -32.84582679965913, 151.7521811959344 -32.84607632947809, 151.7552171530484 -32.84724986711033, 151.75247880060147 -32.84666650014506, 151.75388222779006 -32.84826960974522, 151.75601342330947 -32.84861825476914, 151.75715134622934 -32.85485542719534, 151.76869721291308 -32.85517563849434, 151.77376474777137 -32.85627575246893, 151.7756692704968 -32.85838266373424, 151.77970852001897 -32.8664385121965, 151.7777537365534 -32.86822683514129, 151.7760223883535 -32.86839791268702, 151.7764484646827 -32.87231350399591, 151.77545253935807 -32.87238006184951, 151.77739804592167 -32.87423117737012, 151.78073798843624 -32.87434952005207, 151.7789989317929 -32.875020097432724, 151.77925117782635 -32.87772934381088, 151.78176345935051 -32.881420056376456, 151.78324367183467 -32.88236529007135, 151.78415427786857 -32.889162586325924, 151.78291820771568 -32.89405244572854, 151.77768060829936 -32.90179613224216, 151.77485085047573 -32.902307124050104, 151.77372929486032 -32.9013553821394, 151.77334969736398 -32.8944421191881, 151.77460862514926 -32.88957848754901, 151.76251680824993 -32.8856558323314, 151.76044595885634 -32.88909843986314, 151.76460527180956 -32.89165304851319, 151.7680285896606 -32.894877535433416, 151.76931762717751 -32.897303618754556, 151.7716700445137 -32.913722859714206, 151.77333364267324 -32.91804447503354, 151.7769593123302 -32.923448060688784, 151.77415926987783 -32.922887516469544, 151.7723943965515 -32.91975848686534, 151.77136568182073 -32.91967780230686, 151.7702547487836 -32.91632884110931, 151.7685624117215 -32.91677993532892, 151.76854566712458 -32.921446359171064, 151.766928063606 -32.92263652507709, 151.76527794736228 -32.92270129874724, 151.76527742723775 -32.92100559151838, 151.76424524321337 -32.92206483831959, 151.76157121642905 -32.91762719326368, 151.7598113988211 -32.917611793170906, 151.7615814527317 -32.922699559153926, 151.7650322356742 -32.92524752598405, 151.77324084760266 -32.92479340149, 151.78166368976017 -32.9256243983137, 151.78551423917378 -32.92552514970958, 151.78713786679472 -32.9247431497577, 151.78521851737548 -32.92023973625069, 151.78186088882964 -32.91945962756841, 151.7802147970384 -32.918303784969645, 151.77976079837524 -32.91697699059947, 151.7792294134437 -32.917242450303796, 151.77761125386783 -32.91142569658315, 151.78038481668065 -32.90638286648878, 151.78650226651035 -32.89929435712408, 151.78602028263123 -32.89889728014649, 151.79100296442434 -32.890899814073336, 151.79395431012006 -32.88345055919914, 151.79375550665947 -32.882857367516316, 151.79196017415686 -32.884326518719405, 151.78951042615623 -32.88479151611785, 151.78911038210566 -32.88580892841249, 151.78889001099347 -32.88320389707869, 151.79134759409996 -32.882024004057065, 151.79256823658613 -32.88310266666914, 151.79429197425895 -32.87937398260146, 151.79346958278597 -32.872833406441906, 151.78977134991536 -32.86563784914153, 151.7902726601495 -32.86069864288168, 151.79281631533496 -32.85646491022585, 151.8024382961073 -32.85137495614685, 151.80596088857706 -32.84817781828668, 151.80856479017538 -32.84503123731239, 151.80856849303098 -32.8438321169918, 151.81170241681662 -32.84070709377984, 151.81417420677934 -32.839510088744056, 151.8185786133797 -32.83115038941542, 151.817054746366 -32.823944192291826, 151.80869080584344 -32.820563122564586, 151.79677994467662 -32.81913824355183))";
  let aoiMaskEnabled = true;
  let currentAoiGeometry = null;

  function ensureRingWinding(ring, wantClockwise) {
    if (!ring || ring.length < 3) return ring;
    let sum = 0;
    for (let i = 0; i < ring.length - 1; i++) {
      sum += (ring[i + 1][0] - ring[i][0]) * (ring[i + 1][1] + ring[i][1]);
    }
    const isClockwise = sum > 0;
    if (wantClockwise && !isClockwise) return ring.slice().reverse();
    if (!wantClockwise && isClockwise) return ring.slice().reverse();
    return ring;
  }

  function parseWktPolygon(wkt) {
    if (!wkt || typeof wkt !== "string") return null;
    const clean = wkt.trim();
    let match = clean.match(/POLYGON\s*\(\s*\(([\s\S]+?)\)\s*\)/i);
    if (match) {
      const coords = match[1].split(",").map(pair => {
        const parts = pair.trim().split(/\s+/).map(Number);
        return [parts[0], parts[1]];
      }).filter(pt => !isNaN(pt[0]) && !isNaN(pt[1]));
      if (coords.length > 2) {
        const first = coords[0];
        const last = coords[coords.length - 1];
        if (first[0] !== last[0] || first[1] !== last[1]) {
          coords.push([first[0], first[1]]);
        }
        return { type: "Polygon", coordinates: [coords] };
      }
    }
    let mMulti = clean.match(/MULTIPOLYGON\s*\(\s*\(\s*\(([\s\S]+?)\)\s*\)\s*\)/i);
    if (mMulti) {
      const coords = mMulti[1].split(",").map(pair => {
        const parts = pair.trim().split(/\s+/).map(Number);
        return [parts[0], parts[1]];
      }).filter(pt => !isNaN(pt[0]) && !isNaN(pt[1]));
      if (coords.length > 2) {
        return { type: "MultiPolygon", coordinates: [[coords]] };
      }
    }
    return null;
  }

  // ---------- Metric Buffer & Simplification Tolerance Parsers ----------
  function extractBufferMeters(str) {
    if (!str || typeof str !== "string") return 0;
    const m = str.match(/(?:buffer|catchment|proximity|radius|within)(?:\s*(?:of|is|:))?\s*(\d+(?:\.\d+)?)\s*(km|m|meters|metres|kilometres|kilometers)?/i) ||
              str.match(/(\d+(?:\.\d+)?)\s*(km|m|meters|metres|kilometres|kilometers)\s*(?:buffer|catchment|proximity|radius)?/i);
    if (!m) return 0;
    const val = parseFloat(m[1]);
    const isKm = (m[2] || "").toLowerCase().startsWith("k");
    return isKm ? val * 1000 : val;
  }

  function extractSimplificationTolerance(str) {
    if (!str || typeof str !== "string") return 6;
    const m = str.match(/(?:simplif(?:y|ication)|tolerance|tolerance:|smooth(?:ing)?|fillet)(?:\s*(?:of|is|:))?\s*(\d+(?:\.\d+)?)\s*(m|km|%|deg)?/i) ||
              str.match(/(\d+(?:\.\d+)?)\s*(m|km|%|deg)\s*(?:simplif(?:y|ication)|tolerance|smoothing)?/i);
    if (!m) return 6;
    const val = parseFloat(m[1]);
    if (val >= 100 || val >= 0.01 || val >= 20) return 3;
    if (val <= 10 || val <= 0.001) return 10;
    return 6;
  }

  // ---------- Smoothed Extent Polygon Generator (Rounded Corners & Metric Buffering) ----------
  function createSmoothedExtentPolygon(bbox, numArcPoints = 6, bufferMeters = 0, filletFraction = 0.12) {
    if (!bbox || bbox.length !== 4) return null;
    let [minX, minY, maxX, maxY] = bbox;

    // Apply metric buffer expansion if specified (111,320m per lat degree)
    if (bufferMeters > 0) {
      const dLat = bufferMeters / 111320.0;
      const midLat = (minY + maxY) / 2.0;
      const dLon = bufferMeters / (111320.0 * Math.max(0.2, Math.cos(midLat * Math.PI / 180.0)));
      minX -= dLon;
      maxX += dLon;
      minY -= dLat;
      maxY += dLat;
    }

    const w = maxX - minX;
    const h = maxY - minY;
    // Fillet radius: fraction of shorter dimension
    const r = Math.min(w, h) * Math.max(0.01, Math.min(0.35, filletFraction));
    const ring = [];

    function addArc(cx, cy, startAng, endAng) {
      for (let i = 0; i <= numArcPoints; i++) {
        const ang = startAng + (endAng - startAng) * (i / numArcPoints);
        const x = parseFloat((cx + r * Math.cos(ang)).toFixed(5));
        const y = parseFloat((cy + r * Math.sin(ang)).toFixed(5));
        ring.push([x, y]);
      }
    }

    // Top-left arc: PI down to PI/2
    addArc(minX + r, maxY - r, Math.PI, Math.PI / 2);
    // Top-right arc: PI/2 down to 0
    addArc(maxX - r, maxY - r, Math.PI / 2, 0);
    // Bottom-right arc: 2*PI down to 1.5*PI
    addArc(maxX - r, minY + r, 2 * Math.PI, 1.5 * Math.PI);
    // Bottom-left arc: 1.5*PI down to PI
    addArc(minX + r, minY + r, 1.5 * Math.PI, Math.PI);

    // Close ring
    if (ring[0][0] !== ring[ring.length - 1][0] || ring[0][1] !== ring[ring.length - 1][1]) {
      ring.push([ring[0][0], ring[0][1]]);
    }

    return {
      type: "Polygon",
      coordinates: [ring]
    };
  }

  const STATE_CODES = {
    "new south wales": "NSW", "nsw": "NSW",
    "victoria": "VIC", "vic": "VIC",
    "queensland": "QLD", "qld": "QLD",
    "western australia": "WA", "wa": "WA",
    "south australia": "SA", "sa": "SA",
    "tasmania": "TAS", "tas": "TAS",
    "northern territory": "NT", "nt": "NT",
    "australian capital territory": "ACT", "act": "ACT"
  };

  // Authoritative Australian Administrative & Locality Gazetteer (ABS ASGS 2025/2021 & GA)
  // Embedded 575 Australian LGAs, major cities, and regions (synchronous zero-latency access)
  const EMBEDDED_LGA_GAZETTEER = JSON.parse("{\"nsw\":{\"name\":\"New South Wales\",\"state\":\"NSW\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[141.0,-37.5,153.6,-28.1],\"center\":[149.5,-32.6]},\"new south wales\":{\"name\":\"New South Wales\",\"state\":\"NSW\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[141.0,-37.5,153.6,-28.1],\"center\":[149.5,-32.6]},\"vic\":{\"name\":\"Victoria\",\"state\":\"VIC\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[140.9,-39.2,149.9,-33.9],\"center\":[145.0,-37.0]},\"victoria\":{\"name\":\"Victoria\",\"state\":\"VIC\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[140.9,-39.2,149.9,-33.9],\"center\":[145.0,-37.0]},\"qld\":{\"name\":\"Queensland\",\"state\":\"QLD\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[137.9,-29.2,153.6,-9.1],\"center\":[144.5,-22.5]},\"queensland\":{\"name\":\"Queensland\",\"state\":\"QLD\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[137.9,-29.2,153.6,-9.1],\"center\":[144.5,-22.5]},\"wa\":{\"name\":\"Western Australia\",\"state\":\"WA\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[112.9,-35.2,129.0,-13.7],\"center\":[122.0,-25.0]},\"western australia\":{\"name\":\"Western Australia\",\"state\":\"WA\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[112.9,-35.2,129.0,-13.7],\"center\":[122.0,-25.0]},\"sa\":{\"name\":\"South Australia\",\"state\":\"SA\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[129.0,-38.1,141.0,-25.9],\"center\":[135.0,-30.0]},\"south australia\":{\"name\":\"South Australia\",\"state\":\"SA\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[129.0,-38.1,141.0,-25.9],\"center\":[135.0,-30.0]},\"tas\":{\"name\":\"Tasmania\",\"state\":\"TAS\",\"stateCode\":\"TAS\",\"isState\":false,\"bbox\":[143.8,-43.7,148.5,-39.5],\"center\":[146.5,-42.0]},\"tasmania\":{\"name\":\"Tasmania\",\"state\":\"TAS\",\"stateCode\":\"TAS\",\"isState\":false,\"bbox\":[143.8,-43.7,148.5,-39.5],\"center\":[146.5,-42.0]},\"nt\":{\"name\":\"Northern Territory\",\"state\":\"NT\",\"stateCode\":\"NT\",\"isState\":false,\"bbox\":[129.0,-26.0,138.0,-10.8],\"center\":[133.5,-19.5]},\"northern territory\":{\"name\":\"Northern Territory\",\"state\":\"NT\",\"stateCode\":\"NT\",\"isState\":false,\"bbox\":[129.0,-26.0,138.0,-10.8],\"center\":[133.5,-19.5]},\"act\":{\"name\":\"Australian Capital Territory\",\"state\":\"ACT\",\"stateCode\":\"ACT\",\"isState\":false,\"bbox\":[148.7,-35.9,149.4,-35.1],\"center\":[149.1,-35.3]},\"australian capital territory\":{\"name\":\"Australian Capital Territory\",\"state\":\"ACT\",\"stateCode\":\"ACT\",\"isState\":false,\"bbox\":[148.7,-35.9,149.4,-35.1],\"center\":[149.1,-35.3]},\"australia\":{\"name\":\"Australia National\",\"state\":\"AUS\",\"stateCode\":\"AUS\",\"isState\":false,\"bbox\":[112.9,-43.7,153.7,-10.0],\"center\":[134.5,-25.5]},\"australia national\":{\"name\":\"Australia National\",\"state\":\"AUS\",\"stateCode\":\"AUS\",\"isState\":false,\"bbox\":[112.9,-43.7,153.7,-10.0],\"center\":[134.5,-25.5]},\"sydney\":{\"name\":\"Greater Sydney\",\"state\":\"NSW\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[150.6,-34.15,151.35,-33.6],\"center\":[151.2,-33.87]},\"greater sydney\":{\"name\":\"Greater Sydney\",\"state\":\"NSW\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[150.6,-34.15,151.35,-33.6],\"center\":[151.2,-33.87]},\"melbourne\":{\"name\":\"Greater Melbourne\",\"state\":\"VIC\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[144.5,-38.25,145.5,-37.5],\"center\":[144.96,-37.81]},\"greater melbourne\":{\"name\":\"Greater Melbourne\",\"state\":\"VIC\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[144.5,-38.25,145.5,-37.5],\"center\":[144.96,-37.81]},\"brisbane\":{\"name\":\"Greater Brisbane\",\"state\":\"QLD\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[152.65,-27.75,153.35,-27.05],\"center\":[153.02,-27.47]},\"greater brisbane\":{\"name\":\"Greater Brisbane\",\"state\":\"QLD\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[152.65,-27.75,153.35,-27.05],\"center\":[153.02,-27.47]},\"perth\":{\"name\":\"Greater Perth\",\"state\":\"WA\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.55,-32.35,116.15,-31.65],\"center\":[115.86,-31.95]},\"adelaide\":{\"name\":\"Greater Adelaide\",\"state\":\"SA\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[138.4,-35.25,138.8,-34.65],\"center\":[138.6,-34.93]},\"hobart\":{\"name\":\"Greater Hobart\",\"state\":\"TAS\",\"stateCode\":\"TAS\",\"isState\":false,\"bbox\":[147.15,-43.05,147.5,-42.75],\"center\":[147.33,-42.88]},\"darwin\":{\"name\":\"Greater Darwin\",\"state\":\"NT\",\"stateCode\":\"NT\",\"isState\":false,\"bbox\":[130.75,-12.55,131.05,-12.3],\"center\":[130.84,-12.46]},\"canberra\":{\"name\":\"Canberra\",\"state\":\"ACT\",\"stateCode\":\"ACT\",\"isState\":false,\"bbox\":[148.95,-35.45,149.25,-35.15],\"center\":[149.13,-35.28]},\"hunter\":{\"name\":\"Lower Hunter Floodplain\",\"state\":\"NSW\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[151.45,-32.95,151.82,-32.68],\"center\":[151.63,-32.79]},\"lower hunter\":{\"name\":\"Lower Hunter Floodplain\",\"state\":\"NSW\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[151.45,-32.95,151.82,-32.68],\"center\":[151.63,-32.79]},\"central coast\":{\"name\":\"Central Coast\",\"state\":\"NSW\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[151.1,-33.6,151.6,-33.1],\"center\":[151.35,-33.35]},\"wollongong\":{\"name\":\"Wollongong / Illawarra\",\"state\":\"NSW\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[150.75,-34.55,151.0,-34.3],\"center\":[150.89,-34.42]},\"gold coast\":{\"name\":\"Gold Coast\",\"state\":\"QLD\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[153.25,-28.25,153.55,-27.8],\"center\":[153.4,-28.0]},\"sunshine coast\":{\"name\":\"Sunshine Coast\",\"state\":\"QLD\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[152.85,-26.9,153.15,-26.4],\"center\":[153.05,-26.65]},\"geelong\":{\"name\":\"Geelong\",\"state\":\"VIC\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[144.2,-38.25,144.5,-38.05],\"center\":[144.36,-38.15]},\"townsville\":{\"name\":\"Townsville\",\"state\":\"QLD\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[146.65,-19.38,146.9,-19.18],\"center\":[146.81,-19.26]},\"cairns\":{\"name\":\"Cairns\",\"state\":\"QLD\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[145.65,-17.05,145.85,-16.8],\"center\":[145.77,-16.92]},\"huon valley\":{\"name\":\"Huon Valley\",\"state\":\"Tasmania\",\"stateCode\":\"TAS\",\"isState\":false,\"bbox\":[145.9151,-43.7405,147.216,-42.8472],\"center\":[146.5656,-43.2938]},\"kingborough\":{\"name\":\"Kingborough\",\"state\":\"Tasmania\",\"stateCode\":\"TAS\",\"isState\":false,\"bbox\":[147.0917,-43.5296,147.4333,-42.898],\"center\":[147.2625,-43.2138]},\"tasman\":{\"name\":\"Tasman\",\"state\":\"Tasmania\",\"stateCode\":\"TAS\",\"isState\":false,\"bbox\":[147.6184,-43.2466,148.057,-42.8422],\"center\":[147.8377,-43.0444]},\"clarence\":{\"name\":\"Clarence\",\"state\":\"Tasmania\",\"stateCode\":\"TAS\",\"isState\":false,\"bbox\":[147.2811,-43.0721,147.6134,-42.6752],\"center\":[147.4472,-42.8736]},\"glenorchy\":{\"name\":\"Glenorchy\",\"state\":\"Tasmania\",\"stateCode\":\"TAS\",\"isState\":false,\"bbox\":[147.1354,-42.9133,147.3237,-42.7504],\"center\":[147.2296,-42.8319]},\"derwent valley\":{\"name\":\"Derwent Valley\",\"state\":\"Tasmania\",\"stateCode\":\"TAS\",\"isState\":false,\"bbox\":[145.8325,-43.1188,147.2269,-42.4888],\"center\":[146.5297,-42.8038]},\"sorell\":{\"name\":\"Sorell\",\"state\":\"Tasmania\",\"stateCode\":\"TAS\",\"isState\":false,\"bbox\":[147.4529,-42.9137,147.9369,-42.6697],\"center\":[147.6949,-42.7917]},\"brighton\":{\"name\":\"Brighton\",\"state\":\"Tasmania\",\"stateCode\":\"TAS\",\"isState\":false,\"bbox\":[147.0917,-42.7981,147.393,-42.6554],\"center\":[147.2423,-42.7267]},\"west coast\":{\"name\":\"West Coast\",\"state\":\"Tasmania\",\"stateCode\":\"TAS\",\"isState\":false,\"bbox\":[144.911,-43.3226,146.1343,-41.5823],\"center\":[145.5226,-42.4524]},\"southern midlands\":{\"name\":\"Southern Midlands\",\"state\":\"Tasmania\",\"stateCode\":\"TAS\",\"isState\":false,\"bbox\":[147.0117,-42.7187,147.8565,-42.117],\"center\":[147.4341,-42.4179]},\"glamorgan-spring bay\":{\"name\":\"Glamorgan-Spring Bay\",\"state\":\"Tasmania\",\"stateCode\":\"TAS\",\"isState\":false,\"bbox\":[147.5743,-42.7426,148.3593,-41.814],\"center\":[147.9668,-42.2783]},\"central highlands (tas.)\":{\"name\":\"Central Highlands (Tas.)\",\"state\":\"Tasmania\",\"stateCode\":\"TAS\",\"isState\":false,\"bbox\":[145.9998,-42.6927,147.2789,-41.7003],\"center\":[146.6393,-42.1965]},\"northern midlands\":{\"name\":\"Northern Midlands\",\"state\":\"Tasmania\",\"stateCode\":\"TAS\",\"isState\":false,\"bbox\":[146.7693,-42.2813,148.1462,-41.4785],\"center\":[147.4577,-41.8799]},\"meander valley\":{\"name\":\"Meander Valley\",\"state\":\"Tasmania\",\"stateCode\":\"TAS\",\"isState\":false,\"bbox\":[145.9513,-41.9745,147.1401,-41.3245],\"center\":[146.5457,-41.6495]},\"kentish\":{\"name\":\"Kentish\",\"state\":\"Tasmania\",\"stateCode\":\"TAS\",\"isState\":false,\"bbox\":[145.852,-41.6846,146.5025,-41.2421],\"center\":[146.1773,-41.4634]},\"break o'day\":{\"name\":\"Break O'Day\",\"state\":\"Tasmania\",\"stateCode\":\"TAS\",\"isState\":false,\"bbox\":[147.5906,-41.8822,148.3591,-40.8992],\"center\":[147.9749,-41.3907]},\"launceston\":{\"name\":\"Launceston\",\"state\":\"Tasmania\",\"stateCode\":\"TAS\",\"isState\":false,\"bbox\":[146.9766,-41.5562,147.6481,-41.0858],\"center\":[147.3123,-41.321]},\"waratah-wynyard\":{\"name\":\"Waratah-Wynyard\",\"state\":\"Tasmania\",\"stateCode\":\"TAS\",\"isState\":false,\"bbox\":[145.0627,-41.7076,145.8535,-40.9065],\"center\":[145.4581,-41.3071]},\"central coast (tas.)\":{\"name\":\"Central Coast (Tas.)\",\"state\":\"Tasmania\",\"stateCode\":\"TAS\",\"isState\":false,\"bbox\":[145.8452,-41.4659,146.2731,-41.0741],\"center\":[146.0591,-41.27]},\"west tamar\":{\"name\":\"West Tamar\",\"state\":\"Tasmania\",\"stateCode\":\"TAS\",\"isState\":false,\"bbox\":[146.6584,-41.4655,147.124,-41.0633],\"center\":[146.8912,-41.2644]},\"latrobe (tas.)\":{\"name\":\"Latrobe (Tas.)\",\"state\":\"Tasmania\",\"stateCode\":\"TAS\",\"isState\":false,\"bbox\":[146.3478,-41.378,146.7621,-41.0925],\"center\":[146.555,-41.2353]},\"devonport\":{\"name\":\"Devonport\",\"state\":\"Tasmania\",\"stateCode\":\"TAS\",\"isState\":false,\"bbox\":[146.2414,-41.2718,146.4066,-41.154],\"center\":[146.324,-41.2129]},\"burnie\":{\"name\":\"Burnie\",\"state\":\"Tasmania\",\"stateCode\":\"TAS\",\"isState\":false,\"bbox\":[145.6376,-41.3563,145.9852,-41.0367],\"center\":[145.8114,-41.1965]},\"george town\":{\"name\":\"George Town\",\"state\":\"Tasmania\",\"stateCode\":\"TAS\",\"isState\":false,\"bbox\":[146.7865,-41.2594,147.2481,-40.9802],\"center\":[147.0173,-41.1198]},\"dorset\":{\"name\":\"Dorset\",\"state\":\"Tasmania\",\"stateCode\":\"TAS\",\"isState\":false,\"bbox\":[147.1995,-41.3808,148.2638,-40.7151],\"center\":[147.7317,-41.048]},\"circular head\":{\"name\":\"Circular Head\",\"state\":\"Tasmania\",\"stateCode\":\"TAS\",\"isState\":false,\"bbox\":[144.6041,-41.6687,145.5633,-40.3711],\"center\":[145.0837,-41.0199]},\"flinders (tas.)\":{\"name\":\"Flinders (Tas.)\",\"state\":\"Tasmania\",\"stateCode\":\"TAS\",\"isState\":false,\"bbox\":[146.3806,-40.5943,148.4987,-39.2036],\"center\":[147.4397,-39.8989]},\"king island\":{\"name\":\"King Island\",\"state\":\"Tasmania\",\"stateCode\":\"TAS\",\"isState\":false,\"bbox\":[143.8189,-40.165,144.1641,-39.5792],\"center\":[143.9915,-39.8721]},\"south gippsland\":{\"name\":\"South Gippsland\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[145.6057,-39.1367,146.5284,-38.2612],\"center\":[146.067,-38.6989]},\"bass coast\":{\"name\":\"Bass Coast\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[145.1095,-38.6788,145.8184,-38.2913],\"center\":[145.464,-38.4851]},\"colac otway\":{\"name\":\"Colac Otway\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[143.2471,-38.8577,143.9461,-38.0197],\"center\":[143.5966,-38.4387]},\"warrnambool\":{\"name\":\"Warrnambool\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[142.4224,-38.4501,142.621,-38.3062],\"center\":[142.5217,-38.3781]},\"surf coast\":{\"name\":\"Surf Coast\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[143.8245,-38.5794,144.4061,-38.1005],\"center\":[144.1153,-38.34]},\"mornington peninsula\":{\"name\":\"Mornington Peninsula\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[144.6514,-38.503,145.2617,-38.1624],\"center\":[144.9565,-38.3327]},\"queenscliffe\":{\"name\":\"Queenscliffe\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[144.6008,-38.2922,144.7021,-38.2376],\"center\":[144.6515,-38.2649]},\"latrobe (vic.)\":{\"name\":\"Latrobe (Vic.)\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[146.2105,-38.5364,146.7122,-37.9714],\"center\":[146.4613,-38.2539]},\"corangamite\":{\"name\":\"Corangamite\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[142.8146,-38.773,143.6563,-37.6589],\"center\":[143.2355,-38.216]},\"moyne\":{\"name\":\"Moyne\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[141.8171,-38.6101,143.1073,-37.7655],\"center\":[142.4622,-38.1878]},\"frankston\":{\"name\":\"Frankston\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[145.0979,-38.2006,145.2396,-38.0674],\"center\":[145.1687,-38.134]},\"casey\":{\"name\":\"Casey\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[145.2149,-38.2485,145.4307,-37.9419],\"center\":[145.3228,-38.0952]},\"cardinia\":{\"name\":\"Cardinia\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[145.364,-38.3324,145.7651,-37.8577],\"center\":[145.5645,-38.0951]},\"greater geelong\":{\"name\":\"Greater Geelong\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[144.2025,-38.3026,144.7202,-37.8009],\"center\":[144.4613,-38.0517]},\"wellington\":{\"name\":\"Wellington\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[146.3112,-38.9553,147.7227,-37.12],\"center\":[147.017,-38.0376]},\"kingston (vic.)\":{\"name\":\"Kingston (Vic.)\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[145.0344,-38.085,145.1563,-37.924],\"center\":[145.0953,-38.0045]},\"greater dandenong\":{\"name\":\"Greater Dandenong\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[145.1296,-38.0777,145.2519,-37.9245],\"center\":[145.1908,-38.0011]},\"unincorporated vic\":{\"name\":\"Unincorporated Vic\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[141.9935,-39.1592,149.9185,-36.8364],\"center\":[145.956,-37.9978]},\"baw baw\":{\"name\":\"Baw Baw\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[145.7008,-38.36,146.5873,-37.58],\"center\":[146.144,-37.97]},\"bayside (vic.)\":{\"name\":\"Bayside (Vic.)\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[144.9834,-37.9964,145.0553,-37.8833],\"center\":[145.0193,-37.9398]},\"glen eira\":{\"name\":\"Glen Eira\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[144.9968,-37.9387,145.0852,-37.8602],\"center\":[145.041,-37.8995]},\"knox\":{\"name\":\"Knox\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[145.1909,-37.9649,145.3476,-37.833],\"center\":[145.2692,-37.8989]},\"monash\":{\"name\":\"Monash\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[145.0742,-37.9401,145.2201,-37.8533],\"center\":[145.1472,-37.8967]},\"wyndham\":{\"name\":\"Wyndham\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[144.4441,-38.0046,144.8274,-37.781],\"center\":[144.6358,-37.8928]},\"glenelg\":{\"name\":\"Glenelg\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[140.9658,-38.433,141.919,-37.3487],\"center\":[141.4424,-37.8909]},\"stonnington\":{\"name\":\"Stonnington\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[144.9833,-37.893,145.0922,-37.8296],\"center\":[145.0378,-37.8613]},\"port phillip\":{\"name\":\"Port Phillip\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[144.9125,-37.8917,145.0105,-37.8257],\"center\":[144.9615,-37.8587]},\"hobsons bay\":{\"name\":\"Hobsons Bay\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[144.7514,-37.9,144.9155,-37.8138],\"center\":[144.8334,-37.8569]},\"golden plains\":{\"name\":\"Golden Plains\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[143.4406,-38.1467,144.2865,-37.5579],\"center\":[143.8635,-37.8523]},\"grant\":{\"name\":\"Grant\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[140.2928,-38.0626,140.9736,-37.6102],\"center\":[140.6332,-37.8364]},\"whitehorse\":{\"name\":\"Whitehorse\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[145.0951,-37.8652,145.2135,-37.7921],\"center\":[145.1543,-37.8286]},\"boroondara\":{\"name\":\"Boroondara\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[144.9993,-37.8759,145.1067,-37.7768],\"center\":[145.053,-37.8264]},\"mount gambier\":{\"name\":\"Mount Gambier\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[140.7376,-37.8551,140.8262,-37.7943],\"center\":[140.7819,-37.8247]},\"yarra\":{\"name\":\"Yarra\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[144.9615,-37.8345,145.0453,-37.7753],\"center\":[145.0034,-37.8049]},\"maroondah\":{\"name\":\"Maroondah\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[145.2133,-37.8439,145.3187,-37.7618],\"center\":[145.266,-37.8028]},\"maribyrnong\":{\"name\":\"Maribyrnong\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[144.8392,-37.827,144.9165,-37.7558],\"center\":[144.8779,-37.7914]},\"manningham\":{\"name\":\"Manningham\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[145.0671,-37.8118,145.2939,-37.7024],\"center\":[145.1805,-37.7571]},\"yarra ranges\":{\"name\":\"Yarra Ranges\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[145.2817,-37.975,146.1925,-37.5251],\"center\":[145.7371,-37.7501]},\"moonee valley\":{\"name\":\"Moonee Valley\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[144.8461,-37.7896,144.9404,-37.7092],\"center\":[144.8933,-37.7494]},\"brimbank\":{\"name\":\"Brimbank\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[144.7444,-37.8228,144.8885,-37.6629],\"center\":[144.8165,-37.7429]},\"darebin\":{\"name\":\"Darebin\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[144.9703,-37.7856,145.0754,-37.691],\"center\":[145.0229,-37.7383]},\"merri-bek\":{\"name\":\"Merri-bek\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[144.8862,-37.7802,144.9887,-37.6909],\"center\":[144.9375,-37.7356]},\"banyule\":{\"name\":\"Banyule\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[145.0278,-37.7851,145.1437,-37.6826],\"center\":[145.0858,-37.7339]},\"melton\":{\"name\":\"Melton\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[144.4777,-37.8104,144.7682,-37.5524],\"center\":[144.623,-37.6814]},\"moorabool\":{\"name\":\"Moorabool\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[143.8827,-37.8641,144.5562,-37.4025],\"center\":[144.2194,-37.6333]},\"nillumbik\":{\"name\":\"Nillumbik\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[145.0677,-37.7417,145.3664,-37.4877],\"center\":[145.2171,-37.6147]},\"hume\":{\"name\":\"Hume\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[144.6324,-37.7124,144.9778,-37.4819],\"center\":[144.8051,-37.5971]},\"whittlesea\":{\"name\":\"Whittlesea\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[144.9465,-37.7,145.241,-37.4017],\"center\":[145.0938,-37.5508]},\"southern grampians\":{\"name\":\"Southern Grampians\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[141.4315,-37.9732,142.6191,-37.0873],\"center\":[142.0253,-37.5302]},\"ballarat\":{\"name\":\"Ballarat\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[143.595,-37.716,143.9507,-37.3217],\"center\":[143.7729,-37.5189]},\"wattle range\":{\"name\":\"Wattle Range\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[139.8684,-37.84,140.9739,-37.176],\"center\":[140.4212,-37.508]},\"ararat\":{\"name\":\"Ararat\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[142.3535,-37.8366,143.2913,-37.1419],\"center\":[142.8224,-37.4892]},\"east gippsland\":{\"name\":\"East Gippsland\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[147.189,-38.0787,149.9762,-36.6124],\"center\":[148.5826,-37.3456]},\"macedon ranges\":{\"name\":\"Macedon Ranges\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[144.3104,-37.5677,144.9212,-37.0991],\"center\":[144.6158,-37.3334]},\"pyrenees\":{\"name\":\"Pyrenees\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[143.0609,-37.7574,143.6686,-36.8977],\"center\":[143.3648,-37.3276]},\"hepburn\":{\"name\":\"Hepburn\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[143.6481,-37.4865,144.419,-37.1476],\"center\":[144.0335,-37.317]},\"murrindindi\":{\"name\":\"Murrindindi\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[145.1627,-37.6242,146.186,-36.9379],\"center\":[145.6744,-37.2811]},\"mansfield\":{\"name\":\"Mansfield\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[145.6487,-37.6294,146.6471,-36.8532],\"center\":[146.1479,-37.2413]},\"robe\":{\"name\":\"Robe\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[139.7205,-37.3398,140.2437,-37.0325],\"center\":[139.9821,-37.1861]},\"mitchell\":{\"name\":\"Mitchell\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[144.5304,-37.5154,145.4296,-36.8353],\"center\":[144.98,-37.1753]},\"mount alexander\":{\"name\":\"Mount Alexander\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[143.8306,-37.2702,144.5459,-36.8819],\"center\":[144.1882,-37.0761]},\"naracoorte lucindale\":{\"name\":\"Naracoorte Lucindale\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[140.0838,-37.3219,140.972,-36.669],\"center\":[140.5279,-36.9954]},\"central goldfields\":{\"name\":\"Central Goldfields\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[143.4634,-37.2367,144.0138,-36.7211],\"center\":[143.7386,-36.9789]},\"northern grampians\":{\"name\":\"Northern Grampians\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[142.2347,-37.2939,143.511,-36.4053],\"center\":[142.8728,-36.8496]},\"alpine\":{\"name\":\"Alpine\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[146.5665,-37.2755,147.3923,-36.3927],\"center\":[146.9794,-36.8341]},\"horsham\":{\"name\":\"Horsham\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[141.6577,-37.2245,142.5713,-36.4327],\"center\":[142.1145,-36.8286]},\"bega valley\":{\"name\":\"Bega Valley\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[149.3565,-37.5051,150.0848,-36.1278],\"center\":[149.7207,-36.8165]},\"strathbogie\":{\"name\":\"Strathbogie\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[144.7848,-37.0234,145.874,-36.4246],\"center\":[145.3294,-36.724]},\"greater bendigo\":{\"name\":\"Greater Bendigo\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[144.0259,-37.0604,144.8536,-36.3852],\"center\":[144.4398,-36.7228]},\"kingston (sa)\":{\"name\":\"Kingston (SA)\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[139.6701,-37.0329,140.4318,-36.2487],\"center\":[140.051,-36.6408]},\"wangaratta\":{\"name\":\"Wangaratta\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[146.131,-37.1631,146.7258,-36.0694],\"center\":[146.4284,-36.6163]},\"west wimmera\":{\"name\":\"West Wimmera\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[140.9631,-37.4499,141.8377,-35.7485],\"center\":[141.4004,-36.5992]},\"benalla\":{\"name\":\"Benalla\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[145.7754,-36.9258,146.2808,-36.255],\"center\":[146.0281,-36.5904]},\"greater shepparton\":{\"name\":\"Greater Shepparton\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[145.0319,-36.7005,145.7985,-36.154],\"center\":[145.4152,-36.4273]},\"snowy monaro\":{\"name\":\"Snowy Monaro\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[148.2007,-37.2628,149.6026,-35.5793],\"center\":[148.9017,-36.4211]},\"loddon\":{\"name\":\"Loddon\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[143.3152,-36.9022,144.3441,-35.9059],\"center\":[143.8297,-36.404]},\"towong\":{\"name\":\"Towong\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[147.0337,-36.8032,148.2207,-35.9285],\"center\":[147.6272,-36.3658]},\"campaspe\":{\"name\":\"Campaspe\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[144.2593,-36.7626,145.1576,-35.8841],\"center\":[144.7084,-36.3233]},\"tatiara\":{\"name\":\"Tatiara\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[140.0461,-36.7024,140.9689,-35.7422],\"center\":[140.5075,-36.2223]},\"indigo\":{\"name\":\"Indigo\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[146.1752,-36.4592,147.1974,-35.9582],\"center\":[146.6863,-36.2087]},\"wodonga\":{\"name\":\"Wodonga\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[146.7025,-36.2596,147.0739,-36.0297],\"center\":[146.8882,-36.1446]},\"moira\":{\"name\":\"Moira\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[144.8298,-36.2992,146.2466,-35.802],\"center\":[145.5382,-36.0506]},\"hindmarsh\":{\"name\":\"Hindmarsh\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[141.2266,-36.5674,142.239,-35.4984],\"center\":[141.7328,-36.0329]},\"yarriambiack\":{\"name\":\"Yarriambiack\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[141.9922,-36.7615,142.8168,-35.2909],\"center\":[142.4045,-36.0262]},\"albury\":{\"name\":\"Albury\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[146.8145,-36.116,147.0992,-35.9139],\"center\":[146.9569,-36.0149]},\"snowy valleys\":{\"name\":\"Snowy Valleys\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[147.6874,-36.8061,148.8087,-35.0801],\"center\":[148.248,-35.9431]},\"eurobodalla\":{\"name\":\"Eurobodalla\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[149.543,-36.3656,150.3126,-35.5005],\"center\":[149.9278,-35.9331]},\"buloke\":{\"name\":\"Buloke\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[142.5353,-36.4999,143.5687,-35.1928],\"center\":[143.052,-35.8464]},\"kangaroo island\":{\"name\":\"Kangaroo Island\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[136.5329,-36.0866,138.3036,-35.5612],\"center\":[137.4183,-35.8239]},\"greater hume\":{\"name\":\"Greater Hume\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[146.4971,-36.0682,147.8976,-35.4485],\"center\":[147.1974,-35.7584]},\"berrigan\":{\"name\":\"Berrigan\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[145.332,-35.9918,146.0077,-35.512],\"center\":[145.6698,-35.7519]},\"gannawarra\":{\"name\":\"Gannawarra\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[143.2881,-36.0183,144.4182,-35.4459],\"center\":[143.8531,-35.7321]},\"coorong\":{\"name\":\"Coorong\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[138.8781,-36.2539,140.5204,-35.1829],\"center\":[139.6993,-35.7184]},\"unincorporated act\":{\"name\":\"Unincorporated ACT\",\"state\":\"Australian Capital Territory\",\"stateCode\":\"ACT\",\"isState\":false,\"bbox\":[148.7628,-35.9205,149.3993,-35.1244],\"center\":[149.0811,-35.5224]},\"victor harbor\":{\"name\":\"Victor Harbor\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[138.4373,-35.643,138.6549,-35.3891],\"center\":[138.5461,-35.516]},\"yankalilla\":{\"name\":\"Yankalilla\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[138.0939,-35.6651,138.5907,-35.3227],\"center\":[138.3423,-35.4939]},\"federation\":{\"name\":\"Federation\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[145.9441,-36.0508,146.7109,-34.8734],\"center\":[146.3275,-35.4621]},\"queanbeyan-palerang\":{\"name\":\"Queanbeyan-Palerang\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[149.1315,-36.0092,150.2157,-34.9022],\"center\":[149.6736,-35.4557]},\"southern mallee\":{\"name\":\"Southern Mallee\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[140.0744,-35.748,140.9662,-34.9867],\"center\":[140.5203,-35.3674]},\"alexandrina\":{\"name\":\"Alexandrina\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[138.5158,-35.5624,139.1583,-35.1128],\"center\":[138.8371,-35.3376]},\"lockhart\":{\"name\":\"Lockhart\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[146.3542,-35.5758,147.2329,-35.068],\"center\":[146.7935,-35.3219]},\"edward river\":{\"name\":\"Edward River\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[144.0487,-35.7273,145.5984,-34.7403],\"center\":[144.8236,-35.2338]},\"murray river\":{\"name\":\"Murray River\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[143.3172,-36.1299,145.3637,-34.3307],\"center\":[144.3405,-35.2303]},\"murray bridge\":{\"name\":\"Murray Bridge\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[139.0194,-35.4717,139.6224,-34.9287],\"center\":[139.3209,-35.2002]},\"onkaparinga\":{\"name\":\"Onkaparinga\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[138.4421,-35.3503,138.7134,-35.0233],\"center\":[138.5778,-35.1868]},\"wagga wagga\":{\"name\":\"Wagga Wagga\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[146.7788,-35.5636,147.9314,-34.8081],\"center\":[147.3551,-35.1859]},\"shoalhaven\":{\"name\":\"Shoalhaven\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[149.9773,-35.6446,150.8498,-34.6386],\"center\":[150.4135,-35.1416]},\"swan hill\":{\"name\":\"Swan Hill\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[142.5171,-35.6548,143.8191,-34.5464],\"center\":[143.1681,-35.1006]},\"mount barker\":{\"name\":\"Mount Barker\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[138.6947,-35.2433,139.044,-34.8948],\"center\":[138.8693,-35.069]},\"marion\":{\"name\":\"Marion\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[138.4857,-35.0933,138.5762,-34.9585],\"center\":[138.531,-35.0259]},\"murrumbidgee\":{\"name\":\"Murrumbidgee\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[145.178,-35.5886,146.2297,-34.4349],\"center\":[145.7038,-35.0117]},\"mitcham\":{\"name\":\"Mitcham\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[138.563,-35.0505,138.6814,-34.9633],\"center\":[138.6222,-35.0069]},\"holdfast bay\":{\"name\":\"Holdfast Bay\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[138.5086,-35.0422,138.5378,-34.9627],\"center\":[138.5232,-35.0024]},\"unley\":{\"name\":\"Unley\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[138.5719,-34.9673,138.6441,-34.9406],\"center\":[138.608,-34.954]},\"burnside\":{\"name\":\"Burnside\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[138.6157,-34.9762,138.701,-34.9127],\"center\":[138.6583,-34.9445]},\"west torrens\":{\"name\":\"West Torrens\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[138.503,-34.9759,138.5829,-34.9091],\"center\":[138.5429,-34.9425]},\"karoonda east murray\":{\"name\":\"Karoonda East Murray\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[139.6196,-35.2918,140.4301,-34.5651],\"center\":[140.0249,-34.9284]},\"yass valley\":{\"name\":\"Yass Valley\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[148.5223,-35.3169,149.4226,-34.5356],\"center\":[148.9724,-34.9262]},\"denmark\":{\"name\":\"Denmark\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[116.7247,-35.0678,117.4884,-34.7533],\"center\":[117.1065,-34.9106]},\"norwood payneham and st peters\":{\"name\":\"Norwood Payneham and St Peters\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[138.6128,-34.933,138.6583,-34.883],\"center\":[138.6355,-34.908]},\"goulburn mulwaree\":{\"name\":\"Goulburn Mulwaree\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[149.4705,-35.2563,150.3335,-34.5487],\"center\":[149.902,-34.9025]},\"charles sturt\":{\"name\":\"Charles Sturt\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[138.4757,-34.9514,138.5879,-34.8499],\"center\":[138.5318,-34.9006]},\"adelaide hills\":{\"name\":\"Adelaide Hills\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[138.6652,-35.1216,139.044,-34.6805],\"center\":[138.8546,-34.901]},\"walkerville\":{\"name\":\"Walkerville\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[138.5973,-34.9095,138.6352,-34.8793],\"center\":[138.6162,-34.8944]},\"prospect\":{\"name\":\"Prospect\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[138.5808,-34.8992,138.62,-34.8699],\"center\":[138.6004,-34.8846]},\"campbelltown (sa)\":{\"name\":\"Campbelltown (SA)\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[138.6471,-34.9139,138.7238,-34.857],\"center\":[138.6855,-34.8854]},\"mildura\":{\"name\":\"Mildura\",\"state\":\"Victoria\",\"stateCode\":\"VIC\",\"isState\":false,\"bbox\":[140.9619,-35.7486,142.743,-33.9806],\"center\":[141.8525,-34.8646]},\"port adelaide enfield\":{\"name\":\"Port Adelaide Enfield\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[138.4758,-34.8895,138.6695,-34.763],\"center\":[138.5727,-34.8263]},\"junee\":{\"name\":\"Junee\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[147.3127,-35.0973,147.95,-34.533],\"center\":[147.6313,-34.8152]},\"cootamundra-gundagai\":{\"name\":\"Cootamundra-Gundagai\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[147.6861,-35.2821,148.5831,-34.3365],\"center\":[148.1346,-34.8093]},\"tea tree gully\":{\"name\":\"Tea Tree Gully\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[138.6597,-34.8692,138.7802,-34.7342],\"center\":[138.7199,-34.8017]},\"salisbury\":{\"name\":\"Salisbury\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[138.517,-34.8444,138.6993,-34.6921],\"center\":[138.6081,-34.7683]},\"albany\":{\"name\":\"Albany\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[117.3321,-35.192,118.9149,-34.2849],\"center\":[118.1235,-34.7385]},\"yorke peninsula\":{\"name\":\"Yorke Peninsula\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[136.8219,-35.3782,138.1278,-34.0849],\"center\":[137.4749,-34.7315]},\"port lincoln\":{\"name\":\"Port Lincoln\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[135.8213,-34.7697,135.8936,-34.6874],\"center\":[135.8575,-34.7285]},\"kiama\":{\"name\":\"Kiama\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[150.5999,-34.7922,150.8655,-34.5989],\"center\":[150.7327,-34.6955]},\"playford\":{\"name\":\"Playford\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[138.4357,-34.7754,138.8481,-34.613],\"center\":[138.6419,-34.6942]},\"plantagenet\":{\"name\":\"Plantagenet\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[116.7848,-34.8512,118.4103,-34.3991],\"center\":[117.5976,-34.6251]},\"gawler\":{\"name\":\"Gawler\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[138.68,-34.6705,138.7845,-34.5717],\"center\":[138.7323,-34.6211]},\"barossa\":{\"name\":\"Barossa\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[138.7515,-34.8153,139.1719,-34.4117],\"center\":[138.9617,-34.6135]},\"coolamon\":{\"name\":\"Coolamon\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[146.7918,-34.9073,147.4824,-34.2935],\"center\":[147.1371,-34.6004]},\"manjimup\":{\"name\":\"Manjimup\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.6745,-35.0689,116.8568,-34.1268],\"center\":[116.2656,-34.5979]},\"narrandera\":{\"name\":\"Narrandera\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[146.1524,-35.0984,146.9116,-34.0837],\"center\":[146.532,-34.591]},\"shellharbour\":{\"name\":\"Shellharbour\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[150.6379,-34.6432,150.9045,-34.5373],\"center\":[150.7712,-34.5902]},\"leeton\":{\"name\":\"Leeton\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[146.0216,-34.725,146.5167,-34.3342],\"center\":[146.2691,-34.5296]},\"adelaide plains\":{\"name\":\"Adelaide Plains\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[138.2252,-34.6763,138.6304,-34.3444],\"center\":[138.4278,-34.5104]},\"wingecarribee\":{\"name\":\"Wingecarribee\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[149.964,-34.7693,150.7457,-34.2126],\"center\":[150.3548,-34.4909]},\"lower eyre\":{\"name\":\"Lower Eyre\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[135.028,-35.0375,136.3743,-33.9385],\"center\":[135.7011,-34.488]},\"loxton waikerie\":{\"name\":\"Loxton Waikerie\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[139.6006,-35.0196,140.9656,-33.9319],\"center\":[140.2831,-34.4757]},\"upper lachlan\":{\"name\":\"Upper Lachlan\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[148.938,-34.9495,150.1232,-33.8878],\"center\":[149.5306,-34.4186]},\"mid murray\":{\"name\":\"Mid Murray\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[138.9751,-35.0305,139.8577,-33.8006],\"center\":[139.4164,-34.4156]},\"hilltops\":{\"name\":\"Hilltops\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[147.7108,-34.9072,149.131,-33.9241],\"center\":[148.4209,-34.4156]},\"light\":{\"name\":\"Light\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[138.56,-34.632,139.1274,-34.1875],\"center\":[138.8437,-34.4098]},\"temora\":{\"name\":\"Temora\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[147.0829,-34.6597,147.8755,-34.1065],\"center\":[147.4792,-34.3831]},\"griffith\":{\"name\":\"Griffith\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[145.7348,-34.5701,146.3114,-34.0989],\"center\":[146.0231,-34.3345]},\"cranbrook\":{\"name\":\"Cranbrook\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[116.669,-34.5797,117.9889,-34.0886],\"center\":[117.3289,-34.3342]},\"berri barmera\":{\"name\":\"Berri Barmera\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[140.3202,-34.4563,140.667,-34.1194],\"center\":[140.4936,-34.2878]},\"tumby bay\":{\"name\":\"Tumby Bay\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[135.7774,-34.5438,136.4956,-33.8501],\"center\":[136.1365,-34.197]},\"hay\":{\"name\":\"Hay\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[143.9011,-34.8523,145.2595,-33.4623],\"center\":[144.5803,-34.1573]},\"renmark paringa\":{\"name\":\"Renmark Paringa\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[140.5865,-34.3234,140.9637,-33.9627],\"center\":[140.7751,-34.1431]},\"nannup\":{\"name\":\"Nannup\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.3365,-34.4854,116.011,-33.7839],\"center\":[115.6737,-34.1347]},\"augusta margaret river\":{\"name\":\"Augusta Margaret River\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[114.976,-34.4252,115.6696,-33.8051],\"center\":[115.3228,-34.1151]},\"gnowangerup\":{\"name\":\"Gnowangerup\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[117.8543,-34.4056,118.7425,-33.7675],\"center\":[118.2984,-34.0866]},\"campbelltown (nsw)\":{\"name\":\"Campbelltown (NSW)\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[150.7368,-34.1896,150.9408,-33.9582],\"center\":[150.8388,-34.0739]},\"sutherland\":{\"name\":\"Sutherland\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[150.9223,-34.1723,151.2319,-33.9717],\"center\":[151.0771,-34.072]},\"wollondilly\":{\"name\":\"Wollondilly\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[150.0147,-34.3374,150.9108,-33.8017],\"center\":[150.4627,-34.0695]},\"balranald\":{\"name\":\"Balranald\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[142.4523,-34.9724,144.6892,-33.1157],\"center\":[143.5708,-34.044]},\"jerramungup\":{\"name\":\"Jerramungup\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[118.6068,-34.5352,119.6205,-33.5258],\"center\":[119.1137,-34.0305]},\"camden\":{\"name\":\"Camden\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[150.6278,-34.0934,150.8226,-33.9388],\"center\":[150.7252,-34.0161]},\"clare and gilbert valleys\":{\"name\":\"Clare and Gilbert Valleys\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[138.531,-34.3706,138.9758,-33.6586],\"center\":[138.7534,-34.0146]},\"broomehill-tambellup\":{\"name\":\"Broomehill-Tambellup\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[117.3168,-34.2579,117.9888,-33.7686],\"center\":[117.6528,-34.0132]},\"wakefield\":{\"name\":\"Wakefield\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[138.0844,-34.389,138.7047,-33.6258],\"center\":[138.3945,-34.0074]},\"bridgetown-greenbushes\":{\"name\":\"Bridgetown-Greenbushes\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.9458,-34.2018,116.5043,-33.7806],\"center\":[116.2251,-33.9912]},\"georges river\":{\"name\":\"Georges River\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[151.0333,-34.006,151.138,-33.9391],\"center\":[151.0856,-33.9725]},\"bayside (nsw)\":{\"name\":\"Bayside (NSW)\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[151.1008,-34.006,151.2317,-33.9192],\"center\":[151.1662,-33.9626]},\"liverpool\":{\"name\":\"Liverpool\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[150.6177,-34.0411,150.994,-33.864],\"center\":[150.8059,-33.9526]},\"randwick\":{\"name\":\"Randwick\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[151.2089,-34.0018,151.2716,-33.8896],\"center\":[151.2403,-33.9457]},\"copper coast\":{\"name\":\"Copper Coast\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[137.5079,-34.0976,137.9186,-33.7881],\"center\":[137.7133,-33.9428]},\"kojonup\":{\"name\":\"Kojonup\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[116.72,-34.2179,117.3596,-33.633],\"center\":[117.0398,-33.9254]},\"canterbury-bankstown\":{\"name\":\"Canterbury-Bankstown\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[150.966,-33.9836,151.1553,-33.8641],\"center\":[151.0607,-33.9239]},\"bland\":{\"name\":\"Bland\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[146.0703,-34.3172,147.7841,-33.5208],\"center\":[146.9272,-33.919]},\"inner west\":{\"name\":\"Inner West\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[151.1123,-33.934,151.1966,-33.8455],\"center\":[151.1544,-33.8897]},\"boyup brook\":{\"name\":\"Boyup Brook\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[116.1952,-34.2576,116.8425,-33.5135],\"center\":[116.5189,-33.8855]},\"burwood\":{\"name\":\"Burwood\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[151.089,-33.9037,151.1207,-33.8671],\"center\":[151.1048,-33.8854]},\"waverley\":{\"name\":\"Waverley\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[151.2409,-33.9111,151.2863,-33.857],\"center\":[151.2636,-33.8841]},\"strathfield\":{\"name\":\"Strathfield\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[151.0547,-33.9096,151.0945,-33.85],\"center\":[151.0746,-33.8798]},\"weddin\":{\"name\":\"Weddin\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[147.507,-34.1432,148.5159,-33.6137],\"center\":[148.0114,-33.8785]},\"fairfield\":{\"name\":\"Fairfield\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[150.8116,-33.9142,150.9905,-33.8206],\"center\":[150.901,-33.8674]},\"woollahra\":{\"name\":\"Woollahra\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[151.2192,-33.8909,151.2879,-33.8325],\"center\":[151.2536,-33.8617]},\"canada bay\":{\"name\":\"Canada Bay\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[151.078,-33.8743,151.1662,-33.8228],\"center\":[151.1221,-33.8486]},\"oberon\":{\"name\":\"Oberon\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[149.3947,-34.2059,150.2412,-33.4847],\"center\":[149.8179,-33.8453]},\"cumberland\":{\"name\":\"Cumberland\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[150.9089,-33.8882,151.0664,-33.7851],\"center\":[150.9876,-33.8366]},\"north sydney\":{\"name\":\"North Sydney\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[151.1874,-33.8527,151.233,-33.8157],\"center\":[151.2102,-33.8342]},\"hunters hill\":{\"name\":\"Hunters Hill\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[151.1267,-33.8449,151.1803,-33.8148],\"center\":[151.1535,-33.8299]},\"mosman\":{\"name\":\"Mosman\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[151.2284,-33.8536,151.2689,-33.8033],\"center\":[151.2486,-33.8285]},\"lane cove\":{\"name\":\"Lane Cove\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[151.1423,-33.8434,151.1983,-33.803],\"center\":[151.1703,-33.8232]},\"cowra\":{\"name\":\"Cowra\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[148.3092,-34.0972,149.2577,-33.5255],\"center\":[148.7835,-33.8114]},\"parramatta\":{\"name\":\"Parramatta\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[150.9476,-33.8583,151.0973,-33.757],\"center\":[151.0224,-33.8076]},\"willoughby\":{\"name\":\"Willoughby\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[151.1426,-33.8248,151.2331,-33.7785],\"center\":[151.1878,-33.8017]},\"ryde\":{\"name\":\"Ryde\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[151.065,-33.8418,151.1591,-33.7612],\"center\":[151.1121,-33.8015]},\"barunga west\":{\"name\":\"Barunga West\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[137.7013,-34.1216,138.1449,-33.4681],\"center\":[137.9231,-33.7948]},\"penrith\":{\"name\":\"Penrith\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[150.588,-33.8832,150.8235,-33.6123],\"center\":[150.7057,-33.7477]},\"blacktown\":{\"name\":\"Blacktown\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[150.7596,-33.834,150.9653,-33.6463],\"center\":[150.8625,-33.7401]},\"ku-ring-gai\":{\"name\":\"Ku-ring-gai\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[151.09,-33.7944,151.2075,-33.6596],\"center\":[151.1488,-33.727]},\"goyder\":{\"name\":\"Goyder\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[138.6751,-34.3352,139.358,-33.0976],\"center\":[139.0165,-33.7164]},\"donnybrook-balingup\":{\"name\":\"Donnybrook-Balingup\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.7158,-33.964,116.2398,-33.4403],\"center\":[115.9778,-33.7022]},\"northern beaches\":{\"name\":\"Northern Beaches\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[151.1608,-33.8239,151.343,-33.5718],\"center\":[151.2519,-33.6979]},\"busselton\":{\"name\":\"Busselton\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[114.9747,-33.8397,115.7669,-33.5298],\"center\":[115.3708,-33.6848]},\"ravensthorpe\":{\"name\":\"Ravensthorpe\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[119.431,-34.2884,120.8759,-33.079],\"center\":[120.1534,-33.6837]},\"wentworth\":{\"name\":\"Wentworth\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[141.0017,-34.5936,143.6718,-32.7485],\"center\":[142.3367,-33.6711]},\"cleve\":{\"name\":\"Cleve\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[135.9069,-33.993,136.6712,-33.3275],\"center\":[136.2891,-33.6603]},\"blue mountains\":{\"name\":\"Blue Mountains\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[150.166,-33.9006,150.6598,-33.3635],\"center\":[150.4129,-33.632]},\"carrathool\":{\"name\":\"Carrathool\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[144.3577,-34.5799,146.4928,-32.6712],\"center\":[145.4253,-33.6256]},\"katanning\":{\"name\":\"Katanning\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[117.3271,-33.7882,117.9523,-33.4612],\"center\":[117.6397,-33.6247]},\"blayney\":{\"name\":\"Blayney\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[148.839,-33.8124,149.4221,-33.4207],\"center\":[149.1305,-33.6165]},\"franklin harbour\":{\"name\":\"Franklin Harbour\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[136.6705,-33.8774,137.3856,-33.3259],\"center\":[137.0281,-33.6016]},\"the hills\":{\"name\":\"The Hills\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[150.8697,-33.7744,151.0499,-33.378],\"center\":[150.9598,-33.5762]},\"elliston\":{\"name\":\"Elliston\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[134.24,-34.0095,135.9081,-33.1383],\"center\":[135.074,-33.5739]},\"hornsby\":{\"name\":\"Hornsby\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[150.9718,-33.7657,151.2471,-33.3792],\"center\":[151.1094,-33.5725]},\"kent\":{\"name\":\"Kent\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[117.9068,-33.8047,119.4328,-33.2742],\"center\":[118.6698,-33.5395]},\"capel\":{\"name\":\"Capel\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.4533,-33.6728,115.7829,-33.3812],\"center\":[115.6181,-33.527]},\"woodanilling\":{\"name\":\"Woodanilling\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[116.9803,-33.6549,117.6913,-33.3843],\"center\":[117.3358,-33.5196]},\"esperance\":{\"name\":\"Esperance\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[120.0853,-34.4742,124.2137,-32.5647],\"center\":[122.1495,-33.5195]},\"bathurst\":{\"name\":\"Bathurst\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[149.117,-33.9976,149.9222,-32.9486],\"center\":[149.5196,-33.4731]},\"west arthur\":{\"name\":\"West Arthur\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[116.2657,-33.7008,117.1061,-33.1802],\"center\":[116.6859,-33.4405]},\"dardanup\":{\"name\":\"Dardanup\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.6902,-33.5421,116.058,-33.2901],\"center\":[115.8741,-33.4161]},\"forbes\":{\"name\":\"Forbes\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[147.2968,-33.7205,148.4318,-33.0373],\"center\":[147.8643,-33.3789]},\"port pirie\":{\"name\":\"Port Pirie\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[137.8108,-33.6263,138.4033,-33.104],\"center\":[138.1071,-33.3651]},\"bunbury\":{\"name\":\"Bunbury\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.6097,-33.4088,115.7146,-33.3009],\"center\":[115.6621,-33.3548]},\"hawkesbury\":{\"name\":\"Hawkesbury\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[150.4302,-33.6855,151.1356,-32.9961],\"center\":[150.7829,-33.3408]},\"orange\":{\"name\":\"Orange\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[149.0095,-33.4393,149.2365,-33.2174],\"center\":[149.123,-33.3284]},\"lithgow\":{\"name\":\"Lithgow\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[149.7519,-33.7606,150.6198,-32.8798],\"center\":[150.1859,-33.3202]},\"central coast (nsw)\":{\"name\":\"Central Coast (NSW)\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[150.9841,-33.5706,151.6306,-33.0437],\"center\":[151.3073,-33.3072]},\"northern areas\":{\"name\":\"Northern Areas\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[138.1637,-33.6591,138.7912,-32.9423],\"center\":[138.4775,-33.3007]},\"wagin\":{\"name\":\"Wagin\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[117.0831,-33.5179,117.6879,-33.0318],\"center\":[117.3855,-33.2749]},\"collie\":{\"name\":\"Collie\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.9186,-33.5525,116.4124,-32.9946],\"center\":[116.1655,-33.2736]},\"dumbleyung\":{\"name\":\"Dumbleyung\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[117.6206,-33.4855,118.3545,-32.9502],\"center\":[117.9875,-33.2178]},\"harvey\":{\"name\":\"Harvey\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.6585,-33.3788,116.2091,-32.9219],\"center\":[115.9338,-33.1504]},\"lake grace\":{\"name\":\"Lake Grace\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[118.2597,-33.5403,120.5815,-32.7179],\"center\":[119.4206,-33.1291]},\"cabonne\":{\"name\":\"Cabonne\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[148.2902,-33.6143,149.3637,-32.6073],\"center\":[148.827,-33.1108]},\"williams\":{\"name\":\"Williams\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[116.3891,-33.3434,117.0298,-32.7609],\"center\":[116.7095,-33.0521]},\"whyalla\":{\"name\":\"Whyalla\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[137.2788,-33.3261,137.8115,-32.7651],\"center\":[137.5451,-33.0456]},\"lake macquarie\":{\"name\":\"Lake Macquarie\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[151.3315,-33.2028,151.7379,-32.8723],\"center\":[151.5347,-33.0376]},\"narrogin\":{\"name\":\"Narrogin\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[116.9516,-33.1899,117.5758,-32.804],\"center\":[117.2637,-32.9969]},\"wudinna\":{\"name\":\"Wudinna\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[134.8205,-33.3333,135.9629,-32.6216],\"center\":[135.3917,-32.9775]},\"kimba\":{\"name\":\"Kimba\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[135.4798,-33.3312,136.8109,-32.6022],\"center\":[136.1454,-32.9667]},\"cessnock\":{\"name\":\"Cessnock\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[150.8013,-33.1388,151.6236,-32.6488],\"center\":[151.2124,-32.8938]},\"newcastle\":{\"name\":\"Newcastle\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[151.6068,-32.963,151.8101,-32.7896],\"center\":[151.7084,-32.8763]},\"waroona\":{\"name\":\"Waroona\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.6286,-32.9431,116.18,-32.7552],\"center\":[115.9043,-32.8492]},\"peterborough\":{\"name\":\"Peterborough\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[138.6979,-33.1017,139.3543,-32.594],\"center\":[139.0261,-32.8479]},\"parkes\":{\"name\":\"Parkes\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[147.543,-33.2774,148.5073,-32.3692],\"center\":[148.0251,-32.8233]},\"wickepin\":{\"name\":\"Wickepin\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[117.3577,-33.1032,117.9219,-32.541],\"center\":[117.6398,-32.8221]},\"lachlan\":{\"name\":\"Lachlan\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[146.054,-33.6071,147.6971,-31.9928],\"center\":[146.8756,-32.8]},\"boddington\":{\"name\":\"Boddington\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[116.1782,-33.0858,116.6595,-32.4981],\"center\":[116.4188,-32.7919]},\"kulin\":{\"name\":\"Kulin\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[117.8462,-33.0455,119.6987,-32.4868],\"center\":[118.7724,-32.7661]},\"cuballing\":{\"name\":\"Cuballing\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[116.9079,-32.895,117.4021,-32.5856],\"center\":[117.155,-32.7403]},\"streaky bay\":{\"name\":\"Streaky Bay\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[133.9656,-33.2451,135.1366,-32.2311],\"center\":[134.5511,-32.7381]},\"port stephens\":{\"name\":\"Port Stephens\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[151.5935,-32.8782,152.2055,-32.5788],\"center\":[151.8995,-32.7285]},\"mount remarkable\":{\"name\":\"Mount Remarkable\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[137.9025,-33.1131,138.4402,-32.3231],\"center\":[138.1714,-32.7181]},\"maitland\":{\"name\":\"Maitland\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[151.3991,-32.8105,151.744,-32.6057],\"center\":[151.5716,-32.7081]},\"mandurah\":{\"name\":\"Mandurah\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.6068,-32.8019,115.7882,-32.4556],\"center\":[115.6975,-32.6287]},\"murray\":{\"name\":\"Murray\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.6663,-32.8032,116.2645,-32.4446],\"center\":[115.9654,-32.6239]},\"port augusta\":{\"name\":\"Port Augusta\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[137.5959,-32.8775,137.9652,-32.3548],\"center\":[137.7806,-32.6161]},\"singleton\":{\"name\":\"Singleton\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[150.3354,-33.072,151.5021,-32.1389],\"center\":[150.9187,-32.6055]},\"mid-western\":{\"name\":\"Mid-Western\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[149.1723,-33.1457,150.3626,-32.0581],\"center\":[149.7674,-32.6019]},\"pingelly\":{\"name\":\"Pingelly\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[116.8197,-32.6626,117.5806,-32.401],\"center\":[117.2002,-32.5318]},\"orroroo carrieton\":{\"name\":\"Orroroo Carrieton\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[138.4392,-32.9433,138.8902,-32.1203],\"center\":[138.6647,-32.5318]},\"wandering\":{\"name\":\"Wandering\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[116.1896,-32.8159,116.9435,-32.2359],\"center\":[116.5666,-32.5259]},\"muswellbrook\":{\"name\":\"Muswellbrook\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[150.2264,-32.8459,151.1703,-32.13],\"center\":[150.6984,-32.4879]},\"kondinin\":{\"name\":\"Kondinin\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[118.0388,-32.7653,120.0097,-32.2034],\"center\":[119.0242,-32.4844]},\"dubbo\":{\"name\":\"Dubbo\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[148.3598,-33.0631,149.3032,-31.8862],\"center\":[148.8315,-32.4746]},\"corrigin\":{\"name\":\"Corrigin\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[117.4121,-32.6023,118.2084,-32.1496],\"center\":[117.8102,-32.376]},\"brookton\":{\"name\":\"Brookton\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[116.5344,-32.4925,117.4655,-32.2181],\"center\":[117.0,-32.3553]},\"dungog\":{\"name\":\"Dungog\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[151.3038,-32.651,151.9187,-32.0425],\"center\":[151.6112,-32.3468]},\"serpentine-jarrahdale\":{\"name\":\"Serpentine-Jarrahdale\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.83,-32.4695,116.2597,-32.1796],\"center\":[116.0448,-32.3246]},\"rockingham\":{\"name\":\"Rockingham\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.6601,-32.4581,115.8897,-32.1555],\"center\":[115.7749,-32.3068]},\"kwinana\":{\"name\":\"Kwinana\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.7549,-32.2876,115.9008,-32.1802],\"center\":[115.8279,-32.2339]},\"narromine\":{\"name\":\"Narromine\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[147.4947,-32.6921,148.4569,-31.7714],\"center\":[147.9758,-32.2318]},\"armadale\":{\"name\":\"Armadale\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.8969,-32.2876,116.3581,-32.0702],\"center\":[116.1275,-32.1789]},\"beverley\":{\"name\":\"Beverley\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[116.2801,-32.3577,117.2472,-31.9619],\"center\":[116.7637,-32.1598]},\"ceduna\":{\"name\":\"Ceduna\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[133.2127,-32.5426,134.513,-31.7521],\"center\":[133.8629,-32.1474]},\"flinders ranges\":{\"name\":\"Flinders Ranges\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[137.923,-32.527,138.7546,-31.7397],\"center\":[138.3388,-32.1334]},\"dundas\":{\"name\":\"Dundas\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[120.0097,-33.0398,129.0019,-31.2131],\"center\":[124.5058,-32.1264]},\"unincorp. other territories\":{\"name\":\"Unincorp. Other Territories\",\"state\":\"Other Territories\",\"stateCode\":\"Other Territories\",\"isState\":false,\"bbox\":[150.5924,-35.2009,167.998,-28.9942],\"center\":[159.2952,-32.0975]},\"cockburn\":{\"name\":\"Cockburn\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.4495,-32.1814,115.9162,-31.9873],\"center\":[115.6829,-32.0844]},\"mid-coast\":{\"name\":\"Mid-Coast\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[151.4029,-32.7105,152.8057,-31.4424],\"center\":[152.1043,-32.0765]},\"gosnells\":{\"name\":\"Gosnells\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.9144,-32.1312,116.0896,-32.004],\"center\":[116.002,-32.0676]},\"fremantle\":{\"name\":\"Fremantle\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.7243,-32.0821,115.8033,-32.0212],\"center\":[115.7638,-32.0516]},\"canning\":{\"name\":\"Canning\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.8605,-32.1145,115.9784,-31.9839],\"center\":[115.9194,-32.0492]},\"melville\":{\"name\":\"Melville\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.7761,-32.0855,115.8921,-32.0016],\"center\":[115.8341,-32.0436]},\"east fremantle\":{\"name\":\"East Fremantle\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.758,-32.0473,115.7763,-32.0258],\"center\":[115.7672,-32.0365]},\"narembeen\":{\"name\":\"Narembeen\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[118.1949,-32.2868,119.1852,-31.7575],\"center\":[118.69,-32.0221]},\"quairading\":{\"name\":\"Quairading\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[117.0876,-32.2341,117.7091,-31.7951],\"center\":[117.3983,-32.0146]},\"mosman park\":{\"name\":\"Mosman Park\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.7509,-32.0251,115.7814,-32.0033],\"center\":[115.7662,-32.0142]},\"kalamunda\":{\"name\":\"Kalamunda\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.977,-32.0855,116.2889,-31.9225],\"center\":[116.1329,-32.004]},\"cottesloe\":{\"name\":\"Cottesloe\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.75,-32.0161,115.7718,-31.982],\"center\":[115.7609,-31.9991]},\"peppermint grove\":{\"name\":\"Peppermint Grove\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.7593,-32.0043,115.7747,-31.9934],\"center\":[115.767,-31.9989]},\"south perth\":{\"name\":\"South Perth\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.8448,-32.0335,115.8996,-31.9641],\"center\":[115.8722,-31.9988]},\"claremont\":{\"name\":\"Claremont\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.7662,-31.9935,115.7927,-31.969],\"center\":[115.7794,-31.9813]},\"upper hunter\":{\"name\":\"Upper Hunter\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[149.7916,-32.4088,151.594,-31.5537],\"center\":[150.6928,-31.9812]},\"victoria park\":{\"name\":\"Victoria Park\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.8787,-32.0132,115.9331,-31.9398],\"center\":[115.9059,-31.9765]},\"nedlands\":{\"name\":\"Nedlands\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.7528,-32.005,115.8175,-31.9442],\"center\":[115.7851,-31.9746]},\"bruce rock\":{\"name\":\"Bruce Rock\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[117.6692,-32.2366,118.3785,-31.6964],\"center\":[118.0239,-31.9665]},\"cobar\":{\"name\":\"Cobar\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[144.0163,-33.2762,146.7056,-30.656],\"center\":[145.361,-31.9661]},\"belmont\":{\"name\":\"Belmont\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.8969,-31.9888,115.9875,-31.9197],\"center\":[115.9422,-31.9543]},\"subiaco\":{\"name\":\"Subiaco\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.802,-31.9646,115.8416,-31.942],\"center\":[115.8218,-31.9533]},\"broken hill\":{\"name\":\"Broken Hill\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[141.3928,-32.0191,141.566,-31.8838],\"center\":[141.4794,-31.9515]},\"cambridge\":{\"name\":\"Cambridge\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.7538,-31.9627,115.844,-31.9081],\"center\":[115.7989,-31.9354]},\"vincent\":{\"name\":\"Vincent\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.8231,-31.9499,115.8852,-31.9128],\"center\":[115.8542,-31.9314]},\"york\":{\"name\":\"York\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[116.2849,-32.1399,117.1583,-31.6941],\"center\":[116.7216,-31.917]},\"bayswater\":{\"name\":\"Bayswater\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.8776,-31.9521,115.9387,-31.8654],\"center\":[115.9082,-31.9088]},\"bassendean\":{\"name\":\"Bassendean\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.9257,-31.9244,115.9643,-31.8872],\"center\":[115.945,-31.9058]},\"stirling\":{\"name\":\"Stirling\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.7508,-31.9385,115.8934,-31.8422],\"center\":[115.8221,-31.8903]},\"mundaring\":{\"name\":\"Mundaring\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[116.0148,-32.0625,116.4151,-31.7065],\"center\":[116.2149,-31.8845]},\"joondalup\":{\"name\":\"Joondalup\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.7066,-31.8473,115.8234,-31.7119],\"center\":[115.765,-31.7796]},\"central darling\":{\"name\":\"Central Darling\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[142.0918,-33.3005,145.1596,-30.2426],\"center\":[143.6257,-31.7715]},\"swan\":{\"name\":\"Swan\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.8739,-31.9436,116.298,-31.5972],\"center\":[116.0859,-31.7704]},\"northam\":{\"name\":\"Northam\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[116.3378,-31.9134,116.9615,-31.4845],\"center\":[116.6497,-31.6989]},\"wanneroo\":{\"name\":\"Wanneroo\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.5608,-31.8507,115.8835,-31.4551],\"center\":[115.7221,-31.6529]},\"gilgandra\":{\"name\":\"Gilgandra\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[148.268,-32.0171,149.1393,-31.2487],\"center\":[148.7036,-31.6329]},\"cunderdin\":{\"name\":\"Cunderdin\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[116.8449,-31.8562,117.3911,-31.3689],\"center\":[117.118,-31.6125]},\"tammin\":{\"name\":\"Tammin\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[117.3394,-31.841,117.6267,-31.3692],\"center\":[117.483,-31.6051]},\"kellerberrin\":{\"name\":\"Kellerberrin\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[117.5699,-31.8311,118.0413,-31.323],\"center\":[117.8056,-31.577]},\"bogan\":{\"name\":\"Bogan\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[146.2851,-32.4475,147.5272,-30.693],\"center\":[146.9061,-31.5703]},\"toodyay\":{\"name\":\"Toodyay\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[116.1507,-31.7092,116.6254,-31.2306],\"center\":[116.388,-31.4699]},\"liverpool plains\":{\"name\":\"Liverpool Plains\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[149.8409,-31.8582,150.9991,-31.0822],\"center\":[150.42,-31.4702]},\"merredin\":{\"name\":\"Merredin\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[117.9658,-31.7834,118.8044,-31.1377],\"center\":[118.3851,-31.4605]},\"warrumbungle\":{\"name\":\"Warrumbungle\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[148.7969,-32.3047,150.1106,-30.6056],\"center\":[149.4538,-31.4551]},\"unincorporated nsw\":{\"name\":\"Unincorporated NSW\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[140.9993,-33.8597,159.1092,-28.9989],\"center\":[150.0542,-31.4293]},\"port macquarie-hastings\":{\"name\":\"Port Macquarie-Hastings\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[152.0619,-31.7281,152.9764,-31.114],\"center\":[152.5192,-31.4211]},\"chittering\":{\"name\":\"Chittering\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.8552,-31.6277,116.2475,-31.0888],\"center\":[116.0513,-31.3582]},\"warren\":{\"name\":\"Warren\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[147.0996,-32.1887,148.3575,-30.4023],\"center\":[147.7285,-31.2955]},\"goomalling\":{\"name\":\"Goomalling\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[116.5917,-31.5094,116.9912,-30.9597],\"center\":[116.7914,-31.2345]},\"walcha\":{\"name\":\"Walcha\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[151.2875,-31.6381,152.3496,-30.757],\"center\":[151.8186,-31.1975]},\"wyalkatchem\":{\"name\":\"Wyalkatchem\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[117.2396,-31.4392,117.654,-30.9513],\"center\":[117.4468,-31.1953]},\"gingin\":{\"name\":\"Gingin\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.2627,-31.477,116.0562,-30.8917],\"center\":[115.6594,-31.1844]},\"trayning\":{\"name\":\"Trayning\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[117.5965,-31.3925,118.0799,-30.9416],\"center\":[117.8382,-31.167]},\"nungarin\":{\"name\":\"Nungarin\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[117.9288,-31.3371,118.5054,-30.9371],\"center\":[118.2171,-31.1371]},\"dowerin\":{\"name\":\"Dowerin\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[116.9311,-31.4269,117.2802,-30.7996],\"center\":[117.1056,-31.1133]},\"gunnedah\":{\"name\":\"Gunnedah\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[149.6316,-31.4582,150.5994,-30.5898],\"center\":[150.1155,-31.024]},\"victoria plains\":{\"name\":\"Victoria Plains\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.934,-31.3117,116.6369,-30.7209],\"center\":[116.2854,-31.0163]},\"coolgardie\":{\"name\":\"Coolgardie\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[120.0095,-31.868,122.3996,-30.1608],\"center\":[121.2046,-31.0144]},\"tamworth\":{\"name\":\"Tamworth\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[150.1455,-31.6618,151.4851,-30.1822],\"center\":[150.8153,-30.922]},\"yilgarn\":{\"name\":\"Yilgarn\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[118.5032,-32.2043,120.0139,-29.6124],\"center\":[119.2586,-30.9084]},\"kempsey\":{\"name\":\"Kempsey\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[152.2698,-31.3105,153.1023,-30.5006],\"center\":[152.6861,-30.9055]},\"westonia\":{\"name\":\"Westonia\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[118.5018,-31.5554,118.9575,-30.2033],\"center\":[118.7296,-30.8793]},\"coonamble\":{\"name\":\"Coonamble\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[147.5138,-31.4161,149.0672,-30.3181],\"center\":[148.2905,-30.8671]},\"unincorporated sa\":{\"name\":\"Unincorporated SA\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[129.0019,-35.7357,141.003,-25.9964],\"center\":[135.0025,-30.8661]},\"kalgoorlie-boulder\":{\"name\":\"Kalgoorlie-Boulder\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[120.8455,-31.4105,129.0019,-30.1421],\"center\":[124.9237,-30.7763]},\"wongan-ballidu\":{\"name\":\"Wongan-Ballidu\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[116.4393,-31.0123,117.2578,-30.4504],\"center\":[116.8486,-30.7313]},\"nambucca valley\":{\"name\":\"Nambucca Valley\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[152.4001,-30.9278,153.0204,-30.4887],\"center\":[152.7103,-30.7082]},\"mukinbudin\":{\"name\":\"Mukinbudin\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[118.0526,-31.0702,118.52,-30.2033],\"center\":[118.2863,-30.6367]},\"koorda\":{\"name\":\"Koorda\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[117.2111,-31.0021,117.6037,-30.2061],\"center\":[117.4074,-30.6041]},\"roxby downs\":{\"name\":\"Roxby Downs\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[136.843,-30.6235,136.9245,-30.4743],\"center\":[136.8837,-30.5489]},\"dandaragan\":{\"name\":\"Dandaragan\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[114.9704,-31.0085,115.9522,-30.0743],\"center\":[115.4613,-30.5414]},\"moora\":{\"name\":\"Moora\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.876,-30.8613,116.5436,-30.163],\"center\":[116.2098,-30.5121]},\"uralla\":{\"name\":\"Uralla\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[150.9343,-30.897,151.7747,-30.0739],\"center\":[151.3545,-30.4855]},\"armidale\":{\"name\":\"Armidale\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[151.2532,-30.931,152.4281,-29.9399],\"center\":[151.8406,-30.4355]},\"bellingen\":{\"name\":\"Bellingen\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[152.3897,-30.5671,153.0602,-30.1808],\"center\":[152.725,-30.374]},\"narrabri\":{\"name\":\"Narrabri\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[148.8107,-30.9063,150.3938,-29.7493],\"center\":[149.6022,-30.3278]},\"mount marshall\":{\"name\":\"Mount Marshall\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[117.4902,-30.9752,118.5082,-29.6124],\"center\":[117.9992,-30.2938]},\"coffs harbour\":{\"name\":\"Coffs Harbour\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[152.7957,-30.4487,153.2718,-29.8971],\"center\":[153.0337,-30.1729]},\"dalwallinu\":{\"name\":\"Dalwallinu\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[116.2968,-30.517,117.6712,-29.7432],\"center\":[116.984,-30.1301]},\"bourke\":{\"name\":\"Bourke\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[144.0654,-30.9931,146.6577,-28.9991],\"center\":[145.3616,-29.9961]},\"coorow\":{\"name\":\"Coorow\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[114.9415,-30.2086,116.3708,-29.7489],\"center\":[115.6561,-29.9787]},\"brewarrina\":{\"name\":\"Brewarrina\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[146.3497,-30.902,147.9455,-28.999],\"center\":[147.1476,-29.9505]},\"walgett\":{\"name\":\"Walgett\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[147.1736,-30.5816,149.0943,-28.999],\"center\":[148.1339,-29.7903]},\"carnamah\":{\"name\":\"Carnamah\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[114.8778,-29.9464,116.1631,-29.5156],\"center\":[115.5204,-29.731]},\"clarence valley\":{\"name\":\"Clarence Valley\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[152.1681,-30.4189,153.3948,-28.97],\"center\":[152.7815,-29.6944]},\"glen innes severn\":{\"name\":\"Glen Innes Severn\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[151.4268,-30.022,152.4523,-29.2401],\"center\":[151.9395,-29.6311]},\"three springs\":{\"name\":\"Three Springs\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.2449,-29.7396,116.0182,-29.2881],\"center\":[115.6316,-29.5138]},\"gwydir\":{\"name\":\"Gwydir\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[150.0739,-30.3231,151.0024,-28.673],\"center\":[150.5382,-29.498]},\"maralinga tjarutja\":{\"name\":\"Maralinga Tjarutja\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[129.0019,-30.7637,133.0065,-28.1159],\"center\":[131.0042,-29.4398]},\"inverell\":{\"name\":\"Inverell\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[150.4791,-30.2409,151.6046,-28.6342],\"center\":[151.0419,-29.4376]},\"perenjori\":{\"name\":\"Perenjori\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.9179,-29.9294,117.1531,-28.8658],\"center\":[116.5355,-29.3976]},\"menzies\":{\"name\":\"Menzies\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[118.4357,-30.3075,129.0019,-28.4637],\"center\":[123.7188,-29.3856]},\"irwin\":{\"name\":\"Irwin\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[114.8266,-29.7025,115.2647,-28.9788],\"center\":[115.0456,-29.3407]},\"moree plains\":{\"name\":\"Moree Plains\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[148.6762,-30.1055,150.4863,-28.5372],\"center\":[149.5813,-29.3213]},\"mingenew\":{\"name\":\"Mingenew\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.2502,-29.3732,115.7523,-28.9171],\"center\":[115.5012,-29.1452]},\"morawa\":{\"name\":\"Morawa\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.6219,-29.3442,116.491,-28.7262],\"center\":[116.0564,-29.0352]},\"richmond valley\":{\"name\":\"Richmond Valley\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[152.689,-29.343,153.4835,-28.7107],\"center\":[153.0863,-29.0268]},\"coober pedy\":{\"name\":\"Coober Pedy\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[134.6941,-29.0517,134.8097,-28.971],\"center\":[134.7519,-29.0114]},\"ballina\":{\"name\":\"Ballina\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[153.3625,-29.0012,153.6089,-28.7043],\"center\":[153.4857,-28.8528]},\"tenterfield\":{\"name\":\"Tenterfield\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[151.3654,-29.4275,152.6314,-28.249],\"center\":[151.9984,-28.8382]},\"lismore\":{\"name\":\"Lismore\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[153.0735,-29.0714,153.45,-28.5158],\"center\":[153.2618,-28.7936]},\"kyogle\":{\"name\":\"Kyogle\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[152.3737,-29.0233,153.1838,-28.2695],\"center\":[152.7788,-28.6464]},\"byron\":{\"name\":\"Byron\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[153.3286,-28.7656,153.6387,-28.461],\"center\":[153.4837,-28.6133]},\"southern downs\":{\"name\":\"Southern Downs\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[151.3508,-29.068,152.4926,-27.9367],\"center\":[151.9217,-28.5023]},\"yalgoo\":{\"name\":\"Yalgoo\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[116.0326,-29.8014,118.2839,-27.1744],\"center\":[117.1583,-28.4879]},\"goondiwindi\":{\"name\":\"Goondiwindi\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[148.9196,-29.1793,151.7101,-27.7465],\"center\":[150.3149,-28.4629]},\"greater geraldton\":{\"name\":\"Greater Geraldton\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[113.5883,-29.0619,116.2597,-27.8179],\"center\":[114.924,-28.4399]},\"sandstone\":{\"name\":\"Sandstone\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[117.7736,-29.6127,120.1962,-27.231],\"center\":[118.9849,-28.4218]},\"leonora\":{\"name\":\"Leonora\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[120.045,-29.4982,122.474,-27.2902],\"center\":[121.2595,-28.3942]},\"tweed\":{\"name\":\"Tweed\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[153.1067,-28.5427,153.5863,-28.1569],\"center\":[153.3465,-28.3498]},\"mount magnet\":{\"name\":\"Mount Magnet\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[117.2215,-29.0067,118.7116,-27.5749],\"center\":[117.9666,-28.2908]},\"balonne\":{\"name\":\"Balonne\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[146.8633,-28.9992,149.4956,-27.5705],\"center\":[148.1795,-28.2848]},\"chapman valley\":{\"name\":\"Chapman Valley\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[114.5596,-28.727,115.4958,-27.8179],\"center\":[115.0277,-28.2724]},\"scenic rim\":{\"name\":\"Scenic Rim\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[152.3749,-28.3639,153.2389,-27.7165],\"center\":[152.8069,-28.0402]},\"paroo\":{\"name\":\"Paroo\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[144.2923,-28.9991,147.1429,-26.9758],\"center\":[145.7176,-27.9874]},\"laverton\":{\"name\":\"Laverton\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[121.5445,-29.2212,129.0019,-26.6547],\"center\":[125.2732,-27.938]},\"bulloo\":{\"name\":\"Bulloo\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[140.9993,-28.9992,144.8299,-26.6625],\"center\":[142.9146,-27.8308]},\"northampton\":{\"name\":\"Northampton\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[113.9652,-28.5439,115.4035,-27.1125],\"center\":[114.6843,-27.8282]},\"logan\":{\"name\":\"Logan\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[152.7993,-27.9386,153.2904,-27.5873],\"center\":[153.0448,-27.763]},\"lockyer valley\":{\"name\":\"Lockyer Valley\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[151.9421,-27.9775,152.5187,-27.3852],\"center\":[152.2304,-27.6814]},\"ipswich\":{\"name\":\"Ipswich\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[152.3828,-27.8655,152.9417,-27.4903],\"center\":[152.6623,-27.6779]},\"redland\":{\"name\":\"Redland\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[153.1715,-27.7408,153.5467,-27.3879],\"center\":[153.3591,-27.5643]},\"toowoomba\":{\"name\":\"Toowoomba\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[150.7027,-28.1923,152.2514,-26.7668],\"center\":[151.477,-27.4795]},\"cue\":{\"name\":\"Cue\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[117.1666,-27.8257,118.8433,-26.6261],\"center\":[118.005,-27.2259]},\"moreton bay\":{\"name\":\"Moreton Bay\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[152.6512,-27.4224,153.2076,-26.7923],\"center\":[152.9294,-27.1074]},\"anangu pitjantjatjara yankunytjatjara\":{\"name\":\"Anangu Pitjantjatjara Yankunytjatjara\",\"state\":\"South Australia\",\"stateCode\":\"SA\",\"isState\":false,\"bbox\":[129.0018,-28.12,133.7449,-25.9986],\"center\":[131.3734,-27.0593]},\"somerset\":{\"name\":\"Somerset\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[152.0734,-27.5707,152.757,-26.4523],\"center\":[152.4152,-27.0115]},\"murchison\":{\"name\":\"Murchison\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.2025,-28.4343,117.6216,-25.5835],\"center\":[116.412,-27.0089]},\"western downs\":{\"name\":\"Western Downs\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[149.0973,-28.0144,151.6745,-25.5988],\"center\":[150.3859,-26.8066]},\"south burnett\":{\"name\":\"South Burnett\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[151.0132,-26.9479,152.1901,-25.8536],\"center\":[151.6017,-26.4008]},\"maranoa\":{\"name\":\"Maranoa\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[147.0301,-27.9071,149.8316,-24.8811],\"center\":[148.4309,-26.3941]},\"shark bay\":{\"name\":\"Shark Bay\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[112.9211,-27.304,115.5158,-25.4804],\"center\":[114.2184,-26.3922]},\"noosa\":{\"name\":\"Noosa\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[152.763,-26.4994,153.12,-26.1371],\"center\":[152.9415,-26.3182]},\"cherbourg\":{\"name\":\"Cherbourg\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[151.8865,-26.3187,151.9791,-26.2563],\"center\":[151.9328,-26.2875]},\"gympie\":{\"name\":\"Gympie\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[151.7528,-26.5977,153.1924,-25.7569],\"center\":[152.4726,-26.1773]},\"quilpie\":{\"name\":\"Quilpie\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[141.7042,-27.6518,145.4626,-24.6489],\"center\":[143.5834,-26.1504]},\"murweh\":{\"name\":\"Murweh\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[145.253,-27.5437,147.9546,-24.728],\"center\":[146.6038,-26.1359]},\"wiluna\":{\"name\":\"Wiluna\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[119.1968,-27.2923,124.668,-23.4402],\"center\":[121.9324,-25.3663]},\"fraser coast\":{\"name\":\"Fraser Coast\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[151.9801,-25.9862,153.3604,-24.697],\"center\":[152.6703,-25.3416]},\"meekatharra\":{\"name\":\"Meekatharra\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[117.2081,-27.3133,120.7914,-23.2933],\"center\":[118.9998,-25.3033]},\"north burnett\":{\"name\":\"North Burnett\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[150.3697,-26.0967,152.2764,-24.3921],\"center\":[151.323,-25.2444]},\"barcoo\":{\"name\":\"Barcoo\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[140.6763,-26.7751,144.2533,-23.5707],\"center\":[142.4648,-25.1729]},\"ngaanyatjarraku\":{\"name\":\"Ngaanyatjarraku\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[124.668,-26.7478,129.0019,-23.4403],\"center\":[126.835,-25.0941]},\"bundaberg\":{\"name\":\"Bundaberg\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[151.3418,-25.4313,152.633,-24.5137],\"center\":[151.9874,-24.9725]},\"banana\":{\"name\":\"Banana\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[148.8131,-25.9661,150.9837,-23.6471],\"center\":[149.8984,-24.8066]},\"blackall tambo\":{\"name\":\"Blackall Tambo\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[144.6556,-25.7547,147.2964,-23.8119],\"center\":[145.976,-24.7833]},\"upper gascoyne\":{\"name\":\"Upper Gascoyne\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[114.8065,-25.9289,117.871,-23.5098],\"center\":[116.3388,-24.7193]},\"diamantina\":{\"name\":\"Diamantina\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[137.9986,-25.9968,142.145,-23.1566],\"center\":[140.0718,-24.5767]},\"carnarvon\":{\"name\":\"Carnarvon\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[113.0689,-26.1437,115.6048,-22.7899],\"center\":[114.3368,-24.4668]},\"macdonnell\":{\"name\":\"MacDonnell\",\"state\":\"Northern Territory\",\"stateCode\":\"NT\",\"isState\":false,\"bbox\":[129.0005,-25.9986,137.9991,-22.8539],\"center\":[133.4998,-24.4262]},\"central highlands (qld)\":{\"name\":\"Central Highlands (Qld)\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[146.5725,-25.4724,150.0667,-22.6542],\"center\":[148.3196,-24.0633]},\"woorabinda\":{\"name\":\"Woorabinda\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[149.32,-24.6403,149.7754,-23.427],\"center\":[149.5477,-24.0337]},\"gladstone\":{\"name\":\"Gladstone\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[150.598,-24.792,152.7194,-23.2449],\"center\":[151.6587,-24.0185]},\"longreach\":{\"name\":\"Longreach\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[142.8087,-25.2555,144.9255,-22.4966],\"center\":[143.8671,-23.876]},\"alice springs\":{\"name\":\"Alice Springs\",\"state\":\"Northern Territory\",\"stateCode\":\"NT\",\"isState\":false,\"bbox\":[133.726,-23.8315,133.9405,-23.6305],\"center\":[133.8332,-23.731]},\"rockhampton\":{\"name\":\"Rockhampton\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[149.6726,-23.8536,150.8799,-22.9809],\"center\":[150.2763,-23.4172]},\"barcaldine\":{\"name\":\"Barcaldine\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[143.5832,-24.4458,147.2866,-21.6582],\"center\":[145.4349,-23.052]},\"livingstone\":{\"name\":\"Livingstone\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[149.3682,-23.534,151.0867,-21.9152],\"center\":[150.2275,-22.7246]},\"winton\":{\"name\":\"Winton\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[140.8222,-23.7063,144.5018,-21.3086],\"center\":[142.662,-22.5074]},\"exmouth\":{\"name\":\"Exmouth\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[113.654,-23.0113,114.754,-21.6244],\"center\":[114.204,-22.3178]},\"boulia\":{\"name\":\"Boulia\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[137.9971,-23.6936,141.2535,-20.8645],\"center\":[139.6253,-22.279]},\"isaac\":{\"name\":\"Isaac\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[146.0315,-23.556,150.442,-20.9308],\"center\":[148.2368,-22.2434]},\"ashburton\":{\"name\":\"Ashburton\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[114.3782,-23.8879,119.4268,-20.5816],\"center\":[116.9025,-22.2347]},\"east pilbara\":{\"name\":\"East Pilbara\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[118.4261,-23.728,129.0005,-19.4955],\"center\":[123.7133,-21.6118]},\"mackay\":{\"name\":\"Mackay\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[148.1491,-21.7713,149.9364,-20.3928],\"center\":[149.0428,-21.0821]},\"central desert\":{\"name\":\"Central Desert\",\"state\":\"Northern Territory\",\"stateCode\":\"NT\",\"isState\":false,\"bbox\":[129.0005,-24.1988,137.9988,-17.9452],\"center\":[133.4996,-21.072]},\"karratha\":{\"name\":\"Karratha\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[115.4335,-21.7275,118.2119,-20.3515],\"center\":[116.8227,-21.0395]},\"flinders (qld)\":{\"name\":\"Flinders (Qld)\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[143.2366,-22.2117,145.5396,-19.5656],\"center\":[144.3881,-20.8886]},\"port hedland\":{\"name\":\"Port Hedland\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[117.7533,-22.0014,119.512,-19.5838],\"center\":[118.6326,-20.7926]},\"cloncurry\":{\"name\":\"Cloncurry\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[139.2326,-22.3742,141.3097,-19.0236],\"center\":[140.2711,-20.6989]},\"whitsunday\":{\"name\":\"Whitsunday\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[146.8488,-21.6901,149.1782,-19.7055],\"center\":[148.0135,-20.6978]},\"mckinlay\":{\"name\":\"McKinlay\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[140.7394,-22.0529,142.6096,-19.1353],\"center\":[141.6745,-20.5941]},\"richmond\":{\"name\":\"Richmond\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[142.0376,-21.6675,143.7901,-19.4718],\"center\":[142.9138,-20.5697]},\"charters towers\":{\"name\":\"Charters Towers\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[144.2852,-22.1048,147.3477,-18.3137],\"center\":[145.8165,-20.2093]},\"burdekin\":{\"name\":\"Burdekin\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[146.8815,-20.3968,147.6634,-19.3019],\"center\":[147.2724,-19.8494]},\"mount isa\":{\"name\":\"Mount Isa\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[137.9956,-21.315,140.0329,-18.1783],\"center\":[139.0143,-19.7467]},\"barkly\":{\"name\":\"Barkly\",\"state\":\"Northern Territory\",\"stateCode\":\"NT\",\"isState\":false,\"bbox\":[131.6461,-22.5808,137.9976,-16.5022],\"center\":[134.8218,-19.5415]},\"halls creek\":{\"name\":\"Halls Creek\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[125.9028,-21.232,129.0005,-16.7693],\"center\":[127.4517,-19.0007]},\"palm island\":{\"name\":\"Palm Island\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[146.5049,-18.849,146.6948,-18.6519],\"center\":[146.5999,-18.7505]},\"hinchinbrook\":{\"name\":\"Hinchinbrook\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[145.7378,-18.9525,146.5081,-18.3643],\"center\":[146.123,-18.6584]},\"unincorporated nt\":{\"name\":\"Unincorporated NT\",\"state\":\"Northern Territory\",\"stateCode\":\"NT\",\"isState\":false,\"bbox\":[130.0168,-25.2652,136.7962,-12.0009],\"center\":[133.4065,-18.6331]},\"etheridge\":{\"name\":\"Etheridge\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[142.2442,-19.637,144.8324,-17.4885],\"center\":[143.5383,-18.5628]},\"croydon\":{\"name\":\"Croydon\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[141.1318,-19.6964,143.5132,-17.3307],\"center\":[142.3225,-18.5136]},\"broome\":{\"name\":\"Broome\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[120.0641,-20.0702,123.5663,-16.2768],\"center\":[121.8152,-18.1735]},\"burke\":{\"name\":\"Burke\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[137.9947,-19.5847,140.0738,-16.5383],\"center\":[139.0342,-18.0615]},\"cassowary coast\":{\"name\":\"Cassowary Coast\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[145.5726,-18.5333,146.3587,-17.4024],\"center\":[145.9656,-17.9678]},\"tablelands\":{\"name\":\"Tablelands\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[144.7408,-18.5781,145.8399,-17.0893],\"center\":[145.2903,-17.8337]},\"derby-west kimberley\":{\"name\":\"Derby-West Kimberley\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[122.9952,-19.4988,127.5642,-15.5092],\"center\":[125.2797,-17.504]},\"doomadgee\":{\"name\":\"Doomadgee\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[138.5769,-18.0187,139.1097,-16.8754],\"center\":[138.8433,-17.447]},\"carpentaria\":{\"name\":\"Carpentaria\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[139.7446,-19.4551,142.9615,-15.1902],\"center\":[141.353,-17.3227]},\"mareeba\":{\"name\":\"Mareeba\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[142.1744,-18.2161,145.6736,-16.0425],\"center\":[143.924,-17.1293]},\"yarrabah\":{\"name\":\"Yarrabah\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[145.8372,-17.1705,145.9647,-16.8643],\"center\":[145.9009,-17.0174]},\"mornington\":{\"name\":\"Mornington\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[139.0461,-17.1397,139.8876,-16.2292],\"center\":[139.4668,-16.6844]},\"douglas\":{\"name\":\"Douglas\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[144.9843,-16.7159,145.6291,-15.9029],\"center\":[145.3067,-16.3094]},\"wujal wujal\":{\"name\":\"Wujal Wujal\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[145.287,-15.9952,145.3433,-15.9359],\"center\":[145.3152,-15.9656]},\"victoria daly\":{\"name\":\"Victoria Daly\",\"state\":\"Northern Territory\",\"stateCode\":\"NT\",\"isState\":false,\"bbox\":[129.0004,-18.6827,132.5229,-13.1757],\"center\":[130.7617,-15.9292]},\"wyndham-east kimberley\":{\"name\":\"Wyndham-East Kimberley\",\"state\":\"Western Australia\",\"stateCode\":\"WA\",\"isState\":false,\"bbox\":[124.1742,-17.3363,129.0015,-13.6887],\"center\":[126.5879,-15.5125]},\"roper gulf\":{\"name\":\"Roper Gulf\",\"state\":\"Northern Territory\",\"stateCode\":\"NT\",\"isState\":false,\"bbox\":[131.9459,-17.6114,137.9953,-12.9998],\"center\":[134.9706,-15.3056]},\"kowanyama\":{\"name\":\"Kowanyama\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[141.4836,-15.5691,142.1347,-14.9856],\"center\":[141.8091,-15.2774]},\"hope vale\":{\"name\":\"Hope Vale\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[145.0282,-15.4434,145.3575,-14.8303],\"center\":[145.1928,-15.1368]},\"pormpuraaw\":{\"name\":\"Pormpuraaw\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[141.5256,-15.1463,142.1415,-14.1608],\"center\":[141.8336,-14.6535]},\"katherine\":{\"name\":\"Katherine\",\"state\":\"Northern Territory\",\"stateCode\":\"NT\",\"isState\":false,\"bbox\":[131.6598,-15.1144,132.6885,-14.1858],\"center\":[132.1741,-14.6501]},\"west daly\":{\"name\":\"West Daly\",\"state\":\"Northern Territory\",\"stateCode\":\"NT\",\"isState\":false,\"bbox\":[129.3556,-14.8921,130.6436,-13.282],\"center\":[129.9996,-14.087]},\"groote archipelago\":{\"name\":\"Groote Archipelago\",\"state\":\"Northern Territory\",\"stateCode\":\"NT\",\"isState\":false,\"bbox\":[136.0854,-14.3537,136.985,-13.5772],\"center\":[136.5352,-13.9655]},\"cook\":{\"name\":\"Cook\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[141.5832,-16.3644,145.5303,-10.9985],\"center\":[143.5568,-13.6814]},\"aurukun\":{\"name\":\"Aurukun\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[141.4665,-14.4655,142.1852,-12.5601],\"center\":[141.8259,-13.5128]},\"coomalie\":{\"name\":\"Coomalie\",\"state\":\"Northern Territory\",\"stateCode\":\"NT\",\"isState\":false,\"bbox\":[130.8891,-13.4889,131.279,-12.8158],\"center\":[131.084,-13.1523]},\"lockhart river\":{\"name\":\"Lockhart River\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[142.8834,-13.4855,143.6174,-12.5514],\"center\":[143.2504,-13.0184]},\"east arnhem\":{\"name\":\"East Arnhem\",\"state\":\"Northern Territory\",\"stateCode\":\"NT\",\"isState\":false,\"bbox\":[134.6667,-14.3226,136.9794,-11.001],\"center\":[135.823,-12.6618]},\"weipa\":{\"name\":\"Weipa\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[141.8457,-12.6873,141.9349,-12.6019],\"center\":[141.8903,-12.6446]},\"napranum\":{\"name\":\"Napranum\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[141.5914,-12.9428,142.5695,-12.2321],\"center\":[142.0804,-12.5875]},\"belyuen\":{\"name\":\"Belyuen\",\"state\":\"Northern Territory\",\"stateCode\":\"NT\",\"isState\":false,\"bbox\":[130.6536,-12.5673,130.7128,-12.5091],\"center\":[130.6832,-12.5382]},\"litchfield\":{\"name\":\"Litchfield\",\"state\":\"Northern Territory\",\"stateCode\":\"NT\",\"isState\":false,\"bbox\":[130.859,-12.8619,131.3967,-12.1427],\"center\":[131.1279,-12.5023]},\"palmerston\":{\"name\":\"Palmerston\",\"state\":\"Northern Territory\",\"stateCode\":\"NT\",\"isState\":false,\"bbox\":[130.9236,-12.5472,131.0143,-12.4387],\"center\":[130.969,-12.493]},\"darwin waterfront precinct\":{\"name\":\"Darwin Waterfront Precinct\",\"state\":\"Northern Territory\",\"stateCode\":\"NT\",\"isState\":false,\"bbox\":[130.8412,-12.4737,130.8519,-12.4634],\"center\":[130.8465,-12.4686]},\"wagait\":{\"name\":\"Wagait\",\"state\":\"Northern Territory\",\"stateCode\":\"NT\",\"isState\":false,\"bbox\":[130.7321,-12.4571,130.7676,-12.4276],\"center\":[130.7498,-12.4424]},\"west arnhem\":{\"name\":\"West Arnhem\",\"state\":\"Northern Territory\",\"stateCode\":\"NT\",\"isState\":false,\"bbox\":[131.7591,-13.8085,135.0,-10.9059],\"center\":[133.3795,-12.3572]},\"mapoon\":{\"name\":\"Mapoon\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[141.7254,-12.3917,142.22,-11.9522],\"center\":[141.9727,-12.1719]},\"cocos (keeling) islands\":{\"name\":\"Cocos (Keeling) Islands\",\"state\":\"Other Territories\",\"stateCode\":\"Other Territories\",\"isState\":false,\"bbox\":[96.817,-12.2087,96.9295,-11.8146],\"center\":[96.8732,-12.0116]},\"tiwi islands\":{\"name\":\"Tiwi Islands\",\"state\":\"Northern Territory\",\"stateCode\":\"NT\",\"isState\":false,\"bbox\":[130.0205,-11.9403,131.5437,-11.1654],\"center\":[130.7821,-11.5528]},\"northern peninsula area\":{\"name\":\"Northern Peninsula Area\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[142.1002,-11.2241,142.6093,-10.7197],\"center\":[142.3547,-10.9719]},\"christmas island\":{\"name\":\"Christmas Island\",\"state\":\"Other Territories\",\"stateCode\":\"Other Territories\",\"isState\":false,\"bbox\":[105.5333,-10.5705,105.7126,-10.4123],\"center\":[105.623,-10.4914]},\"torres\":{\"name\":\"Torres\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[141.419,-11.0037,143.8775,-9.1422],\"center\":[142.6483,-10.073]},\"torres strait island\":{\"name\":\"Torres Strait Island\",\"state\":\"Queensland\",\"stateCode\":\"QLD\",\"isState\":false,\"bbox\":[142.0851,-10.5753,144.064,-9.2293],\"center\":[143.0745,-9.9023]},\"tweed heads\":{\"name\":\"Tweed Heads\",\"state\":\"New South Wales\",\"stateCode\":\"NSW\",\"isState\":false,\"bbox\":[153.3618,-28.2823,153.5561,-28.1569],\"center\":[153.4589,-28.2196]}}");
  const GAZETTEER = Object.assign({}, EMBEDDED_LGA_GAZETTEER);

  // Asynchronously load the remaining 3,000+ ABS ASGS SA2 neighborhoods from GCS
  fetch("data/locality_gazetteer.json")
    .then(r => r.ok ? r.json() : null)
    .then(data => {
      if (data && typeof data === "object") {
        Object.entries(data).forEach(([k, v]) => {
          if (!GAZETTEER[k]) GAZETTEER[k] = v;
        });
      }
    })
    .catch(err => console.warn("locality_gazetteer.json background load warning:", err));

  function resolveLocalityExtent(input, opts = {}) {
    if (!input) return null;
    const bufferMeters = opts.bufferMeters !== undefined ? opts.bufferMeters : extractBufferMeters(typeof input === "string" ? input : "");
    const numArcPoints = opts.numArcPoints !== undefined ? opts.numArcPoints : extractSimplificationTolerance(typeof input === "string" ? input : "");
    const filletFraction = opts.filletFraction || 0.12;

    if (typeof input === "object" && !Array.isArray(input)) {
      if (input.type === "FeatureCollection" || input.type === "Feature" ||
          input.type === "Polygon" || input.type === "MultiPolygon") {
        const bbox = geomBounds(input.geometry || input);
        return { polygon: input, bbox, bufferMeters };
      }
      if (input.bbox && Array.isArray(input.bbox) && input.bbox.length === 4) {
        return { bbox: input.bbox, polygon: createSmoothedExtentPolygon(input.bbox, numArcPoints, bufferMeters, filletFraction), bufferMeters };
      }
    }
    if (Array.isArray(input) && input.length === 4 && typeof input[0] === "number") {
      return { bbox: input, polygon: createSmoothedExtentPolygon(input, numArcPoints, bufferMeters, filletFraction), bufferMeters };
    }
    if (Array.isArray(input) && input.length === 2 && Array.isArray(input[0])) {
      const bbox = [input[0][0], input[0][1], input[1][0], input[1][1]];
      return { bbox, polygon: createSmoothedExtentPolygon(bbox, numArcPoints, bufferMeters, filletFraction), bufferMeters };
    }
    if (typeof input === "string") {
      const clean = input.trim();
      const upper = clean.toUpperCase();
      if (upper.startsWith("POLYGON") || upper.startsWith("MULTIPOLYGON")) {
        const parsed = parseWktPolygon(clean);
        if (parsed) return { polygon: parsed, bbox: geomBounds(parsed), bufferMeters };
      }
      const numMatch = clean.match(/(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)/);
      if (numMatch) {
        let bbox = [parseFloat(numMatch[1]), parseFloat(numMatch[2]), parseFloat(numMatch[3]), parseFloat(numMatch[4])];
        if (bbox.every(n => !isNaN(n))) {
          if (bufferMeters > 0) {
            const dLat = bufferMeters / 111320.0;
            const midLat = (bbox[1] + bbox[3]) / 2.0;
            const dLon = bufferMeters / (111320.0 * Math.max(0.2, Math.cos(midLat * Math.PI / 180.0)));
            bbox = [bbox[0] - dLon, bbox[1] - dLat, bbox[2] + dLon, bbox[3] + dLat];
          }
          return { bbox, polygon: createSmoothedExtentPolygon(bbox, numArcPoints, 0, filletFraction), bufferMeters };
        }
      }

      // Strip buffer and simplification phrases from string before matching gazetteer names
      const cleanName = clean
        .replace(/(?:with|using|and|\+)?\s*(?:buffer|catchment|proximity|radius|simplif(?:y|ication)|tolerance|tolerance:)\s*(\d+(?:\.\d+)?)\s*(?:km|m|deg|%|meters|metres)?/gi, "")
        .replace(/\b\d+(?:\.\d+)?\s*(?:km|m|deg|%)\s*(?:buffer|catchment|proximity|radius)?\b/gi, "")
        .replace(/\b(?:in|across|around|at|for|within)\b/gi, "")
        .trim();
      const lower = (cleanName || clean).toLowerCase();

      function buildReturn(entry, bbox) {
        let finalBbox = bbox.slice();
        if (bufferMeters > 0) {
          const dLat = bufferMeters / 111320.0;
          const midLat = (finalBbox[1] + finalBbox[3]) / 2.0;
          const dLon = bufferMeters / (111320.0 * Math.max(0.2, Math.cos(midLat * Math.PI / 180.0)));
          finalBbox = [finalBbox[0] - dLon, finalBbox[1] - dLat, finalBbox[2] + dLon, finalBbox[3] + dLat];
        }
        return {
          name: entry.name || cleanName || clean,
          state: entry.state,
          stateCode: entry.stateCode || STATE_CODES[(entry.state || "").toLowerCase()] || (entry.state ? entry.state.toUpperCase() : null),
          isState: !!entry.isState,
          bbox: finalBbox,
          center: entry.center,
          bufferMeters,
          polygon: createSmoothedExtentPolygon(bbox, numArcPoints, bufferMeters, filletFraction)
        };
      }

      // 1. Direct gazetteer key match
      if (GAZETTEER[lower]) {
        return buildReturn(GAZETTEER[lower], GAZETTEER[lower].bbox);
      }

      // 2. Substring or multi-token match in gazetteer
      const tokens = lower.split(/[,;/]+/).map(s => s.trim()).filter(Boolean);
      let matched = [];
      for (const tok of tokens) {
        if (GAZETTEER[tok]) {
          matched.push(GAZETTEER[tok]);
          continue;
        }
        for (const [k, v] of Object.entries(GAZETTEER)) {
          if (k.length > 3 && (tok.includes(k) || k.includes(tok))) {
            matched.push(v);
            break;
          }
        }
      }
      if (matched.length > 0) {
        const minX = Math.min(...matched.map(m => m.bbox[0]));
        const minY = Math.min(...matched.map(m => m.bbox[1]));
        const maxX = Math.max(...matched.map(m => m.bbox[2]));
        const maxY = Math.max(...matched.map(m => m.bbox[3]));
        const primary = matched[0];
        return buildReturn({
          name: matched.map(m => m.name || m.code).join(", "),
          state: primary.state,
          stateCode: primary.stateCode,
          isState: matched.length === 1 && !!primary.isState,
          center: primary.center
        }, [minX, minY, maxX, maxY]);
      }

      // Fallbacks
      if (lower.includes("statewide") || lower.includes("nsw")) {
        return buildReturn(GAZETTEER.nsw, GAZETTEER.nsw.bbox);
      }
      if (lower.includes("national") || lower.includes("australia")) {
        return buildReturn(GAZETTEER.australia, GAZETTEER.australia.bbox);
      }
    }
    return null;
  }

  function normalizeGeometryInput(input) {
    if (!input) return null;
    const resolved = resolveLocalityExtent(input);
    if (resolved && resolved.polygon) return resolved.polygon;
    if (resolved && resolved.bbox) return createSmoothedExtentPolygon(resolved.bbox);
    return null;
  }

  function createInvertedMaskGeoJSON(geomOrInput) {
    const worldRing = ensureRingWinding([
      [-180, -85],
      [180, -85],
      [180, 85],
      [-180, 85],
      [-180, -85]
    ], false); // Exterior world ring must be counter-clockwise

    if (!geomOrInput) return { type: "FeatureCollection", features: [] };

    const geom = normalizeGeometryInput(geomOrInput);
    if (!geom) return { type: "FeatureCollection", features: [] };

    const holes = [];
    function addPolyHoles(polyCoords) {
      if (polyCoords && polyCoords[0] && polyCoords[0].length >= 3) {
        holes.push(ensureRingWinding(polyCoords[0], true)); // Interior holes must be clockwise
      }
    }

    if (geom.type === "FeatureCollection" && Array.isArray(geom.features)) {
      geom.features.forEach(f => {
        if (!f || !f.geometry) return;
        if (f.geometry.type === "Polygon") addPolyHoles(f.geometry.coordinates);
        else if (f.geometry.type === "MultiPolygon") f.geometry.coordinates.forEach(addPolyHoles);
      });
    } else if (geom.type === "Feature" && geom.geometry) {
      if (geom.geometry.type === "Polygon") addPolyHoles(geom.geometry.coordinates);
      else if (geom.geometry.type === "MultiPolygon") geom.geometry.coordinates.forEach(addPolyHoles);
    } else if (geom.type === "Polygon") {
      addPolyHoles(geom.coordinates);
    } else if (geom.type === "MultiPolygon") {
      geom.coordinates.forEach(addPolyHoles);
    } else if (Array.isArray(geom) && geom.length === 4 && typeof geom[0] === "number") {
      const [minX, minY, maxX, maxY] = geom;
      addPolyHoles([[[minX, minY], [maxX, minY], [maxX, maxY], [minX, maxY], [minX, minY]]]);
    }

    if (!holes.length) return { type: "FeatureCollection", features: [] };

    return {
      type: "FeatureCollection",
      features: [{
        type: "Feature",
        properties: {},
        geometry: {
          type: "Polygon",
          coordinates: [worldRing, ...holes]
        }
      }]
    };
  }

  function extractBoundaryGeoJSON(geomOrInput) {
    if (!geomOrInput) return { type: "FeatureCollection", features: [] };
    const geom = normalizeGeometryInput(geomOrInput);
    if (!geom) return { type: "FeatureCollection", features: [] };
    if (geom.type === "FeatureCollection") return geom;
    if (geom.type === "Feature") return { type: "FeatureCollection", features: [geom] };
    if (geom.type === "Polygon" || geom.type === "MultiPolygon") {
      return { type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: geom }] };
    }
    if (Array.isArray(geom) && geom.length === 4 && typeof geom[0] === "number") {
      const [minX, minY, maxX, maxY] = geom;
      return {
        type: "FeatureCollection",
        features: [{
          type: "Feature",
          properties: {},
          geometry: {
            type: "Polygon",
            coordinates: [[[minX, minY], [maxX, minY], [maxX, maxY], [minX, maxY], [minX, minY]]]
          }
        }]
      };
    }
    return { type: "FeatureCollection", features: [] };
  }

  function installAoiMask() {
    // 1. Territory Focus Mask source & fill layer (#030712 @ 80% opacity from Tuffs)
    if (!map.getSource("territory-mask")) {
      map.addSource("territory-mask", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] }
      });
      map.addLayer({
        id: "territory-mask-fill",
        type: "fill",
        source: "territory-mask",
        paint: {
          "fill-color": "#030712",
          "fill-opacity": 0.80
        }
      });
    }

    // 2. Selected Territory / AOI Highlight Boundary Line (bright cyan #54e1f0, 2.8px)
    if (!map.getSource("aoi-boundary")) {
      map.addSource("aoi-boundary", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] }
      });
      map.addLayer({
        id: "aoi-boundary-line",
        type: "line",
        source: "aoi-boundary",
        paint: {
          "line-color": "#54e1f0",
          "line-width": 2.8,
          "line-opacity": 1.0
        }
      });
    }

    if (currentAoiGeometry) {
      setAoiMask(currentAoiGeometry);
    } else {
      setAoiMask(DEFAULT_HUNTER_AOI_WKT);
    }
  }

  function setAoiMask(geomOrInput, opts = {}) {
    currentAoiGeometry = geomOrInput;
    if (!map || !map.getSource("territory-mask")) return;
    if (!aoiMaskEnabled || !geomOrInput) {
      map.getSource("territory-mask").setData({ type: "FeatureCollection", features: [] });
      if (map.getSource("aoi-boundary")) map.getSource("aoi-boundary").setData({ type: "FeatureCollection", features: [] });
      updateMaskButtonUi();
      return;
    }
    const maskData = createInvertedMaskGeoJSON(geomOrInput);
    map.getSource("territory-mask").setData(maskData);
    if (map.getSource("aoi-boundary")) {
      map.getSource("aoi-boundary").setData(extractBoundaryGeoJSON(geomOrInput));
    }
    if (map.getLayer("territory-mask-fill")) map.moveLayer("territory-mask-fill");
    if (map.getLayer("aoi-boundary-line")) map.moveLayer("aoi-boundary-line");
    ["oic-hl-fill", "oic-hl-line", "oic-hl-point"].forEach(id => { if (map.getLayer(id)) map.moveLayer(id); });
    updateMaskButtonUi();

    // Auto-fit camera to the active AOI bounds if not explicitly disabled
    if (opts.fitBounds !== false && map) {
      const resolved = resolveLocalityExtent(geomOrInput, opts);
      if (resolved && resolved.bbox) {
        map.fitBounds([[resolved.bbox[0], resolved.bbox[1]], [resolved.bbox[2], resolved.bbox[3]]], {
          padding: 50,
          maxZoom: 12.0,
          duration: 800
        });
      }
    }
  }

  function clearAoiMask() {
    currentAoiGeometry = null;
    if (map && map.getSource("territory-mask")) {
      map.getSource("territory-mask").setData({ type: "FeatureCollection", features: [] });
    }
    if (map && map.getSource("aoi-boundary")) {
      map.getSource("aoi-boundary").setData({ type: "FeatureCollection", features: [] });
    }
    updateMaskButtonUi();
  }

  function toggleAoiMask() {
    aoiMaskEnabled = !aoiMaskEnabled;
    if (aoiMaskEnabled) {
      setAoiMask(currentAoiGeometry || DEFAULT_HUNTER_AOI_WKT);
    } else if (map && map.getSource("territory-mask")) {
      map.getSource("territory-mask").setData({ type: "FeatureCollection", features: [] });
      if (map.getSource("aoi-boundary")) map.getSource("aoi-boundary").setData({ type: "FeatureCollection", features: [] });
    }
    updateMaskButtonUi();
  }

  function updateMaskButtonUi() {
    const btn = $("btnToggleAoiMask");
    const status = $("aoiMaskStatus");
    if (!btn || !status) return;
    const hasAoi = !!currentAoiGeometry;
    if (aoiMaskEnabled && hasAoi) {
      status.textContent = "On (80%)";
      btn.classList.add("active");
      btn.style.borderColor = "#54e1f0";
    } else if (aoiMaskEnabled && !hasAoi) {
      status.textContent = "Armed";
      btn.classList.remove("active");
      btn.style.borderColor = "";
    } else {
      status.textContent = "Off";
      btn.classList.remove("active");
      btn.style.borderColor = "";
    }
  }

  // ---------- Highlight & Identify ----------
  function installHighlight() {
    map.addSource("oic-hl", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
    map.addLayer({
      id: "oic-hl-fill", type: "fill", source: "oic-hl", filter: ["in", ["geometry-type"], ["literal", ["Polygon", "MultiPolygon"]]],
      paint: { "fill-color": "#facc15", "fill-opacity": 0.25 }
    });
    map.addLayer({
      id: "oic-hl-line", type: "line", source: "oic-hl", filter: ["!", ["in", ["geometry-type"], ["literal", ["Point", "MultiPoint"]]]],
      paint: { "line-color": "#facc15", "line-width": 4 }
    });
    map.addLayer({
      id: "oic-hl-point", type: "circle", source: "oic-hl", filter: ["in", ["geometry-type"], ["literal", ["Point", "MultiPoint"]]],
      paint: { "circle-radius": 11, "circle-color": "rgba(250,204,21,0.25)", "circle-stroke-color": "#facc15", "circle-stroke-width": 3 }
    });
  }
  function setHighlight(feature) {
    const src = map && map.getSource("oic-hl");
    if (src) src.setData({ type: "FeatureCollection", features: feature ? [{ type: "Feature", geometry: feature.geometry, properties: {} }] : [] });
  }

  function visibleHitLayers() {
    const ids = [];
    CATALOG.forEach(c => { if (state[c.key].visible) hitIds(c.key).forEach(id => { if (map.getLayer(id)) ids.push(id); }); });
    return ids;
  }
  function keyFromLayerId(id) {
    const m = id.match(/^L-(.+)-(fill|outline|line|circle)$/);
    return m ? m[1] : null;
  }

  function queryAt(point) {
    const layers = visibleHitLayers();
    if (!layers.length) return [];
    const bbox = [[point.x - 6, point.y - 6], [point.x + 6, point.y + 6]];
    const rank = { circle: 0, line: 1, fill: 2 };
    const hits = map.queryRenderedFeatures(bbox, { layers });
    const seen = new Set();
    return hits
      .map(h => ({ key: keyFromLayerId(h.layer.id), fid: h.properties.__fid }))
      .filter(h => h.key && h.fid !== undefined && !seen.has(`${h.key}:${h.fid}`) && seen.add(`${h.key}:${h.fid}`))
      .sort((a, b) => rank[BY_KEY[a.key].kind] - rank[BY_KEY[b.key].kind]);
  }

  function handleMapClick(e) {
    if (mode !== "identify") return;
    const hits = queryAt(e.point);
    if (!hits.length) { closePopup(); return; }
    const { key, fid } = hits[0];
    const feature = state[key].data.features[fid];
    showFeature(key, feature, e.lngLat, hits.length - 1);
  }

  function formatVal(v) {
    if (v === null || v === undefined || v === "") return null;
    if (typeof v === "number") return Number.isInteger(v) ? v.toLocaleString() : v.toLocaleString(undefined, { maximumFractionDigits: 4 });
    const s = String(v);
    if (/^https?:\/\//i.test(s)) return `<a href="${esc(s)}" target="_blank" rel="noopener" class="text-secondary underline">${esc(s.length > 48 ? s.slice(0, 48) + "…" : s)}</a>`;
    const plain = s.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
    return esc(plain.length > 220 ? plain.slice(0, 220) + "…" : plain);
  }

  function closePopup() {
    if (popup) { popup.remove(); popup = null; }
    setHighlight(null);
  }

  function showFeature(key, feature, lngLat, otherHits) {
    if (!feature || !map) return;
    const c = BY_KEY[key];
    const props = feature.properties || {};
    const gtype = (feature.geometry && feature.geometry.type) || "Unknown";
    const title = featureTitle(key, props);
    const rows = Object.entries(props)
      .filter(([k]) => !HIDDEN_PROP(k))
      .map(([k, v]) => [k, formatVal(v)])
      .filter(([, v]) => v !== null)
      .map(([k, v]) => `<tr><th>${esc(k)}</th><td>${v}</td></tr>`).join("");

    const el = document.createElement("div");
    el.innerHTML = `
      <div class="oic-popup-header">
        <div style="font-size:10px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:#81f0ff;display:flex;gap:6px;align-items:center;">
          <span style="display:inline-block;width:9px;height:9px;border-radius:${c.kind === "circle" ? "9999px" : "2px"};background:${c.color};"></span>
          ${esc(c.title)} <span style="margin-left:auto;padding:1px 6px;border-radius:9999px;background:rgba(255,255,255,.15);">${esc(gtype.toUpperCase())}</span>
        </div>
        <div style="font-family:'Space Grotesk',sans-serif;font-weight:700;font-size:14px;margin-top:2px;">${esc(title)}</div>
        ${otherHits > 0 ? `<div style="font-size:10px;color:#b1c7f0;margin-top:2px;">+${otherHits} more feature(s) under cursor — zoom in to separate</div>` : ""}
      </div>
      <div class="oic-popup-body"><table class="oic-popup-table">${rows || "<tr><td>No attributes</td></tr>"}</table></div>
      <div class="oic-popup-footer">
        <button type="button" class="oic-popup-act" data-act="zoom">🎯 Zoom</button>
        <button type="button" class="oic-popup-act" data-act="table">⊞ Table</button>
        <button type="button" class="oic-popup-act" data-act="meta">ℹ️ Lineage</button>
      </div>`;
    el.querySelector('[data-act="zoom"]').addEventListener("click", () => zoomToFeature(feature));
    el.querySelector('[data-act="table"]').addEventListener("click", () => openTable(key, props.__fid));
    el.querySelector('[data-act="meta"]').addEventListener("click", () => openMeta(key));

    if (popup) popup.remove();
    const at = lngLat || featureAnchor(feature);
    popup = new maplibregl.Popup({ closeButton: true, closeOnClick: false, maxWidth: "390px", offset: 10 })
      .setLngLat(at).setDOMContent(el).addTo(map);
    popup.on("close", () => setHighlight(null));
    setHighlight(feature);
    updateInspector(key, feature, title, gtype);
    if (dockKey === key) markDockRow(props.__fid);
  }

  function featureAnchor(feature) {
    const g = feature.geometry;
    if (g && g.type === "Point") return g.coordinates;
    const b = geomBounds(g);
    return b ? [(b[0][0] + b[1][0]) / 2, (b[0][1] + b[1][1]) / 2] : map.getCenter();
  }

  function zoomToFeature(feature) {
    const g = feature && feature.geometry;
    if (!g || !map) return;
    if (g.type === "Point") { map.flyTo({ center: g.coordinates, zoom: Math.max(map.getZoom(), 13), duration: 700 }); return; }
    const b = geomBounds(g);
    if (b) map.fitBounds(b, { padding: 60, maxZoom: 14, duration: 700 });
  }

  function updateInspector(key, feature, title, gtype) {
    const status = $("sidebarIdentifyStatus");
    if (status) status.innerHTML = `<b>Selected:</b> ${esc(title)} <span class="font-mono">(${esc(gtype)})</span>`;
    const banner = $("inspectorBanner");
    if (!banner) return;
    $("inspectorBadge").textContent = BY_KEY[key].title;
    $("inspectorName").textContent = title;
    const items = Object.entries(feature.properties || {})
      .filter(([k, v]) => !HIDDEN_PROP(k) && !k.startsWith("_oic_") && v !== null && v !== undefined && v !== "")
      .slice(0, 8);
    $("inspectorGrid").innerHTML = items.map(([k, v]) =>
      `<div class="inspector-item"><span class="inspector-label">${esc(k)}</span><div class="inspector-val">${formatVal(v)}</div></div>`).join("");
    banner.style.display = "block";
  }

  // Public helper used by Step 04 result rows: find a feature by property value, zoom and open popup.
  async function zoomToFeatureByProp(key, prop, value) {
    if (!BY_KEY[key]) return false;
    if (!state[key].visible) await setVisible(key, true);
    const d = state[key].data;
    if (!d) return false;
    const want = String(value).trim().toLowerCase();
    const f = d.features.find(ft => ft.properties && String(ft.properties[prop] ?? "").trim().toLowerCase() === want);
    if (!f) return false;
    zoomToFeature(f);
    map.once("moveend", () => showFeature(key, f, featureAnchor(f), 0));
    return true;
  }

  // ---------- Layer Control & Legend ----------
  function swatch(c) {
    if (c.kind === "circle") return `<span class="geom-swatch-point" style="background:${c.color}"></span>`;
    if (c.kind === "line") return `<span class="geom-swatch-line" style="background:${c.dash ? `repeating-linear-gradient(90deg, ${c.color} 0 4px, transparent 4px 7px)` : c.color}"></span>`;
    return `<span class="geom-swatch-poly" style="color:${c.color};background:${c.hollow ? "transparent" : c.color + "66"};${c.dash ? "border-style:dashed;" : ""}"></span>`;
  }
  function qaBadge(key) {
    const qa = qaIndex[key];
    const s = qa ? qa.overall_qa_status : (BY_KEY[key].derivedFrom ? "DERIVED" : "N/A");
    const cls = s === "PASS" ? "optimal" : (s === "WARNING" || s === "DERIVED" ? "tight" : "long");
    return `<span class="badge-tag ${cls}" style="font-size:9.5px;padding:0 5px;">${esc(s)}</span>`;
  }

  function renderLayerControl() {
    const list = $("layerControlList");
    if (!list) return;
    const filter = (($("layerFilterInput") || {}).value || "").toLowerCase().trim();
    const keys = showAll ? order.concat(CATALOG.map(c => c.key).filter(k => !order.includes(k))) : order.slice();
    const shown = keys.filter(k => !filter || `${BY_KEY[k].title} ${BY_KEY[k].theme} ${k}`.toLowerCase().includes(filter));
    if ($("btnShowAllLayers")) $("btnShowAllLayers").textContent = showAll ? `Active (${order.length})` : `All (${CATALOG.length})`;

    if (!shown.length) {
      list.innerHTML = `<div class="p-4 text-center text-xs text-on-surface-variant space-y-2">
        <div class="font-bold text-on-surface">No layers ${showAll ? "match the filter" : "active yet"}</div>
        <div>Run a query, click <b>All (${CATALOG.length})</b> above, or use <b>+ Catalogue</b> to add any stored GeoParquet layer.</div></div>`;
      return;
    }

    list.innerHTML = shown.map(k => {
      const c = BY_KEY[k];
      const st = state[k];
      const count = st.data ? st.data.features.length : (qaIndex[k] && qaIndex[k].preview_geojson ? qaIndex[k].preview_geojson.preview_feature_count : null);
      const idx = order.indexOf(k);
      return `<div class="layer-card ${dockKey === k ? "active-layer" : ""}" data-layer="${k}">
        <div class="flex items-center gap-2">
          <input type="checkbox" class="accent-secondary cursor-pointer" data-act="toggle" ${st.visible ? "checked" : ""} title="Toggle visibility"/>
          ${swatch(c)}
          <div class="min-w-0 flex-1">
            <div class="text-[12px] font-bold text-on-surface truncate" title="${esc(c.title)}">${esc(c.title)}</div>
            <div class="flex items-center gap-1.5 text-[10px] text-on-surface-variant">
              <span class="font-mono">${count !== null ? Number(count).toLocaleString() + " feat" : "—"}</span>
              <span>•</span><span class="truncate">${esc(c.theme)}</span>${qaBadge(k)}
              ${st.loading && !st.data ? '<span class="text-secondary font-bold">loading…</span>' : ""}
            </div>
          </div>
        </div>
        <div class="flex items-center gap-1 mt-1.5 flex-wrap">
          <button type="button" class="layer-icon-btn" data-act="opacity" title="Opacity">🎚️</button>
          <button type="button" class="layer-icon-btn" data-act="zoom" title="Zoom to layer extent">🎯</button>
          <button type="button" class="layer-icon-btn" data-act="meta" title="Metadata &amp; 3-Level QA lineage">ℹ️</button>
          <button type="button" class="layer-icon-btn" data-act="chart" title="Attribute distribution charts">📊</button>
          <button type="button" class="layer-icon-btn ${dockKey === k ? "active" : ""}" data-act="table" title="Open in Attribute Table View">⊞</button>
          ${idx >= 0 ? `<span class="flex-1"></span>
          <button type="button" class="layer-icon-btn" data-act="up" title="Move up" ${idx === 0 ? "disabled style=\"opacity:.35\"" : ""}>▲</button>
          <button type="button" class="layer-icon-btn" data-act="down" title="Move down" ${idx === order.length - 1 ? "disabled style=\"opacity:.35\"" : ""}>▼</button>
          <button type="button" class="layer-icon-btn" data-act="remove" title="Remove from Layer Control">✕</button>` : ""}
        </div>
        <div class="opacity-drawer hidden mt-1.5 flex items-center gap-2 text-[10px] text-on-surface-variant">
          <span class="font-bold">Opacity</span>
          <input type="range" min="0" max="100" value="${Math.round(st.opacity * 100)}" class="flex-1 accent-secondary" data-act="opacity-slider"/>
          <span class="font-mono w-8 text-right" data-role="opacity-val">${Math.round(st.opacity * 100)}%</span>
        </div>
      </div>`;
    }).join("");
  }

  async function onLayerControlAction(e) {
    const card = e.target.closest("[data-layer]");
    const actEl = e.target.closest("[data-act]");
    if (!card || !actEl) return;
    const key = card.getAttribute("data-layer");
    const act = actEl.getAttribute("data-act");
    if (act === "toggle") return setVisible(key, actEl.checked, { zoom: actEl.checked && !state[key].data });
    if (act === "opacity") { card.querySelector(".opacity-drawer").classList.toggle("hidden"); return; }
    if (act === "zoom") { if (!state[key].visible) await setVisible(key, true); return zoomToLayer(key); }
    if (act === "meta") return openMeta(key);
    if (act === "chart") return openChart(key);
    if (act === "table") return openTable(key);
    if (act === "remove") return removeFromList(key);
    if (act === "up" || act === "down") {
      const i = order.indexOf(key);
      const j = act === "up" ? i - 1 : i + 1;
      if (i < 0 || j < 0 || j >= order.length) return;
      [order[i], order[j]] = [order[j], order[i]];
      applyOrder();
      renderLayerControl();
      renderLegend();
    }
  }
  function onLayerOpacityInput(e) {
    if (!e.target.matches('[data-act="opacity-slider"]')) return;
    const card = e.target.closest("[data-layer]");
    const key = card.getAttribute("data-layer");
    state[key].opacity = Number(e.target.value) / 100;
    card.querySelector('[data-role="opacity-val"]').textContent = `${e.target.value}%`;
    applyOpacity(key);
  }

  function renderLegend() {
    const hud = $("mapLegendHud");
    const items = $("mapLegendItems");
    if (!hud || !items) return;
    const vis = order.filter(k => state[k].visible);
    if ($("legendActiveCount")) $("legendActiveCount").textContent = `${vis.length} layer${vis.length === 1 ? "" : "s"}`;
    if (!vis.length) { hud.style.display = "none"; return; }
    hud.style.display = "block";
    items.innerHTML = vis.map(k => {
      const c = BY_KEY[k];
      if (c.legendClasses) {
        return c.legendClasses.map(([col, lbl]) =>
          `<div class="flex items-center gap-2"><span class="geom-swatch-poly" style="color:#001026;background:${col}99;border-width:1px"></span><span>${esc(lbl)}</span></div>`).join("");
      }
      return `<div class="flex items-center gap-2">${swatch(c)}<span>${esc(c.title)}</span></div>`;
    }).join("");
  }

  // ---------- Modals ----------
  function openModal(id) { const m = $(id); if (m) m.classList.add("open"); }
  function closeModal(id) { const m = $(id); if (m) m.classList.remove("open"); }

  function statusPill(s) {
    const st = s || "NOT TESTED";
    const col = st === "PASS" ? "#006973" : st === "WARNING" ? "#d47300" : st === "FAIL" ? "#ba1a1a" : "#74777f";
    return `<span style="display:inline-block;padding:1px 8px;border-radius:9999px;background:${col}1a;color:${col};font-weight:700;font-size:10.5px;">${esc(st)}</span>`;
  }
  function checksList(level) {
    const checks = (level && level.checks) || [];
    if (!checks.length) return `<li class="text-on-surface-variant">No checks recorded</li>`;
    return checks.map(ch => `<li class="flex items-start gap-1.5">${statusPill(ch.status)}<span>${esc(ch.check || ch.name || ch.check_name || "")}${ch.detail || ch.message ? ` — <span class="text-on-surface-variant">${esc(ch.detail || ch.message)}</span>` : ""}</span></li>`).join("");
  }
  const kv = (k, v) => `<div class="flex gap-2 py-1 border-b border-surface-container"><span class="w-44 shrink-0 font-bold text-on-surface-variant uppercase text-[10px] tracking-wider pt-0.5">${esc(k)}</span><span class="font-mono text-[11px] break-all">${v}</span></div>`;

  async function openMeta(key) {
    const c = BY_KEY[key];
    $("metaModalTitle").textContent = `ℹ️ ${c.title}`;
    $("metaModalBody").innerHTML = `<div class="text-on-surface-variant">Loading layer statistics…</div>`;
    openModal("metaModal");
    try { await loadData(key); } catch (e) { /* metadata still shown */ }
    const qa = qaIndex[key];
    const b = layerBounds(key);
    const loaded = state[key].data ? state[key].data.features.length : 0;
    const live = `
      <div class="p-3 rounded-lg bg-surface-container-low">
        <div class="font-bold text-on-surface mb-1">Loaded Map Layer (computed from stored features)</div>
        ${kv("Features loaded", loaded.toLocaleString())}
        ${kv("Geometry types", esc(geomTypes(key).join(", ") || "—"))}
        ${kv("Computed extent", b ? esc(b.flat().map(n => n.toFixed(4)).join(", ")) : "—")}
        ${kv("Preview path", `<a class="text-secondary underline" href="${esc(c.path)}" target="_blank">${esc(c.path)}</a>`)}
      </div>`;

    if (!qa) {
      const inputs = (c.derivedFrom || []).map(k => `<li>• <a class="text-secondary underline cursor-pointer" data-meta-link="${k}">${esc(BY_KEY[k] ? BY_KEY[k].title : k)}</a> ${qaIndex[k] ? statusPill(qaIndex[k].overall_qa_status) : ""}</li>`).join("");
      $("metaModalBody").innerHTML = `
        <div class="p-3 rounded-lg bg-tertiary-fixed text-on-tertiary-fixed text-[12px]"><b>Derived analysis export.</b> Produced by DuckDB Spatial from catalogued GeoParquet inputs; lineage is the 3-level QA of each input dataset below.</div>
        <div class="p-3 rounded-lg bg-surface-container-low"><div class="font-bold mb-1">Input datasets (click for lineage)</div><ul class="space-y-1">${inputs || "<li>—</li>"}</ul></div>
        ${live}`;
      bindMetaLinks();
      return;
    }

    const l1 = qa.level1_source_contract || {}, l2 = qa.level2_stored_artifact || {}, l3 = qa.level3_reconciliation || qa.level3_source_to_storage_reconciliation || {};
    const gv = l2.geometry_validation || {};
    const lic = qa.licence || {};
    $("metaModalBody").innerHTML = `
      <div class="flex flex-wrap items-center gap-2">${statusPill(qa.overall_qa_status)}<span class="badge">${esc(qa.scale)}</span><span class="badge">${esc(qa.theme)}</span><span class="badge">${esc(qa.category)}</span></div>
      <div class="p-3 rounded-lg bg-surface-container-low">
        <div class="font-bold text-on-surface mb-1">Provenance</div>
        ${kv("Provider", esc(qa.provider))}
        ${kv("Source agency", esc(qa.source_agency))}
        ${kv("Endpoint", `<a class="text-secondary underline" href="${esc(qa.endpoint)}" target="_blank" rel="noopener">${esc(qa.endpoint)}</a>`)}
        ${kv("Licence", `${esc(lic.name || "—")}${lic.url ? ` (<a class="text-secondary underline" href="${esc(lic.url)}" target="_blank">link</a>)` : ""}<br/><span class="text-on-surface-variant">${esc(lic.attribution || "")}</span>`)}
        ${kv("Vintage / published", `${esc(qa.source_vintage)} / ${esc(qa.source_publication_date || "—")}`)}
        ${kv("Retrieved (UTC)", esc(qa.retrieval_timestamp_utc || "—"))}
      </div>
      <div class="p-3 rounded-lg bg-surface-container-low">
        <div class="font-bold text-on-surface mb-1">Stored GeoParquet Artifact (GCS)</div>
        ${kv("GCS URI", esc(qa.gs_uri || "— (not stored)"))}
        ${kv("SHA-256", esc(qa.sha256 || "—"))}
        ${kv("GCS generation", esc(qa.gcs_generation || "—"))}
        ${kv("CRS", `${esc(qa.original_crs)} → ${esc(qa.stored_crs)}`)}
        ${kv("Geometry / features", `${esc(qa.geometry_type || "—")} / ${(qa.feature_count || 0).toLocaleString()}`)}
        ${kv("Valid geometry rate", gv.valid_geometry_rate_pct !== undefined ? `${esc(gv.valid_geometry_rate_pct)}% (null=${esc(gv.null_geometry_count || 0)}, invalid=${esc(gv.invalid_geometry_count || 0)})` : "—")}
        ${kv("File size", qa.file_size_bytes ? `${(qa.file_size_bytes / 1024).toFixed(1)} KB` : "—")}
      </div>
      <div class="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div class="p-3 rounded-lg bg-surface-container-low"><div class="font-bold flex justify-between mb-1"><span>L1 Source Contract</span>${statusPill(l1.status)}</div><ul class="space-y-1 text-[11px]">${checksList(l1)}</ul></div>
        <div class="p-3 rounded-lg bg-surface-container-low"><div class="font-bold flex justify-between mb-1"><span>L2 Stored Artifact</span>${statusPill(l2.status)}</div><ul class="space-y-1 text-[11px]">${checksList(l2)}</ul></div>
        <div class="p-3 rounded-lg bg-surface-container-low"><div class="font-bold flex justify-between mb-1"><span>L3 Reconciliation</span>${statusPill(l3.status)}</div><ul class="space-y-1 text-[11px]">${checksList(l3)}</ul></div>
      </div>
      <div class="p-3 rounded-lg bg-surface-container-low text-[11px]"><b>Known limitations:</b> ${esc((qa.known_limitations || []).join(" ") || "None recorded")}</div>
      ${live}
      <div class="flex justify-end"><a href="qa/inspect.html?dataset=${encodeURIComponent(key)}" class="btn h-8 px-3 text-xs">Open in QA Inspector →</a></div>`;
  }
  function bindMetaLinks() {
    $("metaModalBody").querySelectorAll("[data-meta-link]").forEach(a => a.addEventListener("click", () => openMeta(a.getAttribute("data-meta-link"))));
  }

  // Charts: categorical top-N bars or numeric histogram, from real attributes.
  let chartKey = null;
  async function openChart(key) {
    chartKey = key;
    $("chartModalTitle").textContent = `📊 ${BY_KEY[key].title}`;
    $("chartModalBody").innerHTML = `<div class="text-on-surface-variant text-xs">Loading features…</div>`;
    openModal("chartModal");
    try { await loadData(key); } catch (e) { $("chartModalBody").innerHTML = `<div class="text-error text-xs">${esc(e.message)}</div>`; return; }
    const feats = state[key].data.features;
    const fields = [...new Set(feats.flatMap(f => Object.keys(f.properties || {})))].filter(k => !HIDDEN_PROP(k) && !k.startsWith("_oic_"));
    // Prefer fields with 2..40 distinct values or numeric
    const scored = fields.map(f => {
      const vals = feats.map(ft => ft.properties[f]).filter(v => v !== null && v !== undefined && v !== "");
      const distinct = new Set(vals.map(String)).size;
      const numeric = vals.length && vals.filter(v => !isNaN(Number(v))).length / vals.length >= 0.9;
      return { f, distinct, numeric, n: vals.length, score: (numeric && distinct > 5 ? 2 : 0) + (distinct >= 2 && distinct <= 40 ? 3 : 0) };
    }).filter(s => s.n > 0 && s.distinct > 1);
    scored.sort((a, b) => b.score - a.score);
    const sel = $("chartFieldSelect");
    sel.innerHTML = scored.map(s => `<option value="${esc(s.f)}">${esc(s.f)} (${s.numeric ? "numeric" : s.distinct + " classes"})</option>`).join("");
    if (!scored.length) { $("chartModalBody").innerHTML = `<div class="text-xs text-on-surface-variant">No chartable attributes.</div>`; return; }
    renderChart(scored[0].f);
  }

  function renderChart(field) {
    const feats = state[chartKey].data.features;
    const vals = feats.map(f => f.properties[field]).filter(v => v !== null && v !== undefined && v !== "");
    const numericVals = vals.map(Number).filter(v => !isNaN(v));
    const isNumeric = numericVals.length / vals.length >= 0.9 && new Set(numericVals).size > 12;
    const color = BY_KEY[chartKey].color;
    let bars = [];
    if (isNumeric) {
      const min = Math.min(...numericVals), max = Math.max(...numericVals);
      const bins = 10, w = (max - min) / bins || 1;
      const counts = new Array(bins).fill(0);
      numericVals.forEach(v => { counts[Math.min(bins - 1, Math.floor((v - min) / w))]++; });
      bars = counts.map((cnt, i) => [`${(min + i * w).toLocaleString(undefined, { maximumFractionDigits: 2 })} – ${(min + (i + 1) * w).toLocaleString(undefined, { maximumFractionDigits: 2 })}`, cnt]);
      const mean = numericVals.reduce((a, b) => a + b, 0) / numericVals.length;
      $("chartFieldInfo").textContent = `n=${numericVals.length} • min ${min.toLocaleString()} • max ${max.toLocaleString()} • mean ${mean.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
    } else {
      const counts = {};
      vals.forEach(v => { const s = String(v); counts[s] = (counts[s] || 0) + 1; });
      bars = Object.entries(counts).sort((a, b) => b[1] - a[1]);
      const extra = bars.length > 15 ? bars.slice(15).reduce((a, [, c]) => a + c, 0) : 0;
      bars = bars.slice(0, 15);
      if (extra) bars.push(["(other values)", extra]);
      $("chartFieldInfo").textContent = `n=${vals.length} • ${Object.keys(counts).length} distinct • ${feats.length - vals.length} null`;
    }
    const maxC = Math.max(...bars.map(b => b[1]), 1);
    const rowH = 24, labelW = 230, barW = 440, h = bars.length * rowH + 10;
    const svg = `<svg viewBox="0 0 ${labelW + barW + 60} ${h}" width="100%" style="font-family:'Plus Jakarta Sans',sans-serif;font-size:11px;">
      ${bars.map(([lbl, cnt], i) => {
      const y = i * rowH + 4, bw = Math.max(2, (cnt / maxC) * barW);
      const short = lbl.length > 36 ? lbl.slice(0, 35) + "…" : lbl;
      return `<g><title>${esc(lbl)}: ${cnt}</title>
          <text x="${labelW - 6}" y="${y + 15}" text-anchor="end" fill="#44474e">${esc(short)}</text>
          <rect x="${labelW}" y="${y + 3}" width="${bw}" height="${rowH - 8}" rx="3" fill="${color}" opacity="0.85"></rect>
          <text x="${labelW + bw + 5}" y="${y + 15}" fill="#131b2e" font-weight="700">${cnt.toLocaleString()}</text></g>`;
    }).join("")}
    </svg>`;
    $("chartModalBody").innerHTML = `<div class="text-[11px] font-bold uppercase tracking-wider text-on-surface-variant mb-2">${isNumeric ? "Histogram (10 equal-width bins)" : "Category frequency"} — ${esc(field)}</div>${svg}`;
  }

  // Catalogue picker
  let catalogGeom = "all";
  function renderCatalog() {
    const body = $("catalogModalBody");
    const q = ($("catalogSearchInput").value || "").toLowerCase();
    body.innerHTML = CATALOG.filter(c => (catalogGeom === "all" || c.kind === catalogGeom) && (!q || `${c.title} ${c.theme} ${c.key}`.toLowerCase().includes(q)))
      .map(c => {
        const qa = qaIndex[c.key];
        const on = state[c.key].visible;
        return `<div class="p-3 rounded-lg border ${on ? "border-secondary bg-surface-container-low" : "border-surface-container-high"} flex flex-col gap-1.5">
          <div class="flex items-center gap-2">${swatch(c)}<span class="font-bold text-[12.5px] flex-1">${esc(c.title)}</span>${qaBadge(c.key)}</div>
          <div class="text-[10.5px] text-on-surface-variant">${esc(c.theme)} • ${esc(c.scale)} • ${esc(qa ? qa.provider : "Derived analysis export")}</div>
          <div class="text-[10px] font-mono text-on-surface-variant truncate" title="${esc(qa ? qa.gs_uri : c.path)}">${esc(qa ? (qa.gs_uri || qa.endpoint) : c.path)}</div>
          <div class="flex gap-1.5 pt-1">
            <button type="button" class="btn ${on ? "btn-secondary" : ""} h-7 px-3 text-[11px]" data-cat-toggle="${c.key}">${on ? "✓ On map — Remove" : "+ Add to map"}</button>
            <button type="button" class="btn btn-secondary h-7 px-3 text-[11px]" data-cat-meta="${c.key}">ℹ️ Metadata</button>
          </div></div>`;
      }).join("") || `<div class="text-xs text-on-surface-variant p-3">No layers match.</div>`;
  }

  // ---------- Attribute Table Dock ----------
  const DOCK_ROW_LIMIT = 500;
  let dockRows = [];
  let dockCols = [];

  function refreshDockSelect() {
    const sel = $("dockLayerSelect");
    if (!sel) return;
    const keys = order.filter(k => state[k].data);
    sel.innerHTML = keys.map(k => `<option value="${k}" ${k === dockKey ? "selected" : ""}>${esc(BY_KEY[k].title)}</option>`).join("");
  }

  async function openTable(key, fid) {
    if (!state[key].visible && !state[key].inList) await setVisible(key, true);
    try { await loadData(key); } catch (e) { return; }
    dockKey = key;
    $("attrTableDock").style.display = "block";
    $("btnToggleAttrDock").classList.add("active");
    refreshDockSelect();
    renderLayerControl();
    renderDock();
    if (fid !== undefined) markDockRow(fid, true);
    $("attrTableDock").scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function renderDock() {
    if (!dockKey || !state[dockKey].data) return;
    const feats = state[dockKey].data.features;
    const q = ($("dockSearchInput").value || "").toLowerCase().trim();
    dockCols = [...new Set(feats.flatMap(f => Object.keys(f.properties || {})))].filter(k => !HIDDEN_PROP(k) && !k.startsWith("_oic_"));
    dockRows = q ? feats.filter(f => dockCols.some(c => String(f.properties[c] ?? "").toLowerCase().includes(q))) : feats;
    const shown = dockRows.slice(0, DOCK_ROW_LIMIT);
    $("dockFeatureCountBadge").textContent = `${dockRows.length.toLocaleString()} / ${feats.length.toLocaleString()} rows`;
    const qa = qaIndex[dockKey];
    $("dockLayerSubtitle").textContent = `${BY_KEY[dockKey].title} — ${qa ? qa.gs_uri || qa.endpoint : BY_KEY[dockKey].path}${dockRows.length > DOCK_ROW_LIMIT ? ` (first ${DOCK_ROW_LIMIT} rows shown — refine search)` : ""} • Click a row to zoom & open popup`;
    $("dockTableHead").innerHTML = `<tr><th>#</th><th>Geom</th>${dockCols.map(c => `<th>${esc(c)}</th>`).join("")}</tr>`;
    $("dockTableBody").innerHTML = shown.map(f => {
      const p = f.properties;
      return `<tr class="cursor-pointer" data-fid="${p.__fid}"><td><code>${p.__fid}</code></td><td><code>${esc(((f.geometry && f.geometry.type) || "—").replace("Multi", "M-"))}</code></td>${dockCols.map(c => {
        const raw = p[c] === null || p[c] === undefined ? "" : String(p[c]).replace(/<[^>]*>/g, " ");
        return `<td title="${esc(raw.slice(0, 400))}" style="max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(raw.slice(0, 120))}</td>`;
      }).join("")}</tr>`;
    }).join("") || `<tr><td colspan="${dockCols.length + 2}" class="empty-cell">No rows match the search.</td></tr>`;
  }

  function markDockRow(fid, scroll) {
    const body = $("dockTableBody");
    if (!body) return;
    body.querySelectorAll("tr.selected-row").forEach(tr => tr.classList.remove("selected-row"));
    const tr = body.querySelector(`tr[data-fid="${fid}"]`);
    if (tr) { tr.classList.add("selected-row"); if (scroll) tr.scrollIntoView({ block: "nearest" }); }
  }

  function onDockRowClick(e) {
    const tr = e.target.closest("tr[data-fid]");
    if (!tr || !dockKey) return;
    const f = state[dockKey].data.features[Number(tr.getAttribute("data-fid"))];
    if (!f) return;
    if (!state[dockKey].visible) setVisible(dockKey, true);
    markDockRow(f.properties.__fid);
    zoomToFeature(f);
    map.once("moveend", () => showFeature(dockKey, f, featureAnchor(f), 0));
  }

  function downloadCsv() {
    if (!dockKey || !dockRows.length) return;
    const q = v => `"${String(v === null || v === undefined ? "" : v).replace(/"/g, '""')}"`;
    const lines = [["fid", "geometry_type", ...dockCols].map(q).join(",")]
      .concat(dockRows.map(f => [f.properties.__fid, f.geometry && f.geometry.type, ...dockCols.map(c => f.properties[c])].map(q).join(",")));
    const blob = new Blob([lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${dockKey}_attributes.csv`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  // ---------- Wiring ----------
  function setMode(m) {
    mode = m;
    $("btnModeIdentify").classList.toggle("active", m === "identify");
    $("btnModePan").classList.toggle("active", m === "pan");
    if (m === "pan") closePopup();
    if (map) map.getCanvas().style.cursor = m === "pan" ? "grab" : "";
  }

  function wireUi() {
    const on = (id, ev, fn) => { const el = $(id); if (el) el.addEventListener(ev, fn); };
    on("btnModeIdentify", "click", () => setMode("identify"));
    on("btnModePan", "click", () => setMode("pan"));
    on("btnBasemapMenu", "click", e => { e.stopPropagation(); $("basemapPopover").classList.toggle("hidden"); });
    document.addEventListener("click", e => {
      const pop = $("basemapPopover");
      if (pop && !pop.contains(e.target) && !e.target.closest("#btnBasemapMenu")) pop.classList.add("hidden");
    });
    document.querySelectorAll('input[name="basemapChoice"]').forEach(r => r.addEventListener("change", () => setBasemap(r.value)));
    on("basemapOpacitySlider", "input", e => { $("basemapOpacityVal").textContent = `${e.target.value}%`; setBasemapOpacity(Number(e.target.value) / 100); });
    document.querySelectorAll("[data-zoom-scale]").forEach(b => b.addEventListener("click", () => map && map.fitBounds(EXTENTS[b.getAttribute("data-zoom-scale")], { padding: 30, duration: 700 })));

    on("btnToggleLayerPanel", "click", () => {
      const col = $("layerControlCol"), mapCol = $("mapCanvasCol");
      const hide = !col.classList.contains("hidden");
      col.classList.toggle("hidden", hide);
      mapCol.classList.toggle("lg:col-span-8", !hide);
      mapCol.classList.toggle("lg:col-span-12", hide);
      $("btnToggleLayerPanel").classList.toggle("active", !hide);
      if (map) setTimeout(() => map.resize(), 50);
    });
    on("btnToggleAttrDock", "click", () => {
      const dock = $("attrTableDock");
      if (dock.style.display === "none") {
        const k = dockKey || order.find(x => state[x].visible) || order[0];
        if (k) openTable(k); else { dock.style.display = "block"; $("dockTableBody").innerHTML = `<tr><td class="empty-cell">No layers on the map yet — add a layer first.</td></tr>`; $("btnToggleAttrDock").classList.add("active"); }
      } else { dock.style.display = "none"; $("btnToggleAttrDock").classList.remove("active"); }
    });
    on("btnCloseAttrDock", "click", () => { $("attrTableDock").style.display = "none"; $("btnToggleAttrDock").classList.remove("active"); });
    on("dockLayerSelect", "change", e => openTable(e.target.value));
    on("dockSearchInput", "input", renderDock);
    on("dockTableBody", "click", onDockRowClick);
    on("btnDockOpenMeta", "click", () => dockKey && openMeta(dockKey));
    on("btnDockOpenChart", "click", () => dockKey && openChart(dockKey));
    on("btnDockDownloadCsv", "click", downloadCsv);

    on("layerControlList", "click", onLayerControlAction);
    on("layerControlList", "input", onLayerOpacityInput);
    on("layerFilterInput", "input", renderLayerControl);
    on("btnShowAllLayers", "click", () => { showAll = !showAll; renderLayerControl(); });

    const openCatalog = () => { renderCatalog(); openModal("catalogModal"); };
    on("btnOpenCatalogModal", "click", openCatalog);
    on("btnAddLayerFromSidebar", "click", openCatalog);
    on("catalogSearchInput", "input", renderCatalog);
    document.querySelectorAll("[data-geom-filter]").forEach(b => b.addEventListener("click", () => {
      catalogGeom = b.getAttribute("data-geom-filter");
      document.querySelectorAll("[data-geom-filter]").forEach(x => x.classList.toggle("chip-featured", x === b));
      renderCatalog();
    }));
    on("catalogModalBody", "click", async e => {
      const t = e.target.closest("[data-cat-toggle]");
      const m = e.target.closest("[data-cat-meta]");
      if (t) { const k = t.getAttribute("data-cat-toggle"); if (state[k].visible) removeFromList(k); else await setVisible(k, true, { zoom: true }); renderCatalog(); }
      if (m) openMeta(m.getAttribute("data-cat-meta"));
    });
    on("chartFieldSelect", "change", e => renderChart(e.target.value));
    on("btnToggleAoiMask", "click", toggleAoiMask);
    on("btnOverlayLoadDefault", "click", () => activate(["nsw_water_inundation_areas", "ga_electricity_transmission_lines", "ga_electricity_substations", "nsw_foi_building_complexes"], { fit: EXTENTS.hunter }));

    document.querySelectorAll("[data-close-modal]").forEach(b => b.addEventListener("click", () => closeModal(b.getAttribute("data-close-modal"))));
    document.querySelectorAll(".oic-modal-backdrop").forEach(m => m.addEventListener("click", e => { if (e.target === m) m.classList.remove("open"); }));
    document.addEventListener("keydown", e => { if (e.key === "Escape") document.querySelectorAll(".oic-modal-backdrop.open").forEach(m => m.classList.remove("open")); });
  }

  function attach(mapInstance) {
    map = mapInstance;
    installBasemaps();
    installHighlight();
    installAoiMask();
    map.on("click", handleMapClick);
    map.on("mousemove", e => {
      const r = $("mapCoordReadout");
      if (r) r.textContent = `Lon: ${e.lngLat.lng.toFixed(4)}°E, Lat: ${e.lngLat.lat.toFixed(4)}°`;
      if (mode !== "identify") return;
      const layers = visibleHitLayers();
      const hit = layers.length && map.queryRenderedFeatures([[e.point.x - 6, e.point.y - 6], [e.point.x + 6, e.point.y + 6]], { layers }).length;
      map.getCanvas().style.cursor = hit ? "pointer" : "";
    });
    renderLayerControl();
    if (pending) { const p = pending; pending = null; activate(p.keys, p.opts); }
  }

  // Replace the active layer set (used by query presets). opts.fit = bounds to fit after load.
  async function activate(keys, opts) {
    if (!map) { pending = { keys, opts }; return; }
    closePopup();
    CATALOG.forEach(c => { if (!keys.includes(c.key) && state[c.key].visible) { state[c.key].visible = false; state[c.key].inList = false; applyVisibility(c.key); } });
    order = order.filter(k => keys.includes(k));
    // keys are given top-first
    for (const k of keys.slice().reverse()) await setVisible(k, true);
    order = keys.filter(k => state[k].visible).concat(order.filter(k => !keys.includes(k)));
    applyOrder();
    afterChange();
    if (opts && opts.fit) map.fitBounds(opts.fit, { padding: 30, duration: 700 });
  }

  function clear() {
    closePopup();
    clearAoiMask();
    CATALOG.forEach(c => { state[c.key].visible = false; state[c.key].inList = false; applyVisibility(c.key); });
    order = [];
    dockKey = null;
    if ($("attrTableDock")) $("attrTableDock").style.display = "none";
    if ($("btnToggleAttrDock")) $("btnToggleAttrDock").classList.remove("active");
    afterChange();
  }

  // Bind Step 04 result rows (tr[data-match]) to zoom + popup on a catalogue layer.
  function bindResultsRows(tbody, key, prop) {
    if (!tbody) return;
    tbody.onclick = async e => {
      const tr = e.target.closest("tr[data-match]");
      if (!tr) return;
      tbody.querySelectorAll("tr.selected-row").forEach(r => r.classList.remove("selected-row"));
      tr.classList.add("selected-row");
      const ok = await zoomToFeatureByProp(key, prop, tr.getAttribute("data-match"));
      if (ok) $("panel-map").scrollIntoView({ behavior: "smooth", block: "start" });
    };
  }

  // Register a dynamic or user-uploaded GeoJSON layer into the catalogue & MapLibre
  function registerLayer(config, data) {
    if (!BY_KEY[config.key]) {
      CATALOG.push(config);
      BY_KEY[config.key] = config;
    }
    state[config.key] = {
      data: data || null,
      loading: null,
      visible: false,
      opacity: config.opacity !== undefined ? config.opacity : (config.hollow ? 0.08 : (config.kind === "fill" ? 0.35 : 1)),
      inList: false
    };
    if (data && data.features) {
      data.features.forEach((f, i) => { f.properties = f.properties || {}; f.properties.__fid = i; });
    }
    renderLayerControl();
    return config.key;
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wireUi);
  } else {
    wireUi();
  }

  window.OICLayers = {
    attach,
    activate,
    clear,
    setAoiMask,
    clearAoiMask,
    toggleAoiMask,
    resolveLocalityExtent,
    createSmoothedExtentPolygon,
    createInvertedMaskGeoJSON,
    isAoiMaskEnabled: () => aoiMaskEnabled,
    getCurrentAoiGeometry: () => currentAoiGeometry,
    openMeta,
    openChart,
    openTable,
    zoomToFeatureByProp,
    bindResultsRows,
    registerLayer,
    catalog: CATALOG,
    byKey: BY_KEY,
    loadData,
    getMap: () => map,
    getLayerData: key => (state[key] ? state[key].data : null),
    getState: key => state[key],
    getActiveKeys: () => order.filter(k => state[k] && state[k].visible)
  };
})();
