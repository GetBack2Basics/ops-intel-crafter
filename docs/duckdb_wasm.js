/*
  docs/duckdb_wasm.js
  Client-Side Real DuckDB-Wasm Spatial & Lakehouse Query Runner.

  Zero-Mock Guarantee:
  Executes real analytical queries directly against GeoParquet and GeoJSON snapshots
  using @duckdb/duckdb-wasm WebAssembly engine in the browser.
*/

(function () {
  let db = null;
  let conn = null;
  let isReady = false;
  let isInitializing = false;
  let initError = null;
  let duckdbModule = null;

  const REGISTERED_TABLES = [
    {
      name: "abs_australia_1km_population_grid",
      file: "abs_australia_1km_population_grid.parquet",
      url: "exports/australia_population_grid/result.parquet",
      type: "parquet"
    },
    {
      name: "derived_hunter_1km_population_grid",
      file: "derived_hunter_1km_population_grid.parquet",
      url: "exports/hunter_population_grid_comparison/result.parquet",
      type: "parquet"
    },
    {
      name: "ga_electricity_substations",
      file: "ga_electricity_substations.parquet",
      url: "qa/data/ga_electricity_substations.parquet",
      type: "parquet"
    },
    {
      name: "ga_electricity_transmission_lines",
      file: "ga_electricity_transmission_lines.parquet",
      url: "qa/data/ga_electricity_transmission_lines.parquet",
      type: "parquet"
    },
    {
      name: "nsw_water_inundation_areas",
      file: "nsw_water_inundation_areas.parquet",
      url: "qa/data/nsw_water_inundation_areas.parquet",
      type: "parquet"
    },
    {
      name: "nsw_foi_building_complexes",
      file: "nsw_foi_building_complexes.parquet",
      url: "qa/data/nsw_foi_building_complexes.parquet",
      type: "parquet"
    },
    {
      name: "next_lga_boundaries_asgs2025",
      file: "next_lga_boundaries_asgs2025.parquet",
      url: "qa/data/next_lga_boundaries_asgs2025.parquet",
      type: "parquet"
    },
    {
      name: "next_sa2_boundaries_asgs2021",
      file: "next_sa2_boundaries_asgs2021.parquet",
      url: "qa/data/next_sa2_boundaries_asgs2021.parquet",
      type: "parquet"
    },
    {
      name: "nsw_lga_boundaries",
      file: "nsw_lga_boundaries.parquet",
      url: "qa/data/nsw_lga_boundaries.parquet",
      type: "parquet"
    },
    {
      name: "nsw_rfs_major_incidents_live",
      file: "nsw_rfs_major_incidents_live.parquet",
      url: "qa/data/nsw_rfs_major_incidents_live.parquet",
      type: "parquet"
    },
    {
      name: "ga_major_power_stations",
      file: "ga_major_power_stations.parquet",
      url: "qa/data/ga_major_power_stations.parquet",
      type: "parquet"
    },
    {
      name: "ga_seismic_hazard_pga_10pct",
      file: "ga_seismic_hazard_pga_10pct.parquet",
      url: "qa/data/ga_seismic_hazard_pga_10pct.parquet",
      type: "parquet"
    }
  ];

  async function initDuckDB() {
    if (isReady) return { db, conn };
    if (isInitializing) {
      while (isInitializing) {
        await new Promise(r => setTimeout(r, 60));
      }
      return { db, conn, error: initError };
    }
    isInitializing = true;

    try {
      updateEngineStatus("initializing", "Loading DuckDB-Wasm engine...");
      duckdbModule = await import("https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm@1.28.0/+esm");
      const bundles = duckdbModule.getJsDelivrBundles();
      const bundle = await duckdbModule.selectBundle(bundles);
      const worker = await duckdbModule.createWorker(bundle.mainWorker);
      const logger = new duckdbModule.ConsoleLogger();
      db = new duckdbModule.AsyncDuckDB(logger, worker);
      await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
      conn = await db.connect();

      // Try loading spatial extension
      try {
        await conn.query("INSTALL spatial; LOAD spatial;");
        console.log("[DuckDB-WASM] Spatial extension loaded successfully");
      } catch (spatialErr) {
        console.warn("[DuckDB-WASM] Spatial extension notice (standard GeoJSON/Parquet functions active):", spatialErr);
      }

      // Register Lakehouse tables
      updateEngineStatus("initializing", "Registering Lakehouse Parquet & GeoJSON tables...");
      for (const tbl of REGISTERED_TABLES) {
        try {
          const fileUrl = new URL(tbl.url, window.location.href).href;
          await db.registerFileURL(tbl.file, fileUrl, duckdbModule.DuckDBDataProtocol.HTTP, false);
          if (tbl.type === "parquet") {
            await conn.query(`CREATE OR REPLACE VIEW ${tbl.name} AS SELECT * FROM read_parquet('${tbl.file}');`);
          } else {
            await conn.query(`CREATE OR REPLACE VIEW ${tbl.name} AS SELECT * FROM read_json_auto('${tbl.file}');`);
          }
          console.log(`[DuckDB-WASM] Registered view: ${tbl.name} -> ${tbl.file}`);
        } catch (tblErr) {
          console.warn(`[DuckDB-WASM] Failed to register view ${tbl.name}:`, tblErr);
        }
      }

      isReady = true;
      updateEngineStatus("ready", "DuckDB-WASM (v1.28.0) Ready");
      console.log("[DuckDB-WASM] Engine initialized and connected.");
      return { db, conn };
    } catch (err) {
      console.error("[DuckDB-WASM] Engine initialization failed:", err);
      initError = err;
      updateEngineStatus("error", "DuckDB-WASM Init Failed (Using Snapshot Fallback)");
      return { error: err };
    } finally {
      isInitializing = false;
    }
  }

  function updateEngineStatus(state, label) {
    const badge = document.getElementById("duckdbStatusBadge");
    if (!badge) return;
    badge.textContent = label;
    badge.className = `px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase transition flex items-center gap-1.5 ${
      state === "ready"
        ? "bg-emerald-100 text-emerald-800 border border-emerald-300"
        : state === "initializing"
        ? "bg-amber-100 text-amber-800 border border-amber-300 animate-pulse"
        : state === "running"
        ? "bg-sky-100 text-sky-800 border border-sky-300 animate-pulse"
        : "bg-rose-100 text-rose-800 border border-rose-300"
    }`;
  }

  // Rewrite canonical GCS lake paths to registered virtual tables
  function normalizeSql(sql) {
    if (!sql || typeof sql !== "string") return "";
    let clean = sql;

    // Replace canonical gs:// read_parquet paths with the registered view names
    clean = clean.replace(/read_parquet\s*\(\s*['"]gs:\/\/[^'"]*\/abs_australia_1km_population_grid\/[^'"]*['"]\s*\)/gi, "abs_australia_1km_population_grid");
    clean = clean.replace(/read_parquet\s*\(\s*['"]gs:\/\/[^'"]*\/derived_hunter_1km_population_grid\/[^'"]*['"]\s*\)/gi, "derived_hunter_1km_population_grid");
    clean = clean.replace(/read_parquet\s*\(\s*['"]gs:\/\/[^'"]*\/ga_electricity_substations\/[^'"]*['"]\s*\)/gi, "ga_electricity_substations");
    clean = clean.replace(/read_parquet\s*\(\s*['"]gs:\/\/[^'"]*\/nsw_water_inundation_areas\/[^'"]*['"]\s*\)/gi, "nsw_water_inundation_areas");
    clean = clean.replace(/read_parquet\s*\(\s*['"]gs:\/\/[^'"]*\/nsw_foi_building_complexes\/[^'"]*['"]\s*\)/gi, "nsw_foi_building_complexes");
    clean = clean.replace(/read_parquet\s*\(\s*['"]gs:\/\/[^'"]*\/next_lga_boundaries_asgs2025\/[^'"]*['"]\s*\)/gi, "next_lga_boundaries_asgs2025");
    clean = clean.replace(/read_parquet\s*\(\s*['"]gs:\/\/[^'"]*\/nsw_rfs_major_incidents_live\/[^'"]*['"]\s*\)/gi, "nsw_rfs_major_incidents_live");
    clean = clean.replace(/read_parquet\s*\(\s*['"]gs:\/\/[^'"]*\/ga_major_power_stations\/[^'"]*['"]\s*\)/gi, "ga_major_power_stations");
    clean = clean.replace(/read_parquet\s*\(\s*['"]gs:\/\/[^'"]*\/ga_electricity_transmission_lines\/[^'"]*['"]\s*\)/gi, "ga_electricity_transmission_lines");
    clean = clean.replace(/read_parquet\s*\(\s*['"]gs:\/\/[^'"]*\/ga_seismic_hazard_pga_10pct\/[^'"]*['"]\s*\)/gi, "ga_seismic_hazard_pga_10pct");

    return clean;
  }

  async function executeQuery(rawSql) {
    if (!isReady) {
      await initDuckDB();
    }
    if (!conn) {
      throw new Error(initError ? initError.message : "DuckDB-WASM connection not available");
    }

    const executableSql = normalizeSql(rawSql);
    updateEngineStatus("running", "Executing Query in DuckDB-WASM...");
    const t0 = performance.now();

    try {
      let table;
      try {
        table = await conn.query(executableSql);
      } catch (queryErr) {
        // If a catalog error occurs for a known table, attempt on-demand view creation and retry
        const missingTableMatch = (queryErr.message || "").match(/Table with name (\w+) does not exist/i);
        if (missingTableMatch) {
          const missingName = missingTableMatch[1];
          const tblEntry = REGISTERED_TABLES.find(t => t.name === missingName);
          if (tblEntry && duckdbModule) {
            console.log(`[DuckDB-WASM] Creating missing view on-demand for ${missingName}...`);
            const fileUrl = new URL(tblEntry.url, window.location.href).href;
            try {
              await db.registerFileURL(tblEntry.file, fileUrl, duckdbModule.DuckDBDataProtocol.HTTP, false);
            } catch (regErr) {
              console.warn(`[DuckDB-WASM] registerFileURL error for ${missingName}:`, regErr);
            }
            if (tblEntry.type === "parquet") {
              await conn.query(`CREATE OR REPLACE VIEW ${missingName} AS SELECT * FROM read_parquet('${tblEntry.file}');`);
            } else {
              await conn.query(`CREATE OR REPLACE VIEW ${missingName} AS SELECT * FROM read_json_auto('${tblEntry.file}');`);
            }
            table = await conn.query(executableSql);
          } else {
            throw queryErr;
          }
        } else {
          throw queryErr;
        }
      }
      const elapsedMs = (performance.now() - t0).toFixed(1);
      updateEngineStatus("ready", `DuckDB-WASM (v1.28.0) Ready • ${elapsedMs} ms`);

      const fields = table.schema.fields.map(f => ({
        name: f.name,
        type: String(f.type)
      }));

      const rows = [];
      for (let i = 0; i < table.numRows; i++) {
        const row = table.get(i);
        const obj = {};
        for (const f of fields) {
          const v = row[f.name];
          obj[f.name] = typeof v === "bigint" ? Number(v) : v;
        }
        rows.push(obj);
      }

      return {
        success: true,
        numRows: table.numRows,
        elapsedMs: parseFloat(elapsedMs),
        fields,
        rows
      };
    } catch (err) {
      updateEngineStatus("error", "Query Execution Error");
      throw err;
    }
  }

  window.OICDuckDB = {
    init: initDuckDB,
    executeQuery: executeQuery,
    normalizeSql: normalizeSql,
    isReady: () => isReady,
    registeredTables: () => REGISTERED_TABLES
  };

  // Kick off asynchronous initialization in the background
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      initDuckDB();
    });
  } else {
    initDuckDB();
  }
})();

