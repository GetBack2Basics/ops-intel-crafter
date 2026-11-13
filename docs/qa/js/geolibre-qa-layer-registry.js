/*
 * GeoLibre QA Inspector: multi-dataset layer registry and datastore catalog picker.
 * Plan: docs/plans/hydrosheds_acc_con_integration_plan.md (Addenda v3/v4, Sections H and I).
 *
 * Depends on globals from geolibre_qa_inspect.html: map (MapLibre), mapReady, datasetKey,
 * currentMaxFeatures, fitToFeatures, applyViewportLimiter, openModal, closeModal.
 * Zero-mock: every dataset, value and count comes from the live manifest, GCS objects or the
 * upstream service. Failures show an explicit error with the URL that failed.
 */
'use strict';

const QA_BUCKET_URL = 'https://storage.googleapis.com/operational-intelligence-crafter-lake';
const QA_MANIFEST_URL = '../../config/dataset_manifest.json';
const QA_OVERLAY_COLOURS = ['#a855f7', '#22d3ee', '#f97316', '#84cc16', '#ec4899', '#eab308', '#14b8a6', '#f43f5e'];
const QA_KIND_META = {
  vector: { icon: '🔷', badge: 'badge-vector', label: 'Vector' },
  raster: { icon: '🟩', badge: 'badge-raster', label: 'Raster' },
  point_cloud: { icon: '🟠', badge: 'badge-point-cloud', label: 'Point Cloud' },
  table: { icon: '📑', badge: 'badge-table', label: 'Table' }
};
const QA_LOCAL_RAMP = [[0, [255, 255, 204]], [0.25, [161, 218, 180]], [0.5, [65, 182, 196]], [0.75, [44, 127, 184]], [1, [37, 52, 148]]];

const qaState = {
  manifest: {}, manifestError: null, registry: new Map(), kindFilter: 'all',
  activeTab: 'primary', colourIdx: 0, primaryHeadHtml: null, refreshTimer: null
};

function getActiveDockTab() { return qaState.activeTab; }

