/*
 * qa-sources.js — QA Inspector data sources (zero-mock).
 *
 *   OICQaGcs.load(parquetUrl, {limit})  -> reads the canonical GeoParquet partition on GCS
 *       (the same object ingested into Wherobots and referenced by the GeoLibre project file)
 *       with DuckDB-WASM + spatial. Returns { features, totalRows, sourceUrl }.
 *
 *   OICQaLive.loadQldCyclones(kind)     -> queries the live QLD CycloneHistorical MapServer.
 *       kind: 'Fix' | 'Track' | 'Wind areas'. Every cyclone is its own sublayer, so all
 *       matching sublayers are queried and merged. Returns { features, sublayers, failures }.
 *
 * Failures throw / are reported; nothing is substituted.
 */
(function () {
  'use strict';

  const DUCKDB_ESM = 'https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm@1.29.0/+esm';
  let _conn = null;
  let _initPromise = null;

  async function initDuckDB() {
    if (_conn) return _conn;
    if (_initPromise) return _initPromise;
    _initPromise = (async () => {
      const duckdb = await import(DUCKDB_ESM);
      const bundle = await duckdb.selectBundle(duckdb.getJsDelivrBundles());
      const workerUrl = URL.createObjectURL(
        new Blob([`importScripts("${bundle.mainWorker}");`], { type: 'text/javascript' }));
      const worker = new Worker(workerUrl);
      const db = new duckdb.AsyncDuckDB(new duckdb.ConsoleLogger(duckdb.LogLevel.WARNING), worker);
      await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
      URL.revokeObjectURL(workerUrl);
      const conn = await db.connect();
      await conn.query('INSTALL spatial; LOAD spatial;');
      _conn = conn;
      return conn;
    })();
    try { return await _initPromise; } catch (e) { _initPromise = null; throw e; }
  }

  function sqlStr(s) { return `'${String(s).replace(/'/g, "''")}'`; }

  function rowToPlain(row, fields) {
    const o = {};
    fields.forEach(f => {
      let v = row[f];
      if (typeof v === 'bigint') v = Number(v);
      else if (v instanceof Date) v = v.toISOString();
      else if (v !== null && typeof v === 'object' && typeof v.toString === 'function' && !Array.isArray(v)) v = v.toString();
      o[f] = v;
    });
    return o;
  }

  const OICQaGcs = {
    async load(parquetUrl, opts = {}) {
      if (!parquetUrl) throw new Error('No GCS GeoParquet URL registered for this dataset');
      const limit = Math.max(1, opts.limit || 5000);
      const conn = await initDuckDB();
      const src = `read_parquet(${sqlStr(parquetUrl)})`;

      const desc = (await conn.query(`DESCRIBE SELECT * FROM ${src}`)).toArray();
      const geomCol = desc.find(r => String(r.column_name).toLowerCase() === 'geometry')
        || desc.find(r => String(r.column_type).toUpperCase().startsWith('GEOMETRY'));
      if (!geomCol) throw new Error(`No geometry column in ${parquetUrl}`);
      const gName = `"${geomCol.column_name}"`;
      const gExpr = String(geomCol.column_type).toUpperCase().startsWith('GEOMETRY')
        ? gName : `ST_GeomFromWKB(${gName})`;
      const attrCols = desc
        .filter(r => r.column_name !== geomCol.column_name)
        .filter(r => !/^(BLOB|GEOMETRY)/i.test(String(r.column_type)))
        .map(r => r.column_name);

      const totalRows = Number((await conn.query(`SELECT count(*) AS n FROM ${src}`)).toArray()[0].n);
      const sel = attrCols.map(c => `"${c.replace(/"/g, '""')}"`).join(', ');
      const sql = `SELECT ${sel ? sel + ', ' : ''}ST_AsGeoJSON(${gExpr}) AS __geojson FROM ${src} LIMIT ${limit}`;
      const rows = (await conn.query(sql)).toArray();

      const features = [];
      rows.forEach(r => {
        if (!r.__geojson) return;
        features.push({ type: 'Feature', geometry: JSON.parse(r.__geojson), properties: rowToPlain(r, attrCols) });
      });
      return { features, totalRows, sourceUrl: parquetUrl };
    }
  };

  const QLD_CYCLONE_MAPSERVER =
    'https://spatial-gis.information.qld.gov.au/arcgis/rest/services/EventsIncidents/CycloneHistorical/MapServer';

  const OICQaLive = {
    QLD_CYCLONE_MAPSERVER,
    async loadQldCyclones(kind) {
      const meta = await (await fetch(`${QLD_CYCLONE_MAPSERVER}?f=json`)).json();
      const layers = meta.layers || [];
      const parents = {};
      layers.forEach(l => { if (l.subLayerIds) l.subLayerIds.forEach(id => { parents[id] = l.name; }); });
      const targets = layers.filter(l => !l.subLayerIds && l.name.endsWith(`] ${kind}`));
      const features = [], failures = [];
      await Promise.all(targets.map(async l => {
        const url = `${QLD_CYCLONE_MAPSERVER}/${l.id}/query?where=1%3D1&outFields=*&outSR=4326&f=geojson`;
        try {
          const r = await fetch(url);
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          const fc = await r.json();
          if (fc.error) throw new Error(fc.error.message || 'ArcGIS error');
          const group = parents[l.id] || '';
          const yr = (group.match(/\[(\d{4})-/) || [])[1];
          (fc.features || []).forEach(f => {
            if (!f.geometry) return;
            const p = {};
            Object.keys(f.properties || {}).forEach(k => {
              p[k.replace(/[^a-zA-Z0-9_]/g, '_').replace(/^_+|_+$/g, '').toLowerCase()] = f.properties[k];
            });
            p.cyclone_group = group;
            if (yr) p.cyclone_year = Number(yr);
            p.live_sublayer_id = l.id;
            features.push({ type: 'Feature', geometry: f.geometry, properties: p });
          });
        } catch (e) {
          failures.push(`${l.id} ${l.name}: ${e.message}`);
        }
      }));
      return { features, sublayers: targets.length, failures };
    }
  };

  window.OICQaGcs = OICQaGcs;
  window.OICQaLive = OICQaLive;
})();

