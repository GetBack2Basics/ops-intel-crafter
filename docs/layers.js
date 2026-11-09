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

  function createInvertedMaskGeoJSON(geomOrInput) {
    const worldRing = ensureRingWinding([
      [-180, -85],
      [180, -85],
      [180, 85],
      [-180, 85],
      [-180, -85]
    ], false); // Exterior world ring must be counter-clockwise

    if (!geomOrInput) return { type: "FeatureCollection", features: [] };

    let geom = geomOrInput;
    if (typeof geom === "string") {
      const clean = geom.trim().toUpperCase();
      if (clean.startsWith("POLYGON") || clean.startsWith("MULTIPOLYGON")) {
        geom = parseWktPolygon(geom);
      }
    }
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
    let geom = geomOrInput;
    if (typeof geom === "string") {
      const clean = geom.trim().toUpperCase();
      if (clean.startsWith("POLYGON") || clean.startsWith("MULTIPOLYGON")) {
        geom = parseWktPolygon(geom);
      }
    }
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
      updateMaskButtonUi();
    }
  }

  function setAoiMask(geomOrInput) {
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
    getLayerData: key => (state[key] ? state[key].data : null),
    getState: key => state[key],
    getActiveKeys: () => order.filter(k => state[k] && state[k].visible)
  };
})();
