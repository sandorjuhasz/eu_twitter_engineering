# Population per H3 cell (res 8/9/10) for the London, Portland and Amsterdam boxes

## Source
- **Dataset:** JRC Global Human Settlement Layer, GHS-POP, release **R2023A**, version V1-0
- **Epoch:** 2015
- **Resolution / CRS:** 100 m, World Mollweide (ESRI:54009); values = residents per pixel (float)
- **Licence:** CC BY 4.0, (c) European Union. Citation: Schiavina M., Freire S., Carioli A., MacManus K. (2023): GHS-POP R2023A - GHS population grid multitemporal (1975-2030). European Commission, Joint Research Centre (JRC). doi:10.2905/2FF68A52-5B5B-4A22-8F40-C41DA8332CFE
- **Tiles used** (1000 km x 1000 km):
  - London + Amsterdam: https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_POP_GLOBE_R2023A/GHS_POP_E2015_GLOBE_R2023A_54009_100/V1-0/tiles/GHS_POP_E2015_GLOBE_R2023A_54009_100_V1_0_R3_C19.zip
  - Portland: https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_POP_GLOBE_R2023A/GHS_POP_E2015_GLOBE_R2023A_54009_100/V1-0/tiles/GHS_POP_E2015_GLOBE_R2023A_54009_100_V1_0_R4_C9.zip
- Unzipped GeoTIFFs (~42 MB and ~21 MB) go to `raw/` (gitignored; the script downloads them if missing).

## Method (`build_pop_h3.py`)
1. Read a window of the tile covering the city box (WGS84 box projected to Mollweide) plus a 3 km margin.
2. Take every pixel with population > 0, compute its centroid in Mollweide and reproject it to WGS84 (pyproj).
3. Assign each centroid to an H3 cell with `h3.latlng_to_cell` (h3 v4.5) separately at res 8, 9 and 10, and sum population per cell (each pixel goes entirely to one cell; no areal splitting).
4. Keep only cells whose centre (`h3.cell_to_latlng`) lies inside the city box and with pop > 0. Thanks to the margin, edge cells receive all their pixels, including those just outside the box.

Run: `python build_pop_h3.py` (needs rasterio, numpy, pandas, h3>=4, pyproj; downloads tiles if missing; ~6 s).

## Output `pop_h3.csv`
Columns: `city` (amsterdam / london / portland), `res` (8, 9, 10), `cell` (lowercase H3 hex), `pop` (float, persons). One row per non-empty cell. 228,971 rows.

| city | res 8 cells | res 9 cells | res 10 cells | total pop (res 8 / 9 / 10) |
|---|---|---|---|---|
| london | 3,960 | 24,348 | 136,689 | 9,791,703 / 9,792,037 / 9,793,300 |
| portland | 938 | 5,769 | 33,850 | 1,059,658 / 1,056,170 / 1,055,671 |
| amsterdam | 594 | 3,608 | 19,215 | 1,005,851 / 1,006,163 / 1,006,441 |

Totals differ slightly between resolutions because cells straddling the box edge are kept or dropped depending on their centre. Pixel-level check (pixel centroids inside the box): london 9,792,053; portland 1,055,612; amsterdam 1,006,218.

## Sanity check
- **London box: 9.79M** vs Greater London ~8.6M (ONS mid-2015). The box is a rectangle around Greater London, so it also takes in parts of Surrey, Kent, Essex, Hertfordshire and Buckinghamshire; ~1.1M extra is plausible.
- **Amsterdam box: 1.01M** vs Amsterdam municipality ~0.83M (2015). The box also covers Amstelveen, Diemen, part of Zaanstad, Ouder-Amstel and Haarlemmermeer edges; plausible.
- **Portland box: 1.06M** vs Portland city ~0.63M (2015). The box covers Vancouver WA (~0.17M), Beaverton, Milwaukie, Gresham edges etc.; plausible.

## Caveats
- **Res 10 is noisy.** A res-10 cell (~15,000 m2) holds only ~1.5 GHSL pixels, so values depend on which pixel centroids happen to fall in which cell (aliasing; some cells get 0 or 2 pixels). Res 9 (~4.3 pixels) is borderline; res 8 (~74 pixels) is the most reliable.
- GHS-POP is a modelled (dasymetric) product: census/register counts disaggregated to built-up volume from satellite imagery. It is not a direct count; within-district distribution reflects building volume, not occupancy. Input census years differ by country (see `raw/GHS_POP_GLOBE_R2023A_input_metadata.xlsx`).
- Population is residential (night-time), which matches the home-location use case.
- Cells with zero modelled population are absent from the file (treat missing as 0).

## Official national alternatives (robustness, not downloaded)
- **London:** ONS LSOA mid-year population estimates (incl. mid-2015): https://www.ons.gov.uk/peoplepopulationandcommunity/populationandmigration/populationestimates/datasets/lowersuperoutputareamidyearpopulationestimates ; 2011 Census output-area counts (KS101EW) via Nomis: https://www.nomisweb.co.uk/census/2011/ks101ew ; boundaries: https://geoportal.statistics.gov.uk
- **Amsterdam:** CBS Kaart van 100 meter bij 100 meter met statistieken (2015 edition available): https://www.cbs.nl/nl-nl/dossier/nederland-regionaal/geografische-data/kaart-van-100-meter-bij-100-meter-met-statistieken
- **Portland:** US Census 2010 block-level counts (TIGER/Line with demographic data, P1 table): https://www.census.gov/geographies/mapping-files/2010/geo/tiger-data.html ; ACS 5-year 2013-2017 block-group estimates: https://data.census.gov (or NHGIS, https://www.nhgis.org, which requires a free account).
