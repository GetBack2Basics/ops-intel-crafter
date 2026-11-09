# NExT 1 km² Population Representation Comparison Report (Methods A, B & C)

> [!IMPORTANT]
> **Methodological Scope:** This report presents the controlled comparison required by Section 7 of the *Emergency Spatial Intelligence* specification across identical incident geometries in the Lower Hunter study region (`EPSG:7844` stored CRS, `EPSG:3112` metric CRS).

## 1. Tested Population Representations

1. **Method A — NExT Cell-Centroid Point-in-Polygon Baseline (`ST_Contains`)**
   - Converts each 1 km² grid cell (`G1KM_<east_km>_<north_km>`) to its geometric centroid (`ST_Centroid(cell_geom)`).
   - Selects cells where `ST_Contains(incident_geom, cell_centroid)`.
2. **Method B — 1 km² Cell Polygon Footprint Intersection (`ST_Intersects`)**
   - Selects all 1 km² grid cells where `ST_Intersects(incident_geom, cell_geom)`.
   - Explicitly separates **fully contained interior cells** (`ST_Contains(incident_geom, cell_geom)`) from **boundary-straddling cells** (`ST_Intersects AND NOT ST_Contains`), and identifies straddling cells whose centroids fell outside the incident polygon (missed by Method A).
3. **Method C — Area-Weighted Proportional Intersection (`ST_Area(ST_Intersection) / ST_Area(cell)`)**
   - Computes exact metric overlap fraction in `EPSG:3112` (`GDA2020 / Geoscience Australia Lambert`).
   - **Explicit Assumption Warning:** Modelled proportional estimate assuming uniform within-cell population distribution; never reported as an observed headcount.

---

## 2. Controlled Results Across Four Geometry Regimes

| Geometry Regime | Method A: Centroid `ST_Contains` | Method B: Polygon `ST_Intersects` (Full) | Method B: Contained vs Straddling Cells | Method C: Area-Weighted (Modelled)* | Delta (`B - A`) & Centroids Missed | SQL Execution Time |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1. Small Narrow Polygon** *(Levee Overtopping Strip, ~350m × 3.2km)* | **726.8** pop *(2 cells, 2 FOI bldgs)* | **1,926.2** pop *(5 cells, 4 FOI bldgs)* | Contained: `0` cells (`0.0` pop)<br>Straddling: `5` cells (`1,926.2` pop) | **398.5** est* | **+1,199.4** pop (+165.0%)<br>`3` straddling cells missed by Method A | `35.1 ms` |
| **2. Moderate Irregular Polygon** *(Observed NSW Inundation Basin)* | **6,452.0** pop *(23 cells, 14 FOI bldgs)* | **20,989.2** pop *(68 cells, 53 FOI bldgs)* | Contained: `21` cells (`5,891.5` pop)<br>Straddling: `47` cells (`15,097.7` pop) | **7,431.6** est* | **+14,537.2** pop (+225.3%)<br>`45` straddling cells missed by Method A | `52.4 ms` |
| **3. Large Regional Polygon** *(Lower Hunter Multi-SA2 Envelope)* | **83,555.0** pop *(380 cells, 333 FOI bldgs)* | **94,891.6** pop *(455 cells, 381 FOI bldgs)* | Contained: `355` cells (`76,348.5` pop)<br>Straddling: `100` cells (`18,543.1` pop) | **83,578.2** est* | **+11,336.6** pop (+13.6%)<br>`75` straddling cells missed by Method A | `198.6 ms` |
| **4. Linear Corridor Buffer** *(500m Transmission Line Hazard Buffer)* | **6,881.6** pop *(24 cells, 17 FOI bldgs)* | **18,264.6** pop *(65 cells, 46 FOI bldgs)* | Contained: `24` cells (`6,881.6` pop)<br>Straddling: `41` cells (`11,383.0` pop) | **7,626.0** est* | **+11,383.0** pop (+165.4%)<br>`41` straddling cells missed by Method A | `48.9 ms` |

---

## 3. Key Findings & Operational Guidance

1. **Narrow & Linear Hazard Footprints (Regimes 1 & 4):**
   - When a flood levee breach strip or transmission corridor buffer is narrower than the 1 km grid spacing (`< 1,000 m`), **0% to 37% of intersecting cells are fully contained**, and **Method A (centroid `ST_Contains`) systematically misses 60%–66% of intersecting 1 km² cells** whose centroids fall just outside the corridor edge.
   - For narrow corridors, **Method B** should always be reported as an upper-bound precautionary envelope alongside **Method C** (labelled as a uniform-density proportional estimate).
2. **Irregular Riverine Flood Polygons (Regime 2):**
   - Riverine floodplains have high perimeter-to-area ratios (`47` boundary-straddling cells vs `21` interior cells). Reporting only Method A (`6,452.0`) understates the population living within cells touched by floodwater (`20,989.2` in Method B).
3. **Large Regional Envelopes (Regime 3):**
   - As polygon area grows large relative to the 1 km² cell size (`455` cells), interior cells dominate (`355` contained vs `100` straddling), and Method A (`83,555.0`) converges within `0.03%` of Method C (`83,578.2`), while Method B (`94,891.6`) provides the outer boundary buffer (+13.6%).

