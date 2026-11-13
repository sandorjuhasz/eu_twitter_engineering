"""Household income (ONS small-area estimates, FYE 2016, MSOA 2011) per H3 cell (res 8/9/10)
for the London city box.

Each GHS-POP 2015 100 m pixel (same pixels as ../population/build_pop_h3.py) is assigned to the
MSOA its centroid falls in; a cell's income is the population-weighted mean over its pixels, so
cells that straddle MSOA borders mix their MSOAs by where people live.

Outputs:
  msoa_income_2016.csv  one row per MSOA in the box: codes, names, four income measures, CI
  income_h3.csv         city, res, cell, pop, income_total, income_net, income_net_bhc,
                        income_net_ahc, msoa11cd (dominant), share_dominant, greater_london
Re-runnable: downloads the ONS files and MSOA boundaries into raw/ if missing.
"""
import csv
import json
import os
import sys
import urllib.request

import geopandas as gpd
import h3
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "raw")
sys.path.insert(0, os.path.join(HERE, "..", "population"))
from build_pop_h3 import BOXES, get_tile, pixels_in_box  # noqa: E402

ONS_URL = ("https://www.ons.gov.uk/file?uri=/employmentandlabourmarket/peopleinwork/"
           "earningsandworkinghours/datasets/smallareaincomeestimatesformiddlelayersuperoutputareas"
           "englandandwales/financialyearending2016/")
INCOME_FILES = {
    "income_total": "1totalannualincome.csv",
    "income_net": "1netannualincome.csv",
    "income_net_bhc": "1netannualincomebhc.csv",
    "income_net_ahc": "1netannualincomeahc.csv",
}
MSOA_URL = ("https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/msoa/"
            "FeatureServer/0/query")
MSOA_FILE = "msoa_2011_bgc_london_box.geojson"
CITY = "london"
RESOLUTIONS = [8, 9, 10]
GREATER_LONDON = "E12000007"


def fetch(url, path):
    if not os.path.exists(path):
        os.makedirs(RAW, exist_ok=True)
        urllib.request.urlretrieve(url, path)
    return path


def read_income(name, file):
    """Parse one ONS csv: title lines, a header, MSOA rows, a source footer; '£ 27,300 ' -> 27300."""
    path = fetch(ONS_URL + file, os.path.join(RAW, file))
    with open(path, encoding="latin-1") as f:
        rows = [r for r in csv.reader(f) if r and r[0][:3] in ("E02", "W02")]
    num = lambda s: float(s.replace(",", "").strip())
    return pd.DataFrame({
        "msoa11cd": [r[0] for r in rows],
        "msoa11nm": [r[1] for r in rows],
        "lad_name": [r[3] for r in rows],
        "region_cd": [r[4] for r in rows],
        name: [num(r[6]) for r in rows],
        name + "_ci": [num(r[9]) for r in rows],
    })


def read_msoa(lat_min, lat_max, lon_min, lon_max):
    """MSOA 2011 boundaries (generalised, clipped) intersecting the box, paged 1000 at a time."""
    path = os.path.join(RAW, MSOA_FILE)
    if not os.path.exists(path):
        features, offset = [], 0
        while True:
            q = (f"?where=1%3D1&geometry={lon_min},{lat_min},{lon_max},{lat_max}"
                 "&geometryType=esriGeometryEnvelope&inSR=4326&spatialRel=esriSpatialRelIntersects"
                 f"&outFields=MSOA11CD&outSR=4326&orderByFields=MSOA11CD&resultOffset={offset}"
                 "&f=geojson")
            with urllib.request.urlopen(MSOA_URL + q) as r:
                page = json.load(r)["features"]
            features += page
            if len(page) < 1000:
                break
            offset += len(page)
        os.makedirs(RAW, exist_ok=True)
        with open(path, "w") as f:
            json.dump({"type": "FeatureCollection", "features": features}, f)
    gdf = gpd.read_file(path)
    return gdf.rename(columns={"MSOA11CD": "msoa11cd"})[["msoa11cd", "geometry"]]


def main():
    lat_min, lat_max, lon_min, lon_max, tile = BOXES[CITY]

    income = None
    for name, file in INCOME_FILES.items():
        df = read_income(name, file)
        income = df if income is None else income.merge(
            df.drop(columns=["msoa11nm", "lad_name", "region_cd"]), on="msoa11cd")
    msoa = read_msoa(lat_min, lat_max, lon_min, lon_max)
    income = income[income["msoa11cd"].isin(msoa["msoa11cd"])].reset_index(drop=True)
    income.to_csv(os.path.join(HERE, "msoa_income_2016.csv"), index=False)
    print(f"MSOAs in box: {len(msoa)}, with income: {len(income)}, "
          f"in Greater London: {(income['region_cd'] == GREATER_LONDON).sum()}")

    lat, lon, pop = pixels_in_box(get_tile(tile), lat_min, lat_max, lon_min, lon_max)
    px = gpd.GeoDataFrame({"pop": pop}, geometry=gpd.points_from_xy(lon, lat), crs="EPSG:4326")
    px = gpd.sjoin(px, msoa, how="inner", predicate="within").drop(columns="index_right")
    px = px.merge(income, on="msoa11cd")
    print(f"pixels with an MSOA: {len(px)}, pop {px['pop'].sum():,.0f} of {pop.sum():,.0f}")

    measures = list(INCOME_FILES)
    frames = []
    for res in RESOLUTIONS:
        px["cell"] = [h3.latlng_to_cell(p.y, p.x, res) for p in px.geometry]
        for m in measures:
            px["w_" + m] = px[m] * px["pop"]
        cell = px.groupby("cell").agg(pop=("pop", "sum"),
                                      **{"w_" + m: ("w_" + m, "sum") for m in measures})
        for m in measures:
            cell[m] = cell.pop("w_" + m) / cell["pop"]
        dom = (px.groupby(["cell", "msoa11cd", "region_cd"], as_index=False)["pop"].sum()
               .sort_values(["cell", "pop"], ascending=[True, False])
               .drop_duplicates("cell"))
        cell = cell.reset_index().merge(dom.rename(columns={"pop": "pop_dominant"}), on="cell")
        cell["share_dominant"] = cell.pop("pop_dominant") / cell["pop"]
        cell["greater_london"] = cell.pop("region_cd") == GREATER_LONDON
        centres = np.array([h3.cell_to_latlng(c) for c in cell["cell"]])
        inside = ((centres[:, 0] >= lat_min) & (centres[:, 0] <= lat_max)
                  & (centres[:, 1] >= lon_min) & (centres[:, 1] <= lon_max))
        cell = cell[inside & (cell["pop"] > 0)]
        cell.insert(0, "res", res)
        cell.insert(0, "city", CITY)
        frames.append(cell)
        print(f"res {res:2d}: {len(cell):6d} cells, pop {cell['pop'].sum():12,.0f}, "
              f"net income {cell['income_net'].min():,.0f}-{cell['income_net'].max():,.0f}")

    out = pd.concat(frames, ignore_index=True)
    out = out[["city", "res", "cell", "pop"] + measures
              + ["msoa11cd", "share_dominant", "greater_london"]]
    out[measures] = out[measures].round(0).astype(int)
    out["pop"] = out["pop"].round(2)
    out["share_dominant"] = out["share_dominant"].round(3)
    out.to_csv(os.path.join(HERE, "income_h3.csv"), index=False)
    print("wrote income_h3.csv", len(out), "rows")


if __name__ == "__main__":
    main()