function qaEsc(s) {
  return String(s === undefined || s === null ? '' : s).replace(/[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function qaName(entry, key) { return (entry && (entry.dataset_name || entry.name)) || key; }

async function qaLoadManifest() {
  const url = new URL(QA_MANIFEST_URL, window.location.href).href;
  try {
    const r = await fetch(url, { cache: 'no-cache' });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const j = await r.json();
    qaState.manifest = j.datasets || {};
  } catch (e) {
    // Fallback cleanly to embedded DATASET_CATALOG if manifest file is not hosted
    if (typeof DATASET_CATALOG !== 'undefined' && DATASET_CATALOG && Object.keys(DATASET_CATALOG).length > 0) {
      qaState.manifest = Object.assign({}, DATASET_CATALOG);
      qaState.manifestError = null;
    } else {
      qaState.manifestError = `${e.message} — ${url}`;
      qaState.manifest = {};
    }
  }
}

/* ---------------- Picker ---------------- */

function toggleDatasetPicker(open) {
  if (open) {
    renderPicker();
    openModal('picker-modal');
    const s = document.getElementById('picker-search-input');
    if (s) s.focus();
  } else {
    closeModal('picker-modal');
  }
}

function setPickerKindFilter(kind, btn) {
  qaState.kindFilter = kind;
  document.querySelectorAll('#picker-kind-pills .filter-pill').forEach(p => p.classList.toggle('active', p === btn));
  renderPicker();
}

function filterPickerDatasets() { renderPicker(); }

function qaStoreBadge(entry) {
  const g = entry.locations && entry.locations.gcs;
  if (g && g.present === true) return '<span class="picker-badge badge-raster">GCS ✓</span>';
  if (g && g.uri) return '<span class="picker-badge badge-state" title="Listed in manifest, presence not yet verified by sync tool">GCS ?</span>';
  if (entry.endpoint) return '<span class="picker-badge badge-state">Live endpoint</span>';
  return '';
}

function renderPicker() {
  const grid = document.getElementById('picker-dataset-grid');
  const badge = document.getElementById('picker-total-badge');
  if (!grid) return;
  if (qaState.manifestError) {
    badge.textContent = 'Unavailable';
    grid.innerHTML = `<div style="color:#f43f5e; font-size:0.8rem;">Datastore manifest unreachable: ${qaEsc(qaState.manifestError)}</div>`;
    return;
  }
  const q = (document.getElementById('picker-search-input').value || '').trim().toLowerCase();
  const st = document.getElementById('picker-state-select').value;
  const keys = Object.keys(qaState.manifest).sort();
  badge.textContent = `${keys.length} Datasets`;
  const shown = keys.filter(k => {
    const e = qaState.manifest[k];
    const kind = e.kind || 'vector';
    if (qaState.kindFilter !== 'all' && kind !== qaState.kindFilter) return false;
    if (st !== 'all' && (e.state || 'national') !== st) return false;
    if (!q) return true;
    return [k, qaName(e, k), e.canonical_theme, e.state, e.source_agency].join(' ').toLowerCase().includes(q);
  });
  grid.innerHTML = shown.map(k => {
    const e = qaState.manifest[k];
    const km = QA_KIND_META[e.kind || 'vector'] || QA_KIND_META.vector;
    let btn;
    if (k === datasetKey) btn = '<button class="picker-btn-add added" disabled>Primary</button>';
    else if (qaState.registry.has(k)) btn = '<button class="picker-btn-add added" disabled>Added ✓</button>';
    else btn = `<button class="picker-btn-add" onclick="addDatasetLayer('${k}')">+ Add</button>`;
    const attribution = e.licence && e.licence.attribution ? `<div style="font-size:0.64rem; color:#64748b;">© ${qaEsc(e.licence.attribution)}</div>` : '';
    return `<div class="picker-card">
      <div>
        <div class="picker-card-title">${km.icon} ${qaEsc(qaName(e, k))}</div>
        <div class="picker-card-key">${qaEsc(k)}</div>
        <div class="picker-card-meta">
          <span class="picker-badge ${km.badge}">${km.label}</span>
          <span class="picker-badge badge-state">${qaEsc((e.state || 'national').toUpperCase())}</span>
          ${e.canonical_theme ? `<span class="picker-badge badge-state">${qaEsc(e.canonical_theme)}</span>` : ''}
          ${qaStoreBadge(e)}
        </div>
        ${attribution}
      </div>
      ${btn}
    </div>`;
  }).join('') || '<div style="color:#94a3b8; font-size:0.8rem;">No datasets match the current filters.</div>';
}

/* ---------------- Registry: add / remove ---------------- */

function qaFirstCoreLayerId() { return map.getLayer('bounds-fill') ? 'bounds-fill' : undefined; }

async function addDatasetLayer(key, allowPrimary) {
  if (!mapReady || qaState.registry.has(key) || (!allowPrimary && key === datasetKey)) return;
  const entry = qaState.manifest[key];
  if (!entry) return;
  const kind = entry.kind || 'vector';
  const rec = {
    key, kind, entry, visible: true, opacity: kind === 'raster' ? 0.8 : 0.9,
    colour: QA_OVERLAY_COLOURS[qaState.colourIdx++ % QA_OVERLAY_COLOURS.length],
    layerIds: [], sourceIds: [], features: [], rows: null, bounds: null,
    status: 'Loading…', error: null, cog: null, legend: null
  };
  qaState.registry.set(key, rec);
  renderLayerCard(rec);
  renderPicker();
  qaUpdateHash();
  try {
    if (kind === 'raster') await qaAddRaster(rec);
    else if (kind === 'point_cloud') qaAddPointCloud(rec);
    else if (kind === 'table') await qaAddTable(rec);
    else await qaAddVector(rec);
  } catch (e) {
    rec.error = e.message;
    rec.status = 'Error';
  }
  renderLayerCard(rec);
  qaRestackLayers();
}

function qaRemoveLayer(key) {
  const rec = qaState.registry.get(key);
  if (!rec) return;
  rec.layerIds.forEach(id => { if (map.getLayer(id)) map.removeLayer(id); });
  rec.sourceIds.forEach(id => { if (map.getSource(id)) map.removeSource(id); });
  const card = document.getElementById(`card-qa-${key}`);
  if (card) card.remove();
  const tab = document.getElementById(`tab-qa-${key}`);
  if (tab) tab.remove();
  qaState.registry.delete(key);
  if (qaState.activeTab === key) switchDockTab('primary');
  qaUpdateHash();
  renderPicker();
}

function qaSetVisible(key, visible) {
  const rec = qaState.registry.get(key);
  if (!rec) return;
  rec.visible = visible;
  rec.layerIds.forEach(id => { if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', visible ? 'visible' : 'none'); });
  if (visible && rec.kind === 'vector' && rec.url !== undefined) qaRefreshVector(rec);
  if (visible && rec.kind === 'raster' && rec.parts) qaLoadVisibleParts(rec);
}

function qaSetOpacity(key, val) {
  const rec = qaState.registry.get(key);
  if (!rec) return;
  rec.opacity = parseFloat(val) / 100.0;
  rec.layerIds.forEach(id => {
    const l = map.getLayer(id);
    if (!l) return;
    if (l.type === 'raster') map.setPaintProperty(id, 'raster-opacity', rec.opacity);
    else if (l.type === 'fill') map.setPaintProperty(id, 'fill-opacity', rec.opacity * 0.35);
    else if (l.type === 'line') map.setPaintProperty(id, 'line-opacity', rec.opacity);
    else if (l.type === 'circle') map.setPaintProperty(id, 'circle-opacity', rec.opacity);
  });
  const lbl = document.getElementById(`opacity-qa-${key}`);
  if (lbl) lbl.textContent = `${Math.round(rec.opacity * 100)}%`;
}

function qaZoomTo(key) {
  const rec = qaState.registry.get(key);
  if (!rec) return;
  if (rec.bounds) map.fitBounds(rec.bounds, { padding: 40, maxZoom: 14 });
  else if (rec.features.length) fitToFeatures(rec.features, 40);
}

/* ---------------- Rasters: split datasets load by viewport from a parts index ---------------- */
// processed/<key>/parts.json is written by tools/build_parts_index.py from the real GCS objects.
// Turning a raster on loads every part that intersects the view; panning loads newly exposed parts.

function qaPartsIndexUrl(key) { return `${QA_BUCKET_URL}/processed/${key}/parts.json`; }

function qaViewBbox() {
  const b = map.getBounds();
  return [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()];
}

function qaBboxIntersects(a, b) { return a[0] <= b[2] && a[2] >= b[0] && a[1] <= b[3] && a[3] >= b[1]; }

async function qaAddRaster(rec) {
  const url = qaPartsIndexUrl(rec.key);
  rec.partsUrl = url;
  const r = await fetch(url, { cache: 'no-cache' });
  if (!r.ok) throw new Error(`Not built yet: no parts index (HTTP ${r.status}) — ${url}`);
  const idx = await r.json();
  rec.parts = (idx.parts || []).filter(p => p && p.id && Array.isArray(p.bbox) && p.bbox.length === 4).sort((a, b) => (a.id === 'national' ? -1 : b.id === 'national' ? 1 : a.id.localeCompare(b.id)));
  if (!rec.parts.length) throw new Error(`Parts index lists no parts — ${url}`);
  rec.loadedParts = new Map();
  const u = rec.parts.reduce((a, p) => [Math.min(a[0], p.bbox[0]), Math.min(a[1], p.bbox[1]),
    Math.max(a[2], p.bbox[2]), Math.max(a[3], p.bbox[3])], [Infinity, Infinity, -Infinity, -Infinity]);
  rec.bounds = [[u[0], u[1]], [u[2], u[3]]];
  await qaLoadVisibleParts(rec);
}

function qaRasterStatus(rec) {
  const view = qaViewBbox();
  const inView = rec.parts.filter(p => qaBboxIntersects(p.bbox, view)).length;
  const states = Array.from(rec.loadedParts.values());
  const failed = states.filter(s => s.error).length;
  const ok = states.length - failed;
  if (!inView && !states.length) return `No parts in view · ${rec.parts.length} available (🎯 to zoom)`;
  const minZooms = states.filter(s => !s.error && typeof s.part.minzoom === 'number').map(s => s.part.minzoom);
  const minZ = minZooms.length ? Math.min(...minZooms) : null;
  const zoomHint = minZ !== null && map.getZoom() < minZ ? ` · zoom in to z${minZ}+ to see tiles` : '';
  return `${ok} of ${rec.parts.length} part(s) loaded, ${inView} in view${failed ? `, ${failed} failed` : ''}${zoomHint} · click for raw value`;
}

async function qaLoadVisibleParts(rec) {
  if (!rec.visible || !rec.parts || rec.loadingParts) return;
  const view = qaViewBbox();
  const todo = rec.parts.filter(p => !rec.loadedParts.has(p.id) && qaBboxIntersects(p.bbox, view));
  if (todo.length) {
    rec.loadingParts = true;
    rec.status = `Loading ${todo.length} part(s) in view…`;
    renderLayerCard(rec);
    await Promise.all(todo.map(p => qaLoadPart(rec, p)));
    rec.loadingParts = false;
    qaRestackLayers();
  }
  const states = Array.from(rec.loadedParts.values());
  const errs = states.filter(s => s.error).map(s => s.error);
  rec.error = errs.length && errs.length === states.length ? errs.join(' | ') : null;
  rec.status = qaRasterStatus(rec);
  renderLayerCard(rec);
}

async function qaLoadPart(rec, part) {
  const state = { id: part.id, part, cog: null, legend: null, error: null };
  rec.loadedParts.set(part.id, state);
  const srcId = `qa-src-${rec.key}-${part.id}`;
  const lyrId = `qa-lyr-${rec.key}-${part.id}`;
  if (part.cog_url && typeof GeoTIFF !== 'undefined') {
    try {
      const tiff = await GeoTIFF.fromUrl(part.cog_url);
      const image = await tiff.getImage();
      state.cog = { tiff, image, nodata: image.getGDALNoData() };
    } catch (e) {
      state.cogError = e.message;
    }
  }
  try {
    if (part.tiles_url_template) {
      if (part.legend_url) {
        try {
          const lr = await fetch(part.legend_url, { cache: 'no-cache' });
          if (lr.ok) state.legend = await lr.json();
        } catch (_) { state.legend = null; }
      }
      map.addSource(srcId, {
        type: 'raster', tiles: [part.tiles_url_template], tileSize: 256, bounds: part.bbox,
        minzoom: typeof part.minzoom === 'number' ? part.minzoom : 0,
        maxzoom: typeof part.maxzoom === 'number' ? part.maxzoom : 12
      });
    } else if (state.cog) {
      state.legend = await qaRenderCogImage(rec, state, srcId);
    } else {
      throw new Error(`part ${part.id}: no display tiles and COG unreadable (${part.cog_url || 'no cog_url'}${state.cogError ? `: ${state.cogError}` : ''})`);
    }
    rec.sourceIds.push(srcId);
    map.addLayer({
      id: lyrId, type: 'raster', source: srcId,
      layout: { visibility: rec.visible ? 'visible' : 'none' },
      paint: { 'raster-opacity': rec.opacity, 'raster-resampling': 'nearest' }
    });
    rec.layerIds.push(lyrId);
    if (!rec.legend && state.legend) { rec.legend = state.legend; rec.legendPart = part.id; }
  } catch (e) {
    state.error = e.message;
  }
}

function qaRampColour(t) {
  const x = Math.max(0, Math.min(1, t));
  for (let i = 1; i < QA_LOCAL_RAMP.length; i++) {
    const [t1, c1] = QA_LOCAL_RAMP[i];
    const [t0, c0] = QA_LOCAL_RAMP[i - 1];
    if (x <= t1) {
      const f = (x - t0) / (t1 - t0 || 1);
      return [0, 1, 2].map(j => Math.round(c0[j] + (c1[j] - c0[j]) * f));
    }
  }
  return QA_LOCAL_RAMP[QA_LOCAL_RAMP.length - 1][1];
}

// Fallback when a part has a COG but no published display tiles: draw it in the browser (p2–p98 stretch).
async function qaRenderCogImage(rec, state, srcId) {
  const img = state.cog.image;
  const w = img.getWidth();
  const h = img.getHeight();
  const scale = Math.min(1, 1600 / Math.max(w, h));
  const ow = Math.max(1, Math.round(w * scale));
  const oh = Math.max(1, Math.round(h * scale));
  const data = (await state.cog.tiff.readRasters({ width: ow, height: oh, samples: [0], resampleMethod: 'nearest' }))[0];
  const nodata = state.cog.nodata;
  const isLog = /_acc_/.test(rec.key);
  const isMask = /streams_mask/.test(rec.key);
  const tf = v => (isLog ? Math.log10(Math.max(v, 1)) : v);
  const valid = v => Number.isFinite(v) && !(nodata !== null && Math.abs(v - nodata) < 1e-6);

  const sample = [];
  const step = Math.max(1, Math.floor(data.length / 50000));
  for (let i = 0; i < data.length; i += step) if (valid(data[i])) sample.push(tf(data[i]));
  if (!sample.length) throw new Error(`COG ${state.part.cog_url} has no valid cells`);
  sample.sort((a, b) => a - b);
  const pick = p => sample[Math.min(sample.length - 1, Math.floor(p * (sample.length - 1)))];
  const lo = isMask ? 0 : pick(0.02);
  const hi = isMask ? 1 : pick(0.98);

  const canvas = document.createElement('canvas');
  canvas.width = ow;
  canvas.height = oh;
  const ctx = canvas.getContext('2d');
  const out = ctx.createImageData(ow, oh);
  for (let i = 0; i < data.length; i++) {
    const v = data[i];
    if (!valid(v) || (isMask && v === 0)) { out.data[i * 4 + 3] = 0; continue; }
    const c = qaRampColour((tf(v) - lo) / ((hi - lo) || 1));
    out.data[i * 4] = c[0]; out.data[i * 4 + 1] = c[1]; out.data[i * 4 + 2] = c[2]; out.data[i * 4 + 3] = 225;
  }
  ctx.putImageData(out, 0, 0);
  const [minX, minY, maxX, maxY] = img.getBoundingBox();
  map.addSource(srcId, {
    type: 'image', url: canvas.toDataURL('image/png'),
    coordinates: [[minX, maxY], [maxX, maxY], [maxX, minY], [minX, minY]]
  });
  return {
    label: qaName(rec.entry, rec.key), units: isLog ? 'log10(upstream cells)' : '',
    stats: { p02: lo, p98: hi, min: sample[0], max: sample[sample.length - 1], valid_cells_sampled: sample.length },
    local: true
  };
}

async function qaProbeRasters(lngLat) {
  const out = [];
  for (const rec of qaState.registry.values()) {
    if (rec.kind !== 'raster' || !rec.visible || !rec.loadedParts) continue;
    for (const state of rec.loadedParts.values()) {
      if (!state.cog) continue;
      const img = state.cog.image;
      const [minX, minY, maxX, maxY] = img.getBoundingBox();
      if (lngLat.lng < minX || lngLat.lng > maxX || lngLat.lat < minY || lngLat.lat > maxY) continue;
      const px = Math.min(img.getWidth() - 1, Math.floor((lngLat.lng - minX) / (maxX - minX) * img.getWidth()));
      const py = Math.min(img.getHeight() - 1, Math.floor((maxY - lngLat.lat) / (maxY - minY) * img.getHeight()));
      const label = rec.parts.length > 1 ? `${qaName(rec.entry, rec.key)} [${state.id}]` : qaName(rec.entry, rec.key);
      try {
        const r = await img.readRasters({ window: [px, py, px + 1, py + 1], samples: [0] });
        const v = r[0][0];
        const isNoData = state.cog.nodata !== null && v === state.cog.nodata;
        out.push({ name: label, value: isNoData ? 'nodata' : (Number.isInteger(v) ? v.toLocaleString() : v.toFixed(3)) });
      } catch (e) {
        out.push({ name: label, value: `read failed: ${e.message}` });
      }
    }
  }
  return out;
}

function qaRefreshAllRasters() {
  qaState.registry.forEach(rec => { if (rec.kind === 'raster' && rec.visible && rec.parts) qaLoadVisibleParts(rec); });
}

/* ---------------- Vector overlays (live ArcGIS REST / WFS, viewport limited) ---------------- */

function qaVectorBudget() {
  const globalCap = currentMaxFeatures === 'all' ? 2000 : (parseInt(currentMaxFeatures, 10) || 500);
  let n = 1; // primary dataset shares the budget
  qaState.registry.forEach(r => { if (r.kind === 'vector' && r.visible) n++; });
  return Math.max(50, Math.floor(globalCap / n));
}

function qaVectorQueryUrl(rec) {
  const ep = rec.entry.endpoint || '';
  const b = map.getBounds();
  const w = b.getWest().toFixed(5), s = b.getSouth().toFixed(5), e = b.getEast().toFixed(5), n = b.getNorth().toFixed(5);
  const budget = qaVectorBudget();
  if (/MapServer|FeatureServer/i.test(ep)) {
    const base = ep.replace(/\?.*$/, '').replace(/\/query$/i, '').replace(/\/+$/, '');
    return `${base}/query?where=1%3D1&geometry=${w},${s},${e},${n}&geometryType=esriGeometryEnvelope` +
      `&spatialRel=esriSpatialRelIntersects&inSR=4326&outSR=4326&outFields=*&f=geojson` +
      `&resultRecordCount=${budget}&maxAllowableOffset=0.0005`;
  }
  if (/\/wfs/i.test(ep)) {
    let typeName = rec.entry.wfs_type_name || rec.entry.typeName || null;
    if (!typeName) {
      try {
        const u = new URL(ep);
        typeName = u.searchParams.get('typeName') || u.searchParams.get('typeNames');
      } catch (_) { typeName = null; }
    }
    if (!typeName) return null;
    return `${ep.split('?')[0]}?service=WFS&version=2.0.0&request=GetFeature&typeNames=${encodeURIComponent(typeName)}` +
      `&outputFormat=application/json&srsName=EPSG:4326&count=${budget}&bbox=${s},${w},${n},${e},urn:ogc:def:crs:EPSG::4326`;
  }
  return null;
}

async function qaAddVector(rec) {
  const ep = rec.entry.endpoint || '';
  if (qaVectorQueryUrl(rec) === null) {
    throw new Error(`Overlay mode supports ArcGIS REST endpoints and WFS endpoints with a typeName. ` +
      `Open it as the primary dataset instead. Endpoint: ${ep}`);
  }
  const srcId = `qa-src-${rec.key}`;
  map.addSource(srcId, { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
  rec.sourceIds.push(srcId);
  const isPoly = ['in', ['geometry-type'], ['literal', ['Polygon', 'MultiPolygon']]];
  const isLine = ['in', ['geometry-type'], ['literal', ['LineString', 'MultiLineString']]];
  const isPoint = ['in', ['geometry-type'], ['literal', ['Point', 'MultiPoint']]];
  const defs = [
    { id: `qa-lyr-${rec.key}-fill`, type: 'fill', filter: isPoly, paint: { 'fill-color': rec.colour, 'fill-opacity': rec.opacity * 0.35 } },
    { id: `qa-lyr-${rec.key}-outline`, type: 'line', filter: isPoly, paint: { 'line-color': rec.colour, 'line-width': 1.6, 'line-opacity': rec.opacity } },
    { id: `qa-lyr-${rec.key}-line`, type: 'line', filter: isLine, paint: { 'line-color': rec.colour, 'line-width': 2.6, 'line-opacity': rec.opacity } },
    { id: `qa-lyr-${rec.key}-point`, type: 'circle', filter: isPoint, paint: { 'circle-color': rec.colour, 'circle-radius': 5, 'circle-stroke-color': '#ffffff', 'circle-stroke-width': 1, 'circle-opacity': rec.opacity } }
  ];
  defs.forEach(d => { map.addLayer({ ...d, source: srcId }); rec.layerIds.push(d.id); });
  rec.url = '';
  await qaRefreshVector(rec);
}

async function qaRefreshVector(rec) {
  if (!rec.visible || !map.getSource(`qa-src-${rec.key}`)) return;
  const url = qaVectorQueryUrl(rec);
  rec.url = url;
  try {
    const r = await fetch(url);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const fc = await r.json();
    if (!fc || !Array.isArray(fc.features)) throw new Error('response is not GeoJSON');
    const feats = fc.features.filter(f => f && f.geometry);
    let rendered = feats;
    if (typeof GeoLibreLayerLimiter !== 'undefined' && GeoLibreLayerLimiter.optimizeFeatureCollection) {
      const b = map.getBounds();
      const opt = GeoLibreLayerLimiter.optimizeFeatureCollection(
        { type: 'FeatureCollection', features: feats },
        { maxFeatures: qaVectorBudget(), sortProperty: 'area_ha', sortOrder: 'desc', bbox: [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()] });
      rendered = opt.optimizedGeoJSON.features;
    }
    rec.features = rendered;
    map.getSource(`qa-src-${rec.key}`).setData({ type: 'FeatureCollection', features: rendered });
    const more = fc.exceededTransferLimit || (fc.properties && fc.properties.exceededTransferLimit);
    rec.error = null;
    rec.status = `${rendered.length.toLocaleString()} shown of ${feats.length.toLocaleString()}${more ? '+' : ''} in view`;
  } catch (e) {
    rec.error = `${e.message} — ${url}`;
    rec.status = 'Error';
  }
  renderLayerCard(rec);
  if (qaState.activeTab === rec.key) switchDockTab(rec.key);
}

function qaRefreshAllVectors() {
  qaState.registry.forEach(rec => { if (rec.kind === 'vector' && rec.visible && rec.url !== undefined) qaRefreshVector(rec); });
}

/* ---------------- Point clouds (footprint + 3D viewer link) ---------------- */

function qaParseWktBounds(wkt) {
  if (!wkt) return null;
  const nums = String(wkt).match(/-?\d+(\.\d+)?\s+-?\d+(\.\d+)?/g);
  if (!nums) return null;
  const pts = nums.map(p => p.trim().split(/\s+/).map(Number));
  const xs = pts.map(p => p[0]), ys = pts.map(p => p[1]);
  return [[Math.min(...xs), Math.min(...ys)], [Math.max(...xs), Math.max(...ys)]];
}

function qaAddPointCloud(rec) {
  rec.viewerUrl = `../../projects/geolibre_cesium_3d_viewer.html?dataset=${encodeURIComponent(rec.key)}`;
  const b = qaParseWktBounds(rec.entry.bounds_wgs84);
  if (!b) {
    rec.status = 'No footprint in manifest (bounds_wgs84 missing) · open in 3D viewer';
    return;
  }
  rec.bounds = b;
  const [[x0, y0], [x1, y1]] = b;
  const srcId = `qa-src-${rec.key}`;
  map.addSource(srcId, { type: 'geojson', data: { type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]] } } });
  rec.sourceIds.push(srcId);
  map.addLayer({ id: `qa-lyr-${rec.key}-footprint`, type: 'line', source: srcId, paint: { 'line-color': '#f59e0b', 'line-width': 2, 'line-dasharray': [2, 2], 'line-opacity': rec.opacity } });
  rec.layerIds.push(`qa-lyr-${rec.key}-footprint`);
  rec.status = 'Footprint only (2D) · open in 3D viewer for points';
}

/* ---------------- Non-spatial tables ---------------- */

function qaRowsFromJson(j) {
  if (Array.isArray(j)) return j;
  if (j && Array.isArray(j.features)) return j.features.map(f => f.properties || {});
  if (j && typeof j === 'object') {
    const arr = Object.values(j).find(v => Array.isArray(v) && v.length && typeof v[0] === 'object');
    if (arr) return arr;
  }
  return null;
}

async function qaAddTable(rec) {
  const g = rec.entry.locations && rec.entry.locations.gcs;
  const url = (g && g.https_url) || rec.entry.endpoint;
  if (!url) throw new Error('Manifest entry has no endpoint or GCS https_url');
  const r = await fetch(url, { cache: 'no-cache' });
  if (!r.ok) throw new Error(`HTTP ${r.status} — ${url}`);
  const rows = qaRowsFromJson(await r.json());
  if (!rows) throw new Error(`Could not find a row array in ${url}`);
  rec.rows = rows;
  rec.status = `${rows.length.toLocaleString()} rows · table only`;
  switchDockTab(rec.key);
}

/* ---------------- Layer cards ---------------- */

function qaLegendHtml(rec) {
  const L = rec.legend;
  if (!L) return '';
  let gradient;
  if (Array.isArray(L.ramp) && L.ramp.length > 1) {
    gradient = L.ramp.map((s, i) => `rgba(${s.rgba[0]},${s.rgba[1]},${s.rgba[2]},${(s.rgba[3] / 255).toFixed(2)}) ${Math.round(i / (L.ramp.length - 1) * 100)}%`).join(', ');
  } else {
    gradient = QA_LOCAL_RAMP.map(([t, c]) => `rgb(${c[0]},${c[1]},${c[2]}) ${Math.round(t * 100)}%`).join(', ');
  }
  const st = L.stats || {};
  const fmt = v => (typeof v === 'number' ? (Math.abs(v) >= 100 ? Math.round(v).toLocaleString() : v.toFixed(2)) : '?');
  const lo = Array.isArray(L.ramp) ? L.ramp[0].value : st.p02;
  const hi = Array.isArray(L.ramp) ? L.ramp[L.ramp.length - 1].value : st.p98;
  return `<div style="height:6px; border-radius:3px; background:linear-gradient(90deg, ${gradient});"></div>
    <div style="display:flex; justify-content:space-between; font-size:0.62rem; color:#94a3b8;">
      <span>${fmt(lo)}</span><span>${qaEsc(L.units || '')}${L.local ? ' (p2–p98)' : ''}${rec.parts && rec.parts.length > 1 && rec.legendPart ? ` · legend: ${qaEsc(rec.legendPart)}` : ''}</span><span>${fmt(hi)}</span>
    </div>`;
}

function renderLayerCard(rec) {
  const list = document.getElementById('active-layers-list');
  if (!list) return;
  let card = document.getElementById(`card-qa-${rec.key}`);
  if (!card) {
    card = document.createElement('div');
    card.className = 'active-layer-card';
    card.id = `card-qa-${rec.key}`;
    // Top of the list draws on top: rasters start at the bottom, vectors and footprints at the top.
    if (rec.kind === 'raster') list.appendChild(card);
    else list.insertBefore(card, list.firstChild);
  }
  const km = QA_KIND_META[rec.kind] || QA_KIND_META.vector;
  const name = qaName(rec.entry, rec.key);
  const canZoom = rec.bounds || rec.features.length;
  const hasTable = rec.kind === 'table' || rec.kind === 'vector';
  const hasMapLayer = rec.layerIds.length > 0;
  const statusColour = rec.error ? '#f43f5e' : '#94a3b8';
  const attribution = rec.entry.licence && rec.entry.licence.attribution;
  card.innerHTML = `
    <div class="active-layer-header">
      <label class="active-layer-title" title="${qaEsc(name)}">
        ${hasMapLayer ? `<input type="checkbox" ${rec.visible ? 'checked' : ''} onchange="qaSetVisible('${rec.key}', this.checked)">` : ''}
        <span>${km.icon} ${qaEsc(name)}</span>
      </label>
      <div class="active-layer-actions">
        ${hasMapLayer ? `<button class="btn-layer-action" title="Move up (draw above)" onclick="qaMoveCard(this, -1)">▲</button>
        <button class="btn-layer-action" title="Move down (draw below)" onclick="qaMoveCard(this, 1)">▼</button>` : ''}
        ${canZoom ? `<button class="btn-layer-action" title="Zoom to extent" onclick="qaZoomTo('${rec.key}')">🎯</button>` : ''}
        ${hasTable ? `<button class="btn-layer-action" title="View table" onclick="switchDockTab('${rec.key}')">📋</button>` : ''}
        ${rec.viewerUrl ? `<a class="btn-layer-action" title="Open 3D viewer" href="${rec.viewerUrl}" target="_blank" style="text-decoration:none;">🧊</a>` : ''}
        <button class="btn-layer-action" title="Remove layer" onclick="qaRemoveLayer('${rec.key}')">✕</button>
      </div>
    </div>
    <div style="font-size:0.64rem; color:${statusColour}; word-break:break-all;">${qaEsc(rec.error || rec.status)}</div>
    ${hasMapLayer ? `<div class="active-layer-slider-row">
      <span>Opacity</span>
      <input type="range" class="active-layer-slider" min="0" max="100" value="${Math.round(rec.opacity * 100)}" oninput="qaSetOpacity('${rec.key}', this.value)">
      <span id="opacity-qa-${rec.key}">${Math.round(rec.opacity * 100)}%</span>
    </div>` : ''}
    ${rec.kind === 'raster' ? qaLegendHtml(rec) : ''}
    ${attribution ? `<div style="font-size:0.6rem; color:#64748b;">© ${qaEsc(attribution)}</div>` : ''}`;
}

/* ---------------- Bottom dock tabs and generic tables ---------------- */

function qaEnsureDockTab(rec) {
  if (document.getElementById(`tab-qa-${rec.key}`)) return;
  const tabs = document.getElementById('dock-tabs');
  if (!tabs) return;
  const km = QA_KIND_META[rec.kind] || QA_KIND_META.vector;
  const tab = document.createElement('div');
  tab.className = 'dock-tab';
  tab.id = `tab-qa-${rec.key}`;
  tab.title = qaName(rec.entry, rec.key);
  const label = qaName(rec.entry, rec.key);
  tab.innerHTML = `<span>${km.icon}</span><span>${qaEsc(label.length > 34 ? label.slice(0, 32) + '…' : label)}</span>`;
  tab.onclick = () => switchDockTab(rec.key);
  tabs.appendChild(tab);
}

function switchDockTab(key) {
  const head = document.getElementById('table-head-row');
  if (head && qaState.primaryHeadHtml === null) qaState.primaryHeadHtml = head.innerHTML;
  const rec = key === 'primary' ? null : qaState.registry.get(key);
  if (key !== 'primary' && !rec) key = 'primary';
  qaState.activeTab = key;
  if (rec) qaEnsureDockTab(rec);
  document.querySelectorAll('#dock-tabs .dock-tab').forEach(t => {
    t.classList.toggle('active', key === 'primary' ? t.id === 'tab-primary-dataset' : t.id === `tab-qa-${key}`);
  });
  const dock = document.getElementById('attr-dock');
  if (dock) dock.style.display = 'flex';
  const btn = document.getElementById('btn-toggle-table');
  if (btn) btn.classList.add('active');
  if (key === 'primary') {
    if (head) head.innerHTML = qaState.primaryHeadHtml;
    applyViewportLimiter();
    return;
  }
  qaRenderGenericTable(rec);
}

function qaTableRows(rec) {
  if (rec.kind === 'table') return (rec.rows || []).map(r => ({ props: r, feature: null }));
  return rec.features.map(f => ({ props: f.properties || {}, feature: f }));
}

function qaRenderGenericTable(rec) {
  const head = document.getElementById('table-head-row');
  const tbody = document.getElementById('table-body');
  const countEl = document.getElementById('table-record-count');
  if (!head || !tbody) return;
  const all = qaTableRows(rec);
  const cols = [];
  all.slice(0, 200).forEach(r => Object.keys(r.props).forEach(k => {
    if (!cols.includes(k) && typeof r.props[k] !== 'object') cols.push(k);
  }));
  const shownCols = cols.slice(0, 14);
  rec.sort = rec.sort || { col: null, dir: 1 };
  const rawFilter = (rec.filter || '').trim();
  let rows = all.slice();
  if (rawFilter) {
    let sqlPred = null;
    if (/^(where\s|select\s)|(=|!=|<>|<=|>=|<|>|\b(in|like|ilike|between|is\s+null|is\s+not\s+null)\b)/i.test(rawFilter)) {
      try { sqlPred = qaCompileWhere(rawFilter).predicate; } catch (_) { sqlPred = null; }
    }
    const sub = rawFilter.toLowerCase();
    rows = sqlPred
      ? all.filter(r => sqlPred(r.props))
      : all.filter(r => shownCols.some(c => String(r.props[c]).toLowerCase().includes(sub)));
  }
  if (rec.sort.col) {
    const c = rec.sort.col, d = rec.sort.dir;
    rows.sort((a, b) => {
      const x = a.props[c], y = b.props[c];
      if (typeof x === 'number' && typeof y === 'number') return (x - y) * d;
      return String(x === undefined ? '' : x).localeCompare(String(y === undefined ? '' : y)) * d;
    });
  }
  head.innerHTML = '';
  shownCols.forEach(c => {
    const th = document.createElement('th');
    th.textContent = c + (rec.sort.col === c ? (rec.sort.dir > 0 ? ' ▲' : ' ▼') : '');
    th.style.cursor = 'pointer';
    th.onclick = () => {
      rec.sort = { col: c, dir: rec.sort.col === c ? -rec.sort.dir : 1 };
      qaRenderGenericTable(rec);
    };
    head.appendChild(th);
  });
  tbody.innerHTML = '';
  const MAX_ROWS = 1000;
  rows.slice(0, MAX_ROWS).forEach(r => {
    const tr = document.createElement('tr');
    shownCols.forEach(c => {
      const td = document.createElement('td');
      const v = r.props[c];
      td.textContent = v === undefined || v === null ? '' : String(v);
      tr.appendChild(td);
    });
    if (r.feature) tr.onclick = () => fitToFeatures([r.feature], 60);
    tbody.appendChild(tr);
  });
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="${Math.max(1, shownCols.length)}" style="text-align:center; color:#94a3b8; padding:1.2rem;">${
      qaEsc(rec.error || (rec.kind === 'table' ? 'No rows match the filter.' : 'No features in the current viewport.'))}</td></tr>`;
  }
  if (countEl) {
    countEl.innerHTML = '';
    const txt = document.createElement('span');
    txt.textContent = `${qaName(rec.entry, rec.key)} — ${rows.length.toLocaleString()} of ${all.length.toLocaleString()} rows` +
      (rows.length > MAX_ROWS ? ` (first ${MAX_ROWS} shown)` : '') + (cols.length > shownCols.length ? ` · ${shownCols.length} of ${cols.length} columns` : '');
    const inp = document.createElement('input');
    inp.placeholder = 'filter…';
    inp.value = rec.filter || '';
    inp.style.cssText = 'margin-left:0.6rem; background:#0f172a; border:1px solid #334155; color:#f8fafc; border-radius:3px; font-size:0.68rem; padding:0.1rem 0.35rem; width:120px;';
    inp.onchange = () => { rec.filter = inp.value; qaRenderGenericTable(rec); };
    const exp = document.createElement('button');
    exp.textContent = '⬇ CSV';
    exp.className = 'btn-layer-action';
    exp.style.marginLeft = '0.4rem';
    exp.onclick = () => qaExportCsv(rec, rows, cols);
    countEl.append(txt, inp, exp);
  }
}

function qaExportCsv(rec, rows, cols) {
  const q = v => {
    const s = v === undefined || v === null ? '' : (typeof v === 'object' ? JSON.stringify(v) : String(v));
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const lines = [cols.map(q).join(',')].concat(rows.map(r => cols.map(c => q(r.props[c])).join(',')));
  const blob = new Blob([lines.join('\n')], { type: 'text/csv' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `${rec.key}.csv`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

/* ---------------- Layer order, minimise and drag ---------------- */

function qaCardLayerIds(card) {
  if (card.dataset.coreGroup && typeof CORE_LAYER_GROUPS !== 'undefined') return CORE_LAYER_GROUPS[card.dataset.coreGroup] || [];
  if (card.id.startsWith('card-qa-')) {
    const rec = qaState.registry.get(card.id.slice('card-qa-'.length));
    return rec ? rec.layerIds : [];
  }
  return [];
}

// Apply the panel order to the map: the top card draws on top. The basemap is never moved, so it stays underneath.
function qaRestackLayers() {
  const list = document.getElementById('active-layers-list');
  if (!list || !mapReady) return;
  Array.from(list.children).reverse().forEach(card => {
    qaCardLayerIds(card).forEach(id => { if (map.getLayer(id)) map.moveLayer(id); });
  });
}

function qaMoveCard(btn, dir) {
  const card = btn.closest('.active-layer-card');
  const list = card && card.parentElement;
  if (!list) return;
  const cards = Array.from(list.children).filter(c => c.style.display !== 'none');
  const i = cards.indexOf(card);
  const j = i + dir;
  if (j < 0 || j >= cards.length) return;
  if (dir < 0) list.insertBefore(card, cards[j]);
  else list.insertBefore(card, cards[j].nextSibling);
  qaRestackLayers();
}

const QA_PANEL_KEY = 'oic.qa.layerPanel';

function qaSavePanelState() {
  const panel = document.getElementById('map-layer-control');
  if (!panel) return;
  try {
    localStorage.setItem(QA_PANEL_KEY, JSON.stringify({
      left: panel.style.left || null, top: panel.style.top || null, minimised: panel.classList.contains('minimised')
    }));
  } catch (_) { /* storage unavailable: position is not remembered */ }
}

function qaToggleLayerPanel(force) {
  const panel = document.getElementById('map-layer-control');
  const btn = document.getElementById('btn-minimise-layers');
  if (!panel) return;
  const min = typeof force === 'boolean' ? force : !panel.classList.contains('minimised');
  panel.classList.toggle('minimised', min);
  if (btn) { btn.textContent = min ? '+' : '–'; btn.title = min ? 'Expand' : 'Minimise'; }
  qaSavePanelState();
}

function qaClampPanel(panel, left, top) {
  const host = panel.offsetParent || document.body;
  const maxL = Math.max(0, host.clientWidth - panel.offsetWidth);
  const maxT = Math.max(0, host.clientHeight - 40);
  panel.style.left = `${Math.min(Math.max(0, left), maxL)}px`;
  panel.style.top = `${Math.min(Math.max(0, top), maxT)}px`;
  panel.style.right = 'auto';
}

function qaInitPanelDrag() {
  const panel = document.getElementById('map-layer-control');
  const handle = document.getElementById('layer-control-drag-handle');
  if (!panel || !handle) return;
  try {
    const s = JSON.parse(localStorage.getItem(QA_PANEL_KEY) || 'null');
    if (s && s.left && s.top) qaClampPanel(panel, parseFloat(s.left), parseFloat(s.top));
    if (s && s.minimised) qaToggleLayerPanel(true);
  } catch (_) { /* ignore corrupt saved state */ }
  let drag = null;
  handle.addEventListener('pointerdown', e => {
    if (e.target.closest('button, input, a, select')) return;
    drag = { dx: e.clientX - panel.offsetLeft, dy: e.clientY - panel.offsetTop };
    handle.setPointerCapture(e.pointerId);
    e.preventDefault();
  });
  handle.addEventListener('pointermove', e => {
    if (drag) qaClampPanel(panel, e.clientX - drag.dx, e.clientY - drag.dy);
  });
  const end = e => {
    if (!drag) return;
    drag = null;
    if (handle.hasPointerCapture(e.pointerId)) handle.releasePointerCapture(e.pointerId);
    qaSavePanelState();
  };
  handle.addEventListener('pointerup', end);
  handle.addEventListener('pointercancel', end);
  handle.addEventListener('dblclick', e => { if (!e.target.closest('button')) qaToggleLayerPanel(); });
}

/* ---------------- Attribute filter: real WHERE-clause evaluation ---------------- */
// Supports: SELECT * FROM <name> WHERE <expr>, or a bare <expr>. Operators: = != <> < <= > >=,
// AND / OR / NOT, parentheses, IN (...), LIKE / ILIKE, BETWEEN a AND b, IS [NOT] NULL.
// Column names are matched case-insensitively against feature properties.
// Returns { predicate, columns } — predicate is null when there is no WHERE clause.

function qaTokenizeSql(src) {
  const tokens = [];
  const re = /\s*(?:(\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|'((?:[^']|'')*)'|"((?:[^"]|"")*)"|([A-Za-z_][\w.]*)|(<=|>=|<>|!=|=|<|>|\(|\)|,))/y;
  let pos = 0;
  while (pos < src.length) {
    if (/^\s*$/.test(src.slice(pos))) break;
    re.lastIndex = pos;
    const m = re.exec(src);
    if (!m) throw new Error(`unexpected character at position ${pos + 1}: "${src.slice(pos).trim().slice(0, 12)}"`);
    pos = re.lastIndex;
    if (m[1] !== undefined) tokens.push({ t: 'num', v: parseFloat(m[1]) });
    else if (m[2] !== undefined) tokens.push({ t: 'str', v: m[2].replace(/''/g, "'") });
    else if (m[3] !== undefined) tokens.push({ t: 'id', v: m[3].replace(/""/g, '"') });
    else if (m[4] !== undefined) tokens.push({ t: 'word', v: m[4] });
    else tokens.push({ t: 'op', v: m[5] });
  }
  return tokens;
}

function qaCompileWhere(sqlText) {
  let sql = String(sqlText || '').trim().replace(/;+\s*$/, '');
  const whereMatch = sql.match(/\bwhere\b/i);
  if (/^select\b/i.test(sql)) {
    if (!whereMatch) return { predicate: null, columns: [] };
    sql = sql.slice(whereMatch.index + whereMatch[0].length);
  } else if (whereMatch && whereMatch.index === 0) {
    sql = sql.slice(whereMatch[0].length);
  }
  if (!sql.trim()) return { predicate: null, columns: [] };
  if (/\b(order\s+by|group\s+by|limit|join|having)\b/i.test(sql)) {
    throw new Error('only a WHERE clause is supported (no ORDER BY, GROUP BY, LIMIT or JOIN)');
  }
  const toks = qaTokenizeSql(sql);
  let i = 0;
  const columns = new Set();
  const peek = () => toks[i];
  const isWord = (w, k = 0) => toks[i + k] && toks[i + k].t === 'word' && toks[i + k].v.toUpperCase() === w;
  const expectOp = v => {
    if (!toks[i] || toks[i].t !== 'op' || toks[i].v !== v) throw new Error(`expected "${v}"${toks[i] ? ` near "${toks[i].v}"` : ' at end'}`);
    i++;
  };

  const getCol = (row, name) => {
    if (Object.prototype.hasOwnProperty.call(row, name)) return row[name];
    const lower = name.toLowerCase();
    const k = Object.keys(row).find(key => key.toLowerCase() === lower);
    return k === undefined ? null : row[k];
  };
  const asNum = v => (typeof v === 'number' ? v : (typeof v === 'string' && v.trim() !== '' && !isNaN(Number(v)) ? Number(v) : null));
  const compare = (a, b) => {
    const x = asNum(a), y = asNum(b);
    if (x !== null && y !== null) return x < y ? -1 : (x > y ? 1 : 0);
    const s = String(a), t = String(b);
    return s < t ? -1 : (s > t ? 1 : 0);
  };

  function operand() {
    const tk = peek();
    if (!tk) throw new Error('unexpected end of expression');
    i++;
    if (tk.t === 'num' || tk.t === 'str') return () => tk.v;
    if (tk.t === 'id') { columns.add(tk.v); return row => getCol(row, tk.v); }
    if (tk.t === 'word') {
      const u = tk.v.toUpperCase();
      if (u === 'NULL') return () => null;
      if (u === 'TRUE') return () => true;
      if (u === 'FALSE') return () => false;
      columns.add(tk.v);
      return row => getCol(row, tk.v);
    }
    if (tk.t === 'op' && tk.v === '(') { const e = orExpr(); expectOp(')'); return e; }
    throw new Error(`unexpected "${tk.v}"`);
  }

  function predicate() {
    const left = operand();
    let negate = false;
    if (isWord('IS')) {
      i++;
      if (isWord('NOT')) { negate = true; i++; }
      if (!isWord('NULL')) throw new Error('expected NULL after IS');
      i++;
      return row => { const v = left(row); return negate ? v !== null && v !== undefined : v === null || v === undefined; };
    }
    if (isWord('NOT') && (isWord('IN', 1) || isWord('LIKE', 1) || isWord('ILIKE', 1) || isWord('BETWEEN', 1))) { negate = true; i++; }
    if (isWord('IN')) {
      i++;
      expectOp('(');
      const items = [operand()];
      while (peek() && peek().t === 'op' && peek().v === ',') { i++; items.push(operand()); }
      expectOp(')');
      return row => {
        const v = left(row);
        if (v === null || v === undefined) return false;
        const hit = items.some(it => compare(v, it(row)) === 0);
        return negate ? !hit : hit;
      };
    }
    if (isWord('LIKE') || isWord('ILIKE')) {
      const ci = isWord('ILIKE');
      i++;
      const pat = operand();
      return row => {
        const v = left(row), p = pat(row);
        if (v === null || v === undefined || p === null) return false;
        const rx = new RegExp('^' + String(p).replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/%/g, '.*').replace(/_/g, '.') + '$', ci ? 'i' : '');
        const hit = rx.test(String(v));
        return negate ? !hit : hit;
      };
    }
    if (isWord('BETWEEN')) {
      i++;
      const lo = operand();
      if (!isWord('AND')) throw new Error('expected AND in BETWEEN');
      i++;
      const hi = operand();
      return row => {
        const v = left(row);
        if (v === null || v === undefined) return false;
        const hit = compare(v, lo(row)) >= 0 && compare(v, hi(row)) <= 0;
        return negate ? !hit : hit;
      };
    }
    const tk = peek();
    if (tk && tk.t === 'op' && ['=', '!=', '<>', '<', '<=', '>', '>='].includes(tk.v)) {
      i++;
      const right = operand();
      const op = tk.v;
      return row => {
        const a = left(row), b = right(row);
        if (a === null || a === undefined || b === null || b === undefined) return false;
        const c = compare(a, b);
        if (op === '=') return c === 0;
        if (op === '!=' || op === '<>') return c !== 0;
        if (op === '<') return c < 0;
        if (op === '<=') return c <= 0;
        if (op === '>') return c > 0;
        return c >= 0;
      };
    }
    return row => Boolean(left(row));
  }

  function notExpr() {
    if (isWord('NOT')) { i++; const e = notExpr(); return row => !e(row); }
    return predicate();
  }
  function andExpr() {
    let e = notExpr();
    while (isWord('AND')) { i++; const l = e, r = notExpr(); e = row => l(row) && r(row); }
    return e;
  }
  function orExpr() {
    let e = andExpr();
    while (isWord('OR')) { i++; const l = e, r = andExpr(); e = row => l(row) || r(row); }
    return e;
  }

  const predicateFn = orExpr();
  if (i < toks.length) throw new Error(`unexpected "${toks[i].v}"`);
  return { predicate: predicateFn, columns: Array.from(columns) };
}

/* ---------------- URL hash state, map interaction, init ---------------- */

function qaUpdateHash() {
  const keys = Array.from(qaState.registry.keys());
  const base = window.location.href.split('#')[0];
  history.replaceState(null, '', keys.length ? `${base}#layers=${keys.join(',')}` : base);
}

function qaOverlayVectorLayerIds() {
  const ids = [];
  qaState.registry.forEach(r => { if (r.kind === 'vector' && r.visible) r.layerIds.forEach(id => { if (map.getLayer(id)) ids.push(id); }); });
  return ids;
}

async function qaOnMapClick(e) {
  const core = ['s3-fill', 's3-line', 'live-points', 'live-line', 'live-fill', 'live-clusters'].filter(id => map.getLayer(id));
  if (core.length && map.queryRenderedFeatures(e.point, { layers: core }).length) return;
  const overlayIds = qaOverlayVectorLayerIds();
  const hits = overlayIds.length ? map.queryRenderedFeatures(e.point, { layers: overlayIds }) : [];
  let html = '';
  if (hits.length) {
    const f = hits[0];
    const key = f.layer.id.replace(/^qa-lyr-/, '').replace(/-(fill|outline|line|point)$/, '');
    const rec = qaState.registry.get(key);
    const props = Object.entries(f.properties || {}).filter(([, v]) => v !== null && v !== '').slice(0, 10);
    html += `<strong>${qaEsc(rec ? qaName(rec.entry, key) : key)}</strong><br>` +
      props.map(([k, v]) => `<span style="color:#94a3b8; font-size:0.72rem;">${qaEsc(k)}:</span> <span style="font-size:0.74rem;">${qaEsc(v)}</span>`).join('<br>');
  }
  const values = await qaProbeRasters(e.lngLat);
  if (values.length) {
    html += (html ? '<hr style="border-color:rgba(255,255,255,0.1);">' : '') +
      `<strong>Raw raster values</strong><br>` +
      values.map(v => `<span style="color:#94a3b8; font-size:0.72rem;">${qaEsc(v.name)}:</span> <span style="color:#34d399; font-weight:600;">${qaEsc(v.value)}</span>`).join('<br>') +
      `<br><span style="color:#64748b; font-size:0.66rem;">${e.lngLat.lat.toFixed(5)}, ${e.lngLat.lng.toFixed(5)} · read from COG via HTTP range</span>`;
  }
  if (html) new maplibregl.Popup({ maxWidth: '340px' }).setLngLat(e.lngLat).setHTML(html).addTo(map);
}

async function qaSyncPrimaryFromManifest() {
  const picker = document.getElementById('dataset-picker-select');
  const keys = Object.keys(qaState.manifest).sort();
  if (picker && keys.length) {
    picker.innerHTML = '';
    keys.forEach(k => {
      const e = qaState.manifest[k];
      const opt = document.createElement('option');
      opt.value = k;
      opt.textContent = `[${(e.state || 'national').toUpperCase()}] ${qaName(e, k)}`;
      if (k === datasetKey) opt.selected = true;
      picker.appendChild(opt);
    });
  }
  const entry = qaState.manifest[datasetKey];
  if (!entry) return;
  const gcs = entry.locations && entry.locations.gcs;
  const ep = entry.endpoint || (gcs && gcs.https_url) || (entry.kind === 'raster' ? qaPartsIndexUrl(datasetKey) : '');
  const storeUri = (entry.storage && entry.storage.s3_path) || (gcs && gcs.uri) ||
    (entry.locations && entry.locations.wherobots && entry.locations.wherobots.uri) || '';
  const name = qaName(entry, datasetKey);
  document.title = `Operational Intelligence Crafter — QA Inspection — ${name}`;
  const pt = document.getElementById('page-title'); if (pt) pt.textContent = document.title;
  const nl = document.getElementById('dataset-name-label'); if (nl) nl.textContent = name;
  const sp = document.getElementById('s3-path-label'); if (sp && storeUri) sp.textContent = storeUri;
  const el = document.getElementById('live-endpoint-label');
  if (el && ep) el.innerHTML = `<a href="${qaEsc(ep)}" target="_blank">${qaEsc(ep)}</a>`;

  if (entry.kind === 'raster' || entry.kind === 'table') {
    await addDatasetLayer(datasetKey, true);
    const rec = qaState.registry.get(datasetKey);
    const badge = document.getElementById('s3-count-badge');
    const tc = document.getElementById('table-record-count');
    const tbody = document.getElementById('table-body');
    if (rec && entry.kind === 'raster') {
      if (rec.bounds) {
        const [[x0, y0], [x1, y1]] = rec.bounds;
        if (typeof setExtentOverlay === 'function') setExtentOverlay([[y0, x0], [y1, x1]]);
        if (!new URLSearchParams(window.location.search).get('bbox')) {
          map.fitBounds(rec.bounds, { padding: 40, maxZoom: 12, duration: 0 });
          await qaLoadVisibleParts(rec);
        }
      }
      const nParts = (rec.parts || []).length;
      if (badge) badge.textContent = rec.error ? 'Error' : `${nParts} Part(s) | COG + XYZ Tiles | Live GCS`;
      if (tc) tc.textContent = rec.error ? rec.error : `${nParts} regional/national raster part(s) registered in parts.json — click map to read raw COG cell values`;
      if (tbody) {
        tbody.innerHTML = (rec.parts || []).map(p => {
          const st = rec.loadedParts && rec.loadedParts.get(p.id);
          const stats = st && st.legend && st.legend.stats;
          const statTxt = stats ? `min=${stats.min.toFixed(2)}, p50=${stats.p50.toFixed(2)}, max=${stats.max.toFixed(2)} (${stats.valid_cells.toLocaleString()} valid cells)` : 'Zoom into region to load stats';
          const kb = p.cog_bytes ? `${(p.cog_bytes / 1024).toFixed(1)} KB` : '';
          return `<tr onclick="map.fitBounds([[${p.bbox[0]},${p.bbox[1]}],[${p.bbox[2]},${p.bbox[3]}]],{padding:40})">` +
            `<td style="color:#38bdf8;font-weight:bold;">${qaEsc(p.id)}</td>` +
            `<td>${qaEsc(name)} [${p.bbox.map(v => v.toFixed(2)).join(', ')}]</td>` +
            `<td style="color:#34d399;font-weight:600;">${qaEsc(statTxt)}</td>` +
            `<td style="color:#cbd5e1;">COG ${qaEsc(kb)}${p.tiles_url_template ? ` · XYZ z${p.minzoom || 8}-${p.maxzoom || 12}` : ''}</td></tr>`;
        }).join('') || `<tr><td colspan="4" style="color:#f43f5e;padding:1rem;">${qaEsc(rec.error || 'No raster parts published yet.')}</td></tr>`;
      }
    } else if (rec && entry.kind === 'table' && badge) {
      badge.textContent = rec.error ? 'Error' : `${(rec.rows || []).length.toLocaleString()} Rows | GCS Table`;
    }
  }
}

async function qaInit() {
  qaInitPanelDrag();
  qaRestackLayers();
  await qaLoadManifest();
  const btn = document.getElementById('btn-add-layer');
  if (btn && qaState.manifestError) btn.title = `Datastore manifest unreachable: ${qaState.manifestError}`;
  map.on('click', qaOnMapClick);
  map.on('moveend', () => {
    if (qaState.refreshTimer) clearTimeout(qaState.refreshTimer);
    qaState.refreshTimer = setTimeout(() => { qaRefreshAllVectors(); qaRefreshAllRasters(); }, 400);
  });
  await qaSyncPrimaryFromManifest();
  const m = window.location.hash.match(/layers=([^&]+)/);
  if (m) {
    for (const key of decodeURIComponent(m[1]).split(',').filter(Boolean)) {
      if (qaState.manifest[key]) await addDatasetLayer(key);
    }
  }
}

Object.assign(window, {
  toggleDatasetPicker, setPickerKindFilter, filterPickerDatasets, addDatasetLayer, qaRemoveLayer,
  qaSetVisible, qaSetOpacity, qaZoomTo, switchDockTab, getActiveDockTab, qaInit,
  qaMoveCard, qaRestackLayers, qaToggleLayerPanel, qaCompileWhere
});

// If map is already loaded before this script evaluated, trigger qaInit now
if (typeof mapReady !== 'undefined' && mapReady && typeof map !== 'undefined' && map) {
  qaInit();
} else if (typeof map !== 'undefined' && map && typeof map.on === 'function') {
  map.on('load', () => { if (typeof qaInit === 'function') qaInit(); });
}
