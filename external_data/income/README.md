# Household income per H3 cell (res 8/9/10), London box

## Sources
- **Income:** ONS, *Income estimates for small areas, England and Wales: financial year ending 2016* (2015/16),
  MSOA 2011 geography, published 2018. Four model-based measures, mean annual household income in GBP, each
  with a 95% confidence interval:
  - `income_total`: total annual household income
  - `income_net`: net annual household income
  - `income_net_bhc`: net equivalised household income before housing costs
  - `income_net_ahc`: net equivalised household income after housing costs
  Files `1totalannualincome.csv`, `1netannualincome.csv`, `1netannualincomebhc.csv`, `1netannualincomeahc.csv` from
  https://www.ons.gov.uk/employmentandlabourmarket/peopleinwork/earningsandworkinghours/datasets/smallareaincomeestimatesformiddlelayersuperoutputareasenglandandwales
  Licence: Open Government Licence v3.0. Source: Office for National Statistics.
- **Boundaries:** ONS Open Geography Portal, MSOA December 2011, generalised clipped (BGC), feature service
  `MSOA_2011_EW_BGC` (https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/msoa/FeatureServer/0),
  queried for MSOAs intersecting the London box. Contains OS data (c) Crown copyright and database right.
- **Population weights:** GHS-POP 2015 100 m pixels, same pixels and box as `../population/` (see its README).

Downloads go to `raw/` (gitignored); the script fetches them if missing.

## Method (`build_income_h3.py`)
1. Read the four ONS files and the MSOA polygons intersecting the London box (1,182 MSOAs, 983 of them in Greater
   London; the box also covers parts of Surrey, Kent, Essex, Hertfordshire and Buckinghamshire).
2. Assign every GHS-POP pixel centroid (box + 3 km margin) to the MSOA it falls in.
3. Per H3 cell (res 8, 9, 10): income = population-weighted mean of its pixels' MSOA incomes; `msoa11cd` = the MSOA
   holding most of the cell's population, `share_dominant` its share; `greater_london` = dominant MSOA is in the
   London region (E12000007).
4. Keep cells whose centre lies inside the box (as `pop_h3.csv`).

Run: `python build_income_h3.py` (needs geopandas, h3>=4, pandas, numpy, plus the population script's
rasterio and pyproj; ~20 s once the files are downloaded).

## Outputs
- `msoa_income_2016.csv`: one row per MSOA in the box: `msoa11cd`, `msoa11nm`, `lad_name`, `region_cd`, the four
  measures and their `_ci` (width of the 95% interval).
- `income_h3.csv`: `city` (london), `res`, `cell`, `pop`, the four measures (GBP, rounded), `msoa11cd`,
  `share_dominant`, `greater_london`. 164,021 rows.

| res | cells | pop | net income range (GBP) |
|---|---|---|---|
| 8 | 3,958 | 9,748,143 | 28,454 - 88,200 |
| 9 | 24,270 | 9,748,409 | 27,800 - 93,800 |
| 10 | 135,793 | 9,749,664 | 27,800 - 93,800 |

Population is ~44k below `pop_h3.csv` (9.79M): pixels whose centroid falls outside the clipped MSOA polygons
(Thames, reservoirs). Cells with population only, no income, are missing here.

## Caveats
- **Resolution is the MSOA, not the cell.** An MSOA has ~8,000 residents (~5,000-15,000); res 9 / 10 cells only
  inherit and blend MSOA values. Res 10 adds no income detail; it only allows a join at res 10.
- Model-based estimates with wide intervals (often +-20%); rank or quantile use (e.g. income quartiles of home
  cells) is safer than exact values.
- 2015/16 sits inside the tweet window 2013-17; MSOA 2011 boundaries match the estimates.
- London only. Amsterdam (CBS buurt income) and Portland (ACS tract income) are not included.
